import pandas as pd


def build_occurrence_points(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Agrupa acidentes pelas coordenadas geográficas.

    Cada combinação única de latitude e longitude
    representa um ponto de ocorrência.

    Parameters
    ----------
    df:
        DataFrame contendo os acidentes com coordenadas válidas.

    Returns
    -------
    pd.DataFrame
        DataFrame contendo um registro por ponto de ocorrência,
        com a quantidade total de acidentes, colisões e
        atropelamentos.
    """

    required_columns = {
        "id",
        "latitude",
        "longitude",
        "accident_type",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"Colunas obrigatórias ausentes: {missing}"
        )

    if df.empty:
        return pd.DataFrame(
            columns=[
                "latitude",
                "longitude",
                "accident_count",
                "collisions",
                "pedestrians",
            ]
        )

    result = (
        df
        .groupby(
            [
                "latitude",
                "longitude",
            ],
            dropna=False,
        )
        .agg(
            accident_count=(
                "id",
                "count",
            ),
            collisions=(
                "accident_type",
                lambda x: (
                    x == "COLISAO"
                ).sum(),
            ),
            pedestrians=(
                "accident_type",
                lambda x: (
                    x == "ATROPELAMENTO"
                ).sum(),
            ),
        )
        .reset_index()
    )

    return result