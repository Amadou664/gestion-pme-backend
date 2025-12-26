# gestion/serializers.py
from rest_framework import serializers
from django.db import transaction
from .models import User, Entreprise, Article, Vente, LigneVente, Depense, Client 
from decimal import Decimal
from django.db.models import Sum

# --- 1. SÉRIALIZERS D'AUTHENTIFICATION ---

class UserSerializer(serializers.ModelSerializer):
    entreprise_nom = serializers.CharField(source='entreprise.nom', read_only=True)
    entreprise_id = serializers.IntegerField(source='entreprise.id', read_only=True)
    entreprise_logo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'entreprise_id', 'entreprise_nom', 'entreprise_logo')

    def get_entreprise_logo(self, obj):
        if obj.entreprise and obj.entreprise.logo:
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(obj.entreprise.logo.url)
            return obj.entreprise.logo.url
        return None

class EntrepriseRegistrationSerializer(serializers.Serializer):
    entreprise_nom = serializers.CharField(max_length=100, write_only=True) 
    logo = serializers.ImageField(required=False, allow_null=True, write_only=True) 
    devise = serializers.CharField(max_length=3, default='CFA', write_only=True) 
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Cet email est déjà utilisé.")
        return value

    def create(self, validated_data):
        with transaction.atomic():
            entreprise = Entreprise.objects.create(
                nom=validated_data['entreprise_nom'],
                logo=validated_data.get('logo', None),
                devise=validated_data.get('devise', 'CFA')
            )
            user = User.objects.create_user(
                username=validated_data['username'],
                email=validated_data['email'],
                password=validated_data['password'],
                entreprise=entreprise,
                role='admin'
            )
            return user

    def to_representation(self, instance):
        return UserSerializer(instance, context=self.context).data


# --- 2. SÉRIALIZERS DE GESTION ---

class ArticleSerializer(serializers.ModelSerializer):
    # Ajout du champ calculé pour le nombre total vendu
    total_vendus = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = ['id', 'nom', 'code', 'prix_achat', 'prix_vente', 'stock', 'seuil_alerte', 'total_vendus']
        read_only_fields = ('entreprise',) 

    def get_total_vendus(self, obj):
        # On calcule la somme des quantités dans LigneVente pour cet article
        # On filtre pour exclure les ventes annulées
        resultat = LigneVente.objects.filter(
            article=obj, 
            vente__statut='payee' # On ne compte que les ventes payées
        ).aggregate(total=Sum('quantite'))['total']
        
        return resultat or 0 # Retourne 0 si aucune vente n'a été faite

class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = '__all__'
        read_only_fields = ('entreprise', 'solde_credit')

class DepenseSerializer(serializers.ModelSerializer):
    declaree_par_nom = serializers.CharField(source='declaree_par.username', read_only=True)

    class Meta:
        model = Depense
        fields = ('id', 'motif', 'montant', 'fournisseur','categorie', 'date_depense', 'declaree_par_nom', 'statut_validation')
        read_only_fields = ('entreprise', 'declaree_par', 'statut_validation')


# --- 3. SÉRIALIZERS DE VENTES ---

class LigneVenteSerializer(serializers.ModelSerializer):
    article_nom = serializers.CharField(source='article.nom', read_only=True)
    
    class Meta:
        model = LigneVente
        fields = ('id', 'article', 'article_nom', 'quantite', 'prix_unitaire', 'remise_pct', 'sous_total')
        read_only_fields = ('prix_unitaire', 'sous_total')


class VenteSerializer(serializers.ModelSerializer):
    lignes = LigneVenteSerializer(many=True) # Retrait de write_only pour faciliter certains retours
    client_nom = serializers.CharField(source='client.nom', read_only=True)
    vendeur_nom = serializers.CharField(source='vendeur.username', read_only=True)

    class Meta:
        model = Vente
        fields = (
            'id', 'client', 'client_nom', 'nom_client_libre', 'date_vente', 
            'total_ttc', 'mode_paiement', 'statut', 'lignes', 'numero_sequentiel', 'vendeur_nom'
        )
        read_only_fields = ('total_ttc', 'vendeur', 'entreprise', 'numero_sequentiel', 'statut')

    @transaction.atomic
    def create(self, validated_data):
        lignes_data = validated_data.pop('lignes')
        request = self.context.get('request')
        
        # Sécurité : on extrait tout ce qui est passé manuellement par perform_create
        # pour éviter les doublons dans le **validated_data
        vendeur = validated_data.pop('vendeur', request.user)
        entreprise = validated_data.pop('entreprise', None)
        statut = validated_data.pop('statut', 'payee')

        # Création de la vente avec les variables extraites
        vente = Vente.objects.create(
            vendeur=vendeur,
            entreprise=entreprise,
            statut=statut,
            **validated_data  # Ne contient plus entreprise, vendeur ou statut
        )
        
        total_vente_ttc = Decimal('0.0')

        for ligne_data in lignes_data:
            article = ligne_data['article']
            quantite = Decimal(str(ligne_data['quantite']))
            
            # 1. Vérification du stock (on utilise .stock comme dans les vues)
            if article.stock < quantite:
                raise serializers.ValidationError(
                    f"Stock insuffisant pour {article.nom}. Disponible : {article.stock}"
                )

            # 2. Calculs financiers
            prix_unitaire = article.prix_vente
            remise_pct = Decimal(str(ligne_data.get('remise_pct', 0)))
            
            reduction = (prix_unitaire * remise_pct) / Decimal('100.0')
            prix_final_unitaire = prix_unitaire - reduction
            sous_total = prix_final_unitaire * quantite

            # 3. Mise à jour du stock
            article.stock -= quantite
            article.save()

            # 4. Création de la ligne avec archivage du prix d'achat actuel pour le reporting
            LigneVente.objects.create(
                vente=vente,
                article=article,
                quantite=quantite,
                prix_unitaire=prix_unitaire,
                remise_pct=remise_pct,
                sous_total=sous_total,
                # Optionnel mais recommandé : prix_achat_archive=article.prix_achat
            )
            
            total_vente_ttc += sous_total
        
        # Mise à jour finale du total de la vente
        vente.total_ttc = total_vente_ttc
        vente.save()

        return vente