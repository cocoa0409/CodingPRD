"""Request payload builders. Every builder accepts overrides as keyword arguments."""

from typing import Any, Dict, Optional

from test_helpers.constants import (
    ACTION_TYPE_COACHING,
    APPEAL_CODE_NEW_EVIDENCE,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIMANT_TYPE_BODILY_INJURY,
    CLOCK_EPOCH,
    COUNSEL_TYPE_PANEL,
    CRITERION_ORDER,
    EMPLOYMENT_DECISION_CONTINUE,
    EVIDENCE_TELEMATICS,
    LAYER_KIND_SIR,
    RESERVE_BASIS_PROVISIONAL_REFRESH,
    ROUTE_CLASS_LOCAL,
    SEVERITY_MINOR,
    SUBROGATION_RESOLUTION_RECOVERED,
    TOW_REASON_NONE,
)

Json = Dict[str, Any]


def _payload(base: Json, overrides: Json) -> Json:
    """Apply overrides, dropping any key whose value is the drop sentinel.

    The sentinel is honoured wherever it lands. A caller may aim it at a field
    the builder declares as a named parameter (``cdl_number=DROP``), in which
    case it arrives inside ``base`` rather than in ``overrides``, so both maps
    are scrubbed before the payload is handed to the JSON encoder.
    """
    merged = dict(base)
    for key, value in overrides.items():
        merged[key] = value
    return {key: value for key, value in merged.items() if value is not DROP}


class _Drop:
    """Sentinel telling a builder to omit a field entirely."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "DROP"


DROP = _Drop()


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def clock_payload(current_utc: str) -> Json:
    return {"current_utc": current_utc}


# ---------------------------------------------------------------------------
# Terminal and driver
# ---------------------------------------------------------------------------


def terminal_payload(
    terminal_code: str = "GRE02",
    name: str = "Greenfield Terminal",
    region_code: str = "MW",
    annual_miles_millions: Any = 2.0,
    **overrides: Any,
) -> Json:
    return _payload(
        {
            "name": name,
            "terminal_code": terminal_code,
            "region_code": region_code,
            "annual_miles_millions": annual_miles_millions,
        },
        overrides,
    )


def driver_payload(
    terminal_id: str,
    employee_code: str = "D-5701",
    full_name: str = "Dana Reyes",
    cdl_number: str = "CDL-4471998",
    hire_date: str = "2015-04-06",
    **overrides: Any,
) -> Json:
    return _payload(
        {
            "terminal_id": terminal_id,
            "employee_code": employee_code,
            "full_name": full_name,
            "cdl_number": cdl_number,
            "hire_date": hire_date,
        },
        overrides,
    )


def employment_decision_payload(
    decision: str = EMPLOYMENT_DECISION_CONTINUE,
    decision_note: Optional[str] = "Reviewed with the terminal manager.",
    **overrides: Any,
) -> Json:
    base: Json = {"decision": decision}
    if decision_note is not None:
        base["decision_note"] = decision_note
    return _payload(base, overrides)


# ---------------------------------------------------------------------------
# Crash intake
# ---------------------------------------------------------------------------


def crash_payload(
    driver_id: str,
    terminal_id: str,
    occurred_at: str = "2026-07-31T12:00:00Z",
    notified_at: str = "2026-07-31T13:00:00Z",
    location_text: str = "Interstate 70 milepost 42",
    severity: str = SEVERITY_MINOR,
    route_class: str = ROUTE_CLASS_LOCAL,
    tow_away: bool = False,
    tow_reason: str = TOW_REASON_NONE,
    injury_transported_count: int = 0,
    fatality_count: int = 0,
    hazmat_release: bool = False,
    mechanical_factor: bool = False,
    third_party_at_fault: bool = False,
    **overrides: Any,
) -> Json:
    return _payload(
        {
            "driver_id": driver_id,
            "terminal_id": terminal_id,
            "occurred_at": occurred_at,
            "notified_at": notified_at,
            "location_text": location_text,
            "severity": severity,
            "route_class": route_class,
            "tow_away": tow_away,
            "tow_reason": tow_reason,
            "injury_transported_count": injury_transported_count,
            "fatality_count": fatality_count,
            "hazmat_release": hazmat_release,
            "mechanical_factor": mechanical_factor,
            "third_party_at_fault": third_party_at_fault,
        },
        overrides,
    )


def driver_statement_payload(
    narrative: str = "Traffic slowed abruptly and I braked but could not stop in time.",
    attested: bool = True,
    conditions_note: Optional[str] = "Wet pavement, daylight.",
    **overrides: Any,
) -> Json:
    base: Json = {"narrative": narrative, "attested": attested}
    if conditions_note is not None:
        base["conditions_note"] = conditions_note
    return _payload(base, overrides)


def evidence_payload(
    kind: str = EVIDENCE_TELEMATICS,
    window_start_at: str = "2026-07-31T11:00:00Z",
    window_end_at: str = "2026-07-31T13:00:00Z",
    retention_deadline_at: str = "2026-09-01T00:00:00Z",
    source_device_id: str = "DEV-TEL-001",
    evidence_hash: Optional[str] = None,
    **overrides: Any,
) -> Json:
    base: Json = {
        "kind": kind,
        "source_device_id": source_device_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "retention_deadline_at": retention_deadline_at,
    }
    if evidence_hash is not None:
        base["evidence_hash"] = evidence_hash
    return _payload(base, overrides)


def preserve_payload(
    preserved_copy_uri: str = "s3://evidence-vault/telematics-001.json",
    evidence_hash: str = "9f1c8a3d5e7b2c4f6a8d0e2b4c6f8a1d",
    **overrides: Any,
) -> Json:
    return _payload(
        {"preserved_copy_uri": preserved_copy_uri, "evidence_hash": evidence_hash},
        overrides,
    )


def purge_payload(
    purge_reason: str = "Retention schedule reached before a hold was placed.",
    **overrides: Any,
) -> Json:
    return _payload({"purge_reason": purge_reason}, overrides)


def regulatory_report_payload(
    filing_reference: str = "DOT-2026-000411", **overrides: Any
) -> Json:
    return _payload({"filing_reference": filing_reference}, overrides)


# ---------------------------------------------------------------------------
# Review case and ballots
# ---------------------------------------------------------------------------


def review_case_payload(
    crash_id: str,
    committee_name: str = "Midwest Safety Review Committee",
    statement_waiver_reason: Optional[str] = None,
    **overrides: Any,
) -> Json:
    base: Json = {"crash_id": crash_id, "committee_name": committee_name}
    if statement_waiver_reason is not None:
        base["statement_waiver_reason"] = statement_waiver_reason
    return _payload(base, overrides)


def criterion_scores(
    speed_and_spacing: int = 3,
    hazard_recognition: int = 3,
    regulatory_compliance: int = 3,
    vehicle_condition_precheck: int = 3,
    evasive_action: int = 3,
    **overrides: Any,
) -> Json:
    return _payload(
        {
            "speed_and_spacing": speed_and_spacing,
            "hazard_recognition": hazard_recognition,
            "regulatory_compliance": regulatory_compliance,
            "vehicle_condition_precheck": vehicle_condition_precheck,
            "evasive_action": evasive_action,
        },
        overrides,
    )


def uniform_criterion_scores(score: int) -> Json:
    """The same score on every declared criterion."""
    return {criterion: score for criterion in CRITERION_ORDER}


def vote_payload(
    expected_review_case_version: int,
    vote: str = BALLOT_DISPOSITION_PREVENTABLE,
    scores: Optional[Json] = None,
    comment: Optional[str] = None,
    **overrides: Any,
) -> Json:
    base: Json = {
        "expected_review_case_version": expected_review_case_version,
        "vote": vote,
    }
    if scores is not None:
        base["criterion_scores"] = scores
    if comment is not None:
        base["comment"] = comment
    return _payload(base, overrides)


def appeal_payload(
    appeal_grounds: str = "New telematics evidence contradicts the committee finding.",
    appeal_grounds_code: str = APPEAL_CODE_NEW_EVIDENCE,
    appeal_evidence_item_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    base: Json = {
        "appeal_grounds": appeal_grounds,
        "appeal_grounds_code": appeal_grounds_code,
    }
    if appeal_evidence_item_id is not None:
        base["appeal_evidence_item_id"] = appeal_evidence_item_id
    return _payload(base, overrides)


# ---------------------------------------------------------------------------
# Policy tower and claims
# ---------------------------------------------------------------------------


def policy_layer_payload(
    program_year: int = 2026,
    layer_index: int = 1,
    layer_type: str = LAYER_KIND_SIR,
    attachment_point_cents: int = 0,
    limit_cents: int = 10_000_000,
    insurer_name: str = "Self Insured Retention",
    **overrides: Any,
) -> Json:
    return _payload(
        {
            "program_year": program_year,
            "layer_index": layer_index,
            "layer_type": layer_type,
            "attachment_point_cents": attachment_point_cents,
            "limit_cents": limit_cents,
            "insurer_name": insurer_name,
        },
        overrides,
    )


def claim_payload(
    crash_id: str,
    claimant_notice_date: str = "2026-07-31",
    adjuster_note: Optional[str] = None,
    **overrides: Any,
) -> Json:
    base: Json = {"crash_id": crash_id, "claimant_notice_date": claimant_notice_date}
    if adjuster_note is not None:
        base["adjuster_note"] = adjuster_note
    return _payload(base, overrides)


def reserve_revision_payload(
    expected_claim_version: int,
    basis: str = RESERVE_BASIS_PROVISIONAL_REFRESH,
    revision_note: Optional[str] = None,
    **overrides: Any,
) -> Json:
    base: Json = {"expected_claim_version": expected_claim_version, "basis": basis}
    if revision_note is not None:
        base["revision_note"] = revision_note
    return _payload(base, overrides)


def counsel_assignment_payload(
    counsel_firm_name: str = "Harrow & Vance LLP",
    counsel_type: str = COUNSEL_TYPE_PANEL,
    **overrides: Any,
) -> Json:
    return _payload(
        {"counsel_firm_name": counsel_firm_name, "counsel_type": counsel_type}, overrides
    )


def demand_payload(
    demand_amount_cents: int = 1_000_000,
    claimant_name: str = "Priya Raman",
    claimant_type: str = CLAIMANT_TYPE_BODILY_INJURY,
    represented_by_counsel: bool = False,
    demand_received_at: str = CLOCK_EPOCH,
    **overrides: Any,
) -> Json:
    return _payload(
        {
            "claimant_name": claimant_name,
            "claimant_type": claimant_type,
            "demand_amount_cents": demand_amount_cents,
            "represented_by_counsel": represented_by_counsel,
            "demand_received_at": demand_received_at,
        },
        overrides,
    )


def subrogation_demand_payload(
    at_fault_percentage: int = 40,
    third_party_name: str = "Northline Haulage Inc.",
    basis_note: str = "Third-party vehicle failed to yield at the intersection.",
    **overrides: Any,
) -> Json:
    return _payload(
        {
            "third_party_name": third_party_name,
            "at_fault_percentage": at_fault_percentage,
            "basis_note": basis_note,
        },
        overrides,
    )


def offer_payload(carrier_offer_cents: int, **overrides: Any) -> Json:
    return _payload({"carrier_offer_cents": carrier_offer_cents}, overrides)


def counter_payload(claimant_counter_cents: int, **overrides: Any) -> Json:
    return _payload({"claimant_counter_cents": claimant_counter_cents}, overrides)


def settle_payload(settlement_reference: str = "STL-2026-0001", **overrides: Any) -> Json:
    return _payload({"settlement_reference": settlement_reference}, overrides)


def rescind_payload(
    rescission_reason: str = "Release was never executed by the claimant.",
    **overrides: Any,
) -> Json:
    return _payload({"rescission_reason": rescission_reason}, overrides)


def resolve_subrogation_payload(
    resolution: str = SUBROGATION_RESOLUTION_RECOVERED,
    recovered_amount_cents: Optional[int] = None,
    resolution_note: str = "Recovery negotiated with the third-party carrier.",
    **overrides: Any,
) -> Json:
    base: Json = {"resolution": resolution, "resolution_note": resolution_note}
    if recovered_amount_cents is not None:
        base["recovered_amount_cents"] = recovered_amount_cents
    return _payload(base, overrides)


# ---------------------------------------------------------------------------
# Discipline
# ---------------------------------------------------------------------------


def disciplinary_action_payload(
    driver_id: str,
    crash_id: str,
    action_type: str = ACTION_TYPE_COACHING,
    action_note: str = "Coaching session scheduled with the terminal trainer.",
    suspension_start_at: Optional[str] = None,
    suspension_end_at: Optional[str] = None,
    retraining_course_code: Optional[str] = None,
    override_reason: Optional[str] = None,
    **overrides: Any,
) -> Json:
    base: Json = {
        "driver_id": driver_id,
        "crash_id": crash_id,
        "action_type": action_type,
        "action_note": action_note,
    }
    if suspension_start_at is not None:
        base["suspension_start_at"] = suspension_start_at
    if suspension_end_at is not None:
        base["suspension_end_at"] = suspension_end_at
    if retraining_course_code is not None:
        base["retraining_course_code"] = retraining_course_code
    if override_reason is not None:
        base["override_reason"] = override_reason
    return _payload(base, overrides)


def complete_retraining_payload(
    completion_note: Optional[str] = "Course completed with a passing score.",
    **overrides: Any,
) -> Json:
    base: Json = {}
    if completion_note is not None:
        base["completion_note"] = completion_note
    return _payload(base, overrides)
