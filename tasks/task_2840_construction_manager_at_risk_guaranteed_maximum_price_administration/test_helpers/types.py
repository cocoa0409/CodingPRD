"""Type aliases shared by the helper modules and the test suite.

The API speaks JSON, so responses arrive as plain dictionaries. These aliases
name the shapes the tests pass around so signatures stay readable.
"""

from decimal import Decimal
from typing import Any, Dict, List, Mapping, Tuple, Union

#: A decoded JSON object, e.g. the ``data`` member of a success envelope.
JsonObject = Dict[str, Any]

#: A decoded JSON array of objects, e.g. the ``data`` member of a list response.
JsonArray = List[JsonObject]

#: A request payload ready to be serialised.
Payload = Dict[str, Any]

#: The request headers carrying the operator identity and role.
Headers = Mapping[str, str]

#: The pagination block of a list response.
PageMeta = Dict[str, Any]

#: A list response decomposed into its rows and its pagination block.
Page = Tuple[JsonArray, PageMeta]

#: Anything a money or ratio field may legitimately arrive as.
Numeric = Union[str, int, float, Decimal]
