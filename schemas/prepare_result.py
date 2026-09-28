from typing import NamedTuple, Any


class PrepareResult(NamedTuple):
    mode: str
    text: str
    extra: Any = None
