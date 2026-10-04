"""Payment transactions (PRD sections 3.4 and 3.6): authorize against a
quote, capture, void, ACH return / re-presentment cycle, nested refund and
chargeback listings."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import envelope
import fees
import helpers
import serialize
import store
from auth import caller
from errors import invalid_state, raise_err
from validate import as_str, body, req_field

bp = Blueprint("transactions", __name__)

TXN_READ_ROLES = {"PlatformAdmin", "AgencyAdmin", "TreasuryOfficer", "Payer"}


@bp.route("/portal/payment-transactions", methods=["POST"])
def authorize():
    uid, _role = caller({"Payer"})
    data = body()
    quote_id = as_str(req_field(data, "quote_id"), "quote_id")
    instrument_id = as_str(req_field(data, "instrument_id"), "instrument_id")
    # priority 3: body foreign keys in declared input order, then the payer
    quote = helpers.get_quote(quote_id)
    inst = helpers.get_instrument(instrument_id)
    helpers.require_payer_exists(uid)
    svc = helpers.get_service(quote["service_id"])
    agency = helpers.get_agency(svc["agency_id"])
    # priority 5: the quote must still be OPEN
    if quote["status"] != "OPEN":
        invalid_state("The quote is %s and cannot be authorized" % quote["status"])
    # priority 6: the agency's attestation must still be CURRENT
    if not helpers.pci_current(agency["id"]):
        raise_err(
            "ERR_COMPLIANCE_LAPSED",
            409,
            "Agency lacks a CURRENT PCI_DSS_AOC attestation at the logical clock",
        )
    # priority 9: quote expiry (clock equal to or later than expires_at)
    if clock.now() >= quote["expires_at"]:
        raise_err("ERR_QUOTE_EXPIRED", 409, "The quote has expired")
    # priority 10: ownership, instrument usability, method match, version pin
    if quote["payer_id"] != uid or inst["payer_id"] != uid:
        raise_err(
            "ERR_NOT_RESOURCE_OWNER",
            403,
            "Payer %s must own both the quote and the instrument" % uid,
        )
    if inst["status"] != "ACTIVE":
        raise_err(
            "ERR_INSTRUMENT_NOT_USABLE",
            409,
            "Instrument in status %s cannot authorize" % inst["status"],
        )
    if inst["method"] != quote["method"] or quote["method"] not in svc["allowed_methods"]:
        raise_err(
            "ERR_METHOD_NOT_ALLOWED",
            409,
            "Instrument method does not match the quote or the service's "
            "allowed methods",
        )
    if svc["version"] != quote["service_version_pinned"]:
        raise_err(
            "ERR_STALE_SERVICE_VERSION",
            409,
            "The service has been repriced since the quote was created",
        )
    # FINAL variant: rated from the instrument's actual card cost bucket; also
    # the portal's processing-cost accrual. The disclosure-binding charge is
    # the QUOTED fee recorded on the quote.
    if svc["fee_model"] == "ABSORBED":
        final_fee = 0
    else:
        bucket = inst["card_cost_bucket"] if inst["method"] == "CARD" else None
        final_fee = fees.convenience_fee(quote["amount_cents"], inst["method"], bucket)
    charged_fee = quote["quoted_fee_cents"]
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "quote_id": quote["id"],
        "instrument_id": inst["id"],
        "service_id": svc["id"],
        "agency_id": agency["id"],
        "payer_id": uid,
        "current_batch_id": None,
        "method": quote["method"],
        "fee_model": svc["fee_model"],
        "amount_cents": quote["amount_cents"],
        "charged_fee_cents": charged_fee,
        "final_fee_cents": final_fee,
        "payer_total_cents": quote["amount_cents"] + charged_fee,
        "funds_status": "AUTHORIZED",
        "representment_count": 0,
        "captured_at": None,
        "value_date": None,
        "returned_at": None,
        "refunded_cents": 0,
        "charged_back_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }
    store.transactions[rec["id"]] = rec
    quote["status"] = "CONSUMED"
    return envelope.obj(serialize.transaction(rec), 201)


@bp.route("/portal/payment-transactions/<rid>", methods=["GET"])
def get_transaction(rid):
    uid, role = caller(TXN_READ_ROLES)
    rec = helpers.get_transaction(rid)
    if role == "Payer":
        helpers.require_payer_ownership(uid, rec["payer_id"])
    return envelope.obj(serialize.transaction(rec))


@bp.route("/portal/payment-transactions", methods=["GET"])
def list_transactions():
    uid, role = caller(TXN_READ_ROLES)
    filters = {}
    for key in (
        "agency_id",
        "service_id",
        "payer_id",
        "instrument_id",
        "quote_id",
        "current_batch_id",
        "funds_status",
    ):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    items = list(store.transactions.values())
    if role == "Payer":
        items = [t for t in items if t["payer_id"] == uid]
    for key, v in filters.items():
        items = [t for t in items if t.get(key) == v]
    items.sort(key=lambda t: (t["created_at"], t["created_seq"]))
    return envelope.page([serialize.transaction(t) for t in items], request.args)


@bp.route("/portal/payment-transactions/<rid>/capture", methods=["POST"])
def capture(rid):
    caller({"AgencyAdmin", "PlatformAdmin"})
    rec = helpers.get_transaction(rid)
    if rec["funds_status"] != "AUTHORIZED":
        invalid_state(
            "Only an AUTHORIZED transaction can be captured (status %s)"
            % rec["funds_status"]
        )
    now = clock.now()
    rec["funds_status"] = "CAPTURED"
    rec["captured_at"] = now
    lag = fees.METHOD_LAG_DAYS[rec["method"]]
    rec["value_date"] = (now.date() + timedelta(days=lag)).isoformat()
    helpers.touch(rec)
    return envelope.obj(serialize.transaction(rec))


@bp.route("/portal/payment-transactions/<rid>/void", methods=["POST"])
def void(rid):
    caller({"AgencyAdmin", "PlatformAdmin"})
    rec = helpers.get_transaction(rid)
    if rec["funds_status"] != "AUTHORIZED":
        invalid_state(
            "Only an AUTHORIZED transaction can be voided (status %s)"
            % rec["funds_status"]
        )
    rec["funds_status"] = "VOIDED"
    helpers.touch(rec)
    return envelope.obj(serialize.transaction(rec))


@bp.route("/portal/payment-transactions/<rid>/ach-return", methods=["POST"])
def ach_return(rid):
    caller({"PlatformAdmin"})
    rec = helpers.get_transaction(rid)
    # priority 5: state permission
    if rec["funds_status"] not in ("SETTLED", "RE_PRESENTED"):
        invalid_state(
            "Only a SETTLED or RE_PRESENTED transaction can be returned "
            "(status %s)" % rec["funds_status"]
        )
    # priority 8: method-specific legality
    if rec["method"] != "ECHECK":
        raise_err(
            "ERR_RETURN_NOT_PERMITTED",
            409,
            "ACH returns apply only to ECHECK transactions",
        )
    rec["funds_status"] = "RETURNED"
    rec["returned_at"] = clock.now()
    rec["current_batch_id"] = None
    helpers.touch(rec)
    # Cascade: return debit of amount_cents into the agency's OPEN batch,
    # auto-created for the clock date when none exists. The withheld
    # convenience fee is neither returned to the payer nor clawed back.
    batch = helpers.ensure_open_batch(rec["agency_id"])
    batch["return_debits_cents"] += rec["amount_cents"]
    helpers.touch(batch)
    return envelope.obj(serialize.transaction(rec))


@bp.route("/portal/payment-transactions/<rid>/re-present", methods=["POST"])
def re_present(rid):
    caller({"AgencyAdmin"})
    rec = helpers.get_transaction(rid)
    if rec["funds_status"] != "RETURNED":
        invalid_state(
            "Only a RETURNED transaction can be re-presented (status %s)"
            % rec["funds_status"]
        )
    # priority 8: re-presentment count limit
    if rec["representment_count"] != 0:
        raise_err(
            "ERR_REPRESENTMENT_EXHAUSTED",
            409,
            "The transaction has already been re-presented once",
        )
    # priority 9: within thirty days of the return
    if clock.now() > rec["returned_at"] + timedelta(days=30):
        raise_err(
            "ERR_REPRESENTMENT_WINDOW_CLOSED",
            409,
            "More than 30 days have passed since the return",
        )
    rec["funds_status"] = "RE_PRESENTED"
    rec["representment_count"] = 1
    rec["value_date"] = (
        clock.now().date() + timedelta(days=fees.METHOD_LAG_DAYS["ECHECK"])
    ).isoformat()
    helpers.touch(rec)
    return envelope.obj(serialize.transaction(rec))


@bp.route("/portal/payment-transactions/<rid>/refunds", methods=["GET"])
def list_refunds(rid):
    uid, role = caller(TXN_READ_ROLES)
    rec = helpers.get_transaction(rid)
    if role == "Payer":
        helpers.require_payer_ownership(uid, rec["payer_id"])
    items = [r for r in store.refunds.values() if r["transaction_id"] == rid]
    items.sort(key=lambda r: (r["created_at"], r["created_seq"]))
    return envelope.page([serialize.refund(r) for r in items], request.args)


@bp.route("/portal/payment-transactions/<rid>/chargebacks", methods=["GET"])
def list_chargebacks(rid):
    uid, role = caller(TXN_READ_ROLES)
    rec = helpers.get_transaction(rid)
    if role == "Payer":
        helpers.require_payer_ownership(uid, rec["payer_id"])
    items = [c for c in store.chargebacks.values() if c["transaction_id"] == rid]
    items.sort(key=lambda c: (c["created_at"], c["created_seq"]))
    return envelope.page([serialize.chargeback(c) for c in items], request.args)
