"""Domain types: entity shapes, status enums, and roles for the pizza-day API."""

from typing import Any, Dict, List, Tuple

# A JSON object as decoded from a response body or handed to a request body.
JsonObject = Dict[str, Any]
JsonList = List[Any]

# The two request headers every call must carry.
Headers = Dict[str, str]

# Query-string filters for a list endpoint.
Filters = Dict[str, Any]

# ``validate_paginated`` hands back the row list and the pagination block together.
PaginatedResult = Tuple[JsonList, JsonObject]

# Identifiers are server-minted UUID strings with no type prefix.
ResourceId = str

# --------------------------------------------------------------------- roles
ROLE_STORE_MANAGER = "StoreManager"
ROLE_SHIFT_LEAD = "ShiftLead"
ROLE_CREW_MEMBER = "CrewMember"
ROLE_CUSTOMER = "Customer"


# -------------------------------------------------------------- status enums
class StoreDayStatus:
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class DaypartLabel:
    LUNCH = "LUNCH"
    DINNER = "DINNER"
    LATE_NIGHT = "LATE_NIGHT"


class DaypartStatus:
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class DaypartPosture:
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"


class DemandEventStatus:
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class DoughBatchStatus:
    MIXING = "MIXING"
    PROOFING = "PROOFING"
    PROOFED = "PROOFED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class CheeseBatchStatus:
    PREPPING = "PREPPING"
    RESTING = "RESTING"
    READY = "READY"
    DEPLETED = "DEPLETED"


class ProductionRunStatus:
    PLANNED = "PLANNED"
    BAKING = "BAKING"
    HOLDING = "HOLDING"
    CLOSED = "CLOSED"


class HoldUnitStatus:
    HOLDING = "HOLDING"
    ALLOCATED = "ALLOCATED"
    SOLD = "SOLD"
    DISCARDED = "DISCARDED"


class DiscardReason:
    HOLD_EXPIRED = "HOLD_EXPIRED"
    DAMAGED = "DAMAGED"
    QUALITY = "QUALITY"
    NO_SHOW = "NO_SHOW"


class OrderKind:
    PORTAL_STANDARD = "PORTAL_STANDARD"
    PORTAL_PREORDER = "PORTAL_PREORDER"
    COUNTER = "COUNTER"


class PaymentStatus:
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus:
    PLACED = "PLACED"
    IN_PREPARATION = "IN_PREPARATION"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"
    EXPIRED_NO_SHOW = "EXPIRED_NO_SHOW"


class LockerSlotStatus:
    IDLE = "IDLE"
    OCCUPIED = "OCCUPIED"
    CLEANING = "CLEANING"


class Station:
    OVEN = "OVEN"
    CUT_TABLE = "CUT_TABLE"
    LOCKER_BAY = "LOCKER_BAY"
    DOUGH_PREP = "DOUGH_PREP"


class CrewShiftStatus:
    SCHEDULED = "SCHEDULED"
    ENDED = "ENDED"


__all__ = [
    "JsonObject",
    "JsonList",
    "Headers",
    "Filters",
    "PaginatedResult",
    "ResourceId",
    "ROLE_STORE_MANAGER",
    "ROLE_SHIFT_LEAD",
    "ROLE_CREW_MEMBER",
    "ROLE_CUSTOMER",
    "StoreDayStatus",
    "DaypartLabel",
    "DaypartStatus",
    "DaypartPosture",
    "DemandEventStatus",
    "DoughBatchStatus",
    "CheeseBatchStatus",
    "ProductionRunStatus",
    "HoldUnitStatus",
    "DiscardReason",
    "OrderKind",
    "PaymentStatus",
    "FulfillmentStatus",
    "LockerSlotStatus",
    "Station",
    "CrewShiftStatus",
]
