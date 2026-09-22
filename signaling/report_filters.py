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
    year: int | None = None
    month: int | None = None
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
        if self.year is None:
            period = "Todos os períodos"
        elif self.month is None:
            period = str(self.year)
        else:
            period = f"{self.year} — {MONTH_LABELS[self.month - 1]}"
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
        if self.year is None:
            return True
        if accident.get("year") != self.year:
            return False
        return self.month is None or accident.get("month") == self.month


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

    year = _parse_optional_integer(parameters, "year")
    month = _parse_optional_integer(parameters, "month")
    if month is not None and year is None:
        raise InvalidIndividualReportFilters(
            "Selecione um ano antes de informar o mês."
        )
    if month is not None and not 1 <= month <= 12:
        raise InvalidIndividualReportFilters("O mês informado é inválido.")

    available_periods = {
        (accident.get("year"), accident.get("month"))
        for accident in accidents
        if isinstance(accident.get("year"), int)
        and isinstance(accident.get("month"), int)
    }
    if year is not None:
        if not any(item_year == year for item_year, _ in available_periods):
            raise InvalidIndividualReportFilters(
                "O ano informado não pertence à análise atual."
            )
        if month is not None and (year, month) not in available_periods:
            raise InvalidIndividualReportFilters(
                "O mês informado não pertence ao ano selecionado."
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
    return IndividualReportFilters(year, month, categories, gravity)


def _parse_optional_integer(
    parameters: QueryParameters,
    name: str,
) -> int | None:
    values = parameters.getlist(name)
    if not values or values == [""]:
        return None
    if len(values) != 1:
        raise InvalidIndividualReportFilters(
            f"O parâmetro {name} foi informado mais de uma vez."
        )
    try:
        value = int(values[0])
    except (TypeError, ValueError) as error:
        raise InvalidIndividualReportFilters(
            f"O parâmetro {name} é inválido."
        ) from error
    return value
