from django.contrib.auth.models import AnonymousUser
from rest_framework.authtoken.models import Token
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone


class ApiCsrfExemptMiddleware(MiddlewareMixin):
    """
    Les endpoints REST `/api/` utilisent l'authentification Token.
    On evite que CsrfViewMiddleware bloque les POST/PATCH/DELETE JSON de
    Flutter Web, tout en gardant la protection CSRF pour `/admin/`.
    """
    def process_request(self, request):
        path = request.path_info or ''
        if path.startswith('/api/'):
            request._dont_enforce_csrf_checks = True

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

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.lower().startswith('token '):
            token_key = auth_header.split(' ', 1)[1].strip()
            try:
                token = Token.objects.select_related('user').get(key=token_key)
                request.user = token.user
            except Token.DoesNotExist:
                pass

        user = getattr(request, 'user', None)
        if getattr(user, 'is_authenticated', False):
            now = timezone.now()
            last_seen = getattr(user, 'last_seen', None)
            if last_seen is None or last_seen < now - timezone.timedelta(seconds=30):
                type(user).objects.filter(pk=user.pk).update(last_seen=now)
