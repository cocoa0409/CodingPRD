"""Agent lifecycle: licensing, book transition, cessation and reassignment."""

import clock
import db
import middleware
import occ
from errors import (
    ApiError, ERR_AGENCY_STAFFING_CAP, ERR_AGENT_NOT_FOUND, ERR_HOLDING_POLICIES_REMAIN,
    ERR_INVALID_STATE, ERR_LICENSED_REQUIRED, ERR_NO_SUCCESSOR_AGENT,
)
from money import dec
from services import calculations as calc
from services import factories, recompute

TERMINAL = ("TERMINATED",)


def list_agents(request, role=None, user_id=None):
    rows = list(db.agent_rows().values())
    if role == "AgencyPrincipal":
        rows = [a for a in rows if a.get("agency_id") == user_id]
    rows = middleware.filter_by(rows, {
        "status": request.args.get("status"),
        "state_code": request.args.get("state_code"),
        "agency_id": request.args.get("agency_id"),
    })
    rows.sort(key=lambda a: a["created_at"])
    return rows


def read_license(agent, payload):
    """Read the state board's record: upsert a LicenseRecord, mark the agent
    LICENSED, refresh its expiry, stamp the agreement's license_verified_at."""
    expiry = payload.get("license_expiry_date")
    for existing in db.license_rows().values():
        if existing["agent_id"] == agent["id"]:
            existing["license_expiry_date"] = expiry
            existing["product_lines"] = payload.get("product_lines") or existing["product_lines"]
    record = factories.create_license_record({
        "agent_id": agent["id"],
        "full_name": payload.get("full_name") or agent.get("full_name"),
        "state_code": payload.get("state_code") or agent.get("state_code"),
        "product_lines": payload.get("product_lines") or [],
        "license_expiry_date": expiry,
    })
    agent["license_expiry_date"] = expiry
    agent["license_status"] = "LICENSED" if not _expired(expiry) else "EXPIRED"
    recompute.touch(agent)

    now = clock.iso()
    for agreement in db.agreement_rows().values():
        if agreement["agent_id"] == agent["id"] and agreement.get("license_verified_at") is None:
            agreement["license_verified_at"] = now
            recompute.touch(agreement)
    return agent, record


def _expired(expiry):
    if not expiry:
        return False
    return clock.parse_iso(expiry) < clock.now()


def licensed(agent):
    """Every appointment / book-transition duty requires LICENSED (PRD §2.10)."""
    recompute.refresh_license_status(agent["id"])
    if agent["license_status"] != "LICENSED":
        raise ApiError(ERR_LICENSED_REQUIRED)


def transition_book(agent, target_agency, expected_version):
    occ.check(agent, expected_version, "expected_agent_version")

    if agent["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agent["status"] != "APPOINTED":
        raise ApiError(ERR_INVALID_STATE)

    licensed(agent)
    if not agent.get("is_new_agent"):
        raise ApiError(ERR_INVALID_STATE)
    if target_agency["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE)
    if calc.agency_level_units(target_agency["id"]) >= calc.AGENCY_UNIT_CAP:
        raise ApiError(ERR_AGENCY_STAFFING_CAP)

    agent["agency_id"] = target_agency["id"]
    agent["status"] = "TRANSITIONING"
    recompute.touch(agent)

    target_agency["agency_level_units"] = calc.agency_level_units(target_agency["id"])
    recompute.touch(target_agency)
    return agent


def cessation(agent, payload):
    if agent["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agent["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE)

    licensed(agent)

    now = clock.now()
    agency = db.agency_rows().get(agent.get("agency_id"))
    agreement = _active_agreement(agent)

    for record in db.agreement_rows().values():
        if record["agent_id"] == agent["id"] and record["status"] == "ACTIVE":
            record["termination_initiated_at"] = clock.iso()
            record["status"] = "SUSPENDED"
            recompute.touch(record)
            agreement = record

    agent["status"] = "PENDING_TERMINATION"
    recompute.touch(agent)

    if agreement is not None and agency is not None:
        bonus = calc.cessation_bonus_cents(agency["id"], agreement["created_at"], now)
        agreement["termination_value_cents"] = calc.contract_value_cents(
            agency, agent.get("appointment_date"), bonus, now)
        recompute.touch(agreement)
    return agent


def _active_agreement(agent):
    rows = [a for a in db.agreement_rows().values()
            if a["agent_id"] == agent["id"]]
    rows.sort(key=lambda a: a["created_at"], reverse=True)
    return rows[0] if rows else None


def reassign_policy(ceasing_agent, policy, successor_agent_id):
    """Reassign one OPEN policy held by the ceasing agent to a successor."""
    if policy["holder_agent_id"] != ceasing_agent["id"]:
        raise ApiError(ERR_INVALID_STATE)
    if policy["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)

    successor = db.agent_rows().get(successor_agent_id)
    if successor is None:
        raise ApiError(ERR_AGENT_NOT_FOUND)

    transfer = _ensure_transfer(ceasing_agent, successor)

    policy["holder_agent_id"] = successor["id"]
    policy["owner_agency_id"] = successor.get("agency_id")
    policy["book_transfer_id"] = transfer["id"]
    # first_written_at is preserved: the original tie-break key survives transfer.
    recompute.touch(policy)

    transfer["to_agency_id"] = successor.get("agency_id")
    transfer["successor_agent_id"] = successor["id"]
    recompute.recompute_book_transfer(transfer["id"])
    return policy


def _ensure_transfer(ceasing_agent, successor):
    """The moving book is recorded as a BookTransfer; one is opened on the first
    policy move when the client has not posted one explicitly."""
    transfer = _transfer_for(ceasing_agent)
    if transfer is None:
        transfer = factories.create_book_transfer({
            "agent_id": ceasing_agent["id"],
            "from_agency_id": ceasing_agent.get("agency_id"),
            "to_agency_id": successor.get("agency_id"),
        })
    return transfer


def _transfer_for(agent):
    rows = [t for t in db.transfer_rows().values() if t["agent_id"] == agent["id"]]
    rows.sort(key=lambda t: t["created_at"], reverse=True)
    return rows[0] if rows else None


def complete_reassignment(agent):
    if agent["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")

    # The ops sweep performs PENDING_TERMINATION -> TRANSITIONING once a
    # same-region candidate agency exists (PRD §3.7).  A finalization that
    # arrives before that sweep performs the promotion here so the reassignment
    # reaches its declared end state.
    if agent["status"] == "PENDING_TERMINATION" and _promotable(agent):
        agent["status"] = "TRANSITIONING"
        recompute.touch(agent)

    if agent["status"] != "TRANSITIONING":
        raise ApiError(ERR_INVALID_STATE)

    # Finalization recomputes the successor selection; when the same-region
    # ACTIVE candidate set is empty the selection refuses (PRD §3.7).
    select_successor(agent)

    open_policies = [p for p in db.policy_rows().values()
                     if p["holder_agent_id"] == agent["id"] and p["status"] == "OPEN"]
    if open_policies:
        raise ApiError(ERR_HOLDING_POLICIES_REMAIN)

    transfer = _transfer_for(agent)
    if transfer is not None:
        transfer["successor_agent_id"] = transfer.get("successor_agent_id") or \
            _last_successor(agent)
        transfer["status"] = "SETTLED"
        recompute.recompute_book_transfer(transfer["id"])

    agent["status"] = "TERMINATED"
    recompute.touch(agent)

    agency_id = agent.get("agency_id")
    if agency_id:
        agency = db.agency_rows().get(agency_id)
        if agency is not None:
            agency["agency_level_units"] = calc.agency_level_units(agency_id)
            recompute.touch(agency)
    return agent


def _last_successor(agent):
    for policy in db.policy_rows().values():
        if policy.get("book_transfer_id") is None:
            continue
        transfer = db.transfer_rows().get(policy["book_transfer_id"])
        if transfer is None or transfer["agent_id"] != agent["id"]:
            continue
        if policy["holder_agent_id"] != agent["id"]:
            return policy["holder_agent_id"]
    return None


def _promotable(agent):
    """A same-region ACTIVE agency below the unit cap exists (PRD §3.7)."""
    from services import ops
    agency = db.agency_rows().get(agent.get("agency_id"))
    if agency is None:
        return False
    return bool(ops._target_agencies(agency, exclude_agency_id=agency["id"]))


def select_successor(ceasing_agent):
    candidates = calc.successor_candidates(ceasing_agent, db.agency_rows())
    if not candidates:
        raise ApiError(ERR_NO_SUCCESSOR_AGENT)
    return candidates[0]


def staff_for_agent(agent, request):
    rows = middleware.filter_by(list(db.staff_rows().values()),
                                {"allocated_agent_id": agent["id"]})
    rows = middleware.filter_by(rows, {"status": request.args.get("status")})
    rows.sort(key=lambda s: s["created_at"])
    return rows