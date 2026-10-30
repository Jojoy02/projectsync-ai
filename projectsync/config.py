from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8080"))
    database_path: str = os.getenv("DATABASE_PATH", "./data/projectsync.sqlite3")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "")
    admin_token: str = os.getenv("API_ADMIN_TOKEN", "")
    enable_scheduler: bool = os.getenv("ENABLE_SCHEDULER", "true").lower() == "true"
    writeback_enabled: bool = os.getenv("WRITEBACK_ENABLED", "false").lower() == "true"
    dify_base_url: str = os.getenv("DIFY_BASE_URL", "https://api.dify.ai").rstrip("/")
    dify_app_api_key: str = os.getenv("DIFY_APP_API_KEY", "")
    dify_timeout_seconds: float = float(os.getenv("DIFY_TIMEOUT_SECONDS", "45"))
    feishu_api_base: str = os.getenv("FEISHU_API_BASE", "https://open.feishu.cn/open-apis").rstrip("/")
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "")
    feishu_verification_token: str = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
    feishu_encrypt_key: str = os.getenv("FEISHU_ENCRYPT_KEY", "")
    feishu_calendar_id: str = os.getenv("FEISHU_CALENDAR_ID", "")
    feishu_timezone: str = os.getenv("FEISHU_TIMEZONE", "Asia/Shanghai")
    default_daily_time: str = os.getenv("DEFAULT_DAILY_TIME", "18:00")
    default_weekly_day: int = int(os.getenv("DEFAULT_WEEKLY_DAY", "4"))
    default_weekly_time: str = os.getenv("DEFAULT_WEEKLY_TIME", "18:00")
    http_timeout_seconds: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "20"))

    @property
    def db_path(self) -> Path:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

settings = Settings()
