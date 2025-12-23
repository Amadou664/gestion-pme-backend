# gestion/models.py

from django.db import models
from django.contrib.auth.models import AbstractUser

# Définition des Rôles (Pour le champ 'role' de l'utilisateur)
USER_ROLES = (
    ('admin', 'Admin Entreprise'),
    ('manager', 'Manager'),
    ('caissier', 'Caissier'),
    ('comptable', 'Comptable'),
    ('lecture_seule', 'Lecture Seule'),
)

# 1. Gestion des Entreprises (Multi-tenancy)
class Entreprise(models.Model):
    nom = models.CharField(max_length=100)
    # MODIFICATION : On passe de URLField à ImageField
    logo = models.ImageField(upload_to='logos/', blank=True, null=True) 
    devise = models.CharField(max_length=3, default='EUR')
    tva_default = models.DecimalField(max_digits=5, decimal_places=2, default=20.00)
    couleur_primaire = models.CharField(max_length=7, default='#1976D2')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Entreprises"

    def __str__(self):
        return self.nom

# 2. Utilisateurs personnalisés (Hérite d'AbstractUser)
class User(AbstractUser):
    # On rend l'email unique et obligatoire
    email = models.EmailField(unique=True) 
    
    entreprise = models.ForeignKey(
        Entreprise, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        help_text="L'entreprise à laquelle cet utilisateur est rattaché."
    )
    role = models.CharField(max_length=20, choices=USER_ROLES, default='lecture_seule')

    # --- AJOUTEZ CES DEUX LIGNES ICI ---
    USERNAME_FIELD = 'email'  # Définit l'email comme identifiant de connexion
    REQUIRED_FIELDS = ['username'] # 'username' reste requis mais n'est plus l'identifiant
    # ----------------------------------

    groups = models.ManyToManyField(
        'auth.Group',
        related_name='gestion_user_set', 
        blank=True,
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='gestion_user_permissions', 
        blank=True,
    )

    def __str__(self):
        return self.email

# 3. Articles (Produits)
class Article(models.Model):
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    code = models.CharField(max_length=50, blank=True, unique=True, help_text="Code-barres ou référence SKU.")
    nom = models.CharField(max_length=150)
    prix_achat = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    prix_vente = models.DecimalField(max_digits=10, decimal_places=2)
    archived = models.BooleanField(default=False)
    stock = models.IntegerField(default=0)
    seuil_alerte = models.IntegerField(default=5)  # Ajout de ce champ

    @property
    def en_alerte(self):
        return self.stock <= self.seuil_alerte
    
    class Meta:
        indexes = [models.Index(fields=['entreprise'])]
        unique_together = ('entreprise', 'code')

    def __str__(self):
        return f"{self.nom} ({self.entreprise.nom})"

# 4. Clients
class Client(models.Model):
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    nom = models.CharField(max_length=150)
    telephone = models.CharField(max_length=20, blank=True)
    adresse = models.TextField(blank=True)
    solde_credit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    class Meta:
        indexes = [models.Index(fields=['entreprise', 'nom'])] 

    def __str__(self):
        return self.nom

# 5. Ventes (Entêtes - l'équivalent du ticket)
class Vente(models.Model):
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    vendeur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    nom_client_libre = models.CharField(max_length=255, null=True, blank=True)
    date_vente = models.DateTimeField(auto_now_add=True)
    total_ttc = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    mode_paiement = models.CharField(max_length=20, choices=[(c, c.capitalize()) for c, _ in [('especes', 'Espèces'), ('carte', 'Carte'), ('mobile_money', 'Mobile Money')]])
    statut = models.CharField(max_length=20, default='payee', choices=[(s, s.capitalize()) for s in ['payee', 'annulee', 'credit']])
    numero_sequentiel = models.IntegerField(default=1) # Numéro propre à l'entreprise

    def save(self, *args, **kwargs):
        if not self.pk: # Si c'est une nouvelle vente
            # On cherche la dernière vente de CETTE entreprise uniquement
            derniere_vente = Vente.objects.filter(entreprise=self.entreprise).order_by('numero_sequentiel').last()
            if derniere_vente:
                self.numero_sequentiel = derniere_vente.numero_sequentiel + 1
            else:
                self.numero_sequentiel = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Vente #{self.id} ({self.entreprise.nom})"

# 6. Lignes de Vente (Détail)
class LigneVente(models.Model):
    vente = models.ForeignKey(Vente, related_name='lignes', on_delete=models.CASCADE)
    article = models.ForeignKey(Article, on_delete=models.SET_NULL, null=True, blank=True)
    quantite = models.IntegerField()
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2)
    remise_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sous_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    def __str__(self):
        return f"Ligne {self.id} de Vente {self.vente.id}"

# 7. Dépenses
class Depense(models.Model):
    STATUTS = [
        ('en_attente', 'En attente'),
        ('validee', 'Validée'),
        ('rejetee', 'Rejetée'),
    ]
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    declaree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    categorie = models.CharField(max_length=50) 
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    justificatif_url = models.URLField(blank=True, null=True)
    motif = models.TextField(blank=True)
    statut_validation = models.CharField(max_length=20, choices=STATUTS, default='en_attente')
    date_depense = models.DateField()
    
    def __str__(self):
        return f"Dépense {self.id} ({self.montant})"