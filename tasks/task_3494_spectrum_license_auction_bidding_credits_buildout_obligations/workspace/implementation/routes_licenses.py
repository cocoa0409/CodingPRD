"""Licenses: registry reads and settlement payments with grant side effects
(PRD §3.6, §3.7)."""
from flask import Blueprint, request

import store
import calcs
import serializers
from errors import ApiError, success
from helpers import (auth, require_role, body, req_present, as_int,
                     get_or_404, paginate, touch)

bp = Blueprint("licenses", __name__)


@bp.route("/spectrum-auctions/licenses", methods=["GET"])
def list_licenses():
    auth()
    items = list(store.DB["licenses"].values())
    for param, field in (("auction_id", "auction_id"), ("area_id", "area_id"),
                         ("holder_applicant_id", "holder_applicant_id"),
                         ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            items = [l for l in items if l[field] == value]
    page, meta = paginate(items)
    return success([serializers.license_(l) for l in page], 200, meta)


@bp.route("/spectrum-auctions/licenses/<lid>", methods=["GET"])
def get_license(lid):
    auth()
    return success(serializers.license_(get_or_404("licenses", lid)), 200)


@bp.route("/spectrum-auctions/licenses/<lid>/settlement-payments",
          methods=["POST"])
def pay_settlement(lid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    b = body()
    raw_amount = req_present(b, "amount_cents")
    if isinstance(raw_amount, bool) or not isinstance(raw_amount, int):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "amount_cents must be an integer")
    license_ = get_or_404("licenses", lid)
    if uid != license_["holder_applicant_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                       "X-User-ID must equal the license holder")
    if license_["status"] != "PENDING_PAYMENT":
        raise ApiError("ERR_LICENSE_INVALID_STATE", 409,
                       "Settlement requires PENDING_PAYMENT")
    remaining = license_["net_price_cents"] - license_["paid_cents"]
    if raw_amount <= 0 or raw_amount > remaining:
        raise ApiError("ERR_OVERPAYMENT", 422,
                       "Payment must be positive and may not exceed the "
                       "remaining balance")
    if raw_amount == remaining:
        # The completing payment carries the incumbents-cleared gate: every
        # incumbent of the license's area must be RELOCATING or CLEARED.
        for inc in store.DB["incumbents"].values():
            if (inc["area_id"] == license_["area_id"]
                    and inc["status"] in ("NOTIFIED", "PLAN_SUBMITTED",
                                          "DISPUTED")):
                raise ApiError("ERR_INCUMBENTS_NOT_CLEARED", 409,
                               "An incumbent of this area has not cleared")
    license_["paid_cents"] += raw_amount
    touch(license_)
    if license_["paid_cents"] >= license_["net_price_cents"]:
        grant = store.now()
        license_["status"] = "ACTIVE"
        license_["grant_date"] = grant
        license_["term_end"] = store.add_days(grant, calcs.LICENSE_TERM_DAYS)
        for mtype, days, pct in (
                ("INTERIM", calcs.INTERIM_MILESTONE_DAYS,
                 calcs.INTERIM_COVERAGE_PCT),
                ("FINAL", calcs.FINAL_MILESTONE_DAYS,
                 calcs.FINAL_COVERAGE_PCT)):
            ms = store.stamp_new({
                "id": store.new_id(),
                "license_id": license_["id"],
                "milestone_type": mtype,
                "due_date": store.add_days(grant, days),
                "required_coverage_pct": pct,
                "covered_population": None,
                "status": "PENDING",
            })
            store.DB["milestones"][ms["id"]] = ms
    return success(serializers.license_(license_), 200)
