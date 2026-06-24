import io
from datetime import datetime, timedelta
from urllib.request import urlopen

from django.db.models import Sum, F, DecimalField, Q, Count
from django.db import transaction
from django.http import FileResponse
from django.contrib.auth import authenticate
from django.utils import timezone
from django.db.models.functions import TruncDate

from rest_framework import viewsets, generics, permissions
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.permissions import IsAuthenticated

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import mm
    from reportlab.lib.utils import ImageReader
except ImportError:
    canvas = mm = ImageReader = None

from .models import (
    User, Article, Client, Vente, LigneVente, Depense, Commande,
    Fournisseur, AchatFournisseur, PaiementCredit, MouvementCaisse, MODES_PAIEMENT,
)
from .role_permissions import RoleBasedPermission
from .serializers import (
    EntrepriseRegistrationSerializer, UserSerializer,
    EntrepriseUserCreateSerializer, EntrepriseUserUpdateSerializer,
    ArticleSerializer, ClientSerializer, VenteSerializer,
    DepenseSerializer, CommandeSerializer,
    FournisseurSerializer, AchatFournisseurSerializer, PaiementCreditSerializer,
    MouvementCaisseSerializer,
)
from decimal import Decimal


# ─────────────────────────────────────────────
# PERMISSIONS
# ─────────────────────────────────────────────

class IsOwnerOfEntreprise(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.entreprise is not None

    def has_object_permission(self, request, view, obj):
        return obj.entreprise == request.user.entreprise


class IsAdminRole(permissions.BasePermission):
    message = "Accès réservé à l'administrateur."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if request.user.entreprise is None:
            return False
        return str(getattr(request.user, 'role', '') or '').strip().lower() == 'admin'


def _absolute_media_url(request, file_field):
    if not file_field:
        return None
    try:
        return request.build_absolute_uri(file_field.url)
    except Exception:
        return None


# ─────────────────────────────────────────────
# AUTHENTIFICATION
# ─────────────────────────────────────────────

class CustomAuthToken(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        login_id = str(request.data.get('email') or request.data.get('username') or '').strip()
        password = request.data.get('password')
        if not login_id or not password:
            return Response({'error': 'Email et mot de passe requis'}, status=400)

        user = authenticate(request=request, email=login_id, password=password)
        if not user:
            fallback = User.objects.filter(username__iexact=login_id).first()
            if fallback:
                user = authenticate(request=request, email=fallback.email, password=password)

        if user:
            User.objects.filter(pk=user.pk).update(last_seen=timezone.now())
            token, _ = Token.objects.get_or_create(user=user)
            ent = user.entreprise
            logo_url = _absolute_media_url(request, ent.logo if ent else None)
            return Response({
                'token':           token.key,
                'user_id':         user.pk,
                'username':        user.username,
                'email':           user.email,
                'role':            getattr(user, 'role', 'admin'),
                'entreprise_id':   ent.id if ent else None,
                'entreprise_nom':  ent.nom if ent else 'Admin',
                'entreprise_logo': logo_url,
                'devise':          ent.devise if ent else 'CFA',
                'plan':            ent.plan_actif if ent else 'gratuit',
                'plan_expire':     ent.plan_expire.isoformat() if ent and ent.plan_expire else None,
            })
        return Response({'error': 'Identifiants invalides'}, status=400)


class RegisterEntrepriseView(generics.CreateAPIView):
    queryset           = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class   = EntrepriseRegistrationSerializer


# ─────────────────────────────────────────────
# ARTICLES
# ─────────────────────────────────────────────

class ArticleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise, RoleBasedPermission]
    serializer_class   = ArticleSerializer

    def get_queryset(self):
        qs = Article.objects.filter(entreprise=self.request.user.entreprise)
        archived = self.request.query_params.get('archived', 'false').lower()
        if archived == 'true':
            return qs.filter(archived=True)
        return qs.filter(archived=False)

    def perform_create(self, serializer):
        serializer.save(entreprise=self.request.user.entreprise)

    @action(detail=True, methods=['post'], url_path='archiver')
    def archiver(self, request, pk=None):
        article = self.get_object()
        article.archived = not article.archived
        article.save(update_fields=['archived'])
        state = "archivé" if article.archived else "réactivé"
        return Response({'status': f'Article {state}.', 'archived': article.archived})


# ─────────────────────────────────────────────
# FOURNISSEURS
# ─────────────────────────────────────────────

class FournisseurViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise, RoleBasedPermission]
    serializer_class   = FournisseurSerializer

    def get_queryset(self):
        return Fournisseur.objects.filter(
            entreprise=self.request.user.entreprise
        ).prefetch_related('achats')

    def perform_create(self, serializer):
        serializer.save(entreprise=self.request.user.entreprise)


class AchatFournisseurViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise, RoleBasedPermission]
    serializer_class   = AchatFournisseurSerializer

    def get_queryset(self):
        qs = AchatFournisseur.objects.filter(
            entreprise=self.request.user.entreprise
        ).select_related('fournisseur', 'article', 'declare_par')

        fournisseur_id = self.request.query_params.get('fournisseur')
        if fournisseur_id:
            qs = qs.filter(fournisseur_id=fournisseur_id)

        statut = self.request.query_params.get('statut_paiement')
        if statut:
            qs = qs.filter(statut_paiement=statut)

        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            achat = serializer.save(
                entreprise=self.request.user.entreprise,
                declare_par=self.request.user,
            )
            # Mettre à jour le stock si l'article est lié
            if achat.article:
                achat.article.stock += achat.quantite
                achat.article.prix_achat = achat.prix_unitaire
                achat.article.save(update_fields=['stock', 'prix_achat'])

            # Mettre à jour la dette fournisseur
            if achat.fournisseur:
                reste = achat.montant_total - achat.montant_paye
                if reste > 0:
                    Fournisseur.objects.filter(pk=achat.fournisseur_id).update(
                        solde_dette=achat.fournisseur.solde_dette + reste
                    )

    @action(detail=True, methods=['post'], url_path='payer')
    @transaction.atomic
    def payer(self, request, pk=None):
        """Enregistrer un paiement partiel ou total pour un achat."""
        achat = AchatFournisseur.objects.select_for_update().filter(
            pk=pk, entreprise=request.user.entreprise
        ).first()
        if not achat:
            return Response({'error': 'Achat introuvable.'}, status=404)

        try:
            montant = Decimal(str(request.data.get('montant', 0)))
        except Exception:
            return Response({'error': 'Montant invalide.'}, status=400)

        if montant <= 0:
            return Response({'error': 'Le montant doit être positif.'}, status=400)

        reste = achat.montant_total - achat.montant_paye
        if montant > reste:
            return Response({'error': f'Montant dépasse le reste à payer ({reste}).'}, status=400)

        mode = request.data.get('mode_paiement', 'especes')
        achat.montant_paye += montant
        achat.mode_paiement = mode
        achat.save()

        # Réduire la dette fournisseur
        if achat.fournisseur:
            Fournisseur.objects.filter(pk=achat.fournisseur_id).update(
                solde_dette=max(achat.fournisseur.solde_dette - montant, Decimal('0'))
            )

        return Response(AchatFournisseurSerializer(achat).data)


# ─────────────────────────────────────────────
# CLIENTS
# ─────────────────────────────────────────────

class ClientViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise, RoleBasedPermission]
    serializer_class   = ClientSerializer

    def get_queryset(self):
        return Client.objects.filter(
            entreprise=self.request.user.entreprise
        ).order_by('nom')

    def perform_create(self, serializer):
        serializer.save(entreprise=self.request.user.entreprise)


# ─────────────────────────────────────────────
# VENTES
# ─────────────────────────────────────────────

class VenteViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise, RoleBasedPermission]
    serializer_class   = VenteSerializer

    def get_queryset(self):
        qs = (
            Vente.objects.filter(entreprise=self.request.user.entreprise)
            .select_related('client', 'vendeur')
            .prefetch_related('lignes__article', 'paiements_credit')
            .order_by('-date_vente')
        )
        statut = self.request.query_params.get('statut')
        if statut:
            qs = qs.filter(statut=statut)
        else:
            qs = qs.exclude(statut='annulee')

        date_param = self.request.query_params.get('date')
        if date_param:
            qs = qs.filter(date_vente__date=date_param)

        client_id = self.request.query_params.get('client')
        if client_id:
            qs = qs.filter(client_id=client_id)

        return qs

    def perform_create(self, serializer):
        serializer.save(
            entreprise=self.request.user.entreprise,
            vendeur=self.request.user,
            statut=self.request.data.get('statut', 'payee'),
        )

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def annuler(self, request, pk=None):
        vente = Vente.objects.select_for_update().get(
            pk=pk, entreprise=request.user.entreprise
        )
        if vente.statut == 'annulee':
            return Response({'error': 'Cette vente est déjà annulée.'}, status=400)

        for ligne in vente.lignes.select_related('article').all():
            if ligne.article:
                ligne.article.stock += ligne.quantite
                ligne.article.save(update_fields=['stock'])

        # Rembourser le crédit client si applicable
        if vente.statut == 'credit' and vente.client:
            montant_restant = vente.montant_restant_credit
            Client.objects.filter(pk=vente.client_id).update(
                solde_credit=max(vente.client.solde_credit - montant_restant, Decimal('0'))
            )

        vente.statut = 'annulee'
        vente.save(update_fields=['statut'])
        return Response({'status': 'Vente annulée et stock restauré.'})

    @action(detail=True, methods=['post'], url_path='payer-credit')
    @transaction.atomic
    def payer_credit(self, request, pk=None):
        """Enregistrer un paiement sur une vente à crédit."""
        vente = Vente.objects.select_for_update().get(
            pk=pk, entreprise=request.user.entreprise
        )
        if vente.statut != 'credit':
            return Response({'error': 'Cette vente n\'est pas à crédit.'}, status=400)

        try:
            montant = Decimal(str(request.data.get('montant', 0)))
        except Exception:
            return Response({'error': 'Montant invalide.'}, status=400)

        if montant <= 0:
            return Response({'error': 'Le montant doit être positif.'}, status=400)

        restant = vente.montant_restant_credit
        if montant > restant:
            return Response({'error': f'Montant dépasse le restant dû ({restant}).'}, status=400)

        mode = request.data.get('mode_paiement', 'especes')
        paiement = PaiementCredit.objects.create(
            vente=vente,
            montant=montant,
            mode_paiement=mode,
            notes=request.data.get('notes', ''),
            enregistre_par=request.user,
        )

        # Réduire le solde crédit du client
        if vente.client:
            Client.objects.filter(pk=vente.client_id).update(
                solde_credit=max(vente.client.solde_credit - montant, Decimal('0'))
            )

        # Si soldé → marquer comme payée
        nouveau_restant = vente.montant_restant_credit - montant
        if nouveau_restant <= 0:
            vente.statut = 'payee'
            vente.save(update_fields=['statut'])

        vente.refresh_from_db()
        return Response({
            'status': 'Paiement enregistré.',
            'paiement': PaiementCreditSerializer(paiement).data,
            'vente': VenteSerializer(vente, context={'request': request}).data,
        })

    @action(detail=True, methods=['delete'], url_path='supprimer')
    @transaction.atomic
    def supprimer(self, request, pk=None):
        vente = self.get_object()
        for ligne in vente.lignes.select_related('article').all():
            if ligne.article:
                ligne.article.stock += ligne.quantite
                ligne.article.save(update_fields=['stock'])
        vente.delete()
        return Response(status=204)

    @action(detail=True, methods=['get'],
            authentication_classes=[SessionAuthentication, TokenAuthentication],
            permission_classes=[IsAuthenticated, IsOwnerOfEntreprise])
    def facture_pdf(self, request, pk=None):
        if canvas is None:
            return Response({'error': 'ReportLab absent.'}, status=503)

        vente  = self.get_object()
        buffer = io.BytesIO()
        width  = 80 * mm
        height = (130 + vente.lignes.count() * 15) * mm
        p      = canvas.Canvas(buffer, pagesize=(width, height))

        nom_client = (
            vente.nom_client_libre
            or (vente.client.nom if vente.client else 'Client Passant')
        )
        telephone = (
            getattr(vente, 'telephone_client_libre', '') or
            (vente.client.telephone if vente.client else '')
        )

        # Logo
        if vente.entreprise.logo:
            logo_reader = None
            try:
                logo_reader = ImageReader(vente.entreprise.logo.path)
            except Exception:
                pass
            if logo_reader is None:
                try:
                    url = vente.entreprise.logo.url
                    if str(url).startswith('/'):
                        url = request.build_absolute_uri(url)
                    with urlopen(str(url), timeout=3) as r:
                        logo_reader = ImageReader(io.BytesIO(r.read()))
                except Exception:
                    pass
            if logo_reader:
                try:
                    p.drawImage(
                        logo_reader,
                        (width / 2) - 10 * mm, height - 14 * mm,
                        width=20 * mm, height=10 * mm,
                        preserveAspectRatio=True, mask='auto',
                    )
                except Exception:
                    pass

        # En-tête
        p.setFont("Helvetica-Bold", 12)
        p.drawCentredString(width / 2, height - 20 * mm, vente.entreprise.nom.upper())
        p.setFont("Helvetica", 8)
        date_str  = vente.date_vente.strftime('%d/%m/%Y %H:%M')
        recu_num  = str(vente.numero_sequentiel).zfill(4)
        p.drawCentredString(width / 2, height - 27 * mm, f"Date : {date_str}")
        p.drawCentredString(width / 2, height - 32 * mm, f"Reçu N° {recu_num}")

        p.line(5 * mm, height - 37 * mm, width - 5 * mm, height - 37 * mm)
        p.setFont("Helvetica-Bold", 9)
        p.drawString(7 * mm, height - 43 * mm, f"CLIENT : {nom_client[:25]}")
        if telephone:
            p.setFont("Helvetica", 8)
            p.drawString(7 * mm, height - 48 * mm, f"Tél : {telephone}")

        # Statut crédit
        if vente.statut == 'credit':
            p.setFont("Helvetica-Bold", 8)
            p.setFillColorRGB(0.8, 0, 0)
            p.drawString(7 * mm, height - 54 * mm, f"VENTE À CRÉDIT — Restant : {vente.montant_restant_credit} {vente.entreprise.devise}")
            p.setFillColorRGB(0, 0, 0)

        # Tableau articles
        y = height - 62 * mm
        p.line(5 * mm, y + 2 * mm, width - 5 * mm, y + 2 * mm)
        p.setFont("Helvetica-Bold", 8)
        p.drawString(7 * mm, y, "Désignation")
        p.drawRightString(width - 7 * mm, y, "Total")
        p.line(5 * mm, y - 2 * mm, width - 5 * mm, y - 2 * mm)

        p.setFont("Helvetica", 8)
        for ligne in vente.lignes.all():
            y -= 6 * mm
            nom_art = (getattr(ligne.article, 'nom', None) or "Article supprimé")[:22]
            p.drawString(7 * mm, y, nom_art)
            y -= 4 * mm
            p.drawString(10 * mm, y, f"{ligne.quantite} x {ligne.prix_unitaire}")
            p.drawRightString(width - 7 * mm, y, str(ligne.sous_total))
            y -= 2 * mm

        y -= 8 * mm
        p.line(30 * mm, y + 5 * mm, width - 5 * mm, y + 5 * mm)
        p.setFont("Helvetica-Bold", 11)
        devise = vente.entreprise.devise or ''
        p.drawString(7 * mm, y, "TOTAL :")
        p.drawRightString(width - 7 * mm, y, f"{vente.total_ttc} {devise}")

        if vente.acompte > 0:
            y -= 6 * mm
            p.setFont("Helvetica", 9)
            p.drawString(7 * mm, y, f"Acompte reçu : {vente.acompte} {devise}")
            y -= 5 * mm
            p.drawString(7 * mm, y, f"Reste dû : {vente.montant_restant_credit} {devise}")

        # Mode paiement
        y -= 6 * mm
        mode_label = dict(MODES_PAIEMENT).get(vente.mode_paiement, vente.mode_paiement)
        p.setFont("Helvetica", 8)
        p.drawString(7 * mm, y, f"Paiement : {mode_label}")

        y -= 14 * mm
        p.setFont("Helvetica-Oblique", 7)
        p.drawCentredString(width / 2, y, "Merci de votre confiance !")
        p.drawCentredString(width / 2, y - 4 * mm, "Marchandises ni reprises ni échangées.")

        p.showPage()
        p.save()
        buffer.seek(0)
        return FileResponse(buffer, as_attachment=False, filename=f'Facture_{vente.numero_sequentiel}.pdf')


# ─────────────────────────────────────────────
# PAIEMENTS CRÉDIT (liste globale)
# ─────────────────────────────────────────────

class PaiementCreditViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise, RoleBasedPermission]
    serializer_class   = PaiementCreditSerializer

    def get_queryset(self):
        return PaiementCredit.objects.filter(
            vente__entreprise=self.request.user.entreprise
        ).select_related('vente', 'enregistre_par')


# ─────────────────────────────────────────────
# DÉPENSES
# ─────────────────────────────────────────────

class DepenseViewSet(viewsets.ModelViewSet):
    serializer_class   = DepenseSerializer
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise, RoleBasedPermission]

    def get_queryset(self):
        return Depense.objects.filter(entreprise=self.request.user.entreprise)

    def perform_create(self, serializer):
        serializer.save(
            entreprise=self.request.user.entreprise,
            declaree_par=self.request.user,
        )


# ─────────────────────────────────────────────
# COMMANDES
# ─────────────────────────────────────────────

class CommandeViewSet(viewsets.ModelViewSet):
    serializer_class   = CommandeSerializer
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise, RoleBasedPermission]

    def get_queryset(self):
        return Commande.objects.filter(
            entreprise=self.request.user.entreprise
        ).exclude(statut__in=['livre', 'livree'])

    def perform_create(self, serializer):
        serializer.save(
            entreprise=self.request.user.entreprise,
            vendeur=self.request.user,
        )

    @action(detail=True, methods=['post'], url_path='solder')
    @transaction.atomic
    def solder(self, request, pk=None):
        commande = self.get_queryset().select_for_update().filter(pk=pk).first()
        if not commande:
            return Response({'error': 'Commande introuvable.'}, status=404)
        if commande.statut in ('livre', 'livree'):
            return Response({'error': 'Cette commande est déjà soldée.'}, status=400)

        vente = Vente.objects.create(
            entreprise=commande.entreprise,
            vendeur=request.user,
            nom_client_libre=(commande.nom_client or None),
            telephone_client_libre=(commande.telephone_client or None),
            total_ttc=commande.total_commande,
            mode_paiement='especes',
            statut='payee',
        )
        commande.statut        = 'livre'
        commande.acompte_verse = commande.total_commande
        commande.save(update_fields=['statut', 'acompte_verse'])
        commande.delete()

        return Response({
            'status':    'success',
            'vente_id':  vente.id,
            'message':   f"Commande soldée. Vente n°{vente.numero_sequentiel} générée.",
        })

    @action(detail=False, methods=['get'], url_path='delivery-alerts')
    def delivery_alerts(self, request):
        today = timezone.localdate()
        try:
            days = min(max(int(request.query_params.get('days', 2)), 0), 14)
        except (TypeError, ValueError):
            days = 2

        target_dates    = [today + timedelta(days=i) for i in range(days + 1)]
        pending_statuts = ['devis', 'en_attente', 'en_cours', 'pret']
        queryset = Commande.objects.filter(
            entreprise=request.user.entreprise,
            statut__in=pending_statuts,
            date_livraison_prevue__in=target_dates,
        ).order_by('date_livraison_prevue')

        alerts = []
        for c in queryset:
            delta = (c.date_livraison_prevue - today).days
            echeance = (
                "aujourd'hui" if delta == 0
                else "demain" if delta == 1
                else "après-demain" if delta == 2
                else f"dans {delta} jours"
            )
            alerts.append({
                "id":                    c.id,
                "nom_client":            c.nom_client,
                "telephone_client":      c.telephone_client or 'N/A',
                "date_livraison_prevue": c.date_livraison_prevue.strftime('%Y-%m-%d'),
                "jours_restants":        delta,
                "message": (
                    f"{c.nom_client} ({c.telephone_client or 'N/A'}) — "
                    f"livraison {echeance} ({c.date_livraison_prevue.strftime('%d/%m/%Y')})"
                ),
            })

        return Response({
            "date_reference": today.strftime('%Y-%m-%d'),
            "jours_alerte":   days,
            "total_alertes":  len(alerts),
            "alertes":        alerts,
        })


# ─────────────────────────────────────────────
# UTILISATEURS
# ─────────────────────────────────────────────

class EntrepriseUserViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get_permissions(self):
        if self.action == 'heartbeat':
            return [IsAuthenticated()]
        return [p() for p in self.permission_classes]

    def get_queryset(self):
        qs = User.objects.all()
        if self.request.user.entreprise:
            qs = qs.filter(entreprise=self.request.user.entreprise)
        return qs.order_by('-last_seen', 'username')

    def get_serializer_class(self):
        if self.action == 'create':
            return EntrepriseUserCreateSerializer
        if self.action in ('update', 'partial_update'):
            return EntrepriseUserUpdateSerializer
        return UserSerializer

    def perform_destroy(self, instance):
        if instance.pk == self.request.user.pk:
            raise PermissionDenied("Impossible de supprimer votre propre compte.")
        instance.is_active = False
        instance.save(update_fields=['is_active'])

    @action(detail=False, methods=['post'], url_path='heartbeat')
    def heartbeat(self, request):
        User.objects.filter(pk=request.user.pk).update(last_seen=timezone.now())
        return Response({'status': 'online'})

    @action(detail=False, methods=['get'], url_path='online')
    def online(self, request):
        threshold = timezone.now() - timedelta(minutes=5)
        users = self.get_queryset().filter(is_active=True, last_seen__gte=threshold)
        return Response(UserSerializer(users, many=True, context={'request': request}).data)


# ─────────────────────────────────────────────
# REPORTING
# ─────────────────────────────────────────────

class ReportingViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise, RoleBasedPermission]

    def _chart_points(self, vente_q, depense_q, commande_q):
        ventes = {
            r['jour']: r['total'] or 0
            for r in Vente.objects.filter(vente_q)
            .annotate(jour=TruncDate('date_vente'))
            .values('jour').annotate(total=Sum('total_ttc'))
        }
        depenses = {
            r['date_depense']: r['total'] or 0
            for r in Depense.objects.filter(depense_q)
            .values('date_depense').annotate(total=Sum('montant'))
        }
        acomptes = {
            r['jour']: r['total'] or 0
            for r in Commande.objects.filter(commande_q)
            .annotate(jour=TruncDate('date_commande'))
            .values('jour').annotate(total=Sum('acompte_verse'))
        }
        jours = sorted(set(ventes) | set(depenses) | set(acomptes))
        return [
            {
                'date':     j.strftime('%Y-%m-%d'),
                'ventes':   float(ventes.get(j, 0)),
                'depenses': float(depenses.get(j, 0)),
                'acomptes': float(acomptes.get(j, 0)),
                'net':      float((ventes.get(j, 0) + acomptes.get(j, 0)) - depenses.get(j, 0)),
            }
            for j in jours
        ]

    @action(detail=False, methods=['get'], url_path='financial-summary')
    def financial_summary(self, request):
        ent   = request.user.entreprise
        start = request.query_params.get('start_date')
        end   = request.query_params.get('end_date')

        vq = Q(entreprise=ent) & ~Q(statut='annulee')
        dq = Q(entreprise=ent)
        cq = Q(entreprise=ent) & ~Q(statut='livre')

        try:
            if start:
                vq &= Q(date_vente__date__gte=start)
                dq &= Q(date_depense__gte=start)
                cq &= Q(date_commande__date__gte=start)
            if end:
                vq &= Q(date_vente__date__lte=end)
                dq &= Q(date_depense__lte=end)
                cq &= Q(date_commande__date__lte=end)
        except ValueError:
            return Response({'erreur': 'Format date invalide (YYYY-MM-DD).'}, status=400)

        vente_data = Vente.objects.filter(vq).aggregate(
            total_ca=Sum('total_ttc', output_field=DecimalField()),
            total_cmv=Sum(
                F('lignes__quantite') * F('lignes__article__prix_achat'),
                output_field=DecimalField()
            ),
        )
        total_depenses  = Depense.objects.filter(dq).aggregate(s=Sum('montant'))['s'] or 0
        total_acomptes  = Commande.objects.filter(cq).aggregate(s=Sum('acompte_verse'))['s'] or 0
        total_credits   = Vente.objects.filter(vq, statut='credit').aggregate(
            s=Sum('total_ttc')
        )['s'] or 0
        achats_fournisseur = AchatFournisseur.objects.filter(
            entreprise=ent
        ).aggregate(s=Sum('montant_total'))['s'] or 0

        total_ca  = vente_data['total_ca'] or 0
        total_cmv = vente_data['total_cmv'] or 0
        marge     = total_ca - total_cmv
        benefice  = (marge + total_acomptes) - total_depenses

        # Top 5 produits les plus vendus (par quantité)
        top_articles_qs = (
            LigneVente.objects
            .filter(vente__in=Vente.objects.filter(vq))
            .values('article__nom')
            .annotate(
                qte=Sum('quantite'),
                ca=Sum(F('quantite') * F('prix_unitaire'), output_field=DecimalField())
            )
            .order_by('-qte')[:5]
        )
        top_produits = [
            {
                'nom': r['article__nom'] or 'Article supprimé',
                'qte': int(r['qte'] or 0),
                'ca':  float(r['ca'] or 0),
            }
            for r in top_articles_qs
        ]

        # Top 5 clients par montant total acheté
        top_clients_qs = (
            Vente.objects.filter(vq)
            .values('nom_client_libre', 'client__nom')
            .annotate(
                nb=Count('id'),
                total=Sum('total_ttc')
            )
            .order_by('-total')[:5]
        )
        top_clients = [
            {
                'nom':      r['nom_client_libre'] or r['client__nom'] or 'Client libre',
                'nb_achats': r['nb'],
                'total':    float(r['total'] or 0),
            }
            for r in top_clients_qs
        ]

        return Response({
            'chiffre_affaires':       float(total_ca),
            'marge_brute':            float(marge),
            'total_depenses':         float(total_depenses),
            'total_acomptes':         float(total_acomptes),
            'total_credits_en_cours': float(total_credits),
            'achats_fournisseurs':    float(achats_fournisseur),
            'benefice_net':           float(benefice),
            'devise':                 ent.devise,
            'chart_points':           self._chart_points(vq, dq, cq),
            'top_produits':           top_produits,
            'top_clients':            top_clients,
        })

    @action(detail=False, methods=['get'], url_path='daily-report')
    def daily_report(self, request):
        ent     = request.user.entreprise
        day_str = request.query_params.get('date')
        try:
            day = datetime.strptime(day_str, '%Y-%m-%d').date() if day_str else timezone.localdate()
        except (TypeError, ValueError):
            return Response({'error': 'Format date invalide (YYYY-MM-DD).'}, status=400)

        ventes_qs  = (
            Vente.objects.filter(entreprise=ent, date_vente__date=day)
            .exclude(statut='annulee')
            .select_related('vendeur', 'client')
        )
        depenses_qs = (
            Depense.objects.filter(entreprise=ent, date_depense=day)
            .select_related('declaree_par')
        )

        total_ventes  = ventes_qs.aggregate(s=Sum('total_ttc'))['s'] or 0
        total_depenses = depenses_qs.aggregate(s=Sum('montant'))['s'] or 0

        ventes_par_user = (
            ventes_qs.values('vendeur_id', 'vendeur__username', 'vendeur__email')
            .annotate(total=Sum('total_ttc'), nombre=Count('id'))
            .order_by('-total')
        )
        depenses_par_user = (
            depenses_qs.values('declaree_par_id', 'declaree_par__username', 'declaree_par__email')
            .annotate(total=Sum('montant'), nombre=Count('id'))
            .order_by('-total')
        )

        return Response({
            'date':           day.strftime('%Y-%m-%d'),
            'devise':         ent.devise,
            'total_ventes':   float(total_ventes),
            'total_depenses': float(total_depenses),
            'net':            float(total_ventes - total_depenses),
            'ventes_count':   ventes_qs.count(),
            'depenses_count': depenses_qs.count(),
            'ventes_par_utilisateur': [
                {
                    'user_id':  r['vendeur_id'],
                    'username': r['vendeur__username'] or 'Inconnu',
                    'email':    r['vendeur__email'] or '',
                    'nombre':   r['nombre'],
                    'total':    float(r['total'] or 0),
                }
                for r in ventes_par_user
            ],
            'depenses_par_utilisateur': [
                {
                    'user_id':  r['declaree_par_id'],
                    'username': r['declaree_par__username'] or 'Inconnu',
                    'email':    r['declaree_par__email'] or '',
                    'nombre':   r['nombre'],
                    'total':    float(r['total'] or 0),
                }
                for r in depenses_par_user
            ],
            'ventes':   VenteSerializer(ventes_qs[:100], many=True).data,
            'depenses': DepenseSerializer(depenses_qs[:100], many=True).data,
        })


# ─────────────────────────────────────────────
# CAISSE (MOUVEMENTS)
# ─────────────────────────────────────────────

class MouvementCaisseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsOwnerOfEntreprise, RoleBasedPermission]
    serializer_class   = MouvementCaisseSerializer

    def get_queryset(self):
        qs = MouvementCaisse.objects.filter(
            entreprise=self.request.user.entreprise
        ).select_related('created_by')

        date_param = self.request.query_params.get('date')
        if date_param:
            qs = qs.filter(date_mouvement=date_param)

        type_param = self.request.query_params.get('type')
        if type_param:
            qs = qs.filter(type_mouvement=type_param)

        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        ent = self.request.user.entreprise
        solde_avant = MouvementCaisse.solde_actuel(ent.id)

        type_mouvement = self.request.data.get('type_mouvement', 'depot')
        montant = Decimal(str(self.request.data.get('montant', 0)))

        # Les retraits réduisent le solde
        if type_mouvement == 'retrait':
            solde_apres = solde_avant - montant
        else:
            solde_apres = solde_avant + montant

        serializer.save(
            entreprise=ent,
            created_by=self.request.user,
            solde_avant=solde_avant,
            solde_apres=solde_apres,
            date_mouvement=self.request.data.get('date_mouvement', str(timezone.localdate())),
        )

    @action(detail=False, methods=['get'], url_path='solde')
    def solde(self, request):
        """Retourne le solde actuel de la caisse + total ventes espèces du jour."""
        from django.utils.timezone import localdate
        ent   = request.user.entreprise
        today = str(localdate())

        solde = MouvementCaisse.solde_actuel(ent.id)

        # Ventes espèces du jour
        ventes_jour = Vente.objects.filter(
            entreprise=ent,
            date_vente__date=today,
            mode_paiement='especes',
        ).exclude(statut='annulee').aggregate(total=Sum('total_ttc'))['total'] or 0

        # Acomptes espèces des ventes crédit du jour
        acomptes_credit = Vente.objects.filter(
            entreprise=ent,
            date_vente__date=today,
            statut='credit',
        ).exclude(statut='annulee').aggregate(total=Sum('acompte'))['total'] or 0

        return Response({
            'solde_caisse':       float(solde),
            'ventes_especes_jour': float(ventes_jour),
            'acomptes_credit_jour': float(acomptes_credit),
            'devise':             ent.devise,
            'date':               today,
        })

    @action(detail=False, methods=['get'], url_path='flux-ventes')
    def flux_ventes(self, request):
        """Flux des dernières ventes pour mise à jour en temps réel."""
        ent   = request.user.entreprise
        limit = min(int(request.query_params.get('limit', 50)), 200)

        ventes = (
            Vente.objects.filter(entreprise=ent)
            .exclude(statut='annulee')
            .select_related('vendeur', 'client')
            .order_by('-date_vente')[:limit]
        )

        data = []
        for v in ventes:
            nom = (v.nom_client_libre or (v.client.nom if v.client else 'Client Passant'))
            data.append({
                'id':               v.id,
                'numero':           v.numero_sequentiel,
                'client':           nom,
                'total':            float(v.total_ttc),
                'statut':           v.statut,
                'mode_paiement':    v.mode_paiement,
                'vendeur':          v.vendeur.username if v.vendeur else '',
                'date_vente':       v.date_vente.strftime('%Y-%m-%d %H:%M'),
            })

        return Response({
            'count':      len(data),
            'timestamp':  timezone.now().isoformat(),
            'ventes':     data,
        })


# ─────────────────────────────────────────────
# PROFIL / AVATAR
# ─────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_avatar(request):
    user = request.user
    if getattr(user, 'role', '') not in ('admin', 'manager'):
        return Response({"error": "Accès refusé (rôle insuffisant)"}, status=403)
    if not user.entreprise:
        return Response({"error": "Utilisateur sans entreprise"}, status=400)

    logo = request.FILES.get('logo')
    if logo:
        user.entreprise.logo = logo
        user.entreprise.save()
        logo_url = _absolute_media_url(request, user.entreprise.logo)
        return Response({"message": "Logo mis à jour", "entreprise_logo": logo_url})
    return Response({"error": "Aucun fichier fourni"}, status=400)


@api_view(['POST', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_business_name(request):
    user = request.user
    if getattr(user, 'role', '') not in ('admin', 'manager'):
        return Response({"error": "Accès refusé (rôle insuffisant)"}, status=403)
    nouveau_nom = request.data.get('nom')
    if not nouveau_nom:
        return Response({"error": "Le nom est requis"}, status=400)
    if user.entreprise:
        user.entreprise.nom = nouveau_nom
        user.entreprise.save()
        return Response({"message": "Nom mis à jour", "nom": nouveau_nom})
    return Response({"error": "Entreprise introuvable"}, status=404)
