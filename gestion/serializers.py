# gestion/serializers.py
from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.db.models import Sum

from .models import (
    User, Entreprise, Article, Vente, LigneVente, Depense,
    Client, Commande, Fournisseur, AchatFournisseur, PaiementCredit,
    MouvementCaisse, MODES_PAIEMENT,
)

# ─────────────────────────────────────────────
# 1. AUTHENTIFICATION
# ─────────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    entreprise_nom    = serializers.CharField(source='entreprise.nom', read_only=True)
    entreprise_id     = serializers.IntegerField(source='entreprise.id', read_only=True)
    entreprise_logo   = serializers.SerializerMethodField()
    is_online         = serializers.SerializerMethodField()
    last_seen_formatee = serializers.DateTimeField(
        source='last_seen', format="%Y-%m-%d %H:%M:%S", read_only=True,
    )

    class Meta:
        model  = User
        fields = (
            'id', 'username', 'email', 'role', 'is_active', 'last_seen',
            'last_seen_formatee', 'is_online', 'entreprise_id',
            'entreprise_nom', 'entreprise_logo',
        )

    def get_entreprise_logo(self, obj):
        if obj.entreprise and obj.entreprise.logo:
            return obj.entreprise.logo.url
        return None

    def get_is_online(self, obj):
        if not obj.last_seen:
            return False
        return obj.last_seen >= timezone.now() - timedelta(minutes=5)


class EntrepriseUserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6)
    role     = serializers.ChoiceField(
        choices=[c[0] for c in User._meta.get_field('role').choices],
        error_messages={'required': 'Le rôle est requis.'}
    )

    def validate_username(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError("Le nom d'utilisateur est requis.")
        req = self.context.get('request')
        ent = req.user.entreprise if req else None
        if User.objects.filter(username__iexact=value, entreprise=ent).exists():
            raise serializers.ValidationError("Ce nom d'utilisateur est déjà utilisé.")
        return value

    def validate_email(self, value):
        value = (value or '').strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Cet email est déjà utilisé.")
        return value

    def validate(self, attrs):
        req = self.context.get('request')
        if not req or not req.user.entreprise:
            raise serializers.ValidationError("Entreprise introuvable.")
        return attrs

    def create(self, validated_data):
        req = self.context.get('request')
        return User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            entreprise=req.user.entreprise,
            role=validated_data.get('role', 'lecture_seule'),
        )

    def to_representation(self, instance):
        return UserSerializer(instance, context=self.context).data


class EntrepriseUserUpdateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, min_length=6)

    class Meta:
        model  = User
        fields = ('username', 'role', 'is_active', 'password')

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class EntrepriseRegistrationSerializer(serializers.Serializer):
    entreprise_nom = serializers.CharField(max_length=100, write_only=True)
    logo           = serializers.ImageField(required=False, allow_null=True, write_only=True)
    devise         = serializers.CharField(max_length=3, default='CFA', write_only=True)
    username       = serializers.CharField(max_length=150)
    email          = serializers.EmailField()
    password       = serializers.CharField(write_only=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Cet email est déjà utilisé.")
        return value

    def create(self, validated_data):
        with transaction.atomic():
            essai_expire = timezone.now().date() + timedelta(days=14)
            entreprise = Entreprise.objects.create(
                nom=validated_data['entreprise_nom'],
                logo=validated_data.get('logo'),
                devise=validated_data.get('devise', 'CFA'),
                plan='premium',
                plan_expire=essai_expire,
            )
            user = User.objects.create_user(
                username=validated_data['username'],
                email=validated_data['email'],
                password=validated_data['password'],
                entreprise=entreprise,
                role='admin',
            )
            return user

    def to_representation(self, instance):
        return UserSerializer(instance, context=self.context).data


# ─────────────────────────────────────────────
# 2. FOURNISSEURS
# ─────────────────────────────────────────────

class FournisseurSerializer(serializers.ModelSerializer):
    total_achats      = serializers.SerializerMethodField()
    nb_achats         = serializers.SerializerMethodField()

    class Meta:
        model        = Fournisseur
        fields       = (
            'id', 'nom', 'telephone', 'email', 'adresse',
            'solde_dette', 'notes', 'created_at',
            'total_achats', 'nb_achats',
        )
        read_only_fields = ('entreprise', 'solde_dette', 'created_at')

    def get_total_achats(self, obj):
        return float(obj.achats.aggregate(s=Sum('montant_total'))['s'] or 0)

    def get_nb_achats(self, obj):
        return obj.achats.count()


class AchatFournisseurSerializer(serializers.ModelSerializer):
    fournisseur_nom     = serializers.CharField(source='fournisseur.nom', read_only=True)
    article_nom         = serializers.CharField(source='article.nom', read_only=True, default='')
    declare_par_nom     = serializers.CharField(source='declare_par.username', read_only=True)
    reste_a_payer       = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    mode_paiement_label = serializers.SerializerMethodField()

    class Meta:
        model  = AchatFournisseur
        fields = (
            'id', 'fournisseur', 'fournisseur_nom', 'article', 'article_nom',
            'designation', 'quantite', 'prix_unitaire', 'montant_total',
            'montant_paye', 'reste_a_payer', 'mode_paiement', 'mode_paiement_label',
            'statut_paiement', 'date_achat', 'notes',
            'declare_par', 'declare_par_nom',
        )
        read_only_fields = ('entreprise', 'declare_par', 'statut_paiement', 'montant_total')

    def get_mode_paiement_label(self, obj):
        return dict(MODES_PAIEMENT).get(obj.mode_paiement, obj.mode_paiement)

    def validate(self, attrs):
        quantite      = attrs.get('quantite', 1)
        prix_unitaire = attrs.get('prix_unitaire', Decimal('0'))
        attrs['montant_total'] = (Decimal(str(prix_unitaire)) * int(quantite)).quantize(Decimal('0.01'))
        return attrs


# ─────────────────────────────────────────────
# 3. ARTICLES
# ─────────────────────────────────────────────

class ArticleSerializer(serializers.ModelSerializer):
    total_vendus = serializers.SerializerMethodField()
    en_alerte    = serializers.BooleanField(read_only=True)

    class Meta:
        model        = Article
        fields       = ['id', 'nom', 'code', 'prix_achat', 'prix_vente',
                        'stock', 'seuil_alerte', 'en_alerte', 'total_vendus', 'archived']
        read_only_fields = ('entreprise',)

    def get_total_vendus(self, obj):
        return LigneVente.objects.filter(
            article=obj, vente__statut='payee'
        ).aggregate(total=Sum('quantite'))['total'] or 0


# ─────────────────────────────────────────────
# 4. CLIENTS
# ─────────────────────────────────────────────

class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model        = Client
        fields       = ['id', 'nom', 'telephone', 'adresse', 'solde_credit']
        read_only_fields = ('entreprise', 'solde_credit')


# ─────────────────────────────────────────────
# 5. VENTES & CRÉDIT
# ─────────────────────────────────────────────

class PaiementCreditSerializer(serializers.ModelSerializer):
    enregistre_par_nom  = serializers.CharField(source='enregistre_par.username', read_only=True)
    mode_paiement_label = serializers.SerializerMethodField()
    date_formatee       = serializers.DateTimeField(
        source='date_paiement', format="%Y-%m-%d %H:%M", read_only=True
    )

    class Meta:
        model  = PaiementCredit
        fields = (
            'id', 'vente', 'montant', 'mode_paiement', 'mode_paiement_label',
            'date_paiement', 'date_formatee', 'notes',
            'enregistre_par', 'enregistre_par_nom',
        )
        read_only_fields = ('enregistre_par', 'date_paiement', 'vente')

    def get_mode_paiement_label(self, obj):
        return dict(MODES_PAIEMENT).get(obj.mode_paiement, obj.mode_paiement)


class LigneVenteSerializer(serializers.ModelSerializer):
    article_nom = serializers.CharField(source='article.nom', read_only=True)

    class Meta:
        model        = LigneVente
        fields       = ('id', 'article', 'article_nom', 'quantite',
                        'prix_unitaire', 'remise_pct', 'sous_total')
        read_only_fields = ('prix_unitaire', 'sous_total')


class VenteSerializer(serializers.ModelSerializer):
    lignes              = LigneVenteSerializer(many=True)
    paiements_credit    = PaiementCreditSerializer(many=True, read_only=True)
    client_nom          = serializers.CharField(source='client.nom', read_only=True, default='')
    client_telephone    = serializers.CharField(source='client.telephone', read_only=True, default='')
    vendeur_nom         = serializers.CharField(source='vendeur.username', read_only=True)
    vendeur_id          = serializers.IntegerField(source='vendeur.id', read_only=True)
    vendeur_email       = serializers.CharField(source='vendeur.email', read_only=True)
    date_vente_formatee = serializers.DateTimeField(
        source='date_vente', format="%Y-%m-%d %H:%M", read_only=True
    )
    montant_restant_credit  = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    mode_paiement_label = serializers.SerializerMethodField()

    class Meta:
        model  = Vente
        fields = (
            'id', 'client', 'client_nom', 'nom_client_libre',
            'client_telephone', 'telephone_client_libre',
            'date_vente', 'date_vente_formatee',
            'total_ttc', 'acompte', 'montant_restant_credit',
            'mode_paiement', 'mode_paiement_label',
            'statut', 'lignes', 'paiements_credit',
            'numero_sequentiel', 'vendeur_id', 'vendeur_nom', 'vendeur_email',
        )
        read_only_fields = (
            'total_ttc', 'vendeur', 'entreprise', 'numero_sequentiel', 'statut',
        )

    def get_mode_paiement_label(self, obj):
        return dict(MODES_PAIEMENT).get(obj.mode_paiement, obj.mode_paiement)

    def validate_lignes(self, value):
        if not value:
            raise serializers.ValidationError("La vente doit contenir au moins une ligne.")
        for i, ligne in enumerate(value, 1):
            if int(ligne.get('quantite', 0)) <= 0:
                raise serializers.ValidationError(
                    {'quantite': f"Quantité invalide à la ligne {i}."}
                )
        return value

    @transaction.atomic
    def create(self, validated_data):
        lignes_data = validated_data.pop('lignes', [])
        request     = self.context.get('request')
        vendeur     = validated_data.pop('vendeur', request.user)
        entreprise  = validated_data.pop('entreprise', None)
        statut      = validated_data.pop('statut', 'payee')
        acompte     = validated_data.get('acompte', Decimal('0'))

        vente = Vente.objects.create(
            vendeur=vendeur, entreprise=entreprise, statut=statut, **validated_data
        )

        total = Decimal('0.00')
        for ligne_data in lignes_data:
            article   = ligne_data['article']
            quantite  = int(ligne_data.get('quantite', 0))
            if article.stock < quantite:
                raise serializers.ValidationError(
                    f"Stock insuffisant pour {article.nom}. Disponible : {article.stock}"
                )
            prix_unitaire = Decimal(str(article.prix_vente or '0'))
            remise_pct    = Decimal(str(ligne_data.get('remise_pct', 0)))
            reduction     = (prix_unitaire * remise_pct) / Decimal('100')
            sous_total    = ((prix_unitaire - reduction) * quantite).quantize(Decimal('0.01'))

            article.stock -= quantite
            article.save(update_fields=['stock'])

            LigneVente.objects.create(
                vente=vente, article=article, quantite=quantite,
                prix_unitaire=prix_unitaire, remise_pct=remise_pct, sous_total=sous_total,
            )
            total += sous_total

        vente.total_ttc = total.quantize(Decimal('0.01'))
        vente.save(update_fields=['total_ttc'])

        # Si vente à crédit → mise à jour solde client
        if statut == 'credit' and vente.client:
            montant_credit = vente.total_ttc - Decimal(str(acompte))
            Client.objects.filter(pk=vente.client_id).update(
                solde_credit=vente.client.solde_credit + montant_credit
            )

        return vente


# ─────────────────────────────────────────────
# 6. DÉPENSES
# ─────────────────────────────────────────────

class DepenseSerializer(serializers.ModelSerializer):
    declaree_par_nom   = serializers.CharField(source='declaree_par.username', read_only=True)
    declaree_par_id    = serializers.IntegerField(source='declaree_par.id', read_only=True)
    declaree_par_email = serializers.CharField(source='declaree_par.email', read_only=True)

    class Meta:
        model  = Depense
        fields = (
            'id', 'motif', 'montant', 'fournisseur', 'categorie',
            'date_depense', 'declaree_par_id', 'declaree_par_nom',
            'declaree_par_email', 'statut_validation',
        )
        read_only_fields = ('entreprise', 'declaree_par', 'statut_validation')


# ─────────────────────────────────────────────
# 7. COMMANDES
# ─────────────────────────────────────────────

class CommandeSerializer(serializers.ModelSerializer):
    date_commande_formatee  = serializers.DateTimeField(
        source='date_commande', format="%Y-%m-%d %H:%M", read_only=True
    )
    date_livraison_formatee = serializers.DateField(
        source='date_livraison_prevue', format="%Y-%m-%d", read_only=True
    )
    reste_a_payer = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model        = Commande
        fields       = '__all__'
        read_only_fields = ['entreprise', 'vendeur']


# ─────────────────────────────────────────────
# 8. MOUVEMENTS DE CAISSE
# ─────────────────────────────────────────────

class MouvementCaisseSerializer(serializers.ModelSerializer):
    created_by_nom        = serializers.CharField(source='created_by.username', read_only=True)
    type_mouvement_label  = serializers.CharField(source='get_type_mouvement_display', read_only=True)
    created_at_formatee   = serializers.DateTimeField(source='created_at', format="%Y-%m-%d %H:%M", read_only=True)

    class Meta:
        model  = MouvementCaisse
        fields = (
            'id', 'type_mouvement', 'type_mouvement_label',
            'montant', 'solde_avant', 'solde_apres',
            'notes', 'date_mouvement',
            'created_by', 'created_by_nom', 'created_at', 'created_at_formatee',
        )
        read_only_fields = ('entreprise', 'created_by', 'solde_avant', 'solde_apres')
