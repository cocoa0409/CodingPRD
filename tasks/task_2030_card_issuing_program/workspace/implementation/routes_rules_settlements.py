"""AuthorizationRule and Settlement endpoints."""
from flask import Blueprint, request

from core import (
    STORE, ApiError, ok, ok_list, body, req_field, req_int, req_enum,
    new_entity, new_append_only, touch, pub, sort_created, get_or_404,
    require_roles, fmt_dt, now, account_of, program_of_account,
    qualification_tier, interchange_cents, emv_capable,
    RULE_KINDS, MCC_RE, COUNTRY_RE,
)

bp = Blueprint("rules_settlements", __name__)

RULE_READ = ("ComplianceOfficer", "ProgramManager", "PlatformAdmin")
SETTLE_RW = ("PlatformAdmin", "FinanceController")


# ---------------------------------------------------------------------------
# AuthorizationRule
# ---------------------------------------------------------------------------

def _validate_rule_shape(data, existing=None):
    """Validate kind-specific fields. `existing` allows partial PUT payloads."""
    kind = data.get("rule_kind") or (existing or {}).get("rule_kind")
    merged = dict(existing or {})
    merged.update({k: v for k, v in data.items() if v is not None})
    if kind == "VELOCITY":
        for f, lo in (("window_seconds", 1), ("max_txn_count", 1),
                      ("max_amount_cents", 1)):
            v = merged.get(f)
            if isinstance(v, bool) or not isinstance(v, int) or v < lo:
                raise ApiError("ERR_VALIDATION", 400,
                               "VELOCITY rule requires %s >= 1" % f)
    elif kind in ("MCC_ALLOW", "MCC_BLOCK"):
        lst = merged.get("mcc_list")
        if not isinstance(lst, list) or not lst or \
                any(not isinstance(m, str) or not MCC_RE.match(m) for m in lst):
            raise ApiError("ERR_VALIDATION", 400,
                           "%s rule requires a non-empty mcc_list of 4-digit strings"
                           % kind)
    elif kind == "GEO_BLOCK":
        lst = merged.get("country_code_list")
        if not isinstance(lst, list) or not lst or \
                any(not isinstance(c, str) or not COUNTRY_RE.match(c) for c in lst):
            raise ApiError("ERR_VALIDATION", 400,
                           "GEO_BLOCK rule requires a non-empty country_code_list")
    return kind


@bp.post("/issuing/authorization-rules")
@require_roles("ComplianceOfficer")
def create_rule():
    data = body()
    subject_kind = req_enum(data, "subject_kind", ("PROGRAM", "ACCOUNT"))
    subject_ref = req_field(data, "subject_ref")
    if subject_kind == "PROGRAM":
        if not isinstance(subject_ref, str) or subject_ref not in STORE["programs"]:
            raise ApiError("ERR_INVALID_REFERENCE", 422,
                           "subject_ref does not resolve to an existing program")
    else:
        if not isinstance(subject_ref, str) or subject_ref not in STORE["accounts"]:
            raise ApiError("ERR_INVALID_REFERENCE", 422,
                           "subject_ref does not resolve to an existing account")
    rule_kind = req_enum(data, "rule_kind", RULE_KINDS)
    _validate_rule_shape({"rule_kind": rule_kind, **data})
    priority_rank = req_int(data, "priority_rank")
    r = new_entity()
    r.update({
        "subject_kind": subject_kind,
        "subject_ref": subject_ref,
        "rule_kind": rule_kind,
        "window_seconds": data.get("window_seconds"),
        "max_txn_count": data.get("max_txn_count"),
        "max_amount_cents": data.get("max_amount_cents"),
        "mcc_list": data.get("mcc_list"),
        "country_code_list": data.get("country_code_list"),
        "priority_rank": priority_rank,
        "status": "DRAFT",
    })
    STORE["rules"][r["id"]] = r
    return ok(pub(r), 201)


@bp.get("/issuing/authorization-rules")
@require_roles(*RULE_READ)
def list_rules():
    items = list(STORE["rules"].values())
    for param in ("subject_kind", "subject_ref", "rule_kind", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r.get(param) == val]
    return ok_list([pub(r) for r in sort_created(items)])


def _get_rule(rid):
    return get_or_404("rules", rid, "authorization rule")


@bp.get("/issuing/authorization-rules/<rid>")
@require_roles(*RULE_READ)
def get_rule(rid):
    return ok(pub(_get_rule(rid)))


@bp.put("/issuing/authorization-rules/<rid>")
@require_roles("ComplianceOfficer")
def edit_rule(rid):
    r = _get_rule(rid)
    if r["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only DRAFT rules may be edited")
    data = body()
    merged = dict(r)
    for f in ("window_seconds", "max_txn_count", "max_amount_cents",
              "mcc_list", "country_code_list", "priority_rank"):
        if f in data and data[f] is not None:
            merged[f] = data[f]
    _validate_rule_shape(merged, existing=r)
    if not isinstance(merged.get("priority_rank"), int) or \
            isinstance(merged.get("priority_rank"), bool):
        raise ApiError("ERR_VALIDATION", 400, "priority_rank must be an integer")
    for f in ("window_seconds", "max_txn_count", "max_amount_cents",
              "mcc_list", "country_code_list", "priority_rank"):
        if f in data and data[f] is not None:
            r[f] = data[f]
    touch(r)
    return ok(pub(r))


@bp.post("/issuing/authorization-rules/<rid>/activate")
@require_roles("ComplianceOfficer")
def activate_rule(rid):
    r = _get_rule(rid)
    data = body()
    if "expected_rule_version" not in data or data["expected_rule_version"] is None:
        raise ApiError("ERR_MISSING_OCC_FIELD", 400,
                       "expected_rule_version is required")
    if data["expected_rule_version"] != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_rule_version does not match current version")
    if r["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "rule activation requires status DRAFT")
    if r["subject_kind"] == "PROGRAM":
        prog = STORE["programs"].get(r["subject_ref"])
        if prog is not None and prog["authorization_rules_locked"]:
            raise ApiError("ERR_PROGRAM_RULES_LOCKED", 409,
                           "program authorization rules are locked")
        if prog is not None and prog["posture"] not in ("DRAFT", "LIVE"):
            raise ApiError("ERR_PROGRAM_NOT_EDITABLE", 409,
                           "program posture must be DRAFT or LIVE")
    else:
        acct = STORE["accounts"].get(r["subject_ref"])
        if acct is not None and \
                acct["lifecycle_status"] not in ("OPEN", "SUSPENDED"):
            raise ApiError("ERR_ACCOUNT_TERMINAL_STATE", 409,
                           "account must be OPEN or SUSPENDED")
    if r["rule_kind"] == "VELOCITY":
        for f in ("window_seconds", "max_txn_count", "max_amount_cents"):
            v = r.get(f)
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise ApiError("ERR_VALIDATION", 400,
                               "VELOCITY rule fields do not satisfy their minima")
    r["status"] = "ACTIVE"
    touch(r)
    return ok(pub(r))


@bp.post("/issuing/authorization-rules/<rid>/retire")
@require_roles("ComplianceOfficer")
def retire_rule(rid):
    r = _get_rule(rid)
    if r["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "retire requires status DRAFT or ACTIVE")
    r["status"] = "RETIRED"
    touch(r)
    return ok(pub(r))


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

def _get_event(eid):
    return get_or_404("events", eid, "authorization event")


@bp.post("/issuing/authorization-events/<eid>/settle")
@require_roles(*SETTLE_RW)
def settle_event(eid):
    e = _get_event(eid)
    if e["decision"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only APPROVED authorization events may be settled")
    for s in STORE["settlements"].values():
        if s["authorization_event_id"] == eid:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "authorization event is already settled")
    data = body()
    settled_amount = req_int(data, "settled_amount_cents", min_value=1)
    card = STORE["cards"].get(e["card_id"])
    acct = STORE["accounts"].get(e["account_id"])
    prog = STORE["programs"].get(e["program_id"]) if e.get("program_id") else None
    settled_at = now()
    chip = emv_capable(card) if card else False
    network = prog["network"] if prog else "VISA"
    product_class = prog["product_class"] if prog else "CONSUMER_PREPAID"
    tier = qualification_tier(network, e["mcc"], e["_authorized_at"], settled_at, chip)
    interchange = interchange_cents(settled_amount, network, tier, product_class)
    if acct is not None and settled_amount < e["amount_cents"]:
        acct["available_balance_cents"] += e["amount_cents"] - settled_amount
        touch(acct)
    s = new_append_only()
    s.update({
        "authorization_event_id": eid,
        "card_id": e["card_id"],
        "account_id": e["account_id"],
        "settled_amount_cents": settled_amount,
        "interchange_cents": interchange,
        "qualification_tier": tier,
        "settled_at": fmt_dt(settled_at),
        "_settled_at": settled_at,
        "_program_id": e.get("program_id"),
    })
    STORE["settlements"][s["id"]] = s
    return ok(pub(s), 201)


def _get_settlement(sid):
    return get_or_404("settlements", sid, "settlement")


@bp.get("/issuing/settlements/<sid>")
@require_roles("FinanceController", "PlatformAdmin")
def get_settlement(sid):
    return ok(pub(_get_settlement(sid)))


@bp.get("/issuing/cards/<cid>/settlements")
@require_roles("FinanceController", "PlatformAdmin")
def list_card_settlements(cid):
    get_or_404("cards", cid, "card")
    items = [s for s in STORE["settlements"].values() if s["card_id"] == cid]
    tier = request.args.get("qualification_tier")
    if tier is not None:
        items = [s for s in items if s["qualification_tier"] == tier]
    return ok_list([pub(s) for s in sort_created(items)])


@bp.get("/issuing/accounts/<aid>/settlements")
@require_roles("FinanceController", "PlatformAdmin")
def list_account_settlements(aid):
    get_or_404("accounts", aid, "account")
    items = [s for s in STORE["settlements"].values() if s["account_id"] == aid]
    return ok_list([pub(s) for s in sort_created(items)])


@bp.get("/issuing/authorization-events/<eid>")
@require_roles("FinanceController", "PlatformAdmin", "ProgramManager",
               "ComplianceOfficer")
def get_event(eid):
    return ok(pub(_get_event(eid)))


@bp.get("/issuing/authorization-events/<eid>/settlements")
@require_roles("FinanceController", "PlatformAdmin")
def list_event_settlements(eid):
    _get_event(eid)
    items = [s for s in STORE["settlements"].values()
             if s["authorization_event_id"] == eid]
    return ok_list([pub(s) for s in sort_created(items)])
