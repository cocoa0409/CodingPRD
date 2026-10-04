"""Shipper commitments and capacity — PRD §3.2, endpoints 85-89."""

from decimal import Decimal

import db
import services
import calculations as calc
from core import ApiError, D, now_iso
from response import ok, page_of
from http_util import pagination, must_get, body, coerce_int, coerce_num
from routes._common import route
from models import create

PUBLIC = ["shipper_name", "shipper_floor_per_mile_cents",
          "reserved_window_start_epoch_day", "reserved_window_end_epoch_day",
          "committed_slots"]


def register(app):

    @route(app, "/api/shipper-commitments", ["POST"], ["ShipperPartnershipManager"])
    def create_commitment():
        """§3.2: the commitment registers with commitment_status DRAFT,
        consumed_slots of 0 and remaining_slots equal to committed_slots; it may
        hold no fewer than 1 and no more than 50 slots."""
        raw = body()
        for key in raw:
            if key not in PUBLIC:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in PUBLIC:
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        slots = coerce_int(raw["committed_slots"])
        if slots < 1 or slots > 50:
            raise ApiError("ERR_INVALID_REQUEST",
                           "committed_slots must be no fewer than 1 and no more than 50.")
        start = coerce_int(raw["reserved_window_start_epoch_day"])
        end = coerce_int(raw["reserved_window_end_epoch_day"])
        if not end > start:
            raise ApiError("ERR_INVALID_REQUEST",
                           "reserved_window_end_epoch_day must be strictly after the start.")
        row = create("ShipperCommitment", {
            "shipper_name": raw["shipper_name"],
            "shipper_floor_per_mile_cents": coerce_num(raw["shipper_floor_per_mile_cents"]),
            "reserved_window_start_epoch_day": start,
            "reserved_window_end_epoch_day": end,
            "committed_slots": slots,
        })
        row["commitment_status"] = "DRAFT"
        row["consumed_slots"] = 0
        row["remaining_slots"] = slots
        row["ride_along_credit_cents"] = D(0)
        row["billed_ride_along_cents"] = D(0)
        row["verified_ride_along_count"] = 0
        services.recompute_commitment(row)
        services.flush(row)
        return ok(row, 201)

    @route(app, "/api/shipper-commitments", ["GET"], ["Any"])
    def list_commitments():
        limit, offset = pagination()
        return page_of(db.sort_created(db.all_rows("shipper_commitments")), limit, offset)

    @route(app, "/api/shipper-commitments/<rid>", ["GET"], ["Any"])
    def get_commitment(rid):
        return ok(must_get("ShipperCommitment", rid))

    @route(app, "/api/shipper-commitments/<rid>/confirm", ["POST"],
           ["ShipperPartnershipManager"])
    def confirm_commitment(rid):
        """§3.2: a draft commitment can be confirmed outright."""
        row = must_get("ShipperCommitment", rid)
        raw = body()
        for key in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
        if row.get("commitment_status") != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Only a draft commitment can be confirmed.")
        services.mark(row, "commitment_status", "CONFIRMED")
        services.flush(row)
        return ok(row)

    @route(app, "/api/shipper-commitments/<rid>/revoke", ["POST"],
           ["ShipperPartnershipManager"])
    def revoke_commitment(rid):
        """§3.2: revoking a commitment that is CONFIRMED or SHIPPED moves the whole
        of ride_along_credit_cents into billed_ride_along_cents and recomputes
        ride_along_credit_cents to 0, so the sum of the two readings is
        conserved."""
        row = must_get("ShipperCommitment", rid)
        raw = body()
        for key in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
        if row.get("commitment_status") not in ("CONFIRMED", "SHIPPED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Only a CONFIRMED or SHIPPED commitment can be revoked.")
        credit = D(row.get("ride_along_credit_cents", 0))
        services.mark(row, "billed_ride_along_cents",
                      D(row.get("billed_ride_along_cents", 0)) + credit)
        services.mark(row, "ride_along_credit_cents", D(0))
        services.mark(row, "commitment_status", "REVOKED")
        services.flush(row)
        return ok(row)