"""ViolationPenalty assessment, listing, and lifecycle transitions."""
from flask import Blueprint, request

import envelope
import errors
import requtil
import rules
import store
from timeutil import parse_iso, seconds

bp = Blueprint("penalties", __name__)

SEVERITIES = {"STANDARD", "AGGRAVATED", "EGREGIOUS"}
PENALTY_STATES = {"ASSESSED_PROVISIONAL", "CONFIRMED", "PAID", "WAIVED"}
PENALTY_TARGET_ROLES = {
    "CONFIRMED": ["ComplianceMonitor"],
    "WAIVED": ["ComplianceMonitor"],
    "PAID": ["CompanyRepresentative"],
}
PENALTY_TRANSITIONS = {
    "CONFIRMED": {"ASSESSED_PROVISIONAL"},
    "WAIVED": {"ASSESSED_PROVISIONAL", "CONFIRMED"},
    "PAID": {"CONFIRMED"},
}


@bp.route("/enforcement/consent-orders/<orderId>/violation-penalties", methods=["POST"])
def assess_penalty(orderId):
    user_id, role = requtil.context()
    requtil.require_role(role, ["ComplianceMonitor"])
    order = requtil.get_or_404(
        store.db.consent_orders, orderId, "ERR_CONSENT_ORDER_NOT_FOUND", "ConsentOrder"
    )
    body = requtil.json_body()
    severity = requtil.need_enum(body, "severity", SEVERITIES)
    detected_on = requtil.need_datetime(body, "detected_on")
    description = requtil.need_str(body, "description")
    if order["status"] != "IN_MONITORING":
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Penalties may be assessed only while the order is IN_MONITORING",
        )
    days, amount = rules.provisional_penalty(severity, order["max_penalty_cents"])
    with store.db.lock:
        penalty = store.stamp_new(
            {
                "consent_order_id": order["id"],
                "severity": severity,
                "detected_on": detected_on,
                "description": description,
                "assessed_by_user_id": user_id,
                "provisional_days": days,
                "provisional_amount_cents": amount,
                "cured_on": None,
                "final_days": None,
                "final_amount_cents": None,
                "confirmed_by_user_id": None,
                "status": "ASSESSED_PROVISIONAL",
            }
        )
        store.db.violation_penalties[penalty["id"]] = penalty
    return envelope.success(store.public(penalty), 201)


@bp.route("/enforcement/consent-orders/<orderId>/violation-penalties", methods=["GET"])
def list_penalties(orderId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    order = requtil.get_or_404(
        store.db.consent_orders, orderId, "ERR_CONSENT_ORDER_NOT_FOUND", "ConsentOrder"
    )
    limit, offset = requtil.page_params()
    items = [
        p
        for p in store.db.violation_penalties.values()
        if p["consent_order_id"] == order["id"]
    ]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda e: (parse_iso(e["created_at"]), e["_seq"]))
    total = len(items)
    page = [store.public(p) for p in items[offset:offset + limit]]
    return envelope.success_list(page, limit, offset, total)


@bp.route("/enforcement/violation-penalties/<penaltyId>/transition", methods=["POST"])
def transition_penalty(penaltyId):
    user_id, role = requtil.context()
    requtil.require_role(role, ["ComplianceMonitor", "CompanyRepresentative"])
    penalty = requtil.get_or_404(
        store.db.violation_penalties,
        penaltyId,
        "ERR_VIOLATION_PENALTY_NOT_FOUND",
        "ViolationPenalty",
    )
    body = requtil.json_body()
    target = requtil.need_enum(body, "target_state", PENALTY_STATES)
    requtil.require_target_role(role, target, PENALTY_TARGET_ROLES)
    cured_on = None
    if target == "CONFIRMED":
        cured_on = requtil.need_datetime(body, "cured_on")
        if seconds(parse_iso(cured_on)) < seconds(parse_iso(penalty["detected_on"])):
            errors.fail(
                "ERR_INVALID_REQUEST",
                "cured_on must not fall earlier than detected_on",
            )
    if target not in PENALTY_TRANSITIONS or penalty["status"] not in PENALTY_TRANSITIONS[target]:
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "ViolationPenalty cannot transition from {} to {}".format(
                penalty["status"], target
            ),
        )
    # Tier 7: segregation of duties — never the assessing monitor.
    if target in ("CONFIRMED", "WAIVED") and user_id == penalty["assessed_by_user_id"]:
        errors.fail(
            "ERR_SOD_PENALTY_CONFIRM",
            "The confirming/waiving monitor must differ from the assessing monitor",
        )
    # Tier 13: subject-company ownership on payment.
    if target == "PAID":
        order = store.db.consent_orders.get(penalty["consent_order_id"])
        if order is None or user_id != order["subject_company_id"]:
            errors.fail(
                "ERR_SUBJECT_COMPANY_MISMATCH",
                "X-User-ID must equal the order's subject company id",
            )
    with store.db.lock:
        penalty["status"] = target
        if target == "CONFIRMED":
            order = store.db.consent_orders.get(penalty["consent_order_id"])
            cap = order["max_penalty_cents"] if order is not None else None
            days, amount = rules.final_penalty(
                penalty["severity"],
                parse_iso(penalty["detected_on"]),
                parse_iso(cured_on),
                cap if cap is not None else penalty["provisional_amount_cents"],
            )
            penalty["cured_on"] = cured_on
            penalty["final_days"] = days
            penalty["final_amount_cents"] = amount
            penalty["confirmed_by_user_id"] = user_id
        store.touch(penalty)
    return envelope.success(store.public(penalty), 200)
