"""Provider factory — returns the configured market data adapter.

Usage:
    from src.data.providers.provider_factory import get_provider
    provider = get_provider()  # uses config, defaults to 'angelone'
    ltp = provider.get_ltp(["NIFTY", "BANKNIFTY"])
"""
from __future__ import annotations
from typing import Optional
from .base import MarketDataProvider

# Registry maps provider name → lazy-loaded class
_REGISTRY: dict[str, str] = {
    "angelone":  "src.data.providers.angelone_provider.AngelOneProvider",
    "upstox":    "src.data.providers.upstox_provider.UpstoxProvider",
    "aliceblue": "src.data.providers.aliceblue_provider.AliceBlueProvider",
    "zerodha":   "src.data.providers.zerodha_provider.ZerodhaProvider",
    "dhan":      "src.data.providers.dhan_provider.DhanProvider",
    "fyers":     "src.data.providers.fyers_provider.FyersProvider",
    "shoonya":   "src.data.providers.shoonya_provider.ShoonyaProvider",
    "truedata":  "src.data.providers.truedata_provider.TrueDataProvider",
}

_CACHE: dict[str, MarketDataProvider] = {}


def get_provider(name: Optional[str] = None) -> MarketDataProvider:
    """Return the configured market data provider instance.
    
    Args:
        name: Provider name (e.g., 'angelone', 'upstox'). If None, reads
              from config.settings.data_provider (default: 'angelone').
    
    Returns:
        MarketDataProvider instance.
    
    Raises:
        ValueError: If provider name is not registered.
        RuntimeError: If provider dependencies or credentials are missing.
    """
    if name is None:
        try:
            from config import settings
            name = getattr(settings, "data_provider", "angelone")
        except ImportError:
            name = "angelone"
    
    name = name.lower()
    
    if name in _CACHE:
        return _CACHE[name]
    
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(
            f"Unknown provider '{name}'. Available: {available}"
        )
    
    # Lazy import
    module_path, class_name = _REGISTRY[name].rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    
    instance = cls()
    if not instance.is_available:
        raise RuntimeError(
            f"Provider '{name}' is not available. Check dependencies and credentials."
        )
    
    _CACHE[name] = instance
    return instance


def list_providers() -> list[dict[str, str]]:
    """List all registered providers and their availability."""
    results = []
    for name, fqn in sorted(_REGISTRY.items()):
        try:
            provider = get_provider(name)
            results.append({
                "name": name,
                "available": provider.is_available,
                "class": fqn,
            })
        except Exception as e:
            results.append({
                "name": name,
                "available": False,
                "error": str(e),
                "class": fqn,
            })
    return results
