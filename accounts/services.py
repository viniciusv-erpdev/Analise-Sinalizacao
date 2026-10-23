"""Atomic public registration, without modifying existing accounts or groups."""
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction


@transaction.atomic
def register_analyst(form):
    """Accept a validated RegistrationForm; never provision permissions here."""
    try:
        group = Group.objects.get(name="analista")
    except Group.DoesNotExist as error:
        raise ImproperlyConfigured("Registration requires the existing analista group.") from error
    user = form.save(commit=False)
    user.is_active = True
    user.is_staff = False
    user.is_superuser = False
    user.save()
    user.groups.add(group)
    return user
