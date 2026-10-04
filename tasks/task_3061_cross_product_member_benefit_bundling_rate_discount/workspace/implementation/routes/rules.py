"""Rate-discount rule governance routes."""

from flask import Blueprint

from db import DB
from errors import (
    ERR_ACTIVE_RULE_ON_UNPRICED_LOAN,
    ERR_DUPLICATE_RULE_CODE,
    ERR_INVALID_STATE,
    ERR_RULE_WINDOW_OVERLAP,
    ERR_SELF_STACK_CYCLE,
    ERR_STACK_CLASS_CONFLICT,
    ApiError,
)
from middleware import (
    as_bool,
    as_enum,
    as_int,
    as_string,
    as_timestamp,
    auth,
    raw_body,
    reject_unknown,
    require_fields,
)
from response import ok_object
from routes.common import fetch, list_response, mk
from services import calc, recompute, serialize
from timeutil import parse_ts

BP = Blueprint("rules", __name__)

DISCOUNT_KINDS = ("MEMBER_TIER", "DIRECT_DEPOSIT", "AUTOPAY", "PROMOTIONAL", "CAREER_SERVICES")
STACKING_CLASSES = ("BASE", "ADDITIVE", "CAP_CONTRIBUTING")
TIERS = ("NONE", "BASE", "PLUS", "PREMIER")
OVERLAP_MIN_GAP_DAYS = 1

CREATE_ALLOWED = {
    "rule_code",
    "discount_kind",
    "stacking_class",
    "discount_bps",
    "effective_from",
    "effective_to",
    "stacks_on_rule_id",
    "requires_direct_deposit",
    "min_member_tier",
}
EDIT_ALLOWED = {"stacks_on_rule_id", "discount_bps", "effective_to"}


def _stack_chain_ok(rule_id, parent_id):
    """Walk the chain; reject a cycle or a class mismatch."""
    parent = DB.rules.get(parent_id)
    if parent is None:
        raise ApiError(ERR_ACTIVE_RULE_ON_UNPRICED_LOAN)
    rule = DB.rules.get(rule_id) if rule_id else None
    if rule is not None and parent["stacking_class"] != rule["stacking_class"]:
        raise ApiError(ERR_STACK_CLASS_CONFLICT)
    seen = {rule_id} if rule_id else set()
    cursor = parent
    while cursor is not None:
        if cursor["id"] in seen:
            raise ApiError(ERR_SELF_STACK_CYCLE)
        seen.add(cursor["id"])
        nxt = cursor.get("stacks_on_rule_id")
        cursor = DB.rules.get(nxt) if nxt else None
    return parent


def _window_conflict(candidate, exclude_id=None):
    """No non-RETIRED rule of the same kind may approach within one day."""
    start = parse_ts(candidate["effective_from"])
    end = parse_ts(candidate["effective_to"])
    if start is None or end is None:
        raise ApiError(ERR_INVALID_STATE)
    for row in DB.rules.values():
        if row["id"] == exclude_id:
            continue
        if row["status"] == "RETIRED" or row["id"] == candidate.get("id"):
            continue
        if row["discount_kind"] != candidate["discount_kind"]:
            continue
        r_start = parse_ts(row["effective_from"])
        r_end = parse_ts(row["effective_to"])
        if r_start is None or r_end is None:
            continue
        if start <= r_end and r_start <= end:
            raise ApiError(ERR_RULE_WINDOW_OVERLAP)
        if start >= r_end:
            gap = (start - r_end).total_seconds() / 86400.0
        else:
            gap = (r_start - end).total_seconds() / 86400.0
        if gap < OVERLAP_MIN_GAP_DAYS:
            raise ApiError(ERR_RULE_WINDOW_OVERLAP)
    return


@BP.route("/benefits/rate-discount-rules", methods=["POST"])
def create_rule():
    auth(("BenefitsAdmin",))
    payload = raw_body()
    reject_unknown(payload, CREATE_ALLOWED)
    require_fields(
        payload,
        ("rule_code", "discount_kind", "stacking_class", "discount_bps", "effective_from",
         "effective_to"),
    )
    rule_code = as_string(payload, "rule_code")
    discount_kind = as_enum(payload, "discount_kind", DISCOUNT_KINDS)
    stacking_class = as_enum(payload, "stacking_class", STACKING_CLASSES)
    discount_bps = as_int(payload, "discount_bps", minimum=0)
    effective_from = as_timestamp(payload, "effective_from")
    effective_to = as_timestamp(payload, "effective_to")
    if parse_ts(effective_from) >= parse_ts(effective_to):
        raise ApiError(ERR_INVALID_STATE)
    requires_direct_deposit = as_bool(payload, "requires_direct_deposit", default=False)
    min_member_tier = as_enum(payload, "min_member_tier", TIERS, required=False, default="NONE")
    stacks_on_rule_id = None
    if payload.get("stacks_on_rule_id") is not None:
        stacks_on_rule_id = as_string(payload, "stacks_on_rule_id")

    for existing in DB.rules.values():
        if existing["rule_code"] == rule_code:
            raise ApiError(ERR_DUPLICATE_RULE_CODE)

    candidate = {
        "id": None,
        "rule_code": rule_code,
        "discount_kind": discount_kind,
        "stacking_class": stacking_class,
        "discount_bps": discount_bps,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "stacks_on_rule_id": stacks_on_rule_id,
        "requires_direct_deposit": requires_direct_deposit,
        "min_member_tier": min_member_tier,
        "status": "DRAFT",
    }
    if stacks_on_rule_id is not None:
        _stack_chain_ok(None, stacks_on_rule_id)
    _window_conflict(candidate)

    rule = mk("rules", **{k: v for k, v in candidate.items() if k != "id"})
    return ok_object(serialize.rule(rule)), 201


@BP.route("/benefits/rate-discount-rules", methods=["GET"])
def list_rules():
    auth(("PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer", "Underwriter"))
    items = list(DB.rules.values())
    filters = {
        "discount_kind": "discount_kind",
        "status": "status",
        "stacks_on_rule_id": "stacks_on_rule_id",
    }
    return list_response(items, serialize.rule, filters)


@BP.route("/benefits/rate-discount-rules/<rule_id>", methods=["GET"])
def get_rule(rule_id):
    auth(("PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer", "Underwriter"))
    rule = fetch("rules", rule_id)
    return ok_object(serialize.rule(rule))


@BP.route("/benefits/rate-discount-rules/<rule_id>", methods=["PUT"])
def edit_rule(rule_id):
    auth(("BenefitsAdmin",))
    rule = fetch("rules", rule_id)
    if rule["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE)
    payload = raw_body()
    reject_unknown(payload, EDIT_ALLOWED)
    if not payload:
        raise ApiError(ERR_INVALID_STATE)

    candidate = dict(rule)
    if "discount_bps" in payload:
        candidate["discount_bps"] = as_int(payload, "discount_bps", minimum=0)
    if "effective_to" in payload:
        candidate["effective_to"] = as_timestamp(payload, "effective_to")
    if "stacks_on_rule_id" in payload:
        if payload["stacks_on_rule_id"] is None:
            candidate["stacks_on_rule_id"] = None
        else:
            candidate["stacks_on_rule_id"] = as_string(payload, "stacks_on_rule_id")
            _stack_chain_ok(rule["id"], candidate["stacks_on_rule_id"])
    if parse_ts(candidate["effective_from"]) >= parse_ts(candidate["effective_to"]):
        raise ApiError(ERR_INVALID_STATE)
    _window_conflict(candidate, exclude_id=rule["id"])

    for key in ("discount_bps", "effective_to", "stacks_on_rule_id"):
        if key in payload:
            rule[key] = candidate[key]
    from db import touch

    touch(rule, DB.clock())
    return ok_object(serialize.rule(rule))


@BP.route("/benefits/rate-discount-rules/<rule_id>/activate", methods=["POST"])
def activate_rule(rule_id):
    auth(("BenefitsAdmin",))
    rule = fetch("rules", rule_id)
    if rule["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE)
    parent_id = rule.get("stacks_on_rule_id")
    if parent_id:
        parent = DB.rules.get(parent_id)
        if parent is None or parent["status"] == "DRAFT":
            raise ApiError(ERR_ACTIVE_RULE_ON_UNPRICED_LOAN)
    _window_conflict(rule, exclude_id=rule["id"])
    rule["status"] = "ACTIVE"
    from db import touch

    touch(rule, DB.clock())
    recompute.refresh_all_members()
    for member_id in list(DB.members.keys()):
        recompute.materialise_live_applications(member_id)
    recompute.reprice_all_loans()
    return ok_object(serialize.rule(rule))


@BP.route("/benefits/rate-discount-rules/<rule_id>/retire", methods=["POST"])
def retire_rule(rule_id):
    auth(("BenefitsAdmin",))
    rule = fetch("rules", rule_id)
    if rule["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE)
    now = DB.clock()
    rule["status"] = "RETIRED"
    from db import touch

    touch(rule, now)
    _reap_applications(now)
    for app in calc.applications_of_rule(rule_id):
        if app["application_state"] == "APPLIED":
            applied_at = parse_ts(app.get("applied_at"))
            if applied_at is None or applied_at < now:
                app["application_state"] = "ROLLED_BACK"
                app["preempted_by_application_id"] = None
                touch(app, now)
    recompute.reprice_all_loans()
    return ok_object(serialize.rule(rule))


def _reap_applications(now):
    """Drop any application whose rule is no longer live from its loan's stack."""
    for loan in DB.loan_accounts.values():
        survivors = {r["id"] for r in calc.survivor_rules(loan)}
        for app in calc.applications_of(loan["id"]):
            if app["application_state"] != "APPLIED":
                continue
            rule = DB.rules.get(app["rule_id"])
            if rule is None or rule["status"] != "ACTIVE" or app["rule_id"] not in survivors:
                app["application_state"] = "ROLLED_BACK"
                app["preempted_by_application_id"] = None
                from db import touch as _touch

                _touch(app, now)