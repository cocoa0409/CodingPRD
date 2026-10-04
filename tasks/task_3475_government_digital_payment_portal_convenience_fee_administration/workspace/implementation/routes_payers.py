"""Payer registration and payment instruments (PRD section 3.3)."""
import uuid

from flask import Blueprint, request

import clock
import envelope
import helpers
import serialize
import store
from auth import caller
from errors import invalid_request, invalid_state, raise_err
from validate import as_enum, as_str, body, opt_field, req_field

bp = Blueprint("payers", __name__)

CARD_BRANDS = {"VISA", "MASTERCARD", "AMEX", "DISCOVER"}
CARD_BUCKETS = {"CONSUMER_DEBIT", "CONSUMER_CREDIT", "COMMERCIAL"}


@bp.route("/portal/payers", methods=["POST"])
def create_payer():
    caller({"Anonymous", "PlatformAdmin"})
    data = body()
    full_name = as_str(req_field(data, "full_name"), "full_name")
    email = as_str(req_field(data, "email"), "email")
    billing_zip = as_str(req_field(data, "billing_zip"), "billing_zip")
    # priority 8: email unique across all payers
    for p in store.payers.values():
        if p["email"] == email:
            raise_err(
                "ERR_DUPLICATE_PAYER_EMAIL",
                409,
                "email %s is already registered to another payer" % email,
            )
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "full_name": full_name,
        "email": email,
        "billing_zip": billing_zip,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }
    store.payers[rec["id"]] = rec
    return envelope.obj(serialize.payer(rec), 201)


@bp.route("/portal/payers/<rid>", methods=["GET"])
def get_payer(rid):
    uid, role = caller({"PlatformAdmin", "Payer"})
    rec = helpers.get_payer(rid)
    # priority 10: a Payer may read only its own record
    if role == "Payer":
        helpers.require_payer_ownership(uid, rid)
    return envelope.obj(serialize.payer(rec))


@bp.route("/portal/payers/<rid>/instruments", methods=["POST"])
def create_instrument(rid):
    uid, role = caller({"Payer", "PlatformAdmin"})
    payer = helpers.get_payer(rid)
    data = body()
    method = as_enum(req_field(data, "method"), "method", {"CARD", "ECHECK", "WALLET"})
    last4 = as_str(req_field(data, "last4"), "last4")
    card_brand = opt_field(data, "card_brand")
    card_bucket = opt_field(data, "card_cost_bucket")
    # card fields required iff method == CARD, forbidden otherwise
    if method == "CARD":
        if card_brand is None or card_bucket is None:
            invalid_request(
                "card_brand and card_cost_bucket are required for CARD instruments"
            )
        card_brand = as_enum(card_brand, "card_brand", CARD_BRANDS)
        card_bucket = as_enum(card_bucket, "card_cost_bucket", CARD_BUCKETS)
    else:
        if card_brand is not None or card_bucket is not None:
            invalid_request(
                "card_brand and card_cost_bucket are forbidden on non-CARD instruments"
            )
    # priority 3 then 10: an unknown payer X-User-ID reports
    # ERR_PAYER_NOT_FOUND before the ownership check; a Payer must own the
    # payer named in the path; PlatformAdmin bypasses both
    if role == "Payer":
        helpers.require_payer_exists(uid)
        helpers.require_payer_ownership(uid, payer["id"])
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "payer_id": payer["id"],
        "method": method,
        "card_brand": card_brand,
        "card_cost_bucket": card_bucket,
        "last4": last4,
        "token_ref": "tok_" + uuid.uuid4().hex,
        "status": "PENDING_VERIFICATION" if method == "ECHECK" else "ACTIVE",
        "ach_verify_failures": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }
    store.instruments[rec["id"]] = rec
    return envelope.obj(serialize.instrument(rec), 201)


@bp.route("/portal/payers/<rid>/instruments", methods=["GET"])
def list_instruments(rid):
    uid, role = caller({"PlatformAdmin", "Payer"})
    helpers.get_payer(rid)
    if role == "Payer":
        helpers.require_payer_ownership(uid, rid)
    items = [i for i in store.instruments.values() if i["payer_id"] == rid]
    items.sort(key=lambda i: (i["created_at"], i["created_seq"]))
    return envelope.page([serialize.instrument(i) for i in items], request.args)


@bp.route("/portal/instruments/<rid>/verify-ach", methods=["POST"])
def verify_ach(rid):
    uid, role = caller({"Payer", "PlatformAdmin"})
    inst = helpers.get_instrument(rid)
    data = body()
    outcome = as_enum(req_field(data, "outcome"), "outcome", {"SUCCESS", "FAILURE"})
    # priority 5: state permission (method ECHECK, still pending)
    if inst["method"] != "ECHECK":
        invalid_state("Micro-deposit verification applies only to ECHECK instruments")
    if inst["status"] != "PENDING_VERIFICATION":
        invalid_state(
            "Instrument in status %s accepts no further verification reports"
            % inst["status"]
        )
    # priority 10: payer ownership (PlatformAdmin bypasses)
    if role == "Payer":
        helpers.require_payer_exists(uid)
        helpers.require_payer_ownership(uid, inst["payer_id"])
    if outcome == "SUCCESS":
        inst["status"] = "ACTIVE"
    else:
        inst["ach_verify_failures"] += 1
        if inst["ach_verify_failures"] >= 3:
            # the failure that brings the count to 3 deactivates the instrument
            inst["ach_verify_failures"] = 3
            inst["status"] = "DEACTIVATED"
    helpers.touch(inst)
    return envelope.obj(serialize.instrument(inst))
