import pandas as pd


def validate_coordinates(
    df: pd.DataFrame,
) -> pd.DataFrame:

    result = df.copy()

    result["coordinate_status"] = "INVALID"

    valid_coordinates = (
        result["latitude"].notna()
        & result["longitude"].notna()
    )

    result.loc[
        valid_coordinates,
        "coordinate_status",
    ] = "UNVERIFIED"

    return result