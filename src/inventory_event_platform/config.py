from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IEP_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/inventory.db"
    data_dir: Path = Path("./data")
    outbox_max_attempts: int = 3

    @property
    def bus_path(self) -> Path:
        return self.data_dir / "bus" / "inventory_events.ndjson"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.bus_path.parent.mkdir(parents=True, exist_ok=True)
