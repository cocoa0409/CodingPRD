"""Routes: question sets, waves, transactions."""

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import services
from middleware import require_roles
from response import parse_pagination, success_list, success_object
from routes_core import _body, _require, _sorted

bp = Blueprint("instrument", __name__)


# ------------------------------------------------------------ question sets


def _validate_questions(questions):
    if not isinstance(questions, list) or len(questions) < 1:
        raise errors.validation("questions must contain at least one question")
    seen = set()
    for q in questions:
        if not isinstance(q, dict):
            raise errors.validation("each question must be an object")
        code = q.get("question_code")
        prompt = q.get("prompt")
        weight = q.get("weight")
        if not isinstance(code, str) or not code:
            raise errors.validation("question_code required")
        if code in seen:
            raise errors.validation("question_code must be unique within the set")
        seen.add(code)
        if not isinstance(prompt, str):
            raise errors.validation("prompt required")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise errors.validation("weight must be a positive number")
        if weight <= 0:
            raise errors.validation("weights must be positive")


@bp.post("/survey/question-sets")
@require_roles("PlatformAdmin")
def create_question_set(user_id, role):
    data = _require(_body(), "code", "questions", "comparability_factor")
    for q in db.question_sets.values():
        if q["code"] == data["code"]:
            raise errors.validation("QuestionSet code must be unique")
    _validate_questions(data["questions"])
    cf = data["comparability_factor"]
    if isinstance(cf, bool) or not isinstance(cf, (int, float)):
        raise errors.invalid_request("comparability_factor must be a number")
    if not (cf > 0.5 and cf <= 1.5):
        raise errors.validation("comparability_factor must be in (0.5, 1.5]")
    rec = helpers.make_record()
    rec.update(
        {
            "code": data["code"],
            "questions": data["questions"],
            "comparability_factor": cf,
            "status": "DRAFT",
        }
    )
    db.question_sets[rec["id"]] = rec
    return success_object(helpers.ser_question_set(rec), 201)


@bp.get("/survey/question-sets/<qid>")
@require_roles("PlatformAdmin", "RegionalManager", "ComplianceAuditor", "FieldConsultant")
def get_question_set(user_id, role, qid):
    rec = db.question_sets.get(qid)
    if rec is None:
        raise errors.not_found("QuestionSet not found")
    return success_object(helpers.ser_question_set(rec))


@bp.post("/survey/question-sets/<qid>/activate")
@require_roles("PlatformAdmin")
def activate_question_set(user_id, role, qid):
    rec = db.question_sets.get(qid)
    if rec is None:
        raise errors.not_found("QuestionSet not found")
    if rec["status"] != "DRAFT":
        raise errors.invalid_state("QuestionSet is not DRAFT")
    for q in db.question_sets.values():
        if q["status"] == "ACTIVE":
            raise errors.active_question_set_exists()
    rec["status"] = "ACTIVE"
    helpers.touch(rec)
    return success_object(helpers.ser_question_set(rec))


@bp.post("/survey/question-sets/<qid>/retire")
@require_roles("PlatformAdmin")
def retire_question_set(user_id, role, qid):
    rec = db.question_sets.get(qid)
    if rec is None:
        raise errors.not_found("QuestionSet not found")
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("QuestionSet is not ACTIVE")
    rec["status"] = "RETIRED"
    helpers.touch(rec)
    return success_object(helpers.ser_question_set(rec))


# ------------------------------------------------------------------- waves


@bp.post("/survey/waves")
@require_roles("PlatformAdmin")
def create_wave(user_id, role):
    data = _require(_body(), "period_start", "period_end", "question_set_id")
    if data["question_set_id"] not in db.question_sets:
        raise errors.not_found("QuestionSet not found")
    try:
        start = clock.parse_iso(data["period_start"])
        end = clock.parse_iso(data["period_end"])
    except (ValueError, TypeError):
        raise errors.invalid_request("period_start/period_end must be ISO8601")
    if not end > start:
        raise errors.invalid_request("period_end must be > period_start")
    rec = helpers.make_record()
    rec.update(
        {
            "period_start": start,
            "period_end": end,
            "question_set_id": data["question_set_id"],
            "status": "DRAFT",
            "closed_at": None,
            "invitations_total": 0,
            "queued_count": 0,
            "sent_count": 0,
            "responded_count": 0,
            "expired_count": 0,
            "opted_out_count": 0,
            "suppressed_count": 0,
        }
    )
    db.waves[rec["id"]] = rec
    return success_object(helpers.ser_wave(rec), 201)


@bp.get("/survey/waves/<wid>")
@require_roles(
    "PlatformAdmin",
    "RegionalManager",
    "ComplianceAuditor",
    "FieldConsultant",
    "DealerPrincipal",
)
def get_wave(user_id, role, wid):
    rec = db.waves.get(wid)
    if rec is None:
        raise errors.not_found("Wave not found")
    return success_object(helpers.ser_wave(rec))


@bp.get("/survey/waves")
@require_roles("PlatformAdmin", "RegionalManager", "ComplianceAuditor", "FieldConsultant")
def list_waves(user_id, role):
    limit, offset = parse_pagination(request.args)
    items = list(db.waves.values())
    qs = request.args.get("question_set_id")
    status = request.args.get("status")
    if qs is not None:
        items = [w for w in items if w["question_set_id"] == qs]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = _sorted(items)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([helpers.ser_wave(w) for w in page], limit, offset, total)


@bp.post("/survey/waves/<wid>/open")
@require_roles("PlatformAdmin")
def open_wave(user_id, role, wid):
    rec = db.waves.get(wid)
    if rec is None:
        raise errors.not_found("Wave not found")
    if rec["status"] != "DRAFT":
        raise errors.invalid_state("Wave is not DRAFT")
    qs = db.question_sets.get(rec["question_set_id"])
    if qs is None or qs["status"] != "ACTIVE":
        raise errors.question_set_not_active()
    rec["status"] = "OPEN"
    helpers.touch(rec)
    services.run_sampling_sweep(rec)
    helpers.touch(rec)
    return success_object(helpers.ser_wave(rec))


@bp.post("/survey/waves/<wid>/close")
@require_roles("PlatformAdmin")
def close_wave_route(user_id, role, wid):
    rec = db.waves.get(wid)
    if rec is None:
        raise errors.not_found("Wave not found")
    if rec["status"] != "OPEN":
        raise errors.invalid_state("Wave is not OPEN")
    if clock.now() < rec["period_end"]:
        raise errors.wave_still_open()
    services.close_wave(rec)
    return success_object(helpers.ser_wave(rec))


@bp.post("/survey/waves/<wid>/finalize")
@require_roles("PlatformAdmin")
def finalize_wave(user_id, role, wid):
    rec = db.waves.get(wid)
    if rec is None:
        raise errors.not_found("Wave not found")
    if rec["status"] != "CLOSED":
        raise errors.invalid_state("Wave is not CLOSED")
    # appeals gate first (priority 16 before 17)
    for resp in db.responses.values():
        inv = db.invitations.get(resp["invitation_id"])
        if inv is None or inv["wave_id"] != wid:
            continue
        for ap in db.appeals.values():
            if ap["response_id"] == resp["id"] and ap["status"] in (
                "FILED",
                "UNDER_REVIEW",
            ):
                raise errors.appeals_pending()
    dealer_ids = set()
    for inv in db.invitations.values():
        if inv["wave_id"] != wid:
            continue
        tx = db.transactions.get(inv["transaction_id"])
        if tx is not None:
            dealer_ids.add(tx["dealer_id"])
    for f in db.flags.values():
        if f["dealer_id"] in dealer_ids and f["status"] == "OPEN":
            raise errors.flags_pending()
    for st in db.statements.values():
        if st["wave_id"] == wid and st["status"] == "PROVISIONAL":
            st["status"] = "FINAL"
            helpers.touch(st)
    rec["status"] = "FINALIZED"
    helpers.touch(rec)
    return success_object(helpers.ser_wave(rec))


@bp.get("/survey/waves/<wid>/benchmarks/<did>")
@require_roles(
    "PlatformAdmin",
    "RegionalManager",
    "ComplianceAuditor",
    "FieldConsultant",
    "DealerPrincipal",
)
def wave_benchmark(user_id, role, wid, did):
    wave = db.waves.get(wid)
    if wave is None:
        raise errors.not_found("Wave not found")
    target = db.dealers.get(did)
    if target is None:
        raise errors.not_found("Dealer not found")
    eligible = []
    for d in db.dealers.values():
        if d["region_id"] != target["region_id"]:
            continue
        if d["current_score_adjusted"] is None:
            continue
        has_tx = any(
            tx["dealer_id"] == d["id"]
            and wave["period_start"] <= tx["completed_at"] < wave["period_end"]
            for tx in db.transactions.values()
        )
        if has_tx:
            eligible.append(d)
    dealer_count = len(eligible)
    if target["current_score_adjusted"] is None or target not in eligible:
        # Target not eligible: rank at bottom + count, percentile 0 base
        rank = dealer_count + 1
        denom = max(dealer_count, 1)
    else:
        rank = 1 + sum(
            1
            for d in eligible
            if d["current_score_adjusted"] > target["current_score_adjusted"]
        )
        denom = max(dealer_count, 1)
    percentile = services.round2(
        services.D(100) * (1 - services.D(rank - 1) / services.D(denom))
    )
    return success_object(
        {
            "region_id": target["region_id"],
            "wave_id": wave["id"],
            "dealer_count": dealer_count,
            "dealer_rank": rank,
            "percentile": helpers.num(percentile),
        }
    )


# ------------------------------------------------------------- transactions


@bp.post("/survey/transactions")
@require_roles("PlatformAdmin")
def create_transaction(user_id, role):
    data = _require(
        _body(),
        "dealer_id",
        "department_id",
        "customer_id",
        "kind",
        "completed_at",
        "margin_cents",
    )
    dealer = db.dealers.get(data["dealer_id"])
    if dealer is None:
        raise errors.not_found("Dealer not found")
    dep = db.departments.get(data["department_id"])
    if dep is None:
        raise errors.not_found("Department not found")
    advisor_id = data.get("advisor_id")
    advisor = None
    if advisor_id is not None:
        advisor = db.advisors.get(advisor_id)
        if advisor is None:
            raise errors.not_found("Advisor not found")
    if data["customer_id"] not in db.customers:
        raise errors.not_found("Customer not found")
    if dep["dealer_id"] != dealer["id"]:
        raise errors.cross_reference("Department does not belong to dealer")
    if advisor is not None and advisor["department_id"] != dep["id"]:
        raise errors.cross_reference("Advisor does not belong to department")
    if data["kind"] not in ("SALE", "SERVICE_VISIT"):
        raise errors.invalid_request("kind must be SALE or SERVICE_VISIT")
    try:
        completed_at = clock.parse_iso(data["completed_at"])
    except (ValueError, TypeError):
        raise errors.invalid_request("completed_at must be ISO8601")
    margin = data["margin_cents"]
    if isinstance(margin, bool) or not isinstance(margin, int) or margin < 0:
        raise errors.invalid_request("margin_cents must be an integer >= 0")
    rec = helpers.make_record(common=False)
    rec.update(
        {
            "dealer_id": dealer["id"],
            "department_id": dep["id"],
            "advisor_id": advisor_id,
            "customer_id": data["customer_id"],
            "kind": data["kind"],
            "completed_at": completed_at,
            "margin_cents": margin,
        }
    )
    db.transactions[rec["id"]] = rec
    return success_object(helpers.ser_transaction(rec), 201)


@bp.get("/survey/transactions/<tid>")
@require_roles("PlatformAdmin", "ComplianceAuditor", "RegionalManager")
def get_transaction(user_id, role, tid):
    rec = db.transactions.get(tid)
    if rec is None:
        raise errors.not_found("Transaction not found")
    return success_object(helpers.ser_transaction(rec))


def _list_transactions(args, forced_dealer_id=None):
    limit, offset = parse_pagination(args)
    items = list(db.transactions.values())
    dealer_id = forced_dealer_id or args.get("dealer_id")
    if dealer_id is not None:
        items = [t for t in items if t["dealer_id"] == dealer_id]
    for param in ("department_id", "advisor_id", "customer_id", "kind"):
        v = args.get(param)
        if v is not None:
            items = [t for t in items if t.get(param) == v]
    items = _sorted(items)
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [helpers.ser_transaction(t) for t in page], limit, offset, total
    )


@bp.get("/survey/transactions")
@require_roles("PlatformAdmin", "ComplianceAuditor", "RegionalManager")
def list_transactions(user_id, role):
    return _list_transactions(request.args)


@bp.get("/survey/dealers/<did>/transactions")
@require_roles("PlatformAdmin", "ComplianceAuditor", "RegionalManager", "DealerPrincipal")
def list_dealer_transactions(user_id, role, did):
    if did not in db.dealers:
        raise errors.not_found("Dealer not found")
    return _list_transactions(request.args, forced_dealer_id=did)
