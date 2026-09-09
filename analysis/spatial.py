import numpy as np
import pandas as pd
from math import atan2, cos, radians, sin, sqrt

from sklearn.cluster import DBSCAN


EARTH_RADIUS_METERS = 6_371_000


def haversine_distance_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Calcula a distância geodésica aproximada entre duas coordenadas."""
    latitude_delta = radians(latitude_b - latitude_a)
    longitude_delta = radians(longitude_b - longitude_a)
    latitude_a_radians = radians(latitude_a)
    latitude_b_radians = radians(latitude_b)

    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(latitude_a_radians)
        * cos(latitude_b_radians)
        * sin(longitude_delta / 2) ** 2
    )
    angular_distance = 2 * atan2(sqrt(haversine), sqrt(1 - haversine))
    return EARTH_RADIUS_METERS * angular_distance


def cluster_points(
    points: pd.DataFrame,
    radius_meters: float = 20,
    min_samples: int = 1,
) -> pd.DataFrame:
    """
    Agrupa pontos geográficos próximos utilizando DBSCAN.

    Parameters
    ----------
    points:
        DataFrame contendo as colunas latitude e longitude.

    radius_meters:
        Distância máxima entre pontos para pertencerem
        ao mesmo agrupamento.

    min_samples:
        Quantidade mínima de pontos para formar um agrupamento.

    Returns
    -------
    DataFrame
        Cópia dos pontos contendo a coluna cluster_id.
    """

    required_columns = {
        "latitude",
        "longitude",
    }

    missing = required_columns - set(points.columns)

    if missing:
        raise ValueError(
            f"Colunas obrigatórias ausentes: {missing}"
        )

    if points.empty:
        result = points.copy()
        result["cluster_id"] = pd.Series(
            dtype="int64"
        )
        return result

    result = points.copy()

    coordinates = (
        result[
            ["latitude", "longitude"]
        ]
        .astype("float64")
        .to_numpy()
    )

    coordinates_radians = np.radians(
        coordinates
    )

    epsilon = (
        radius_meters
        / EARTH_RADIUS_METERS
    )

    model = DBSCAN(
        eps=epsilon,
        min_samples=min_samples,
        metric="haversine",
    )

    labels = model.fit_predict(
        coordinates_radians
    )

    result["cluster_id"] = labels

    return result

def assign_clusters_to_accidents(
    accidents: pd.DataFrame,
    clustered_points: pd.DataFrame,
) -> pd.DataFrame:
    """
    Associa cada acidente ao cluster correspondente.

    A associação é feita através das coordenadas
    latitude e longitude.
    """

    required_accident_columns = {
        "latitude",
        "longitude",
    }

    required_point_columns = {
        "latitude",
        "longitude",
        "cluster_id",
    }

    missing_accidents = (
        required_accident_columns
        - set(accidents.columns)
    )

    missing_points = (
        required_point_columns
        - set(clustered_points.columns)
    )

    if missing_accidents:
        raise ValueError(
            f"Colunas obrigatórias ausentes em accidents: "
            f"{missing_accidents}"
        )

    if missing_points:
        raise ValueError(
            f"Colunas obrigatórias ausentes em clustered_points: "
            f"{missing_points}"
        )

    result = accidents.copy()

    cluster_mapping = (
        clustered_points[
            [
                "latitude",
                "longitude",
                "cluster_id",
            ]
        ]
        .drop_duplicates(
            subset=[
                "latitude",
                "longitude",
            ]
        )
    )

    result = result.merge(
        cluster_mapping,
        on=[
            "latitude",
            "longitude",
        ],
        how="left",
        validate="many_to_one",
    )

    return result
