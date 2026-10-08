import pandas as pd


INDIVIDUAL_MODE_COLUMNS = {
    "pedestrian_count": "Pedestre",
    "bicycle_count": "Bicicleta",
    "motorcycle_count": "Motocicleta",
    "car_count": "Automóvel",
    "bus_count": "Ônibus",
    "truck_count": "Caminhão",
    "other_vehicle_count": "Outros veículos",
    "unavailable_vehicle_count": "Veículo não disponível",
}


INDIVIDUAL_TYPE_PRESENTATION = {
    "ATROPELAMENTO": ("Atropelamento", "pedestrian"),
    "CHOQUE": ("Choque", "crash"),
    "COLISAO": ("Colisão", "collision"),
    "NAO_DISPONIVEL": ("Não disponível", "unavailable"),
    "OUTRO": ("Outros", "other"),
}

INDIVIDUAL_FILTER_CATEGORIES = (
    ("pedestrian", "Atropelamento"),
    ("crash", "Choque"),
    ("collision", "Colisão"),
    ("unavailable", "Não disponível"),
    ("other", "Outros"),
)


def _safe_quantity(value: object) -> int:
    if pd.isna(value):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


MAP_COLUMNS = [
    "cluster_id",
    "latitude",
    "longitude",
    "location",
    "location_type",
    "collisions_1y",
    "pedestrians_1y",
    "collisions_3y",
    "pedestrians_3y",
    "collision_1y_met",
    "collision_3y_met",
    "pedestrian_1y_met",
    "pedestrian_3y_met",
    "collision_criterion",
    "pedestrian_criterion",
    "criterion",
    "eligible",
]


def build_map_data(results: pd.DataFrame) -> list[dict]:
    """
    Prepara os resultados da análise para serem consumidos pelo mapa.

    Apenas clusters elegíveis e com coordenadas válidas são enviados.
    """

    required_columns = set(MAP_COLUMNS)

    missing = required_columns - set(results.columns)

    if missing:
        raise ValueError(
            f"Colunas obrigatórias ausentes: {missing}"
        )

    data = results[
        results["eligible"]
        & results["latitude"].notna()
        & results["longitude"].notna()
    ].copy()

    map_data = []
    period_summaries = results.attrs.get("cluster_period_summaries", {})

    for _, row in data.iterrows():

        item = {
            "cluster_id": int(row["cluster_id"]),
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "location": str(row["location"]),
            "location_type": str(row["location_type"]),
            "collisions_1y": int(row["collisions_1y"]),
            "pedestrians_1y": int(row["pedestrians_1y"]),
            "collisions_3y": int(row["collisions_3y"]),
            "pedestrians_3y": int(row["pedestrians_3y"]),
            "collision_1y_met": bool(row["collision_1y_met"]),
            "collision_3y_met": bool(row["collision_3y_met"]),
            "pedestrian_1y_met": bool(row["pedestrian_1y_met"]),
            "pedestrian_3y_met": bool(row["pedestrian_3y_met"]),
            "collision_criterion": bool(
                row["collision_criterion"]
            ),
            "pedestrian_criterion": bool(
                row["pedestrian_criterion"]
            ),
            "eligible": bool(row["eligible"]),
            "criterion": str(row["criterion"]),
            "period_summary": period_summaries.get(
                int(row["cluster_id"]),
                {"total_count": 0, "unperiodized_count": 0, "counts": []},
            ),
        }

        map_data.append(item)

    return map_data


def build_individual_map_data(accidents: pd.DataFrame) -> list[dict]:
    """Serializa sinistros válidos individualmente para o mapa."""
    required_columns = {
        "id",
        "record_type",
        "date",
        "accident_type",
        "street",
        "latitude",
        "longitude",
        *INDIVIDUAL_MODE_COLUMNS,
    }
    missing = required_columns - set(accidents.columns)
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes: {missing}")

    return [
        build_individual_accident_item(row)
        for _, row in accidents.iterrows()
    ]


def build_individual_accident_item(row: pd.Series) -> dict[str, object]:
    """Serializa um sinistro individual normalizado."""
    type_label, category = INDIVIDUAL_TYPE_PRESENTATION.get(
        row["accident_type"],
        ("Outros", "other"),
    )
    modes = []
    for column, label in INDIVIDUAL_MODE_COLUMNS.items():
        quantity = _safe_quantity(row[column])
        if quantity > 0:
            modes.append({"name": label, "quantity": quantity})
    date = row["date"]
    street = row["street"]
    record_type = row["record_type"]
    year = row.get("year", pd.NA)
    month = row.get("month", pd.NA)

    return {
        "id": str(row["id"]),
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "year": None if pd.isna(year) else int(year),
        "month": None if pd.isna(month) else int(month),
        "is_fatal": (
            not pd.isna(record_type)
            and str(record_type) == "SINISTRO FATAL"
        ),
        "record_type": (
            "Não disponível"
            if pd.isna(record_type) or not str(record_type).strip()
            else str(record_type)
        ),
        "date": (
            "Não disponível"
            if pd.isna(date)
            else date.strftime("%d/%m/%Y")
        ),
        "accident_type": type_label,
        "category": category,
        "street": (
            "Não disponível"
            if pd.isna(street) or not str(street).strip()
            else str(street)
        ),
        "modes": modes,
    }
