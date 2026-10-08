from dataclasses import dataclass
from typing import Protocol

from analysis.map_data import INDIVIDUAL_FILTER_CATEGORIES


GRAVITY_LABELS = {
    "all": "Todas",
    "fatal": "Somente fatais",
    "non_fatal": "Somente não fatais",
}
MONTH_LABELS = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)
CATEGORY_LABELS = dict(INDIVIDUAL_FILTER_CATEGORIES)


class QueryParameters(Protocol):
    def get(self, key: str, default: object = None) -> object: ...
    def getlist(self, key: str) -> list[str]: ...


class InvalidIndividualReportFilters(ValueError):
    """Indica que a URL pediu um recorte incompatível com a análise."""


@dataclass(frozen=True)
class IndividualReportFilters:
    years: tuple[int, ...] = ()
    months: tuple[int, ...] = ()
    categories: tuple[str, ...] = ()
    gravity: str = "all"

    def apply(
        self,
        accidents: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        selected_categories = set(self.categories)
        return [
            accident
            for accident in accidents
            if (
                (
                    not selected_categories
                    or accident.get("category") in selected_categories
                )
                and self._matches_gravity(accident)
                and self._matches_period(accident)
            )
        ]

    def presentation(self) -> dict[str, str]:
        if not self.years and not self.months:
            period = "Todos os períodos disponíveis"
        else:
            year_text = (
                _join_labels([str(year) for year in self.years])
                if self.years else "Todos os anos"
            )
            month_text = (
                _join_labels([MONTH_LABELS[month - 1] for month in self.months])
                if self.months else "Todos os meses disponíveis"
            )
            period = f"Anos: {year_text}. Meses: {month_text}."
        categories = (
            ", ".join(CATEGORY_LABELS[value] for value in self.categories)
            if self.categories
            else "Todas"
        )
        return {
            "period": period,
            "categories": categories,
            "gravity": GRAVITY_LABELS[self.gravity],
        }

    def _matches_gravity(self, accident: dict[str, object]) -> bool:
        if self.gravity == "all":
            return True
        is_fatal = (
            bool(accident.get("is_fatal"))
            or accident.get("record_type") == "SINISTRO FATAL"
        )
        return is_fatal if self.gravity == "fatal" else not is_fatal

    def _matches_period(self, accident: dict[str, object]) -> bool:
        if self.years and accident.get("year") not in self.years:
            return False
        return not self.months or accident.get("month") in self.months


def parse_individual_report_filters(
    parameters: QueryParameters,
    accidents: list[dict[str, object]],
    current_analysis_id: str | None = None,
) -> IndividualReportFilters:
    requested_analysis_id = parameters.get("analysis")
    if (
        requested_analysis_id is not None
        and requested_analysis_id != current_analysis_id
    ):
        raise InvalidIndividualReportFilters(
            "Os filtros informados pertencem a outra análise."
        )

    years = _parse_integer_collection(parameters, "year")
    months = _parse_integer_collection(parameters, "month")
    if any(not 1 <= month <= 12 for month in months):
        raise InvalidIndividualReportFilters("O mês informado é inválido.")

    available_periods = {
        (accident.get("year"), accident.get("month"))
        for accident in accidents
        if isinstance(accident.get("year"), int)
        and isinstance(accident.get("month"), int)
    }
    available_years = {year for year, _ in available_periods}
    if set(years) - available_years:
        raise InvalidIndividualReportFilters(
            "Um ou mais anos informados não pertencem à análise atual."
        )
    relevant_periods = {
        (year, month)
        for year, month in available_periods
        if not years or year in years
    }
    available_months = {month for _, month in relevant_periods}
    if set(months) - available_months:
        raise InvalidIndividualReportFilters(
            "Um ou mais meses informados não pertencem aos anos selecionados."
        )

    requested_categories = parameters.getlist("category")
    invalid_categories = set(requested_categories) - set(CATEGORY_LABELS)
    if invalid_categories:
        raise InvalidIndividualReportFilters(
            "Uma ou mais categorias informadas são inválidas."
        )
    categories = tuple(
        value for value in CATEGORY_LABELS if value in requested_categories
    )

    gravity = str(parameters.get("gravity", "all") or "all")
    if gravity not in GRAVITY_LABELS:
        raise InvalidIndividualReportFilters(
            "O filtro de gravidade informado é inválido."
        )
    return IndividualReportFilters(years, months, categories, gravity)


def _parse_integer_collection(
    parameters: QueryParameters,
    name: str,
) -> tuple[int, ...]:
    values = [value for value in parameters.getlist(name) if value != ""]
    if not values:
        return ()
    try:
        parsed = [int(value) for value in values]
    except (TypeError, ValueError) as error:
        raise InvalidIndividualReportFilters(
            f"O parâmetro {name} é inválido."
        ) from error
    return tuple(dict.fromkeys(parsed))


def _join_labels(labels: list[str]) -> str:
    if len(labels) < 2:
        return labels[0] if labels else ""
    return f"{', '.join(labels[:-1])} e {labels[-1]}"
