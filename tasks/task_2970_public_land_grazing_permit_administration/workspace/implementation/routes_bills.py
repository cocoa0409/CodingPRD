"""Grazing bills: reading, payment and voiding (PRD 3.6)."""

from flask import Blueprint

import auth
import derive
import envelope
from errors import ApiError
import find
import services
import store
from validate import field, json_body, parse_body

bp = Blueprint("bills", __name__)

PAYMENT_FIELDS = [field("amount_cents", "int", min=0)]
VOID_FIELDS = [field("void_reason", "str", required=False, nullable=True,
                     default=None)]


def bill_state(message):
    raise ApiError("ERR_BILL_STATE_INVALID", message)


@bp.get("/grazing-bills")
def list_bills():
    envelope.page_params()
    actor = auth.any_operational()
    records = envelope.sort_default(store.rows("bills"))
    records = auth.scope_permittee_rows(actor, records,
                                       lambda row: row["permittee_id"])
    records = find.apply_filters(records, [
        ("permittee_id", "permittee_id", "str"),
        ("aoi_id", "aoi_id", "str"),
        ("trespass_incident_id", "trespass_incident_id", "str"),
        ("project_id", "project_id", "str"),
        ("superseded_bill_id", "superseded_bill_id", "str"),
        ("bill_type", "bill_type", "str"),
        ("bill_status", "bill_status", "str"),
    ])
    return envelope.paginate(records, derive.bill_json)


@bp.get("/grazing-bills/<bill_id>")
def get_bill(bill_id):
    actor = auth.any_operational()
    bill = find.need("bills", bill_id)
    auth.require_own(actor, bill["permittee_id"])
    return envelope.ok(derive.bill_json(bill))


@bp.post("/grazing-bills/<bill_id>/payments")
def pay_bill(bill_id):
    body = parse_body(json_body(), PAYMENT_FIELDS)
    actor = auth.authenticate(["Permittee", "AuthorizedOfficer"])
    bill = find.need("bills", bill_id)
    auth.require_own(actor, bill["permittee_id"])
    if bill["bill_status"] not in ("ISSUED", "DELINQUENT"):
        bill_state("only an ISSUED or DELINQUENT bill may receive a payment")
    amount = body["amount_cents"]
    remaining = bill["total_amount_cents"] - bill["amount_paid_cents"]
    if amount < 1 or amount > remaining:
        raise ApiError("ERR_OVERPAYMENT",
                       "the payment exceeds the amount still owed")
    bill["amount_paid_cents"] += amount
    if bill["amount_paid_cents"] >= bill["total_amount_cents"]:
        bill["bill_status"] = "PAID"
    store.touch(bill)
    if bill["bill_status"] == "PAID":
        settle_paid_bill(bill)
    services.refresh_account_status(bill["permittee_id"])
    release_nonpayment_suspensions(bill["permittee_id"])
    return envelope.created(derive.bill_json(bill))


def settle_paid_bill(bill):
    """The first two consequential effects of PRD 3.6."""
    if bill["bill_type"] == "UNAUTHORIZED_USE" and bill["trespass_incident_id"]:
        incident = store.get("trespass_incidents", bill["trespass_incident_id"])
        if incident is not None and incident["incident_status"] == "BILLED":
            incident["incident_status"] = "RESOLVED"
            store.touch(incident)
    if not bill["aoi_id"]:
        return
    aoi = store.get("aois", bill["aoi_id"])
    if aoi is None or aoi["aoi_status"] != "BILLED":
        return
    for other in store.rows("bills"):
        if other["aoi_id"] != aoi["id"]:
            continue
        if other["bill_status"] == "VOIDED":
            continue
        if other["bill_status"] != "PAID":
            return
    aoi["aoi_status"] = "CLOSED"
    store.touch(aoi)


def release_nonpayment_suspensions(permittee_id):
    """The fourth consequential effect of PRD 3.6."""
    if not permittee_id or derive.has_delinquent_bill(permittee_id):
        return
    for permit in store.rows("permits"):
        if permit["permittee_id"] != permittee_id:
            continue
        if permit["permit_status"] == "SUSPENDED" \
                and permit["suspension_reason"] == "NONPAYMENT":
            permit["permit_status"] = "ISSUED"
            permit["suspension_reason"] = None
            store.touch(permit)


@bp.post("/grazing-bills/<bill_id>/void")
def void_bill_route(bill_id):
    body = parse_body(json_body(), VOID_FIELDS)
    auth.authenticate(["AuthorizedOfficer"])
    bill = find.need("bills", bill_id)
    if bill["bill_status"] not in ("ISSUED", "DELINQUENT"):
        bill_state("only an ISSUED or DELINQUENT bill may be voided")
    if bill["amount_paid_cents"] > 0:
        bill_state("a bill that has received money may not be voided")
    services.void_bill(bill, body["void_reason"])
    return envelope.ok(derive.bill_json(bill))
