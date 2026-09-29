"""Compliance actions, the cure and the bond-draw default cascade — PRD 3.9."""
import calc
from auth import ALL_ROLES, fetch, guard
from envelope import created, listing, ok
from errors import ApiError
from logic import (bond_of, clear_deficiency, lease_of, recompute_outstanding,
                   unwind_live_children)
from router import route
from shape import body, opt_str, ref, req_enum, req_instant, req_int, req_str
from store import db, insert, now, parse_iso_instant, touch

ACTION_TYPES = ("FEE_DELINQUENCY", "OPERATING_STANDARD", "INSURANCE_LAPSE")
NOTICE_LEASE_STATES = ("ACTIVE", "HOLDOVER")
BOND_DRAWABLE = ("ACTIVE", "PARTIALLY_DRAWN")


@route("/compliance-actions", methods=["POST"])
def compliance_create():
    guard("ContractingOfficer")
    data = body()
    lease = None
    lease_ref = ref(data, "lease_id")
    if lease_ref is not None:
        lease = fetch(db.leases, lease_ref, "ERR_LEASE_NOT_FOUND")
    reconciliation_ref = ref(data, "reconciliation_id")
    if reconciliation_ref is not None:
        reconciliation = fetch(db.reconciliations, reconciliation_ref,
                               "ERR_RECONCILIATION_NOT_FOUND")
        if lease is None or reconciliation["lease_id"] != lease["id"]:
            raise ApiError("ERR_RECONCILIATION_NOT_FOUND",
                           "The reconciliation does not belong to this lease")
    row = {
        "lease_id": req_str(data, "lease_id"),
        "reconciliation_id": opt_str(data, "reconciliation_id"),
        "action_type": req_enum(data, "action_type", ACTION_TYPES),
        "origin": "AGENCY_ISSUED",
        "deficiency_note": req_str(data, "deficiency_note"),
        "cure_deadline": req_instant(data, "cure_deadline")[0],
        "cure_note": None,
        "draw_amount_cents": None,
        "status": "NOTICE_ISSUED",
    }
    if lease["contract_status"] not in NOTICE_LEASE_STATES:
        raise ApiError("ERR_LEASE_STATUS_INVALID",
                       "Lease contract_status %s cannot receive a notice"
                       % lease["contract_status"])
    action = insert(db.compliance_actions, row)
    if lease["compliance_status"] == "COMPLIANT":
        lease["compliance_status"] = "DEFICIENT"
        touch(lease)
    return created(action)


@route("/compliance-actions/<action_id>/accept-cure", methods=["POST"])
def compliance_accept_cure(action_id):
    guard("ContractingOfficer")
    action = fetch(db.compliance_actions, action_id, "ERR_COMPLIANCE_ACTION_NOT_FOUND")
    data = body()
    note = req_str(data, "cure_note")
    if action["status"] != "NOTICE_ISSUED":
        raise ApiError("ERR_COMPLIANCE_ACTION_STATUS_INVALID",
                       "Compliance action status %s cannot accept a cure" % action["status"])
    action["cure_note"] = note
    action["status"] = "CURE_ACCEPTED"
    touch(action)
    lease = lease_of(action)
    if lease is not None:
        clear_deficiency(lease)
    return ok(action)


@route("/compliance-actions/<action_id>/order-bond-draw", methods=["POST"])
def compliance_order_bond_draw(action_id):
    guard("ContractingOfficer")
    action = fetch(db.compliance_actions, action_id, "ERR_COMPLIANCE_ACTION_NOT_FOUND")
    data = body()
    amount = req_int(data, "draw_amount_cents")
    if action["status"] != "NOTICE_ISSUED":
        raise ApiError("ERR_COMPLIANCE_ACTION_STATUS_INVALID",
                       "Compliance action status %s cannot order a draw" % action["status"])
    lease = lease_of(action)
    bond = bond_of(lease) if lease is not None else None
    if bond is None or bond["status"] not in BOND_DRAWABLE:
        raise ApiError("ERR_BOND_NOT_ACTIVE", "The performance bond cannot be drawn")
    deadline = parse_iso_instant(action["cure_deadline"])
    if deadline is not None and not now() > deadline:
        raise ApiError("ERR_CURE_PERIOD_OPEN", "The cure period is still open")
    if amount > bond["available_balance_cents"]:
        raise ApiError("ERR_DRAW_EXCEEDS_BOND",
                       "The draw exceeds the bond's available balance")
    # Hop one — record the draw on the notice.
    action["draw_amount_cents"] = amount
    action["status"] = "BOND_DRAW_ORDERED"
    touch(action)
    # Hop two — move the money on the bond; the penal sum never changes.
    bond["available_balance_cents"] = bond["available_balance_cents"] - amount
    bond["drawn_total_cents"] = bond["drawn_total_cents"] + amount
    floor = calc.bond_sufficiency_floor(bond["required_amount_cents"])
    if bond["available_balance_cents"] >= floor:
        bond["status"] = "PARTIALLY_DRAWN"
    else:
        bond["status"] = "INSUFFICIENT"
    touch(bond)
    # Hop three — the declared default, both dimensions at once.
    terminated = False
    if bond["status"] == "INSUFFICIENT":
        if lease["compliance_status"] == "DEFICIENT":
            lease["compliance_status"] = "DEFAULT"
            touch(lease)
        if lease["contract_status"] in NOTICE_LEASE_STATES:
            lease["contract_status"] = "TERMINATED_DEFAULT"
            touch(lease)
            terminated = True
    # Hop four — unwind the terminated lease's live children.
    if terminated:
        unwind_live_children(lease)
    # Regardless of where the bond landed, an exact-amount draw pays the invoice.
    if action["reconciliation_id"]:
        reconciliation = db.reconciliations.get(action["reconciliation_id"])
        if (reconciliation is not None
                and reconciliation["status"] == "PENDING_PAYMENT"
                and amount == reconciliation["additional_fee_due_cents"]):
            reconciliation["status"] = "SETTLED"
            touch(reconciliation)
            recompute_outstanding(lease)
    return ok(action)


@route("/compliance-actions", methods=["GET"])
def compliance_list():
    guard(*ALL_ROLES)
    return listing(db.compliance_actions, ("lease_id", "reconciliation_id", "status", "origin"))


@route("/compliance-actions/<action_id>", methods=["GET"])
def compliance_read(action_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.compliance_actions, action_id, "ERR_COMPLIANCE_ACTION_NOT_FOUND"))
