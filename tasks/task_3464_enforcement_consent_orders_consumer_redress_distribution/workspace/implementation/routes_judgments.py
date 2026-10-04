"""MonetaryJudgment: entry, retrieval, payments/reversals with the redress-fund
sync cascade, inability-to-pay suspension dimension, and asset tracing.
"""
from flask import Blueprint

import envelope
import errors
import requtil
import rules
import store
from timeutil import parse_iso, seconds

bp = Blueprint("judgments", __name__)

PAYMENT_KINDS = {"COLLECTION", "REVERSAL"}
JUDGMENT_TARGET_STATES = {
    "ACTIVE",
    "SUSPENDED",
    "REINSTATED",
    "OUTSTANDING",
    "PARTIALLY_COLLECTED",
    "SATISFIED",
}
SUSPENSION_TRANSITIONS = {
    "SUSPENDED": {"ACTIVE"},
    "REINSTATED": {"SUSPENDED"},
}


def _fund_for_judgment(judgment_id):
    for fund in store.db.redress_funds.values():
        if fund["judgment_id"] == judgment_id:
            return fund
    return None


def _order_for_judgment(judgment):
    return store.db.consent_orders.get(judgment["consent_order_id"])


@bp.route("/enforcement/consent-orders/<orderId>/judgment", methods=["POST"])
def enter_judgment(orderId):
    _user_id, role = requtil.context()
    requtil.require_role(role, ["Commissioner"])
    order = requtil.get_or_404(
        store.db.consent_orders, orderId, "ERR_CONSENT_ORDER_NOT_FOUND", "ConsentOrder"
    )
    body = requtil.json_body()
    amount_cents = requtil.need_int(body, "amount_cents", minimum=1)
    if order["status"] not in ("FINAL", "IN_MONITORING"):
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "A judgment may be entered only for a FINAL or IN_MONITORING order",
        )
    # Tier 11: at most one MonetaryJudgment per ConsentOrder.
    for existing in store.db.judgments.values():
        if existing["consent_order_id"] == order["id"]:
            errors.fail(
                "ERR_JUDGMENT_ALREADY_EXISTS",
                "The consent order already has a monetary judgment",
            )
    with store.db.lock:
        judgment = store.stamp_new(
            {
                "consent_order_id": order["id"],
                "amount_cents": amount_cents,
                "collected_cents": 0,
                "outstanding_cents": amount_cents,
                "collection_status": "OUTSTANDING",
                "suspension_status": "ACTIVE",
                "sworn_total_assets_cents": None,
                "asset_trace_log": [],
            }
        )
        store.db.judgments[judgment["id"]] = judgment
        fund = store.stamp_new(
            {
                "judgment_id": judgment["id"],
                "consent_order_id": order["id"],
                "total_collected_cents": 0,
                "admin_reserve_cents": 0,
                "distributable_pool_cents": 0,
                "allocated_cents": 0,
                "disbursed_cents": 0,
                "available_cents": 0,
                "residual_cents": 0,
                "residual_disposition": "NONE",
                "residual_recipient_name": None,
                "status": "ACCUMULATING",
            }
        )
        store.db.redress_funds[fund["id"]] = fund
    return envelope.success(store.public(judgment), 201)


@bp.route("/enforcement/consent-orders/<orderId>/judgment", methods=["GET"])
def get_order_judgment(orderId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    order = requtil.get_or_404(
        store.db.consent_orders, orderId, "ERR_CONSENT_ORDER_NOT_FOUND", "ConsentOrder"
    )
    matches = [
        j for j in store.db.judgments.values() if j["consent_order_id"] == order["id"]
    ]
    return envelope.success_list([store.public(j) for j in matches], len(matches) or 1, 0, len(matches))


@bp.route("/enforcement/judgments/<judgmentId>", methods=["GET"])
def get_judgment(judgmentId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    judgment = requtil.get_or_404(
        store.db.judgments, judgmentId, "ERR_JUDGMENT_NOT_FOUND", "MonetaryJudgment"
    )
    return envelope.success(store.public(judgment), 200)


@bp.route("/enforcement/judgments/<judgmentId>/payments", methods=["POST"])
def record_payment(judgmentId):
    user_id, role = requtil.context()
    requtil.require_role(role, ["CompanyRepresentative"])
    judgment = requtil.get_or_404(
        store.db.judgments, judgmentId, "ERR_JUDGMENT_NOT_FOUND", "MonetaryJudgment"
    )
    body = requtil.json_body()
    amount_cents = requtil.need_int(body, "amount_cents", minimum=1)
    kind = requtil.need_enum(body, "kind", PAYMENT_KINDS)
    # Tier 5a: suspension gate blocks payments and reversals alike.
    if judgment["suspension_status"] == "SUSPENDED":
        errors.fail(
            "ERR_JUDGMENT_SUSPENDED",
            "The judgment's collection is SUSPENDED",
        )
    # Tier 5b: collection window must still be open on the linked fund.
    fund = _fund_for_judgment(judgment["id"])
    if fund is None or fund["status"] not in ("ACCUMULATING", "OPEN_FOR_CLAIMS"):
        errors.fail(
            "ERR_COLLECTION_WINDOW_CLOSED",
            "The linked redress fund is no longer collecting",
        )
    # Tier 13: subject-company ownership.
    order = _order_for_judgment(judgment)
    if order is None or user_id != order["subject_company_id"]:
        errors.fail(
            "ERR_SUBJECT_COMPANY_MISMATCH",
            "X-User-ID must equal the judgment's subject company id",
        )
    # Tier 14: money limits.
    if kind == "COLLECTION" and amount_cents > judgment["outstanding_cents"]:
        errors.fail(
            "ERR_PAYMENT_EXCEEDS_OUTSTANDING",
            "Payment exceeds the judgment's outstanding_cents",
        )
    if kind == "REVERSAL" and amount_cents > judgment["collected_cents"]:
        errors.fail(
            "ERR_REVERSAL_EXCEEDS_COLLECTED",
            "Reversal exceeds the judgment's collected_cents",
        )
    with store.db.lock:
        if kind == "COLLECTION":
            judgment["collected_cents"] += amount_cents
        else:
            judgment["collected_cents"] -= amount_cents
        collected = judgment["collected_cents"]
        judgment["outstanding_cents"] = judgment["amount_cents"] - collected
        if collected == 0:
            judgment["collection_status"] = "OUTSTANDING"
        elif collected == judgment["amount_cents"]:
            judgment["collection_status"] = "SATISFIED"
        else:
            judgment["collection_status"] = "PARTIALLY_COLLECTED"
        store.touch(judgment)
        # Ledger sync — a cascaded mutation of the fund (version bumps, PRD §2.10).
        fund["total_collected_cents"] = collected
        store.touch(fund)
        # Fund ignition: system-only ACCUMULATING -> OPEN_FOR_CLAIMS.
        if (
            fund["status"] == "ACCUMULATING"
            and collected >= rules.FUND_OPEN_MINIMUM_CENTS
        ):
            fund["status"] = "OPEN_FOR_CLAIMS"
            for claimant in store.db.claimants.values():
                if (
                    claimant["redress_fund_id"] == fund["id"]
                    and claimant["status"] == "IDENTIFIED"
                ):
                    claimant["status"] = "NOTIFIED"
                    claimant["notified_at"] = store.now_str()
                    store.touch(claimant)
            store.touch(fund)
    return envelope.success(store.public(judgment), 201)


@bp.route("/enforcement/judgments/<judgmentId>/transition", methods=["POST"])
def transition_judgment(judgmentId):
    _user_id, role = requtil.context()
    requtil.require_role(role, ["Commissioner"])
    judgment = requtil.get_or_404(
        store.db.judgments, judgmentId, "ERR_JUDGMENT_NOT_FOUND", "MonetaryJudgment"
    )
    body = requtil.json_body()
    target = requtil.need_enum(body, "target_state", JUDGMENT_TARGET_STATES)
    sworn = None
    if target == "SUSPENDED":
        sworn = requtil.need_int(body, "sworn_total_assets_cents", minimum=0)
    # Tier 5: the suspension dimension transitions independently of collection.
    if (
        target not in SUSPENSION_TRANSITIONS
        or judgment["suspension_status"] not in SUSPENSION_TRANSITIONS[target]
    ):
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Judgment suspension cannot transition from {} to {}".format(
                judgment["suspension_status"], target
            ),
        )
    if target == "REINSTATED" and not judgment["asset_trace_log"]:
        errors.fail(
            "ERR_NO_COMPLETED_ASSET_TRACE",
            "Reinstatement requires a non-empty asset_trace_log",
        )
    outstanding = judgment["outstanding_cents"]
    # Tier 14: the ten-percent asset-ratio thresholds (exact rational 1/10).
    if target == "SUSPENDED":
        if sworn * 10 >= outstanding:
            errors.fail(
                "ERR_SUSPENSION_THRESHOLD_NOT_MET",
                "Sworn assets must be strictly below 10% of outstanding_cents",
            )
    if target == "REINSTATED":
        latest = max(
            enumerate(judgment["asset_trace_log"]),
            key=lambda pair: (parse_iso(pair[1]["traced_at"]), pair[0]),
        )[1]
        if latest["found_assets_cents"] * 10 < outstanding:
            errors.fail(
                "ERR_SUSPENSION_THRESHOLD_NOT_MET",
                "Latest asset trace must find at least 10% of outstanding_cents",
            )
    with store.db.lock:
        judgment["suspension_status"] = target
        if target == "SUSPENDED":
            judgment["sworn_total_assets_cents"] = sworn
        store.touch(judgment)
    return envelope.success(store.public(judgment), 200)


@bp.route("/enforcement/judgments/<judgmentId>/asset-traces", methods=["POST"])
def record_asset_trace(judgmentId):
    _user_id, role = requtil.context()
    requtil.require_role(role, ["StaffAttorney"])
    judgment = requtil.get_or_404(
        store.db.judgments, judgmentId, "ERR_JUDGMENT_NOT_FOUND", "MonetaryJudgment"
    )
    body = requtil.json_body()
    found_assets_cents = requtil.need_int(body, "found_assets_cents", minimum=0)
    trace_ref = requtil.need_str(body, "trace_ref")
    with store.db.lock:
        judgment["asset_trace_log"].append(
            {
                "found_assets_cents": found_assets_cents,
                "trace_ref": trace_ref,
                "traced_at": store.now_str(),
            }
        )
        store.touch(judgment)
    return envelope.success(store.public(judgment), 201)


@bp.route("/enforcement/judgments/<judgmentId>/redress-fund", methods=["GET"])
def get_judgment_fund(judgmentId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    judgment = requtil.get_or_404(
        store.db.judgments, judgmentId, "ERR_JUDGMENT_NOT_FOUND", "MonetaryJudgment"
    )
    fund = _fund_for_judgment(judgment["id"])
    items = [store.public(fund)] if fund is not None else []
    return envelope.success_list(items, len(items) or 1, 0, len(items))
