from abc import ABC, abstractmethod


class ChannelAdapter(ABC):
    """All outgoing messages flow through here.

    To add WhatsApp later: implement this interface in whatsapp/adapter.py
    and register it — no changes needed in chat logic.
    """

    name: str = "base"

    @abstractmethod
    async def send(self, participant: dict, text: str) -> dict:
        """Deliver `text` to `participant`. Returns delivery status dict."""
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError
