class UnsaMindError(Exception):
    """Base de errores del dominio/aplicación."""


class FetchError(UnsaMindError):
    pass


class ParseError(UnsaMindError):
    pass


class LLMError(UnsaMindError):
    pass


class NotFoundError(UnsaMindError):
    pass
