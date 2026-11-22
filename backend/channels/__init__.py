from .base import ChannelAdapter
from .web import WebChannelAdapter

_registry: dict[str, ChannelAdapter] = {}
_web = WebChannelAdapter()
_registry[_web.name] = _web


def get_channel(name: str) -> ChannelAdapter:
    channel = _registry.get(name)
    if channel is None:
        raise KeyError(f"Unknown channel: {name}")
    return channel


def register_channel(adapter: ChannelAdapter) -> None:
    _registry[adapter.name] = adapter
