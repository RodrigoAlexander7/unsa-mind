from unsa_mind.domain.errors import LLMError


class TransientLLMError(LLMError):
    """Fallo reintentable (429, 5xx, timeouts, red)."""


__all__ = ["LLMError", "TransientLLMError"]
