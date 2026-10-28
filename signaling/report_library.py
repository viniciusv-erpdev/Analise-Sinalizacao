"""Authorized, one-row-per-report metadata queries; no snapshots or artifacts."""
from django import forms
from django.db.models import OuterRef, Subquery, Q
from django.db.models.functions import TruncDate
from signaling.report_read_access import official_reports_for, official_versions_for
from signaling.report_snapshots import OFFICIAL_TIMEZONE


class OfficialReportFilters(forms.Form):
    number = forms.RegexField(r"^RTSV-[0-9]{4}-[0-9]{4}$", required=False, max_length=14,
        label="N\u00famero oficial", error_messages={"invalid":"Use RTSV-AAAA-NNNN."})
    year = forms.IntegerField(required=False, min_value=1, max_value=9999, label="Ano do n\u00famero oficial")
    issued_from = forms.DateField(required=False, input_formats=["%Y-%m-%d"], label="Emiss\u00e3o inicial",
        widget=forms.DateInput(attrs={"type":"date"}, format="%Y-%m-%d"))
    issued_to = forms.DateField(required=False, input_formats=["%Y-%m-%d"], label="Emiss\u00e3o final",
        widget=forms.DateInput(attrs={"type":"date"}, format="%Y-%m-%d"))
    author = forms.CharField(required=False, max_length=200, label="Autor hist\u00f3rico")
    waypoint = forms.IntegerField(required=False, min_value=1, max_value=9223372036854775807, label="Waypoint hist\u00f3rico (ID)")

    def clean_number(self):
        number = self.cleaned_data["number"]
        if number:
            _, year, sequence = number.split("-")
            if int(year) < 1 or int(sequence) < 1:
                raise forms.ValidationError("Use ano e sequencia positivos.")
        return number

    def clean(self):
        data = super().clean()
        if hasattr(self.data, "getlist") and any(len(self.data.getlist(key)) > 1 for key in self.fields):
            raise forms.ValidationError("Informe cada filtro apenas uma vez.")
        if data.get("issued_from") and data.get("issued_to") and data["issued_from"] > data["issued_to"]:
            raise forms.ValidationError("O in\u00edcio da emiss\u00e3o deve preceder o fim.")
        return data


def report_rows(user, filters):
    reports = official_reports_for(user)
    latest = official_versions_for(user).filter(report_id=OuterRef("pk")).order_by("-version")
    reports = reports.annotate(
        published_version=Subquery(latest.values("version")[:1]),
        published_issued_at=Subquery(latest.values("issued_at")[:1]),
        historical_author=Subquery(latest.values("author_identity")[:1]),
    ).only("id", "year", "sequence", "waypoint_history")
    if filters.get("number"):
        _, year, sequence = filters["number"].split("-")
        reports = reports.filter(year=int(year), sequence=int(sequence))
    if filters.get("year"):
        reports = reports.filter(year=filters["year"])
    if filters.get("author"):
        reports = reports.filter(Q(historical_author__full_name__icontains=filters["author"]) |
                                 Q(historical_author__username__icontains=filters["author"]))
    if filters.get("waypoint"):
        reports = reports.filter(waypoint_history__id=filters["waypoint"])
    if filters.get("issued_from") or filters.get("issued_to"):
        reports = reports.annotate(emission_date=TruncDate("published_issued_at", tzinfo=OFFICIAL_TIMEZONE))
        if filters.get("issued_from"):
            reports = reports.filter(emission_date__gte=filters["issued_from"])
        if filters.get("issued_to"):
            reports = reports.filter(emission_date__lte=filters["issued_to"])
    return reports.order_by("-published_issued_at", "-year", "-sequence", "pk")
