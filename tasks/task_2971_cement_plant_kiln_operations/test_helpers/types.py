"""Type aliases for the payload and row shapes exchanged with the API."""

from typing import Any, Dict, List, Tuple

Headers = Dict[str, str]
Payload = Dict[str, Any]
Row = Dict[str, Any]
RowList = List[Row]
Meta = Dict[str, Any]
Page = Tuple[RowList, Meta]

__all__ = ["Headers", "Payload", "Row", "RowList", "Meta", "Page"]
