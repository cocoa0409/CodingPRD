"""Agent roster and referral relationship (PRD 3.1, PRD 3.7).

Registering an agent requires a ``full_name``, a ``brokerage_name`` and a state
``license_number`` unique across all agents, and permits an optional
``referral_rate_bps`` defaulting to 250 basis points.  A freshly registered agent
is ``PENDING``.  A coordinator moves it to ``QUALIFIED`` once verified; the
licence number must be present for that step.  A coordinator can suspend an
agent that is either ``PENDING`` or ``QUALIFIED``, and suspension is contagious
in exactly one direction: every referral belonging to that agent whose status is
``OPEN`` is simultaneously moved to ``VOIDED``, and ``active_referral_count`` is
recomputed on both the agent and each affected program.  Reinstatement supplies
a ``reinstatement_note`` and returns the agent to ``QUALIFIED``; it does not
revive the referrals that were voided.

A referral is created against an ``agent_id`` and a ``bridge_program_id`` with a
``role_scope``, carrying its own ``referral_rate_bps`` copied from the agent at
creation (and overridable) together with a ``qualifying_volume_cents``
defaulting to 0.  It opens ``OPEN``.  Two rules constrain creation: an agent
whose ``qualification_status`` is ``SUSPENDED`` cannot be the subject of a new
referral (``ERR_AGENT_NOT_QUALIFIED``), and a program may not hold two
simultaneously active referrals for the same side of the transaction
(``ERR_DUPLICATE_ACTIVE_REFERRAL``).
"""

from constants import (
    DEFAULT_AGENT_REFERRAL_RATE_BPS,
    DEFAULT_QUALIFYING_VOLUME_CENTS,
    REFERRAL_ROLE_SCOPES,
)
from errors import (
    ERR_AGENT_NOT_QUALIFIED,
    ERR_DUPLICATE_ACTIVE_REFERRAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ApiError,
)
from services import current_time, create, touch
from services import disclosure as disclosure_service
from services import referral as referral_service
from services.lookup import get_agent, get_bridge_program, get_referral
from store import db
from timeutil import format_iso
from validation import body_of, get_enum, get_int, get_str


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def create_agent(payload):
    data = body_of(payload)
    full_name = get_str(data, "full_name", required=True)
    brokerage_name = get_str(data, "brokerage_name", required=True)
    license_number = get_str(data, "license_number", required=True)

    for existing in db.all("agents"):
        if existing.get("license_number") == license_number:
            raise ApiError(ERR_INVALID_REQUEST, "license_number must be unique across agents.")

    referral_rate_bps = get_int(
        data, "referral_rate_bps", required=False, default=DEFAULT_AGENT_REFERRAL_RATE_BPS, minimum=0
    )

    record = {
        "full_name": full_name,
        "brokerage_name": brokerage_name,
        "license_number": license_number,
        "referral_rate_bps": referral_rate_bps,
        "qualification_status": "PENDING",
        "active_referral_count": 0,
    }
    create("agents", record)
    return record


def qualify_agent(agent_id):
    agent = get_agent(agent_id)
    if agent.get("qualification_status") != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Only a PENDING agent may be qualified.")
    if not agent.get("license_number"):
        raise ApiError(ERR_INVALID_STATE, "The agent's licence number must be present.")
    agent["qualification_status"] = "QUALIFIED"
    touch(agent)
    return agent


def suspend_agent(agent_id):
    agent = get_agent(agent_id)
    if agent.get("qualification_status") not in ("PENDING", "QUALIFIED"):
        raise ApiError(ERR_INVALID_STATE, "The agent is already suspended.")

    agent["qualification_status"] = "SUSPENDED"
    touch(agent)

    affected_program_ids = set()
    for referral in db.all("referrals"):
        if referral.get("agent_id") == agent["id"] and referral.get("status") == "OPEN":
            referral["status"] = "VOIDED"
            touch(referral)
            affected_program_ids.add(referral.get("bridge_program_id"))

    recompute_agent_active_referrals(agent)
    touch(agent)
    for program_id in affected_program_ids:
        program = db.get("bridge_programs", program_id)
        if program is not None:
            from services.program import recompute_active_referral_count

            recompute_active_referral_count(program)
            disclosure_service.recompute_program_charge(program)
            touch(program)
    return agent


def reinstate_agent(agent_id, payload):
    agent = get_agent(agent_id)
    data = body_of(payload)
    note = data.get("reinstatement_note")

    if agent.get("qualification_status") != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Only a suspended agent may be reinstated.")
    if not isinstance(note, str) or note.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST, "reinstatement_note is required to reinstate an agent.")

    agent["qualification_status"] = "QUALIFIED"
    touch(agent)
    return agent


def recompute_agent_active_referrals(agent):
    agent["active_referral_count"] = len([
        r for r in db.all("referrals")
        if r.get("agent_id") == agent["id"] and r.get("status") == "OPEN"
    ])
    return agent


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------

def create_referral(payload):
    data = body_of(payload)
    agent_id = get_str(data, "agent_id", required=True)
    program_id = get_str(data, "bridge_program_id", required=True)
    role_scope = get_enum(data, "role_scope", REFERRAL_ROLE_SCOPES, required=True)

    agent = get_agent(agent_id)
    program = get_bridge_program(program_id)

    if agent.get("qualification_status") == "SUSPENDED":
        raise ApiError(ERR_AGENT_NOT_QUALIFIED, "A suspended agent may not receive referrals.")

    for existing in db.all("referrals"):
        if (
            existing.get("bridge_program_id") == program["id"]
            and existing.get("role_scope") == role_scope
            and existing.get("status") == "OPEN"
        ):
            raise ApiError(
                ERR_DUPLICATE_ACTIVE_REFERRAL,
                "This program already holds an active referral for that side of the transaction.",
            )

    referral_rate_bps = get_int(
        data, "referral_rate_bps", required=False, default=int(agent.get("referral_rate_bps") or 0), minimum=0
    )
    qualifying_volume_cents = get_int(
        data,
        "qualifying_volume_cents",
        required=False,
        default=DEFAULT_QUALIFYING_VOLUME_CENTS,
        minimum=0,
    )

    record = {
        "agent_id": agent["id"],
        "bridge_program_id": program["id"],
        "role_scope": role_scope,
        "referral_rate_bps": referral_rate_bps,
        "qualifying_volume_cents": qualifying_volume_cents,
        "status": "OPEN",
        "base_fee_cents": 0,
        "reconciled_fee_cents": 0,
        "fee_variance_cents": 0,
        "completed_at": None,
    }
    create("referrals", record)
    referral_service.refresh_fee_fields(record, agent)

    from services.program import recompute_active_referral_count

    recompute_active_referral_count(program)
    disclosure_service.recompute_program_charge(program)
    touch(program)
    recompute_agent_active_referrals(agent)
    touch(agent)
    return record


def update_referral(referral_id, payload):
    referral = get_referral(referral_id)
    data = body_of(payload)

    if "qualifying_volume_cents" in data and data["qualifying_volume_cents"] is not None:
        referral["qualifying_volume_cents"] = get_int(
            data, "qualifying_volume_cents", required=False, default=0, minimum=0
        )
    if "referral_rate_bps" in data and data["referral_rate_bps"] is not None:
        referral["referral_rate_bps"] = get_int(
            data, "referral_rate_bps", required=False, default=0, minimum=0
        )

    agent = db.get("agents", referral.get("agent_id"))
    referral_service.refresh_fee_fields(referral, agent)
    touch(referral)
    return referral


def complete_referral(referral_id):
    """Close out a referral once its tasks are done and it has volume (PRD 3.7)."""
    referral = get_referral(referral_id)
    if referral.get("status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Only an OPEN referral may be completed.")

    from services.coordination import all_tasks_completed

    if not all_tasks_completed(referral["id"]):
        raise ApiError(ERR_INVALID_STATE, "Every coordination task for this referral must be COMPLETED.")
    if int(referral.get("qualifying_volume_cents") or 0) <= 0:
        raise ApiError(ERR_INVALID_STATE, "The referral's qualifying volume must be greater than zero.")

    referral["status"] = "COMPLETED"
    referral["completed_at"] = format_iso(current_time())
    agent = db.get("agents", referral.get("agent_id"))
    referral_service.refresh_fee_fields(referral, agent)
    touch(referral)

    _refresh_referral_counters(referral, agent)
    _refresh_program_disclosure(referral.get("bridge_program_id"))
    return referral


def void_referral(referral_id):
    """Void an OPEN referral whose agent has been suspended (PRD 3.7)."""
    referral = get_referral(referral_id)
    if referral.get("status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Only an OPEN referral may be voided.")

    agent = db.get("agents", referral.get("agent_id"))
    if agent is None or agent.get("qualification_status") != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "The linked agent is not suspended.")

    referral["status"] = "VOIDED"
    touch(referral)
    # Voiding recomputes the counters but does not touch the fee fields, since
    # no fee was ever earned.
    _refresh_referral_counters(referral, agent)
    return referral


def reopen_referral(referral_id, payload):
    """Reopen a completed referral when new coordination work arrives."""
    referral = get_referral(referral_id)
    data = body_of(payload)

    expected_version = get_int(data, "expected_referral_version", required=True)
    if expected_version != referral["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_referral_version %s does not match the referral's version %s."
            % (expected_version, referral["version"]),
        )

    if referral.get("status") != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, "Only a COMPLETED referral may be reopened.")

    completed_at = referral.get("completed_at")
    new_work = any(
        t.get("referral_id") == referral["id"]
        and completed_at is not None
        and (t.get("created_at") or "") > completed_at
        for t in db.all("coordination_tasks")
    )
    if not new_work:
        raise ApiError(ERR_INVALID_STATE, "No coordination task was created after completion.")

    referral["status"] = "OPEN"
    referral["completed_at"] = None
    touch(referral)
    agent = db.get("agents", referral.get("agent_id"))
    _refresh_referral_counters(referral, agent)
    _refresh_program_disclosure(referral.get("bridge_program_id"))
    return referral


def _refresh_referral_counters(referral, agent):
    from services.program import recompute_active_referral_count

    if agent is not None:
        recompute_agent_active_referrals(agent)
        touch(agent)
    program = db.get("bridge_programs", referral.get("bridge_program_id"))
    if program is not None:
        recompute_active_referral_count(program)
        disclosure_service.recompute_program_charge(program)
        touch(program)


def _refresh_program_disclosure(program_id):
    program = db.get("bridge_programs", program_id)
    if program is not None:
        disclosure_service.recompute_program_charge(program)
        touch(program)