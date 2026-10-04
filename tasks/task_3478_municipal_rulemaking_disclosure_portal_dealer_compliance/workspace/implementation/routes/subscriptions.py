"""Data subscription lifecycle, fee computation, and licensed data feeds."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import serializers
import services
import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_ORG_NOT_FOUND,
    ERR_ORG_SUSPENDED,
    ERR_PRODUCT_NOT_LICENSED,
    ERR_SUBSCRIPTION_NOT_FOUND,
)
from respond import ok, ok_list
from validators import (
    get_body,
    paginate,
    req_enum,
    req_int,
    req_str,
    require_auth,
    require_role,
    _bad,
)

bp = Blueprint("subscriptions", __name__)

PRODUCT_CODES = ("TRADE_REALTIME", "TRADE_HISTORICAL", "DISCLOSURE_ARCHIVE")
LICENSE_SCOPES = ("INTERNAL", "DISPLAY", "REDISTRIBUTION")
SUBSCRIPTION_READ_ROLES = ("LicensingOfficer", "ComplianceOfficer")

# calculations.subscription_monthly_fee constants.
BASE_CENTS = {
    "TRADE_REALTIME": 250000,
    "TRADE_HISTORICAL": 99999,
    "DISCLOSURE_ARCHIVE": 150000,
}
PER_SEAT_CENTS = {
    "TRADE_REALTIME": 5000,
    "TRADE_HISTORICAL": 2500,
    "DISCLOSURE_ARCHIVE": 1000,
}
INCLUDED_SEATS = {
    "TRADE_REALTIME": 5,
    "TRADE_HISTORICAL": 10,
    "DISCLOSURE_ARCHIVE": 20,
}
SCOPE_MULTIPLIER = {
    "INTERNAL": Decimal("1.0"),
    "DISPLAY": Decimal("1.5"),
    "REDISTRIBUTION": Decimal("2.25"),
}
ORG_TYPE_DISCOUNT = {
    "ISSUER": Decimal("1.0"),
    "OBLIGATED_PERSON": Decimal("1.0"),
    "BROKER_DEALER": Decimal("1.0"),
    "MUNICIPAL_ADVISOR": Decimal("0.9"),
}
MONTHS_PER_YEAR = 12


def _monthly_fee_cents(product_code, license_scope, seats, org_type):
    """Exactly one round_half_up, applied at the end of the formula."""
    billable_seats = max(seats - INCLUDED_SEATS[product_code], 0)
    unrounded = (
        Decimal(BASE_CENTS[product_code])
        + Decimal(billable_seats) * Decimal(PER_SEAT_CENTS[product_code])
    ) * SCOPE_MULTIPLIER[license_scope] * ORG_TYPE_DISCOUNT[org_type]
    return int(unrounded.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@bp.route("/msrb/data-subscriptions", methods=["POST"])
def create_subscription():
    _uid, role = require_auth()
    require_role(role, ("LicensingOfficer",))
    body = get_body()
    product_code = req_enum(body, "product_code", PRODUCT_CODES)
    licensee_org_id = req_str(body, "licensee_org_id")
    subscriber_principal = req_str(body, "subscriber_principal")
    license_scope = req_enum(body, "license_scope", LICENSE_SCOPES)
    seats = req_int(body, "seats")
    if seats < 1:
        raise _bad("seats must be >= 1.")
    org = store.organizations.get(licensee_org_id)
    if org is None:
        raise ApiError(ERR_ORG_NOT_FOUND, "licensee_org_id does not exist.", 404)
    if org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, "The licensee organization is SUSPENDED.", 409)
    monthly_fee_cents = _monthly_fee_cents(
        product_code, license_scope, seats, org["org_type"]
    )
    # Round-per-line then sum: the identical monthly line is already rounded.
    annual_invoice_cents = MONTHS_PER_YEAR * monthly_fee_cents
    now = store.now()
    subscription = {
        "id": store.new_id(),
        "product_code": product_code,
        "licensee_org_id": licensee_org_id,
        "subscriber_principal": subscriber_principal,
        "license_scope": license_scope,
        "seats": seats,
        "status": "PENDING",
        "monthly_fee_cents": monthly_fee_cents,
        "annual_invoice_cents": annual_invoice_cents,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.data_subscriptions[subscription["id"]] = subscription
    return ok(serializers.data_subscription(subscription), 201)


@bp.route("/msrb/data-subscriptions", methods=["GET"])
def list_subscriptions():
    _uid, role = require_auth()
    require_role(role, SUBSCRIPTION_READ_ROLES)
    items = list(store.data_subscriptions.values())
    licensee_filter = request.args.get("licensee_org_id")
    if licensee_filter is not None:
        items = [s for s in items if s["licensee_org_id"] == licensee_filter]
    product_filter = request.args.get("product_code")
    if product_filter is not None:
        items = [s for s in items if s["product_code"] == product_filter]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return ok_list(
        [serializers.data_subscription(s) for s in page], limit, offset, total
    )


@bp.route("/msrb/data-subscriptions/<subscription_id>", methods=["GET"])
def get_subscription(subscription_id):
    _uid, role = require_auth()
    require_role(role, SUBSCRIPTION_READ_ROLES)
    subscription = store.data_subscriptions.get(subscription_id)
    if subscription is None:
        raise ApiError(ERR_SUBSCRIPTION_NOT_FOUND, "Data subscription not found.", 404)
    return ok(serializers.data_subscription(subscription), 200)


@bp.route("/msrb/data-subscriptions/<subscription_id>/transition", methods=["POST"])
def transition_subscription(subscription_id):
    _uid, role = require_auth()
    require_role(role, ("LicensingOfficer",))
    body = get_body()
    to_state = req_str(body, "to_state")
    # REJECTED is system-only (compliance cascade); any other non-target is an
    # invalid input enum member. Both are refused as ERR_INVALID_REQUEST.
    if to_state not in ("ACTIVE", "TERMINATED"):
        raise _bad("to_state must be one of ['ACTIVE', 'TERMINATED'].")
    subscription = store.data_subscriptions.get(subscription_id)
    if subscription is None:
        raise ApiError(ERR_SUBSCRIPTION_NOT_FOUND, "Data subscription not found.", 404)
    current = subscription["status"]
    if current == "PENDING" and to_state == "ACTIVE":
        org = store.organizations.get(subscription["licensee_org_id"])
        if org is not None and org["status"] != "ACTIVE":
            raise ApiError(
                ERR_ORG_SUSPENDED, "The licensee organization is SUSPENDED.", 409
            )
        subscription["status"] = "ACTIVE"
    elif current in ("PENDING", "ACTIVE") and to_state == "TERMINATED":
        subscription["status"] = "TERMINATED"
    else:
        raise ApiError(
            ERR_INVALID_STATE,
            "Subscription cannot advance from %s to %s." % (current, to_state),
            409,
        )
    services.bump(subscription)
    return ok(serializers.data_subscription(subscription), 200)


@bp.route("/msrb/data-feeds/<product_code>", methods=["GET"])
def get_data_feed(product_code):
    uid, role = require_auth()
    require_role(role, ("MarketDataSubscriber",))
    # An unrecognized product code is an invalid enum member (schema failure).
    if product_code not in PRODUCT_CODES:
        raise _bad("product_code must be one of %s." % sorted(PRODUCT_CODES))
    # Last check in the validation order: product licensing.
    subscription = None
    for candidate in store.data_subscriptions.values():
        if (
            candidate["product_code"] == product_code
            and candidate["status"] == "ACTIVE"
            and candidate["subscriber_principal"] == uid
            and (
                subscription is None
                or candidate["created_at"] < subscription["created_at"]
            )
        ):
            subscription = candidate
    if subscription is None:
        raise ApiError(
            ERR_PRODUCT_NOT_LICENSED,
            "No ACTIVE subscription for this product with subscriber_principal == X-User-ID.",
            403,
        )
    if product_code in ("TRADE_REALTIME", "TRADE_HISTORICAL"):
        record_count = sum(
            1 for t in store.trade_reports.values() if t["status"] == "DISSEMINATED"
        )
    else:
        record_count = sum(
            1
            for s in store.disclosure_submissions.values()
            if s["status"] == "PUBLISHED"
        )
    return ok(
        {
            "product_code": product_code,
            "subscription_id": subscription["id"],
            "record_count": record_count,
        },
        200,
    )
