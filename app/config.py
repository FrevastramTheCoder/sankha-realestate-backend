import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./nyumbasalama.db"
    JWT_SECRET: str = ""
    JWT_EXPIRES_IN: str = "7d"
    PORT: int = 8000
    FRONTEND_URL: str = "https://nyumbasalama-frontend.netlify.app"
    ALLOWED_ORIGINS: str = "http://localhost:3000,https://nyumbasalama-frontend.netlify.app"
    GEOCODING_ENABLED: bool = True
    GEOCODER_BASE_URL: str = "https://nominatim.openstreetmap.org"
    GEOCODER_USER_AGENT: str = "NyumbaSalama/1.0 (+https://nyumbasalama.com/contact)"
    ROUTING_ENABLED: bool = True
    ROUTING_BASE_URL: str = "https://router.project-osrm.org"
    ROUTING_SUPPORTED_MODES: str = "driving"
    GEO_HTTP_TIMEOUT: float = 6.0
    GEO_CACHE_TTL_SECONDS: int = 86400
    ROUTE_CACHE_TTL_SECONDS: int = 1800

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
