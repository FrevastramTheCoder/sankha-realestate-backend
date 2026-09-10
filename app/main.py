import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ✅ load_dotenv LAZIMA iwe KABLA ya imports za app
load_dotenv()

from app.database import SessionLocal, init_db
from app.services.seed import seed_admin
from app.routers import (
    accommodations,
    admin,
    auth,
    favorites,
    geo,
    images,
    properties,
    reviews,
    universities,
    users,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
UPLOADS_DIR = os.path.join(PROJECT_ROOT, "uploads")
IMAGES_DIR = os.path.join(UPLOADS_DIR, "images")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "app.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("nyumbasalama")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting NyumbaSalama API")
    init_db()
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()
    logger.info("NyumbaSalama API is ready")
    yield
    logger.info("NyumbaSalama API stopped")


app = FastAPI(
    title="NyumbaSalama API",
    description="Student accommodation platform",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

_configured_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "https://nyumbasalama.com",
    "https://www.nyumbasalama.com",
    "https://api.nyumbasalama.com",
    os.getenv("FRONTEND_URL", ""),
]
ALLOWED_ORIGINS = list(dict.fromkeys(origin for origin in _configured_origins if origin))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
    expose_headers=["Content-Length", "Content-Type"],
    max_age=600,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "status_code": exc.status_code,
            "message": str(exc.detail),
            "path": request.url.path,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "status_code": 500,
            "message": "Internal server error. Please try again later.",
            "path": request.url.path,
        },
    )


app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# ============================================================
# ROUTERS
# ============================================================
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(properties.router)
app.include_router(reviews.router)
app.include_router(favorites.router)
app.include_router(admin.router)
app.include_router(images.router)

# New routes (without ai)
for current_router in (geo.router, accommodations.router, universities.router):
    app.include_router(current_router)
    app.include_router(current_router, prefix="/api")


@app.get("/", tags=["System"])
async def root():
    return {
        "success": True,
        "message": "NyumbaSalama API is running",
        "application": "NyumbaSalama",
        "version": "2.0.0",
        "status": "online",
        "endpoints": {
            "docs": "/docs",
            "health": "/api/health",
            "auth": "/auth",
            "images": "/images",
            "uploads": "/uploads",
            "chat": "/chat",
        },
    }


@app.get("/api/health", tags=["System"])
async def health_check():
    return {
        "success": True,
        "status": "healthy",
        "application": "NyumbaSalama API",
        "version": "2.0.0",
        "cors": {"enabled": True, "origins": ALLOWED_ORIGINS},
        "uploads": {
            "enabled": True,
            "directory_exists": os.path.isdir(UPLOADS_DIR),
            "images_directory_exists": os.path.isdir(IMAGES_DIR),
        },
        "routers": {
            "auth": True,
            "properties": True,
            "images": True,
            "universities": True,
            "accommodations": True,
            "geo": True,
            
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("DEBUG", "false").casefold() == "true",
    )