import pandas as pd


def extract_available_periods(
    accidents: pd.DataFrame,
) -> list[dict[str, object]]:
    """Lista anos e meses válidos realmente presentes nos registros aceitos."""
    valid = _valid_period_rows(accidents)
    if valid.empty:
        return []

    return [
        {
            "year": int(year),
            "months": sorted(int(month) for month in group["month"].unique()),
        }
        for year, group in valid.groupby("year", sort=True)
    ]


def build_cluster_period_summaries(
    accidents: pd.DataFrame,
    cluster_ids: set[int],
) -> dict[int, dict[str, object]]:
    """Compacta ocorrências de clusters elegíveis por ano e mês."""
    selected = accidents[accidents["cluster_id"].isin(cluster_ids)].copy()
    summaries = {
        int(cluster_id): {
            "total_count": int(len(group)),
            "unperiodized_count": 0,
            "counts": [],
        }
        for cluster_id, group in selected.groupby("cluster_id", sort=False)
    }
    if selected.empty:
        return summaries

    valid_mask = _valid_period_mask(selected)
    invalid_counts = selected[~valid_mask].groupby("cluster_id").size()
    for cluster_id, count in invalid_counts.items():
        summaries[int(cluster_id)]["unperiodized_count"] = int(count)

    valid = selected[valid_mask]
    period_counts = valid.groupby(["cluster_id", "year", "month"]).size()
    for (cluster_id, year, month), count in period_counts.items():
        summaries[int(cluster_id)]["counts"].append(
            {
                "year": int(year),
                "month": int(month),
                "count": int(count),
            }
        )
    return summaries


def _valid_period_rows(accidents: pd.DataFrame) -> pd.DataFrame:
    if not {"year", "month"}.issubset(accidents.columns):
        return pd.DataFrame(columns=["year", "month"])
    return accidents.loc[_valid_period_mask(accidents), ["year", "month"]]


def _valid_period_mask(accidents: pd.DataFrame) -> pd.Series:
    if not {"year", "month"}.issubset(accidents.columns):
        return pd.Series(False, index=accidents.index, dtype="bool")
    return (
        accidents["year"].notna()
        & accidents["month"].notna()
        & accidents["year"].between(1, 9999)
        & accidents["month"].between(1, 12)
    )
