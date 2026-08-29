from collections.abc import Iterable
from io import BytesIO

import pandas as pd
from django.core.files.uploadedfile import UploadedFile

from accidents.normalizer import COLUMN_MAPPING


REQUIRED_SOURCE_COLUMNS = set(COLUMN_MAPPING)


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

    return consolidated.drop_duplicates(
        subset=["id_sinistro"],
        keep="first",
    ).reset_index(drop=True)


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
