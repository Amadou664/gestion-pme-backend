import io
from datetime import datetime
from django.db.models import Sum, F, DecimalField, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth import authenticate

# Rest Framework
from rest_framework import status, viewsets, generics, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.permissions import IsAuthenticated

# ReportLab pour le PDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

from .models import User, Article, Client, Vente, Depense
from .serializers import (
    EntrepriseRegistrationSerializer, 
    ArticleSerializer, 
    ClientSerializer, 
    VenteSerializer,
    DepenseSerializer
)

# --- PERMISSIONS ---

class IsOwnerOfEntreprise(permissions.BasePermission):
    """
    Permission pour s'assurer que l'utilisateur n'accède qu'aux données 
    liées à son entreprise.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.entreprise is not None

    def has_object_permission(self, request, view, obj):
        return obj.entreprise == request.user.entreprise

# --- AUTHENTIFICATION ---

class CustomAuthToken(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        login_id = request.data.get('email') or request.data.get('username')
        password = request.data.get('password')
        user = authenticate(username=login_id, password=password)

        if user:
            token, _ = Token.objects.get_or_create(user=user)
            ent = user.entreprise 
            
            logo_url = None
            if ent and ent.logo:
                logo_url = request.build_absolute_uri(ent.logo.url)

            return Response({
                'token': token.key,
                'user_id': user.pk,
                'email': user.email,
                'role': getattr(user, 'role', 'admin'),
                'entreprise_id': ent.id if ent else None,
                'entreprise_nom': ent.nom if ent else "Admin",
                'entreprise_logo': logo_url,
                'devise': ent.devise if ent else "EUR",
            })
        return Response({'error': 'Identifiants invalides'}, status=400)
    
class RegisterEntrepriseView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = EntrepriseRegistrationSerializer

# --- CRUD VIEWSETS ---

class ArticleViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOfEntreprise]
    serializer_class = ArticleSerializer

    def get_queryset(self):
        return Article.objects.filter(entreprise=self.request.user.entreprise)
    
    def perform_create(self, serializer):
        serializer.save(entreprise=self.request.user.entreprise)

class ClientViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOfEntreprise]
    serializer_class = ClientSerializer

    def get_queryset(self):
        return Client.objects.filter(entreprise=self.request.user.entreprise).order_by('nom')
    
    def perform_create(self, serializer):
        serializer.save(entreprise=self.request.user.entreprise)

class VenteViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOfEntreprise]
    serializer_class = VenteSerializer
    
    def get_queryset(self):
        # On définit la base du queryset
        queryset = Vente.objects.filter(entreprise=self.request.user.entreprise)\
                            .select_related('client', 'vendeur')\
                            .prefetch_related('lignes__article')\
                            .order_by('-date_vente')
    
        # ON APPLIQUE LE FILTRE AVANT LE RETURN
        date_param = self.request.query_params.get('date')
        if date_param:
            queryset = queryset.filter(date_vente__date=date_param)
                
        return queryset
    
    def perform_create(self, serializer):
        # On retire la boucle "for article.stock -= ..." d'ici 
        # car elle est déjà dans serializers.py
        serializer.save(
            entreprise=self.request.user.entreprise, 
            vendeur=self.request.user,
            statut='payee',
            nom_client_libre=self.request.data.get('nom_client_libre')
        )

    @action(detail=True, methods=['post'])
    def annuler(self, request, pk=None):
        """Action pour annuler une vente et remettre les produits en stock"""
        vente = self.get_object()
        
        if vente.statut == 'annulee':
            return Response({'error': 'Cette vente est déjà annulée'}, status=400)
        
        # --- LOGIQUE : REMETTRE EN STOCK ---
        for ligne in vente.lignes.all():
            article = ligne.article
            article.stock += ligne.quantite  # On rajoute ce qui avait été vendu
            article.save()
            
        vente.statut = 'annulee'
        vente.save()
        
        return Response({'status': 'Vente annulée et stock mis à jour'})
    
    @action(detail=True, methods=['get'], 
            authentication_classes=[SessionAuthentication, TokenAuthentication],
            permission_classes=[IsAuthenticated])
    def facture_pdf(self, request, pk=None):
        vente = self.get_object() 
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # --- LOGIQUE D'AFFICHAGE DU NOM ---
        # 1. On vérifie s'il y a un nom saisi manuellement
        # 2. Sinon on prend le nom du client lié (base de données)
        # 3. Sinon "Client Passant"
        if vente.nom_client_libre:
            nom_client_final = vente.nom_client_libre
        elif vente.client:
            nom_client_final = vente.client.nom
        else:
            nom_client_final = "Client Passant"

        # --- EN-TÊTE ---
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, height - 50, f"{vente.entreprise.nom.upper()}")
        
        p.setFont("Helvetica", 10)
        p.drawString(50, height - 65, f"Date: {vente.date_vente.strftime('%d/%m/%Y %H:%M')}")
        p.drawString(50, height - 80, f"Facture N°: #{str(vente.numero_sequentiel).zfill(4)}")
        
        # --- CLIENT ---
        p.setFont("Helvetica-Bold", 11)
        p.drawString(350, height - 65, f"CLIENT: {nom_client_final}") # Utilisation du nom dynamique
        
        p.line(50, height - 100, width - 50, height - 100)

        # --- TABLEAU (Entêtes) ---
        y = height - 130
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y, "Désignation")
        p.drawString(280, y, "P.U.")
        p.drawString(380, y, "Qté")
        p.drawString(480, y, "Total")
        p.line(50, y - 5, width - 50, y - 5)
        
        # --- LIGNES DE VENTE ---
        p.setFont("Helvetica", 10)
        for ligne in vente.lignes.all():
            y -= 25
            if y < 100:
                p.showPage()
                y = height - 50
            p.drawString(50, y, f"{ligne.article.nom[:35]}")
            p.drawString(280, y, f"{ligne.article.prix_vente}")
            p.drawString(380, y, f"{ligne.quantite}")
            p.drawString(480, y, f"{ligne.sous_total}")

        # --- TOTAL EN BAS ---
        y -= 40
        p.line(350, y + 10, width - 50, y + 10)
        p.setFont("Helvetica-Bold", 14)
        p.drawString(350, y, f"TOTAL À PAYER :")
        p.drawString(480, y, f"{vente.total_ttc} {vente.entreprise.devise}")

        # --- PIED DE PAGE ---
        p.setFont("Helvetica-Oblique", 9)
        p.drawCentredString(width / 2, 50, "Merci de votre confiance ! À très bientôt.")
        p.drawCentredString(width / 2, 35, "NB: Les marchandises vendues ne sont ni reprises ni échangées.")
        
        p.showPage()
        p.save()
        buffer.seek(0)
        
        return FileResponse(buffer, as_attachment=False, filename=f'Facture_{vente.id}.pdf')
    
class DepenseViewSet(viewsets.ModelViewSet):
    serializer_class = DepenseSerializer
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise]

    def get_queryset(self):
        # On ne voit que les dépenses de son entreprise
        return Depense.objects.filter(entreprise=self.request.user.entreprise)

    def perform_create(self, serializer):
        # ACTION CRUCIALE : On injecte l'entreprise et l'utilisateur ici
        serializer.save(
            entreprise=self.request.user.entreprise,
            declaree_par=self.request.user
        )

# --- REPORTING (CORRIGÉ POUR L'ACTUALISATION) ---

class ReportingViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, IsOwnerOfEntreprise]

    @action(detail=False, methods=['get'], url_path='financial-summary')
    def financial_summary(self, request):
        ent = request.user.entreprise
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        
        # Filtres de base
        # On ajoute : exclusion des ventes annulées
        vente_filtres = Q(entreprise=ent) & ~Q(statut='annulee') 
        depense_filtres = Q(entreprise=ent) 

        try:
            if start_date_str:
                # Filtrage précis sur la DATE uniquement
                vente_filtres &= Q(date_vente__date__gte=start_date_str)
                depense_filtres &= Q(date_depense__gte=start_date_str)
            if end_date_str:
                vente_filtres &= Q(date_vente__date__lte=end_date_str)
                depense_filtres &= Q(date_depense__lte=end_date_str)
        except ValueError:
            return Response({"erreur": "Format date invalide"}, status=400)
        
        # Calcul du CA et du coût des marchandises vendues (CMV)
        vente_data = Vente.objects.filter(vente_filtres).aggregate(
            total_ca=Sum('total_ttc', output_field=DecimalField()),
            total_cmv=Sum(F('lignes__quantite') * F('lignes__article__prix_achat'), output_field=DecimalField())
        )
        
        total_ca = vente_data['total_ca'] or 0
        total_cmv = vente_data['total_cmv'] or 0
        total_depense = Depense.objects.filter(depense_filtres).aggregate(s=Sum('montant'))['s'] or 0
        
        marge_brute = total_ca - total_cmv
        benefice_net = marge_brute - total_depense

        return Response({
            'chiffre_affaires': float(total_ca),
            'marge_brute': float(marge_brute),
            'total_depenses': float(total_depense),
            'benefice_net': float(benefice_net),
            'devise': ent.devise
        })