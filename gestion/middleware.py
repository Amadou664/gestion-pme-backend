from django.contrib.auth.models import AnonymousUser
from rest_framework.authtoken.models import Token
from django.utils.deprecation import MiddlewareMixin

class TokenURLMiddleware(MiddlewareMixin):
    """

    Permet l'authentification via un paramètre 'token' dans l'URL.

    Utile pour l'ouverture des PDF dans un nouvel onglet sur le Web.

    """
    def process_request(self, request):
        # 1. On récupère le token dans l'URL (?token=...)
        token_key = request.GET.get('token')
        
        # 2. Si un token est présent et que l'utilisateur n'est pas encore connecté
        if token_key:
            try:
                # On cherche le token dans la table de Django REST Framework
                token = Token.objects.select_related('user').get(key=token_key)
                # On "force" l'utilisateur sur la requête
                request.user = token.user
            except Token.DoesNotExist:
                # Si le token est invalide, on laisse AnonymousUser
                pass