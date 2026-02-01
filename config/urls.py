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
# Importe tout ce dont tu as besoin depuis gestion.views
from gestion import views 

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Routes d'authentification (via l'objet views)
    path('api/auth/login/', views.CustomAuthToken.as_view(), name='login'),
    path('api/auth/register/', views.RegisterEntrepriseView.as_view(), name='register_entreprise'),
    
    # Nouvelles routes pour le profil
    path('api/auth/update-avatar/', views.update_avatar, name='update_avatar'),
    path('api/auth/update-business-name/', views.update_business_name, name='update_name'),
    
    # Inclusion des autres routes (gestion/urls.py)
    path('api/', include('gestion.urls')),
]

# Servir les fichiers médias (logos) en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)