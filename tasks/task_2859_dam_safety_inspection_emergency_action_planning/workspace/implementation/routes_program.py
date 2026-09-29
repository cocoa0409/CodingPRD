"""Program operations: the compliance sweep and the logical-clock capability."""

from flask import Blueprint, request

import calc
import guards
import services
from common import ApiError, add_days, body_dict, fmt_dt, ok, v_dt
from derive import dam_eap_required, dam_inspection_overdue, owner_delinquency_status
from guards import HEADER_USER_ID, HEADER_USER_ROLE
from store import db, insertion_order, touch

bp = Blueprint("program", __name__)


@bp.route("/program/compliance-sweep", methods=["POST"])
def compliance_sweep():
    guards.authenticate(request, ("ProgramAdmin",))
    swept_at = db.clock

    defaulted_ids = []
    penalty_cents_assessed = 0
    escalated_deficiency_count = 0
    newly_delinquent_owners = []
    dams_moved_under_enforcement = 0

    # ---- Stage 1: default overdue orders and run the four-link cascade -----
    for order in insertion_order(list(db.orders.values())):
        if order["status"] not in ("ISSUED", "RESPONSE_FILED"):
            continue
        if not (db.clock > order["compliance_deadline_at"]):
            continue
        response_filed = order["response_filed_at"] is not None
        days = calc.overdue_days(db.clock, order["compliance_deadline_at"])
        penalty = calc.final_penalty_cents(
            order["daily_penalty_rate_cents"], days, response_filed)
        # Link 1
        order["status"] = "DEFAULTED"
        order["defaulted_at"] = db.clock
        order["assessed_penalty_cents"] = penalty
        touch(order)
        defaulted_ids.append(order["id"])
        penalty_cents_assessed += penalty
        deficiency = db.deficiencies.get(order["deficiency_id"])
        if deficiency is not None and deficiency["status"] == "ORDERED":
            deficiency["status"] = "ESCALATED"
            touch(deficiency)
            escalated_deficiency_count += 1
        # Link 2, then link 3, then link 4 -- each conditional on the previous.
        owner = db.owners.get(order["owner_id"])
        if owner is not None and penalty > 0:
            before = owner_delinquency_status(owner["id"])
            services.post_ledger_entry(
                owner["id"], "CIVIL_PENALTY", penalty, services.SYSTEM_USER_ID,
                source_ref=order["id"],
                memo="Civil penalty assessed on remediation order default")
            touch(owner)
            after = owner_delinquency_status(owner["id"])
            if before == "CURRENT" and after == "DELINQUENT":
                newly_delinquent_owners.append(owner["id"])
                dam = db.dams.get(order["dam_id"])
                if dam is not None and services.move_under_enforcement(dam):
                    dams_moved_under_enforcement += 1

    # ---- Stage 2: refer aged defaults for prosecution ---------------------
    referred_order_count = 0
    for order in insertion_order(list(db.orders.values())):
        if order["status"] != "DEFAULTED" or order["defaulted_at"] is None:
            continue
        if db.clock > add_days(order["defaulted_at"], calc.REFERRAL_DAYS):
            order["status"] = "REFERRED_FOR_ENFORCEMENT"
            touch(order)
            referred_order_count += 1

    # ---- Stage 3: expire stale emergency action plans ---------------------
    expired_eap_count = 0
    for plan in insertion_order(list(db.plans.values())):
        if plan["status"] != "APPROVED" or plan["expires_at"] is None:
            continue
        if not (db.clock > plan["expires_at"]):
            continue
        plan["status"] = "EXPIRED"
        touch(plan)
        expired_eap_count += 1
        dam = db.dams.get(plan["dam_id"])
        if dam is None:
            continue
        if dam_eap_required(dam):
            services.open_eap_missing_deficiency(dam)
            touch(dam)
        else:
            touch(dam, bump=False)

    # ---- Stage 4: recompute the overdue-inspection flags ------------------
    overdue_inspection_count = 0
    for dam in db.dams.values():
        if dam_inspection_overdue(dam):
            overdue_inspection_count += 1

    return ok({
        "swept_at": fmt_dt(swept_at),
        "defaulted_order_count": len(defaulted_ids),
        "defaulted_order_ids": defaulted_ids,
        "escalated_deficiency_count": escalated_deficiency_count,
        "referred_order_count": referred_order_count,
        "expired_eap_count": expired_eap_count,
        "penalty_cents_assessed": penalty_cents_assessed,
        "newly_delinquent_owner_count": len(newly_delinquent_owners),
        "dams_moved_under_enforcement": dams_moved_under_enforcement,
        "overdue_inspection_count": overdue_inspection_count,
    })


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    """The one endpoint that does not require identity headers. A role header
    that is present but wrong is still rejected."""
    role = request.headers.get(HEADER_USER_ROLE)
    user_id = request.headers.get(HEADER_USER_ID)
    if (role is not None and role.strip() != "") or (user_id is not None and user_id.strip() != ""):
        if role is None or role.strip() == "" or role.strip() != "ProgramAdmin":
            raise ApiError("ERR_FORBIDDEN_ROLE", "only a ProgramAdmin may set the logical clock")
    body = body_dict()
    to_iso8601 = v_dt(body, "to_iso8601")
    # Rung 42: the clock never moves backwards; an equal instant is a no-op.
    if to_iso8601 < db.clock:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC",
                       "the logical clock may not move backwards")
    db.clock = to_iso8601
    return ok({})
