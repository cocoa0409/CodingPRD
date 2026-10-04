"""Admin routes: clock, appetite rules, class codes."""
from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
from services import policy_ops
from services import serialize as ser
from services import audit as aud

bp = Blueprint("admin", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@bp.post("/ins/_clock/set_current_utc")
def set_clock():
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin")
    body = _body()
    errors.reject_unknown_keys(body, ("to_iso8601",))
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise errors.validation("to_iso8601 is required")
    try:
        dt = db.parse_iso(to_iso)
    except (ValueError, TypeError):
        raise errors.validation("to_iso8601 must be an ISO8601 string")
    db.set_clock(dt)
    events = policy_ops.advance_transitions()
    for etype, ent, action in events:
        aud.record(actor.role, actor.user_id, etype, ent["id"], action,
                   before={}, after={"status": ent["status"]})
    return resp.ok_object({"current_utc": db.fmt_iso(db.clock_now())})


# ---------------------------------------------------------------------------
# Appetite rules
# ---------------------------------------------------------------------------
@bp.post("/ins/appetite-rules")
def create_appetite_rule():
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin")
    body = _body()
    errors.reject_unknown_keys(body, (
        "keyword", "class_code", "disposition", "effective_from",
        "effective_to", "priority_rank", "is_enabled",
    ))
    keyword = body.get("keyword")
    class_code = body.get("class_code")
    disposition = body.get("disposition")
    effective_from = body.get("effective_from")
    effective_to = body.get("effective_to")
    priority_rank = body.get("priority_rank")
    is_enabled = body.get("is_enabled", True)

    if not isinstance(keyword, str) or not keyword:
        raise errors.validation("keyword is required")
    if not isinstance(class_code, str) or not class_code:
        raise errors.validation("class_code is required")
    if disposition not in ("ADMIT", "REFER", "DECLINE"):
        raise errors.validation("disposition must be ADMIT, REFER or DECLINE")
    if not isinstance(priority_rank, int) or isinstance(priority_rank, bool):
        raise errors.validation("priority_rank must be an integer")
    if not isinstance(is_enabled, bool):
        raise errors.validation("is_enabled must be a boolean")
    try:
        ef = db.parse_iso(effective_from)
        et = db.parse_iso(effective_to)
    except (ValueError, TypeError):
        raise errors.validation("effective_from/effective_to must be ISO8601 strings")
    if not ef < et:
        raise errors.appetite_window_invalid()

    rec = {
        "id": db.new_id(),
        "keyword": keyword.lower(),
        "class_code": class_code,
        "disposition": disposition,
        "effective_from": db.fmt_iso(ef),
        "effective_to": db.fmt_iso(et),
        "is_enabled": is_enabled,
        "priority_rank": priority_rank,
        "created_at": db.fmt_iso(db.clock_now()),
        "updated_at": db.fmt_iso(db.clock_now()),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.appetite_rules[rec["id"]] = rec
    aud.record(actor.role, actor.user_id, "AppetiteRule", rec["id"], "create",
               after=ser.public(rec))
    return resp.ok_object(ser.public(rec), status=201)


@bp.get("/ins/appetite-rules")
def list_appetite_rules():
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Underwriter", "ComplianceOfficer")
    class_code = request.args.get("class_code")
    disposition = request.args.get("disposition")
    include_disabled = request.args.get("include_disabled", "false").lower() == "true"
    items = list(db.appetite_rules.values())
    if class_code is not None:
        items = [r for r in items if r["class_code"] == class_code]
    if disposition is not None:
        items = [r for r in items if r["disposition"] == disposition]
    if not include_disabled:
        items = [r for r in items if r["is_enabled"]]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.patch("/ins/appetite-rules/<rid>")
def patch_appetite_rule(rid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin")
    rec = db.appetite_rules.get(rid)
    if rec is None:
        raise errors.not_found("Appetite rule not found")
    body = _body()
    allowed = {"is_enabled", "effective_from", "effective_to", "disposition"}
    unknown = set(body.keys()) - allowed
    if unknown:
        raise errors.validation(f"Unknown fields: {sorted(unknown)}")
    before = ser.public(rec)
    new_ef = rec["effective_from"]
    new_et = rec["effective_to"]
    if "effective_from" in body:
        try:
            new_ef = db.fmt_iso(db.parse_iso(body["effective_from"]))
        except (ValueError, TypeError):
            raise errors.validation("effective_from must be ISO8601")
    if "effective_to" in body:
        try:
            new_et = db.fmt_iso(db.parse_iso(body["effective_to"]))
        except (ValueError, TypeError):
            raise errors.validation("effective_to must be ISO8601")
    if db.parse_iso(new_ef) >= db.parse_iso(new_et):
        raise errors.appetite_window_invalid()
    if "is_enabled" in body:
        if not isinstance(body["is_enabled"], bool):
            raise errors.validation("is_enabled must be a boolean")
        rec["is_enabled"] = body["is_enabled"]
    if "disposition" in body:
        if body["disposition"] not in ("ADMIT", "REFER", "DECLINE"):
            raise errors.validation("disposition must be ADMIT, REFER or DECLINE")
        rec["disposition"] = body["disposition"]
    rec["effective_from"] = new_ef
    rec["effective_to"] = new_et
    rec["updated_at"] = db.fmt_iso(db.clock_now())
    rec["version"] += 1
    aud.record(actor.role, actor.user_id, "AppetiteRule", rec["id"], "update",
               before=before, after=ser.public(rec))
    return resp.ok_object(ser.public(rec))


# ---------------------------------------------------------------------------
# Class codes
# ---------------------------------------------------------------------------
@bp.post("/ins/class-codes")
def create_class_code():
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin")
    body = _body()
    errors.reject_unknown_keys(body, (
        "code", "description", "eligible_lines", "base_rates_cents",
        "risk_factor", "appetite_active",
    ))
    code = body.get("code")
    description = body.get("description")
    eligible_lines = body.get("eligible_lines")
    base_rates = body.get("base_rates_cents")
    risk_factor = body.get("risk_factor")
    appetite_active = body.get("appetite_active", True)

    if not isinstance(code, str) or not code:
        raise errors.validation("code is required")
    if any(c["code"] == code for c in db.class_codes.values()):
        raise errors.validation("code must be unique")
    if not isinstance(description, str):
        raise errors.validation("description is required")
    if (not isinstance(eligible_lines, list) or not eligible_lines
            or any(l not in ("GL", "PL", "TOOLS") for l in eligible_lines)):
        raise errors.validation("eligible_lines must be a non-empty subset of GL/PL/TOOLS")
    if not isinstance(base_rates, dict):
        raise errors.validation("base_rates_cents must be an object")
    if set(base_rates.keys()) != set(eligible_lines):
        raise errors.validation("base_rates_cents keys must equal eligible_lines members")
    for v in base_rates.values():
        if not isinstance(v, int) or isinstance(v, bool):
            raise errors.validation("base_rates_cents values must be integer cents")
    if not isinstance(risk_factor, (int, float)) or isinstance(risk_factor, bool):
        raise errors.validation("risk_factor must be a number")
    if risk_factor < 0.25 or risk_factor > 4.00:
        raise errors.validation("risk_factor must be between 0.25 and 4.00")
    if not isinstance(appetite_active, bool):
        raise errors.validation("appetite_active must be a boolean")

    rec = {
        "id": db.new_id(),
        "code": code,
        "description": description,
        "eligible_lines": list(eligible_lines),
        "base_rates_cents": dict(base_rates),
        "risk_factor": risk_factor,
        "appetite_active": appetite_active,
        "created_at": db.fmt_iso(db.clock_now()),
        "updated_at": db.fmt_iso(db.clock_now()),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.class_codes[rec["id"]] = rec
    aud.record(actor.role, actor.user_id, "ClassCode", rec["id"], "create",
               after=ser.public(rec))
    return resp.ok_object(ser.public(rec), status=201)


@bp.get("/ins/class-codes")
def list_class_codes():
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Underwriter", "ComplianceOfficer",
                    "Policyholder", "Agent", "PartnerPlatform")
    items = list(db.class_codes.values())
    af = request.args.get("appetite_active")
    if af is not None:
        want = af.lower() == "true"
        items = [c for c in items if c["appetite_active"] == want]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.get("/ins/class-codes/<cid>")
def get_class_code(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Underwriter", "ComplianceOfficer",
                    "Policyholder", "Agent", "PartnerPlatform")
    rec = db.class_codes.get(cid)
    if rec is None:
        raise errors.not_found("Class code not found")
    return resp.ok_object(ser.public(rec))


@bp.get("/ins/class-codes/<cid>/appetite-rules")
def class_appetite_rules(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Underwriter", "ComplianceOfficer")
    rec = db.class_codes.get(cid)
    if rec is None:
        raise errors.not_found("Class code not found")
    items = [r for r in db.appetite_rules.values() if r["class_code"] == rec["code"]]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.get("/ins/class-codes/<cid>/policies")
def class_policies(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Underwriter", "ComplianceOfficer")
    rec = db.class_codes.get(cid)
    if rec is None:
        raise errors.not_found("Class code not found")
    items = [p for p in db.policies.values() if p["class_code_id"] == cid]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.patch("/ins/class-codes/<cid>")
def patch_class_code(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin")
    rec = db.class_codes.get(cid)
    if rec is None:
        raise errors.not_found("Class code not found")
    body = _body()
    allowed = {"appetite_active", "base_rates_cents", "risk_factor"}
    unknown = set(body.keys()) - allowed
    if unknown:
        raise errors.validation(f"Unknown fields: {sorted(unknown)}")
    before = ser.public(rec)
    was_active = rec["appetite_active"]
    if "appetite_active" in body:
        if not isinstance(body["appetite_active"], bool):
            raise errors.validation("appetite_active must be a boolean")
        rec["appetite_active"] = body["appetite_active"]
    if "base_rates_cents" in body:
        br = body["base_rates_cents"]
        if not isinstance(br, dict) or set(br.keys()) != set(rec["eligible_lines"]):
            raise errors.validation("base_rates_cents keys must equal eligible_lines members")
        rec["base_rates_cents"] = dict(br)
    if "risk_factor" in body:
        rf = body["risk_factor"]
        if not isinstance(rf, (int, float)) or isinstance(rf, bool) or rf < 0.25 or rf > 4.00:
            raise errors.validation("risk_factor must be between 0.25 and 4.00")
        rec["risk_factor"] = rf
    rec["updated_at"] = db.fmt_iso(db.clock_now())
    rec["version"] += 1
    aud.record(actor.role, actor.user_id, "ClassCode", rec["id"], "update",
               before=before, after=ser.public(rec))

    # appetite_active true -> false: auto non-renewal notices for in-window
    # ACTIVE policies of this class with no notice yet, when statutory
    # window (>=45 days for APPETITE_CHANGE) is still satisfiable.
    if was_active and not rec["appetite_active"]:
        now = db.clock_now()
        for p in db.policies.values():
            if p["class_code_id"] != rec["id"] or p["status"] != "ACTIVE":
                continue
            if p["non_renewal_notice_sent_at"] is not None:
                continue
            rws = db.parse_iso(p["renewal_window_start"])
            if now < rws:
                continue
            te = db.parse_iso(p["term_end"])
            days_left = db.day_of(te) - db.day_of(now)
            if days_left < 45:
                continue  # statutory window not satisfiable; runs to expiry
            notice = {
                "id": db.new_id(),
                "policy_id": p["id"],
                "reason_code": "APPETITE_CHANGE",
                "sent_at": db.fmt_iso(now),
                "days_before_term_end": days_left,
                "created_at": db.fmt_iso(now),
                "updated_at": db.fmt_iso(now),
                "version": 1,
                "_seq": db.next_seq(),
            }
            db.non_renewal_notices[notice["id"]] = notice
            pb = ser.public(p)
            p["non_renewal_notice_sent_at"] = notice["sent_at"]
            p["status"] = "NON_RENEWAL_PENDING"
            p["updated_at"] = db.fmt_iso(now)
            p["version"] += 1
            aud.record(actor.role, actor.user_id, "NonRenewalNotice", notice["id"],
                       "auto_issue", after=ser.public(notice))
            aud.record(actor.role, actor.user_id, "Policy", p["id"],
                       "non_renewal_pending", before=pb, after=ser.public(p))

    return resp.ok_object(ser.public(rec))
