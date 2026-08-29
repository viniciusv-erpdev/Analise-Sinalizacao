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

    result["collision_1y_met"] = (
        result["collisions_1y"] >= 3
    )
    result["collision_3y_met"] = (
        result["collisions_3y"] >= 7
    )
    result["pedestrian_1y_met"] = (
        result["pedestrians_1y"] >= 2
    )
    result["pedestrian_3y_met"] = (
        result["pedestrians_3y"] >= 4
    )

    result["collision_criterion"] = (
        result["collision_1y_met"]
        | result["collision_3y_met"]
    )

    result["pedestrian_criterion"] = (
        result["pedestrian_1y_met"]
        | result["pedestrian_3y_met"]
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


def count_historical_cluster_accidents(
    accidents: pd.DataFrame,
    years: int,
) -> pd.DataFrame:
    """
    Encontra as maiores contagens em qualquer janela histórica
    de ``years`` anos para cada cluster.

    As janelas usam anos-calendário e incluem as datas inicial
    e final.
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

    if years <= 0:
        raise ValueError(
            "A duração da janela deve ser maior que zero."
        )

    valid_dates = accidents[
        accidents["date"].notna()
    ].sort_values(
        ["cluster_id", "date"]
    )

    rows = []
    offset = pd.DateOffset(years=years)

    for cluster_id, group in valid_dates.groupby(
        "cluster_id",
        sort=False,
    ):
        dates = group["date"].tolist()
        accident_types = group["accident_type"].tolist()

        left = 0
        collisions = 0
        pedestrians = 0
        maximum_accidents = 0
        maximum_collisions = 0
        maximum_pedestrians = 0

        for right, (date, accident_type) in enumerate(
            zip(dates, accident_types)
        ):
            if accident_type == "COLISAO":
                collisions += 1
            elif accident_type == "ATROPELAMENTO":
                pedestrians += 1

            window_start = date - offset

            while dates[left] < window_start:
                removed_type = accident_types[left]

                if removed_type == "COLISAO":
                    collisions -= 1
                elif removed_type == "ATROPELAMENTO":
                    pedestrians -= 1

                left += 1

            maximum_accidents = max(
                maximum_accidents,
                right - left + 1,
            )
            maximum_collisions = max(
                maximum_collisions,
                collisions,
            )
            maximum_pedestrians = max(
                maximum_pedestrians,
                pedestrians,
            )

        rows.append(
            {
                "cluster_id": cluster_id,
                "accident_count": maximum_accidents,
                "collisions": maximum_collisions,
                "pedestrians": maximum_pedestrians,
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "cluster_id",
            "accident_count",
            "collisions",
            "pedestrians",
        ],
    )


def evaluate_historical_criteria(
    accidents: pd.DataFrame,
) -> pd.DataFrame:
    """Avalia os critérios em qualquer janela histórica válida."""

    one_year = count_historical_cluster_accidents(
        accidents,
        years=1,
    )
    three_years = count_historical_cluster_accidents(
        accidents,
        years=3,
    )

    return evaluate_criteria(
        one_year,
        three_years,
    )
