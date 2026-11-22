import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .channels import register_channel
from .config import settings
from .database import init_db
from .routers import chat, participants, proactive, whatsapp_webhook

logging.basicConfig(level=logging.INFO)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Kile — AI Conversational Companion", version="1.0.0")

app.include_router(participants.router)
app.include_router(chat.router)
app.include_router(proactive.router)
app.include_router(whatsapp_webhook.router)


@app.on_event("startup")
def startup() -> None:
    init_db()
    if settings.whatsapp_access_token and settings.whatsapp_phone_id:
        from whatsapp.adapter import WhatsAppAdapter

        register_channel(WhatsAppAdapter())
        logging.getLogger("kile").info("WhatsApp channel registered (phone_id=%s)", settings.whatsapp_phone_id)
    else:
        logging.getLogger("kile").warning("WhatsApp credentials missing — web channel only")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "kile",
        "whatsapp_configured": bool(
            settings.whatsapp_access_token and settings.whatsapp_phone_id
        ),
        "message_channel": settings.message_channel,
    }


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
