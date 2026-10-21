from django.contrib import admin

from signaling.authorization import ADD, CHANGE, DELETE, VIEW
from signaling.models import SignalingIntervention, SignalingPoint


class WaypointAccessAdmin(admin.ModelAdmin):
    """Keep native model checks AND require the waypoint aggregate policy."""
    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and request.user.has_perm(VIEW)

    def has_add_permission(self, request):
        return super().has_add_permission(request) and request.user.has_perms(
            (VIEW, self.waypoint_add_permission)
        )

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and request.user.has_perms(
            (VIEW, CHANGE)
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and request.user.has_perms(
            (VIEW, self.waypoint_delete_permission)
        )


@admin.register(SignalingPoint)
class SignalingPointAdmin(WaypointAccessAdmin):
    waypoint_add_permission = ADD
    waypoint_delete_permission = DELETE


@admin.register(SignalingIntervention)
class SignalingInterventionAdmin(WaypointAccessAdmin):
    waypoint_add_permission = CHANGE
    waypoint_delete_permission = CHANGE
