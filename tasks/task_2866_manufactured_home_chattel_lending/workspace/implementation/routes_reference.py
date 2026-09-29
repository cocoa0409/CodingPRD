"""Logical clock, guide editions, borrowers, communities and the operator
agreement (PRD 2.4, 3.1)."""

from flask import Blueprint

import constants as K
import core
import domain
import envelope
import security
import shape
import store
from errors import ApiError

bp = Blueprint("reference", __name__)


# --------------------------------------------------------------------------
# the logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    security.require(security.PLATFORM_ADMIN)
    data = shape.body()
    current = shape.req_instant(data, "current_utc")
    if current < core.now():
        raise ApiError("ERR_CLOCK_REGRESSION")
    core.set_clock(current)
    return envelope.ok({"current_utc": core.iso(core.now())})


# --------------------------------------------------------------------------
# book value guides
# --------------------------------------------------------------------------

@bp.post("/book-value-guides")
def create_guide():
    security.require(security.PLATFORM_ADMIN)
    data = shape.body()
    record = {
        "id": core.new_id(),
        "guide_edition": shape.req_string(data, "guide_edition"),
        "region_code": shape.req_string(data, "region_code"),
        "effective_date": shape.req_instant(data, "effective_date"),
        "base_value_per_sqft_cents": shape.req_int(data, "base_value_per_sqft_cents", minimum=1),
        "single_wide_multiplier_bps": shape.req_int(data, "single_wide_multiplier_bps", minimum=1),
        "multi_wide_multiplier_bps": shape.req_int(data, "multi_wide_multiplier_bps", minimum=1),
        "annual_depreciation_bps": shape.req_int(data, "annual_depreciation_bps",
                                                 minimum=0, maximum=1000),
    }
    store.stamp_new(record, versioned=False)
    store.guides[record["id"]] = record
    return envelope.created(store.serialize(record))


@bp.get("/book-value-guides/<guide_id>")
def read_guide(guide_id):
    security.require(*security.STAFF)
    return envelope.ok(store.serialize(store.get_guide(guide_id)))


# --------------------------------------------------------------------------
# borrowers
# --------------------------------------------------------------------------

@bp.post("/borrowers")
def create_borrower():
    security.require(security.PLATFORM_ADMIN)
    data = shape.body()
    record = {
        "id": core.new_id(),
        "full_name": shape.req_string(data, "full_name"),
        "credit_score": shape.req_int(data, "credit_score", minimum=300, maximum=850),
        "monthly_income_cents": shape.req_int(data, "monthly_income_cents", minimum=0),
        "state_code": shape.req_string(data, "state_code"),
        "status": "ACTIVE",
        "total_outstanding_principal_cents": 0,
        "units_under_recovery_hold_count": 0,
    }
    store.stamp_new(record)
    store.borrowers[record["id"]] = record
    return envelope.created(store.serialize(record))


@bp.get("/borrowers/<borrower_id>")
def read_borrower(borrower_id):
    actor = security.require(*(security.STAFF + (security.BORROWER,)))
    security.check_borrower_scope(actor, borrower_id)
    return envelope.ok(store.serialize(store.get_borrower(borrower_id)))


# --------------------------------------------------------------------------
# communities
# --------------------------------------------------------------------------

@bp.post("/communities")
def create_community():
    security.require(security.PLATFORM_ADMIN)
    data = shape.body()
    record = {
        "id": core.new_id(),
        "name": shape.req_string(data, "name"),
        "state_code": shape.req_string(data, "state_code"),
        "lot_count": shape.req_int(data, "lot_count", minimum=1),
        "monthly_lot_rent_cents": shape.req_int(data, "monthly_lot_rent_cents", minimum=0),
        "sales_commission_bps": shape.opt_int(data, "sales_commission_bps", default=0,
                                              minimum=0, maximum=500),
        "operator_agreement_status": "NONE",
        "lender_access_rights": False,
        "agreement_executed_at": None,
    }
    store.stamp_new(record)
    store.communities[record["id"]] = record
    return envelope.created(store.serialize(record))


@bp.get("/communities/<community_id>")
def read_community(community_id):
    actor = security.require(*(security.STAFF + (security.COMMUNITY_OPERATOR,)))
    security.check_community_scope(actor, community_id)
    return envelope.ok(store.serialize(store.get_community(community_id)))


@bp.post("/communities/<community_id>/operator-agreement")
def operator_agreement(community_id):
    actor = security.require(security.PLATFORM_ADMIN, security.COMMUNITY_OPERATOR)
    security.check_community_scope(actor, community_id)
    community = store.get_community(community_id)
    data = shape.body()
    action = shape.req_enum(data, "action", K.OPERATOR_AGREEMENT_ACTIONS)

    # EXECUTE is the one write reserved to the CommunityOperator; the other two
    # arms are PlatformAdmin actions (PRD 3.1).
    if action == "EXECUTE":
        if not actor.is_operator:
            raise ApiError("ERR_ROLE_NOT_PERMITTED")
    elif actor.is_operator:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    status = community["operator_agreement_status"]
    if action == "PROPOSE":
        if status not in ("NONE", "TERMINATED"):
            raise ApiError("ERR_OPERATOR_AGREEMENT_INVALID_STATE")
        community["operator_agreement_status"] = "PENDING"
    elif action == "EXECUTE":
        if status != "PENDING":
            raise ApiError("ERR_OPERATOR_AGREEMENT_INVALID_STATE")
        community["operator_agreement_status"] = "EXECUTED"
        community["lender_access_rights"] = True
        community["agreement_executed_at"] = core.now()
    else:
        if status != "EXECUTED":
            raise ApiError("ERR_OPERATOR_AGREEMENT_INVALID_STATE")
        community["operator_agreement_status"] = "TERMINATED"
        community["lender_access_rights"] = False
    store.touch(community)
    return envelope.ok(store.serialize(community))
