from .base import ChannelAdapter


class WebChannelAdapter(ChannelAdapter):
    """Messages surface in the web UI; delivery is immediate by definition."""

    name = "web"

    async def send(self, participant: dict, text: str) -> dict:
        return {"status": "delivered", "channel": "web", "text": text}

    def is_available(self) -> bool:
        return True
