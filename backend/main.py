import asyncio
import logging
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from justwatch_check import check_netflix_es, debug_check
from letterboxd import LetterboxdError, get_slugs, get_title_year

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("netflix-letterboxd-checker")

app = FastAPI(title="Letterboxd -> Netflix España")

# CORS abierto: es una herramienta de uso personal/local, el frontend es un
# HTML suelto que puede servirse desde cualquier origen (file://, un puerto
# distinto, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Estado de jobs en memoria. Vale para uso local de una sola persona; se
# pierde al reiniciar el proceso, y no hace falta más para esto.
JOBS: dict[str, dict] = {}

DELAY_BETWEEN_FILMS = 0.4  # segundos, cortesía con Letterboxd/JustWatch


class ScanRequest(BaseModel):
    username: str
    list_type: str = "watchlist"  # "watchlist" o "watched"


@app.post("/scan")
async def start_scan(req: ScanRequest):
    username = req.username.strip()
    if not username:
        raise HTTPException(400, "Falta el usuario de Letterboxd")
    if req.list_type not in ("watchlist", "watched"):
        raise HTTPException(400, "list_type debe ser 'watchlist' o 'watched'")

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "running",  # running | done | error
        "total": 0,
        "done": 0,
        "current": None,
        "results": [],
        "errors": [],  # errores por película (JustWatch/Letterboxd), no cortan el escaneo
        "error": None,  # error que corta el escaneo entero
    }
    asyncio.create_task(_run_scan(job_id, username, req.list_type))
    return {"job_id": job_id}


async def _run_scan(job_id: str, username: str, list_type: str):
    job = JOBS[job_id]
    try:
        async with httpx.AsyncClient() as client:
            slugs = await get_slugs(client, username, list_type)
            job["total"] = len(slugs)
            logger.info("Escaneo %s: %d películas encontradas en %s/%s", job_id, len(slugs), username, list_type)

            for slug in slugs:
                info = await get_title_year(client, slug)
                job["current"] = info["title"]
                logger.info("[%s] comprobando: %r (año=%s, slug=%s)", job_id, info["title"], info["year"], slug)

                nf = await check_netflix_es(info["title"], info["year"])

                if nf.get("error"):
                    logger.warning("[%s] error comprobando %r: %s", job_id, info["title"], nf["error"])
                    job["errors"].append({"title": info["title"], "error": nf["error"]})

                if nf["available"]:
                    job["results"].append(
                        {
                            "title": info["title"],
                            "year": info["year"],
                            "letterboxd_url": f"https://letterboxd.com/film/{slug}/",
                            "netflix_url": nf["url"],
                            "poster": nf["poster"],
                        }
                    )

                job["done"] += 1
                await asyncio.sleep(DELAY_BETWEEN_FILMS)

        job["status"] = "done"
        job["current"] = None
        logger.info(
            "[%s] terminado: %d/%d comprobadas, %d en Netflix ES, %d errores",
            job_id, job["done"], job["total"], len(job["results"]), len(job["errors"]),
        )

    except LetterboxdError as e:
        logger.error("[%s] LetterboxdError: %s", job_id, e)
        job["status"] = "error"
        job["error"] = str(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] error inesperado", job_id)
        job["status"] = "error"
        job["error"] = f"Error inesperado: {e}"


@app.get("/status/{job_id}")
async def status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job no encontrado")
    return job


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/debug/check")
async def debug_check_endpoint(title: str, year: int | None = None):
    """
    Diagnóstico del lado JustWatch: qué ve JustWatch al buscar `title`, con
    todos los candidatos que devuelve (título, año, si tiene Netflix ES en
    suscripción, similitud con lo buscado). Pensado para probar en el
    navegador, ej:
    http://localhost:8000/debug/check?title=Cocaine%20Bear&year=2023
    """
    return await debug_check(title, year)


@app.get("/debug/letterboxd/{slug}")
async def debug_letterboxd_endpoint(slug: str):
    """
    Diagnóstico del lado Letterboxd: qué título/año extraemos de la ficha
    de una película a partir de su slug. El slug es la parte de la URL
    después de /film/, ej. para https://letterboxd.com/film/cocaine-bear/
    el slug es "cocaine-bear":
    http://localhost:8000/debug/letterboxd/cocaine-bear
    """
    async with httpx.AsyncClient() as client:
        return await get_title_year(client, slug)
