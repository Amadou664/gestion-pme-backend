from django.contrib import admin
from .models import (
    Entreprise, User, Article, Client,
    Vente, LigneVente, Depense, Commande,
    Fournisseur, AchatFournisseur, PaiementCredit, MouvementCaisse,
)


@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    list_display = ('nom', 'devise', 'created_at')


@admin.register(Vente)
class VenteAdmin(admin.ModelAdmin):
    list_display  = ('numero_sequentiel', 'entreprise', 'vendeur', 'total_ttc', 'statut', 'mode_paiement', 'date_vente')
    list_filter   = ('statut', 'mode_paiement')
    search_fields = ('nom_client_libre', 'client__nom')


@admin.register(PaiementCredit)
class PaiementCreditAdmin(admin.ModelAdmin):
    list_display = ('vente', 'montant', 'mode_paiement', 'date_paiement', 'enregistre_par')
    list_filter  = ('mode_paiement',)


@admin.register(Fournisseur)
class FournisseurAdmin(admin.ModelAdmin):
    list_display  = ('nom', 'entreprise', 'telephone', 'email', 'solde_dette')
    search_fields = ('nom', 'telephone')


@admin.register(AchatFournisseur)
class AchatFournisseurAdmin(admin.ModelAdmin):
    list_display = ('designation', 'fournisseur', 'quantite', 'montant_total', 'montant_paye', 'statut_paiement', 'date_achat')
    list_filter  = ('statut_paiement', 'mode_paiement')


@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display = ('nom_client', 'entreprise', 'total_commande', 'statut', 'date_livraison_prevue')
    list_filter  = ('statut',)


@admin.register(Depense)
class DepenseAdmin(admin.ModelAdmin):
    list_display = ('entreprise', 'fournisseur', 'montant', 'categorie', 'statut_validation', 'date_depense')
    list_filter  = ('statut_validation', 'categorie')


@admin.register(MouvementCaisse)
class MouvementCaisseAdmin(admin.ModelAdmin):
    list_display  = ('entreprise', 'type_mouvement', 'montant', 'solde_avant', 'solde_apres', 'created_by', 'date_mouvement')
    list_filter   = ('type_mouvement',)
    search_fields = ('notes',)


admin.site.register(User)
admin.site.register(Article)
admin.site.register(Client)
admin.site.register(LigneVente)
