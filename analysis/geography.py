from pathlib import Path

import geopandas as gpd
import pandas as pd


TARGET_CRS = "EPSG:4326"
MUNICIPALITY_CRS = "EPSG:31983"


def load_municipality(
    path: Path,
) -> gpd.GeoDataFrame:
    """
    Carrega o polígono do município e
    transforma suas coordenadas para WGS84.
    """

    municipality = gpd.read_file(path)

    municipality = municipality.set_crs(
        MUNICIPALITY_CRS,
        allow_override=True,
    )

    municipality = municipality.to_crs(
        TARGET_CRS
    )

    return municipality


def validate_coordinates(
    df: pd.DataFrame,
    municipality: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """
    Classifica as coordenadas dos acidentes como:

    MISSING
        Latitude ou longitude ausente.

    VALID
        Coordenada localizada dentro do município.

    OUTSIDE_MUNICIPALITY
        Coordenada localizada fora do município.
    """

    result = df.copy()

    result["coordinate_status"] = "MISSING"

    valid_coordinates = (
        result["latitude"].notna()
        & result["longitude"].notna()
    )

    result.loc[
        valid_coordinates,
        "coordinate_status",
    ] = "OUTSIDE_MUNICIPALITY"

    if not valid_coordinates.any():
        return result

    points = gpd.GeoDataFrame(
        result.loc[valid_coordinates].copy(),
        geometry=gpd.points_from_xy(
            result.loc[valid_coordinates, "longitude"],
            result.loc[valid_coordinates, "latitude"],
        ),
        crs=TARGET_CRS,
    )

    municipality = municipality.to_crs(
        TARGET_CRS
    )

    municipality_geometry = municipality.geometry.union_all()

    inside = points.geometry.within(
        municipality_geometry
    )

    result.loc[
        valid_coordinates,
        "coordinate_status",
    ] = inside.map(
        {
            True: "VALID",
            False: "OUTSIDE_MUNICIPALITY",
        }
    ).to_numpy()

    return result