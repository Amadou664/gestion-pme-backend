import io
from datetime import datetime
from django.db.models import Sum, F, DecimalField, Q
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth import authenticate

# Rest Framework
from rest_framework import status, viewsets, generics, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.permissions import IsAuthenticated

# ReportLab pour le PDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

from .models import User, Article, Client, Vente, Depense, Commande
from .serializers import (
    EntrepriseRegistrationSerializer, 
    ArticleSerializer, 
    ClientSerializer, 
    VenteSerializer,
    DepenseSerializer,
    CommandeSerializer
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

class CommandeViewSet(viewsets.ModelViewSet):
    serializer_class = CommandeSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOfEntreprise]

    def get_queryset(self):
        # L'utilisateur ne voit que les commandes de son entreprise
        return Commande.objects.filter(entreprise=self.request.user.entreprise)

    def perform_create(self, serializer):
        # On injecte l'entreprise et le vendeur automatiquement au moment de l'enregistrement
        serializer.save(
            entreprise=self.request.user.entreprise,
            vendeur=self.request.user
        )

    @action(detail=True, methods=['post'], url_path='solder')
    @transaction.atomic
    def solder(self, request, pk=None):
        print(f"\n--- TENTATIVE DE SOLDER LA COMMANDE ID: {pk} ---")
        
        # 1. On cherche la commande sans le filtre get_object pour voir si elle existe vraiment
        commande = Commande.objects.filter(pk=pk).first()
        
        if not commande:
            print(f"❌ ERREUR: La commande {pk} n'existe pas en base de données.")
            return Response({'error': 'Commande introuvable.'}, status=404)

        # 2. Vérification de l'entreprise (Le problème vient souvent d'ici)
        if commande.entreprise != request.user.entreprise:
            print(f"❌ ERREUR PERMISSION: Cette commande appartient à l'entreprise ID {commande.id}")
            print(f"   L'utilisateur connecté appartient à l'entreprise ID {request.user.entreprise.id if request.user.entreprise else 'NULL'}")
            return Response({'error': 'Accès interdit à cette entreprise.'}, status=403)

        # 3. Vérification du statut
        if commande.statut == 'livree':
            return Response({'error': 'Cette commande est déjà soldée.'}, status=400)

        try:
            # 4. Création de la Vente (Vérifie que ton modèle Vente a bien ces champs)
            vente = Vente.objects.create(
                entreprise=commande.entreprise,
                vendeur=request.user,
                nom_client_libre=commande.nom_client,
                telephone_client_libre=commande.telephone_client,
                total_ttc=commande.total_commande,
                mode_paiement='especes',
                statut='payee'
            )
            
            # 5. Mise à jour de la commande
            commande.statut = 'livree'
            commande.save()
            
            print(f"✅ SUCCÈS: Commande {pk} soldée, Vente {vente.id} créée.")
            return Response({
                'status': 'success',
                'message': f"Commande soldée. Vente n°{vente.id} générée."
            })

        except Exception as e:
            print(f"🔥 ERREUR CRITIQUE: {str(e)}")
            return Response({'error': str(e)}, status=500)

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
    # On passe les objets via save(), le serializer s'occupera du reste
        serializer.save(
            entreprise=self.request.user.entreprise, 
            vendeur=self.request.user,
            statut='payee'
            # Suppression de nom_client_libre ici car il est déjà dans validated_data
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

        # --- LOGIQUE D'AFFICHAGE DU TÉLÉPHONE (AJOUT) ---
        # On suppose que vous avez un champ 'telephone_client_libre' sur votre modèle Vente
        # ou que vous le récupérez via l'objet client
        telephone_final = ""
        if hasattr(vente, 'telephone_client_libre') and vente.telephone_client_libre:
            telephone_final = vente.telephone_client_libre
        elif vente.client and hasattr(vente.client, 'telephone'):
            telephone_final = vente.client.telephone

        # --- EN-TÊTE ---
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, height - 50, f"{vente.entreprise.nom.upper()}")
        
        p.setFont("Helvetica", 10)
        p.drawString(50, height - 65, f"Date: {vente.date_vente.strftime('%d/%m/%Y %H:%M')}")
        p.drawString(50, height - 80, f"Facture N°: #{str(vente.numero_sequentiel).zfill(4)}")
        
        # --- SECTION CLIENT MISE À JOUR ---
        p.setFont("Helvetica-Bold", 11)
        p.drawString(350, height - 65, f"CLIENT: {nom_client_final}") 
        
        # Affichage du numéro si disponible
        if telephone_final:
            p.setFont("Helvetica", 10)
            p.drawString(350, height - 80, f"Tél: {telephone_final}")
        
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
        vente_filtres = Q(entreprise=ent) & ~Q(statut='annulee') 
        depense_filtres = Q(entreprise=ent) 
        commande_filtres = Q(entreprise=ent) & ~Q(statut='livree') # Nouveau filtre pour les acomptes

        try:
            if start_date_str:
                vente_filtres &= Q(date_vente__date__gte=start_date_str)
                depense_filtres &= Q(date_depense__gte=start_date_str)
                # On filtre les acomptes par date de création de la commande
                commande_filtres &= Q(date_commande__date__gte=start_date_str)
            if end_date_str:
                vente_filtres &= Q(date_vente__date__lte=end_date_str)
                depense_filtres &= Q(date_depense__lte=end_date_str)
                commande_filtres &= Q(date_commande__date__lte=end_date_str)
        except ValueError:
            return Response({"erreur": "Format date invalide"}, status=400)
        
        # 1. Calcul CA et CMV (Ventes directes)
        vente_data = Vente.objects.filter(vente_filtres).aggregate(
            total_ca=Sum('total_ttc', output_field=DecimalField()),
            total_cmv=Sum(F('lignes__quantite') * F('lignes__article__prix_achat'), output_field=DecimalField())
        )
        
        # 2. Calcul des Dépenses
        total_depense = Depense.objects.filter(depense_filtres).aggregate(s=Sum('montant'))['s'] or 0
        
        # 3. NOUVEAU : Calcul des Acomptes (Commandes de meubles)
        total_acomptes = Commande.objects.filter(commande_filtres).aggregate(s=Sum('acompte_verse'))['s'] or 0

        # --- LOGIQUE FINANCIÈRE ---
        total_ca = vente_data['total_ca'] or 0
        total_cmv = vente_data['total_cmv'] or 0
        marge_brute = total_ca - total_cmv
        
        # Le bénéfice net inclut maintenant les acomptes (argent encaissé) 
        # moins les dépenses.
        benefice_net = (marge_brute + total_acomptes) - total_depense

        return Response({
            'chiffre_affaires': float(total_ca),
            'marge_brute': float(marge_brute),
            'total_depenses': float(total_depense),
            'total_acomptes': float(total_acomptes), # <--- Envoyé à Flutter
            'benefice_net': float(benefice_net),
            'devise': ent.devise
        })
    
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_avatar(request):
    """
    Met à jour le logo de l'entreprise de l'utilisateur connecté.
    """
    user = request.user
    if not user.entreprise:
        return Response({"error": "Utilisateur sans entreprise"}, status=400)

    logo = request.FILES.get('logo')
    if logo:
        user.entreprise.logo = logo
        user.entreprise.save()
        # On construit l'URL complète pour le retour à Flutter
        logo_url = user.entreprise.logo.url

        return Response({"message": "Logo mis à jour", "entreprise_logo": logo_url})
    
    return Response({"error": "Aucun fichier fourni"}, status=400)

@api_view(['POST', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_business_name(request):
    """
    Modifie le nom de l'entreprise.
    """
    user = request.user
    nouveau_nom = request.data.get('nom')

    if not nouveau_nom:
        return Response({"error": "Le nom est requis"}, status=400)

    if user.entreprise:
        user.entreprise.nom = nouveau_nom
        user.entreprise.save()
        return Response({"message": "Nom de l'entreprise mis à jour", "nom": nouveau_nom})
    
    return Response({"error": "Entreprise introuvable"}, status=404)