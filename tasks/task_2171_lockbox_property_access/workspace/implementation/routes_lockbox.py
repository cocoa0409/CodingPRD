"""Lockbox intake, reads and the inventory state machine (PRD §3.4, §3.7)."""
from flask import Blueprint

import calc
import serialize
from cascades import create_charge, lockbox_missing_cascade
from core import (
    ADMIN, MEMBER, READ_ROLES, authenticate, body, db, fail, is_int, is_str,
    lookup, new_common, now, ok, ordered, paginate, parse_date, present,
    qfilter, touch,
)
from ladder import (
    assert_not_terminal, assert_owner, assert_transition, assert_version,
    require_action, require_str, require_version_field,
)

bp = Blueprint("lockbox", __name__)

LOCKBOX_ACTIONS = ("ASSIGN", "RETURN", "REPORT_LOST", "REPORT_STOLEN", "RECOVER", "RETIRE")
ADMIN_ONLY_ACTIONS = ("ASSIGN", "RECOVER", "RETIRE")

LOCKBOX_TRANSITIONS = {
    "ASSIGN": ("IN_STOCK", "ASSIGNED"),
    "RETURN": ("ASSIGNED", "QUARANTINE"),
    "REPORT_LOST": ("ASSIGNED", "PLACED"),
    "REPORT_STOLEN": ("ASSIGNED", "PLACED"),
    "RETIRE": ("IN_STOCK", "MISSING", "QUARANTINE"),
}
MODELS = ("LB_STD", "LB_PRO")


@bp.post("/lockboxes")
def create_lockbox():
    authenticate([ADMIN])
    payload = body()
    association = None
    if present(payload, "association_id"):
        association = lookup("associations", payload["association_id"])
    if association is None:
        fail("ERR_INVALID_REQUEST", "association_id is required.")
    require_str(payload, "serial_number")
    if not present(payload, "model") or payload["model"] not in MODELS:
        fail("ERR_INVALID_REQUEST", "model must be one of LB_STD, LB_PRO.")
    if not present(payload, "replacement_cost_cents") or not is_int(payload["replacement_cost_cents"]):
        fail("ERR_INVALID_REQUEST", "replacement_cost_cents is required and must be an integer.")
    if payload["replacement_cost_cents"] <= 0:
        fail("ERR_INVALID_REQUEST", "replacement_cost_cents must be greater than zero.")
    require_str(payload, "in_service_since")
    if parse_date(payload["in_service_since"]) is None:
        fail("ERR_INVALID_REQUEST", "in_service_since must be an ISO date (YYYY-MM-DD).")

    # Rung 15 — uniqueness within the association.
    for existing in db.lockboxes.values():
        if (existing["association_id"] == association["id"]
                and existing["serial_number"] == payload["serial_number"]):
            fail("ERR_DUPLICATE_SERIAL", "serial_number already exists in this association.")

    rec = new_common()
    rec.update({
        "association_id": association["id"],
        "serial_number": payload["serial_number"],
        "model": payload["model"],
        "replacement_cost_cents": payload["replacement_cost_cents"],
        "in_service_since": payload["in_service_since"],
        "status": "IN_STOCK",
        "assigned_member_id": None,
        "current_listing_id": None,
        "loss_type": None,
        "police_report_number": None,
    })
    db.lockboxes[rec["id"]] = rec
    return ok(serialize.lockbox(rec), 201)


@bp.get("/lockboxes/<lockbox_id>")
def read_lockbox(lockbox_id):
    authenticate(READ_ROLES)
    return ok(serialize.lockbox(lookup("lockboxes", lockbox_id)))


@bp.get("/lockboxes")
def list_lockboxes():
    authenticate(READ_ROLES)
    rows = ordered(db.lockboxes)
    rows = qfilter(rows, "association_id")
    rows = qfilter(rows, "assigned_member_id")
    rows = qfilter(rows, "current_listing_id")
    rows = qfilter(rows, "status")
    return paginate(rows, serialize.lockbox)


@bp.post("/lockboxes/<lockbox_id>/state")
def lockbox_state(lockbox_id):
    user_id, role = authenticate([ADMIN, MEMBER])
    payload = body()
    # Rung 2 — action-level role admission.
    raw_action = payload.get("action")
    if is_str(raw_action) and raw_action in ADMIN_ONLY_ACTIONS and role != ADMIN:
        fail("ERR_FORBIDDEN_ROLE", "Only an AssociationAdmin may perform %s." % raw_action)

    lockbox = lookup("lockboxes", lockbox_id)

    # Rung 4 — body foreign keys.
    member = None
    if present(payload, "member_id"):
        member = lookup("members", payload["member_id"])

    # Rung 5 — request shape.
    action = require_action(payload, LOCKBOX_ACTIONS)
    expected = require_version_field(payload, "expected_lockbox_version")
    if action == "ASSIGN" and member is None:
        fail("ERR_INVALID_REQUEST", "member_id is required for ASSIGN.")
    if action == "REPORT_STOLEN":
        require_str(payload, "police_report_number")
    elif action == "REPORT_LOST" and present(payload, "police_report_number"):
        fail("ERR_INVALID_REQUEST", "A plain loss report must not carry a police_report_number.")
    if action == "ASSIGN" and member["association_id"] != lockbox["association_id"]:
        fail("ERR_INVALID_REQUEST", "The member belongs to a different association.")

    # Rung 6 — Member ownership.
    assert_owner(role, user_id, lockbox.get("assigned_member_id"))

    # Rung 8 — optimistic concurrency.
    assert_version(expected, lockbox)

    # Rungs 9 / 11 — terminal lockdown then declared transitions.
    assert_not_terminal("lockbox", lockbox["status"])
    status = lockbox["status"]
    if action == "RECOVER":
        # PRD §3.7: recovery outside MISSING is ERR_RECOVERY_WINDOW_CLOSED (rung 20).
        if status != "MISSING":
            fail("ERR_RECOVERY_WINDOW_CLOSED", "The lockbox is not MISSING.")
    else:
        assert_transition(status, LOCKBOX_TRANSITIONS, action)

    if action == "ASSIGN":
        if status == "ASSIGNED" and lockbox.get("assigned_member_id") == member["id"]:
            fail("ERR_INVALID_STATE", "The lockbox is already assigned to that member.")
        # Rung 10 — referenced member eligibility.
        if member["membership_status"] not in ("ACTIVE", "PROBATION"):
            fail("ERR_MEMBER_NOT_ELIGIBLE", "The receiving member is not in good standing.")
        # Rung 17 — member solvency.
        if calc.member_statement_balance(member["id"]) != 0:
            fail("ERR_MEMBER_BALANCE_DELINQUENT", "The member has an outstanding balance.")
        lockbox["assigned_member_id"] = member["id"]
        lockbox["status"] = "ASSIGNED"

    elif action == "RETURN":
        if status == "ASSIGNED":
            blocked = any(
                p["lockbox_id"] == lockbox_id
                and p["placement_status"] in calc.ACTIVE_PLACEMENT_STATES
                for p in db.placements.values()
            )
            if blocked:
                fail("ERR_INVALID_STATE", "The lockbox still has an active placement.")
            lockbox["assigned_member_id"] = None
            lockbox["status"] = "IN_STOCK"
        else:  # QUARANTINE -> IN_STOCK
            lockbox["loss_type"] = None
            lockbox["police_report_number"] = None
            lockbox["assigned_member_id"] = None
            lockbox["status"] = "IN_STOCK"

    elif action in ("REPORT_LOST", "REPORT_STOLEN"):
        loss_type = "LOST" if action == "REPORT_LOST" else "STOLEN"
        police = payload.get("police_report_number") if loss_type == "STOLEN" else None
        holder_id = lockbox.get("assigned_member_id")
        prior_losses = calc.loss_report_count(holder_id) if holder_id else 0
        amount, variant, basis = calc.replacement_charge_amount(
            lockbox, loss_type, police, prior_losses
        )
        was_placed = status == "PLACED"
        lockbox["status"] = "MISSING"
        lockbox["loss_type"] = loss_type
        lockbox["police_report_number"] = police
        create_charge(
            member_id=holder_id,
            charge_type="REPLACEMENT",
            amount_cents=amount,
            variant_applied=variant,
            basis=basis,
            lockbox_id=lockbox_id,
        )
        if was_placed:
            lockbox_missing_cascade(lockbox)
            lockbox["current_listing_id"] = None

    elif action == "RECOVER":
        for charge in ordered(db.charges):
            if (charge.get("lockbox_id") == lockbox_id
                    and charge["charge_type"] == "REPLACEMENT"
                    and charge["status"] in ("PENDING", "INVOICED")):
                charge["status"] = "VOID"
                touch(charge)
        lockbox["status"] = "QUARANTINE"

    elif action == "RETIRE":
        lockbox["assigned_member_id"] = None
        lockbox["status"] = "RETIRED"

    touch(lockbox)
    return ok(serialize.lockbox(lockbox))
