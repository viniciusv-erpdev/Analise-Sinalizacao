import pandas as pd


def summarize_clusters(
    clustered_points: pd.DataFrame,
) -> pd.DataFrame:
    """
    Resume os pontos agrupados espacialmente.

    Cada linha do resultado representa um cluster.
    """

    required_columns = {
        "cluster_id",
        "latitude",
        "longitude",
        "accident_count",
        "collisions",
        "pedestrians",
    }

    missing = (
        required_columns
        - set(clustered_points.columns)
    )

    if missing:
        raise ValueError(
            f"Colunas obrigatórias ausentes: {missing}"
        )

    if clustered_points.empty:
        return pd.DataFrame(
            columns=[
                "cluster_id",
                "latitude",
                "longitude",
                "point_count",
                "accident_count",
                "collisions",
                "pedestrians",
            ]
        )

    summary = (
        clustered_points
        .groupby("cluster_id")
        .agg(
            latitude=("latitude", "mean"),
            longitude=("longitude", "mean"),
            point_count=("cluster_id", "size"),
            accident_count=("accident_count", "sum"),
            collisions=("collisions", "sum"),
            pedestrians=("pedestrians", "sum"),
        )
        .reset_index()
    )

    return summary