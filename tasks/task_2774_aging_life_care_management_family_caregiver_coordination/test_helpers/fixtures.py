"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test starts against an empty record. Setup calls go
through the lenient `get_success_data` validator so a broken precondition
surfaces as a setup failure rather than as a confusing assertion failure.

Two version-pinning re-reads are threaded through these helpers deliberately:
`GET /care/clients/{clientId}` immediately before authoring a care plan, and
`GET /care/care-plans/{carePlanId}` immediately before every proposal of a
service authorization, because every authorization transition on a plan advances
that plan's version.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    CARE_MANAGER_HOURLY_RATE_CENTS,
    SUPERVISOR_HOURLY_RATE_CENTS,
)
from .test_users import (
    BILLING_ADMINISTRATOR,
    PRACTICE_ADMIN,
    make_care_manager_headers,
    make_family_decision_maker_headers,
    make_practice_supervisor_headers,
)

DEFAULT_CLOCK = "2026-08-15T09:00:00Z"


# ------------------------------------------------------------ logical clock ---
def set_logical_clock(to_iso8601: str) -> str:
    """Move the server's logical clock and return the resulting `current_utc`."""
    data = get_success_data(
        api_client.set_clock(f.clock_payload(to_iso8601), PRACTICE_ADMIN)
    )
    return data["current_utc"]


# ------------------------------------------------------------------- reads ----
def read_client(client_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_client(client_id, headers or PRACTICE_ADMIN)
    )


def read_care_plan(
    care_plan_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_care_plan(care_plan_id, headers or PRACTICE_ADMIN)
    )


def read_authorization(
    authorization_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_service_authorization(authorization_id, headers or PRACTICE_ADMIN)
    )


def read_assessment(
    assessment_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_assessment(assessment_id, headers or PRACTICE_ADMIN)
    )


def read_time_entry(
    time_entry_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_time_entry(time_entry_id, headers or PRACTICE_ADMIN)
    )


def read_invoice(
    invoice_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_invoice(invoice_id, headers or PRACTICE_ADMIN)
    )


def read_conference(
    conference_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_family_conference(conference_id, headers or PRACTICE_ADMIN)
    )


def read_decision(
    decision_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_conference_decision(decision_id, headers or PRACTICE_ADMIN)
    )


def read_family_contact(
    contact_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_family_contact(contact_id, headers or PRACTICE_ADMIN)
    )


def read_crisis_episode(
    episode_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_crisis_episode(episode_id, headers or PRACTICE_ADMIN)
    )


# ------------------------------------------------------- registration tier ----
def register_client(**overrides: Any) -> Dict[str, Any]:
    """Register an older adult as a prospect. `retainer_floor_cents` defaults to
    0 here so that authorization fixtures are not gated on a deposit; tests that
    exercise the floor pass their own value."""
    payload = f.create_client_payload(**overrides)
    payload.setdefault("retainer_floor_cents", 0)
    return get_success_data(api_client.create_client(payload, PRACTICE_ADMIN))


def register_client_with_practice_defaults(**overrides: Any) -> Dict[str, Any]:
    """Register a client without supplying any of the four optional commercial
    parameters, so the practice defaults apply."""
    return get_success_data(
        api_client.create_client(f.create_client_payload(**overrides), PRACTICE_ADMIN)
    )


def register_care_manager(
    full_name: str = "Dana Whitfield",
    hourly_rate_cents: int = CARE_MANAGER_HOURLY_RATE_CENTS,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.create_care_manager_payload(
        full_name=full_name, hourly_rate_cents=hourly_rate_cents, **overrides
    )
    payload.setdefault("is_supervisor", False)
    return get_success_data(api_client.create_care_manager(payload, PRACTICE_ADMIN))


def register_supervisor(
    full_name: str = "Iris Ferreira",
    hourly_rate_cents: int = SUPERVISOR_HOURLY_RATE_CENTS,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.create_care_manager_payload(
        full_name=full_name, hourly_rate_cents=hourly_rate_cents, **overrides
    )
    payload["is_supervisor"] = True
    return get_success_data(api_client.create_care_manager(payload, PRACTICE_ADMIN))


def register_vendor(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_vendor(f.create_vendor_payload(**overrides), PRACTICE_ADMIN)
    )


def register_referral_vendor(
    name: str = "Southgate Elder Law",
    vendor_type: str = "LEGAL",
    referral_fee_pct: float = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    """A vendor carrying a referral relationship, which forces the
    conflict-of-interest disclosure on every authorization naming it."""
    return register_vendor(
        name=name,
        vendor_type=vendor_type,
        has_referral_relationship=True,
        referral_fee_pct=referral_fee_pct,
        **overrides,
    )


def register_family_contact(
    client_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_family_contact(
            f.create_family_contact_payload(client_id, **overrides),
            headers or PRACTICE_ADMIN,
        )
    )


def register_surrogate_contact(
    client_id: str,
    full_name: str = "Lena Oyelaran",
    contact_role: str = "POA_HEALTHCARE",
    **overrides: Any,
) -> Dict[str, Any]:
    """A family contact who may execute decisions on the client's behalf."""
    return register_family_contact(
        client_id,
        full_name=full_name,
        contact_role=contact_role,
        is_surrogate_decision_maker=True,
        **overrides,
    )


def deposit_retainer(
    client_id: str, amount_cents: int, received_at: str = "2026-08-15T09:00:00Z"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.post_retainer_deposit(
            client_id,
            f.retainer_deposit_payload(amount_cents=amount_cents, received_at=received_at),
            BILLING_ADMINISTRATOR,
        )
    )


def record_capacity_determination(
    client_id: str,
    capacity_status: str,
    basis: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    """Record a capacity determination. `headers` must belong to a `CareManager`
    or a `PracticeSupervisor`, the only two roles the operation admits."""
    return get_success_data(
        api_client.record_capacity_determination(
            client_id,
            f.capacity_determination_payload(capacity_status=capacity_status, basis=basis),
            headers,
        )
    )


def discharge_client(client_id: str, reason: str = "File closed") -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_client_state(
            client_id, f.client_state_payload("DISCHARGED", reason=reason), PRACTICE_ADMIN
        )
    )


# ------------------------------------------------------- assessment tier ------
def open_assessment(
    client_id: str,
    care_manager_id: str,
    scores: Optional[Dict[str, int]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_assessment(
            f.create_assessment_payload(
                client_id, care_manager_id, scores=scores, **overrides
            ),
            make_care_manager_headers(care_manager_id),
        )
    )


def submit_assessment(assessment_id: str, care_manager_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_assessment_state(
            assessment_id,
            f.assessment_state_payload("SUBMITTED"),
            make_care_manager_headers(care_manager_id),
        )
    )


def accept_assessment(assessment_id: str, supervisor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_assessment_state(
            assessment_id,
            f.assessment_state_payload("ACCEPTED", **overrides),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def request_assessment_revision(
    assessment_id: str, supervisor_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_assessment_state(
            assessment_id,
            f.assessment_state_payload("REVISION_REQUESTED", **overrides),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def return_assessment_to_draft(assessment_id: str, care_manager_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_assessment_state(
            assessment_id,
            f.assessment_state_payload("DRAFT"),
            make_care_manager_headers(care_manager_id),
        )
    )


def create_accepted_assessment(
    client_id: str,
    care_manager_id: str,
    supervisor_id: str,
    scores: Optional[Dict[str, int]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a draft, submit it as its author, and accept it as the supervisor."""
    assessment = open_assessment(client_id, care_manager_id, scores=scores, **overrides)
    submit_assessment(assessment["id"], care_manager_id)
    return accept_assessment(assessment["id"], supervisor_id)


# --------------------------------------------------------- care plan tier -----
def author_care_plan(
    client_id: str,
    source_assessment_id: str,
    care_manager_id: str,
    goals: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Read the client for its current `version`, then author the plan against
    that pinned value."""
    client = read_client(client_id)
    payload = f.create_care_plan_payload(
        client_id,
        source_assessment_id,
        client["version"],
        goals=goals,
        **overrides,
    )
    return get_success_data(
        api_client.create_care_plan(payload, make_care_manager_headers(care_manager_id))
    )


def send_plan_for_family_approval(
    care_plan_id: str, care_manager_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_care_plan_state(
            care_plan_id,
            f.care_plan_state_payload("PENDING_FAMILY_APPROVAL", **overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


def family_approve_plan(
    care_plan_id: str, surrogate_contact_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_care_plan_state(
            care_plan_id,
            f.care_plan_state_payload("ACTIVE", **overrides),
            make_family_decision_maker_headers(surrogate_contact_id),
        )
    )


def family_reject_plan(
    care_plan_id: str, surrogate_contact_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_care_plan_state(
            care_plan_id,
            f.care_plan_state_payload("REJECTED", **overrides),
            make_family_decision_maker_headers(surrogate_contact_id),
        )
    )


def return_plan_to_draft(care_plan_id: str, care_manager_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_care_plan_state(
            care_plan_id,
            f.care_plan_state_payload("DRAFT"),
            make_care_manager_headers(care_manager_id),
        )
    )


def create_active_care_plan(
    client_id: str,
    source_assessment_id: str,
    care_manager_id: str,
    surrogate_contact_id: str,
    goals: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Author a plan, send it for family approval, and have the surrogate
    approve it, which also advances the client to ACTIVE_CARE."""
    plan = author_care_plan(
        client_id, source_assessment_id, care_manager_id, goals=goals, **overrides
    )
    send_plan_for_family_approval(plan["id"], care_manager_id)
    return family_approve_plan(plan["id"], surrogate_contact_id)


# ---------------------------------------------- service authorization tier ----
def propose_service_authorization(
    care_plan_id: str,
    vendor_id: str,
    care_manager_id: str,
    coverage_start: str = "2026-08-16T08:00:00Z",
    coverage_end: str = "2026-08-16T16:00:00Z",
    concurrent_caregivers: int = 1,
    hourly_cost_cents: int = 4_000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Re-read the care plan for a fresh `version` and propose the engagement."""
    plan = read_care_plan(care_plan_id)
    payload = f.create_service_authorization_payload(
        care_plan_id,
        vendor_id,
        plan["version"],
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        concurrent_caregivers=concurrent_caregivers,
        hourly_cost_cents=hourly_cost_cents,
        **overrides,
    )
    return get_success_data(
        api_client.create_service_authorization(
            payload, make_care_manager_headers(care_manager_id)
        )
    )


def authorize_service_authorization(
    authorization_id: str, supervisor_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_service_authorization_state(
            authorization_id,
            f.authorization_state_payload("AUTHORIZED", **overrides),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def activate_service_authorization(
    authorization_id: str, care_manager_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_service_authorization_state(
            authorization_id,
            f.authorization_state_payload("ACTIVE", **overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


def suspend_service_authorization(
    authorization_id: str, care_manager_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_service_authorization_state(
            authorization_id,
            f.authorization_state_payload("SUSPENDED", **overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


def terminate_service_authorization(
    authorization_id: str, care_manager_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_service_authorization_state(
            authorization_id,
            f.authorization_state_payload("TERMINATED", **overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


def disclose_conflict_of_interest(
    authorization_id: str, care_manager_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.post_coi_event(
            authorization_id,
            f.coi_event_payload("DISCLOSE", **overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


def acknowledge_conflict_of_interest(
    authorization_id: str, surrogate_contact_id: str, **overrides: Any
) -> Dict[str, Any]:
    """The acknowledging contact must be the acting `X-User-ID`, so nobody
    acknowledges on somebody else's behalf."""
    return get_success_data(
        api_client.post_coi_event(
            authorization_id,
            f.coi_event_payload(
                "ACKNOWLEDGE", acknowledged_by_contact_id=surrogate_contact_id, **overrides
            ),
            make_family_decision_maker_headers(surrogate_contact_id),
        )
    )


# ------------------------------------------------------ conference tier -------
def schedule_conference(
    client_id: str,
    invited_contact_ids: List[str],
    care_manager_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_family_conference(
            f.create_family_conference_payload(
                client_id, invited_contact_ids, **overrides
            ),
            make_care_manager_headers(care_manager_id),
        )
    )


def convene_conference(
    conference_id: str,
    attended_contact_ids: List[str],
    care_manager_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_family_conference_state(
            conference_id,
            f.conference_state_payload(
                "CONVENED", attended_contact_ids=list(attended_contact_ids), **overrides
            ),
            make_care_manager_headers(care_manager_id),
        )
    )


def document_conference(conference_id: str, care_manager_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_family_conference_state(
            conference_id,
            f.conference_state_payload("DOCUMENTED", **overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


def record_conference_decision(
    conference_id: str,
    decided_by_contact_id: str,
    care_manager_id: str,
    decision_type: str = "VENDOR_ENGAGEMENT",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_conference_decision(
            f.create_conference_decision_payload(
                conference_id,
                decided_by_contact_id,
                decision_type=decision_type,
                **overrides,
            ),
            make_care_manager_headers(care_manager_id),
        )
    )


def ratify_conference_decision(
    decision_id: str, supervisor_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_conference_decision_state(
            decision_id,
            f.decision_state_payload("RATIFIED", **overrides),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def escalate_conference_decision(
    decision_id: str, supervisor_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_conference_decision_state(
            decision_id,
            f.decision_state_payload("ESCALATED", **overrides),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def accept_escalation(decision_id: str, supervisor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_conference_decision_state(
            decision_id,
            f.decision_state_payload("ESCALATION_ACCEPTED", **overrides),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def decline_escalation(decision_id: str, supervisor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_conference_decision_state(
            decision_id,
            f.decision_state_payload("ESCALATION_DECLINED", **overrides),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def rescind_conference_decision(
    decision_id: str, supervisor_id: str, note: str = "Family withdrew the engagement"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_conference_decision_state(
            decision_id,
            f.decision_state_payload("RESCINDED", note=note),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def create_ratified_decision(
    client_id: str,
    surrogate_contact_id: str,
    care_manager_id: str,
    supervisor_id: str,
    decision_type: str = "VENDOR_ENGAGEMENT",
    invited_contact_ids: Optional[List[str]] = None,
    attended_contact_ids: Optional[List[str]] = None,
    **decision_overrides: Any,
) -> Dict[str, Any]:
    """Schedule a conference, convene it with the surrogate present, document a
    decision against it and have the supervisor ratify it. Only a RATIFIED
    decision may be named as the authorizing decision on a vendor engagement."""
    invited = invited_contact_ids or [surrogate_contact_id]
    attended = attended_contact_ids or [surrogate_contact_id]
    conference = schedule_conference(client_id, invited, care_manager_id)
    convene_conference(conference["id"], attended, care_manager_id)
    decision = record_conference_decision(
        conference["id"],
        surrogate_contact_id,
        care_manager_id,
        decision_type=decision_type,
        **decision_overrides,
    )
    return ratify_conference_decision(decision["id"], supervisor_id)


def create_documented_conference_with_ratified_decision(
    client_id: str,
    surrogate_contact_id: str,
    care_manager_id: str,
    supervisor_id: str,
    decision_type: str = "ESCALATE_GUARDIANSHIP_PETITION",
    **decision_overrides: Any,
) -> Dict[str, Any]:
    """Reach a DOCUMENTED conference carrying one RATIFIED decision, the state an
    escalation requires. Returns a dict of `conference` and `decision`."""
    conference = schedule_conference(
        client_id, [surrogate_contact_id], care_manager_id
    )
    convene_conference(conference["id"], [surrogate_contact_id], care_manager_id)
    decision = record_conference_decision(
        conference["id"],
        surrogate_contact_id,
        care_manager_id,
        decision_type=decision_type,
        **decision_overrides,
    )
    ratified = ratify_conference_decision(decision["id"], supervisor_id)
    documented = document_conference(conference["id"], care_manager_id)
    return {"conference": documented, "decision": ratified}


# ---------------------------------------------------- crisis episode tier ------
def open_crisis_episode(
    client_id: str, care_manager_id: str, trigger_type: str = "FALL", **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_crisis_episode(
            f.create_crisis_episode_payload(
                client_id, trigger_type=trigger_type, **overrides
            ),
            make_care_manager_headers(care_manager_id),
        )
    )


def stabilize_crisis_episode(
    episode_id: str, care_manager_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_crisis_episode_state(
            episode_id,
            f.crisis_episode_state_payload("STABILIZED", **overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


def hand_to_transition_oversight(
    episode_id: str, care_manager_id: str, discharge_at: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_crisis_episode_state(
            episode_id,
            f.crisis_episode_state_payload(
                "TRANSITION_OVERSIGHT", discharge_at=discharge_at, **overrides
            ),
            make_care_manager_headers(care_manager_id),
        )
    )


def close_crisis_episode(
    episode_id: str, care_manager_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_crisis_episode_state(
            episode_id,
            f.crisis_episode_state_payload("CLOSED", **overrides),
            make_care_manager_headers(care_manager_id),
        )
    )


# -------------------------------------------------------- time entry tier ------
def log_time_entry(
    client_id: str,
    care_manager_id: str,
    start_at: str,
    end_at: str,
    service_type: str = "CARE_COORDINATION",
    service_location_id: str = "CLIENT_HOME",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_time_entry(
            f.create_time_entry_payload(
                client_id,
                care_manager_id,
                start_at,
                end_at,
                service_type=service_type,
                service_location_id=service_location_id,
                **overrides,
            ),
            make_care_manager_headers(care_manager_id),
        )
    )


def submit_time_entry(time_entry_id: str, care_manager_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_time_entry_state(
            time_entry_id,
            f.time_entry_state_payload("SUBMITTED"),
            make_care_manager_headers(care_manager_id),
        )
    )


def approve_time_entry(time_entry_id: str, supervisor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_time_entry_state(
            time_entry_id,
            f.time_entry_state_payload("APPROVED", **overrides),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def reject_time_entry(time_entry_id: str, supervisor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_time_entry_state(
            time_entry_id,
            f.time_entry_state_payload("REJECTED", **overrides),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def void_time_entry(time_entry_id: str, supervisor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_time_entry_state(
            time_entry_id,
            f.time_entry_state_payload("VOIDED", **overrides),
            make_practice_supervisor_headers(supervisor_id),
        )
    )


def create_approved_time_entry(
    client_id: str,
    care_manager_id: str,
    supervisor_id: str,
    start_at: str,
    end_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Log an interval, submit it as its author, and approve it as a supervisor
    who is not the author."""
    entry = log_time_entry(client_id, care_manager_id, start_at, end_at, **overrides)
    submit_time_entry(entry["id"], care_manager_id)
    return approve_time_entry(entry["id"], supervisor_id)


# ----------------------------------------------------------- invoice tier ------
def open_invoice(
    client_id: str,
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-31",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_invoice(
            f.create_invoice_payload(
                client_id, period_start=period_start, period_end=period_end, **overrides
            ),
            BILLING_ADMINISTRATOR,
        )
    )


def issue_invoice(invoice_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_invoice_state(
            invoice_id, f.invoice_state_payload("ISSUED", **overrides), BILLING_ADMINISTRATOR
        )
    )


def void_invoice(invoice_id: str, reason: str = "Billed in error") -> Dict[str, Any]:
    return get_success_data(
        api_client.patch_invoice_state(
            invoice_id,
            f.invoice_state_payload("VOIDED", reason=reason),
            BILLING_ADMINISTRATOR,
        )
    )


def pay_invoice(
    invoice_id: str, amount_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.post_invoice_payment(
            invoice_id,
            f.invoice_payment_payload(amount_cents, **overrides),
            BILLING_ADMINISTRATOR,
        )
    )


def create_issued_invoice(
    client_id: str,
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-31",
) -> Dict[str, Any]:
    invoice = open_invoice(client_id, period_start=period_start, period_end=period_end)
    return issue_invoice(invoice["id"])


# ====================================================== composite scenarios ====
@dataclass
class CareScenario:
    """A practice with the people around one client, plus whichever clinical and
    commercial records the scenario walked into place."""

    client: Dict[str, Any]
    care_manager: Dict[str, Any]
    supervisor: Dict[str, Any]
    surrogate: Optional[Dict[str, Any]] = None
    vendor: Optional[Dict[str, Any]] = None
    assessment: Optional[Dict[str, Any]] = None
    care_plan: Optional[Dict[str, Any]] = None
    authorization: Optional[Dict[str, Any]] = None
    contacts: List[Dict[str, Any]] = field(default_factory=list)

    # --- convenient ids ---
    @property
    def client_id(self) -> str:
        return self.client["id"]

    @property
    def care_manager_id(self) -> str:
        return self.care_manager["id"]

    @property
    def supervisor_id(self) -> str:
        return self.supervisor["id"]

    @property
    def surrogate_id(self) -> str:
        assert self.surrogate is not None, "this scenario has no surrogate contact"
        return self.surrogate["id"]

    @property
    def vendor_id(self) -> str:
        assert self.vendor is not None, "this scenario has no vendor"
        return self.vendor["id"]

    @property
    def assessment_id(self) -> str:
        assert self.assessment is not None, "this scenario has no assessment"
        return self.assessment["id"]

    @property
    def care_plan_id(self) -> str:
        assert self.care_plan is not None, "this scenario has no care plan"
        return self.care_plan["id"]

    @property
    def authorization_id(self) -> str:
        assert self.authorization is not None, "this scenario has no authorization"
        return self.authorization["id"]

    # --- headers threaded with the real entity ids ---
    @property
    def cm_headers(self) -> Dict[str, str]:
        return make_care_manager_headers(self.care_manager_id)

    @property
    def supervisor_headers(self) -> Dict[str, str]:
        return make_practice_supervisor_headers(self.supervisor_id)

    @property
    def family_headers(self) -> Dict[str, str]:
        return make_family_decision_maker_headers(self.surrogate_id)

    @property
    def admin_headers(self) -> Dict[str, str]:
        return PRACTICE_ADMIN

    @property
    def billing_headers(self) -> Dict[str, str]:
        return BILLING_ADMINISTRATOR

    # --- live re-reads ---
    def refresh_client(self) -> Dict[str, Any]:
        self.client = read_client(self.client_id)
        return self.client

    def refresh_care_plan(self) -> Dict[str, Any]:
        self.care_plan = read_care_plan(self.care_plan_id)
        return self.care_plan

    def refresh_authorization(self) -> Dict[str, Any]:
        self.authorization = read_authorization(self.authorization_id)
        return self.authorization


def setup_practice(
    clock: Optional[str] = DEFAULT_CLOCK,
    client_overrides: Optional[Dict[str, Any]] = None,
    surrogate_role: str = "POA_HEALTHCARE",
    with_surrogate: bool = True,
    with_vendor: bool = True,
    vendor_overrides: Optional[Dict[str, Any]] = None,
    deposit_cents: Optional[int] = None,
) -> CareScenario:
    """Tier 2. The recurring preamble: a logical clock, one care manager, one
    supervisor, one client, one surrogate family contact and one vendor."""
    if clock is not None:
        set_logical_clock(clock)
    care_manager = register_care_manager()
    supervisor = register_supervisor()
    client = register_client(**(client_overrides or {}))
    surrogate = (
        register_surrogate_contact(client["id"], contact_role=surrogate_role)
        if with_surrogate
        else None
    )
    vendor = register_vendor(**(vendor_overrides or {})) if with_vendor else None
    if deposit_cents is not None:
        client = deposit_retainer(client["id"], deposit_cents)
    return CareScenario(
        client=client,
        care_manager=care_manager,
        supervisor=supervisor,
        surrogate=surrogate,
        vendor=vendor,
        contacts=[c for c in [surrogate] if c is not None],
    )


def setup_accepted_assessment_scenario(
    scores: Optional[Dict[str, int]] = None, **practice_kwargs: Any
) -> CareScenario:
    """Tier 3. A practice whose client carries one ACCEPTED assessment, the only
    clinical basis a care plan may be authored from."""
    scenario = setup_practice(**practice_kwargs)
    scenario.assessment = create_accepted_assessment(
        scenario.client_id, scenario.care_manager_id, scenario.supervisor_id, scores=scores
    )
    scenario.refresh_client()
    return scenario


def setup_draft_care_plan_scenario(
    scores: Optional[Dict[str, int]] = None,
    goals: Optional[List[str]] = None,
    **practice_kwargs: Any,
) -> CareScenario:
    """Tier 3. A DRAFT care plan authored from an accepted assessment."""
    scenario = setup_accepted_assessment_scenario(scores=scores, **practice_kwargs)
    scenario.care_plan = author_care_plan(
        scenario.client_id,
        scenario.assessment_id,
        scenario.care_manager_id,
        goals=goals,
    )
    scenario.refresh_client()
    return scenario


def setup_active_care_plan_scenario(
    scores: Optional[Dict[str, int]] = None,
    goals: Optional[List[str]] = None,
    **practice_kwargs: Any,
) -> CareScenario:
    """Tier 3. An ACTIVE care plan approved by the surrogate, which also advances
    the client to ACTIVE_CARE."""
    scenario = setup_draft_care_plan_scenario(scores=scores, goals=goals, **practice_kwargs)
    send_plan_for_family_approval(scenario.care_plan_id, scenario.care_manager_id)
    scenario.care_plan = family_approve_plan(scenario.care_plan_id, scenario.surrogate_id)
    scenario.refresh_client()
    return scenario


def setup_proposed_authorization_scenario(
    coverage_start: str = "2026-08-16T08:00:00Z",
    coverage_end: str = "2026-08-16T16:00:00Z",
    concurrent_caregivers: int = 1,
    hourly_cost_cents: int = 4_000,
    authorization_overrides: Optional[Dict[str, Any]] = None,
    **plan_kwargs: Any,
) -> CareScenario:
    """Tier 3. A PROPOSED authorization sitting under an ACTIVE care plan."""
    scenario = setup_active_care_plan_scenario(**plan_kwargs)
    scenario.authorization = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        concurrent_caregivers=concurrent_caregivers,
        hourly_cost_cents=hourly_cost_cents,
        **(authorization_overrides or {}),
    )
    scenario.refresh_client()
    return scenario


def setup_authorized_authorization_scenario(**kwargs: Any) -> CareScenario:
    """Tier 3. An AUTHORIZED authorization, so the client already carries its
    coverage hours and the parent plan's coverage gap has closed."""
    scenario = setup_proposed_authorization_scenario(**kwargs)
    scenario.authorization = authorize_service_authorization(
        scenario.authorization_id, scenario.supervisor_id
    )
    scenario.refresh_client()
    return scenario


def setup_active_authorization_scenario(**kwargs: Any) -> CareScenario:
    """Tier 3. An ACTIVE authorization — the state suspension and termination
    compensate away from."""
    scenario = setup_authorized_authorization_scenario(**kwargs)
    scenario.authorization = activate_service_authorization(
        scenario.authorization_id, scenario.care_manager_id
    )
    scenario.refresh_client()
    return scenario


def setup_accrued_time_scenario(
    windows: Optional[List[Dict[str, Any]]] = None,
    approve: bool = True,
    **plan_kwargs: Any,
) -> Dict[str, Any]:
    """Tier 4. An ACTIVE_CARE client carrying one or more logged intervals, so a
    known `unbilled_accrual_cents` is standing before the invoice under test.

    Each window is a dict of `start_at`, `end_at` and any time-entry overrides.
    Returns `{"scenario": CareScenario, "time_entries": [...]}` with the entries
    APPROVED unless `approve` is false.
    """
    scenario = setup_active_care_plan_scenario(**plan_kwargs)
    windows = windows or [
        {"start_at": "2026-08-16T10:00:00Z", "end_at": "2026-08-16T11:00:00Z"}
    ]
    entries: List[Dict[str, Any]] = []
    for window in windows:
        start_at = window.pop("start_at")
        end_at = window.pop("end_at")
        entry = log_time_entry(
            scenario.client_id, scenario.care_manager_id, start_at, end_at, **window
        )
        if approve:
            submit_time_entry(entry["id"], scenario.care_manager_id)
            entry = approve_time_entry(entry["id"], scenario.supervisor_id)
        entries.append(entry)
    scenario.refresh_client()
    return {"scenario": scenario, "time_entries": entries}


def setup_issued_invoice_scenario(
    deposit_cents: int = 60_000,
    windows: Optional[List[Dict[str, Any]]] = None,
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-31",
    **plan_kwargs: Any,
) -> Dict[str, Any]:
    """Tier 5. Retainer on deposit, approved time standing, and one ISSUED
    invoice that has actually drawn the retainer.

    Returns `{"scenario": ..., "time_entries": [...], "invoice": ...}`.
    """
    plan_kwargs.setdefault("deposit_cents", deposit_cents)
    built = setup_accrued_time_scenario(windows=windows, **plan_kwargs)
    scenario: CareScenario = built["scenario"]
    invoice = open_invoice(
        scenario.client_id, period_start=period_start, period_end=period_end
    )
    invoice = issue_invoice(invoice["id"])
    scenario.refresh_client()
    return {
        "scenario": scenario,
        "time_entries": built["time_entries"],
        "invoice": invoice,
    }


def setup_crisis_scenario(
    trigger_type: str = "FALL", **practice_kwargs: Any
) -> Dict[str, Any]:
    """Tier 3. An OPEN crisis episode, which puts the client's posture at CRISIS
    immediately. Returns `{"scenario": ..., "episode": ...}`."""
    scenario = setup_practice(**practice_kwargs)
    episode = open_crisis_episode(
        scenario.client_id, scenario.care_manager_id, trigger_type=trigger_type
    )
    scenario.refresh_client()
    return {"scenario": scenario, "episode": episode}
