"""
Scraper de Letterboxd.

Letterboxd no tiene API pública de acceso libre, así que esto lee
directamente el HTML de las páginas públicas del perfil.

Los selectores de aquí NO son una suposición mía: los saqué del código
fuente de `lettarrboxd` (https://github.com/ryanpag3/lettarrboxd), un
proyecto open source activo que sincroniza listas de Letterboxd con Radarr
y que sigue funcionando en producción hoy. Mi primera versión asumía que
los pósters eran enlaces `<a href="/film/slug/">`, pero Letterboxd los
renderiza ahora como componentes React (`data-target-link` en un
`div.react-component`), sin `href`. Por eso la primera versión devolvía 0
resultados.

Qué usa cada cosa:
- Listado (watchlist / vistas): `.react-component[data-target-link]` para
  cada póster, y `.paginate-nextprev .next` para encontrar la siguiente
  página (en vez de intentar deducir el número de páginas).
- Ficha de película: `.primaryname` para el título y el `href` del enlace
  `span.releasedate a` (que apunta a `/films/year/<año>/...`) para el año.

Sigo sin poder ejecutar esto en vivo desde el entorno donde lo escribí (sin
salida de red a letterboxd.com), pero esta vez está basado en selectores
confirmados por un scraper real en producción, no en una convención que yo
diera por hecha.
"""

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE = "https://letterboxd.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

YEAR_RE = re.compile(r"/films/year/(\d{4})/")

MAX_PAGES = 300  # salvaguarda para no entrar en bucle infinito


class LetterboxdError(Exception):
    pass


async def get_slugs(client: httpx.AsyncClient, username: str, list_type: str) -> list[str]:
    """
    Recorre todas las páginas de la lista (watchlist o films/watched) de un
    usuario y devuelve los slugs de película únicos, en el orden en que
    aparecen, siguiendo el enlace "siguiente" de la paginación.
    """
    path = "watchlist" if list_type == "watchlist" else "films"
    url = f"{BASE}/{username}/{path}/"

    slugs: list[str] = []
    seen: set[str] = set()
    pages_visited = 0

    while url and pages_visited < MAX_PAGES:
        resp = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)

        if resp.status_code == 404:
            raise LetterboxdError(
                f"No se encontró la lista '{path}' del usuario '{username}' "
                "(usuario inexistente, lista vacía o privada)."
            )
        resp.raise_for_status()
        pages_visited += 1

        soup = BeautifulSoup(resp.text, "html.parser")

        for el in soup.select(".react-component[data-target-link]"):
            link = el.get("data-target-link", "")
            m = re.match(r"^/film/([a-z0-9\-]+)/?$", link)
            if m:
                slug = m.group(1)
                if slug not in seen:
                    seen.add(slug)
                    slugs.append(slug)

        next_link = soup.select_one(".paginate-nextprev .next")
        href = next_link.get("href") if next_link else None
        url = urljoin(BASE, href) if href else None

    return slugs


async def get_title_year(client: httpx.AsyncClient, slug: str) -> dict:
    """
    Devuelve {"slug", "title", "year"} para una película a partir de su
    ficha en Letterboxd.
    """
    url = f"{BASE}/film/{slug}/"
    resp = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    name_el = soup.select_one(".primaryname")
    title = name_el.get_text(strip=True) if name_el else slug.replace("-", " ").title()

    year = None
    year_link = soup.select_one("span.releasedate a")
    if year_link and year_link.get("href"):
        m = YEAR_RE.search(year_link["href"])
        if m:
            year = int(m.group(1))

    return {"slug": slug, "title": title, "year": year}
