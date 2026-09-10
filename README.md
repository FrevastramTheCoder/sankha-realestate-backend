# NyumbaSalama

FastAPI backend for student accommodation discovery in Dar es Salaam.

## Architecture

- `app/routers/ai.py` exposes the new `/api/ai/chat` tool-oriented chatbot and the `/chat` compatibility path.
- `app/services/ai_orchestrator.py` owns conversation memory, follow-up questions, and response composition.
- `app/services/accommodation_tools.py` parses preferences, queries real `Property` rows, checks stored availability, and ranks results transparently.
- `app/services/geo_knowledge.py` is the curated Dar place/campus layer. Its coordinates are labeled centroids.
- `app/services/gis.py` resolves unknown places through Nominatim and obtains road distance/duration/geometry from OSRM.
- `app/routers/geo.py`, `universities.py`, and `accommodations.py` expose deterministic APIs for frontend and other clients.

The chatbot does not use an LLM to invent properties, prices, coordinates, availability, distances, or travel times. An optional language-model layer may be added later above the deterministic tools.

## Database

The application uses synchronous SQLAlchemy and the existing `nyumbasalama.db` SQLite database by default. `init_db()` creates missing tables and adds only nullable property metadata columns. Existing rows are not deleted or marked available automatically.

Availability is returned as:

- `available`: explicitly stored as available
- `unavailable`: explicitly unavailable/rented
- `unknown`: no current status is stored

Unknown records are never described as currently available.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | API health |
| `POST /api/ai/chat` | New structured AI chat API |
| `POST /chat` | Compatibility chat path |
| `GET /api/universities` | Curated university/campus records and aliases |
| `GET /api/universities/{id}` | University detail |
| `GET /api/accommodations` | Structured listing search |
| `GET /api/accommodations/{id}` | Listing detail |
| `GET /api/search?q=...` | Natural-language listing search |
| `GET /api/geo/geocode?q=Sinza` | Local/external geocoding |
| `GET /api/geo/distance` | Straight-line and route distance |
| `POST /api/geo/route` | OSRM route with distance, duration, and GeoJSON |
| `POST /api/geo/accommodations/search` | Structured spatial listing search |

The same new endpoints are available without `/api` for existing local clients.

## Environment

Copy `.env.example` to `.env`:

```text
DATABASE_URL=sqlite:///./nyumbasalama.db
GEOCODING_ENABLED=true
GEOCODER_BASE_URL=https://nominatim.openstreetmap.org
GEOCODER_USER_AGENT=NyumbaSalama/1.0 (+https://nyumbasalama.com/contact)
ROUTING_ENABLED=true
ROUTING_BASE_URL=https://router.project-osrm.org
ROUTING_SUPPORTED_MODES=driving
GEO_HTTP_TIMEOUT=6
GEO_CACHE_TTL_SECONDS=86400
ROUTE_CACHE_TTL_SECONDS=1800
```

Nominatim and the public OSRM endpoint are external services with rate limits. Configure a hosted/provider endpoint for production traffic. If routing is unavailable, the API returns an unavailable route and the assistant does not estimate it.

## Local Development

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The frontend defaults to `http://127.0.0.1:8000` through `NEXT_PUBLIC_API_BASE_URL`.

## Verification

```bash
python -m compileall -q app
python -m unittest discover -s tests -p "test_*.py"
```

From `nyumbasalama-frontend`:

```bash
npm run build
npx tsc --noEmit --incremental false
```
