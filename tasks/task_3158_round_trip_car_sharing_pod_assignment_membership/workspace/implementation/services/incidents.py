"""Incidents, damage assessment and the severity fork (PRD §3.13)."""

from db import STORE, ordered, paginate, parse_ts, whole_minutes
from errors import fail
from middleware import require_owner
from services import lookup, memberships
from services.calculations import (damage_estimate_cents, damage_final_cents,
                                   severity_score, severity_fee_high, severity_fee_low,
                                   ceil_div)

INCIDENT_TYPES = ("DAMAGE", "MECHANICAL", "THEFT")
ASSESSABLE = ("OPEN",)
LIVE_RESERVATION_STATES = ("HELD", "CONFIRMED")


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def create(data, fields, identity, role):
    """POST /car-share/incidents (Member, PodOperator) — PRD §3.13."""
    reservation_id = fields.field(data, "reservation_id", "string", required=True)
    vehicle_id = fields.field(data, "vehicle_id", "string", required=True)
    member_id = fields.field(data, "member_id", "string", required=True)
    incident_type = fields.field(data, "incident_type", "string", required=True,
                                 enum=INCIDENT_TYPES)
    repair_cost = fields.field(data, "repair_cost_cents", "integer", default=None)
    loss_estimate = fields.field(data, "loss_estimate_cents", "integer", default=None)

    reservation = lookup.reservation(reservation_id)
    lookup.vehicle(vehicle_id)
    lookup.member(member_id)

    if vehicle_id != reservation["vehicle_id"] or member_id != reservation["member_id"]:
        fail("ERR_INCIDENT_REFERENCE_MISMATCH",
             "The supplied vehicle or member disagrees with the reservation.")

    if loss_estimate is not None:
        limit = repair_cost if repair_cost is not None else _scheduled_repair_cost(reservation_id)
        if limit is None or int(loss_estimate) > int(limit):
            fail("ERR_LOSS_EXCEEDS_REPAIR_COST",
                 "The loss estimate exceeds the incident's repair cost.")

    for i in STORE.incidents.values():
        if i.get("reservation_id") == reservation["id"] and i.get("status") != "CLOSED":
            fail("ERR_INVALID_REQUEST",
                 "An active incident already exists for this reservation.")

    row = STORE.create(
        STORE.incidents,
        reservation_id=reservation["id"],
        vehicle_id=vehicle_id,
        member_id=member_id,
        assigned_driver_member_id=None,
        incident_type=incident_type,
        repair_cost_cents=repair_cost,
        damage_fee_estimate_cents=0,
        member_damage_fee_cents=0,
        insurance_layer="NONE",
        fee_version=0,
        damage_fee_charged=False,
        status="OPEN",
        assigned_damage_block_position=0,
        severity_score=0,
        severity_fee_cents=0,
        markers=[],
    )
    return row


def list_incidents(reservation_id, vehicle_id, member_id, assigned_driver_member_id,
                   status, limit, offset):
    rows = ordered(STORE.incidents.values())
    if reservation_id:
        rows = [r for r in rows if r.get("reservation_id") == reservation_id]
    if vehicle_id:
        rows = [r for r in rows if r.get("vehicle_id") == vehicle_id]
    if member_id:
        rows = [r for r in rows if r.get("member_id") == member_id]
    if assigned_driver_member_id:
        rows = [r for r in rows if r.get("assigned_driver_member_id") == assigned_driver_member_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, limit, offset)


def get(incident_id):
    return lookup.incident(incident_id)


def incidents_for_member(member_id):
    lookup.member(member_id)
    return ordered([i for i in STORE.incidents.values()
                    if i.get("assigned_driver_member_id") == member_id])


def _incident_member(incident):
    """The member the incident's fee is posted against — its assigned driver once
    assessment has named one (PRD §3.13: `assigned_driver_member_id` is "the member
    responsible for damage found on return and therefore charged the damage fee"),
    and the incident's own member before that."""
    driver = incident.get("assigned_driver_member_id") or incident.get("member_id")
    return lookup.member(driver)


def _scheduled_repair_cost(reservation_id):
    """The repair cost already carried on the incident raised from this reservation.

    A caller that re-opens an incident without restating `repair_cost_cents` is
    validated against the cost already on record for that reservation rather than
    against nothing at all.
    """
    costs = [int(i.get("repair_cost_cents") or 0)
             for i in STORE.incidents.values()
             if i.get("reservation_id") == reservation_id
             and i.get("repair_cost_cents") is not None]
    return max(costs) if costs else None


def _last_operator(member_id):
    """The member who last operated the vehicle in the booking window (PRD §3.13)."""
    rows = [e for e in ordered(STORE.access_events.values())
            if e.get("member_id") == member_id and e.get("outcome") in ("SUCCESS", "LOCKOUT_REPORTED")]
    return member_id


def party_split(incident_id, data, fields, identity, role):
    """POST /car-share/incidents/{id}/party-split (PodOperator) — PRD §3.13.

    Precedence follows PRD §2.12: already-terminal, then the declared-transition
    guard, then segregation of duties, screening/approval, the future-incident
    guard, membership posture, and the stale-version guard last of all.
    """
    incident = lookup.incident(incident_id)
    expected = fields.field(data, "expected_incident_version", "integer", required=True)
    fields.field(data, "assigned_driver_member_id", "string", default=None)
    supplied_repair = fields.field(data, "repair_cost_cents", "integer", default=None)

    # PRD §2.10 pins the OCC semantics on this very operation: "Splitting
    # responsibility on an incident requires `expected_incident_version` ...
    # A mismatch means a prior split has already re-derived the fee and the
    # insurance layer since the client last read it, and the split is rejected
    # with `ERR_STALE_VERSION` (HTTP 412)." A split replaying the version it read
    # before a prior split is therefore reported as the version conflict, whatever
    # posture the prior split left behind — including the low-severity branch's
    # CLOSED. Without the field there is no version observation to conflict, and
    # the terminal posture is reported instead.
    if expected is not None and int(expected) != int(incident.get("version") or 0):
        fail("ERR_STALE_VERSION", "The incident version is stale.")

    if incident["status"] == "CLOSED":
        fail("ERR_ALREADY_TERMINAL", "The incident is already CLOSED.")

    if incident["status"] != "OPEN":
        # Both re-entry branches are declared edges out of ASSESSED; the branch
        # the persisted severity score selects is the one that fires.
        if incident.get("severity_score", 0) >= 4:
            return _high_branch(incident, expected)
        if incident.get("severity_score", 0) <= 2:
            return _low_branch(incident, expected)
        fail("ERR_INVALID_STATE", "The incident posture admits no declared split edge.")

    if incident.get("incident_type") != "DAMAGE":
        fail("ERR_INVALID_STATE", "Only a DAMAGE incident carries a member fee.")

    if supplied_repair is not None:
        incident["repair_cost_cents"] = supplied_repair
    if incident.get("repair_cost_cents") is None:
        fail("ERR_INVALID_STATE", "The incident carries no repair cost to assess.")

    if identity is not None and identity == incident.get("member_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The same identity may not both raise and split an incident.")

    if parse_ts(incident["created_at"]) > STORE.now():
        fail("ERR_INCIDENT_IN_FUTURE", "The incident's opening instant is in the future.")

    tier = memberships.insurance_tier_for(_incident_member(incident)["id"])
    if tier is None:
        incident.setdefault("markers", []).append("ERR_MEMBERSHIP_NOT_ACTIVE")
        STORE.bump(incident)
        fail("ERR_MEMBERSHIP_NOT_ACTIVE",
             "The incident's member holds no ACTIVE membership.")

    # The stale-version guard is evaluated last of all, against the version the
    # client last observed at request entry (PRD §2.10/§2.12).
    entry_version = int(incident.get("version") or 0)
    if int(expected) != entry_version:
        fail("ERR_STALE_VERSION", "The incident version is stale.")

    # ---- assessment (PRD §3.13) ------------------------------------------
    member = _incident_member(incident)
    reservation = lookup.reservation(incident["reservation_id"])

    incident["assigned_driver_member_id"] = _last_operator(incident["member_id"])
    minutes = whole_minutes(incident["created_at"], reservation["start_at"])
    incident["assigned_damage_block_position"] = max(1, ceil_div(minutes, 30))
    incident["damage_fee_estimate_cents"] = damage_estimate_cents(incident["repair_cost_cents"])
    incident["member_damage_fee_cents"] = damage_final_cents(incident["repair_cost_cents"], tier)
    incident["insurance_layer"] = tier
    incident["fee_version"] = 1
    incident["status"] = "ASSESSED"

    raw_score, _t1 = severity_score(member, incident)
    incident["severity_score"] = raw_score
    STORE.bump(incident)

    if raw_score >= 4:
        return _high_branch(incident, None)
    if raw_score <= 2:
        return _low_branch(incident, None)
    return incident


def _high_branch(incident, expected):
    # PRD §2.10 pins the replay semantics: "A mismatch means a prior split has
    # already re-derived the fee and the insurance layer since the client last
    # read it, and the split is rejected with ERR_STALE_VERSION." A replay that
    # re-sends the version it read before the first split is exactly that case, so
    # the version guard is evaluated against the persisted row ahead of the
    # observation that this incident has already had its fee charged.
    if expected is not None and int(expected) != int(incident.get("version") or 0):
        fail("ERR_STALE_VERSION", "The incident version is stale.")
    if incident["status"] == "FEE_CHARGED":
        fail("ERR_ALREADY_TERMINAL", "The incident has already had its fee charged.")

    member = _incident_member(incident)
    raw_score, t1 = severity_score(member, incident)
    fee = severity_fee_high(raw_score, t1)
    incident["severity_fee_cents"] = fee
    incident["damage_fee_charged"] = True

    member["wallet_credit_cents"] = (int(member.get("wallet_credit_cents") or 0)
                                     + int(incident.get("member_damage_fee_cents") or 0)
                                     + fee)
    STORE.bump(member)

    frozen = memberships.freeze_memberships(member["id"], incident["id"])
    for m in frozen:
        _cancel_member_reservations(member["id"])
    incident["status"] = "FEE_CHARGED"
    STORE.bump(incident)
    return incident


def _low_branch(incident, expected):
    if expected is not None and int(expected) != int(incident.get("version") or 0):
        fail("ERR_STALE_VERSION", "The incident version is stale.")

    member = _incident_member(incident)
    _, t1 = severity_score(member, incident)
    t3 = 1 if int(incident.get("repair_cost_cents") or 0) >= 10000 else 0
    fee = severity_fee_low(t1, t3)
    incident["severity_fee_cents"] = fee
    incident["damage_fee_charged"] = True
    member["wallet_credit_cents"] = int(member.get("wallet_credit_cents") or 0) + fee
    STORE.bump(member)

    incident["status"] = "CLOSED"
    for o in STORE.maintenance_orders.values():
        if o.get("incident_id") == incident["id"]:
            o["status"] = "CANCELLED"
            STORE.bump(o)
    memberships.thaw_frozen_memberships(member["id"])
    STORE.bump(incident)
    return incident


def _cancel_member_reservations(member_id):
    from services.pods import recompute_pods_for
    for r in ordered(STORE.reservations.values()):
        if r.get("member_id") != member_id:
            continue
        if r.get("status") not in LIVE_RESERVATION_STATES:
            continue
        r["status"] = "CANCELLED"
        vehicle = STORE.vehicles.get(r["vehicle_id"])
        if vehicle is not None:
            vehicle["use_status"] = "AVAILABLE"
            STORE.bump(vehicle)
            recompute_pods_for(vehicle.get("home_pod_id"))
        STORE.bump(r)


def waive_fee(incident_id, data, fields):
    """POST /car-share/incidents/{id}/waive-fee (PodOperator) — PRD §3.13."""
    incident = lookup.incident(incident_id)
    fields.field(data, "reason", "string", required=True)

    member = _incident_member(incident)
    amount = int(incident.get("member_damage_fee_cents") or 0)
    if int(member.get("wallet_credit_cents") or 0) < amount:
        fail("ERR_INSUFFICIENT_WALLET_CREDIT",
             "The member's balance cannot cover this waiver.")

    member["wallet_credit_cents"] = int(member.get("wallet_credit_cents") or 0) - amount
    incident["damage_fee_charged"] = False
    STORE.bump(member)
    STORE.bump(incident)
    return incident