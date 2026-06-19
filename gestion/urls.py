# gestion/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ArticleViewSet, ClientViewSet, VenteViewSet,
    DepenseViewSet, ReportingViewSet, CommandeViewSet,
    EntrepriseUserViewSet, FournisseurViewSet,
    AchatFournisseurViewSet, PaiementCreditViewSet,
    MouvementCaisseViewSet,
)

router = DefaultRouter()
router.register(r'articles',          ArticleViewSet,          basename='article')
router.register(r'clients',           ClientViewSet,           basename='client')
router.register(r'ventes',            VenteViewSet,            basename='vente')
router.register(r'depenses',          DepenseViewSet,          basename='depense')
router.register(r'reporting',         ReportingViewSet,        basename='reporting')
router.register(r'commandes',         CommandeViewSet,         basename='commande')
router.register(r'utilisateurs',      EntrepriseUserViewSet,   basename='utilisateur')
router.register(r'fournisseurs',      FournisseurViewSet,      basename='fournisseur')
router.register(r'achats',            AchatFournisseurViewSet, basename='achat')
router.register(r'paiements-credit',  PaiementCreditViewSet,   basename='paiement-credit')
router.register(r'caisse',            MouvementCaisseViewSet,  basename='caisse')

urlpatterns = [
    path('', include(router.urls)),
]
