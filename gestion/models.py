from django.db import models
from django.contrib.auth.models import AbstractUser
from decimal import Decimal

# Définition des Rôles
USER_ROLES = (
    ('admin', 'Admin Entreprise'),
    ('manager', 'Manager'),
    ('caissier', 'Caissier'),
    ('comptable', 'Comptable'),
    ('lecture_seule', 'Lecture Seule'),
)

# 1. Gestion des Entreprises
class Entreprise(models.Model):
    nom = models.CharField(max_length=100)
    logo = models.ImageField(upload_to='logos/', blank=True, null=True) 
    devise = models.CharField(max_length=3, default='CFA')
    tva_default = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    couleur_primaire = models.CharField(max_length=7, default='#1976D2')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Entreprises"

    def __str__(self):
        return self.nom

# 2. Utilisateurs personnalisés
class User(AbstractUser):
    email = models.EmailField(unique=True) 
    entreprise = models.ForeignKey(
        Entreprise, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True
    )
    role = models.CharField(max_length=20, choices=USER_ROLES, default='caissier')

    USERNAME_FIELD = 'email'  
    REQUIRED_FIELDS = ['username'] 

    def __str__(self):
        return f"{self.email} ({self.role})"

# 3. Articles (Produits)
class Article(models.Model):
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    code = models.CharField(max_length=50, blank=True, help_text="Code-barres ou SKU.")
    nom = models.CharField(max_length=150)
    prix_achat = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    prix_vente = models.DecimalField(max_digits=10, decimal_places=2)
    stock_actuel = models.IntegerField(default=0)
    seuil_alerte = models.IntegerField(default=5)
    archived = models.BooleanField(default=False)

    @property
    def en_alerte(self):
        return self.stock_actuel <= self.seuil_alerte
    
    class Meta:
        unique_together = ('entreprise', 'code') # Code unique par boutique
        indexes = [models.Index(fields=['entreprise'])]

    def __str__(self):
        return f"{self.nom} - {self.entreprise.nom}"

# 4. Clients
class Client(models.Model):
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    nom = models.CharField(max_length=150)
    telephone = models.CharField(max_length=20, blank=True)
    adresse = models.TextField(blank=True)
    solde_credit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    def __str__(self):
        return self.nom

# 5. Ventes (Entêtes)
class Vente(models.Model):
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    vendeur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    nom_client_libre = models.CharField(max_length=255, null=True, blank=True)
    date_vente = models.DateTimeField(auto_now_add=True)
    total_ttc = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    mode_paiement = models.CharField(
        max_length=20, 
        choices=[('especes', 'Espèces'), ('carte', 'Carte'), ('mobile_money', 'Mobile Money')],
        default='especes'
    )
    statut = models.CharField(
        max_length=20, 
        default='payee', 
        choices=[('payee', 'Payée'), ('annulee', 'Annulée'), ('credit', 'Crédit')]
    )
    numero_sequentiel = models.IntegerField(default=1)

    def save(self, *args, **kwargs):
        if not self.pk:
            derniere_vente = Vente.objects.filter(entreprise=self.entreprise).order_by('numero_sequentiel').last()
            self.numero_sequentiel = (derniere_vente.numero_sequentiel + 1) if derniere_vente else 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Vente #{self.numero_sequentiel} - {self.entreprise.nom}"

# 6. Lignes de Vente
class LigneVente(models.Model):
    vente = models.ForeignKey(Vente, related_name='lignes', on_delete=models.CASCADE)
    article = models.ForeignKey(Article, on_delete=models.PROTECT) # On protège l'article
    quantite = models.IntegerField()
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2)
    remise_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sous_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    def save(self, *args, **kwargs):
        # Calcul auto du sous-total
        reduction = (self.prix_unitaire * self.remise_pct) / Decimal('100.0')
        self.sous_total = (self.prix_unitaire - reduction) * self.quantite
        super().save(*args, **kwargs)

# 7. Dépenses
class Depense(models.Model):
    STATUTS = [('en_attente', 'En attente'), ('validee', 'Validée'), ('rejetee', 'Rejetée')]
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    declaree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    categorie = models.CharField(max_length=50) 
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    justificatif = models.ImageField(upload_to='depenses/', blank=True, null=True)
    motif = models.TextField(blank=True)
    statut_validation = models.CharField(max_length=20, choices=STATUTS, default='en_attente')
    date_depense = models.DateField()