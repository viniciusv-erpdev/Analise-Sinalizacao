"""Validação dos textos transitórios usados na caracterização do relatório."""

import re

from django.core.exceptions import ValidationError


MAX_PGT_ITEMS = 50
MAX_PGT_LENGTH = 300
INVALID_XML_CHARACTERS = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]"
)


def validate_report_text(value: str) -> None:
    """Aceita Unicode e texto literal, rejeitando caracteres inválidos no XML."""
    if INVALID_XML_CHARACTERS.search(value):
        raise ValidationError("O texto contém caracteres de controle inválidos.")
