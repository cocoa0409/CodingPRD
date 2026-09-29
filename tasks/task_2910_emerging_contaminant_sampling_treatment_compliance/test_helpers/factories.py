"""Request-payload builders.

Each builder returns a valid payload for one write endpoint and accepts keyword
overrides. Monetary amounts are emitted as JSON integers of cents and
concentrations, masses and scores as JSON numbers with two decimal places;
every instant is a full ISO-8601 UTC instant with three fractional digits.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CANONICAL_POPULATION_SERVED,
    DELIVERY_MAIL,
    DELIVERY_POSTING,
    MANDATORY_CONTENT_ELEMENTS,
)


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def contaminant_payload(
    code: str = "PFOA",
    mcl_ng_per_l: float = 4.00,
    trigger_level_ng_per_l: float = 2.00,
    required_mrl_ng_per_l: float = 2.00,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "code": code,
            "mcl_ng_per_l": mcl_ng_per_l,
            "trigger_level_ng_per_l": trigger_level_ng_per_l,
            "required_mrl_ng_per_l": required_mrl_ng_per_l,
        },
        overrides,
    )


def hazard_member_payload(
    code: str,
    hbwc_ng_per_l: float,
    mcl_ng_per_l: float = 10.00,
    trigger_level_ng_per_l: float = 5.00,
    required_mrl_ng_per_l: float = 2.00,
    **overrides: Any,
) -> Dict[str, Any]:
    """A contaminant that participates in the mixture hazard index."""
    return _merge(
        {
            "code": code,
            "mcl_ng_per_l": mcl_ng_per_l,
            "trigger_level_ng_per_l": trigger_level_ng_per_l,
            "required_mrl_ng_per_l": required_mrl_ng_per_l,
            "hazard_index_member": True,
            "hbwc_ng_per_l": hbwc_ng_per_l,
        },
        overrides,
    )


def laboratory_payload(
    name: str = "Northgate Analytical",
    certification_id: str = "CERT-001",
    certified_methods: Optional[List[str]] = None,
    lowest_achievable_dl_ng_per_l: float = 1.00,
    certification_expires_on: str = "2027-12-31T00:00:00.000Z",
    daily_analysis_capacity: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "certification_id": certification_id,
            "certified_methods": list(certified_methods or ["METHOD_533"]),
            "lowest_achievable_dl_ng_per_l": lowest_achievable_dl_ng_per_l,
            "certification_expires_on": certification_expires_on,
            "daily_analysis_capacity": daily_analysis_capacity,
        },
        overrides,
    )


def entry_point_payload(
    label: str = "EPTDS-01",
    source_type: str = "GROUNDWATER",
    population_served: int = CANONICAL_POPULATION_SERVED,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "label": label,
            "source_type": source_type,
            "population_served": population_served,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def sample_payload(
    entry_point_id: str,
    panel_contaminant_ids: List[str],
    monitoring_period: str = "2026Q2",
    collected_at: str = "2026-05-15T08:00:00.000Z",
    protocol: str = "LOW_FLOW_GRAB",
    ptfe_free_kit: bool = True,
    field_blank_included: bool = True,
    preservative_lot: str = "LOT-A1",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "entry_point_id": entry_point_id,
            "panel_contaminant_ids": list(panel_contaminant_ids),
            "monitoring_period": monitoring_period,
            "collected_at": collected_at,
            "protocol": protocol,
            "ptfe_free_kit": ptfe_free_kit,
            "field_blank_included": field_blank_included,
            "preservative_lot": preservative_lot,
        },
        overrides,
    )


def ship_sample_payload(laboratory_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"laboratory_id": laboratory_id}, overrides)


def receive_sample_payload(
    chain_of_custody_intact: bool = True,
    field_blank_result_ng_per_l: float = 0.50,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "chain_of_custody_intact": chain_of_custody_intact,
            "field_blank_result_ng_per_l": field_blank_result_ng_per_l,
        },
        overrides,
    )


def invalidate_sample_payload(
    invalidation_reason: str = "OPERATOR_ERROR", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"invalidation_reason": invalidation_reason}, overrides)


# ---------------------------------------------------------------------------
# Analytical reporting and review
# ---------------------------------------------------------------------------
def lab_result_payload(
    sample_id: str,
    contaminant_id: str,
    method: str = "METHOD_533",
    reported_ng_per_l: float = 3.00,
    detection_limit_ng_per_l: float = 1.00,
    analyzed_at: str = "2026-05-20T08:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "sample_id": sample_id,
            "contaminant_id": contaminant_id,
            "method": method,
            "reported_ng_per_l": reported_ng_per_l,
            "detection_limit_ng_per_l": detection_limit_ng_per_l,
            "analyzed_at": analyzed_at,
        },
        overrides,
    )


def accept_review_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"action": "ACCEPT"}, overrides)


def reject_review_payload(
    reject_reason_code: str = "QC_FAILURE",
    review_note: str = "Continuing calibration verification out of range",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "action": "REJECT",
            "reject_reason_code": reject_reason_code,
            "review_note": review_note,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Determinations and notifications
# ---------------------------------------------------------------------------
def determination_payload(
    entry_point_id: str,
    contaminant_id: str,
    expected_entry_point_version: int,
    period_end: str = "2026Q2",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "entry_point_id": entry_point_id,
            "contaminant_id": contaminant_id,
            "period_end": period_end,
            "expected_entry_point_version": expected_entry_point_version,
        },
        overrides,
    )


def rescind_payload(rescind_reason: str = "Laboratory data withdrawn", **overrides: Any) -> Dict[str, Any]:
    return _merge({"rescind_reason": rescind_reason}, overrides)


def notification_submit_payload(
    content_elements: Optional[List[str]] = None,
    delivery_methods: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "content_elements": list(
                content_elements if content_elements is not None else MANDATORY_CONTENT_ELEMENTS
            ),
            "delivery_methods": list(
                delivery_methods if delivery_methods is not None else [DELIVERY_MAIL, DELIVERY_POSTING]
            ),
        },
        overrides,
    )


def notification_review_payload(
    approve: bool = True, review_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"approve": approve}
    if review_note is not None:
        payload["review_note"] = review_note
    return _merge(payload, overrides)


def certify_distribution_payload(
    delivery_evidence_ref: str = "EVIDENCE-0001", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"delivery_evidence_ref": delivery_evidence_ref}, overrides)


# ---------------------------------------------------------------------------
# Monitoring frequency
# ---------------------------------------------------------------------------
def monitoring_status_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def reduction_request_payload(
    target_status: str = "ANNUAL",
    justification: str = "Four quarters of low results",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"target_status": target_status, "justification": justification}, overrides)


def reduction_decision_payload(
    approve: bool = True, decision_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"approve": approve}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Treatment evaluation, pilots and residuals
# ---------------------------------------------------------------------------
def treatment_evaluation_payload(entry_point_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"entry_point_id": entry_point_id}, overrides)


def gac_pilot_payload(
    treatment_evaluation_id: str,
    window_start_at: str = "2026-05-01T00:00:00.000Z",
    window_end_at: str = "2026-05-15T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "treatment_evaluation_id": treatment_evaluation_id,
            "technology": "GAC",
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "ebct_min": 10.00,
            "lifecycle_cost_cents": 2550000000,
            "capital_cost_estimate_cents": 680000000,
            "annual_om_estimate_cents": 31000000,
            "residuals_burden_score": 62.00,
            "footprint_score": 71.00,
            "om_complexity_score": 83.00,
        },
        overrides,
    )


def ix_pilot_payload(
    treatment_evaluation_id: str,
    window_start_at: str = "2026-05-17T00:00:00.000Z",
    window_end_at: str = "2026-05-31T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "treatment_evaluation_id": treatment_evaluation_id,
            "technology": "IX",
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "ebct_min": 3.00,
            "lifecycle_cost_cents": 1800000000,
            "capital_cost_estimate_cents": 520000000,
            "annual_om_estimate_cents": 28000000,
            "residuals_burden_score": 40.00,
            "footprint_score": 85.00,
            "om_complexity_score": 70.00,
        },
        overrides,
    )


def ro_pilot_payload(
    treatment_evaluation_id: str,
    window_start_at: str = "2026-06-05T00:00:00.000Z",
    window_end_at: str = "2026-06-20T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "treatment_evaluation_id": treatment_evaluation_id,
            "technology": "RO",
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "ebct_min": 2.00,
            "lifecycle_cost_cents": 3100000000,
            "capital_cost_estimate_cents": 910000000,
            "annual_om_estimate_cents": 46000000,
            "residuals_burden_score": 55.00,
            "footprint_score": 60.00,
            "om_complexity_score": 58.00,
        },
        overrides,
    )


def complete_pilot_payload(
    influent_ng_per_l: float = 50.00,
    effluent_ng_per_l: float = 1.85,
    bed_volumes_treated: float = 25000.00,
    spent_media_kg: float = 800.00,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "influent_ng_per_l": influent_ng_per_l,
            "effluent_ng_per_l": effluent_ng_per_l,
            "bed_volumes_treated": bed_volumes_treated,
            "spent_media_kg": spent_media_kg,
        },
        overrides,
    )


def evaluation_decision_payload(
    action: str = "SELECT",
    decision_note: str = "GAC scores highest above the removal floor",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"action": action, "decision_note": decision_note}, overrides)


def manifest_payload(
    pilot_test_id: str,
    media_type: str = "GAC_CARBON",
    mass_kg: float = 100.00,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"pilot_test_id": pilot_test_id, "media_type": media_type, "mass_kg": mass_kg},
        overrides,
    )


def classify_manifest_payload(leachate_pfas_ng_per_l: float, **overrides: Any) -> Dict[str, Any]:
    return _merge({"leachate_pfas_ng_per_l": leachate_pfas_ng_per_l}, overrides)


def ship_manifest_payload(
    disposal_method: str, carrier_ref: str = "HAULER-4417", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"disposal_method": disposal_method, "carrier_ref": carrier_ref}, overrides)


def void_manifest_payload(
    void_reason_code: str = "MASS_CORRECTION", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"void_reason_code": void_reason_code}, overrides)


# ---------------------------------------------------------------------------
# Capital finance
# ---------------------------------------------------------------------------
def project_patch_payload(**overrides: Any) -> Dict[str, Any]:
    """A cost adjustment carries only the fields being changed.

    PRD: "No other endpoint in this system accepts a version field.
    `expected_entry_point_version` and `expected_capital_project_version` appear
    on exactly the two writes named above and nowhere else, and supplying either
    of them to any other endpoint is a request-shape failure." Those two writes
    are determination creation and funding-application creation, so a project
    cost adjustment must not carry a version field.
    """
    return _merge({}, overrides)


def construction_status_payload(target_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"target_status": target_status}, overrides)


def funding_application_payload(
    expected_capital_project_version: int,
    program: str = "SRF_LOAN",
    amount_requested_cents: int = 400000000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "program": program,
            "amount_requested_cents": amount_requested_cents,
            "expected_capital_project_version": expected_capital_project_version,
        },
        overrides,
    )


def award_payload(
    awarded_cents: int, decision_note: str = "Loan awarded", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"action": "AWARD", "awarded_cents": awarded_cents, "decision_note": decision_note},
        overrides,
    )


def deny_payload(decision_note: str = "Programme oversubscribed", **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": "DENY", "decision_note": decision_note}, overrides)


def withdraw_payload(withdraw_reason: str = "Alternative financing secured", **overrides: Any) -> Dict[str, Any]:
    return _merge({"withdraw_reason": withdraw_reason}, overrides)


def cost_recovery_claim_payload(
    entry_point_id: str,
    capital_project_id: str,
    responsible_party_name: str = "Northfield Coatings",
    investigation_basis: str = "MANUFACTURING_SITE",
    allocation_pct: float = 60.00,
    investigation_cost_cents: int = 20000000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "entry_point_id": entry_point_id,
            "capital_project_id": capital_project_id,
            "responsible_party_name": responsible_party_name,
            "investigation_basis": investigation_basis,
            "allocation_pct": allocation_pct,
            "investigation_cost_cents": investigation_cost_cents,
        },
        overrides,
    )


def file_claim_payload(claimed_cents: int = 900000000, **overrides: Any) -> Dict[str, Any]:
    return _merge({"claimed_cents": claimed_cents}, overrides)


def settle_claim_payload(
    recovered_cents: int, resolution_note: str = "Consent decree entered", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "action": "SETTLE",
            "recovered_cents": recovered_cents,
            "resolution_note": resolution_note,
        },
        overrides,
    )


def dismiss_claim_payload(
    resolution_note: str = "Responsible party insolvent", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"action": "DISMISS", "resolution_note": resolution_note}, overrides)


def clock_payload(current_utc: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)
