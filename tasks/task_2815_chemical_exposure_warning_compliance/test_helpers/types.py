"""Lightweight typing aliases for request payloads and response rows.

These exist for readability inside the client and factories; the API is plain
JSON so nothing here is enforced at runtime.
"""

from typing import Any, Dict, List, Literal, Optional, Tuple

# ─── Generic shapes ───────────────────────────────────────────────────────────
Payload = Dict[str, Any]
Headers = Dict[str, str]
Row = Dict[str, Any]
RowList = List[Row]
Meta = Dict[str, Any]
Page = Tuple[RowList, Meta]
QueryParams = Dict[str, Any]

# ─── Enumerations mirrored from the PRD ───────────────────────────────────────
Role = Literal[
    "RegistryAdmin",
    "ComplianceAnalyst",
    "ToxicologyReviewer",
    "LabelingSpecialist",
    "RegulatoryCounsel",
    "SupplierPortalUser",
]

EndpointType = Literal[
    "CANCER", "REPRODUCTIVE_FEMALE", "REPRODUCTIVE_MALE", "DEVELOPMENTAL"
]
HarmClass = Literal["CANCER", "REPRODUCTIVE"]
SafeHarborBasis = Literal["NSRL", "MADL", "NONE"]
ChemicalStatus = Literal["PROPOSED", "LISTED", "WITHDRAWN", "DELISTED"]

WarrantyStatus = Literal["NONE", "ACTIVE", "REVOKED"]
MaterialClass = Literal["RAW_MATERIAL", "PACKAGING", "MANUFACTURING_AID"]
DisclosureStatus = Literal[
    "NOT_REQUESTED", "REQUESTED", "RECEIVED", "INCOMPLETE", "REFUSED", "VERIFIED"
]
MeasurementBasis = Literal["SUPPLIER_DECLARED", "LAB_TESTED"]
LinkStatus = Literal[
    "DECLARED", "TEST_REQUESTED", "TEST_REPORTED", "DISPUTED", "VERIFIED"
]

ProductCategory = Literal[
    "CONSUMER_GOOD", "FOOD", "DIETARY_SUPPLEMENT", "FURNITURE", "VEHICLE_PART"
]
DistributionChannel = Literal["RETAIL", "CATALOG", "INTERNET"]
LifecycleState = Literal["DEVELOPMENT", "MARKETED", "DISCONTINUED"]
CompliancePosture = Literal[
    "EXPOSURE_UNKNOWN",
    "CLEAR",
    "WARNING_REQUIRED",
    "WARNING_ACTIVE",
    "ENFORCEMENT_HOLD",
]
ComponentStatus = Literal["ACTIVE", "REMOVED", "SUPERSEDED"]

AssessmentMethod = Literal["MODELED", "LAB_TESTED"]
ExposureRoute = Literal["ORAL", "DERMAL", "INHALATION"]
AssessmentStatus = Literal[
    "DRAFT", "SUBMITTED", "PEER_REVIEWED", "REJECTED", "FINAL", "SUPERSEDED"
]
AssessmentResult = Literal[
    "BELOW_SAFE_HARBOR", "AT_OR_ABOVE_SAFE_HARBOR", "NO_SAFE_HARBOR"
]

WarningDecision = Literal["WARNING_REQUIRED", "NO_WARNING_REQUIRED"]
WarningType = Literal[
    "NONE", "PRODUCT_SPECIFIC_SHORT", "PRODUCT_SPECIFIC_LONG", "OCCUPANCY"
]
DeterminationStatus = Literal[
    "DRAFT", "PENDING_APPROVAL", "APPROVED", "REVOKED", "SUPERSEDED"
]
RequiredChannel = Literal["LABEL", "CATALOG", "INTERNET_POS", "POSTED_SIGN"]
PlacementStatus = Literal["PLANNED", "IMPLEMENTED", "VERIFIED", "NON_COMPLIANT"]

NoticingPartyType = Literal["PRIVATE_PARTY", "ATTORNEY_GENERAL", "DISTRICT_ATTORNEY"]
ViolationType = Literal[
    "FAILURE_TO_WARN", "INADEQUATE_WARNING_CONTENT", "EXPOSURE_LEVEL_DISPUTE"
]
NoticeStatus = Literal[
    "RECEIVED",
    "UNDER_EVALUATION",
    "CURE_ELECTED",
    "CURED_WITHIN_WINDOW",
    "CURE_FAILED",
    "SETTLEMENT_NEGOTIATION",
    "SETTLED",
    "LITIGATION",
    "DISMISSED",
]
SettlementStatus = Literal["PROPOSED", "COUNTERED", "EXECUTED", "VOID"]
ProjectStatus = Literal[
    "PLANNED", "IN_PROGRESS", "VERIFICATION", "COMPLETED", "ABANDONED"
]
SummaryVariant = Literal["AS_OF_TODAY", "AS_OF_SERVICE_DATE"]

OptionalStr = Optional[str]
OptionalFloat = Optional[float]
OptionalInt = Optional[int]
