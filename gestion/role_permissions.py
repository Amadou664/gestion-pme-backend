from __future__ import annotations
from rest_framework.permissions import BasePermission, SAFE_METHODS


def _role_from_user(user) -> str:
    role = getattr(user, "role", None)
    if not role:
        return "lecture_seule"
    return str(role).strip().lower()


class RoleBasedPermission(BasePermission):
    """
    Permission basée sur le rôle (admin/manager/caissier/comptable/lecture_seule).
    Définir `role_action_matrix` sur un ViewSet pour surcharger la matrice.
    """

    READ_ALL = {"admin", "manager", "caissier", "comptable", "lecture_seule"}

    DEFAULT_MATRIX = {
        "ArticleViewSet": {
            "__read__":  READ_ALL,
            "__write__": {"admin", "manager"},
            "archiver":  {"admin", "manager"},
        },
        "ClientViewSet": {
            "__read__":  READ_ALL,
            "__write__": {"admin", "manager", "comptable"},
        },
        "FournisseurViewSet": {
            "__read__":  {"admin", "manager", "comptable"},
            "__write__": {"admin", "manager"},
        },
        "AchatFournisseurViewSet": {
            "__read__":  {"admin", "manager", "comptable"},
            "__write__": {"admin", "manager"},
            "payer":     {"admin", "manager", "comptable"},
        },
        "PaiementCreditViewSet": {
            "__read__":  {"admin", "manager", "comptable"},
        },
        "CommandeViewSet": {
            "__read__":  READ_ALL,
            "__write__": {"admin", "manager", "caissier"},
            "destroy":   {"admin", "manager"},
            "solder":    {"admin", "manager", "caissier"},
        },
        "VenteViewSet": {
            "__read__":    READ_ALL,
            "__write__":   {"admin", "manager", "caissier"},
            "annuler":     {"admin", "manager"},
            "supprimer":   {"admin", "manager"},
            "payer_credit": {"admin", "manager", "caissier", "comptable"},
            "facture_pdf": READ_ALL,
        },
        "DepenseViewSet": {
            "__read__":  READ_ALL,
            "__write__": {"admin", "manager", "comptable"},
        },
        "ReportingViewSet": {
            "__read__":          {"admin", "manager", "comptable"},
            "financial_summary": {"admin", "manager", "comptable"},
            "daily_report":      {"admin", "manager", "comptable"},
        },
        "EntrepriseUserViewSet": {
            "__read__":  {"admin"},
            "__write__": {"admin"},
            "heartbeat": READ_ALL,
            "online":    {"admin"},
        },
        "MouvementCaisseViewSet": {
            "__read__":   {"admin", "manager", "comptable"},
            "__write__":  {"admin", "manager"},
            "solde":      {"admin", "manager", "caissier", "comptable"},
            "flux_ventes":{"admin", "manager", "comptable"},
        },
    }

    def _get_allowed_roles(self, view, action: str, is_write: bool) -> set[str] | None:
        view_name = view.__class__.__name__
        matrix    = getattr(view, "role_action_matrix", None) or self.DEFAULT_MATRIX.get(view_name)
        if not matrix:
            return None
        if action in matrix:
            return set(matrix[action])
        key = "__write__" if is_write else "__read__"
        return set(matrix.get(key, set()))

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True

        role     = _role_from_user(user)
        action   = getattr(view, "action", None) or request.method.lower()
        is_write = request.method not in SAFE_METHODS

        allowed = self._get_allowed_roles(view, action, is_write)
        if allowed is None:
            return True
        return role in allowed
