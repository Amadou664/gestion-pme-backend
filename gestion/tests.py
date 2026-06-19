from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Article, Client, Entreprise, User


class AuthAndRoutingTests(APITestCase):
    def setUp(self):
        self.entreprise = Entreprise.objects.create(
            nom="Entreprise Test",
            devise="CFA",
        )
        self.user = User.objects.create_user(
            username="admin_test",
            email="admin@test.com",
            password="motdepasse123",
            entreprise=self.entreprise,
            role="admin",
        )
        self.token = Token.objects.create(user=self.user)

    def test_login_response_contains_username(self):
        response = self.client.post(
            "/api/auth/login/",
            {
                "email": "admin@test.com",
                "password": "motdepasse123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["username"], "admin_test")
        self.assertEqual(response.data["entreprise_nom"], "Entreprise Test")

    def test_clients_route_is_available(self):
        Client.objects.create(
            entreprise=self.entreprise,
            nom="Client 1",
            telephone="70000000",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        response = self.client.get("/api/clients/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["nom"], "Client 1")

    def test_create_vente_with_lignes_and_stock_update(self):
        article = Article.objects.create(
            entreprise=self.entreprise,
            nom='Produit Test',
            prix_achat=1000,
            prix_vente=2000,
            stock=10,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        response = self.client.post(
            "/api/ventes/",
            {
                "mode_paiement": "especes",
                "lignes": [{"article": article.id, "quantite": 2}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        article.refresh_from_db()
        self.assertEqual(article.stock, 8)
        self.assertEqual(float(response.data["total_ttc"]), 4000.0)
        self.assertTrue("id" in response.data)
