"""Domain types for the Textile & Apparel Labeling Compliance API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    BRAND_ADMIN = "BrandAdmin"
    LABELING_SPECIALIST = "LabelingSpecialist"
    LABELING_APPROVER = "LabelingApprover"
    ACCREDITED_LAB = "AccreditedLab"
    CUSTOMS_OFFICER = "CustomsOfficer"
    AUDITOR = "Auditor"


class PartyType(str, Enum):
    BRAND_OWNER = "BRAND_OWNER"
    PRIVATE_LABEL_RETAILER = "PRIVATE_LABEL_RETAILER"
    LICENSEE = "LICENSEE"


class ResponsibilityMode(str, Enum):
    SELF_OF_RECORD = "SELF_OF_RECORD"
    LICENSOR_OF_RECORD = "LICENSOR_OF_RECORD"


class BrandPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class ProductClass(str, Enum):
    WOVEN_OUTERWEAR = "WOVEN_OUTERWEAR"
    KNIT_TOP = "KNIT_TOP"
    HOSIERY = "HOSIERY"
    HOME_TEXTILE = "HOME_TEXTILE"


class SubstantiationState(str, Enum):
    FIBER_DECLARED = "FIBER_DECLARED"
    FIBER_TEST_PENDING = "FIBER_TEST_PENDING"
    FIBER_SUBSTANTIATED = "FIBER_SUBSTANTIATED"
    FIBER_MISSTATED = "FIBER_MISSTATED"


class OriginState(str, Enum):
    ORIGIN_UNDETERMINED = "ORIGIN_UNDETERMINED"
    ORIGIN_DRAFTED = "ORIGIN_DRAFTED"
    ORIGIN_ISSUED = "ORIGIN_ISSUED"


class LabelReadiness(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class MaterialStage(str, Enum):
    TRIM = "TRIM"
    FIBER = "FIBER"
    YARN = "YARN"
    FABRIC = "FABRIC"
    CUT_AND_SEW = "CUT_AND_SEW"


class TestType(str, Enum):
    FIBER_CONTENT = "FIBER_CONTENT"
    CARE_PERFORMANCE = "CARE_PERFORMANCE"


class TestMethod(str, Enum):
    AATCC_20A = "AATCC_20A"
    ISO_1833 = "ISO_1833"
    AATCC_135 = "AATCC_135"
    ISO_6330 = "ISO_6330"


class LabTestState(str, Enum):
    BENCH_RESERVED = "BENCH_RESERVED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class OriginDeterminationState(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class OriginMethod(str, Enum):
    SUBSTANTIAL_TRANSFORMATION = "SUBSTANTIAL_TRANSFORMATION"
    YARN_FORWARD = "YARN_FORWARD"


class ArtifactType(str, Enum):
    PERMANENT_LABEL = "PERMANENT_LABEL"
    HANGTAG = "HANGTAG"


class LabelSpecState(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class ConsistencyState(str, Enum):
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PlacementCode(str, Enum):
    NECK_CENTER_INSIDE = "NECK_CENTER_INSIDE"
    SIDE_SEAM_INSIDE = "SIDE_SEAM_INSIDE"
    WAISTBAND_INSIDE = "WAISTBAND_INSIDE"
    NOT_PERMANENT = "NOT_PERMANENT"


class MarketingClaim(str, Enum):
    MADE_IN_USA = "MADE_IN_USA"
    ORGANIC_COTTON = "ORGANIC_COTTON"
    WRINKLE_FREE = "WRINKLE_FREE"


class MarkingState(str, Enum):
    ENTRY_FILED = "ENTRY_FILED"
    MARKING_COMPLIANT = "MARKING_COMPLIANT"
    REDELIVERY_ORDERED = "REDELIVERY_ORDERED"
    MARKING_CORRECTED = "MARKING_CORRECTED"


class DeficiencyCode(str, Enum):
    MISSING_ORIGIN = "MISSING_ORIGIN"
    WRONG_ORIGIN = "WRONG_ORIGIN"
    MISSING_IDENTITY = "MISSING_IDENTITY"
    NON_PERMANENT_PLACEMENT = "NON_PERMANENT_PLACEMENT"
    LANGUAGE_DEFICIENT = "LANGUAGE_DEFICIENT"


class AssessmentBasis(str, Enum):
    AD_VALOREM = "AD_VALOREM"
    STATUTORY_PER_UNIT = "STATUTORY_PER_UNIT"


class AuditScope(str, Enum):
    STYLE_DOSSIER = "STYLE_DOSSIER"
    MARKET_LABELING = "MARKET_LABELING"
    IMPORT_MARKING = "IMPORT_MARKING"


class AuditState(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    PENDING_CLOSURE = "PENDING_CLOSURE"
    CLOSED = "CLOSED"


class FindingCode(str, Enum):
    FIBER_CONTENT_MISSTATED = "FIBER_CONTENT_MISSTATED"
    ORIGIN_MISSTATED = "ORIGIN_MISSTATED"
    CARE_UNSUBSTANTIATED = "CARE_UNSUBSTANTIATED"
    IDENTITY_MISSING = "IDENTITY_MISSING"
    PLACEMENT_NON_PERMANENT = "PLACEMENT_NON_PERMANENT"
    HANGTAG_INCONSISTENT = "HANGTAG_INCONSISTENT"


class FindingSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FindingState(str, Enum):
    OPEN = "OPEN"
    REMEDIATED = "REMEDIATED"
    CLOSED = "CLOSED"


class WithdrawnReason(str, Enum):
    AUTO_FIBER_MISSTATED = "AUTO_FIBER_MISSTATED"
    AUTO_ORIGIN_VOIDED = "AUTO_ORIGIN_VOIDED"
    AUTO_PARENT_WITHDRAWN = "AUTO_PARENT_WITHDRAWN"


# --- Entity shapes -------------------------------------------------------


class Brand(TypedDict):
    id: str
    legal_name: str
    party_type: str
    rn_number: Optional[str]
    licensor_brand_id: Optional[str]
    responsibility_mode: str
    responsible_brand_id: str
    outstanding_penalty_usd: float
    critical_audit_finding_count: int
    posture: str
    created_at: str
    updated_at: str
    version: int


# A market regime is immutable once registered: only id and created_at.
class MarketRequirement(TypedDict):
    id: str
    market_code: str
    required_languages: List[str]
    fiber_tolerance_pp: float
    absolute_claim_tolerance_pp: float
    min_durability_cycles: int
    marking_duty_rate: float
    requires_identity_disclosure: bool
    requires_origin_statement: bool
    created_at: str


class Style(TypedDict):
    id: str
    brand_id: str
    style_code: str
    product_class: str
    target_market_codes: List[str]
    net_weight_grams: float
    declared_fibers: List[dict]
    substantiation_state: str
    origin_state: str
    label_readiness: str
    effective_fiber_content_text: str
    created_at: str
    updated_at: str
    version: int


class MaterialInput(TypedDict):
    id: str
    style_id: str
    parent_input_id: Optional[str]
    stage: str
    country_code: str
    value_added_usd: float
    weight_grams: float
    is_ornamentation: bool
    depth: int
    created_at: str
    updated_at: str
    version: int


class LabTest(TypedDict):
    id: str
    style_id: str
    test_type: str
    lab_code: str
    method: str
    specimen_received_at: str
    results_due_at: str
    wash_temp_c: Optional[int]
    cycles_run: Optional[int]
    measured_fibers: Optional[List[dict]]
    dimensional_change_pct: Optional[float]
    colorfastness_grade: Optional[float]
    legibility_cycles: Optional[int]
    state: str
    attempt_no: int
    result_delta_pp_max: Optional[float]
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OriginDetermination(TypedDict):
    id: str
    style_id: str
    state: str
    method_pinned: Optional[str]
    st_country: str
    yf_country: str
    divergent: bool
    determined_country: Optional[str]
    graph_node_count: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabelSpec(TypedDict):
    id: str
    style_id: str
    artifact_type: str
    parent_label_spec_id: Optional[str]
    origin_determination_id: Optional[str]
    care_test_id: Optional[str]
    market_codes: List[str]
    languages: List[str]
    placement_code: str
    durability_cycles_rating: int
    wash_temp_c: Optional[int]
    bleach_code: str
    dry_code: str
    iron_code: str
    dryclean_code: str
    identity_display_mode: str
    fiber_content_text: str
    origin_text: str
    marketing_claims: List[str]
    state: str
    authored_by_user_id: str
    approved_by_user_id: Optional[str]
    revision_note: Optional[str]
    withdrawn_reason: Optional[str]
    effective_from: Optional[str]
    effective_to: Optional[str]
    content_hash: str
    consistency_state: str
    created_at: str
    updated_at: str
    version: int


class ImportShipment(TypedDict):
    id: str
    importer_brand_id: str
    style_id: str
    corrective_label_spec_id: Optional[str]
    entry_number: str
    quantity_units: int
    declared_value_usd: float
    entry_market_code: str
    marking_state: str
    deficiency_code: Optional[str]
    review_decided_at: Optional[str]
    redelivery_deadline_at: Optional[str]
    posture_at_review: Optional[str]
    assessment_basis: Optional[str]
    penalty_ad_valorem_usd: Optional[float]
    penalty_statutory_usd: Optional[float]
    penalty_assessed_usd: float
    penalty_mitigated_usd: float
    corrected_units: int
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict):
    id: str
    brand_id: str
    scope: str
    audit_window_from: str
    audit_window_to: str
    state: str
    open_finding_count: int
    critical_finding_count: int
    units_in_scope: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    audit_id: str
    style_id: str
    corrective_label_spec_id: Optional[str]
    finding_code: str
    severity: str
    units_affected: int
    units_relabeled: int
    units_destroyed: int
    units_released: int
    units_unresolved: int
    state: str
    disposition_recorded_at: Optional[str]
    verified_at: Optional[str]
    reopen_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
