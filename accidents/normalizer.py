import pandas as pd


COLUMN_MAPPING = {
    "id_sinistro": "id",
    "tipo_registro": "record_type",
    "data_sinistro": "date",
    "latitude": "latitude",
    "longitude": "longitude",
    "tp_sinistro_primario": "accident_type",
    "logradouro": "street",
    "numero_logradouro": "street_number",
    "municipio": "city",
    "tipo_via": "road_type",
    "qtd_pedestre": "pedestrian_count",
    "qtd_bicicleta": "bicycle_count",
    "qtd_motocicleta": "motorcycle_count",
    "qtd_automovel": "car_count",
    "qtd_onibus": "bus_count",
    "qtd_caminhao": "truck_count",
    "qtd_veic_outros": "other_vehicle_count",
    "qtd_veic_nao_disponivel": "unavailable_vehicle_count",
}


INDIVIDUAL_COUNT_COLUMNS = [
    "pedestrian_count",
    "bicycle_count",
    "motorcycle_count",
    "car_count",
    "bus_count",
    "truck_count",
    "other_vehicle_count",
    "unavailable_vehicle_count",
]


TYPE_MAPPING = {
    "COLISAO": "COLISAO",
    "ATROPELAMENTO": "ATROPELAMENTO",
    "CHOQUE": "CHOQUE",
    "OUTROS": "OUTRO",
    "NAO DISPONIVEL": "NAO_DISPONIVEL",
}


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza o DataFrame original do Infosiga
    para o formato utilizado pelo projeto.
    """

    df = df.rename(columns=COLUMN_MAPPING).copy()

    for column in COLUMN_MAPPING.values():
        if column not in df.columns:
            df[column] = pd.NA

    # Data
    df["date"] = pd.to_datetime(
        df["date"],
        format="%d/%m/%Y",
        errors="coerce",
    )

    # Coordenadas
    for column in ["latitude", "longitude"]:
        df[column] = (
        pd.to_numeric(
            df[column]
            .astype("string")
            .str.replace(",", ".", regex=False),
            errors="coerce",
        )
        .astype("float64")
    )

    # Tipo de sinistro
    df["accident_type"] = (
        df["accident_type"]
        .astype("string")
        .str.strip()
        .str.upper()
        .str.normalize("NFKD")
        .str.encode("ascii", errors="ignore")
        .str.decode("ascii")
        .map(TYPE_MAPPING)
    )

    for column in ["record_type", "road_type"]:
        df[column] = (
            df[column]
            .astype("string")
            .str.strip()
            .str.upper()
            .str.normalize("NFKD")
            .str.encode("ascii", errors="ignore")
            .str.decode("ascii")
        )

    # Logradouro
    df["street"] = (
        df["street"]
        .astype("string")
        .str.strip()
    )

    # Cidade
    df["city"] = (
        df["city"]
        .astype("string")
        .str.strip()
        .str.upper()
    )

    # Número do logradouro
    df["street_number"] = (
        pd.to_numeric(
        df["street_number"],
        errors="coerce",
        )
    .astype("float64")
    )

    for column in INDIVIDUAL_COUNT_COLUMNS:
        df[column] = (
            pd.to_numeric(df[column], errors="coerce")
            .fillna(0)
            .clip(lower=0)
            .astype("int64")
        )

    # Manter apenas as colunas necessárias
    columns = [
        "id",
        "record_type",
        "road_type",
        "date",
        "latitude",
        "longitude",
        "accident_type",
        "street",
        "street_number",
        "city",
        *INDIVIDUAL_COUNT_COLUMNS,
    ]

    return df[columns]

def validate(df: pd.DataFrame) -> None:
    required_columns = {
        "id",
        "date",
        "latitude",
        "longitude",
        "accident_type",
        "street",
        "street_number",
        "city",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"Colunas ausentes após normalização: {missing}"
        )
