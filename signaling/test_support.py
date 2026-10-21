from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client

WAYPOINT_PERMISSIONS = (
    "view_signalingpoint", "add_signalingpoint", "change_signalingpoint",
    "delete_signalingpoint", "generate_signaling_report",
)


def authorize(client, permissions=WAYPOINT_PERMISSIONS):
    user = get_user_model().objects.create_user(
        username=f"test-user-{get_user_model().objects.count()}",
    )
    user.user_permissions.set(Permission.objects.filter(
        content_type__app_label="signaling", codename__in=permissions,
    ))
    client.force_login(user)
    return user


def authorized_client(permissions=WAYPOINT_PERMISSIONS):
    client = Client()
    authorize(client, permissions)
    return client
