import pandas as pd


COLUMN_MAPPING = {
    "id_sinistro": "id",
    "data_sinistro": "date",
    "latitude": "latitude",
    "longitude": "longitude",
    "tp_sinistro_primario": "accident_type",
    "logradouro": "street",
    "numero_logradouro": "street_number",
    "municipio": "city",
}


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
        .map(TYPE_MAPPING)
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

    # Manter apenas as colunas necessárias
    columns = [
        "id",
        "date",
        "latitude",
        "longitude",
        "accident_type",
        "street",
        "street_number",
        "city",
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