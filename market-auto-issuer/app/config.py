from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Yandex Market API
    MARKET_API_TOKEN: str = ""
    MARKET_API_BASE: str = "https://api.partner.market.yandex.ru"
    MARKET_BUSINESS_ID: str = ""
    MARKET_CAMPAIGN_ID: str = ""

    # Webhook security
    WEBHOOK_SHARED_SECRET: Optional[str] = None

    # Delivery mode
    DELIVERY_MODE: str = "yandex_digital"

    # Database
    DATABASE_URL: str = "postgresql://marketuser:marketpass@db:5432/marketdb"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # App metadata
    APP_NAME: str = "Market Auto Issuer"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Admin UI – set a password to protect the admin panel
    ADMIN_SECRET: str = "changeme"

    # Which order statuses are allowed to trigger fulfillment
    ALLOWED_ISSUE_STATUSES: list[str] = ["PROCESSING"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
