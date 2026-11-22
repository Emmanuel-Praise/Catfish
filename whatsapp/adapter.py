"""WhatsApp Cloud API channel adapter (Meta Graph API)."""

import httpx

from backend.channels.base import ChannelAdapter
from backend.config import settings


class WhatsAppAdapter(ChannelAdapter):
    name = "whatsapp"

    def __init__(self, access_token: str = "", phone_number_id: str = "", api_version: str = ""):
        self.access_token = access_token or settings.whatsapp_access_token
        self.phone_number_id = phone_number_id or settings.whatsapp_phone_id
        self.api_version = api_version or settings.whatsapp_api_version

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    def is_available(self) -> bool:
        return bool(self.access_token and self.phone_number_id)

    async def send(self, participant: dict, text: str) -> dict:
        if not self.is_available():
            return {"status": "failed", "channel": "whatsapp", "error": "not configured"}
        to = _normalize_phone(participant.get("contact_ref") or "")
        if not to:
            return {"status": "failed", "channel": "whatsapp", "error": "no contact_ref"}

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.post(
                    f"{self.base_url}/{self.phone_number_id}/messages",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                )
                data = res.json()
        except httpx.HTTPError as exc:
            return {"status": "failed", "channel": "whatsapp", "error": str(exc)}

        if res.status_code >= 400:
            err = data.get("error", {})
            return {
                "status": "failed",
                "channel": "whatsapp",
                "error": err.get("message", f"HTTP {res.status_code}"),
                "code": err.get("code"),
            }
        messages = data.get("messages", [{}])
        return {
            "status": "sent",
            "channel": "whatsapp",
            "message_id": messages[0].get("id"),
        }

    async def verify_number(self) -> dict:
        """Check credentials against the Graph API without sending anything."""
        if not self.is_available():
            return {"status": "failed", "error": "not configured"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(
                    f"{self.base_url}/{self.phone_number_id}",
                    params={
                        "fields": "verified_name,display_phone_number",
                        "access_token": self.access_token,
                    },
                )
                data = res.json()
        except httpx.HTTPError as exc:
            return {"status": "failed", "error": str(exc)}
        if res.status_code >= 400:
            return {
                "status": "failed",
                "error": data.get("error", {}).get("message", f"HTTP {res.status_code}"),
            }
        return {"status": "ok", **data}


def _normalize_phone(raw: str) -> str:
    """WhatsApp 'to' accepts digits with optional leading +."""
    digits = "".join(ch for ch in str(raw) if ch.isdigit() or ch == "+")
    return digits.lstrip("+")
