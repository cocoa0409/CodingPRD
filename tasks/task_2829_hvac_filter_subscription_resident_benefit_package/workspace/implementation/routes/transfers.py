"""Mid-lease address change: the transfer workflow and cascade C (PRD 3.8)."""
from flask import Blueprint

import calc
import clock
import envelope
import guards
import ledger
import services
import validate
import views
from errors import fail
from routes.subscriptions import build_subscription, new_entitlement
from store import base_record, db, sorted_rows, touch

bp = Blueprint("transfers", __name__)

TRANSFER_STATUSES = ("REQUESTED", "SKU_REMAPPED", "COMPLETED", "REJECTED",
                     "SUPERSEDED")
OPEN_TRANSFER_STATUSES = ("REQUESTED", "SKU_REMAPPED")


def transfers_of(subscription_id):
    return sorted_rows([t for t in db.transfers.values()
                        if t["subscription_id"] == subscription_id])


@bp.post("/subscription-transfers")
def open_transfer():
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    body = validate.json_body()
    # rung 3: body foreign keys in declaration order
    sub = guards.get_subscription(body.get("subscription_id"))
    dest_unit = guards.get_unit(body.get("to_unit_id"))
    guards.own_subscription(uid, role, sub)
    effective_date = validate.req_date(body, "effective_date")
    expected_version = validate.req_int(body, "expected_subscription_version")
    if expected_version != sub["version"]:
        fail("ERR_STALE_SUBSCRIPTION_VERSION",
             "expected_subscription_version does not match the subscription")
    if sub["status"] != "ACTIVE":
        fail("ERR_SUBSCRIPTION_STATE_INVALID", "the subscription is not ACTIVE")

    lease_start = clock.parse_date(sub["lease_start_date"])
    lease_end = clock.parse_date(sub["lease_end_date"])
    # rung 22 precedes rungs 25 and 26 on the ladder of 2.10. The moving
    # subscription is excluded from its own occupancy test.
    if calc.occupancy_conflict(dest_unit["id"], lease_start, lease_end,
                              ignore_subscription_ids=(sub["id"],)):
        fail("ERR_UNIT_OCCUPANCY_CONFLICT",
             "the destination unit cannot accommodate the incoming lease")
    if (effective_date < clock.today() or effective_date < lease_start
            or effective_date > lease_end):
        fail("ERR_TRANSFER_DATE_INVALID",
             "the effective date is outside the permitted range")
    if dest_unit["id"] == sub["unit_id"] or dest_unit["status"] != "AVAILABLE":
        fail("ERR_TRANSFER_TARGET_INVALID",
             "the destination must be a different AVAILABLE unit")

    rec = base_record()
    rec["subscription_id"] = sub["id"]
    rec["to_unit_id"] = dest_unit["id"]
    rec["effective_date"] = clock.fmt_date(effective_date)
    rec["remapped_sku_id"] = None
    rec["proration_credit_cents"] = 0
    rec["proration_charge_cents"] = 0
    rec["net_adjustment_cents"] = 0
    rec["successor_subscription_id"] = None
    rec["rejection_reason"] = None
    rec["status"] = "REQUESTED"
    db.transfers[rec["id"]] = rec

    for other in transfers_of(sub["id"]):
        if other["id"] != rec["id"] and other["status"] in OPEN_TRANSFER_STATUSES:
            other["status"] = "SUPERSEDED"
            touch(other)
    sub["status"] = "TRANSFER_PENDING"
    touch(sub)
    return envelope.object_response(views.transfer_view(rec), 201)


@bp.get("/subscription-transfers/<transfer_id>")
def read_transfer(transfer_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    rec = guards.get_transfer(transfer_id)
    guards.own_subscription(uid, role, db.subscriptions[rec["subscription_id"]])
    return envelope.object_response(views.transfer_view(rec))


@bp.get("/subscription-transfers")
def list_transfers():
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    limit, offset, filters = guards.pagination(
        {"status": TRANSFER_STATUSES},
        ("subscription_id", "to_unit_id", "remapped_sku_id",
         "successor_subscription_id"))
    rows = [t for t in db.transfers.values()
            if all(t[k] == v for k, v in filters.items())]
    if role == "PropertyManager":
        rows = [t for t in rows
                if db.subscriptions[t["subscription_id"]]["property_id"] == uid]
    rows = sorted_rows(rows)
    return envelope.list_response([views.transfer_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


@bp.post("/subscription-transfers/<transfer_id>/remap-sku")
def remap_sku(transfer_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_transfer(transfer_id)
    if rec["status"] != "REQUESTED":
        fail("ERR_TRANSFER_STATE_INVALID", "the transfer is not REQUESTED")

    sub = db.subscriptions[rec["subscription_id"]]
    dest_unit = db.units[rec["to_unit_id"]]
    resident = db.residents[sub["resident_id"]]
    # rung 20 sits above rung 26 on the ladder of 2.10.
    sku = calc.select_sku(dest_unit, resident)
    if dest_unit["status"] != "AVAILABLE":
        fail("ERR_TRANSFER_TARGET_INVALID",
             "the destination unit is no longer AVAILABLE")

    rec["remapped_sku_id"] = sku["id"]
    rec["status"] = "SKU_REMAPPED"
    touch(rec)
    return envelope.object_response(views.transfer_view(rec))


@bp.post("/subscription-transfers/<transfer_id>/reject")
def reject(transfer_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    rec = guards.get_transfer(transfer_id)
    sub = db.subscriptions[rec["subscription_id"]]
    guards.own_subscription(uid, role, sub)
    body = validate.json_body()
    reason = validate.req_text(body, "rejection_reason")
    if rec["status"] not in OPEN_TRANSFER_STATUSES:
        fail("ERR_TRANSFER_STATE_INVALID", "the transfer is already resolved")

    rec["rejection_reason"] = reason
    rec["status"] = "REJECTED"
    touch(rec)
    sub["status"] = "ACTIVE"
    touch(sub)
    return envelope.object_response(views.transfer_view(rec))


@bp.post("/subscription-transfers/<transfer_id>/complete")
def complete(transfer_id):
    """Cascade C: one atomic step that mints the successor, cancels the
    outgoing leg without settling it, and books a single net ledger row."""
    guards.auth(["ProgramOperator"])
    rec = guards.get_transfer(transfer_id)
    sub = db.subscriptions[rec["subscription_id"]]
    dest_unit = db.units[rec["to_unit_id"]]
    dest_prop = db.properties[dest_unit["property_id"]]
    if dest_prop["status"] != "ACTIVE":
        fail("ERR_PROPERTY_NOT_ACTIVE",
             "the property owning the destination unit is not ACTIVE")
    if rec["status"] != "SKU_REMAPPED":
        fail("ERR_TRANSFER_STATE_INVALID", "the transfer is not SKU_REMAPPED")
    if sub["status"] != "TRANSFER_PENDING":
        fail("ERR_TRANSFER_STATE_INVALID",
             "the outgoing subscription is not TRANSFER_PENDING")

    # The successor is priced before any money is computed: cadence, filters per
    # shipment, benefit set and monthly fee against the destination unit, with
    # the SKU already fixed as remapped_sku_id (PRD 3.8).
    resident = db.residents[sub["resident_id"]]
    sku = db.skus[rec["remapped_sku_id"]]
    cadence = calc.ship_cadence_days(dest_unit, sku, resident)
    quantity = calc.filters_per_shipment(dest_unit, sku)
    codes = calc.benefit_codes(dest_prop, sub["billing_party"], "UNVERIFIED")
    priced = {
        "assigned_sku_id": sku["id"],
        "ship_cadence_days": cadence,
        "filters_per_shipment": quantity,
        "entitled_benefit_codes": codes,
        "monthly_fee_cents": calc.monthly_fee_cents(sku, quantity, cadence, codes),
    }

    effective_date = clock.parse_date(rec["effective_date"])
    proration = calc.transfer_proration(sub["monthly_fee_cents"],
                                        priced["monthly_fee_cents"],
                                        effective_date)
    ledger.check_credit_ceiling(dest_prop, sub["billing_party"],
                               proration["net_adjustment_cents"])

    successor = build_subscription(
        resident, dest_unit, dest_prop, sub["billing_party"],
        sub["enrollment_channel"], sub["lease_start_date"],
        sub["lease_end_date"], priced, predecessor_id=sub["id"], status="ACTIVE")
    successor["activated_at"] = clock.now_iso()
    for code in successor["entitled_benefit_codes"]:
        row = new_entitlement(successor, code)
        row["state"] = "ACTIVE"
        row["effective_from"] = clock.now_iso()

    rec["proration_credit_cents"] = proration["proration_credit_cents"]
    rec["proration_charge_cents"] = proration["proration_charge_cents"]
    rec["net_adjustment_cents"] = proration["net_adjustment_cents"]
    rec["successor_subscription_id"] = successor["id"]
    rec["status"] = "COMPLETED"
    touch(rec)

    # The outgoing leg is cancelled but deliberately NOT settled: the transfer
    # proration replaces the settlement of 3.9 entirely.
    sub["status"] = "CANCELLED"
    sub["cancel_effective_date"] = rec["effective_date"]
    sub["cancel_reason"] = "TRANSFER_SUPERSEDED"
    touch(sub)
    services.cancel_scheduled_shipments(sub)
    services.expire_entitlements(sub, "TRANSFER_SUPERSEDED")

    ledger.post_one_off(successor, "TRANSFER_ADJUSTMENT",
                        proration["net_adjustment_cents"],
                        "transfer proration net adjustment", rec["id"],
                        on_date=effective_date)

    services.occupy_unit(dest_unit["id"])
    services.release_unit_if_free(sub["unit_id"])
    return envelope.object_response(views.transfer_view(rec))
