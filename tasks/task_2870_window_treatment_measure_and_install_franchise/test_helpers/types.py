"""Type aliases for the resource payloads exchanged with the franchise API."""

from typing import Any, Dict, List, Optional, Tuple

Json = Dict[str, Any]
Headers = Dict[str, str]

Territory = Json
Designer = Json
SampleKit = Json
Lead = Json
Consultation = Json
SampleCheckout = Json
Opening = Json
Quote = Json
Vendor = Json
VendorOrder = Json
InstallJob = Json
LedgerEntry = Json

PageResult = Tuple[List[Json], Json]

OptionalStr = Optional[str]
