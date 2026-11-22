"""Launch Kile with logging to file: python run_server.py"""

import logging
from logging.handlers import RotatingFileHandler

import uvicorn

from backend.config import settings

handler = RotatingFileHandler(
    "kile.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
)
handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
)
logging.basicConfig(level=logging.INFO, handlers=[handler])

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
    )
