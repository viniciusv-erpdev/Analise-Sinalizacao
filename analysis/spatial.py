import numpy as np
import pandas as pd

from sklearn.cluster import DBSCAN


EARTH_RADIUS_METERS = 6_371_000
CLUSTER_RADIUS_METERS = 20


def cluster_accidents(
    df: pd.DataFrame,
    radius_meters: float = CLUSTER_RADIUS_METERS,
) -> pd.DataFrame:

    coordinates = df[
        ["latitude", "longitude"]
    ].to_numpy(dtype="float64")

    coordinates_radians = np.radians(coordinates)

    epsilon = radius_meters / EARTH_RADIUS_METERS

    model = DBSCAN(
        eps=epsilon,
        min_samples=1,
        metric="haversine",
        algorithm="ball_tree",
    )

    labels = model.fit_predict(coordinates_radians)

    result = df.copy()

    result["cluster_id"] = labels

    return result

def summarize_clusters(
    clustered: pd.DataFrame,
) -> pd.DataFrame:

    summary = (
        clustered
        .groupby("cluster_id")
        .agg(
            latitude=("latitude", "mean"),
            longitude=("longitude", "mean"),
            accident_count=("id", "count"),
        )
        .reset_index()
    )

    return summary

def summarize_clusters(
    clustered: pd.DataFrame,
) -> pd.DataFrame:

    summary = (
        clustered
        .groupby("cluster_id")
        .agg(
            latitude=("latitude", "mean"),
            longitude=("longitude", "mean"),
            accident_count=("id", "count"),
            collisions=(
                "accident_type",
                lambda x: (x == "COLISAO").sum(),
            ),
            pedestrians=(
                "accident_type",
                lambda x: (x == "ATROPELAMENTO").sum(),
            ),
        )
        .reset_index()
    )

    return summary

def summarize_clusters(
    clustered: pd.DataFrame,
) -> pd.DataFrame:

    summary = (
        clustered
        .groupby("cluster_id")
        .agg(
            latitude=("latitude", "mean"),
            longitude=("longitude", "mean"),
            accident_count=("id", "count"),
            collisions=(
                "accident_type",
                lambda x: (x == "COLISAO").sum(),
            ),
            pedestrians=(
                "accident_type",
                lambda x: (x == "ATROPELAMENTO").sum(),
            ),
        )
        .reset_index()
    )

    return summary

def group_by_coordinates(
    df: pd.DataFrame,
) -> pd.DataFrame:

    valid = df[
        df["latitude"].notna()
        & df["longitude"].notna()
    ]

    points = (
        valid
        .groupby(
            ["latitude", "longitude"],
        )
        .agg(
            accident_count=("id", "count"),
            collisions=(
                "accident_type",
                lambda x: (x == "COLISAO").sum(),
            ),
            pedestrians=(
                "accident_type",
                lambda x: (x == "ATROPELAMENTO").sum(),
            ),
        )
        .reset_index()
    )

    return points