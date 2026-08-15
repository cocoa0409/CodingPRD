"""CardAccount, Card, PIN, activation token, and authorization endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from core import (
    STORE, ApiError, ok, ok_list, body, req_field, req_int, opt_int, req_enum,
    new_entity, new_append_only, touch, pub, sort_created, get_or_404,
    require_roles, fmt_dt, now, create_card, matching_rules,
    approved_events_in_window, account_of, program_of_account,
    ACCOUNT_CLASSES, FORM_FACTORS, PIN_RE, MCC_RE, COUNTRY_RE,
    T1_SECONDS,
)

bp = Blueprint("accounts_cards", __name__)

ACCOUNT_READ = ("ProgramManager", "OperationsAnalyst", "FinanceController",
                "PlatformAdmin")
CARD_READ = ("ProgramManager", "OperationsAnalyst", "CardholderOps", "PlatformAdmin")
EVENT_READ = ("ProgramManager", "OperationsAnalyst", "ComplianceOfficer",
              "PlatformAdmin")


def _get_account(aid):
    return get_or_404("accounts", aid, "account")


def _get_card(cid):
    return get_or_404("cards", cid, "card")


# ---------------------------------------------------------------------------
# CardAccount
# ---------------------------------------------------------------------------

@bp.post("/issuing/accounts")
@require_roles("ProgramManager")
def create_account():
    data = body()
    program_id = req_field(data, "program_id")
    prog = STORE["programs"].get(program_id) if isinstance(program_id, str) else None
    if prog is None:
        raise ApiError("ERR_INVALID_REFERENCE", 422,
                       "program_id does not resolve to an existing program")
    ref = req_field(data, "external_account_ref")
    if not isinstance(ref, str) or not ref:
        raise ApiError("ERR_VALIDATION", 400,
                       "external_account_ref must be a non-empty string")
    account_class = req_enum(data, "account_class", ACCOUNT_CLASSES)
    credit_limit = opt_int(data, "credit_limit_cents", default=0, min_value=0)
    if prog["product_class"] != "COMMERCIAL_CREDIT" and credit_limit != 0:
        raise ApiError("ERR_VALIDATION", 400,
                       "credit_limit_cents must be 0 outside COMMERCIAL_CREDIT programs")
    cap = req_int(data, "daily_spend_cap_cents", min_value=0)
    if cap > prog["daily_spend_cap_cents"]:
        raise ApiError("ERR_VALIDATION", 400,
                       "daily_spend_cap_cents must not exceed the program cap")
    for a in STORE["accounts"].values():
        if a["program_id"] == program_id and a["external_account_ref"] == ref:
            raise ApiError("ERR_VALIDATION", 409,
                           "external_account_ref must be unique within the program")
    a = new_entity()
    a.update({
        "program_id": program_id,
        "external_account_ref": ref,
        "account_class": account_class,
        "currency_code": prog["currency_code"],
        "credit_limit_cents": credit_limit,
        "available_balance_cents": 0,
        "lifecycle_status": "ONBOARDING",
        "risk_tier": "STANDARD",
        "daily_spend_cap_cents": cap,
    })
    STORE["accounts"][a["id"]] = a
    return ok(pub(a), 201)


@bp.get("/issuing/accounts")
@require_roles(*ACCOUNT_READ)
def list_accounts():
    items = list(STORE["accounts"].values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    lifecycle = request.args.get("lifecycle_status")
    if lifecycle is not None:
        items = [a for a in items if a["lifecycle_status"] == lifecycle]
    return ok_list([pub(a) for a in sort_created(items)])


@bp.get("/issuing/programs/<pid>/accounts")
@require_roles(*ACCOUNT_READ)
def list_program_accounts(pid):
    get_or_404("programs", pid, "program")
    items = [a for a in STORE["accounts"].values() if a["program_id"] == pid]
    lifecycle = request.args.get("lifecycle_status")
    if lifecycle is not None:
        items = [a for a in items if a["lifecycle_status"] == lifecycle]
    return ok_list([pub(a) for a in sort_created(items)])


@bp.get("/issuing/accounts/<aid>")
@require_roles(*ACCOUNT_READ)
def get_account(aid):
    return ok(pub(_get_account(aid)))


@bp.put("/issuing/accounts/<aid>")
@require_roles("ProgramManager")
def update_account(aid):
    a = _get_account(aid)
    data = body()
    if "expected_account_version" not in data or data["expected_account_version"] is None:
        raise ApiError("ERR_MISSING_OCC_FIELD", 400,
                       "expected_account_version is required")
    if data["expected_account_version"] != a["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_account_version does not match current version")
    prog = STORE["programs"].get(a["program_id"])
    if "daily_spend_cap_cents" in data and data["daily_spend_cap_cents"] is not None:
        v = data["daily_spend_cap_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ApiError("ERR_VALIDATION", 400,
                           "daily_spend_cap_cents must be a non-negative integer")
        if prog is not None and v > prog["daily_spend_cap_cents"]:
            raise ApiError("ERR_VALIDATION", 400,
                           "daily_spend_cap_cents must not exceed the program cap")
        a["daily_spend_cap_cents"] = v
    if "credit_limit_cents" in data and data["credit_limit_cents"] is not None:
        v = data["credit_limit_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ApiError("ERR_VALIDATION", 400,
                           "credit_limit_cents must be a non-negative integer")
        if prog is not None and prog["product_class"] != "COMMERCIAL_CREDIT" and v != 0:
            raise ApiError("ERR_VALIDATION", 400,
                           "credit_limit_cents must be 0 outside COMMERCIAL_CREDIT programs")
        a["credit_limit_cents"] = v
    touch(a)
    return ok(pub(a))


@bp.post("/issuing/accounts/<aid>/activate")
@require_roles("ProgramManager")
def activate_account(aid):
    a = _get_account(aid)
    if a["lifecycle_status"] != "ONBOARDING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "account activation requires status ONBOARDING")
    prog = STORE["programs"].get(a["program_id"])
    if prog is None or prog["posture"] != "LIVE":
        raise ApiError("ERR_PROGRAM_NOT_LIVE", 409,
                       "account activation requires program posture LIVE")
    has_capacity = any(
        br["program_id"] == prog["id"] and br["status"] == "ACTIVE" and
        (br["range_size"] - br["pans_allocated"]) >= 1
        for br in STORE["bin_ranges"].values())
    if not has_capacity:
        raise ApiError("ERR_NO_BIN_CAPACITY", 409,
                       "no ACTIVE BinRange with available PANs under this program")
    a["lifecycle_status"] = "OPEN"
    touch(a)
    return ok(pub(a))


@bp.post("/issuing/accounts/<aid>/suspend")
@require_roles("ProgramManager")
def suspend_account(aid):
    a = _get_account(aid)
    if a["lifecycle_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "suspend requires status OPEN")
    a["lifecycle_status"] = "SUSPENDED"
    for card in STORE["cards"].values():
        if card["account_id"] == aid and card["lifecycle_status"] == "ACTIVE":
            card["lifecycle_status"] = "SUSPENDED"
            touch(card)
    touch(a)
    return ok(pub(a))


@bp.post("/issuing/accounts/<aid>/resume")
@require_roles("ProgramManager")
def resume_account(aid):
    a = _get_account(aid)
    if a["lifecycle_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "resume requires status SUSPENDED")
    prog = STORE["programs"].get(a["program_id"])
    if prog is None or prog["posture"] != "LIVE":
        raise ApiError("ERR_PROGRAM_NOT_LIVE", 409,
                       "account resume requires program posture LIVE")
    a["lifecycle_status"] = "OPEN"
    for card in STORE["cards"].values():
        if card["account_id"] == aid and card["lifecycle_status"] == "SUSPENDED":
            card["lifecycle_status"] = "ACTIVE"
            touch(card)
    touch(a)
    return ok(pub(a))


@bp.post("/issuing/accounts/<aid>/close")
@require_roles("ProgramManager")
def close_account(aid):
    a = _get_account(aid)
    if a["lifecycle_status"] not in ("OPEN", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "close requires status OPEN or SUSPENDED")
    if a["available_balance_cents"] != 0:
        raise ApiError("ERR_ACCOUNT_BALANCE_NONZERO", 409,
                       "account close requires available_balance_cents = 0")
    a["lifecycle_status"] = "CLOSED"
    for card in STORE["cards"].values():
        if card["account_id"] == aid and card["lifecycle_status"] not in (
                "CANCELLED", "EXPIRED", "COMPROMISED"):
            card["lifecycle_status"] = "CANCELLED"
            touch(card)
    touch(a)
    return ok(pub(a))


@bp.post("/issuing/accounts/<aid>/fund")
@require_roles("FinanceController", "PlatformAdmin")
def fund_account(aid):
    a = _get_account(aid)
    data = body()
    amount = req_int(data, "amount_cents", min_value=1)
    a["available_balance_cents"] += amount
    touch(a)
    return ok(pub(a))


# ---------------------------------------------------------------------------
# Card issuance
# ---------------------------------------------------------------------------

@bp.post("/issuing/accounts/<aid>/cards")
@require_roles("ProgramManager")
def issue_card(aid):
    a = _get_account(aid)
    if a["lifecycle_status"] in ("CLOSED", "CONVERTED_OUT"):
        raise ApiError("ERR_ACCOUNT_TERMINAL_STATE", 409,
                       "cannot issue cards on a terminal account")
    prog = STORE["programs"].get(a["program_id"])
    if prog is None or prog["posture"] not in ("DRAFT", "LIVE"):
        raise ApiError("ERR_PROGRAM_NOT_LIVE", 409,
                       "no new cards may be issued under a %s program"
                       % (prog["posture"] if prog else "missing"))
    data = body()
    expiry_month = req_int(data, "expiry_month")
    if expiry_month < 1 or expiry_month > 12:
        raise ApiError("ERR_VALIDATION", 400, "expiry_month must be in 1..12")
    expiry_year = req_int(data, "expiry_year")
    clock = now()
    if expiry_year < clock.year or \
            (expiry_year == clock.year and expiry_month < clock.month):
        raise ApiError("ERR_VALIDATION", 400,
                       "expiry must not be in the past relative to the server clock")
    form_factor = req_enum(data, "form_factor", FORM_FACTORS)

    bin_range_id = data.get("bin_range_id")
    if bin_range_id is not None:
        br = STORE["bin_ranges"].get(bin_range_id) if isinstance(bin_range_id, str) else None
        if br is None or br["program_id"] != prog["id"]:
            raise ApiError("ERR_INVALID_REFERENCE", 422,
                           "bin_range_id does not resolve to a BinRange of this program")
        if not (br["_effective_from"] <= clock < br["_effective_until"]):
            raise ApiError("ERR_BIN_NOT_IN_WINDOW", 409,
                           "BinRange is outside its effective window")
        if br["status"] != "ACTIVE" or \
                (br["range_size"] - br["pans_allocated"]) < 1:
            raise ApiError("ERR_NO_BIN_CAPACITY", 409,
                           "BinRange has no available PANs")
    else:
        candidates = []
        for cand in STORE["bin_ranges"].values():
            if cand["program_id"] != prog["id"] or cand["status"] != "ACTIVE":
                continue
            if (cand["range_size"] - cand["pans_allocated"]) < 1:
                continue
            if not (cand["_effective_from"] <= clock < cand["_effective_until"]):
                continue
            candidates.append(cand)
        candidates.sort(key=lambda c: (c["bin_prefix"], c["_effective_from"],
                                       c["created_at"], c["_seq"]))
        if not candidates:
            raise ApiError("ERR_NO_BIN_CAPACITY", 409,
                           "no ACTIVE BinRange with available PANs under this program")
        br = candidates[0]
    card = create_card(a, br, expiry_month, expiry_year, form_factor)
    return ok(pub(card), 201)


# ---------------------------------------------------------------------------
# Card reads
# ---------------------------------------------------------------------------

@bp.get("/issuing/cards/<cid>")
@require_roles(*CARD_READ)
def get_card(cid):
    return ok(pub(_get_card(cid)))


@bp.get("/issuing/accounts/<aid>/cards")
@require_roles(*CARD_READ)
def list_account_cards(aid):
    _get_account(aid)
    items = [c for c in STORE["cards"].values() if c["account_id"] == aid]
    lifecycle = request.args.get("lifecycle_status")
    if lifecycle is not None:
        items = [c for c in items if c["lifecycle_status"] == lifecycle]
    pin_status = request.args.get("pin_status")
    if pin_status is not None:
        items = [c for c in items if c["pin_status"] == pin_status]
    return ok_list([pub(c) for c in sort_created(items)])


@bp.get("/issuing/bin-ranges/<rid>/cards")
@require_roles("ProgramManager", "OperationsAnalyst", "PlatformAdmin")
def list_bin_range_cards(rid):
    get_or_404("bin_ranges", rid, "bin range")
    items = [c for c in STORE["cards"].values() if c["bin_range_id"] == rid]
    lifecycle = request.args.get("lifecycle_status")
    if lifecycle is not None:
        items = [c for c in items if c["lifecycle_status"] == lifecycle]
    return ok_list([pub(c) for c in sort_created(items)])


@bp.get("/issuing/cards")
@require_roles("ProgramManager", "OperationsAnalyst", "PlatformAdmin")
def list_cards():
    items = list(STORE["cards"].values())
    for param in ("account_id", "bin_range_id", "replaced_by_card_id",
                  "replaced_from_card_id", "reissue_campaign_id",
                  "lifecycle_status"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if c.get(param) == val]
    return ok_list([pub(c) for c in sort_created(items)])


# ---------------------------------------------------------------------------
# Card lifecycle transitions
# ---------------------------------------------------------------------------

@bp.post("/issuing/cards/<cid>/activate")
@require_roles("CardholderOps")
def activate_card(cid):
    card = _get_card(cid)
    if card["lifecycle_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "card activation requires ISSUED")
    acct = account_of(card)
    if acct is None or acct["lifecycle_status"] != "OPEN":
        raise ApiError("ERR_ACCOUNT_NOT_OPEN", 409,
                       "card activation requires account status OPEN")
    data = body()
    token_value = data.get("activation_token")
    clock = now()
    matched = None
    for tok in STORE["tokens"].values():
        if tok["card_id"] == cid and tok["status"] == "PENDING" and \
                tok["_expires_at"] > clock:
            if token_value is not None and tok["token_value"] == token_value:
                matched = tok
                break
    if matched is None:
        raise ApiError("ERR_ACTIVATION_TOKEN_INVALID", 409,
                       "activation_token does not match a PENDING unexpired token")
    if card["pin_status"] != "SET":
        raise ApiError("ERR_PIN_NOT_SET", 409,
                       "card activation requires pin_status SET")
    matched["status"] = "CONSUMED"
    matched["consumed_at"] = fmt_dt(clock)
    touch(matched)
    card["lifecycle_status"] = "ACTIVE"
    touch(card)
    return ok(pub(card))


@bp.post("/issuing/cards/<cid>/suspend")
@require_roles("ProgramManager")
def suspend_card(cid):
    card = _get_card(cid)
    if card["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "suspend requires status ACTIVE")
    card["lifecycle_status"] = "SUSPENDED"
    touch(card)
    return ok(pub(card))


@bp.post("/issuing/cards/<cid>/resume")
@require_roles("ProgramManager")
def resume_card(cid):
    card = _get_card(cid)
    if card["lifecycle_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "resume requires status SUSPENDED")
    acct = account_of(card)
    if acct is None or acct["lifecycle_status"] != "OPEN":
        raise ApiError("ERR_ACCOUNT_NOT_OPEN", 409,
                       "card resume requires account status OPEN")
    card["lifecycle_status"] = "ACTIVE"
    touch(card)
    return ok(pub(card))


@bp.post("/issuing/cards/<cid>/cancel")
@require_roles("ProgramManager")
def cancel_card(cid):
    card = _get_card(cid)
    if card["lifecycle_status"] not in ("ISSUED", "ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "cancel requires status ISSUED, ACTIVE, or SUSPENDED")
    was = card["lifecycle_status"]
    card["lifecycle_status"] = "CANCELLED"
    if was == "ISSUED":
        for tok in STORE["tokens"].values():
            if tok["card_id"] == cid and tok["status"] == "PENDING":
                tok["status"] = "REVOKED"
                touch(tok)
    br = STORE["bin_ranges"].get(card["bin_range_id"])
    if br is not None:
        br["pans_allocated"] = max(0, br["pans_allocated"] - 1)
        touch(br)
    touch(card)
    return ok(pub(card))


@bp.post("/issuing/cards/<cid>/mark_compromised")
@require_roles("ComplianceOfficer")
def compromise_card(cid):
    card = _get_card(cid)
    if card["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "mark_compromised requires status ACTIVE")
    card["lifecycle_status"] = "COMPROMISED"
    clock = now()
    card["_compromised_at"] = clock
    br = STORE["bin_ranges"].get(card["bin_range_id"])
    if br is not None:
        br["pans_allocated"] = max(0, br["pans_allocated"] - 1)
        touch(br)
    touch(card)
    acct = account_of(card)
    if acct is not None:
        window_start = clock - timedelta(days=7)
        recent = [c for c in STORE["cards"].values()
                  if c["account_id"] == acct["id"]
                  and c["lifecycle_status"] == "COMPROMISED"
                  and c.get("_compromised_at") is not None
                  and window_start <= c["_compromised_at"] <= clock]
        if len(recent) >= 3:
            acct["risk_tier"] = "RESTRICTED"
            if acct["lifecycle_status"] == "OPEN":
                acct["lifecycle_status"] = "SUSPENDED"
                for other in STORE["cards"].values():
                    if other["account_id"] == acct["id"] and \
                            other["lifecycle_status"] == "ACTIVE":
                        other["lifecycle_status"] = "SUSPENDED"
                        touch(other)
            touch(acct)
    return ok(pub(card))


# ---------------------------------------------------------------------------
# PIN dimension
# ---------------------------------------------------------------------------

@bp.post("/issuing/cards/<cid>/pin")
@require_roles("CardholderOps")
def set_pin(cid):
    card = _get_card(cid)
    if card["lifecycle_status"] not in ("ISSUED", "ACTIVE"):
        raise ApiError("ERR_CARD_TERMINAL_STATE", 409,
                       "PIN operations are invalid against a terminal card")
    data = body()
    new_pin = req_field(data, "new_pin")
    if not isinstance(new_pin, str) or not PIN_RE.match(new_pin):
        raise ApiError("ERR_PIN_FORMAT_INVALID", 400,
                       "new_pin must be 4-12 digits")
    ps = card["pin_status"]
    if ps == "UNSET":
        card["_pin"] = new_pin
        card["pin_status"] = "SET"
    elif ps == "SET":
        if data.get("current_pin") != card.get("_pin"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "current_pin does not match the stored PIN")
        card["_pin"] = new_pin
    elif ps == "RESET_PENDING":
        card["_pin"] = new_pin
        card["pin_status"] = "SET"
    else:  # BLOCKED
        raise ApiError("ERR_INVALID_STATE", 409,
                       "PIN is BLOCKED; a reset is required first")
    touch(card)
    return ok(pub(card))


@bp.post("/issuing/cards/<cid>/pin_reset_request")
@require_roles("CardholderOps")
def pin_reset_request(cid):
    card = _get_card(cid)
    if card["pin_status"] != "BLOCKED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "pin_reset_request requires pin_status BLOCKED")
    card["pin_status"] = "RESET_PENDING"
    touch(card)
    return ok(pub(card))


@bp.post("/issuing/cards/<cid>/pin_block")
@require_roles("PlatformAdmin")
def pin_block(cid):
    card = _get_card(cid)
    if card["pin_status"] != "SET":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "pin_block requires pin_status SET")
    card["pin_status"] = "BLOCKED"
    touch(card)
    return ok(pub(card))


# ---------------------------------------------------------------------------
# Activation tokens
# ---------------------------------------------------------------------------

@bp.get("/issuing/cards/<cid>/activation-tokens")
@require_roles("CardholderOps", "PlatformAdmin")
def list_activation_tokens(cid):
    _get_card(cid)
    items = [t for t in STORE["tokens"].values() if t["card_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return ok_list([pub(t) for t in sort_created(items)])


# ---------------------------------------------------------------------------
# Authorization events
# ---------------------------------------------------------------------------

def _record_event(card, acct, prog, amount, mcc, country, decision, reason, rule_id):
    e = new_append_only()
    clock = now()
    e.update({
        "card_id": card["id"],
        "account_id": acct["id"],
        "program_id": prog["id"] if prog else None,
        "amount_cents": amount,
        "mcc": mcc,
        "country_code": country,
        "decision": decision,
        "decision_reason": reason,
        "applied_rule_id": rule_id,
        "authorized_at": fmt_dt(clock),
        "_authorized_at": clock,
    })
    STORE["events"][e["id"]] = e
    return e


@bp.post("/issuing/cards/<cid>/authorizations")
@require_roles("CardholderOps", "PlatformAdmin")
def create_authorization(cid):
    card = _get_card(cid)
    data = body()
    amount = req_int(data, "amount_cents", min_value=1)
    mcc = req_field(data, "mcc")
    if not isinstance(mcc, str) or not MCC_RE.match(mcc):
        raise ApiError("ERR_VALIDATION", 400, "mcc must be a 4-digit string")
    country = req_field(data, "country_code")
    if not isinstance(country, str) or not COUNTRY_RE.match(country):
        raise ApiError("ERR_VALIDATION", 400,
                       "country_code must be an ISO 3166-1 alpha-2 code")
    acct = account_of(card)
    prog = program_of_account(acct) if acct else None
    clock = now()

    # State gate: recorded as DECLINED_STATE, returned 201
    if card["lifecycle_status"] != "ACTIVE":
        e = _record_event(card, acct, prog, amount, mcc, country,
                          "DECLINED_STATE", "CARD_NOT_ACTIVE", None)
        return ok(pub(e), 201)
    if acct["lifecycle_status"] != "OPEN":
        e = _record_event(card, acct, prog, amount, mcc, country,
                          "DECLINED_STATE", "ACCOUNT_NOT_OPEN", None)
        return ok(pub(e), 201)

    # Rule gate (MCC_ALLOW / MCC_BLOCK / GEO_BLOCK): recorded DECLINED_RULE, 201
    for rule in matching_rules(card, ("MCC_ALLOW", "MCC_BLOCK", "GEO_BLOCK")):
        decline = False
        reason = None
        if rule["rule_kind"] == "MCC_BLOCK" and mcc in (rule.get("mcc_list") or []):
            decline, reason = True, "RULE_MCC_BLOCK"
        elif rule["rule_kind"] == "MCC_ALLOW" and mcc not in (rule.get("mcc_list") or []):
            decline, reason = True, "RULE_MCC_ALLOW"
        elif rule["rule_kind"] == "GEO_BLOCK" and \
                country in (rule.get("country_code_list") or []):
            decline, reason = True, "RULE_GEO_BLOCK"
        if decline:
            e = _record_event(card, acct, prog, amount, mcc, country,
                              "DECLINED_RULE", reason, rule["id"])
            return ok(pub(e), 201)

    # Fiscal gate 1: funds
    if acct["available_balance_cents"] < amount:
        _record_event(card, acct, prog, amount, mcc, country,
                      "DECLINED_LIMIT", "INSUFFICIENT_FUNDS", None)
        raise ApiError("ERR_INSUFFICIENT_FUNDS", 409,
                       "account available_balance_cents is below amount_cents")

    # Fiscal gate 2: velocity
    for rule in matching_rules(card, ("VELOCITY",)):
        window_start = clock - timedelta(seconds=rule["window_seconds"])
        evs = approved_events_in_window(acct["id"], window_start, clock)
        if len(evs) + 1 > rule["max_txn_count"] or \
                sum(e["amount_cents"] for e in evs) + amount > rule["max_amount_cents"]:
            _record_event(card, acct, prog, amount, mcc, country,
                          "DECLINED_VELOCITY", "VELOCITY_EXCEEDED", rule["id"])
            raise ApiError("ERR_VELOCITY_EXCEEDED", 409,
                           "velocity rule limit exceeded")

    # Fiscal gate 3: daily cap (effective = min(account cap, program cap))
    effective_cap = acct["daily_spend_cap_cents"]
    if prog is not None:
        effective_cap = min(effective_cap, prog["daily_spend_cap_cents"])
    day_events = approved_events_in_window(
        acct["id"], clock - timedelta(seconds=T1_SECONDS), clock)
    if sum(e["amount_cents"] for e in day_events) + amount > effective_cap:
        _record_event(card, acct, prog, amount, mcc, country,
                      "DECLINED_LIMIT", "DAILY_CAP_EXCEEDED", None)
        raise ApiError("ERR_DAILY_CAP_EXCEEDED", 409,
                       "daily spend cap would be exceeded")

    acct["available_balance_cents"] -= amount
    touch(acct)
    e = _record_event(card, acct, prog, amount, mcc, country,
                      "APPROVED", "APPROVED", None)
    return ok(pub(e), 201)


@bp.get("/issuing/cards/<cid>/authorizations")
@require_roles(*EVENT_READ)
def list_card_authorizations(cid):
    _get_card(cid)
    items = [e for e in STORE["events"].values() if e["card_id"] == cid]
    decision = request.args.get("decision")
    if decision is not None:
        items = [e for e in items if e["decision"] == decision]
    return ok_list([pub(e) for e in sort_created(items)])


@bp.get("/issuing/accounts/<aid>/authorization-events")
@require_roles(*EVENT_READ)
def list_account_events(aid):
    _get_account(aid)
    items = [e for e in STORE["events"].values() if e["account_id"] == aid]
    decision = request.args.get("decision")
    if decision is not None:
        items = [e for e in items if e["decision"] == decision]
    return ok_list([pub(e) for e in sort_created(items)])


@bp.get("/issuing/programs/<pid>/authorization-events")
@require_roles(*EVENT_READ)
def list_program_events(pid):
    get_or_404("programs", pid, "program")
    items = [e for e in STORE["events"].values() if e["program_id"] == pid]
    decision = request.args.get("decision")
    if decision is not None:
        items = [e for e in items if e["decision"] == decision]
    return ok_list([pub(e) for e in sort_created(items)])


@bp.get("/issuing/authorization-rules/<rid>/authorization-events")
@require_roles("ComplianceOfficer", "PlatformAdmin")
def list_rule_events(rid):
    get_or_404("rules", rid, "authorization rule")
    items = [e for e in STORE["events"].values() if e.get("applied_rule_id") == rid]
    return ok_list([pub(e) for e in sort_created(items)])
