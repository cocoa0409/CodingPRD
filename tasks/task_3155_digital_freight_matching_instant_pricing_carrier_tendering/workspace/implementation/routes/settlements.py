"""Carrier settlement endpoints: read, unready, payout, clawback."""

from flask import request

from constants import PAYOUT_MODES, utc
from db import clock_now, db, serialize, touch
from errors import ApiError
from middleware import roles_required
from response import array_response, object_response, paginate
from routers import body, require
from services.common import get_carrier, get_settlement, refresh_shipper
from services.settlements import (
    apply_clawback, quick_pay_tier_rate, restrike,
)


def register(app):
    @app.route("/v1/carrier-settlements", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin")
    def list_settlements():
        rows = list(db.settlements.values())
        for field in ("carrier_id", "booking_id", "load_id",
                      "reversal_of_settlement_id", "settlement_status"):
            value = request.args.get(field)
            if value:
                rows = [row for row in rows if row.get(field) == value]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("CarrierSettlement", row) for row in window], pagination)

    @app.route("/v1/carrier-settlements/<settlement_id>", methods=["GET"])
    @roles_required("Carrier", "Shipper", "PlatformAdmin")
    def get_settlement_route(settlement_id):
        return object_response(serialize("CarrierSettlement", get_settlement(settlement_id)))

    @app.route("/v1/carrier-settlements/<settlement_id>/unready", methods=["POST"])
    @roles_required("PlatformAdmin")
    def unready(settlement_id):
        settlement = get_settlement(settlement_id)
        if settlement["settlement_status"] == "PAID":
            raise ApiError("ERR_INVALID_STATE")
        if settlement["settlement_status"] != "READY":
            raise ApiError("ERR_INVALID_STATE")
        settlement["settlement_status"] = "ACCRUED"
        settlement["payout_due_at"] = None
        touch(settlement)
        return object_response(serialize("CarrierSettlement", settlement))

    @app.route("/v1/carrier-settlements/<settlement_id>/payout", methods=["POST"])
    @roles_required("PlatformAdmin")
    def payout(settlement_id):
        payload = body()
        mode = payload.get("payout_mode")
        if mode not in PAYOUT_MODES:
            raise ApiError("ERR_INVALID_REQUEST", "payout_mode must be TERMS or QUICK_PAY.")
        expected = payload.get("expected_settlement_version")
        if expected is None:
            raise ApiError("ERR_INVALID_REQUEST", "expected_settlement_version is required.")
        settlement = get_settlement(settlement_id)

        key = payload.get("retry_idempotency_key")
        if key:
            stored = db.payout_keys.get(settlement["id"])
            if stored is not None and stored["key"] == key:
                return object_response(serialize("CarrierSettlement", settlement))

        # State precedence (validations priority 4) outranks the optimistic
        # concurrency guard (priority 14).
        if settlement["settlement_status"] != "READY":
            raise ApiError("ERR_INVALID_STATE")
        if int(expected) != int(settlement["version"]):
            raise ApiError("ERR_STALE_VERSION")

        now = clock_now()
        due = settlement["payout_due_at"]
        if mode == "TERMS":
            if due is not None and now < utc(due):
                raise ApiError("ERR_SETTLEMENT_NOT_DUE")
        else:
            # QUICK_PAY beats the date; at exactly the due instant both modes are
            # permitted, so only a strictly later instant is refused (PRD 3.9).
            if due is not None and now > utc(due):
                raise ApiError("ERR_SETTLEMENT_NOT_DUE",
                               "QUICK_PAY must beat the due instant.")

        booking = db.bookings.get(settlement["booking_id"])
        if booking is not None and mode == "QUICK_PAY":
            rate = quick_pay_tier_rate(settlement["carrier_id"], now,
                                       exclude_settlement_id=settlement["id"])
            booking["quick_pay_elected"] = True
            restrike(settlement, tier_rate=rate)
            booking["quick_pay_discount_cents"] = settlement["quick_pay_discount_cents"]
            touch(booking)

        settlement["settlement_status"] = "PAID"
        settlement["paid_at"] = now
        touch(settlement)

        if booking is not None:
            booking["settled_at"] = now
            booking["status"] = "SETTLED"
            touch(booking)
            load = db.loads.get(booking["load_id"])
            if load is not None:
                shipper = db.shippers.get(load["shipper_id"])
                if shipper is not None:
                    shipper["credit_used_cents"] -= booking["agreed_rate_cents"]
                    touch(shipper)
                    refresh_shipper(shipper)
                if load["status"] == "INVOICED":
                    load["status"] = "PAID"
                    touch(load)

        if key:
            db.payout_keys[settlement["id"]] = {"key": key, "outcome": settlement["id"]}
        return object_response(serialize("CarrierSettlement", settlement))

    @app.route("/v1/carrier-settlements/<settlement_id>/clawback", methods=["POST"])
    @roles_required("PlatformAdmin")
    def clawback(settlement_id):
        settlement = get_settlement(settlement_id)
        # An approved claim on the booking or load is the guard; with none the
        # answer is ERR_NO_APPROVED_CLAIM (PRD 3.9).
        if settlement["settlement_status"] in ("PAID", "REVERSED"):
            raise ApiError("ERR_INVALID_STATE")
        approved = [claim for claim in db.claims.values()
                    if claim["status"] == "APPROVED"
                    and claim["load_id"] == settlement["load_id"]]
        if not approved:
            raise ApiError("ERR_NO_APPROVED_CLAIM")
        approved.sort(key=lambda row: row["created_at"])
        apply_clawback(settlement, approved[0])
        return object_response(serialize("CarrierSettlement", settlement))