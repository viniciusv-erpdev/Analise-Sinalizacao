import pandas as pd


def count_accidents(
    df: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    Conta colisões e atropelamentos por cluster
    dentro de um determinado período.

    Esta função não calcula a quantidade total de acidentes.
    Ela retorna apenas os indicadores necessários para
    avaliação dos critérios.
    """

    required_columns = {
        "date",
        "cluster_id",
        "accident_type",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"Colunas obrigatórias ausentes: {missing}"
        )

    period = df[
        (df["date"] >= start_date)
        & (df["date"] <= end_date)
    ]

    result = (
        period
        .groupby("cluster_id")
        .agg(
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


def count_cluster_accidents(
    accidents: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    Conta acidentes, colisões e atropelamentos
    por cluster dentro de um determinado período.
    """

    required_columns = {
        "id",
        "date",
        "cluster_id",
        "accident_type",
    }

    missing = required_columns - set(accidents.columns)

    if missing:
        raise ValueError(
            f"Colunas obrigatórias ausentes: {missing}"
        )

    period = accidents[
        (accidents["date"] >= start_date)
        & (accidents["date"] <= end_date)
    ].copy()

    result = (
        period
        .groupby("cluster_id")
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


def evaluate_criteria(
    one_year: pd.DataFrame,
    three_years: pd.DataFrame,
) -> pd.DataFrame:
    """
    Avalia os critérios para instalação de semáforo.

    Critérios:

    Colisões:
        - 3 ou mais em 1 ano
        OU
        - 7 ou mais em 3 anos

    Atropelamentos:
        - 2 ou mais em 1 ano
        OU
        - 4 ou mais em 3 anos
    """

    result = pd.merge(
        one_year,
        three_years,
        on="cluster_id",
        how="outer",
        suffixes=("_1y", "_3y"),
    ).fillna(0)

    result["collision_criterion"] = (
        (result["collisions_1y"] >= 3)
        | (result["collisions_3y"] >= 7)
    )

    result["pedestrian_criterion"] = (
        (result["pedestrians_1y"] >= 2)
        | (result["pedestrians_3y"] >= 4)
    )

    result["eligible"] = (
        result["collision_criterion"]
        | result["pedestrian_criterion"]
    )

    return result


def classify_criterion(
    row: pd.Series,
) -> str:
    """
    Classifica o motivo pelo qual um cluster
    foi considerado elegível.

    Possíveis resultados:

        COLISAO_1_ANO
        COLISAO_3_ANOS
        ATROPELAMENTO_1_ANO
        ATROPELAMENTO_3_ANOS
        MULTIPLO
        NAO_ELEGIVEL
    """

    reasons = []

    if row["collisions_1y"] >= 3:
        reasons.append("COLISAO_1_ANO")

    if row["collisions_3y"] >= 7:
        reasons.append("COLISAO_3_ANOS")

    if row["pedestrians_1y"] >= 2:
        reasons.append("ATROPELAMENTO_1_ANO")

    if row["pedestrians_3y"] >= 4:
        reasons.append("ATROPELAMENTO_3_ANOS")

    if not reasons:
        return "NAO_ELEGIVEL"

    if len(reasons) > 1:
        return "MULTIPLO"

    return reasons[0]


def add_criterion_classification(
    criteria: pd.DataFrame,
) -> pd.DataFrame:
    """
    Adiciona a classificação do motivo de elegibilidade
    ao resultado dos critérios.
    """

    result = criteria.copy()

    result["criterion"] = result.apply(
        classify_criterion,
        axis=1,
    )

    return result