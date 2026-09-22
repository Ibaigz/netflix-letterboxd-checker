# Letterboxd → Netflix España

Comprueba qué películas de tu watchlist (o de tus vistas) en Letterboxd están
disponibles ahora mismo en Netflix España.

## Cómo funciona

1. **Backend (FastAPI)**: dado un usuario de Letterboxd, hace scraping de sus
   páginas públicas (`/watchlist/` o `/films/`) para sacar el listado de
   películas, y por cada una consulta la API no oficial de JustWatch
   (vía la librería [`simple-justwatch-python-api`](https://pypi.org/project/simple-justwatch-python-api/))
   filtrando por Netflix España.
2. **Frontend**: un HTML suelto que llama al backend y muestra progreso en
   vivo + resultados.

## Arrancar

```bash
docker compose up --build
```

Esto levanta el backend en `http://localhost:8000`. Luego abre
`frontend/index.html` directamente en el navegador (doble clic, o
`open frontend/index.html`). No necesita servirse desde ningún sitio en
concreto porque llama al backend por HTTP con CORS abierto.

Si prefieres correrlo sin Docker:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

## Limitaciones que debes conocer (importante)

- **Letterboxd no tiene API pública de acceso libre.** Esto scrapea HTML.
  La primera versión de este scraper asumía enlaces `<a href="/film/slug/">`
  en el grid de pósters, pero Letterboxd los renderiza como componentes React
  (`data-target-link` en un `div.react-component`) sin `href` — por eso daba
  0 resultados. Los selectores actuales (`.react-component[data-target-link]`
  para el listado, `.paginate-nextprev .next` para paginar, `.primaryname` y
  `span.releasedate a` para título/año) están sacados del código fuente de
  [lettarrboxd](https://github.com/ryanpag3/lettarrboxd), un proyecto activo
  que sigue funcionando hoy contra letterboxd.com, no de una suposición mía.
  Aun así **no he podido ejecutar esto en vivo** contra letterboxd.com desde
  donde lo escribí (sin salida de red a ese dominio) — solo he verificado la
  lógica con HTML simulado que replica esa estructura. Si vuelve a fallar,
  dime el error exacto o pásame el HTML de una página tuya y lo ajusto.
- Si Letterboxd empieza a devolver una página de verificación (Cloudflare)
  en vez del contenido normal, la petición con `httpx` sin más no la va a
  superar — hay forks de `lettarrboxd` que añaden FlareSolverr para ese caso
  concreto. Avísame si ves eso (contenido muy corto, sin `.primaryname`) y lo
  metemos.
- **JustWatch tampoco tiene API pública oficial.** La librería que uso
  (`simple-justwatch-python-api`) accede a su GraphQL interno mediante
  ingeniería inversa; puede dejar de funcionar si JustWatch cambia su
  esquema. Es de uso no comercial, como el propio proyecto indica.
- **El matching es por título + año con tolerancia de ±1 año**, no por ID
  único. Con títulos muy genéricos o remakes puede haber algún falso
  positivo o negativo ocasional.
- Solo cuenta como "disponible" lo que está incluido en la suscripción
  (`FLATRATE`/`ADS`); si una película solo se puede alquilar o comprar en
  Netflix, no se marca como disponible.
- El escaneo hace una request a Letterboxd y otra a JustWatch **por cada
  película**, con una pequeña pausa entre ellas para no ser agresivo. Para
  una watchlist grande (cientos de títulos) puede tardar varios minutos.

## Estructura

```
backend/
  main.py             # endpoints FastAPI (/scan, /status/{job_id})
  letterboxd.py        # scraping de Letterboxd
  justwatch_check.py    # consulta a JustWatch
  requirements.txt
  Dockerfile
frontend/
  index.html          # UI standalone
docker-compose.yml
```
