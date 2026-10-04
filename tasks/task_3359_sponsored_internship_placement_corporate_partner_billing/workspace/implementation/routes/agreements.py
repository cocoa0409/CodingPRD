"""Placement agreements and their activation (PRD 3.3)."""

from flask import Blueprint

import db
import middleware
import response
import validators
from errors import (
    ERR_FEE_TIER_MISMATCH,
    ERR_INVALID_STATE,
    ERR_PARTNER_CREDIT_HOLD,
    ERR_PARTNER_SUSPENDED,
    ApiError,
)
from routes.common import must_get, must_get_body, require_version

FEE_TIERS = ("TIER_A", "TIER_B", "TIER_C")
MIN_WINDOW_DAYS = 28
MIN_SUPERVISION_HOURS = 10
MIN_SLOT_COUNT = 1

bp = Blueprint("agreements", __name__)


def _window_days(start_date, end_date):
    return (end_date.date() - start_date.date()).days


@bp.post("/agreements")
def create_agreement():
    middleware.require(("ProgramStaff",))
    data = validators.body()

    raw_partner_id = data.get("partner_id")
    if not isinstance(raw_partner_id, str) or not raw_partner_id.strip():
        validators.fail("field 'partner_id' is required")
    partner = must_get_body("partners", raw_partner_id.strip(), "partner_id")

    project_scope = validators.as_str(data, "project_scope")
    supervision_hours_per_week = validators.as_int(data, "supervision_hours_per_week")
    slot_count = validators.as_int(data, "slot_count")
    fee_tier = validators.as_enum(data, "fee_tier", FEE_TIERS)
    start_date = validators.as_dt(data, "start_date")
    end_date = validators.as_dt(data, "end_date")
    if _window_days(start_date, end_date) < MIN_WINDOW_DAYS:
        validators.fail("end_date must be at least %d days after start_date" % MIN_WINDOW_DAYS)

    row = db.make_row(
        partner_id=partner["id"],
        project_scope=project_scope,
        supervision_hours_per_week=supervision_hours_per_week,
        slot_count=slot_count,
        fee_tier=fee_tier,
        start_date=start_date,
        end_date=end_date,
        status="DRAFT",
    )
    db.insert("agreements", row)
    return response.success(row, status=201)


@bp.post("/agreements/<agreement_id>/activations")
def activate_agreement(agreement_id):
    middleware.require(("ProgramStaff",))
    agreement = must_get("agreements", agreement_id, "agreement")
    data = validators.body()
    expected_version = validators.as_int(data, "expected_partner_version")

    if agreement["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE,
            "agreement %s is %s and cannot be activated" % (agreement_id, agreement["status"]),
            409,
        )

    if int(agreement["supervision_hours_per_week"]) < MIN_SUPERVISION_HOURS:
        validators.fail("supervision_hours_per_week must be at least %d" % MIN_SUPERVISION_HOURS)
    if int(agreement["slot_count"]) < MIN_SLOT_COUNT:
        validators.fail("slot_count must be at least %d" % MIN_SLOT_COUNT)
    if _window_days(agreement["start_date"], agreement["end_date"]) < MIN_WINDOW_DAYS:
        validators.fail("end_date must be at least %d days after start_date" % MIN_WINDOW_DAYS)

    partner = db.get("partners", agreement["partner_id"])

    if agreement["fee_tier"] != partner["fee_tier"]:
        raise ApiError(
            ERR_FEE_TIER_MISMATCH,
            "the agreement's fee_tier %s does not match the partner's current fee_tier %s"
            % (agreement["fee_tier"], partner["fee_tier"]),
            409,
        )
    if partner["credit_hold"]:
        raise ApiError(
            ERR_PARTNER_CREDIT_HOLD,
            "partner %s is on credit hold" % partner["id"],
            402,
        )
    if partner["status"] != "ACTIVE":
        raise ApiError(
            ERR_PARTNER_SUSPENDED,
            "partner %s is %s" % (partner["id"], partner["status"]),
            402,
        )

    require_version(expected_version, partner["version"], "partner")

    agreement["fee_tier"] = partner["fee_tier"]
    agreement["status"] = "ACTIVE"
    db.touch(agreement)
    db.touch(partner)
    return response.success(agreement)
