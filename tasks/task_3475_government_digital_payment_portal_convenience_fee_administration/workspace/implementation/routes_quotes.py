"""Checkout fee quotation (PRD section 3.4). The QUOTED fee variant rates
CARD from CONSUMER_CREDIT regardless of the instrument later presented, and
is disclosure-binding. Quotes expire 30 minutes after creation."""
from flask import Blueprint, request

import clock
import envelope
import fees
import helpers
import serialize
import store
from auth import caller
from errors import invalid_state, raise_err
from validate import as_enum, as_positive_int, as_str, body, req_field

bp = Blueprint("quotes", __name__)


@bp.route("/portal/fee-quotes", methods=["POST"])
def create_quote():
    uid, _role = caller({"Payer"})
    data = body()
    service_id = as_str(req_field(data, "service_id"), "service_id")
    amount = as_positive_int(req_field(data, "amount_cents"), "amount_cents")
    method = as_enum(req_field(data, "method"), "method", {"CARD", "ECHECK", "WALLET"})
    # priority 3: body foreign key, then unknown payer X-User-ID
    svc = helpers.get_service(service_id)
    helpers.require_payer_exists(uid)
    agency = helpers.get_agency(svc["agency_id"])
    # priority 5: state permission
    if svc["status"] != "ACTIVE":
        invalid_state("The service is not ACTIVE")
    if agency["status"] != "ACTIVE":
        raise_err(
            "ERR_AGENCY_NOT_ACTIVE",
            409,
            "Quotation requires the agency in ACTIVE status",
        )
    # priority 6: compliance, then statutory coverage
    if not helpers.pci_current(agency["id"]):
        raise_err(
            "ERR_COMPLIANCE_LAPSED",
            409,
            "Agency lacks a CURRENT PCI_DSS_AOC attestation at the logical clock",
        )
    covering = None
    if svc["fee_model"] == "CONVENIENCE_FEE":
        covering = helpers.covering_authorization(svc["id"])
        if covering is None:
            raise_err(
                "ERR_NO_STATUTORY_COVERAGE",
                422,
                "No in-effect APPROVED statutory authorization covers this service",
            )
    # priority 10: method must be allowed by the service
    if method not in svc["allowed_methods"]:
        raise_err(
            "ERR_METHOD_NOT_ALLOWED",
            409,
            "Method %s is not in the service's allowed_methods" % method,
        )
    # priority 11: amount range, then the statutory fee cap
    if not (svc["min_amount_cents"] <= amount <= svc["max_amount_cents"]):
        raise_err(
            "ERR_AMOUNT_OUT_OF_RANGE",
            422,
            "amount_cents is outside the service's inclusive bounds",
        )
    if svc["fee_model"] == "CONVENIENCE_FEE":
        # QUOTED variant: CARD is always rated CONSUMER_CREDIT
        bucket = "CONSUMER_CREDIT" if method == "CARD" else None
        quoted_fee = fees.convenience_fee(amount, method, bucket)
        if quoted_fee > covering["fee_cap_cents"]:
            # the cap is a hard stop; the fee is never clamped down to it
            raise_err(
                "ERR_FEE_EXCEEDS_STATUTORY_CAP",
                422,
                "Computed convenience fee exceeds the statutory cap",
            )
        payer_total = amount + quoted_fee
    else:
        quoted_fee = 0
        payer_total = amount
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "service_id": svc["id"],
        "payer_id": uid,
        "statutory_authorization_id": covering["id"] if covering else None,
        "amount_cents": amount,
        "method": method,
        "quoted_fee_cents": quoted_fee,
        "payer_total_cents": payer_total,
        "disclosure_text_version": covering["disclosure_text_version"] if covering else None,
        "service_version_pinned": svc["version"],
        "expires_at": clock.add_minutes(now, fees.QUOTE_TTL_MINUTES),
        "status": "OPEN",
        "created_at": now,
        "created_seq": store.next_seq(),
    }
    store.quotes[rec["id"]] = rec
    return envelope.obj(serialize.quote(rec), 201)


@bp.route("/portal/fee-quotes/<rid>", methods=["GET"])
def get_quote(rid):
    uid, role = caller({"PlatformAdmin", "Payer"})
    rec = helpers.get_quote(rid)
    if role == "Payer":
        helpers.require_payer_ownership(uid, rec["payer_id"])
    return envelope.obj(serialize.quote(rec))


@bp.route("/portal/fee-quotes", methods=["GET"])
def list_quotes():
    uid, role = caller({"PlatformAdmin", "AgencyAdmin", "Payer"})
    service_id = request.args.get("service_id")
    payer_id = request.args.get("payer_id")
    authorization_id = request.args.get("statutory_authorization_id")
    items = list(store.quotes.values())
    # a Payer ever sees only records whose payer_id equals its X-User-ID
    if role == "Payer":
        items = [q for q in items if q["payer_id"] == uid]
    if service_id is not None:
        items = [q for q in items if q["service_id"] == service_id]
    if payer_id is not None:
        items = [q for q in items if q["payer_id"] == payer_id]
    if authorization_id is not None:
        items = [q for q in items if q["statutory_authorization_id"] == authorization_id]
    items.sort(key=lambda q: (q["created_at"], q["created_seq"]))
    return envelope.page([serialize.quote(q) for q in items], request.args)
