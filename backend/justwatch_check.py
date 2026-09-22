"""
Comprobación de disponibilidad en Netflix España usando la API GraphQL no
oficial de JustWatch, a través de la librería `simple-justwatch-python-api`
(https://pypi.org/project/simple-justwatch-python-api/).

Es una API no documentada y de terceros: puede cambiar sin aviso. Uso
personal/no comercial, tal y como indica la propia librería.

Nota sobre el parámetro `providers` de la búsqueda: la librería permite
pasarlo para filtrar ya en la propia query de JustWatch (`packages` dentro
de `searchTitlesFilter`). En teoría eso debería bastar para pedir "solo
títulos con oferta de Netflix", pero es un campo no documentado y de
comportamiento no garantizado. En vez de depender de que ese filtro haga
exactamente lo que promete, aquí se busca sin filtrar por proveedor y se
comprueba directamente, en las ofertas que trae cada resultado para el país
pedido (ES), si Netflix está ahí. Es más lento (la búsqueda puede traer
resultados sin Netflix que luego se descartan) pero no depende de una
suposición sobre un campo no oficial.
"""

import asyncio
import re
import unicodedata
from difflib import SequenceMatcher

from simplejustwatchapi.justwatch import search as jw_search

NETFLIX_SHORT_NAME = "nfx"
# Tipos de monetización que cuentan como "incluido en la suscripción".
# Se excluye deliberadamente RENT y BUY: eso no es "está en Netflix",
# es "se puede alquilar/comprar a través del enlace de Netflix".
SUBSCRIPTION_TYPES = {"FLATRATE", "ADS"}

# Umbral de similitud de título (0-1). Por debajo de esto, se descarta el
# resultado aunque tenga oferta de Netflix: es señal de que es una película
# distinta con nombre parecido, no la que se buscaba.
TITLE_SIMILARITY_THRESHOLD = 0.6

SEARCH_COUNT = 10


def _normalize(text: str) -> str:
    """minúsculas, sin acentos, sin puntuación, espacios colapsados."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _has_netflix_offer(entry) -> tuple[bool, object]:
    for offer in entry.offers:
        if offer.package.short_name == NETFLIX_SHORT_NAME and offer.monetization_type in SUBSCRIPTION_TYPES:
            return True, offer
    return False, None


def _search(title: str) -> list:
    return jw_search(
        title=title,
        country="ES",
        language="es",
        count=SEARCH_COUNT,
        best_only=True,
        object_types="MOVIE",
    )


def _check_sync(title: str, year: int | None) -> dict:
    try:
        results = _search(title)
    except Exception as e:  # noqa: BLE001 - queremos capturar cualquier fallo de red/API
        return {"available": False, "url": None, "poster": None, "error": str(e)}

    best_match = None  # (similitud, entry, offer)

    for entry in results:
        if year and entry.release_year and abs(entry.release_year - year) > 1:
            continue

        similarity = _title_similarity(title, entry.title or "")
        if similarity < TITLE_SIMILARITY_THRESHOLD:
            continue

        has_netflix, offer = _has_netflix_offer(entry)
        if has_netflix and (best_match is None or similarity > best_match[0]):
            best_match = (similarity, entry, offer)

    if not best_match:
        return {"available": False, "url": None, "poster": None, "error": None}

    _, entry, offer = best_match
    return {
        "available": True,
        "url": offer.url or entry.url,
        "poster": entry.poster,
        "error": None,
    }


async def check_netflix_es(title: str, year: int | None) -> dict:
    # La librería usa httpx de forma síncrona; la delegamos a un hilo para
    # no bloquear el event loop de FastAPI.
    return await asyncio.to_thread(_check_sync, title, year)


def _debug_sync(title: str, year: int | None) -> dict:
    """
    Para depurar: qué ve JustWatch cuando buscamos este título, sin aplicar
    ningún filtro de similitud ni de año, para poder ver a ojo por qué algo
    no está matcheando.
    """
    try:
        results = _search(title)
    except Exception as e:  # noqa: BLE001
        return {"query": title, "error": str(e), "candidates": []}

    candidates = []
    for entry in results:
        has_netflix, offer = _has_netflix_offer(entry)
        candidates.append(
            {
                "title": entry.title,
                "release_year": entry.release_year,
                "similarity_to_query": round(_title_similarity(title, entry.title or ""), 3),
                "has_netflix_es_subscription": has_netflix,
                "netflix_url": offer.url if offer else None,
                "all_providers_es": sorted(
                    {o.package.short_name for o in entry.offers}
                ),
            }
        )

    return {"query": title, "requested_year": year, "error": None, "candidates": candidates}


async def debug_check(title: str, year: int | None) -> dict:
    return await asyncio.to_thread(_debug_sync, title, year)
