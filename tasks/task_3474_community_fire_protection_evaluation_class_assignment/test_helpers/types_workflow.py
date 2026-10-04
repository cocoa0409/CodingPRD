"""TypedDicts for the scoring, classification, and insurance-domain resources.

All of these resources carry the common fields (``id``, ``created_at``,
``updated_at``, ``version``). Nullable fields are typed ``Optional``.
"""
from typing import Any, Dict, List, Optional
from typing import TypedDict


class RiskReductionCredit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    cycle_id: str
    program_type: str
    activity_points: float
    evidence_note: str
    status: str
    credited_points: float
    verified_by: Optional[str]


class ScoreSheet(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    cycle_id: str
    status: str
    equipment_points: float
    staffing_points: float
    staffing_variant_used: str
    training_points: float
    response_points: float
    fd_total_points: float
    supply_points: float
    flow_points: float
    distribution_points: float
    storage_points: float
    water_total_points: float
    water_variant_used: str
    comms_points: float
    crr_raw_points: float
    crr_effective_points: float
    subtotal_points: float
    divergence_penalty_points: float
    adjusted_total_points: float
    base_class: int
    split_class_beyond_hydrant: int


class Classification(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    community_id: str
    cycle_id: str
    score_sheet_id: str
    base_class: int
    split_class_beyond_hydrant: int
    premium_modifier: float
    status: str
    published_by: str
    published_at: str
    effective_from: Optional[str]
    effective_until: Optional[str]


class PropertyRiskProfile(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    community_id: str
    address: str
    distance_to_nearest_hydrant_ft: int
    distance_to_nearest_station_road_miles: float
    construction_type: str
    insured_value_cents: int
    applicable_class: Optional[int]
    applicable_premium_modifier: Optional[float]


class PremiumQuote(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    property_id: str
    classification_id: str
    coverage_amount_cents: int
    base_rate_bp: int
    term_months: int
    coverage_start_date: str
    coverage_end_date: str
    provisional_premium_cents: int
    final_premium_cents: Optional[int]
    status: str
    bound_by: Optional[str]
    bound_at: Optional[str]


class ReevaluationRequest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    community_id: str
    justification: str
    evidence_items: List[Dict[str, Any]]
    status: str
    submitted_by: str
    decision_note: Optional[str]


class Appeal(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    classification_id: str
    community_id: str
    grounds: str
    evidence_items: List[Dict[str, Any]]
    status: str
    filed_by: str
    adjudicated_by: Optional[str]
    new_score_sheet_id: Optional[str]
