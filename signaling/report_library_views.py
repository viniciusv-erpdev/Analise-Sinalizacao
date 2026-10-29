"""Published metadata only. No document download or finalization operations."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, InvalidPage
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.vary import vary_on_cookie
from django.views.decorators.http import require_GET
from signaling.report_read_access import can_view_official_reports
from signaling.report_library import OfficialReportFilters, report_rows


@never_cache
@vary_on_cookie
@require_GET
@login_required
def report_library(request):
    if not can_view_official_reports(request.user):
        return HttpResponseForbidden("Sem permiss\u00e3o para consultar relat\u00f3rios oficiais.")
    form = OfficialReportFilters(request.GET)
    page = None
    status = 200
    if form.is_valid():
        raw_page = request.GET.get("page", "1")
        if len(request.GET.getlist("page")) > 1 or not raw_page.isascii() or not raw_page.isdecimal() or len(raw_page) > 10:
            raise Http404("P\u00e1gina inexistente")
        try:
            page = Paginator(report_rows(request.user, form.cleaned_data), 20).page(int(raw_page))
        except InvalidPage:
            raise Http404("P\u00e1gina inexistente") from None
    else:
        status = 400
    query = request.GET.copy()
    for name in list(query):
        if name not in form.fields:
            del query[name]
    navigation_query = query.copy()
    if page is not None and page.number > 1:
        navigation_query["page"] = str(page.number)
    return render(request, "signaling/report_library.html", {
        "filters": form, "page_obj": page, "filter_query": query.urlencode(), "filters_valid": status == 200,
        "library_query": navigation_query.urlencode(),
    }, status=status)


@never_cache
@vary_on_cookie
@require_GET
def report_detail(request, report_id):
    # The centralized getter hides both absent and unauthorized objects, even
    # for anonymous requests. Never load snapshots or private artifact records.
    from signaling.report_read_access import get_official_report, official_versions_for

    report = get_official_report(request.user, report_id)
    versions = list(official_versions_for(request.user).filter(report_id=report.pk)
        .only("id", "report_id", "version", "issued_at", "finalized_at",
              "author_identity", "snapshot_sha256", "schema_version")
        .order_by("-issued_at", "-version", "pk"))
    if not versions:
        raise Http404("Report object not found")
    from signaling.report_read_access import official_artifacts_for
    artifacts = official_artifacts_for(request.user).filter(version_id__in=[v.pk for v in versions]).only(
        "id", "version_id", "kind", "ordinal").order_by("kind", "ordinal", "pk")
    by_version = {v.pk: [] for v in versions}
    for artifact in artifacts:
        by_version[artifact.version_id].append(artifact)
    for published in versions:
        published.visible_artifacts = by_version[published.pk]
        published.document_artifacts = sorted(
            (a for a in published.visible_artifacts if a.kind in ("PDF", "DOCX")),
            key=lambda artifact: artifact.kind != "PDF")
        published.photo_artifacts = [a for a in published.visible_artifacts if a.kind == "PHOTO"]
    return_query = request.GET.copy()
    for name in list(return_query):
        if name not in (*OfficialReportFilters.base_fields, "page"):
            del return_query[name]
    latest = max(versions, key=lambda version: version.version)
    return render(request, "signaling/report_detail.html", {
        "report": report, "versions": versions, "latest_version": latest,
        "library_return_query": return_query.urlencode(),
    })
