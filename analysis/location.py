import pandas as pd


def build_location_summary(
    accidents: pd.DataFrame,
    eligible_clusters: pd.DataFrame,
) -> pd.DataFrame:
    """
    Associa cada cluster elegível aos principais logradouros
    encontrados nos acidentes pertencentes ao cluster.

    Parameters
    ----------
    accidents:
        DataFrame contendo os acidentes com cluster_id,
        street e street_number.

    eligible_clusters:
        DataFrame contendo os clusters elegíveis.

    Returns
    -------
    DataFrame
        Resultado dos clusters com informações de localização.
    """

    required_accident_columns = {
        "cluster_id",
        "street",
        "street_number",
    }

    missing = (
        required_accident_columns
        - set(accidents.columns)
    )

    if missing:
        raise ValueError(
            "Colunas obrigatórias ausentes em accidents: "
            f"{missing}"
        )

    if "cluster_id" not in eligible_clusters.columns:
        raise ValueError(
            "A coluna 'cluster_id' é obrigatória em "
            "eligible_clusters."
        )

    if eligible_clusters.empty:
        result = eligible_clusters.copy()

        result["streets"] = pd.Series(
            dtype="object"
        )

        result["street_numbers"] = pd.Series(
            dtype="object"
        )

        result["location"] = pd.Series(
            dtype="object"
        )

        result["location_type"] = pd.Series(
            dtype="object"
        )

        return result

    eligible_ids = set(
        eligible_clusters["cluster_id"]
    )

    cluster_accidents = accidents[
        accidents["cluster_id"].isin(
            eligible_ids
        )
    ].copy()

    location_rows = []

    for cluster_id, group in cluster_accidents.groupby(
        "cluster_id"
    ):

        streets = (
            group["street"]
            .dropna()
            .astype(str)
            .str.strip()
        )

        streets = streets[
            streets != ""
        ]

        street_counts = (
            streets
            .value_counts()
        )

        unique_streets = (
            street_counts
            .index
            .tolist()
        )

        numbers = (
            group["street_number"]
            .dropna()
            .astype(str)
            .str.strip()
        )

        numbers = numbers[
            numbers != ""
        ]

        unique_numbers = (
            numbers
            .unique()
            .tolist()
        )

        location = _build_location_text(
            unique_streets
        )

        location_type = _classify_location(
            unique_streets
        )

        location_rows.append(
            {
                "cluster_id": cluster_id,
                "streets": unique_streets,
                "street_numbers": unique_numbers,
                "location": location,
                "location_type": location_type,
            }
        )

    locations = pd.DataFrame(
        location_rows
    )

    result = eligible_clusters.merge(
        locations,
        on="cluster_id",
        how="left",
    )

    result["streets"] = result[
        "streets"
    ].apply(
        lambda value: (
            value
            if isinstance(value, list)
            else []
        )
    )

    result["street_numbers"] = result[
        "street_numbers"
    ].apply(
        lambda value: (
            value
            if isinstance(value, list)
            else []
        )
    )

    result["location"] = result[
        "location"
    ].fillna(
        "Localização não identificada"
    )

    result["location_type"] = result[
        "location_type"
    ].fillna(
        "UNKNOWN"
    )

    return result


def _build_location_text(
    streets: list[str],
) -> str:

    if not streets:
        return "Localização não identificada"

    if len(streets) == 1:
        return streets[0]

    if len(streets) == 2:
        return (
            f"{streets[0]} × {streets[1]}"
        )

    return " × ".join(
        streets[:3]
    )


def _classify_location(
    streets: list[str],
) -> str:

    if not streets:
        return "UNKNOWN"

    if len(streets) == 1:
        return "STREET"

    if len(streets) == 2:
        return "INTERSECTION"

    return "MULTIPLE_STREETS"