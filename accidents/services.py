from collections.abc import Iterable
from io import BytesIO

import pandas as pd
from django.core.files.uploadedfile import UploadedFile

REQUIRED_SOURCE_COLUMNS = {
    "id_sinistro",
    "data_sinistro",
    "latitude",
    "longitude",
    "tp_sinistro_primario",
    "logradouro",
    "numero_logradouro",
    "municipio",
    "qtd_gravidade_fatal",
    "qtd_gravidade_grave",
    "qtd_gravidade_leve",
    "qtd_gravidade_nao_disponivel",
    "qtd_gravidade_ileso",
}

EXCLUSIVELY_UNINJURED_EXCLUDED_COUNT_ATTR = (
    "exclusively_uninjured_excluded_count"
)
OTHER_SEVERITY_COLUMNS = (
    "qtd_gravidade_fatal",
    "qtd_gravidade_grave",
    "qtd_gravidade_leve",
    "qtd_gravidade_nao_disponivel",
)
UNINJURED_SEVERITY_COLUMN = "qtd_gravidade_ileso"


class AccidentImportError(ValueError):
    """Erro causado por um arquivo de sinistros inválido."""


def import_accident_files(
    uploaded_files: Iterable[UploadedFile],
) -> pd.DataFrame:
    """Lê e consolida arquivos CSV do Infosiga em memória."""

    files = list(uploaded_files)

    if not files:
        raise AccidentImportError(
            "Selecione pelo menos um arquivo de sinistros."
        )

    dataframes = [
        _read_accident_file(uploaded_file)
        for uploaded_file in files
    ]

    consolidated = pd.concat(
        dataframes,
        ignore_index=True,
    )

    deduplicated = consolidated.drop_duplicates(
        subset=["id_sinistro"],
        keep="first",
    ).reset_index(drop=True)
    return exclude_exclusively_uninjured_accidents(deduplicated)


def exclude_exclusively_uninjured_accidents(
    accidents: pd.DataFrame,
) -> pd.DataFrame:
    """Remove sinistros cuja única gravidade preenchida seja ileso."""
    required_columns = {*OTHER_SEVERITY_COLUMNS, UNINJURED_SEVERITY_COLUMN}
    missing_columns = required_columns - set(accidents.columns)
    if missing_columns:
        missing_text = ", ".join(sorted(missing_columns))
        raise AccidentImportError(
            "Não foi possível aplicar a regra de gravidade; "
            f"colunas ausentes: {missing_text}."
        )

    exclusion_mask = accidents[list(OTHER_SEVERITY_COLUMNS)].isna().all(axis=1)
    exclusion_mask &= accidents[UNINJURED_SEVERITY_COLUMN].notna()
    filtered = accidents.loc[~exclusion_mask].reset_index(drop=True)
    filtered.attrs[EXCLUSIVELY_UNINJURED_EXCLUDED_COUNT_ATTR] = int(
        exclusion_mask.sum()
    )
    return filtered


def _read_accident_file(
    uploaded_file: UploadedFile,
) -> pd.DataFrame:
    file_name = uploaded_file.name or "arquivo sem nome"
    uploaded_file.seek(0)
    content = uploaded_file.read()

    try:
        dataframe = pd.read_csv(
            BytesIO(content),
            sep=";",
            encoding="utf-8",
        )
    except UnicodeDecodeError:
        try:
            dataframe = pd.read_csv(
                BytesIO(content),
                sep=";",
                encoding="latin-1",
            )
        except (pd.errors.EmptyDataError, pd.errors.ParserError) as error:
            raise AccidentImportError(
                f"O arquivo '{file_name}' não é um CSV válido."
            ) from error
    except pd.errors.EmptyDataError as error:
        raise AccidentImportError(
            f"O arquivo '{file_name}' está vazio."
        ) from error
    except pd.errors.ParserError as error:
        raise AccidentImportError(
            f"O arquivo '{file_name}' não é um CSV válido."
        ) from error

    if dataframe.empty:
        raise AccidentImportError(
            f"O arquivo '{file_name}' não possui registros."
        )

    missing_columns = (
        REQUIRED_SOURCE_COLUMNS
        - set(dataframe.columns)
    )

    if missing_columns:
        missing_text = ", ".join(
            sorted(missing_columns)
        )
        raise AccidentImportError(
            f"O arquivo '{file_name}' não possui as colunas "
            f"obrigatórias: {missing_text}."
        )

    return dataframe
