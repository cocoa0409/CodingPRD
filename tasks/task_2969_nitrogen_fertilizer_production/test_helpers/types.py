"""Lightweight structural aliases for the thirteen resource families.

These are documentation-grade aliases, not runtime validators: every API
response is a plain JSON object, so tests index it directly. The aliases exist
so helper signatures state which family they carry.
"""

from typing import Any, Dict, List, Optional, Tuple

Json = Dict[str, Any]

Plant = Json
ReformerTrain = Json
CatalystCharge = Json
GasHedgeLot = Json
ProductLine = Json
ProductionRun = Json
ProductionOrder = Json
StorageAsset = Json
Shipment = Json
PriceQuote = Json
Turnaround = Json
TurnaroundTask = Json
EmissionsReading = Json

Headers = Dict[str, str]
Payload = Dict[str, Any]
ListPage = Tuple[List[Json], Json]

# Field groups used by the shared assertions.

# Present on every family (PRD 2.4).
IDENTITY_FIELDS = ("id", "created_at")

# Present on every family except ProductLine and EmissionsReading (PRD 2.4).
VERSIONED_FIELDS = ("updated_at", "version")

# The four derived storage position figures (PRD 3.6).
POSITION_FIELDS = (
    "on_hand_tons",
    "reserved_tons",
    "seasonal_reserve_tons",
    "available_tons",
)

# The freight breakdown written at booking (PRD 3.7).
FREIGHT_FIELDS = (
    "base_freight_usd",
    "fuel_surcharge_usd",
    "freight_total_usd",
    "freight_per_ton_usd",
)

__all__ = [
    "Json",
    "Plant",
    "ReformerTrain",
    "CatalystCharge",
    "GasHedgeLot",
    "ProductLine",
    "ProductionRun",
    "ProductionOrder",
    "StorageAsset",
    "Shipment",
    "PriceQuote",
    "Turnaround",
    "TurnaroundTask",
    "EmissionsReading",
    "Headers",
    "Payload",
    "ListPage",
    "IDENTITY_FIELDS",
    "VERSIONED_FIELDS",
    "POSITION_FIELDS",
    "FREIGHT_FIELDS",
    "Optional",
    "List",
]
