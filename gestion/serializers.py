# gestion/serializers.py
from rest_framework import serializers
from django.db import transaction
from .models import User, Entreprise, Article, Vente, LigneVente, Depense, Client 
from decimal import Decimal

# --- 1. SÉRIALIZERS D'AUTHENTIFICATION ET DE BASE ---

# Serializer d'Utilisateur (pour les infos de connexion/réponse)
class UserSerializer(serializers.ModelSerializer):
    entreprise_nom = serializers.CharField(source='entreprise.nom', read_only=True)
    entreprise_id = serializers.IntegerField(source='entreprise.id', read_only=True)
    # On utilise SerializerMethodField pour construire l'URL complète dynamiquement
    entreprise_logo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'entreprise_id', 'entreprise_nom', 'entreprise_logo')

    def get_entreprise_logo(self, obj):
        """Retourne l'URL complète du logo si elle existe"""
        if obj.entreprise and obj.entreprise.logo:
            # Récupère l'objet request pour construire une URL absolue (avec http://127.0.0.1:8000)
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(obj.entreprise.logo.url)
            # Fallback si la requête n'est pas dans le contexte
            return obj.entreprise.logo.url
        return None

# Serializer d'Inscription
class EntrepriseRegistrationSerializer(serializers.Serializer):
    entreprise_nom = serializers.CharField(max_length=100, write_only=True) 
    # MODIFICATION ICI : ImageField au lieu de URLField
    logo = serializers.ImageField(required=False, allow_null=True, write_only=True) 
    devise = serializers.CharField(max_length=3, default='EUR', write_only=True) 
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Cet email est déjà utilisé.")
        return value

    def create(self, validated_data):
        with transaction.atomic():
            # 1. Création de l'Entreprise avec le logo
            entreprise = Entreprise.objects.create(
                nom=validated_data['entreprise_nom'],
                logo=validated_data.get('logo', None), # RÉCUPÉRATION DU LOGO
                devise=validated_data.get('devise', 'EUR')
            )
            
            # 2. Création de l'Utilisateur Admin
            user = User.objects.create_user(
                username=validated_data['username'],
                email=validated_data['email'],
                password=validated_data['password'],
                entreprise=entreprise,
                role='admin'
            )
            return user

    def to_representation(self, instance):
        return UserSerializer(instance).data


# --- 3. SÉRIALIZERS DE GESTION ---

# 3. Serializer pour les Articles (Catalogue)
class ArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Article
        fields = '__all__'
        read_only_fields = ('entreprise',) 

# 4. Serializer pour les Clients
class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = '__all__'
        read_only_fields = ('entreprise', 'solde_credit')

# 5. Serializer pour les Dépenses
class DepenseSerializer(serializers.ModelSerializer):
    declaree_par_nom = serializers.CharField(source='declaree_par.username', read_only=True)

    class Meta:
        model = Depense
        # On liste explicitement les champs pour être certain
        fields = ('id', 'motif', 'montant', 'categorie', 'date_depense', 'declaree_par_nom', 'statut_validation')
        read_only_fields = ('entreprise', 'declaree_par', 'statut_validation')
        
# --- 6. SÉRIALIZERS DE VENTES (Logique Imbriquée) ---

# 6. Serializer pour les Lignes de Vente (détail du ticket)
class LigneVenteSerializer(serializers.ModelSerializer):
    article_nom = serializers.CharField(source='article.nom', read_only=True)
    
    class Meta:
        model = LigneVente
        fields = ('id', 'article', 'article_nom', 'quantite', 'prix_unitaire', 'remise_pct', 'sous_total')
        extra_kwargs = {
            'prix_unitaire': {'read_only': True}, 
            'sous_total': {'read_only': True}     
        }


# 7. Serializer pour la Vente (avec imbrication des lignes)
class VenteSerializer(serializers.ModelSerializer):
    lignes = LigneVenteSerializer(many=True, write_only=True) 
    lignes_detail = LigneVenteSerializer(source='lignes', read_only=True, many=True) 
    client_nom = serializers.CharField(source='client.nom', read_only=True)

    class Meta:
        model = Vente
        fields = ('id', 'client', 'client_nom', 'nom_client_libre', 'date_vente', 'total_ttc', 'mode_paiement', 'statut', 'lignes', 'lignes_detail', 'numero_sequentiel')
        read_only_fields = ('total_ttc', 'vendeur', 'entreprise')

    @transaction.atomic
    def create(self, validated_data):
        lignes_data = validated_data.pop('lignes')
        vente = Vente.objects.create(**validated_data)
        total_vente_ttc = Decimal('0.0') # Initialisé en Decimal

        for ligne_data in lignes_data:
            article = ligne_data['article']
            quantite = ligne_data['quantite']
            
            if article.stock_actuel < quantite:
                transaction.set_rollback(True)
                raise serializers.ValidationError(
                    f"Stock insuffisant pour l'article {article.nom}. Disponible : {article.stock_actuel}"
                )

            # --- CORRECTION DU CALCUL ICI ---
            prix_unitaire = article.prix_vente
            remise_pct = ligne_data.get('remise_pct', 0)
            
            # On convertit tout en Decimal pour éviter le TypeError
            remise_dec = Decimal(str(remise_pct)) / Decimal('100.0')
            facteur_multiplicateur = Decimal('1.0') - remise_dec
            
            prix_applique_ttc = prix_unitaire * facteur_multiplicateur
            sous_total = prix_applique_ttc * Decimal(str(quantite))
            # -------------------------------

            total_vente_ttc += sous_total

            article.stock_actuel -= quantite
            article.save()

            LigneVente.objects.create(
                vente=vente,
                prix_unitaire=prix_unitaire,
                sous_total=sous_total,
                **ligne_data
            )
        
        vente.total_ttc = total_vente_ttc
        vente.save()

        return vente