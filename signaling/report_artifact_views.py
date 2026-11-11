"""Authorized immutable file delivery; no public storage URLs."""
from pathlib import PurePosixPath
from django.http import FileResponse, Http404
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.vary import vary_on_cookie
from django.views.decorators.http import require_GET
from signaling.report_read_access import get_official_artifact
from signaling.report_storage import PrivateReportStorage, ArtifactStorageError


@never_cache
@cache_control(private=True)
@vary_on_cookie
@require_GET
def report_artifact(request, report_id, version, artifact_id, download=False):
    artifact = get_official_artifact(request.user, report_id, version, artifact_id)
    suffix = PurePosixPath(artifact.storage_key).suffix
    types = {
        ("PDF", ".pdf"): "application/pdf",
        ("DOCX", ".docx"): "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ("PHOTO", ".png"): "image/png",
        ("PHOTO", ".jpg"): "image/jpeg",
    }
    content_type = types.get((artifact.kind, suffix))
    if not content_type or artifact.content_type != content_type or (not download and artifact.kind == "DOCX"):
        raise Http404("Report file not found")
    # Generate a safe name from server-owned identifiers, never a storage path.
    filename = f"RTSV-{artifact.version.report.year:04d}-{artifact.version.report.sequence:04d}-v{version}"
    if artifact.kind == "PHOTO":
        filename += f"-foto-{artifact.ordinal + 1}"
    try:
        stream = PrivateReportStorage().open_verified(artifact)
    except ArtifactStorageError:
        raise Http404("Report file not found") from None
    try:
        response = FileResponse(stream, as_attachment=download,
                                filename=filename + suffix, content_type=content_type)
    except Exception:
        stream.close()
        raise
    response["X-Content-Type-Options"] = "nosniff"
    return response
