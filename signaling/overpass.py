"""Sugestões opcionais de PGT; nenhuma consulta ocorre ao gerar o Word."""

import json
import math
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError

from signaling.characterization import MAX_PGT_LENGTH, validate_report_text
from signaling.models import (
    MAX_SIGNALING_SEARCH_RADIUS_METERS,
    MIN_SIGNALING_SEARCH_RADIUS_METERS,
)


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HTTP_TIMEOUT_SECONDS = 15
QUERY_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PGT_SEARCH_ERROR = (
    "Não foi possível consultar automaticamente os locais próximos. "
    "Você ainda pode adicionar os Polos Geradores de Tráfego manualmente."
)
AMENITY_LABELS = {
    "hospital": "🏥 Unidade de Saúde",
    "clinic": "🏥 Unidade de Saúde",
    "doctors": "🏥 Unidade de Saúde",
    "university": "🎓 Unidade escolar",
    "college": "🎓 Unidade escolar",
    "school": "🎓 Unidade escolar",
    "kindergarten": "🎓 Unidade escolar",
}


class OverpassUnavailable(ValueError):
    """Falha controlada da fonte auxiliar, sem impedir o relatório manual."""


class InvalidPGTLocation(ValueError):
    """Coordenadas ou raio persistidos não podem ser usados na consulta."""


def build_pgt_query(*, latitude, longitude, radius_meters) -> str:
    try:
        lat, lon, radius = map(float, (latitude, longitude, radius_meters))
    except (TypeError, ValueError, OverflowError) as error:
        raise InvalidPGTLocation from error
    if (
        not all(math.isfinite(value) for value in (lat, lon, radius))
        or not -90 <= lat <= 90
        or not -180 <= lon <= 180
        or not MIN_SIGNALING_SEARCH_RADIUS_METERS <= radius <= MAX_SIGNALING_SEARCH_RADIUS_METERS
        or not radius.is_integer()
    ):
        raise InvalidPGTLocation
    amenities = "|".join(AMENITY_LABELS)
    return (
        f"[out:json][timeout:{QUERY_TIMEOUT_SECONDS}];"
        f'nwr(around:{int(radius)},{lat:.6f},{lon:.6f})'
        f'["amenity"~"^({amenities})$"];'
        "out tags;"
    )


def find_nearby_pgts(*, latitude, longitude, radius_meters) -> list[str]:
    query = build_pgt_query(
        latitude=latitude, longitude=longitude, radius_meters=radius_meters,
    )
    request = Request(
        OVERPASS_URL,
        data=urlencode({"data": query}).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "Analise-Sinalizacao/1.0 (PGT report suggestions)",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise OverpassUnavailable(PGT_SEARCH_ERROR)
            content = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        # Inclui 429, 5xx e demais respostas HTTP de erro.
        error.close()
        raise OverpassUnavailable(PGT_SEARCH_ERROR) from error
    except (URLError, OSError, HTTPException) as error:
        # TimeoutError também é OSError.
        raise OverpassUnavailable(PGT_SEARCH_ERROR) from error
    if len(content) > MAX_RESPONSE_BYTES:
        raise OverpassUnavailable(PGT_SEARCH_ERROR)
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeError) as error:
        raise OverpassUnavailable(PGT_SEARCH_ERROR) from error
    return _normalize_results(payload)


def _normalize_results(payload: object) -> list[str]:
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("elements"), list)
        or payload.get("remark")
    ):
        # Overpass pode devolver erro de execução em JSON com HTTP 200.
        raise OverpassUnavailable(PGT_SEARCH_ERROR)
    results = []
    seen = set()
    for element in payload["elements"]:
        if not isinstance(element, dict) or not isinstance(element.get("tags", {}), dict):
            raise OverpassUnavailable(PGT_SEARCH_ERROR)
        if element.get("type") not in {"node", "way", "relation"}:
            continue
        tags = element.get("tags", {})
        amenity = tags.get("amenity")
        if not isinstance(amenity, str) or amenity not in AMENITY_LABELS:
            continue
        name = tags.get("name")
        # Sem nome não há sugestão tecnicamente útil; não inventar identificação.
        if not isinstance(name, str) or not name.strip():
            continue
        label = f'{AMENITY_LABELS[amenity]}: {" ".join(name.split())}'
        if len(label) > MAX_PGT_LENGTH:
            continue
        try:
            validate_report_text(label)
        except ValidationError:
            continue
        key = label.lower()
        if key not in seen:
            results.append(label)
            seen.add(key)
    return results
