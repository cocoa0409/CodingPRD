"""Logical clock, equity plans and approval authorities."""

from flask import Blueprint, request

import auth
import calc
import clock
import envelope
import services
import store
import validate
from auth import AUDITOR, BOARD, COMPLIANCE, DELEGATED, PLAN_ADMIN
from errors import ApiError

bp = Blueprint("plans", __name__)

PLAN_READERS = (PLAN_ADMIN, BOARD, DELEGATED, COMPLIANCE, AUDITOR)
SUMMARY_READERS = (PLAN_ADMIN, BOARD, COMPLIANCE, AUDITOR)


# --- logical clock ----------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    actor = auth.begin(PLAN_ADMIN, COMPLIANCE)
    raw = actor.body.get("current_utc")
    instant = validate.field_instant(actor.body, "current_utc")
    clock.set_now(instant, raw if isinstance(raw, str) else clock.fmt_instant(instant))
    return envelope.ok({"current_utc": clock.raw_current()})


# --- equity plans -----------------------------------------------------------

def _new_plan(body):
    row = store.base_row()
    row.update({
        "name": validate.field_str(body, "name", min_len=1, max_len=120),
        "total_authorized_shares": validate.field_int(
            body, "total_authorized_shares", minimum=1),
        "common_shares_outstanding": validate.field_int(
            body, "common_shares_outstanding", minimum=1),
        "fiscal_year_start_date": clock.fmt_date(
            validate.field_date(body, "fiscal_year_start_date")),
        "current_fiscal_year_label": validate.field_str(
            body, "current_fiscal_year_label", required=False, default="FY2026"),
        "evergreen_pct_bps": validate.field_int(
            body, "evergreen_pct_bps", required=False, default=0, minimum=0, maximum=10000),
        "evergreen_cap_shares": validate.field_int(
            body, "evergreen_cap_shares", required=False, default=0, minimum=0),
        "burn_rate_limit_bps": validate.field_int(
            body, "burn_rate_limit_bps", required=False, default=10000, minimum=1, maximum=10000),
        "fungible_ratio_full_value_bps": validate.field_int(
            body, "fungible_ratio_full_value_bps", required=False, default=10000, minimum=10000),
        "low_reserve_threshold_bps": validate.field_int(
            body, "low_reserve_threshold_bps", required=False, default=0, minimum=0,
            maximum=10000),
        "next_earnings_release_at": None,
        "status": "ACTIVE",
        "freeze_reason": None,
        "shares_committed_cumulative": 0,
        "shares_returned_cumulative": 0,
        "fiscal_year_gross_granted_shares": 0,
        "fiscal_year_returned_shares": 0,
        "evergreen_topup_last_shares": 0,
        "gross_burn_rate_bps": 0,
        "net_burn_rate_bps": 0,
    })
    earnings = validate.field_instant(body, "next_earnings_release_at", required=False)
    if earnings is not None:
        row["next_earnings_release_at"] = clock.fmt_instant(earnings)
    services.recompute_reserve(row)
    return row


@bp.route("/equity-plans", methods=["POST"])
def create_plan():
    actor = auth.begin(PLAN_ADMIN)
    row = _new_plan(actor.body)
    store.plans[row["id"]] = row
    return envelope.created(store.public(row))


@bp.route("/equity-plans", methods=["GET"])
def list_plans():
    auth.begin(*PLAN_READERS)
    rows = list(store.plans.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    posture = request.args.get("reserve_posture")
    if posture is not None:
        rows = [r for r in rows if r["reserve_posture"] == posture]
    return envelope.page(store.sort_default(rows))


@bp.route("/equity-plans/<plan_id>", methods=["GET"])
def read_plan(plan_id):
    auth.begin(*PLAN_READERS)
    return envelope.ok(store.public(services.plan_or_404(plan_id)))


@bp.route("/equity-plans/<plan_id>/status", methods=["POST"])
def plan_status(plan_id):
    actor = auth.begin(PLAN_ADMIN, BOARD)
    plan = services.plan_or_404(plan_id)
    action = validate.field_enum(actor.body, "action", ("FREEZE", "UNFREEZE", "TERMINATE"))
    reason = validate.field_str(actor.body, "freeze_reason", required=False)
    current = plan["status"]
    if action == "FREEZE":
        if current != "ACTIVE":
            raise ApiError("ERR_PLAN_INVALID_STATE")
        plan["status"] = "FROZEN"
        plan["freeze_reason"] = reason
    elif action == "UNFREEZE":
        if current != "FROZEN":
            raise ApiError("ERR_PLAN_INVALID_STATE")
        plan["status"] = "ACTIVE"
        plan["freeze_reason"] = None
    else:
        if current not in ("ACTIVE", "FROZEN"):
            raise ApiError("ERR_PLAN_INVALID_STATE")
        plan["status"] = "TERMINATED"
        plan["freeze_reason"] = reason
        _terminate_cascade(plan)
    store.touch(plan)
    return envelope.ok(store.public(plan))


def _terminate_cascade(plan):
    stamp = clock.fmt_instant(clock.now())
    for row in store.sort_default(
        [a for a in store.authorities.values() if a["plan_id"] == plan["id"]]
    ):
        if row["status"] == "ACTIVE":
            row["status"] = "REVOKED"
            row["revoked_at"] = stamp
            store.touch(row)
    for row in store.sort_default(
        [w for w in store.windows.values() if w["plan_id"] == plan["id"]]
    ):
        if row["status"] in ("SCHEDULED", "OPEN", "SUSPENDED"):
            row["status"] = "CLOSED"
            services.close_window_cascade(row)
            store.touch(row)


@bp.route("/equity-plans/<plan_id>/share-reserve-adjustments", methods=["POST"])
def adjust_reserve(plan_id):
    actor = auth.begin(PLAN_ADMIN)
    plan = services.plan_or_404(plan_id)
    delta = validate.field_int(actor.body, "delta_shares")
    expected = validate.field_int(actor.body, "expected_plan_version")
    validate.field_str(actor.body, "adjustment_reason", required=False)
    services.require_plan_active(plan)
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION")
    projected_total = plan["total_authorized_shares"] + delta
    projected = calc.available_reserve(
        projected_total,
        plan["shares_committed_cumulative"],
        plan["shares_returned_cumulative"],
    )
    if projected < 0:
        raise ApiError("ERR_RESERVE_INSUFFICIENT")
    plan["total_authorized_shares"] = projected_total
    services.recompute_reserve(plan)
    store.touch(plan)
    return envelope.ok(store.public(plan))


@bp.route("/equity-plans/<plan_id>/annual-rollover", methods=["POST"])
def annual_rollover(plan_id):
    actor = auth.begin(PLAN_ADMIN)
    plan = services.plan_or_404(plan_id)
    label = validate.field_str(actor.body, "fiscal_year_label")
    services.require_plan_active(plan)
    topup = calc.evergreen_topup(
        plan["common_shares_outstanding"],
        plan["evergreen_pct_bps"],
        plan["evergreen_cap_shares"],
    )
    plan["total_authorized_shares"] += topup
    plan["evergreen_topup_last_shares"] = topup
    plan["current_fiscal_year_label"] = label
    new_start = clock.add_years(clock.parse_date(plan["fiscal_year_start_date"]), 1)
    plan["fiscal_year_start_date"] = clock.fmt_date(new_start)
    plan["fiscal_year_gross_granted_shares"] = 0
    plan["fiscal_year_returned_shares"] = 0
    plan["gross_burn_rate_bps"] = 0
    plan["net_burn_rate_bps"] = 0
    services.recompute_reserve(plan)
    store.touch(plan)
    for row in store.sort_default(
        [a for a in store.authorities.values() if a["plan_id"] == plan["id"]]
    ):
        if row["status"] == "ACTIVE" and clock.parse_date(row["effective_to"]) < new_start:
            row["status"] = "EXPIRED"
            store.touch(row)
    return envelope.ok(store.public(plan))


@bp.route("/equity-plans/<plan_id>/burn-rate-summary", methods=["GET"])
def burn_rate_summary(plan_id):
    auth.begin(*SUMMARY_READERS)
    plan = services.plan_or_404(plan_id)
    return envelope.ok({
        "plan_id": plan["id"],
        "gross_burn_rate_bps": plan["gross_burn_rate_bps"],
        "net_burn_rate_bps": plan["net_burn_rate_bps"],
        "fiscal_year_gross_granted_shares": plan["fiscal_year_gross_granted_shares"],
        "fiscal_year_returned_shares": plan["fiscal_year_returned_shares"],
        "burn_rate_limit_bps": plan["burn_rate_limit_bps"],
        "headroom_shares": calc.headroom_shares(
            plan["burn_rate_limit_bps"],
            plan["common_shares_outstanding"],
            plan["fiscal_year_gross_granted_shares"],
        ),
        "available_reserve_shares": plan["available_reserve_shares"],
        "reserve_posture": plan["reserve_posture"],
    })


# --- approval authorities ---------------------------------------------------

@bp.route("/approval-authorities", methods=["POST"])
def create_authority():
    actor = auth.begin(BOARD)
    body = actor.body
    plan_ref = validate.raw_id(body, "plan_id")
    if plan_ref is not None:
        services.plan_or_404(plan_ref)
    plan_id = validate.field_id(body, "plan_id")
    row = store.base_row()
    effective_from = validate.field_date(body, "effective_from")
    effective_to = validate.field_date(body, "effective_to")
    validate.require_order(effective_from, effective_to, "effective_to precedes effective_from.")
    row.update({
        "plan_id": plan_id,
        "authority_type": validate.field_enum(
            body, "authority_type", ("DELEGATED_OFFICER", "COMMITTEE")),
        "delegate_user_id": validate.field_str(body, "delegate_user_id"),
        "per_grant_share_cap": validate.field_int(body, "per_grant_share_cap", minimum=1),
        "aggregate_share_cap": validate.field_int(body, "aggregate_share_cap", minimum=1),
        "effective_from": clock.fmt_date(effective_from),
        "effective_to": clock.fmt_date(effective_to),
        "status": "ACTIVE",
        "consumed_shares": 0,
        "revoked_at": None,
    })
    row["remaining_shares"] = row["aggregate_share_cap"]
    store.authorities[row["id"]] = row
    return envelope.created(store.public(row))


@bp.route("/approval-authorities/<authority_id>", methods=["GET"])
def read_authority(authority_id):
    auth.begin(*PLAN_READERS)
    return envelope.ok(store.public(services.authority_or_404(authority_id)))


@bp.route("/equity-plans/<plan_id>/approval-authorities", methods=["GET"])
def list_authorities(plan_id):
    auth.begin(*PLAN_READERS)
    services.plan_or_404(plan_id)
    rows = [a for a in store.authorities.values() if a["plan_id"] == plan_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.page(store.sort_default(rows))


@bp.route("/approval-authorities/<authority_id>/revoke", methods=["POST"])
def revoke_authority(authority_id):
    actor = auth.begin(BOARD)
    row = services.authority_or_404(authority_id)
    validate.field_str(actor.body, "revocation_reason", required=False)
    if row["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise ApiError("ERR_AUTHORITY_INVALID_STATE")
    row["status"] = "REVOKED"
    row["revoked_at"] = clock.fmt_instant(clock.now())
    store.touch(row)
    return envelope.ok(store.public(row))
