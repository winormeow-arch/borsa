"""Settings read from the environment (optionally a git-ignored .env file)."""
import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Config:
    alpaca_key: str
    alpaca_secret: str
    alpaca_base_url: str
    alpaca_data_url: str
    mirror_allocation: float
    active_members: int
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_to: str

    @property
    def is_paper(self) -> bool:
        return "paper-api" in self.alpaca_base_url

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.email_to)


def load() -> Config:
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    env = os.environ
    key, secret = env.get("ALPACA_API_KEY", ""), env.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise SystemExit("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set")
    allocation = float(env.get("MIRROR_ALLOCATION", "0.95"))
    if not 0 < allocation <= 1:
        raise SystemExit("MIRROR_ALLOCATION must be in (0, 1]")
    return Config(
        alpaca_key=key,
        alpaca_secret=secret,
        alpaca_base_url=env.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets/v2").rstrip("/"),
        alpaca_data_url=env.get("ALPACA_DATA_URL", "https://data.alpaca.markets/v2").rstrip("/"),
        mirror_allocation=allocation,
        active_members=int(env.get("ACTIVE_MEMBERS", "20")),
        smtp_host=env.get("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(env.get("SMTP_PORT", "587")),
        smtp_user=env.get("SMTP_USER", ""),
        smtp_password=env.get("SMTP_PASSWORD", ""),
        email_to=env.get("EMAIL_TO", ""),
    )
