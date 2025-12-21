from django.contrib import admin

# gestion/admin.py
from django.contrib import admin
from .models import Entreprise, User, Article, Client, Vente, Depense

# gestion/admin.py
@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    list_display = ('nom', 'devise', 'logo')  # Les colonnes affichées dans la liste

# Enregistrement simple
admin.site.register(User)
admin.site.register(Article)
admin.site.register(Client)
admin.site.register(Vente)
admin.site.register(Depense)
