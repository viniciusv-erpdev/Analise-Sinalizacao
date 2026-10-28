"""Versioned JSON editing source; rendering never consults live ORM/session data."""
from datetime import date, datetime
from io import BytesIO
import hashlib
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import warnings

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from PIL import Image, UnidentifiedImageError

from signaling.forms import SignalingReportForm, MAX_REPORT_PHOTOS, MAX_REPORT_PHOTO_SIZE_BYTES
from signaling.report_drafts import serialize_draft
from signaling.report_generator import generate_signaling_report
from signaling.surveys import capture_point_items

OFFICIAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
SCHEMA_VERSION = 1
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_PHOTOS_TOTAL_BYTES = 24 * 1024 * 1024
MAX_PHOTO_PIXELS = 20_000_000


def canonical(value):
    return json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def point_source(point, draft):
    return {
        "point": {"id": point.pk, "latitude": str(point.latitude), "longitude": str(point.longitude),
                  "status": point.status, "search_radius_meters": point.search_radius_meters,
                  "created_at": point.created_at.isoformat(), "updated_at": point.updated_at.isoformat()},
        "items": capture_point_items(point),
        "draft": {"revision": draft.revision if draft else 0,
                  "fields": serialize_draft(point.pk, draft)["fields"]},
    }


def validate_form(fields):
    form = SignalingReportForm(fields)
    if not form.is_valid():
        raise ValidationError(dict(form.errors))
    return {key: value for key, value in form.cleaned_data.items() if key != "photos"}


def prepare_photos(uploads):
    if len(uploads) > MAX_REPORT_PHOTOS:
        raise ValidationError({"photos": "At most 10 photos"})
    result, total = [], 0
    for index, upload in enumerate(uploads):
        if upload.size > MAX_REPORT_PHOTO_SIZE_BYTES:
            raise ValidationError({"photos": "Photo exceeds 10 MiB"})
        upload.seek(0)
        data = upload.read(MAX_REPORT_PHOTO_SIZE_BYTES + 1)
        total += len(data)
        if len(data) > MAX_REPORT_PHOTO_SIZE_BYTES or total > MAX_PHOTOS_TOTAL_BYTES:
            raise ValidationError({"photos": "Photos exceed size limits (10 MiB each, 24 MiB total)"})
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    if image.format not in ("PNG", "JPEG") or image.width * image.height > MAX_PHOTO_PIXELS:
                        raise ValueError
                    metadata = {"ordinal": index, "format": image.format,
                                "width": image.width, "height": image.height,
                                "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                "content_type": Image.MIME[image.format]}
                    image.verify()
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError,
                Image.DecompressionBombWarning):
            raise ValidationError({"photos": "Invalid JPEG/PNG or image exceeds 20 megapixels"}) from None
        result.append((metadata, data))
    return result


def render_snapshot(snapshot, photos):
    if snapshot["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported_snapshot_schema")
    fields = dict(snapshot["form"])
    for key in ("occurrence_date", "inspection_date"):
        if fields.get(key):
            fields[key] = date.fromisoformat(fields[key])
    identity = snapshot["author"]
    author = SimpleNamespace(is_authenticated=True, get_full_name=lambda: identity["full_name"],
                             get_username=lambda: identity["username"])
    issued_at = datetime.fromisoformat(snapshot["issued_at"]).astimezone(OFFICIAL_TIMEZONE)
    return generate_signaling_report(
        SimpleNamespace(**snapshot["source"]["point"]), snapshot["survey"], fields,
        [BytesIO(photo) for photo in photos], author=author, issued_at=issued_at,
        official_number=snapshot["official_number"],
    ).getvalue()
