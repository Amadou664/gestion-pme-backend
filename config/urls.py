"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

# config/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from gestion.views import CustomAuthToken, RegisterEntrepriseView

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Routes d'authentification
    path('api/auth/login/', CustomAuthToken.as_view(), name='login'),
    path('api/auth/register/', RegisterEntrepriseView.as_view(), name='register_entreprise'),
    
    # Inclusion des routes de l'application gestion (Articles, Ventes, etc.)
    path('api/', include('gestion.urls')),
]

# Servir les fichiers médias (logos) en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)