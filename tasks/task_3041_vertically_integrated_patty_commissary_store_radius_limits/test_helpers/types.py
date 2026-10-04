"""Domain types: status enums and entity field-name references.

The PRD (section 2.4) guarantees every primary resource carries ``id``,
``created_at``, ``updated_at``, and ``version``.  Status enumerations below
mirror the state machines described in PRD section 3.
"""


class BeefSupplierStatus:
    PROBATION = "PROBATION"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class AuditStatus:
    SCHEDULED = "SCHEDULED"
    RECORDED = "RECORDED"
    CANCELLED = "CANCELLED"


class AuditResult:
    PASS = "PASS"
    FAIL = "FAIL"


class CommissaryStatus:
    PLANNING = "PLANNING"
    BUILDING = "BUILDING"
    OPERATIONAL = "OPERATIONAL"
    DECOMMISSIONED = "DECOMMISSIONED"


class TruckStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RouteType:
    PRIMARY = "PRIMARY"
    RESERVE = "RESERVE"


class DeliveryRouteStatus:
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StoreStatus:
    SITE_REVIEW = "SITE_REVIEW"
    APPROVED = "APPROVED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OpeningMode:
    NORMAL = "NORMAL"
    OPENING_SURGE = "OPENING_SURGE"


class StaffingPosture:
    STEADY = "STEADY"
    STRAINED = "STRAINED"
    CRITICAL = "CRITICAL"


class DeliveryBatchStatus:
    PLANNED = "PLANNED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderStatus:
    PLACED = "PLACED"
    SERVED = "SERVED"
    CANCELLED = "CANCELLED"


class ManagerPostingStatus:
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ManagerApplicationStatus:
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ShiftAssignmentStatus:
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class BeefDeliveryStatus:
    SCHEDULED = "SCHEDULED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class ProductionRunStatus:
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
