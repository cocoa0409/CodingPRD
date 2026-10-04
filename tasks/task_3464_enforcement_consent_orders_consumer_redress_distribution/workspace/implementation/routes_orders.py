"""ConsentOrder retrieval and OCC-guarded lifecycle; PublicCommentPeriod listing
and comment filing.
"""
from flask import Blueprint, request

import envelope
import errors
import requtil
import rules
import store
from timeutil import parse_iso, fmt_iso, seconds, add_days, add_years

bp = Blueprint("orders", __name__)

ORDER_STATES = {
    "DRAFT",
    "IN_PUBLIC_COMMENT",
    "FINAL",
    "IN_MONITORING",
    "EXPIRED",
    "TERMINATED",
}
ORDER_TARGET_ROLES = {
    "IN_PUBLIC_COMMENT": ["StaffAttorney"],
    "DRAFT": ["StaffAttorney"],
    "FINAL": ["Commissioner"],
    "IN_MONITORING": ["Commissioner"],
    "TERMINATED": ["Commissioner"],
}
ORDER_TRANSITIONS = {
    "IN_PUBLIC_COMMENT": {"DRAFT"},
    "DRAFT": {"IN_PUBLIC_COMMENT"},
    "FINAL": {"IN_PUBLIC_COMMENT"},
    "IN_MONITORING": {"FINAL"},
    "TERMINATED": {"DRAFT", "IN_MONITORING"},
}


@bp.route("/enforcement/consent-orders/<orderId>", methods=["GET"])
def get_consent_order(orderId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    order = requtil.get_or_404(
        store.db.consent_orders, orderId, "ERR_CONSENT_ORDER_NOT_FOUND", "ConsentOrder"
    )
    return envelope.success(store.public(order), 200)


@bp.route("/enforcement/consent-orders/<orderId>/transition", methods=["POST"])
def transition_consent_order(orderId):
    user_id, role = requtil.context()
    requtil.require_role(role, ["StaffAttorney", "Commissioner"])
    order = requtil.get_or_404(
        store.db.consent_orders, orderId, "ERR_CONSENT_ORDER_NOT_FOUND", "ConsentOrder"
    )
    body = requtil.json_body()
    target = requtil.need_enum(body, "target_state", ORDER_STATES)
    requtil.require_target_role(role, target, ORDER_TARGET_ROLES)
    expected = requtil.need_int(body, "expected_consent_order_version")
    # Tier 5: state legality (EXPIRED is system-only; not requestable).
    if target not in ORDER_TRANSITIONS or order["status"] not in ORDER_TRANSITIONS[target]:
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "ConsentOrder cannot transition from {} to {}".format(
                order["status"], target
            ),
        )
    # Tier 6: optimistic concurrency.
    if expected != order["version"]:
        errors.fail(
            "ERR_STALE_ORDER_VERSION",
            "expected_consent_order_version {} does not match current version {}".format(
                expected, order["version"]
            ),
        )
    # Tier 8: regulatory cooling-off on finalization.
    if target == "FINAL":
        periods = [
            p
            for p in store.db.comment_periods.values()
            if p["consent_order_id"] == order["id"]
        ]
        latest = max(periods, key=lambda p: p["round"], default=None)
        if latest is None or latest["status"] != "CLOSED":
            errors.fail(
                "ERR_COMMENT_PERIOD_OPEN",
                "The latest public comment period is not CLOSED",
            )
    # Tier 10: half-open monitoring-window overlap per subject company.
    if target == "IN_MONITORING":
        new_start = seconds(store.db.clock_dt)
        new_end = add_years(new_start, order["monitoring_term_years"])
        for other in store.db.consent_orders.values():
            if (
                other["id"] == order["id"]
                or other["subject_company_id"] != order["subject_company_id"]
                or other["status"] != "IN_MONITORING"
            ):
                continue
            other_start = seconds(parse_iso(other["monitoring_started_at"]))
            other_end = seconds(parse_iso(other["monitoring_ends_at"]))
            # Half-open windows: adjacency (end == start) is NOT overlap.
            if other_start < new_end and new_start < other_end:
                errors.fail(
                    "ERR_MONITORING_TERM_OVERLAP",
                    "Another order of this subject company is IN_MONITORING over an overlapping window",
                )
    with store.db.lock:
        now = store.now_dt()
        if target == "IN_PUBLIC_COMMENT":
            period = store.stamp_new(
                {
                    "consent_order_id": order["id"],
                    "round": order["proposal_round"],
                    "opened_at": store.now_str(),
                    "closes_at": fmt_iso(add_days(now, rules.COMMENT_PERIOD_DAYS)),
                    "comments": [],
                    "comment_count": 0,
                    "status": "OPEN",
                }
            )
            store.db.comment_periods[period["id"]] = period
            order["status"] = "IN_PUBLIC_COMMENT"
            store.touch(order)
        elif target == "DRAFT":
            for period in store.db.comment_periods.values():
                if (
                    period["consent_order_id"] == order["id"]
                    and period["status"] == "OPEN"
                ):
                    period["status"] = "VOIDED"
                    store.touch(period)
            order["proposal_round"] += 1
            order["status"] = "DRAFT"
            store.touch(order)
        elif target == "FINAL":
            order["finalized_at"] = store.now_str()
            order["finalized_by_user_id"] = user_id
            order["status"] = "FINAL"
            store.touch(order)
            inv = store.db.investigations.get(order["investigation_id"])
            if inv is not None and inv["status"] == "SETTLED":
                inv["status"] = "CLOSED_ORDER_ENTERED"
                store.touch(inv)
        elif target == "IN_MONITORING":
            order["monitoring_started_at"] = store.now_str()
            order["monitoring_ends_at"] = fmt_iso(
                add_years(now, order["monitoring_term_years"])
            )
            order["status"] = "IN_MONITORING"
            store.touch(order)
        elif target == "TERMINATED":
            order["status"] = "TERMINATED"
            store.touch(order)
    return envelope.success(store.public(order), 200)


@bp.route("/enforcement/consent-orders/<orderId>/comment-periods", methods=["GET"])
def list_comment_periods(orderId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    order = requtil.get_or_404(
        store.db.consent_orders, orderId, "ERR_CONSENT_ORDER_NOT_FOUND", "ConsentOrder"
    )
    limit, offset = requtil.page_params()
    items = [
        p
        for p in store.db.comment_periods.values()
        if p["consent_order_id"] == order["id"]
    ]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    # The single exception to created_at ordering: comment periods list by round ASC.
    items.sort(key=lambda p: (p["round"], p["_seq"]))
    total = len(items)
    page = [store.public(p) for p in items[offset:offset + limit]]
    return envelope.success_list(page, limit, offset, total)


@bp.route("/enforcement/comment-periods/<periodId>/comments", methods=["POST"])
def file_comment(periodId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    period = requtil.get_or_404(
        store.db.comment_periods,
        periodId,
        "ERR_COMMENT_PERIOD_NOT_FOUND",
        "PublicCommentPeriod",
    )
    body = requtil.json_body()
    author_email = requtil.need_str(body, "author_email")
    text = requtil.need_str(body, "body")
    # Tier 9: comments are accepted only while the period is OPEN.
    if period["status"] != "OPEN":
        errors.fail(
            "ERR_COMMENT_PERIOD_CLOSED",
            "The comment period is {}".format(period["status"]),
        )
    with store.db.lock:
        period["comments"].append(
            {
                "author_email": author_email,
                "body": text,
                "submitted_at": store.now_str(),
            }
        )
        period["comment_count"] = len(period["comments"])
        store.touch(period)
    return envelope.success(store.public(period), 201)
