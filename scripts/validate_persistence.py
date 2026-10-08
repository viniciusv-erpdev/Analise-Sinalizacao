"""Read-only audit: python manage.py shell < scripts/validate_persistence.py.

Run on a frozen SQLite COPY and on the imported PostgreSQL database.
Output contains counts and hashes, never record contents or credentials.
"""
import datetime
import hashlib
import json

from django.apps import apps
from django.core import serializers
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ValidationError


class FullPrecisionEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, (datetime.datetime, datetime.time)):
            return value.isoformat()
        return super().default(value)


manifest = {}
errors = []
for model in sorted(apps.get_models(include_auto_created=True), key=lambda m: m._meta.label_lower):
    label = model._meta.label_lower
    queryset = model._default_manager.all()
    for field in model._meta.fields:
        if field.many_to_one or field.one_to_one:
            target = field.remote_field.model._default_manager.values_list(field.target_field.name, flat=True)
            orphans = queryset.filter(**{f"{field.attname}__isnull": False}).exclude(**{f"{field.attname}__in": target}).count()
            if orphans:
                errors.append(f"{label}.{field.name}: {orphans} orphan references")
    if model._meta.app_label == "signaling" and not model._meta.auto_created:
        for record in queryset.iterator():
            try:
                record.full_clean()
            except ValidationError:
                errors.append(f"{label} pk={record.pk}: invalid data (review privately)")
    # Auto-created M2M tables have backend-dependent surrogate IDs.
    # Their counts and FKs are checked here; their links are hashed on the parent.
    if model._meta.auto_created:
        manifest[label] = {"count": queryset.count()}
        continue
    rows = serializers.serialize(
        "python", queryset.order_by("pk"), use_natural_foreign_keys=True,
        use_natural_primary_keys=label in {"contenttypes.contenttype", "auth.permission"},
    )
    for row in rows:
        for field in model._meta.many_to_many:
            row["fields"][field.name] = sorted(row["fields"][field.name], key=lambda value: json.dumps(value, sort_keys=True))
    canonical = sorted(json.dumps(row, sort_keys=True, ensure_ascii=True, cls=FullPrecisionEncoder) for row in rows)
    manifest[label] = {"count": len(rows), "sha256": hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest()}
print(json.dumps(manifest, indent=2, sort_keys=True))
if errors:
    raise RuntimeError("Persistence validation failed:\n" + "\n".join(errors))
