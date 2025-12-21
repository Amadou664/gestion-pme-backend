# gestion/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ArticleViewSet, ClientViewSet, VenteViewSet, 
    DepenseViewSet, ReportingViewSet
)

# Initialisation du routeur
router = DefaultRouter()
router.register(r'articles', ArticleViewSet, basename='article')
router.register(r'clients', ClientViewSet, basename='client')
router.register(r'ventes', VenteViewSet, basename='vente')
router.register(r'depenses', DepenseViewSet, basename='depense')
router.register(r'reporting', ReportingViewSet, basename='reporting')

# IMPORTANT : On définit les urlpatterns sans inclure 'gestion.urls' ici
urlpatterns = [
    path('', include(router.urls)),
]