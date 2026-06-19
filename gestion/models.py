# gestion/models.py

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models import Max, Sum

USER_ROLES = (
    ('admin', 'Admin Entreprise'),
    ('manager', 'Manager'),
    ('caissier', 'Caissier'),
    ('comptable', 'Comptable'),
    ('lecture_seule', 'Lecture Seule'),
)

MODES_PAIEMENT = [
    ('especes',      'Espèces'),
    ('orange_money', 'Orange Money'),
    ('wave',         'Wave'),
    ('moov_money',   'Moov Money'),
    ('banque',       'Virement bancaire'),
    ('carte',        'Carte bancaire'),
]


# 1. Entreprises
class Entreprise(models.Model):
    nom              = models.CharField(max_length=100)
    logo             = models.ImageField(upload_to='logos/', blank=True, null=True)
    devise           = models.CharField(max_length=3, default='CFA')
    tva_default      = models.DecimalField(max_digits=5, decimal_places=2, default=20.00)
    couleur_primaire = models.CharField(max_length=7, default='#1976D2')
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Entreprises"

    def __str__(self):
        return self.nom


# 2. Utilisateurs
class User(AbstractUser):
    email      = models.EmailField(unique=True)
    entreprise = models.ForeignKey(
        Entreprise, on_delete=models.CASCADE, null=True, blank=True,
        help_text="L'entreprise à laquelle cet utilisateur est rattaché."
    )
    role      = models.CharField(max_length=20, choices=USER_ROLES, default='lecture_seule')
    last_seen = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['username']

    groups = models.ManyToManyField(
        'auth.Group', related_name='gestion_user_set', blank=True,
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission', related_name='gestion_user_permissions', blank=True,
    )

    def __str__(self):
        return self.email


# 3. Fournisseurs
class Fournisseur(models.Model):
    entreprise  = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    nom         = models.CharField(max_length=150)
    telephone   = models.CharField(max_length=20, blank=True)
    email       = models.EmailField(blank=True)
    adresse     = models.TextField(blank=True)
    solde_dette = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                      help_text="Montant total dû à ce fournisseur.")
    notes       = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering            = ['nom']
        verbose_name_plural = "Fournisseurs"

    def __str__(self):
        return f"{self.nom} ({self.entreprise.nom})"


# 4. Articles (Produits)
class Article(models.Model):
    entreprise  = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    code        = models.CharField(max_length=50, blank=True, null=True,
                                   help_text="Code-barres ou référence SKU.")
    nom         = models.CharField(max_length=150)
    prix_achat  = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    prix_vente  = models.DecimalField(max_digits=10, decimal_places=2)
    archived    = models.BooleanField(default=False)
    stock       = models.IntegerField(default=0)
    seuil_alerte = models.IntegerField(default=5)

    @property
    def en_alerte(self):
        return self.stock <= self.seuil_alerte

    def save(self, *args, **kwargs):
        if self.code is not None:
            self.code = self.code.strip() or None
        super().save(*args, **kwargs)

    class Meta:
        indexes       = [models.Index(fields=['entreprise'])]
        unique_together = ('entreprise', 'code')

    def __str__(self):
        return f"{self.nom} ({self.entreprise.nom})"


# 5. Achats Fournisseur
class AchatFournisseur(models.Model):
    STATUTS_PAIEMENT = [
        ('non_paye', 'Non payé'),
        ('partiel',  'Partiellement payé'),
        ('paye',     'Payé'),
    ]

    entreprise      = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    fournisseur     = models.ForeignKey(Fournisseur, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='achats')
    article         = models.ForeignKey(Article, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='achats_fournisseur')
    designation     = models.CharField(max_length=200,
                                       help_text="Nom libre si l'article n'est pas en stock.")
    quantite        = models.IntegerField(default=1)
    prix_unitaire   = models.DecimalField(max_digits=10, decimal_places=2)
    montant_total   = models.DecimalField(max_digits=12, decimal_places=2)
    montant_paye    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    mode_paiement   = models.CharField(max_length=20, choices=MODES_PAIEMENT, default='especes')
    statut_paiement = models.CharField(max_length=20, choices=STATUTS_PAIEMENT, default='non_paye')
    date_achat      = models.DateField()
    notes           = models.TextField(blank=True)
    declare_par     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-date_achat']

    @property
    def reste_a_payer(self):
        return self.montant_total - self.montant_paye

    def _update_statut(self):
        if self.montant_paye >= self.montant_total:
            self.statut_paiement = 'paye'
        elif self.montant_paye > 0:
            self.statut_paiement = 'partiel'
        else:
            self.statut_paiement = 'non_paye'

    def save(self, *args, **kwargs):
        self._update_statut()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Achat {self.designation} — {self.fournisseur}"


# 6. Clients
class Client(models.Model):
    entreprise   = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    nom          = models.CharField(max_length=150)
    telephone    = models.CharField(max_length=20, blank=True)
    adresse      = models.TextField(blank=True)
    solde_credit = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                       help_text="Montant total dû par ce client.")

    class Meta:
        indexes = [models.Index(fields=['entreprise', 'nom'])]

    def __str__(self):
        return self.nom


# 7. Ventes
class Vente(models.Model):
    entreprise            = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    vendeur               = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    client                = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    nom_client_libre      = models.CharField(max_length=255, null=True, blank=True)
    telephone_client_libre = models.CharField(max_length=20, null=True, blank=True)
    date_vente            = models.DateTimeField(auto_now_add=True)
    total_ttc             = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    acompte               = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                                help_text="Acompte versé pour les ventes à crédit.")
    mode_paiement         = models.CharField(max_length=20, choices=MODES_PAIEMENT, default='especes')
    statut                = models.CharField(max_length=20, default='payee',
                                             choices=[('payee', 'Payée'), ('annulee', 'Annulée'), ('credit', 'À crédit')])
    numero_sequentiel     = models.IntegerField(default=1)

    def save(self, *args, **kwargs):
        if not self.pk:
            last_num = (
                Vente.objects.filter(entreprise=self.entreprise)
                .aggregate(m=Max('numero_sequentiel'))
                .get('m')
            )
            self.numero_sequentiel = int(last_num or 0) + 1
        super().save(*args, **kwargs)

    @property
    def montant_paye_credit(self):
        return self.paiements_credit.aggregate(s=Sum('montant'))['s'] or 0

    @property
    def montant_restant_credit(self):
        return max(self.total_ttc - self.acompte - self.montant_paye_credit, 0)

    def __str__(self):
        return f"Vente #{self.numero_sequentiel} ({self.entreprise.nom})"


# 8. Paiements Crédit
class PaiementCredit(models.Model):
    vente          = models.ForeignKey(Vente, on_delete=models.CASCADE, related_name='paiements_credit')
    montant        = models.DecimalField(max_digits=10, decimal_places=2)
    mode_paiement  = models.CharField(max_length=20, choices=MODES_PAIEMENT, default='especes')
    date_paiement  = models.DateTimeField(auto_now_add=True)
    notes          = models.TextField(blank=True)
    enregistre_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-date_paiement']

    def __str__(self):
        return f"Paiement {self.montant} sur Vente #{self.vente.numero_sequentiel}"


# 9. Lignes de Vente
class LigneVente(models.Model):
    vente         = models.ForeignKey(Vente, related_name='lignes', on_delete=models.CASCADE)
    article       = models.ForeignKey(Article, on_delete=models.SET_NULL, null=True, blank=True)
    quantite      = models.IntegerField()
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2)
    remise_pct    = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sous_total    = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"Ligne {self.id} — Vente #{self.vente.numero_sequentiel}"


# 10. Dépenses
class Depense(models.Model):
    STATUTS = [
        ('en_attente', 'En attente'),
        ('validee',    'Validée'),
        ('rejetee',    'Rejetée'),
    ]
    entreprise        = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    declaree_par      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    categorie         = models.CharField(max_length=50)
    montant           = models.DecimalField(max_digits=10, decimal_places=2)
    fournisseur       = models.CharField(max_length=255, blank=True, null=True, default="Inconnu")
    justificatif_url  = models.URLField(blank=True, null=True)
    motif             = models.TextField(blank=True)
    statut_validation = models.CharField(max_length=20, choices=STATUTS, default='en_attente')
    date_depense      = models.DateField()

    def __str__(self):
        return f"Dépense {self.id} — {self.fournisseur} ({self.montant})"


# 11. Commandes Personnalisées
class Commande(models.Model):
    STATUTS_COMMANDE = [
        ('devis',      'Devis'),
        ('en_attente', 'En attente'),
        ('en_cours',   'En fabrication'),
        ('pret',       'Prêt / Terminé'),
        ('livre',      'Livré'),
        ('annule',     'Annulé'),
    ]

    entreprise           = models.ForeignKey(Entreprise, on_delete=models.CASCADE)
    vendeur              = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    nom_client           = models.CharField(max_length=150)
    telephone_client     = models.CharField(max_length=20, blank=True)
    ville_client         = models.CharField(max_length=100, blank=True)
    bois                 = models.CharField(max_length=100, blank=True)
    tissu                = models.CharField(max_length=100, blank=True)
    description          = models.TextField(blank=True)
    date_commande        = models.DateTimeField(auto_now_add=True)
    date_livraison_prevue = models.DateField()
    total_commande       = models.DecimalField(max_digits=10, decimal_places=2)
    acompte_verse        = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    statut               = models.CharField(max_length=20, choices=STATUTS_COMMANDE, default='devis')

    class Meta:
        ordering = ['-date_commande']

    @property
    def reste_a_payer(self):
        return self.total_commande - self.acompte_verse

    def __str__(self):
        return f"Commande {self.nom_client} — {self.total_commande} {self.entreprise.devise}"


# 12. Mouvements de Caisse
class MouvementCaisse(models.Model):
    TYPES = [
        ('ouverture', 'Ouverture caisse'),
        ('depot',     'Dépôt / Alimentation'),
        ('retrait',   'Retrait'),
        ('ajustement','Ajustement'),
    ]
    entreprise      = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name='mouvements_caisse')
    type_mouvement  = models.CharField(max_length=20, choices=TYPES, default='depot')
    montant         = models.DecimalField(max_digits=12, decimal_places=2)
    solde_avant     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    solde_apres     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes           = models.TextField(blank=True)
    created_by      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='mouvements_caisse')
    created_at      = models.DateTimeField(auto_now_add=True)
    date_mouvement  = models.DateField()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_type_mouvement_display()} {self.montant} — {self.date_mouvement}"

    @classmethod
    def solde_actuel(cls, entreprise_id):
        """Retourne le solde actuel de la caisse pour une entreprise."""
        last = cls.objects.filter(entreprise_id=entreprise_id).order_by('-created_at').first()
        return last.solde_apres if last else 0
