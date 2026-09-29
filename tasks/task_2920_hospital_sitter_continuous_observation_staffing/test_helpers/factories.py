"""
Request-payload builders.

Type fidelity rules enforced here once, so no test has to remember them:

* money is always sent as a JSON **number** — PRD 2.7 says the cents fields are
  "whole-cent integers, never decimals and never strings";
* every instant is sent as a full ISO 8601 UTC instant, never a date-only string,
  canonicalised by ``api_client.canonical_instant`` on the way out;
* optional fields are **omitted** from the body rather than sent as ``None``,
  because several PRD rules distinguish an absent field from a supplied empty one
  (``float_authorization_code``, ``review_findings``, ``video_monitoring_enabled``).
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from .api_client import canonical_instant
from .constants import (
    ACUITY_WEIGHT,
    AGE_ADJUSTMENT_POINTS,
    AGE_ADJUSTMENT_THRESHOLD,
    COMPETENCY_ADVANCED,
    MODALITY_ONE_TO_ONE_SITTER,
    POOL_INTERNAL_FLOAT,
    POOL_MULTIPLIER,
    RISK_FALL,
    RISK_SCORE_CAP,
    RISK_WEIGHT,
    SPAN_LIMIT_FLOOR,
    SPAN_PENALTY_HEAVY_SLOTS,
    SPAN_PENALTY_HEAVY_WEIGHT,
    SPAN_PENALTY_MEDIUM_SLOTS,
    SPAN_PENALTY_MEDIUM_WEIGHT,
    SURCHARGE_TIERS,
)

_OMIT = object()


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not _OMIT}


# ─── Units (PRD 3.1) ──────────────────────────────────

def unit_payload(
    unit_code: str = "UNIT-1",
    name: str = "Medical Observation Unit",
    observation_cost_budget_cents: int = 100000,
    video_monitoring_enabled: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune(
        {
            "unit_code": unit_code,
            "name": name,
            "observation_cost_budget_cents": observation_cost_budget_cents,
            "video_monitoring_enabled": video_monitoring_enabled,
        }
    )


def cost_close_payload(
    close_through_utc: str,
    budget_increase_cents: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune(
        {
            "close_through_utc": canonical_instant(close_through_utc),
            "budget_increase_cents": budget_increase_cents,
        }
    )


# ─── Patients (PRD 3.1) ───────────────────────────────

def patient_payload(
    unit_id: str,
    mrn: str = "MRN-1000",
    full_name: str = "Observation Patient",
    age_years: int = 60,
) -> Dict[str, Any]:
    return {
        "unit_id": unit_id,
        "mrn": mrn,
        "full_name": full_name,
        "age_years": age_years,
    }


# ─── Staff (PRD 3.1) ──────────────────────────────────

def staff_payload(
    home_unit_id: str,
    full_name: str = "Observation Sitter",
    source_pool: str = POOL_INTERNAL_FLOAT,
    hourly_rate_cents: int = 2000,
    competency_level: str = COMPETENCY_ADVANCED,
    deescalation_cert_expires_on: str = "2027-01-01T00:00:00Z",
) -> Dict[str, Any]:
    return {
        "home_unit_id": home_unit_id,
        "full_name": full_name,
        "source_pool": source_pool,
        "hourly_rate_cents": hourly_rate_cents,
        "competency_level": competency_level,
        "deescalation_cert_expires_on": canonical_instant(deescalation_cert_expires_on),
    }


def certification_payload(
    competency_level: str,
    deescalation_cert_expires_on: str,
) -> Dict[str, Any]:
    return {
        "competency_level": competency_level,
        "deescalation_cert_expires_on": canonical_instant(deescalation_cert_expires_on),
    }


# ─── Observation orders (PRD 3.2 / 3.3 / 3.9) ─────────

def order_payload(
    patient_id: str,
    ordering_provider_user_id: str,
    risk_categories: Optional[List[str]] = None,
    required_modality: str = MODALITY_ONE_TO_ONE_SITTER,
    clinical_rationale: str = "Continuous observation indicated by bedside assessment.",
) -> Dict[str, Any]:
    return {
        "patient_id": patient_id,
        "ordering_provider_user_id": ordering_provider_user_id,
        "risk_categories": [RISK_FALL] if risk_categories is None else risk_categories,
        "required_modality": required_modality,
        "clinical_rationale": clinical_rationale,
    }


def reassessment_payload(risk_categories_after: List[str]) -> Dict[str, Any]:
    return {"risk_categories_after": risk_categories_after}


def discontinuation_review_payload(recommendation: str) -> Dict[str, Any]:
    return {"recommendation": recommendation}


def discontinuation_decision_payload(
    decision: str,
    rationale: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune({"decision": decision, "rationale": rationale})


# ─── Sitter assignments (PRD 3.4 / 3.5) ───────────────

def assignment_payload(
    order_id: str,
    staff_id: str,
    shift_start_at: str,
    shift_end_at: str,
    expected_order_version: int,
    float_authorization_code: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune(
        {
            "order_id": order_id,
            "staff_id": staff_id,
            "shift_start_at": canonical_instant(shift_start_at),
            "shift_end_at": canonical_instant(shift_end_at),
            "expected_order_version": expected_order_version,
            "float_authorization_code": float_authorization_code,
        }
    )


def completion_payload(completion_reason: str) -> Dict[str, Any]:
    return {"completion_reason": completion_reason}


# ─── Handoffs (PRD 3.6) ───────────────────────────────

def handoff_payload(
    outgoing_assignment_id: str,
    incoming_assignment_id: str,
    behavior_summary: str = "Patient calm, redirected twice, no attempts to rise.",
    interventions_used: Optional[List[str]] = None,
) -> Dict[str, Any]:
    from .constants import INTERVENTION_VERBAL_REDIRECTION

    return {
        "outgoing_assignment_id": outgoing_assignment_id,
        "incoming_assignment_id": incoming_assignment_id,
        "behavior_summary": behavior_summary,
        "interventions_used": (
            [INTERVENTION_VERBAL_REDIRECTION]
            if interventions_used is None
            else interventions_used
        ),
    }


# ─── Consoles and feeds (PRD 3.7) ─────────────────────

def station_payload(
    observer_staff_id: str,
    station_label: str = "CONSOLE-1",
    declared_max_span: int = 3,
) -> Dict[str, Any]:
    return {
        "observer_staff_id": observer_staff_id,
        "station_label": station_label,
        "declared_max_span": declared_max_span,
    }


def feed_payload(
    station_id: str,
    order_id: str,
    monitor_start_at: str,
    monitor_end_at: str,
) -> Dict[str, Any]:
    return {
        "station_id": station_id,
        "order_id": order_id,
        "monitor_start_at": canonical_instant(monitor_start_at),
        "monitor_end_at": canonical_instant(monitor_end_at),
    }


# ─── Safety events (PRD 3.8) ──────────────────────────

def safety_event_payload(
    order_id: str,
    event_kind: str,
    narrative: str = "Observed and documented at the bedside.",
    assignment_id: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune(
        {
            "order_id": order_id,
            "event_kind": event_kind,
            "narrative": narrative,
            "assignment_id": assignment_id,
        }
    )


def escalate_response_payload(response_actions: List[str]) -> Dict[str, Any]:
    return {"response_actions": response_actions}


def close_event_payload(
    resolution: str,
    review_findings: Any = _OMIT,
) -> Dict[str, Any]:
    return _prune({"resolution": resolution, "review_findings": review_findings})


# ─── Logical clock (PRD 2.4 / 3.3) ────────────────────

def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": canonical_instant(current_utc)}


# ─── Derived-figure calculators ───────────────────────
# These restate the PRD's own arithmetic so a test can express an expectation the
# way the contract states it instead of as an opaque literal.

def round_half_up(value: float, places: int = 0) -> float:
    """
    PRD 2.7: "rounded half up ... a value whose fractional part is exactly one
    half rounds away from zero to the next whole cent".
    """
    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(repr(float(value))).quantize(quantum, rounding=ROUND_HALF_UP)
    return float(rounded) if places else int(rounded)


def baseline_risk_score(risk_categories: List[str], age_years: int) -> float:
    """The admission-baseline score of PRD 3.2, whose event component is fixed at 0.0."""
    total = sum(RISK_WEIGHT[category] for category in risk_categories)
    if age_years >= AGE_ADJUSTMENT_THRESHOLD:
        total += AGE_ADJUSTMENT_POINTS
    return round_half_up(min(total, RISK_SCORE_CAP), 1)


def rolling_risk_score(
    risk_categories: List[str],
    age_years: int,
    windowed_attempts: int = 0,
    all_time_incidents: int = 0,
) -> float:
    """
    The rolling event-weighted score of PRD 3.3: 1.0 per windowed
    ELOPEMENT_ATTEMPT/AGGRESSION plus 2.0 per all-time
    FALL_WITH_INJURY/SELF_HARM_ATTEMPT, capped at 10.0 before rounding.
    """
    total = sum(RISK_WEIGHT[category] for category in risk_categories)
    if age_years >= AGE_ADJUSTMENT_THRESHOLD:
        total += AGE_ADJUSTMENT_POINTS
    total += 1.0 * windowed_attempts + 2.0 * all_time_incidents
    return round_half_up(min(total, RISK_SCORE_CAP), 1)


def interval_hours_for_score(score: float) -> int:
    """The four inclusive reassessment tiers of PRD 3.2."""
    if score >= 8.0:
        return 4
    if score >= 6.0:
        return 8
    if score >= 3.0:
        return 12
    return 24


def provisional_cents(
    hourly_rate_cents: int,
    scheduled_minutes: int,
    source_pool: str,
) -> int:
    """
    PRD 3.4: the rate times ``scheduled_minutes`` divided by 60 times the pool
    multiplier, "rounded half up to whole cents **once**, over the whole window".
    """
    raw = hourly_rate_cents * (scheduled_minutes / 60) * POOL_MULTIPLIER[source_pool]
    return round_half_up(raw)


def segment_cents(
    hourly_rate_cents: int,
    segment_minutes: int,
    source_pool: str,
    night: bool = False,
) -> int:
    """
    PRD 3.5: one segment's amount, "rounded half up to whole cents" on its own —
    rounding per segment, never once over the sum.
    """
    raw = (
        hourly_rate_cents
        * (segment_minutes / 60)
        * POOL_MULTIPLIER[source_pool]
        * (1.15 if night else 1.00)
    )
    return round_half_up(raw)


def is_night_segment(start_instant: str) -> bool:
    """
    PRD 3.5: "the segment is a night segment when that hour is 23 or later, or
    earlier than 7" — decided purely by the UTC hour the segment started.
    """
    hour = int(canonical_instant(start_instant)[11:13])
    return hour >= 23 or hour < 7


def acuity_weight(risk_categories: List[str]) -> float:
    """The feed weight frozen at admission (PRD 3.7)."""
    return round_half_up(
        sum(ACUITY_WEIGHT[category] for category in risk_categories), 1
    )


def effective_span_limit(declared_max_span: int, active_acuity_weight: float) -> int:
    """The acuity penalty and the floor of 1 declared in PRD 3.7."""
    if active_acuity_weight >= SPAN_PENALTY_HEAVY_WEIGHT:
        penalty = SPAN_PENALTY_HEAVY_SLOTS
    elif active_acuity_weight >= SPAN_PENALTY_MEDIUM_WEIGHT:
        penalty = SPAN_PENALTY_MEDIUM_SLOTS
    else:
        penalty = 0
    return max(SPAN_LIMIT_FLOOR, declared_max_span - penalty)


def surcharge_pct_for_subtotal(subtotal_cents: int) -> float:
    """PRD 3.9 step two: a tier keyed on ``subtotal_cents`` alone."""
    for threshold, pct in SURCHARGE_TIERS:
        if subtotal_cents >= threshold:
            return pct
    return 0.00


def surcharge_cents(subtotal_cents: int) -> int:
    """PRD 3.9 step three: the subtotal times the tier percentage, rounded half up."""
    return round_half_up(subtotal_cents * surcharge_pct_for_subtotal(subtotal_cents))
