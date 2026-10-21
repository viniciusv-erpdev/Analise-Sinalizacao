from django.contrib import admin

from signaling.authorization import VIEW
from django.core.exceptions import PermissionDenied
from signaling.models import SignalingIntervention, SignalingPoint


class WaypointAccessAdmin(admin.ModelAdmin):
    """Read-only signaling until the Admin participates in the reservation protocol."""
    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and request.user.has_perm(VIEW)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        return {}

    def save_model(self, request, obj, form, change):
        raise PermissionDenied("Alterações exigem o protocolo de reservas.")

    def delete_model(self, request, obj):
        raise PermissionDenied("Exclusões exigem o protocolo de reservas.")

    def delete_queryset(self, request, queryset):
        raise PermissionDenied("Exclusões exigem o protocolo de reservas.")


@admin.register(SignalingPoint)
class SignalingPointAdmin(WaypointAccessAdmin):
    pass


@admin.register(SignalingIntervention)
class SignalingInterventionAdmin(WaypointAccessAdmin):
    pass
