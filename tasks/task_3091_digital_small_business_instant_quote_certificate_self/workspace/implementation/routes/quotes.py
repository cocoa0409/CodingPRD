"""Quote routes: create (classify/score/route), get, list, bind, referral views."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
from services import underwriting as uw
from services import serialize as ser
from services import audit as aud

bp = Blueprint("quotes", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


def _get_quote(qid):
    q = db.quotes.get(qid)
    if q is None:
        raise errors.not_found("Quote not found")
    return q


def _check_quote_visibility(actor, quote):
    if actor.role == "Policyholder" and actor.user_id != quote["business_account_id"]:
        raise errors.not_found("Quote not found")


@bp.get("/ins/quotes")
def list_quotes():
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Underwriter")
    items = list(db.quotes.values())
    ccid = request.args.get("class_code_id")
    status = request.args.get("status")
    if ccid is not None:
        items = [q for q in items if q.get("class_code_id") == ccid]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.post("/ins/quotes")
def create_quote():
    actor = mw.get_actor()
    mw.require_role(actor, "Policyholder", "Agent", "PartnerPlatform")
    body = _body()
    errors.reject_unknown_keys(body, (
        "business_account_id", "raw_description", "selected_lines",
        "exposure_units", "requested_effective_at", "uw_answers",
        "channel_partner_id",
    ))
    account_id = body.get("business_account_id")
    raw_description = body.get("raw_description")
    selected_lines = body.get("selected_lines")
    exposure_units = body.get("exposure_units")
    requested_effective_at = body.get("requested_effective_at")
    uw_answers = body.get("uw_answers")
    channel_partner_id = body.get("channel_partner_id")

    # --- shape validation (400) ---
    if not isinstance(account_id, str):
        raise errors.validation("business_account_id is required")
    if not isinstance(raw_description, str):
        raise errors.validation("raw_description is required")
    if not isinstance(selected_lines, list):
        raise errors.validation("selected_lines must be an array")
    if not isinstance(exposure_units, int) or isinstance(exposure_units, bool):
        raise errors.validation("exposure_units must be an integer")
    if not isinstance(uw_answers, dict):
        raise errors.validation("uw_answers must be an object")

    # --- existence (404) ---
    acct = db.business_accounts.get(account_id)
    if acct is None:
        raise errors.not_found("Business account not found")
    # Policyholder quoting for own account only (cross-account -> 404)
    if actor.role == "Policyholder" and actor.user_id != account_id:
        raise errors.not_found("Business account not found")

    # --- business constraints ---
    if exposure_units < 0:
        raise errors.exposure_negative()
    try:
        req_eff = db.parse_iso(requested_effective_at)
    except (ValueError, TypeError):
        raise errors.validation("requested_effective_at must be an ISO8601 string")
    if req_eff < db.clock_now():
        raise errors.validation("requested_effective_at must be >= current clock instant")

    # --- channel matching (referential) ---
    if acct["channel"] == "PARTNER":
        if not channel_partner_id or channel_partner_id != acct["partner_tenant"]:
            raise errors.channel_mismatch()
    else:
        if channel_partner_id is not None:
            raise errors.channel_mismatch()

    now = db.clock_now()
    quote = {
        "id": db.new_id(),
        "business_account_id": account_id,
        "channel_partner_id": channel_partner_id if acct["channel"] == "PARTNER" else None,
        "class_code_id": None,
        "raw_description": raw_description,
        "selected_lines": list(selected_lines),
        "exposure_units": exposure_units,
        "requested_effective_at": db.fmt_iso(req_eff),
        "uw_answers": dict(uw_answers),
        "risk_score": None,
        "annual_premium_cents": None,
        "premium_basis_hash": None,
        "status": "CLASSIFYING",
        "expires_at": None,
        "created_at": db.fmt_iso(now),
        "updated_at": db.fmt_iso(now),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.quotes[quote["id"]] = quote
    aud.record(actor.role, actor.user_id, "Quote", quote["id"], "create",
               after=ser.public(quote))

    # --- classification ---
    winner, matches, refer_hit, ambiguous, declined = uw.classify(raw_description)

    if ambiguous:
        quote["status"] = "DECLINED"
        quote["updated_at"] = db.fmt_iso(now)
        quote["version"] += 1
        aud.record(actor.role, actor.user_id, "Quote", quote["id"], "classify_ambiguous",
                   after={"status": "DECLINED"})
        raise errors.class_ambiguous()
    if declined:
        quote["status"] = "DECLINED"
        quote["updated_at"] = db.fmt_iso(now)
        quote["version"] += 1
        aud.record(actor.role, actor.user_id, "Quote", quote["id"], "classify_declined",
                   after={"status": "DECLINED"})
        raise errors.class_declined()

    if winner is None and refer_hit:
        # REFER routing without an admitted class: still needs a class to score.
        # Choose the highest-scoring class among matched REFER rules whose class exists.
        refer_classes = {}
        for r in matches:
            if r["disposition"] == "REFER":
                refer_classes.setdefault(r["class_code"], []).append(r)
        # pick best by (count, -rank_sum, earliest)
        best = None
        for cid, rs in refer_classes.items():
            cls = uw.class_by_code(cid)
            if cls is None:
                continue
            key = (len(rs), -sum(r["priority_rank"] for r in rs), -min(r["_seq"] for r in rs))
            if best is None or key > best[0]:
                best = (key, cls)
        if best is None:
            quote["status"] = "DECLINED"
            aud.record(actor.role, actor.user_id, "Quote", quote["id"], "classify_declined",
                       after={"status": "DECLINED"})
            raise errors.class_declined()
        winner = best[1]

    quote["class_code_id"] = winner["id"]

    # selected_lines must be a non-empty subset of eligible_lines
    eligible = set(winner["eligible_lines"])
    if not selected_lines or any(l not in eligible for l in selected_lines):
        aud.record(actor.role, actor.user_id, "Quote", quote["id"], "lines_ineligible",
                   after={"status": quote["status"]})
        raise errors.line_not_eligible()

    # --- risk score ---
    risk = uw.compute_risk_score(winner, account_id, uw_answers)
    quote["risk_score"] = risk

    # --- routing ---
    route_refer = refer_hit or (60 <= risk < 85)
    route_decline = risk >= 85

    if route_decline:
        quote["status"] = "DECLINED"
        quote["updated_at"] = db.fmt_iso(now)
        quote["version"] += 1
        aud.record(actor.role, actor.user_id, "Quote", quote["id"], "risk_declined",
                   after={"status": "DECLINED", "risk_score": risk})
        return resp.ok_object(ser.public(quote), status=201)

    if route_refer:
        quote["status"] = "REFERRED"
        quote["updated_at"] = db.fmt_iso(now)
        quote["version"] += 1
        referral = {
            "id": db.new_id(),
            "quote_id": quote["id"],
            "assigned_underwriter": None,
            "decision": "PENDING",
            "status": "OPEN",
            "created_at": db.fmt_iso(now),
            "updated_at": db.fmt_iso(now),
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.referrals[referral["id"]] = referral
        aud.record(actor.role, actor.user_id, "Quote", quote["id"], "referred",
                   after={"status": "REFERRED", "risk_score": risk})
        aud.record(actor.role, actor.user_id, "UnderwriterReferral", referral["id"], "create",
                   after=ser.public(referral))
        _supersede_prior_quotes(account_id, quote["id"], actor)
        return resp.ok_object(ser.public(quote), status=201)

    # QUOTED path
    _finalize_quoted(quote, winner, acct, actor)
    _supersede_prior_quotes(account_id, quote["id"], actor)
    return resp.ok_object(ser.public(quote), status=201)


def _finalize_quoted(quote, cls, acct, actor):
    """Move quote CLASSIFYING/REFERRED -> QUOTED: provisional premium,
    expires_at = clock + 168h, mark PENDING signals APPLIED, set basis hash."""
    now = db.clock_now()
    premium = uw.premium_cents(cls, quote["selected_lines"], quote["exposure_units"],
                               acct["claims_free_flag"], variant="provisional")
    pend = uw.pending_signals(quote["business_account_id"])
    quote["annual_premium_cents"] = premium
    quote["expires_at"] = db.fmt_iso(now + timedelta(hours=168))
    quote["premium_basis_hash"] = uw.premium_basis_hash(
        cls["id"], quote["selected_lines"], quote["exposure_units"],
        quote["uw_answers"], [s["id"] for s in pend])
    before_status = quote["status"]
    quote["status"] = "QUOTED"
    quote["updated_at"] = db.fmt_iso(now)
    quote["version"] += 1
    for s in pend:
        s["status"] = "APPLIED"
        s["updated_at"] = db.fmt_iso(now)
        s["version"] += 1
        aud.record(actor.role, actor.user_id, "RiskSignalReport", s["id"], "applied",
                   before={"status": "PENDING"}, after={"status": "APPLIED"})
    aud.record(actor.role, actor.user_id, "Quote", quote["id"], "quoted",
               before={"status": before_status}, after={"status": "QUOTED"})


def _supersede_prior_quotes(account_id, new_quote_id, actor):
    for q in db.quotes.values():
        if (q["business_account_id"] == account_id and q["id"] != new_quote_id
                and q["status"] == "QUOTED"):
            q["status"] = "SUPERSEDED"
            q["updated_at"] = db.fmt_iso(db.clock_now())
            q["version"] += 1
            aud.record(actor.role, actor.user_id, "Quote", q["id"], "superseded",
                       before={"status": "QUOTED"}, after={"status": "SUPERSEDED"})


@bp.get("/ins/quotes/<qid>")
def get_quote(qid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Agent", "PartnerPlatform", "Policyholder", "Underwriter")
    q = _get_quote(qid)
    _check_quote_visibility(actor, q)
    return resp.ok_object(ser.public(q))


@bp.get("/ins/quotes/<qid>/referral")
def quote_referral(qid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Underwriter")
    _get_quote(qid)
    items = [r for r in db.referrals.values() if r["quote_id"] == qid]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.get("/ins/quotes/<qid>/policy")
def quote_policy(qid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "Agent", "PartnerPlatform", "Underwriter")
    q = _get_quote(qid)
    _check_quote_visibility(actor, q)
    items = [p for p in db.policies.values() if p["quote_id"] == qid]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.post("/ins/quotes/<qid>/bind")
def bind_quote(qid):
    actor = mw.get_actor()
    mw.require_role(actor, "Policyholder")
    q = _get_quote(qid)
    _check_quote_visibility(actor, q)
    body = _body()
    errors.reject_unknown_keys(body, ("expected_quote_version",))
    expected = body.get("expected_quote_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.validation("expected_quote_version is required")

    now = db.clock_now()

    # state
    if q["status"] != "QUOTED":
        raise errors.invalid_state("Quote is not QUOTED")
    # temporal: expired
    exp = db.parse_iso(q["expires_at"])
    if now >= exp:
        raise errors.quote_expired()
    # ownership (Policyholder binding own quote)
    if actor.user_id != q["business_account_id"]:
        raise errors.not_found("Quote not found")
    # fiscal gate: basis unchanged. The current pricing basis includes both
    # APPLIED signals (already folded into this quote) and any PENDING signals
    # that arrived after issuance — a fresh quote would apply those, so their
    # presence changes the fingerprint (§3.4).
    cls = db.class_codes.get(q["class_code_id"])
    current_hash = uw.premium_basis_hash(
        q["class_code_id"], q["selected_lines"], q["exposure_units"],
        q["uw_answers"], [s["id"] for s in db.risk_signals.values()
                          if s["business_account_id"] == q["business_account_id"]
                          and s["status"] in ("APPLIED", "PENDING")])
    if current_hash != q["premium_basis_hash"]:
        raise errors.quote_basis_stale()
    # OCC
    if expected != q["version"]:
        raise errors.stale_quote_version()

    # FINAL premium: claims_free re-evaluated now; no COVERAGE_ADJUST lineage yet
    acct = db.business_accounts[q["business_account_id"]]
    final_premium = uw.premium_cents(cls, q["selected_lines"], q["exposure_units"],
                                     acct["claims_free_flag"], variant="final",
                                     exposure_uplift=False)

    term_start = db.parse_iso(q["requested_effective_at"])
    term_end = term_start + timedelta(days=365)
    policy = {
        "id": db.new_id(),
        "quote_id": q["id"],
        "business_account_id": q["business_account_id"],
        "class_code_id": q["class_code_id"],
        "term_start": db.fmt_iso(term_start),
        "term_end": db.fmt_iso(term_end),
        "term_day_count": 365,
        "exposure_units": q["exposure_units"],
        "base_annual_premium_cents": final_premium,
        "earned_premium_cents": 0,
        "open_claim_count": 0,
        "renewal_window_start": db.fmt_iso(term_end - timedelta(days=120)),
        "non_renewal_notice_sent_at": None,
        "status": "BOUND",
        "created_at": db.fmt_iso(now),
        "updated_at": db.fmt_iso(now),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.policies[policy["id"]] = policy

    # If the clock has already reached term_start, the policy activates
    # immediately (BOUND -> ACTIVE time-driven transition, §2.4/§3.2).
    if now >= term_start:
        policy["status"] = "ACTIVE"
        policy["updated_at"] = db.fmt_iso(now)
        policy["version"] += 1
        aud.record(actor.role, actor.user_id, "Policy", policy["id"], "activate",
                   before={"status": "BOUND"}, after={"status": "ACTIVE"})

    before_q = {"status": q["status"], "version": q["version"]}
    q["status"] = "BOUND"
    q["updated_at"] = db.fmt_iso(now)
    q["version"] += 1

    # signals that fed this quote -> STALE once quote BOUND
    for s in db.risk_signals.values():
        if (s["business_account_id"] == q["business_account_id"] and s["status"] == "APPLIED"):
            s["status"] = "STALE"
            s["updated_at"] = db.fmt_iso(now)
            s["version"] += 1
            aud.record(actor.role, actor.user_id, "RiskSignalReport", s["id"], "stale",
                       before={"status": "APPLIED"}, after={"status": "STALE"})

    aud.record(actor.role, actor.user_id, "Quote", q["id"], "bind",
               before=before_q, after={"status": "BOUND", "version": q["version"]})
    aud.record(actor.role, actor.user_id, "Policy", policy["id"], "create",
               after=ser.public(policy))
    return resp.ok_object(ser.public(policy), status=201)
