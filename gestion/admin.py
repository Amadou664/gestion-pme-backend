from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from datetime import timedelta, date
from .models import (
    Entreprise, User, Article, Client,
    Vente, LigneVente, Depense, Commande,
    Fournisseur, AchatFournisseur, PaiementCredit, MouvementCaisse,
)


# ─── INLINES ──────────────────────────────────────────────────────────────────
class LigneVenteInline(admin.TabularInline):
    model = LigneVente
    extra = 0
    readonly_fields = ('sous_total',)
    fields = ('article', 'quantite', 'prix_unitaire', 'remise_pct', 'sous_total')
    can_delete = False


class PaiementCreditInline(admin.TabularInline):
    model = PaiementCredit
    extra = 0
    readonly_fields = ('date_paiement',)
    fields = ('montant', 'mode_paiement', 'date_paiement', 'notes')
    can_delete = False


# ─── ENTREPRISE ───────────────────────────────────────────────────────────────
@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    list_display  = ('nom', 'devise', 'plan_badge', 'plan_expire', 'nb_utilisateurs', 'created_at')
    list_filter   = ('plan', 'devise')
    search_fields = ('nom',)
    fields        = ('nom', 'logo', 'devise', 'tva_default', 'couleur_primaire', 'plan', 'plan_expire')
    actions       = ['passer_premium_illimite', 'passer_premium_30j', 'passer_premium_365j', 'passer_gratuit']

    def plan_badge(self, obj):
        if obj.plan_actif == 'premium':
            return format_html(
                '<span style="background:#f59e0b;color:#fff;padding:3px 12px;'
                'border-radius:12px;font-weight:bold;font-size:11px">{}</span>',
                '⭐ PREMIUM'
            )
        return format_html(
            '<span style="background:#6b7280;color:#fff;padding:3px 12px;'
            'border-radius:12px;font-size:11px">{}</span>',
            'Gratuit'
        )
    plan_badge.short_description = 'Plan'

    def nb_utilisateurs(self, obj):
        count = obj.user_set.filter(is_active=True).count()
        return format_html('<b>{}</b>', count)
    nb_utilisateurs.short_description = 'Utilisateurs actifs'

    @admin.action(description='⭐ PREMIUM — Illimité (sans date de fin)')
    def passer_premium_illimite(self, request, queryset):
        queryset.update(plan='premium', plan_expire=None)
        self.message_user(request, f'{queryset.count()} entreprise(s) passée(s) en Premium illimité.')

    @admin.action(description='⭐ PREMIUM — 30 jours')
    def passer_premium_30j(self, request, queryset):
        expire = date.today() + timedelta(days=30)
        queryset.update(plan='premium', plan_expire=expire)
        self.message_user(request, f'{queryset.count()} entreprise(s) en Premium jusqu\'au {expire}.')

    @admin.action(description='⭐ PREMIUM — 365 jours (1 an)')
    def passer_premium_365j(self, request, queryset):
        expire = date.today() + timedelta(days=365)
        queryset.update(plan='premium', plan_expire=expire)
        self.message_user(request, f'{queryset.count()} entreprise(s) en Premium jusqu\'au {expire}.')

    @admin.action(description='🔒 Repasser en GRATUIT')
    def passer_gratuit(self, request, queryset):
        queryset.update(plan='gratuit', plan_expire=None)
        self.message_user(request, f'{queryset.count()} entreprise(s) repassée(s) en Gratuit.')


# ─── UTILISATEURS ─────────────────────────────────────────────────────────────
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display    = ('username', 'email', 'entreprise', 'role_badge', 'statut_connexion', 'last_seen', 'is_active')
    list_filter     = ('role', 'is_active', 'entreprise')
    search_fields   = ('username', 'email')
    readonly_fields = ('last_seen', 'date_joined', 'last_login')
    ordering        = ('-last_seen',)

    _ROLE_COLORS = {
        'admin':        ('#dc2626', 'Admin'),
        'manager':      ('#7c3aed', 'Manager'),
        'caissier':     ('#0891b2', 'Caissier'),
        'comptable':    ('#059669', 'Comptable'),
        'lecture_seule': ('#6b7280', 'Lecture seule'),
    }

    def role_badge(self, obj):
        color, label = self._ROLE_COLORS.get(obj.role, ('#6b7280', obj.role))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:8px;font-size:11px;font-weight:bold">{}</span>',
            color, label
        )
    role_badge.short_description = 'Rôle'

    def statut_connexion(self, obj):
        if obj.last_seen and obj.last_seen >= timezone.now() - timedelta(minutes=5):
            return format_html(
                '<span style="color:#16a34a;font-weight:bold">{}</span>',
                '● En ligne'
            )
        return format_html('<span style="color:#9ca3af">{}</span>', '○ Hors ligne')
    statut_connexion.short_description = 'Statut'


# ─── ARTICLES ─────────────────────────────────────────────────────────────────
@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display  = ('nom', 'entreprise', 'code', 'prix_achat', 'prix_vente',
                     'stock', 'seuil_alerte', 'stock_status', 'archived')
    list_filter   = ('entreprise', 'archived')
    search_fields = ('nom', 'code')
    list_editable = ('seuil_alerte',)
    actions       = ['archiver_articles', 'desarchiver_articles']

    def stock_status(self, obj):
        if obj.stock <= 0:
            return format_html(
                '<span style="background:#dc2626;color:#fff;padding:2px 8px;'
                'border-radius:8px;font-size:11px;font-weight:bold">{}</span>',
                '⚠ RUPTURE'
            )
        if obj.stock <= obj.seuil_alerte:
            return format_html(
                '<span style="background:#f59e0b;color:#fff;padding:2px 8px;'
                'border-radius:8px;font-size:11px">{}</span>',
                '⚠ Critique'
            )
        return format_html(
            '<span style="background:#16a34a;color:#fff;padding:2px 8px;'
            'border-radius:8px;font-size:11px">{}</span>',
            '✓ OK'
        )
    stock_status.short_description = 'Stock'

    @admin.action(description='Archiver les articles sélectionnés')
    def archiver_articles(self, request, queryset):
        queryset.update(archived=True)
        self.message_user(request, f'{queryset.count()} article(s) archivé(s).')

    @admin.action(description='Désarchiver les articles sélectionnés')
    def desarchiver_articles(self, request, queryset):
        queryset.update(archived=False)
        self.message_user(request, f'{queryset.count()} article(s) désarchivé(s).')


# ─── VENTES ───────────────────────────────────────────────────────────────────
@admin.register(Vente)
class VenteAdmin(admin.ModelAdmin):
    list_display    = ('numero_sequentiel', 'entreprise', 'vendeur', 'client_display',
                       'montant_display', 'statut_badge', 'mode_paiement', 'date_vente')
    list_filter     = ('statut', 'mode_paiement', 'entreprise', 'vendeur')
    search_fields   = ('numero_sequentiel', 'nom_client_libre', 'client__nom', 'vendeur__username')
    date_hierarchy  = 'date_vente'
    readonly_fields = ('date_vente', 'numero_sequentiel', 'vendeur')
    inlines         = [LigneVenteInline, PaiementCreditInline]

    _STATUT_COLORS = {
        'payee':   ('#16a34a', '✓ Payée'),
        'credit':  ('#f59e0b', '💳 Crédit'),
        'annulee': ('#dc2626', '✗ Annulée'),
    }

    def client_display(self, obj):
        if obj.client:
            return obj.client.nom
        return obj.nom_client_libre or '—'
    client_display.short_description = 'Client'

    def montant_display(self, obj):
        return format_html('<b>{:,.0f} {}</b>', obj.total_ttc, obj.entreprise.devise)
    montant_display.short_description = 'Montant'

    def statut_badge(self, obj):
        color, label = self._STATUT_COLORS.get(obj.statut, ('#6b7280', obj.statut))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:8px;font-size:11px">{}</span>',
            color, label
        )
    statut_badge.short_description = 'Statut'


# ─── LIGNES DE VENTE ──────────────────────────────────────────────────────────
@admin.register(LigneVente)
class LigneVenteAdmin(admin.ModelAdmin):
    list_display  = ('vente', 'article', 'quantite', 'prix_unitaire', 'remise_pct', 'sous_total')
    search_fields = ('article__nom',)
    list_filter   = ('vente__entreprise',)


# ─── PAIEMENTS CRÉDIT ─────────────────────────────────────────────────────────
@admin.register(PaiementCredit)
class PaiementCreditAdmin(admin.ModelAdmin):
    list_display    = ('vente', 'montant', 'mode_paiement', 'date_paiement', 'enregistre_par')
    list_filter     = ('mode_paiement', 'vente__entreprise')
    date_hierarchy  = 'date_paiement'
    readonly_fields = ('date_paiement', 'enregistre_par')


# ─── DÉPENSES ─────────────────────────────────────────────────────────────────
@admin.register(Depense)
class DepenseAdmin(admin.ModelAdmin):
    list_display    = ('motif', 'entreprise', 'montant_display', 'categorie',
                       'fournisseur', 'statut_badge', 'declaree_par', 'date_depense')
    list_filter     = ('statut_validation', 'categorie', 'entreprise')
    search_fields   = ('motif', 'fournisseur')
    date_hierarchy  = 'date_depense'
    readonly_fields = ('declaree_par', 'date_depense')
    actions         = ['valider_depenses', 'rejeter_depenses']

    _STATUT_COLORS = {
        'en_attente': ('#f59e0b', '⏳ En attente'),
        'validee':    ('#16a34a', '✓ Validée'),
        'rejetee':    ('#dc2626', '✗ Rejetée'),
    }

    def montant_display(self, obj):
        return format_html('<b>{:,.0f}</b>', obj.montant)
    montant_display.short_description = 'Montant'

    def statut_badge(self, obj):
        color, label = self._STATUT_COLORS.get(obj.statut_validation, ('#6b7280', obj.statut_validation))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:8px;font-size:11px">{}</span>',
            color, label
        )
    statut_badge.short_description = 'Statut'

    @admin.action(description='✓ Valider les dépenses sélectionnées')
    def valider_depenses(self, request, queryset):
        updated = queryset.filter(statut_validation='en_attente').update(statut_validation='validee')
        self.message_user(request, f'{updated} dépense(s) validée(s).')

    @admin.action(description='✗ Rejeter les dépenses sélectionnées')
    def rejeter_depenses(self, request, queryset):
        updated = queryset.filter(statut_validation='en_attente').update(statut_validation='rejetee')
        self.message_user(request, f'{updated} dépense(s) rejetée(s).')


# ─── COMMANDES ────────────────────────────────────────────────────────────────
@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display  = ('nom_client', 'entreprise', 'montant_display',
                     'statut_badge', 'date_livraison_prevue', 'retard_display')
    list_filter   = ('statut', 'entreprise')
    search_fields = ('nom_client', 'telephone_client')
    date_hierarchy = 'date_livraison_prevue'

    _STATUT_COLORS = {
        'devis':      ('#6b7280', '📋 Devis'),
        'en_attente': ('#f59e0b', '⏳ En attente'),
        'en_cours':   ('#3b82f6', '🔨 En cours'),
        'pret':       ('#8b5cf6', '📦 Prêt'),
        'livre':      ('#16a34a', '✓ Livré'),
        'annule':     ('#dc2626', '✗ Annulé'),
    }

    def montant_display(self, obj):
        return format_html(
            '{:,.0f} {} <small style="color:#6b7280">(acompte: {:,.0f})</small>',
            obj.total_commande, obj.entreprise.devise, obj.acompte_verse
        )
    montant_display.short_description = 'Montant / Acompte'

    def statut_badge(self, obj):
        color, label = self._STATUT_COLORS.get(obj.statut, ('#6b7280', obj.statut))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:8px;font-size:11px">{}</span>',
            color, label
        )
    statut_badge.short_description = 'Statut'

    def retard_display(self, obj):
        if obj.date_livraison_prevue and obj.statut not in ('livre', 'annule'):
            today = timezone.now().date()
            if obj.date_livraison_prevue < today:
                jours = (today - obj.date_livraison_prevue).days
                return format_html(
                    '<span style="color:#dc2626;font-weight:bold">⚠ +{}j</span>',
                    jours
                )
        return format_html('<span style="color:#16a34a">{}</span>', '✓')
    retard_display.short_description = 'Retard'


# ─── FOURNISSEURS ─────────────────────────────────────────────────────────────
@admin.register(Fournisseur)
class FournisseurAdmin(admin.ModelAdmin):
    list_display  = ('nom', 'entreprise', 'telephone', 'email', 'dette_display', 'created_at')
    search_fields = ('nom', 'telephone', 'email')
    list_filter   = ('entreprise',)

    def dette_display(self, obj):
        if obj.solde_dette > 0:
            return format_html(
                '<span style="color:#dc2626;font-weight:bold">{:,.0f}</span>',
                obj.solde_dette
            )
        return format_html('<span style="color:#16a34a">{}</span>', '— Soldé')
    dette_display.short_description = 'Dette'


# ─── ACHATS FOURNISSEURS ──────────────────────────────────────────────────────
@admin.register(AchatFournisseur)
class AchatFournisseurAdmin(admin.ModelAdmin):
    list_display    = ('designation', 'fournisseur', 'quantite', 'montant_total',
                       'montant_paye', 'reste_display', 'statut_badge', 'declare_par', 'date_achat')
    list_filter     = ('statut_paiement', 'mode_paiement', 'fournisseur__entreprise')
    search_fields   = ('designation', 'fournisseur__nom')
    date_hierarchy  = 'date_achat'
    readonly_fields = ('declare_par', 'date_achat', 'statut_paiement')

    _STATUT_COLORS = {
        'non_paye': ('#dc2626', 'Non payé'),
        'partiel':  ('#f59e0b', 'Partiel'),
        'paye':     ('#16a34a', '✓ Soldé'),
    }

    def reste_display(self, obj):
        reste = obj.montant_total - obj.montant_paye
        if reste > 0:
            return format_html(
                '<span style="color:#dc2626;font-weight:bold">{:,.0f}</span>',
                reste
            )
        return format_html('<span style="color:#16a34a">{}</span>', '—')
    reste_display.short_description = 'Reste'

    def statut_badge(self, obj):
        color, label = self._STATUT_COLORS.get(obj.statut_paiement, ('#6b7280', obj.statut_paiement))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:8px;font-size:11px">{}</span>',
            color, label
        )
    statut_badge.short_description = 'Paiement'


# ─── MOUVEMENTS DE CAISSE ─────────────────────────────────────────────────────
@admin.register(MouvementCaisse)
class MouvementCaisseAdmin(admin.ModelAdmin):
    list_display    = ('type_badge', 'entreprise', 'montant_display', 'solde_avant',
                       'solde_apres', 'created_by', 'date_mouvement')
    list_filter     = ('type_mouvement', 'entreprise', 'created_by')
    search_fields   = ('notes',)
    date_hierarchy  = 'date_mouvement'
    readonly_fields = ('created_by', 'date_mouvement', 'solde_avant', 'solde_apres', 'created_at')

    _TYPE_COLORS = {
        'ouverture':  ('#3b82f6', '🔓 Ouverture'),
        'depot':      ('#16a34a', '↑ Dépôt'),
        'retrait':    ('#dc2626', '↓ Retrait'),
        'ajustement': ('#f59e0b', '⚖ Ajustement'),
    }

    def type_badge(self, obj):
        color, label = self._TYPE_COLORS.get(obj.type_mouvement, ('#6b7280', obj.type_mouvement))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:8px;font-size:11px">{}</span>',
            color, label
        )
    type_badge.short_description = 'Type'

    def montant_display(self, obj):
        return format_html('<b>{:,.0f}</b>', obj.montant)
    montant_display.short_description = 'Montant'


# ─── CLIENTS ──────────────────────────────────────────────────────────────────
@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display  = ('nom', 'entreprise', 'telephone', 'credit_display')
    search_fields = ('nom', 'telephone')
    list_filter   = ('entreprise',)

    def credit_display(self, obj):
        if obj.solde_credit > 0:
            return format_html(
                '<span style="color:#dc2626;font-weight:bold">💳 {:,.0f}</span>',
                obj.solde_credit
            )
        return format_html('<span style="color:#9ca3af">{}</span>', '—')
    credit_display.short_description = 'Crédit impayé'


# ─── PERSONNALISATION ADMIN ───────────────────────────────────────────────────
admin.site.site_header  = 'IKA GESTION — Administration'
admin.site.site_title   = 'IKA Admin'
admin.site.index_title  = 'Tableau de bord opérateur'
