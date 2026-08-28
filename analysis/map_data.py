import pandas as pd


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
            "collision_criterion": bool(
                row["collision_criterion"]
            ),
            "pedestrian_criterion": bool(
                row["pedestrian_criterion"]
            ),
            "eligible": bool(row["eligible"]),
            "criterion": str(row["criterion"]),
        }

        map_data.append(item)

    return map_data