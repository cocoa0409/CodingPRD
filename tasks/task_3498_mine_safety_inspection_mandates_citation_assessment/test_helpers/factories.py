"""Payload factories — one per writable endpoint, input fields only.

Factories never seed system-managed fields (``id``, ``created_at``,
``updated_at``, ``version``, status fields, computed fields) into payloads:
PRD §2.5 tier 3 rejects undeclared fields with ERR_INVALID_REQUEST.

Default instants are >= the logical clock's startup reading
(2026-09-01T00:00:00Z, PRD §2.4) so every default payload is reachable
without any clock call.

Small date/datetime helpers are provided for window arithmetic: cycle
geometry (PRD §2.6) computes period_end = period_start + 89 days
(UNDERGROUND) or + 179 days (SURFACE), and the contest/finalize windows
and abatement deadlines need day/second offsets from logical-clock
readings.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from .constants import (
    ABATEMENT_BASE_DAYS,
    SURFACE_CYCLE_DAYS,
    TEST_DEFAULTS,
    UNDERGROUND_CYCLE_DAYS,
)


# ─── Date / datetime helpers (ISO 8601, UTC) ──────────────────────────────────

def parse_clock(ts: str) -> datetime:
    """Parse a logical-clock reading ('2026-09-01T00:00:00Z', optionally with
    fractional seconds) into an aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def format_clock(dt: datetime) -> str:
    """Render an aware datetime as the logical clock reads: second precision,
    'Z' suffix, no fractional part (domain timestamps render as the clock
    reads, PRD §2.4)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_seconds(ts: str, seconds: int) -> str:
    """Return the clock reading `seconds` after the given clock reading."""
    return format_clock(parse_clock(ts) + timedelta(seconds=seconds))


def add_days_to_timestamp(ts: str, days: int) -> str:
    """Return the clock reading `days` after the given clock reading."""
    return format_clock(parse_clock(ts) + timedelta(days=days))


def add_days_to_date(iso_date: str, days: int) -> str:
    """Return the ISO calendar date `days` after the given YYYY-MM-DD date."""
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def cycle_period_end(mine_type: str, period_start: str) -> str:
    """Correct inclusive period_end for a cycle: period_start + 89 days for
    UNDERGROUND, + 179 days for SURFACE (PRD §2.6)."""
    span = UNDERGROUND_CYCLE_DAYS if mine_type == "UNDERGROUND" else SURFACE_CYCLE_DAYS
    return add_days_to_date(period_start, span - 1)


def next_period_start(prior_period_end: str) -> str:
    """Strictly contiguous next cycle start: prior period_end + 1 day."""
    return add_days_to_date(prior_period_end, 1)


def abatement_extension_days(gravity_severity: str) -> int:
    """ceil(base_days / 2): 30 -> 15, 15 -> 8, 5 -> 3, 1 -> 1 (PRD §3.4)."""
    base = ABATEMENT_BASE_DAYS[gravity_severity]
    return -(-base // 2)


def unique_badge_number(prefix: str = "INSP") -> str:
    """Badge numbers must be unique across all inspectors (PRD §3.1); a random
    suffix keeps multi-inspector fixtures collision-free."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def set_clock_payload(current_utc: str, **overrides) -> dict:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


# ─── Registry payloads (PRD §3.1) ─────────────────────────────────────────────

def create_operator_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["OPERATOR_LEGAL_NAME"],
        "annual_tonnage_tons": TEST_DEFAULTS["OPERATOR_TONNAGE"],
        "home_district": TEST_DEFAULTS["OPERATOR_HOME_DISTRICT"],
    }
    payload.update(overrides)
    return payload


def create_mine_payload(operator_id: str, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "mine_name": TEST_DEFAULTS["MINE_NAME"],
        "mine_type": TEST_DEFAULTS["MINE_TYPE"],
        "activation_date": TEST_DEFAULTS["ACTIVATION_DATE"],
    }
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["INSPECTOR_FULL_NAME"],
        "badge_number": unique_badge_number(),
        "district_code": TEST_DEFAULTS["INSPECTOR_DISTRICT_CODE"],
        "certification": TEST_DEFAULTS["INSPECTOR_CERTIFICATION"],
        "conflicted_operator_ids": [],
    }
    payload.update(overrides)
    return payload


# ─── Inspection cycles (PRD §3.2) ─────────────────────────────────────────────

def create_inspection_cycle_payload(period_start: str, mine_type: str = "UNDERGROUND",
                                    **overrides) -> dict:
    """Cycle payload with geometrically correct period_end unless overridden.
    Pass an explicit period_end override to probe ERR_CYCLE_PERIOD_INVALID."""
    payload = {
        "period_start": period_start,
        "period_end": cycle_period_end(mine_type, period_start),
    }
    payload.update(overrides)
    return payload


# ─── Inspections (PRD §3.3) ───────────────────────────────────────────────────

def create_inspection_payload(mine_id: str, inspector_id: str, kind: str = "SPOT",
                              **overrides) -> dict:
    """Inspection assignment payload. ``cycle_id`` / ``accident_id`` are
    included only when supplied (REGULAR requires cycle_id;
    ACCIDENT_INVESTIGATION requires accident_id; otherwise the fields must
    be omitted or null). Default planned window is strictly positive."""
    payload = {
        "mine_id": mine_id,
        "inspector_id": inspector_id,
        "kind": kind,
        "planned_start_at": TEST_DEFAULTS["PLANNED_START_AT"],
        "planned_end_at": TEST_DEFAULTS["PLANNED_END_AT"],
    }
    cycle_id = overrides.pop("cycle_id", None)
    accident_id = overrides.pop("accident_id", None)
    if cycle_id is not None:
        payload["cycle_id"] = cycle_id
    if accident_id is not None:
        payload["accident_id"] = accident_id
    payload.update(overrides)
    return payload


def reassign_inspection_payload(new_inspector_id: str, **overrides) -> dict:
    payload = {"new_inspector_id": new_inspector_id}
    payload.update(overrides)
    return payload


# ─── Citations and abatement (PRD §3.4) ───────────────────────────────────────

def create_citation_payload(inspection_id: str, mine_id: str, **overrides) -> dict:
    """Citation issuance payload with the seven factor fields defaulted to a
    minimal LOW/UNLIKELY/NO_INJURY/1-person non-S&S non-repeat citation."""
    payload = {
        "inspection_id": inspection_id,
        "mine_id": mine_id,
        "standard_code": TEST_DEFAULTS["STANDARD_CODE"],
        "kind": "CITATION",
        "negligence": "LOW",
        "gravity_likelihood": "UNLIKELY",
        "gravity_severity": "NO_INJURY",
        "persons_affected": 1,
        "significant_and_substantial": False,
        "repeat_violation": False,
    }
    payload.update(overrides)
    return payload


def abate_citation_payload(**overrides) -> dict:
    payload = {"abatement_note": TEST_DEFAULTS["ABATEMENT_NOTE"]}
    payload.update(overrides)
    return payload


def verify_citation_abatement_payload(**overrides) -> dict:
    payload = {"verification_note": TEST_DEFAULTS["VERIFICATION_NOTE"]}
    payload.update(overrides)
    return payload


def extend_abatement_payload(**overrides) -> dict:
    payload = {"justification": TEST_DEFAULTS["JUSTIFICATION"]}
    payload.update(overrides)
    return payload


# ─── Imminent-danger orders (PRD §3.5) ────────────────────────────────────────

def create_ido_payload(mine_id: str, **overrides) -> dict:
    """IDO issuance payload. ``inspection_id`` is included only when supplied
    (optional; when present the inspection must be IN_PROGRESS at the mine
    and assigned to the acting inspector)."""
    payload = {
        "mine_id": mine_id,
        "hazard_description": TEST_DEFAULTS["HAZARD_DESCRIPTION"],
    }
    inspection_id = overrides.pop("inspection_id", None)
    if inspection_id is not None:
        payload["inspection_id"] = inspection_id
    payload.update(overrides)
    return payload


def confirm_withdrawal_payload(miners_withdrawn_count: int = None, **overrides) -> dict:
    payload = {
        "miners_withdrawn_count": (
            TEST_DEFAULTS["MINERS_WITHDRAWN_COUNT"]
            if miners_withdrawn_count is None
            else miners_withdrawn_count
        )
    }
    payload.update(overrides)
    return payload


def verify_ido_abatement_payload(**overrides) -> dict:
    payload = {"abatement_note": TEST_DEFAULTS["VERIFICATION_NOTE"]}
    payload.update(overrides)
    return payload


# ─── Contests (PRD §3.6) ──────────────────────────────────────────────────────

def create_contest_payload(citation_id: str, expected_citation_version: int,
                           **overrides) -> dict:
    """Contest filing payload; expected_citation_version is the OCC field of
    PRD §2.8 (read the citation's current version immediately before filing)."""
    payload = {
        "citation_id": citation_id,
        "expected_citation_version": expected_citation_version,
        "grounds": TEST_DEFAULTS["GROUNDS"],
    }
    payload.update(overrides)
    return payload


def decide_contest_payload(outcome: str, modified_penalty_cents=None, **overrides) -> dict:
    """Commission decision payload. modified_penalty_cents is included only
    when supplied — it is required iff outcome == MODIFIED and forbidden
    otherwise (ERR_CONTEST_DECISION_INVALID)."""
    payload = {"outcome": outcome}
    if modified_penalty_cents is not None:
        payload["modified_penalty_cents"] = modified_penalty_cents
    payload.update(overrides)
    return payload


# ─── Mine plans (PRD §3.7) ────────────────────────────────────────────────────

def submit_mine_plan_payload(plan_type: str = "EMERGENCY_RESPONSE", **overrides) -> dict:
    payload = {
        "plan_type": plan_type,
        "document_ref": TEST_DEFAULTS["DOCUMENT_REF"],
    }
    payload.update(overrides)
    return payload


def approve_mine_plan_payload(expected_mine_version: int, **overrides) -> dict:
    """Plan approval payload; expected_mine_version is the OCC field of
    PRD §2.8 (read the owning mine's current version immediately before
    approving)."""
    payload = {"expected_mine_version": expected_mine_version}
    payload.update(overrides)
    return payload


def reject_mine_plan_payload(rejection_reason: str = None, **overrides) -> dict:
    payload = {
        "rejection_reason": (
            TEST_DEFAULTS["REJECTION_REASON"] if rejection_reason is None else rejection_reason
        )
    }
    payload.update(overrides)
    return payload


# ─── Accidents (PRD §3.7) ─────────────────────────────────────────────────────

def report_accident_payload(mine_id: str, occurred_at: str, severity: str = "FATAL",
                            **overrides) -> dict:
    """Accident report payload. occurred_at is an input (when the accident
    occurred); reported_at is stamped from the logical clock."""
    payload = {
        "mine_id": mine_id,
        "occurred_at": occurred_at,
        "severity": severity,
        "description": TEST_DEFAULTS["ACCIDENT_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def publish_report_payload(**overrides) -> dict:
    payload = {
        "root_cause": TEST_DEFAULTS["ROOT_CAUSE"],
        "report_text": TEST_DEFAULTS["REPORT_TEXT"],
    }
    payload.update(overrides)
    return payload
