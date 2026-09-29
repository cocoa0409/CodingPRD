"""Dealers: certification, version-carrying renewals, suspension with its
shipment hold, and reinstatement (PRD 3.9).
"""

from flask import Blueprint

import serializers as ser
from cascades import hold_shipments_for_suspension
from core import (
    CERTIFICATION_CATEGORIES,
    ROLE_AUTHORITY,
    ROLE_DEALER,
    ROLE_OPERATOR,
    apply_changes,
    at_or_after_today,
    authenticate,
    clock,
    db,
    envelope_object,
    f_date,
    f_enum,
    f_int,
    f_str,
    get_dealer,
    invalid,
    json_body,
    stamp_new,
)
from errors import ApiError

bp = Blueprint("dealers", __name__)


@bp.route("/dealers", methods=["POST"])
def certify_dealer():
    authenticate([ROLE_AUTHORITY])
    body = json_body()
    name = f_str(body, "name")
    state_code = f_str(body, "state_code", pattern=r"^[A-Z]{2}$", min_len=2, max_len=2)
    category = f_enum(body, "certification_category", CERTIFICATION_CATEGORIES)
    certification_no = f_str(body, "certification_no")
    certified_through = f_date(body, "certified_through")
    dealer = {
        "name": name,
        "state_code": state_code,
        "certification_category": category,
        "certification_no": certification_no,
        "certified_through": certified_through,
        "icssl_listed_through": None,
        "listing_status": "NOT_LISTED",
        "recall_strike_count": 0,
        "suspension_reason": None,
    }
    stamp_new(dealer)
    db.dealers[dealer["id"]] = dealer
    return envelope_object(ser.dealer(dealer)), 201


@bp.route("/dealers/<dealer_id>", methods=["GET"])
def read_dealer(dealer_id):
    authenticate([ROLE_AUTHORITY, ROLE_DEALER, ROLE_OPERATOR])
    dealer = get_dealer(dealer_id)
    return envelope_object(ser.dealer(dealer)), 200


@bp.route("/dealers/<dealer_id>/certification-renewals", methods=["POST"])
def renew_certification(dealer_id):
    authenticate([ROLE_AUTHORITY])
    dealer = get_dealer(dealer_id)
    body = json_body()
    expected_version = f_int(body, "expected_dealer_version")
    certified_through = f_date(body, "certified_through")
    icssl_listed_through = f_date(
        body, "icssl_listed_through", required=False, default=None
    )
    # Rung 5 — a renewal must extend the certification into the future.
    if certified_through <= clock.today():
        raise invalid(
            "Field 'certified_through' must be strictly after the current date."
        )
    if icssl_listed_through is not None and icssl_listed_through > certified_through:
        raise invalid(
            "Field 'icssl_listed_through' must be at or before 'certified_through'."
        )
    # Rung 6 — optimistic concurrency (PRD 2.8).
    if expected_version != dealer["version"]:
        raise ApiError("ERR_STALE_DEALER_VERSION")

    changes = {"certified_through": certified_through}
    if icssl_listed_through is not None:
        changes["icssl_listed_through"] = icssl_listed_through
        # The listing dimension moves only on the first listing.
        if dealer["listing_status"] == "NOT_LISTED":
            changes["listing_status"] = "LISTED"
    apply_changes(dealer, changes)
    return envelope_object(ser.dealer(dealer)), 200


@bp.route("/dealers/<dealer_id>/suspend", methods=["POST"])
def suspend_dealer(dealer_id):
    authenticate([ROLE_AUTHORITY])
    dealer = get_dealer(dealer_id)
    body = json_body()
    f_str(body, "suspension_note", required=False, default=None)

    # Rung 7 — only a listed dealer may be suspended.
    if dealer["listing_status"] != "LISTED":
        raise ApiError("ERR_INVALID_DEALER_LISTING_STATE")

    apply_changes(
        dealer,
        {"listing_status": "SUSPENDED", "suspension_reason": "AUTHORITY_ACTION"},
    )
    hold_shipments_for_suspension(dealer)
    return envelope_object(ser.dealer(dealer)), 200


@bp.route("/dealers/<dealer_id>/reinstate", methods=["POST"])
def reinstate_dealer(dealer_id):
    authenticate([ROLE_AUTHORITY])
    dealer = get_dealer(dealer_id)
    body = json_body()
    icssl_listed_through = f_date(
        body, "icssl_listed_through", required=False, default=None
    )

    # Rung 7 — only a suspended dealer may be reinstated.
    if dealer["listing_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_DEALER_LISTING_STATE")
    # Rung 13 — the certification must still be current.
    if not at_or_after_today(dealer["certified_through"]):
        raise ApiError("ERR_DEALER_CERTIFICATION_EXPIRED")

    changes = {"listing_status": "LISTED", "suspension_reason": None}
    if icssl_listed_through is not None:
        changes["icssl_listed_through"] = icssl_listed_through
    apply_changes(dealer, changes)
    # Reinstatement releases no hold and resets no strike.
    return envelope_object(ser.dealer(dealer)), 200
