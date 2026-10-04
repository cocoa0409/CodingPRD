"""Entity assertions, timestamp-family checks, and PRD §3.4/§3.7 reference
computations.

Timestamp rendering has TWO families (PRD §2.4) and these helpers keep them
distinct:

- ``assert_system_timestamp`` — for ``created_at``, ``updated_at`` and the
  envelope's ``api_request_timestamp``: ISO 8601 UTC with EXACTLY three
  fractional digits (e.g. "2026-09-01T00:00:00.000Z").
- ``assert_domain_timestamp`` — for event fields stamped from the logical
  clock (``issued_at``, ``reported_at``, ``verified_at``, ``abated_at``,
  ``filed_at``, ``decided_at``, ``screened_at``, ``submitted_at``,
  ``approved_at``, ``published_at``, ``planned_start_at``, ``planned_end_at``,
  ``actual_entry_at``, ``completed_at``, ``file_reviewed_at``,
  ``withdrawal_confirmed_at``, ``abatement_verified_at``, ``terminated_at``,
  ``occurred_at``, ``abatement_deadline``, ``next_revision_due_at``): they
  render AS THE CLOCK READS, so a fractional part appears only when the clock
  was set with one. Both "2026-09-01T00:00:00Z" and "...:00.500Z" pass.
- ``assert_iso_date`` — for the plain calendar-date fields
  ``activation_date``, ``period_start``, ``period_end`` (YYYY-MM-DD, no time).

Status-code convention (PRD §4): creation endpoints answer 201; all other
successes answer 200. ``validate_created(resp)`` is the 201 wrapper; for any
other endpoint call the framework's ``validate_success(resp)`` (default 200)
or pass an explicit ``expected_status``.
"""
import re
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .constants import (
    FLOOR_CITATION_CENTS,
    FLOOR_CITATION_SS_CENTS,
    FLOOR_ORDER_CENTS,
    GOOD_FAITH_RATE,
    HISTORY_BAND_EDGES,
    HISTORY_BAND_POINTS,
    LIKELIHOOD_POINTS,
    NEGLIGENCE_POINTS,
    PENALTY_TIER_BANDS,
    PENALTY_TIER_CENTS,
    PERSONS_BAND_EDGES,
    PERSONS_BAND_POINTS,
    REPEAT_MULTIPLIER,
    SEVERITY_POINTS,
    SIZE_BAND_POINTS,
    SIZE_TONNAGE_EDGES,
    SS_SURCHARGE_POINTS,
)

_SYSTEM_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ─── Response wrappers ────────────────────────────────────────────────────────

def validate_created(response) -> dict:
    """Validate a 201 creation response and return its data payload.
    Creation endpoints return 201 (PRD §4); the framework's
    ``validate_success`` defaults to 200, so creates MUST use this wrapper
    (or pass expected_status=201 explicitly)."""
    return validate_success(response, 201)


# ─── Timestamp-family assertions ─────────────────────────────────────────────

def assert_system_timestamp(value, field: str = "timestamp"):
    """created_at / updated_at / api_request_timestamp: exactly three
    fractional digits (PRD §2.4)."""
    assert isinstance(value, str) and bool(_SYSTEM_TS_RE.match(value)), (
        f"{field} must be ISO 8601 UTC with exactly three fractional digits, "
        f"got {value!r}"
    )


def assert_domain_timestamp(value, field: str = "timestamp"):
    """Logical-clock event timestamp: rendered as the clock reads (fractional
    part only when the clock was set with one)."""
    assert is_iso8601_timestamp(value), (
        f"{field} must be an ISO 8601 UTC timestamp as the clock reads, got {value!r}"
    )


def assert_nullable_domain_timestamp(data: dict, field: str):
    """When the field is present and non-null, it must be a domain timestamp.
    Null is the documented not-yet-set value (e.g. file_reviewed_at)."""
    if data.get(field) is not None:
        assert_domain_timestamp(data[field], field)


def assert_iso_date(value, field: str = "date"):
    """Plain YYYY-MM-DD calendar date with no time component (PRD §2.4)."""
    assert isinstance(value, str) and bool(_ISO_DATE_RE.match(value)), (
        f"{field} must be a plain ISO YYYY-MM-DD date, got {value!r}"
    )


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.4: every entity carries id (dashed UUID), created_at /
    updated_at (three-fraction-digit timestamps) and integer version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a dashed UUID"
    assert_system_timestamp(data.get("created_at"), f"{entity}.created_at")
    assert_system_timestamp(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_enum(data: dict, field: str, allowed, entity: str):
    assert data.get(field) in allowed, (
        f"{entity}.{field} must be one of {sorted(allowed)}, got {data.get(field)!r}"
    )


# ─── Per-entity shape assertions ─────────────────────────────────────────────

def assert_operator(data: dict):
    _assert_common_fields(data, "Operator")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("annual_tonnage_tons"), int) and data["annual_tonnage_tons"] >= 0
    assert isinstance(data.get("home_district"), str) and data["home_district"]


def assert_mine(data: dict):
    _assert_common_fields(data, "Mine")
    assert is_valid_uuid(data.get("operator_id", "")), "Mine.operator_id must be a UUID"
    assert isinstance(data.get("mine_name"), str) and data["mine_name"]
    _assert_enum(data, "mine_type", {"UNDERGROUND", "SURFACE"}, "Mine")
    assert_iso_date(data.get("activation_date"), "Mine.activation_date")
    _assert_enum(data, "status", {"ACTIVE", "IDLED"}, "Mine")
    _assert_enum(data, "production_status", {"NORMAL", "HALTED"}, "Mine")
    _assert_enum(data, "pov_status", {"NONE", "POTENTIAL_POV", "POV_FINAL"}, "Mine")


def assert_inspector(data: dict):
    _assert_common_fields(data, "Inspector")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("badge_number"), str) and data["badge_number"]
    assert isinstance(data.get("district_code"), str) and data["district_code"]
    _assert_enum(data, "certification", {"UNDERGROUND", "SURFACE", "BOTH"}, "Inspector")
    conflicted = data.get("conflicted_operator_ids")
    assert isinstance(conflicted, list), "Inspector.conflicted_operator_ids must be a list"
    for cid in conflicted:
        assert is_valid_uuid(cid), f"conflicted_operator_ids entries must be UUIDs, got {cid!r}"


def assert_inspection_cycle(data: dict):
    _assert_common_fields(data, "InspectionCycle")
    assert is_valid_uuid(data.get("mine_id", "")), "InspectionCycle.mine_id must be a UUID"
    assert isinstance(data.get("cycle_index"), int) and data["cycle_index"] >= 1
    assert_iso_date(data.get("period_start"), "InspectionCycle.period_start")
    assert_iso_date(data.get("period_end"), "InspectionCycle.period_end")
    assert isinstance(data.get("required_inspections"), int) and data["required_inspections"] >= 1
    assert isinstance(data.get("completed_inspections"), int) and data["completed_inspections"] >= 0
    _assert_enum(data, "status", {"OPEN", "COMPLIANT", "DELINQUENT", "CURED"}, "InspectionCycle")


def assert_inspection(data: dict):
    _assert_common_fields(data, "Inspection")
    assert is_valid_uuid(data.get("mine_id", "")), "Inspection.mine_id must be a UUID"
    assert is_valid_uuid(data.get("inspector_id", "")), "Inspection.inspector_id must be a UUID"
    _assert_enum(
        data, "kind",
        {"REGULAR", "SPOT", "FOLLOW_UP", "ACCIDENT_INVESTIGATION"},
        "Inspection",
    )
    if data.get("cycle_id") is not None:
        assert is_valid_uuid(data["cycle_id"]), "Inspection.cycle_id must be a UUID when set"
    if data.get("accident_id") is not None:
        assert is_valid_uuid(data["accident_id"]), "Inspection.accident_id must be a UUID when set"
    assert_domain_timestamp(data.get("planned_start_at"), "Inspection.planned_start_at")
    assert_domain_timestamp(data.get("planned_end_at"), "Inspection.planned_end_at")
    _assert_enum(
        data, "status",
        {"ASSIGNED", "FILE_REVIEWED", "IN_PROGRESS", "SUSPENDED", "COMPLETED", "CANCELLED"},
        "Inspection",
    )
    for ts_field in ("file_reviewed_at", "actual_entry_at", "completed_at"):
        assert_nullable_domain_timestamp(data, ts_field)


def assert_citation(data: dict):
    _assert_common_fields(data, "Citation")
    if data.get("inspection_id") is not None:
        assert is_valid_uuid(data["inspection_id"]), "Citation.inspection_id must be a UUID when set"
    assert is_valid_uuid(data.get("mine_id", "")), "Citation.mine_id must be a UUID"
    if data.get("issued_by_inspector_id") is not None:
        assert is_valid_uuid(data["issued_by_inspector_id"]), (
            "Citation.issued_by_inspector_id must be a UUID when set"
        )
    assert isinstance(data.get("standard_code"), str) and data["standard_code"]
    _assert_enum(data, "kind", {"CITATION", "ORDER"}, "Citation")
    _assert_enum(data, "negligence", set(NEGLIGENCE_POINTS), "Citation")
    _assert_enum(data, "gravity_likelihood", set(LIKELIHOOD_POINTS), "Citation")
    _assert_enum(data, "gravity_severity", set(SEVERITY_POINTS), "Citation")
    assert isinstance(data.get("persons_affected"), int) and data["persons_affected"] >= 1
    assert isinstance(data.get("significant_and_substantial"), bool)
    assert isinstance(data.get("repeat_violation"), bool)
    assert_domain_timestamp(data.get("issued_at"), "Citation.issued_at")
    assert isinstance(data.get("abatement_base_days"), int) and data["abatement_base_days"] >= 1
    assert_domain_timestamp(data.get("abatement_deadline"), "Citation.abatement_deadline")
    assert isinstance(data.get("abatement_extended"), bool)
    assert isinstance(data.get("system_issued"), bool)
    _assert_enum(data, "abatement_status", {"OPEN", "ABATED", "VERIFIED"}, "Citation")
    _assert_enum(
        data, "contest_status",
        {"UNCONTESTED", "CONTESTED", "AFFIRMED", "MODIFIED", "VACATED"},
        "Citation",
    )
    for ts_field in ("abated_at", "verified_at"):
        assert_nullable_domain_timestamp(data, ts_field)
    if data.get("verified_by_inspector_id") is not None:
        assert is_valid_uuid(data["verified_by_inspector_id"]), (
            "Citation.verified_by_inspector_id must be a UUID when set"
        )


def assert_penalty_assessment(data: dict):
    _assert_common_fields(data, "PenaltyAssessment")
    assert is_valid_uuid(data.get("citation_id", "")), "PenaltyAssessment.citation_id must be a UUID"
    assert isinstance(data.get("points_total"), int) and data["points_total"] >= 0
    assert isinstance(data.get("proposed_penalty_cents"), int) and data["proposed_penalty_cents"] >= 0
    assert isinstance(data.get("good_faith_applied"), bool)
    assert isinstance(data.get("statutory_floor_applied"), bool)
    _assert_enum(data, "status", {"PROPOSED", "CONTESTED", "FINAL"}, "PenaltyAssessment")
    final = data.get("final_penalty_cents")
    if data.get("status") == "FINAL":
        assert isinstance(final, int) and final >= 0, (
            "final_penalty_cents must be a non-negative integer once FINAL"
        )
    else:
        assert final is None, (
            f"final_penalty_cents must be null until FINAL, got {final!r}"
        )


def assert_imminent_danger_order(data: dict):
    _assert_common_fields(data, "ImminentDangerOrder")
    assert is_valid_uuid(data.get("mine_id", "")), "ImminentDangerOrder.mine_id must be a UUID"
    if data.get("inspection_id") is not None:
        assert is_valid_uuid(data["inspection_id"]), "ido.inspection_id must be a UUID when set"
    if data.get("issued_by_inspector_id") is not None:
        assert is_valid_uuid(data["issued_by_inspector_id"]), (
            "ido.issued_by_inspector_id must be a UUID when set"
        )
    assert isinstance(data.get("hazard_description"), str) and data["hazard_description"]
    assert_domain_timestamp(data.get("issued_at"), "ImminentDangerOrder.issued_at")
    _assert_enum(
        data, "status",
        {"ISSUED", "WITHDRAWAL_CONFIRMED", "ABATEMENT_VERIFIED", "TERMINATED"},
        "ImminentDangerOrder",
    )
    if data.get("miners_withdrawn_count") is not None:
        assert isinstance(data["miners_withdrawn_count"], int) and data["miners_withdrawn_count"] >= 0
    for ts_field in ("withdrawal_confirmed_at", "abatement_verified_at", "terminated_at"):
        assert_nullable_domain_timestamp(data, ts_field)
    if data.get("verified_by_inspector_id") is not None:
        assert is_valid_uuid(data["verified_by_inspector_id"]), (
            "ido.verified_by_inspector_id must be a UUID when set"
        )


def assert_contest(data: dict):
    _assert_common_fields(data, "Contest")
    assert is_valid_uuid(data.get("citation_id", "")), "Contest.citation_id must be a UUID"
    assert is_valid_uuid(data.get("filed_by_operator_id", "")), (
        "Contest.filed_by_operator_id must be a UUID"
    )
    assert isinstance(data.get("grounds"), str) and data["grounds"]
    assert_domain_timestamp(data.get("filed_at"), "Contest.filed_at")
    _assert_enum(data, "status", {"FILED", "DOCKETED", "DECIDED", "WITHDRAWN"}, "Contest")
    if data.get("outcome") is not None:
        _assert_enum(data, "outcome", {"AFFIRMED", "MODIFIED", "VACATED"}, "Contest")
    if data.get("modified_penalty_cents") is not None:
        assert isinstance(data["modified_penalty_cents"], int) and data["modified_penalty_cents"] >= 0
    assert_nullable_domain_timestamp(data, "decided_at")


def assert_mine_plan(data: dict):
    _assert_common_fields(data, "MinePlan")
    assert is_valid_uuid(data.get("mine_id", "")), "MinePlan.mine_id must be a UUID"
    _assert_enum(
        data, "plan_type",
        {"VENTILATION", "ROOF_CONTROL", "EMERGENCY_RESPONSE"},
        "MinePlan",
    )
    assert isinstance(data.get("revision_no"), int) and data["revision_no"] >= 1
    assert isinstance(data.get("document_ref"), str) and data["document_ref"]
    assert_domain_timestamp(data.get("submitted_at"), "MinePlan.submitted_at")
    _assert_enum(
        data, "status",
        {"SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED", "REVISION_DUE"},
        "MinePlan",
    )
    if data.get("supersedes_plan_id") is not None:
        assert is_valid_uuid(data["supersedes_plan_id"]), (
            "MinePlan.supersedes_plan_id must be a UUID when set"
        )
    for ts_field in ("approved_at", "next_revision_due_at"):
        assert_nullable_domain_timestamp(data, ts_field)
    if data.get("rejection_reason") is not None:
        assert isinstance(data["rejection_reason"], str)


def assert_accident(data: dict):
    _assert_common_fields(data, "Accident")
    assert is_valid_uuid(data.get("mine_id", "")), "Accident.mine_id must be a UUID"
    assert_domain_timestamp(data.get("occurred_at"), "Accident.occurred_at")
    assert_domain_timestamp(data.get("reported_at"), "Accident.reported_at")
    _assert_enum(data, "severity", {"FATAL", "LOST_TIME", "NO_LOST_TIME"}, "Accident")
    assert isinstance(data.get("description"), str) and data["description"]
    assert isinstance(data.get("late_report"), bool)
    _assert_enum(
        data, "status",
        {"REPORTED", "UNDER_INVESTIGATION", "REPORT_PUBLISHED"},
        "Accident",
    )
    if data.get("root_cause") is not None:
        assert isinstance(data["root_cause"], str)
    if data.get("report_text") is not None:
        assert isinstance(data["report_text"], str)
    assert_nullable_domain_timestamp(data, "published_at")


def assert_pov_screening(data: dict):
    _assert_common_fields(data, "POVScreening")
    assert is_valid_uuid(data.get("mine_id", "")), "POVScreening.mine_id must be a UUID"
    _assert_enum(data, "variant", {"SCREENING", "FINAL_DETERMINATION"}, "POVScreening")
    assert_domain_timestamp(data.get("screened_at"), "POVScreening.screened_at")
    assert_domain_timestamp(data.get("window_start"), "POVScreening.window_start")
    assert isinstance(data.get("ss_citation_count"), int) and data["ss_citation_count"] >= 0
    assert isinstance(data.get("weighted_score"), int) and data["weighted_score"] >= 0
    _assert_enum(
        data, "result",
        {"POTENTIAL_POV", "BELOW_THRESHOLD", "CONFIRMED_POV"},
        "POVScreening",
    )


# ─── PRD §3.4 reference computations (penalty points and dollar pipeline) ─────
# These mirror the pinned PRD formulas exactly so boundary families can be
# cross-checked. Rounding: half-up to whole cents after the multiplier step
# and again after the discount step; intermediate values are exact decimals.

def persons_points(persons_affected: int) -> int:
    """1 -> 0; 2..5 -> 5; 6..20 -> 10; >= 21 -> 20."""
    for edge, pts in zip(reversed(PERSONS_BAND_EDGES), reversed(PERSONS_BAND_POINTS[1:])):
        if persons_affected >= edge:
            return pts
    return PERSONS_BAND_POINTS[0]


def history_points(prior_citation_count: int) -> int:
    """0..5 -> 0; 6..15 -> 5; 16..30 -> 10; >= 31 -> 20 (trailing 730-day
    window, opening instant excluded, non-VACATED citations only)."""
    for edge, pts in zip(reversed(HISTORY_BAND_EDGES), reversed(HISTORY_BAND_POINTS[1:])):
        if prior_citation_count >= edge:
            return pts
    return HISTORY_BAND_POINTS[0]


def size_points(annual_tonnage_tons: int) -> int:
    """< 50000 -> 0; 50000..499999 -> 5; 500000..4999999 -> 10; >= 5000000 -> 15."""
    for edge, pts in zip(reversed(SIZE_TONNAGE_EDGES), reversed(SIZE_BAND_POINTS[1:])):
        if annual_tonnage_tons >= edge:
            return pts
    return SIZE_BAND_POINTS[0]


def compute_points_total(negligence: str, gravity_likelihood: str,
                         gravity_severity: str, persons_affected: int,
                         significant_and_substantial: bool,
                         prior_history_count: int,
                         operator_annual_tonnage_tons: int) -> int:
    """points_total = negligence + likelihood + severity + persons + S&S
    surcharge + history + size (seven additive factor tables, PRD §3.4).
    ``prior_history_count`` is the number of the mine's OTHER non-VACATED
    citations with issued_at in the trailing 730-day window (window-open
    excluded, own issued_at included; the new citation itself excluded)."""
    return (
        NEGLIGENCE_POINTS[negligence]
        + LIKELIHOOD_POINTS[gravity_likelihood]
        + SEVERITY_POINTS[gravity_severity]
        + persons_points(persons_affected)
        + (SS_SURCHARGE_POINTS if significant_and_substantial else 0)
        + history_points(prior_history_count)
        + size_points(operator_annual_tonnage_tons)
    )


def compute_gross_cents(points_total: int) -> int:
    """Marginal tier conversion: first 20 points at 11,250c each, next 40
    (21-60) at 22,500c, next 40 (61-100) at 37,500c, beyond 100 at 52,500c."""
    t1, t2, t3, t4 = PENALTY_TIER_CENTS
    b1, b2, b3 = PENALTY_TIER_BANDS
    gross = min(points_total, b1) * t1
    gross += min(max(points_total - b1, 0), b2) * t2
    gross += min(max(points_total - b1 - b2, 0), b3) * t3
    gross += max(points_total - b1 - b2 - b3, 0) * t4
    return gross


def _round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def statutory_floor_cents(kind: str, significant_and_substantial: bool) -> int:
    """150,000c for an ORDER; 120,000c for an S&S CITATION; 60,000c otherwise.
    The floor applies LAST and can only raise an amount."""
    if kind == "ORDER":
        return FLOOR_ORDER_CENTS
    return FLOOR_CITATION_SS_CENTS if significant_and_substantial else FLOOR_CITATION_CENTS


def compute_proposed_penalty_cents(points_total: int, kind: str,
                                   significant_and_substantial: bool,
                                   repeat_violation: bool) -> int:
    """Proposed variant (at issuance): tiers -> repeat multiplier (round
    half-up) -> statutory floor LAST. No good-faith discount."""
    gross = Decimal(compute_gross_cents(points_total))
    multiplied = (
        _round_half_up_cents(gross * REPEAT_MULTIPLIER) if repeat_violation else int(gross)
    )
    return max(multiplied, statutory_floor_cents(kind, significant_and_substantial))


def compute_final_penalty_cents(points_total: int, kind: str,
                                significant_and_substantial: bool,
                                repeat_violation: bool,
                                verified_on_time: bool) -> int:
    """Final variant (finalize after window lapse, or decide AFFIRMED): adds
    the 10% good-faith discount — the discount itself rounded half-up — only
    when the citation is VERIFIED with verified_at on or before
    abatement_deadline. Floor still applies last. (MODIFIED instead stores
    max(modified_penalty_cents, floor) with no discount; VACATED stores 0.)"""
    gross = Decimal(compute_gross_cents(points_total))
    multiplied = (
        _round_half_up_cents(gross * REPEAT_MULTIPLIER) if repeat_violation else int(gross)
    )
    net = multiplied
    if verified_on_time:
        discount = _round_half_up_cents(Decimal(multiplied) * GOOD_FAITH_RATE)
        net = multiplied - discount
    return max(net, statutory_floor_cents(kind, significant_and_substantial))


def compute_pov_weighted_score(ss_citation_count: int,
                               high_negligence_count: int,
                               ido_count: int) -> int:
    """POV weighted score (PRD §3.7): 2 per S&S citation + 1 per
    HIGH/RECKLESS_DISREGARD citation + 5 per imminent-danger order in the
    window. Threshold: weighted_score >= 8 crosses to POTENTIAL_POV /
    CONFIRMED_POV."""
    return 2 * ss_citation_count + 1 * high_negligence_count + 5 * ido_count
