from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from datetime import timedelta
from .models import (
    Entreprise, User, Article, Client,
    Vente, LigneVente, Depense, Commande,
    Fournisseur, AchatFournisseur, PaiementCredit, MouvementCaisse,
)


# ─── ENTREPRISE ───────────────────────────────────────────────────────────────
@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    list_display  = ('nom', 'devise', 'plan_badge', 'plan_expire', 'created_at')
    list_filter   = ('plan',)
    search_fields = ('nom',)
    fields        = ('nom', 'logo', 'devise', 'tva_default', 'couleur_primaire', 'plan', 'plan_expire')
    actions       = ['passer_premium', 'passer_gratuit']

    def plan_badge(self, obj):
        if obj.plan_actif == 'premium':
            return format_html(
                '<span style="background:#f59e0b;color:#fff;padding:2px 10px;'
                'border-radius:12px;font-weight:bold;font-size:11px">⭐ PREMIUM</span>')
        return format_html(
            '<span style="background:#6b7280;color:#fff;padding:2px 10px;'
            'border-radius:12px;font-size:11px">Gratuit</span>')
    plan_badge.short_description = 'Plan'

    @admin.action(description='⭐ Passer en PREMIUM (sans limite)')
    def passer_premium(self, request, queryset):
        queryset.update(plan='premium', plan_expire=None)
        self.message_user(request, f'{queryset.count()} entreprise(s) passée(s) en Premium.')

    @admin.action(description='🔒 Repasser en GRATUIT')
    def passer_gratuit(self, request, queryset):
        queryset.update(plan='gratuit', plan_expire=None)
        self.message_user(request, f'{queryset.count()} entreprise(s) repassée(s) en Gratuit.')


# ─── UTILISATEURS ─────────────────────────────────────────────────────────────
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display  = ('username', 'email', 'entreprise', 'role', 'statut_connexion', 'last_seen', 'is_active')
    list_filter   = ('role', 'is_active', 'entreprise')
    search_fields = ('username', 'email')
    readonly_fields = ('last_seen', 'date_joined', 'last_login')
    ordering      = ('-last_seen',)

    def statut_connexion(self, obj):
        if obj.last_seen and obj.last_seen >= timezone.now() - timedelta(minutes=5):
            return format_html('<span style="color:green;font-weight:bold">● Connecté</span>')
        return format_html('<span style="color:grey">○ Hors ligne</span>')
    statut_connexion.short_description = 'Statut'


# ─── ARTICLES ─────────────────────────────────────────────────────────────────
@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display  = ('nom', 'entreprise', 'prix_vente', 'stock', 'seuil_alerte', 'stock_status')
    list_filter   = ('entreprise',)
    search_fields = ('nom',)

    def stock_status(self, obj):
        if obj.stock <= obj.seuil_alerte:
            return format_html('<span style="color:red;font-weight:bold">⚠ Stock critique</span>')
        return format_html('<span style="color:green">✓ OK</span>')
    stock_status.short_description = 'Stock'


# ─── VENTES ───────────────────────────────────────────────────────────────────
@admin.register(Vente)
class VenteAdmin(admin.ModelAdmin):
    list_display  = ('numero_sequentiel', 'entreprise', 'vendeur', 'client_display',
                     'total_ttc', 'statut', 'mode_paiement', 'date_vente')
    list_filter   = ('statut', 'mode_paiement', 'entreprise', 'vendeur')
    search_fields = ('numero_sequentiel', 'nom_client_libre', 'client__nom', 'vendeur__username')
    date_hierarchy = 'date_vente'
    readonly_fields = ('date_vente', 'numero_sequentiel', 'vendeur')

    def client_display(self, obj):
        if obj.client:
            return obj.client.nom
        return obj.nom_client_libre or '—'
    client_display.short_description = 'Client'


# ─── LIGNES DE VENTE ──────────────────────────────────────────────────────────
@admin.register(LigneVente)
class LigneVenteAdmin(admin.ModelAdmin):
    list_display  = ('vente', 'article', 'quantite', 'prix_unitaire', 'sous_total')
    search_fields = ('article__nom', 'vente__numero_sequentiel')


# ─── PAIEMENTS CRÉDIT ─────────────────────────────────────────────────────────
@admin.register(PaiementCredit)
class PaiementCreditAdmin(admin.ModelAdmin):
    list_display  = ('vente', 'montant', 'mode_paiement', 'date_paiement', 'enregistre_par')
    list_filter   = ('mode_paiement', 'enregistre_par')
    date_hierarchy = 'date_paiement'
    readonly_fields = ('date_paiement', 'enregistre_par')


# ─── DÉPENSES ─────────────────────────────────────────────────────────────────
@admin.register(Depense)
class DepenseAdmin(admin.ModelAdmin):
    list_display  = ('motif', 'entreprise', 'montant', 'categorie',
                     'fournisseur', 'statut_validation', 'declaree_par', 'date_depense')
    list_filter   = ('statut_validation', 'categorie', 'entreprise')
    search_fields = ('motif', 'fournisseur')
    date_hierarchy = 'date_depense'
    readonly_fields = ('declaree_par', 'date_depense')


# ─── COMMANDES ────────────────────────────────────────────────────────────────
@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display  = ('nom_client', 'entreprise', 'total_commande', 'acompte_verse',
                     'statut', 'date_livraison_prevue', 'retard_display')
    list_filter   = ('statut', 'entreprise')
    search_fields = ('nom_client', 'telephone_client')
    date_hierarchy = 'date_livraison_prevue'

    def retard_display(self, obj):
        if obj.date_livraison_prevue and obj.statut not in ('terminee', 'annulee'):
            today = timezone.now().date()
            if obj.date_livraison_prevue < today:
                jours = (today - obj.date_livraison_prevue).days
                return format_html('<span style="color:red;font-weight:bold">⚠ +{}j de retard</span>', jours)
        return '—'
    retard_display.short_description = 'Retard'


# ─── FOURNISSEURS ─────────────────────────────────────────────────────────────
@admin.register(Fournisseur)
class FournisseurAdmin(admin.ModelAdmin):
    list_display  = ('nom', 'entreprise', 'telephone', 'email', 'solde_dette')
    search_fields = ('nom', 'telephone')
    list_filter   = ('entreprise',)


# ─── ACHATS FOURNISSEURS ──────────────────────────────────────────────────────
@admin.register(AchatFournisseur)
class AchatFournisseurAdmin(admin.ModelAdmin):
    list_display  = ('designation', 'fournisseur', 'quantite', 'montant_total',
                     'montant_paye', 'statut_paiement', 'declare_par', 'date_achat')
    list_filter   = ('statut_paiement', 'mode_paiement')
    search_fields = ('designation', 'fournisseur__nom')
    date_hierarchy = 'date_achat'
    readonly_fields = ('declare_par', 'date_achat')


# ─── MOUVEMENTS DE CAISSE ─────────────────────────────────────────────────────
@admin.register(MouvementCaisse)
class MouvementCaisseAdmin(admin.ModelAdmin):
    list_display  = ('type_mouvement', 'entreprise', 'montant', 'solde_avant',
                     'solde_apres', 'created_by', 'date_mouvement', 'notes')
    list_filter   = ('type_mouvement', 'entreprise', 'created_by')
    search_fields = ('notes',)
    date_hierarchy = 'date_mouvement'
    readonly_fields = ('created_by', 'date_mouvement', 'solde_avant', 'solde_apres')


# ─── CLIENTS ──────────────────────────────────────────────────────────────────
@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display  = ('nom', 'entreprise', 'telephone', 'solde_credit')
    search_fields = ('nom', 'telephone')
    list_filter   = ('entreprise',)


# ─── PERSONNALISATION ADMIN ───────────────────────────────────────────────────
admin.site.site_header  = 'IKA GESTION — Administration'
admin.site.site_title   = 'IKA Admin'
admin.site.index_title  = 'Tableau de bord administrateur'
