import pandas as pd


def build_analysis_result(
    clusters: pd.DataFrame,
    criteria_result: pd.DataFrame,
) -> pd.DataFrame:
    """
    Constrói o resultado final da análise.

    Combina as informações espaciais dos clusters com
    os resultados dos critérios temporais.

    Parameters
    ----------
    clusters:
        DataFrame contendo os clusters espaciais.
        Deve possuir cluster_id, latitude e longitude.

    criteria_result:
        DataFrame produzido por evaluate_criteria().
        Contém as estatísticas temporais e os critérios
        de elegibilidade.

    Returns
    -------
    DataFrame
        Resultado final contendo apenas clusters elegíveis,
        com suas coordenadas e estatísticas.
    """

    required_cluster_columns = {
        "cluster_id",
        "latitude",
        "longitude",
    }

    missing_clusters = (
        required_cluster_columns
        - set(clusters.columns)
    )

    if missing_clusters:
        raise ValueError(
            "Colunas obrigatórias ausentes em clusters: "
            f"{missing_clusters}"
        )

    required_criteria_columns = {
        "cluster_id",
        "accident_count_1y",
        "collisions_1y",
        "pedestrians_1y",
        "accident_count_3y",
        "collisions_3y",
        "pedestrians_3y",
        "collision_criterion",
        "pedestrian_criterion",
        "eligible",
    }

    missing_criteria = (
        required_criteria_columns
        - set(criteria_result.columns)
    )

    if missing_criteria:
        raise ValueError(
            "Colunas obrigatórias ausentes em "
            f"criteria_result: {missing_criteria}"
        )

    cluster_locations = (
        clusters[
            [
                "cluster_id",
                "latitude",
                "longitude",
            ]
        ]
        .drop_duplicates(
            subset=["cluster_id"]
        )
    )

    result = pd.merge(
        cluster_locations,
        criteria_result,
        on="cluster_id",
        how="inner",
    )

    result = result[
        result["eligible"]
    ].copy()

    result = result.sort_values(
        "cluster_id"
    ).reset_index(drop=True)

    return result