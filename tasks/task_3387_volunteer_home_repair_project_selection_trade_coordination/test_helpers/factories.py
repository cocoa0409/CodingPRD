"""Payload factories — one per creation endpoint, input fields only.

Shapes match the PRD §4 endpoint definitions verbatim. Optional fields are
included only when a non-None value is supplied, so server-side defaults
(priority_mode STANDARD, sponsor_tier COMMUNITY, skills [], team_leader flags
false, max_concurrent_jobs 1) are exercised unless a caller overrides them.
"""

from .constants import (
    DEFAULT_ADDRESS,
    DEFAULT_ASSESSMENT_DATE,
    DEFAULT_BUDGET_CENTS,
    DEFAULT_DOB,
    DEFAULT_EVENT_DATE,
    DEFAULT_FISCAL_YEAR,
    DEFAULT_HOUSEHOLD_SIZE,
    DEFAULT_INCOME_CENTS,
    DEFAULT_INSURANCE_EXPIRES_ON,
    DEFAULT_LICENSE_EXPIRES_ON,
    DEFAULT_MAX_VOLUNTEERS,
    DEFAULT_VISIT_END,
    DEFAULT_VISIT_START,
)

_counter = {"n": 0}


def _unique(tag: str) -> str:
    _counter["n"] += 1
    return f"{tag}-{_counter['n']}"


# --- FundingCycle / SelectionRun ----------------------------------------------

def create_funding_cycle_payload(**overrides) -> dict:
    payload = {
        "name": overrides.pop("name", _unique("Cycle")),
        "fiscal_year": overrides.pop("fiscal_year", DEFAULT_FISCAL_YEAR),
        "total_budget_cents": overrides.pop("total_budget_cents", DEFAULT_BUDGET_CENTS),
    }
    priority_mode = overrides.pop("priority_mode", None)
    if priority_mode is not None:
        payload["priority_mode"] = priority_mode
    payload.update(overrides)
    return payload


def create_selection_run_payload(expected_funding_cycle_version, **overrides) -> dict:
    payload = {"expected_funding_cycle_version": expected_funding_cycle_version}
    payload.update(overrides)
    return payload


# --- Sponsor / SponsorshipCommitment -------------------------------------------

def create_sponsor_payload(**overrides) -> dict:
    payload = {
        "name": overrides.pop("name", _unique("Sponsor")),
        "contact_email": overrides.pop("contact_email", f"{_unique('sponsor')}@example.com"),
    }
    sponsor_tier = overrides.pop("sponsor_tier", None)
    if sponsor_tier is not None:
        payload["sponsor_tier"] = sponsor_tier
    payload.update(overrides)
    return payload


def create_commitment_payload(sponsor_id, funding_cycle_id, amount_cents, **overrides) -> dict:
    payload = {
        "sponsor_id": sponsor_id,
        "funding_cycle_id": funding_cycle_id,
        "amount_cents": amount_cents,
    }
    team_build_event_date = overrides.pop("team_build_event_date", None)
    if team_build_event_date is not None:
        payload["team_build_event_date"] = team_build_event_date
    payload.update(overrides)
    return payload


# --- HomeownerApplication --------------------------------------------------------

def create_application_payload(funding_cycle_id, **overrides) -> dict:
    """Required inputs per PRD §3.2; defaults form an eligible, doc-complete,
    non-older-adult household of one well under the income ceiling."""
    payload = {
        "funding_cycle_id": funding_cycle_id,
        "homeowner_name": overrides.pop("homeowner_name", _unique("Homeowner")),
        "date_of_birth": overrides.pop("date_of_birth", DEFAULT_DOB),
        "household_size": overrides.pop("household_size", DEFAULT_HOUSEHOLD_SIZE),
        "household_income_cents": overrides.pop(
            "household_income_cents", DEFAULT_INCOME_CENTS
        ),
        "is_veteran": overrides.pop("is_veteran", False),
        "has_disability": overrides.pop("has_disability", False),
        "ownership_doc_provided": overrides.pop("ownership_doc_provided", True),
        "occupancy_doc_provided": overrides.pop("occupancy_doc_provided", True),
        "address": overrides.pop("address", DEFAULT_ADDRESS),
    }
    payload.update(overrides)
    return payload


# --- HomeAssessment / ScopeItem --------------------------------------------------

def create_assessment_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "scheduled_on": overrides.pop("scheduled_on", DEFAULT_ASSESSMENT_DATE),
    }
    payload.update(overrides)
    return payload


def scope_item_payload(**overrides) -> dict:
    """One scope-item input element (PRD §3.3). Default: a volunteer-performable
    GENERAL item estimated 100000..100000 cents with no permit requirement."""
    payload = {
        "category": overrides.pop("category", "GENERAL"),
        "required_trade": overrides.pop("required_trade", "NONE"),
        "volunteer_performable": overrides.pop("volunteer_performable", True),
        "requires_permit": overrides.pop("requires_permit", False),
        "est_low_cents": overrides.pop("est_low_cents", 100_000),
        "est_high_cents": overrides.pop("est_high_cents", 100_000),
        "description": overrides.pop("description", _unique("item")),
    }
    payload.update(overrides)
    return payload


def trade_scope_item_payload(
    trade="ELECTRICAL", est_low_cents=50_000, est_high_cents=50_000, **overrides
) -> dict:
    """A licensed-trade item: volunteer_performable false, required_trade set."""
    return scope_item_payload(
        category=overrides.pop("category", "CRITICAL_SYSTEMS"),
        required_trade=trade,
        volunteer_performable=False,
        est_low_cents=est_low_cents,
        est_high_cents=est_high_cents,
        **overrides,
    )


def complete_assessment_payload(scope_items=None, **overrides) -> dict:
    """Completion body (PRD §3.3): findings plus a non-empty scope_items array."""
    payload = {
        "safety_hazard_max_severity": overrides.pop("safety_hazard_max_severity", 0),
        "accessibility_needs_count": overrides.pop("accessibility_needs_count", 0),
        "scope_items": scope_items if scope_items is not None else [scope_item_payload()],
    }
    notes = overrides.pop("critical_systems_notes", None)
    if notes is not None:
        payload["critical_systems_notes"] = notes
    payload.update(overrides)
    return payload


# --- Project scope amendment ------------------------------------------------------

def create_scope_amendment_payload(expected_project_version, **overrides) -> dict:
    """OCC-guarded amendment body; add_items / drop_item_ids / restore_item_ids
    are included only when supplied."""
    payload = {"expected_project_version": expected_project_version}
    for key in ("add_items", "drop_item_ids", "restore_item_ids"):
        value = overrides.pop(key, None)
        if value is not None:
            payload[key] = value
    payload.update(overrides)
    return payload


# --- RebuildEvent ------------------------------------------------------------------

def create_event_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "name": overrides.pop("name", _unique("Rebuild Day")),
        "event_date": overrides.pop("event_date", DEFAULT_EVENT_DATE),
        "max_volunteers": overrides.pop("max_volunteers", DEFAULT_MAX_VOLUNTEERS),
    }
    payload.update(overrides)
    return payload


# --- Volunteer / EventEnrollment -----------------------------------------------------

def create_volunteer_payload(**overrides) -> dict:
    payload = {
        "full_name": overrides.pop("full_name", _unique("Volunteer")),
        "email": overrides.pop("email", f"{_unique('vol')}@example.com"),
    }
    skills = overrides.pop("skills", None)
    if skills is not None:
        payload["skills"] = skills
    tle = overrides.pop("team_leader_eligible", None)
    if tle is not None:
        payload["team_leader_eligible"] = tle
    payload.update(overrides)
    return payload


def create_enrollment_payload(event_id, volunteer_id, **overrides) -> dict:
    payload = {"event_id": event_id, "volunteer_id": volunteer_id}
    is_team_leader = overrides.pop("is_team_leader", None)
    if is_team_leader is not None:
        payload["is_team_leader"] = is_team_leader
    payload.update(overrides)
    return payload


# --- TradeContractor / TradeWorkOrder -------------------------------------------------

def create_contractor_payload(**overrides) -> dict:
    payload = {
        "legal_name": overrides.pop("legal_name", _unique("Contractor")),
        "trade": overrides.pop("trade", "ELECTRICAL"),
        "license_number": overrides.pop("license_number", _unique("LIC")),
        "license_expires_on": overrides.pop(
            "license_expires_on", DEFAULT_LICENSE_EXPIRES_ON
        ),
        "insurance_expires_on": overrides.pop(
            "insurance_expires_on", DEFAULT_INSURANCE_EXPIRES_ON
        ),
    }
    max_concurrent_jobs = overrides.pop("max_concurrent_jobs", None)
    if max_concurrent_jobs is not None:
        payload["max_concurrent_jobs"] = max_concurrent_jobs
    payload.update(overrides)
    return payload


def create_work_order_payload(project_id, contractor_id, scope_item_ids, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "contractor_id": contractor_id,
        "scope_item_ids": list(scope_item_ids),
    }
    payload.update(overrides)
    return payload


def schedule_work_order_payload(visit_start=DEFAULT_VISIT_START, visit_end=DEFAULT_VISIT_END, **overrides) -> dict:
    payload = {"visit_start": visit_start, "visit_end": visit_end}
    payload.update(overrides)
    return payload


def inspect_work_order_payload(outcome="PASSED", **overrides) -> dict:
    payload = {"outcome": outcome}
    notes = overrides.pop("notes", None)
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# --- MaterialOrder ---------------------------------------------------------------------

def material_line_payload(item_name=None, quantity=1, unit_price_dollars=10.00, **overrides) -> dict:
    payload = {
        "item_name": item_name if item_name is not None else _unique("material"),
        "quantity": quantity,
        "unit_price_dollars": unit_price_dollars,
    }
    payload.update(overrides)
    return payload


def create_material_order_payload(project_id, lines=None, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "lines": lines if lines is not None else [material_line_payload()],
    }
    supplier = overrides.pop("supplier", None)
    if supplier is not None:
        payload["supplier"] = supplier
    payload.update(overrides)
    return payload


# --- WarrantyClaim -----------------------------------------------------------------------

def create_warranty_claim_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "description": overrides.pop("description", _unique("Defect")),
        "claim_amount_cents": overrides.pop("claim_amount_cents", 5_000),
    }
    payload.update(overrides)
    return payload
