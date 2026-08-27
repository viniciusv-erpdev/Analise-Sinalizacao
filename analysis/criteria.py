import pandas as pd


def count_accidents(
    df: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:

    period = df[
        (df["date"] >= start_date)
        & (df["date"] <= end_date)
    ]

    result = (
        period
        .groupby(["latitude", "longitude"])
        .agg(
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

    return result