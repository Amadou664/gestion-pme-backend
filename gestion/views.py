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
from reportlab.lib.pagesizes import mm, A4
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
import requests

from .models import User, Article, Client, Vente, Depense, Commande, SyncBucket
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
        # 1. On récupère la base
        queryset = Vente.objects.filter(entreprise=self.request.user.entreprise)\
                        .exclude(statut='annulee')\
                        .select_related('client', 'vendeur')\
                        .prefetch_related('lignes__article')\
                        .order_by('-date_vente')
    
        # 2. Filtrage par date (Correction du décalage possible)
        date_param = self.request.query_params.get('date')
        if date_param:
            # On filtre explicitement sur la partie 'date' du champ DateTime
            queryset = queryset.filter(date_vente__date=date_param)
            
        # 3. Filtrage par client (Optionnel, mais aide ton code Flutter)
        client_id = self.request.query_params.get('client')
        if client_id:
            queryset = queryset.filter(client_id=client_id)
                
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

        # --- 1. CONFIGURATION DU FORMAT TICKET ---
        # Largeur standard 80mm. 
        # Hauteur dynamique : 100mm de base + 15mm par article pour éviter de couper le papier trop tôt
        width_ticket = 80 * mm
        height_ticket = (120 + (vente.lignes.count() * 15)) * mm 
        
        # On crée le canvas avec cette taille personnalisée
        p = canvas.Canvas(buffer, pagesize=(width_ticket, height_ticket))
        
        # --- LOGIQUE DE NOM & TEL (Gardée de ton code) ---
        nom_client_final = vente.nom_client_libre or (vente.client.nom if vente.client else "Client Passant")
        telephone_final = getattr(vente, 'telephone_client_libre', "") or (vente.client.telephone if vente.client else "")

        # --- EN-TÊTE (Centré pour le ticket) ---
        p.setFont("Helvetica-Bold", 12)
        p.drawCentredString(width_ticket / 2, height_ticket - 15 * mm, f"{vente.entreprise.nom.upper()}")

        # Logo entreprise (si disponible)
        if vente.entreprise and vente.entreprise.logo:
            try:
                logo_url = request.build_absolute_uri(vente.entreprise.logo.url)
                resp = requests.get(logo_url, timeout=5)
                if resp.status_code == 200 and resp.content:
                    logo_img = ImageReader(io.BytesIO(resp.content))
                    p.drawImage(
                        logo_img,
                        5 * mm,
                        height_ticket - 20 * mm,
                        width=10 * mm,
                        height=10 * mm,
                        preserveAspectRatio=True,
                        mask='auto',
                    )
            except Exception:
                pass
        
        p.setFont("Helvetica", 8)
        p.drawCentredString(width_ticket / 2, height_ticket - 22 * mm, f"Date: {vente.date_vente.strftime('%d/%m/%Y %H:%M')}")
        p.drawCentredString(width_ticket / 2, height_ticket - 27 * mm, f"Reçu N°: #{str(vente.numero_sequentiel).zfill(4)}")
        
        # Infos Client
        p.line(5 * mm, height_ticket - 32 * mm, width_ticket - 5 * mm, height_ticket - 32 * mm)
        p.setFont("Helvetica-Bold", 9)
        p.drawString(7 * mm, height_ticket - 38 * mm, f"CLIENT: {nom_client_final[:25]}")
        if telephone_final:
            p.setFont("Helvetica", 8)
            p.drawString(7 * mm, height_ticket - 43 * mm, f"Tél: {telephone_final}")

        # --- TABLEAU (Entêtes plus serrées) ---
        y = height_ticket - 52 * mm
        p.line(5 * mm, y + 2 * mm, width_ticket - 5 * mm, y + 2 * mm)
        p.setFont("Helvetica-Bold", 8)
        p.drawString(7 * mm, y, "Désignation")
        p.drawRightString(width_ticket - 7 * mm, y, "Total")
        p.line(5 * mm, y - 2 * mm, width_ticket - 5 * mm, y - 2 * mm)
        
        # --- LIGNES DE VENTE ---
        p.setFont("Helvetica", 8)
        for ligne in vente.lignes.all():
            y -= 6 * mm
            # Nom de l'article (on coupe si trop long pour éviter de déborder)
            p.drawString(7 * mm, y, f"{ligne.article.nom[:22]}")
            # Prix et quantité sur la ligne d'en dessous pour gagner de la place
            y -= 4 * mm
            p.drawString(10 * mm, y, f"{ligne.quantite} x {ligne.article.prix_vente}")
            p.drawRightString(width_ticket - 7 * mm, y, f"{ligne.sous_total}")
            y -= 2 * mm # Petit espace entre articles

        # --- TOTAL ---
        y -= 8 * mm
        p.line(30 * mm, y + 5 * mm, width_ticket - 5 * mm, y + 5 * mm)
        p.setFont("Helvetica-Bold", 11)
        p.drawString(7 * mm, y, "TOTAL:")
        p.drawRightString(width_ticket - 7 * mm, y, f"{vente.total_ttc} {vente.entreprise.devise}")

        # --- PIED DE PAGE ---
        y -= 15 * mm
        p.setFont("Helvetica-Oblique", 7)
        p.drawCentredString(width_ticket / 2, y, "Merci de votre confiance !")
        p.drawCentredString(width_ticket / 2, y - 4 * mm, "Marchandises ni reprises ni échangées.")
        
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
        # On construit l'URL absolue pour le retour à Flutter
        logo_url = request.build_absolute_uri(user.entreprise.logo.url)

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


@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def sync_bucket(request, key):
    allowed_keys = {'quotes_invoices', 'credits_clients', 'clients_loyalty'}
    if key not in allowed_keys:
        return Response({"error": "Clé de synchronisation invalide"}, status=400)

    user = request.user
    if not user.entreprise:
        return Response({"error": "Utilisateur sans entreprise"}, status=400)

    bucket, _ = SyncBucket.objects.get_or_create(
        entreprise=user.entreprise,
        key=key,
        defaults={'data': []},
    )

    if request.method == 'GET':
        return Response({
            "key": key,
            "data": bucket.data if isinstance(bucket.data, list) else [],
            "updated_at": bucket.updated_at.isoformat(),
        })

    payload = request.data.get('data', [])
    if not isinstance(payload, list):
        return Response({"error": "Le champ data doit être une liste"}, status=400)

    bucket.data = payload
    bucket.save(update_fields=['data', 'updated_at'])
    return Response({
        "ok": True,
        "key": key,
        "updated_at": bucket.updated_at.isoformat(),
    })
