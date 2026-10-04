"""Governing bodies, certification cycles, complaints (PRD 3.1, 3.2)."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import db
import timeutil
from constants import ALL_ROLES_READ, CYCLE_MAX_DURATION_DAYS, \
    COMPLIANCE_EXCELLENT_THRESHOLD, COMPLIANCE_PASS_THRESHOLD
from envelope import respond_list, respond_object
from errors import ApiError, ERR_CYCLE_WINDOW_INVALID, ERR_CYCLE_WINDOW_OVERLAP, \
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SCORE_OUT_OF_RANGE, \
    ERR_SEGREGATION_OF_DUTIES, already_terminal, invalid_state, not_found
from validate import auth, body_json, check_gb_ownership, req_datetime, \
    req_enum, req_int, req_str, require_roles

bp = Blueprint("gb", __name__)

GB_STATES = ["APPLIED", "CERTIFIED", "PROBATION", "INTERIM_MANAGED", "DECERTIFIED"]
GB_TRANSITION_STATES = ["INTERIM_MANAGED", "PROBATION", "DECERTIFIED"]
CYCLE_TRANSITION_STATES = ["OPEN", "FINDINGS_ISSUED", "REMEDIATION",
                           "CLOSED_PASSED", "CLOSED_FAILED"]
COMPLAINT_TRANSITION_STATES = ["TRIAGED", "INVESTIGATING", "SUBSTANTIATED",
                               "DISMISSED"]
COMPLAINT_CATEGORIES = ["GOVERNANCE", "ATHLETE_REPRESENTATION", "FINANCIAL",
                        "SAFE_SPORT", "SELECTION"]
COMPLAINT_SEVERITIES = ["CRITICAL", "MAJOR", "MINOR"]


def get_gb_or_404(gb_id):
    gb = db.get("governing_bodies", gb_id)
    if gb is None:
        raise not_found("governing body not found")
    return gb


def get_cycle_or_404(cycle_id):
    cycle = db.get("certification_cycles", cycle_id)
    if cycle is None:
        raise not_found("certification cycle not found")
    return cycle


def get_complaint_or_404(complaint_id):
    complaint = db.get("complaints", complaint_id)
    if complaint is None:
        raise not_found("complaint not found")
    return complaint


# --- GoverningBody --------------------------------------------------------------
@bp.route("/api/governing-bodies", methods=["POST"])
def create_gb():
    _, role = auth()
    require_roles(role, ["CommitteeAdmin"])
    body = body_json()
    name = req_str(body, "name")
    sport_code = req_str(body, "sport_code")
    budget = req_int(body, "funding_budget_cents")
    pool = req_int(body, "sport_science_pool_hours")
    gb = db.create("governing_bodies", {
        "name": name,
        "sport_code": sport_code,
        "status": "APPLIED",
        "certified_at": None,
        "interim_manager_id": None,
        "funding_budget_cents": budget,
        "sport_science_pool_hours": pool,
        "committed_monthly_stipend_cents": 0,
        "allocated_science_hours": 0,
        "substantiated_complaint_count": 0,
        "complaint_posture": "NORMAL",
    })
    return respond_object(gb, 201)


@bp.route("/api/governing-bodies/<gb_id>", methods=["GET"])
def read_gb(gb_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    check_gb_ownership(uid, role, gb_id)  # NGBAdmin: X-User-ID == body id
    gb = get_gb_or_404(gb_id)
    cascades.due_body(gb, timeutil.now())
    return respond_object(gb)


@bp.route("/api/governing-bodies/<gb_id>/transitions", methods=["POST"])
def gb_transition(gb_id):
    _, role = auth()
    require_roles(role, ["CommitteeAdmin"])
    gb = get_gb_or_404(gb_id)
    if gb["status"] == "DECERTIFIED":
        raise already_terminal("governing body is DECERTIFIED")
    body = body_json()
    to_state = req_enum(body, "to_state", GB_TRANSITION_STATES)
    now = timeutil.now()

    if to_state == "INTERIM_MANAGED":
        if gb["status"] not in ("PROBATION", "INTERIM_MANAGED"):
            raise invalid_state(
                "INTERIM_MANAGED is only reachable from PROBATION or "
                "INTERIM_MANAGED (manager replacement)")
        manager = body.get("interim_manager_id")
        if not isinstance(manager, str) or not manager.strip():
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "interim_manager_id is required")
        gb["interim_manager_id"] = manager
        gb["status"] = "INTERIM_MANAGED"
        db.mark("governing_bodies", gb)
        return respond_object(gb)

    if to_state == "PROBATION":
        if gb["status"] != "INTERIM_MANAGED":
            raise invalid_state("PROBATION is only reachable from INTERIM_MANAGED")
        gb["interim_manager_id"] = None
        gb["status"] = "PROBATION"
        db.mark("governing_bodies", gb)
        return respond_object(gb)

    # DECERTIFIED: evidence within trailing 365 days required.
    if gb["status"] not in ("PROBATION", "INTERIM_MANAGED"):
        raise invalid_state("DECERTIFIED is only reachable from PROBATION or "
                            "INTERIM_MANAGED")
    window = timeutil.days(365)
    evidence = False
    for cycle in db.all_of("certification_cycles"):
        if cycle["governing_body_id"] == gb["id"] \
                and cycle["status"] == "CLOSED_FAILED" \
                and cycle.get("closed_at") is not None \
                and now - cycle["closed_at"] <= window:
            evidence = True
            break
    if not evidence:
        for complaint in db.all_of("complaints"):
            if complaint["governing_body_id"] == gb["id"] \
                    and complaint["status"] == "SUBSTANTIATED" \
                    and complaint["severity"] == "CRITICAL" \
                    and complaint.get("resolved_at") is not None \
                    and now - complaint["resolved_at"] <= window:
                evidence = True
                break
    if not evidence:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "no decertification evidence: requires a CLOSED_FAILED "
                       "cycle or a SUBSTANTIATED CRITICAL complaint within the "
                       "trailing 365 days")
    cascades.decertify(gb)
    gb["status"] = "DECERTIFIED"
    db.mark("governing_bodies", gb)
    return respond_object(gb)


# --- CertificationCycle -----------------------------------------------------------
@bp.route("/api/governing-bodies/<gb_id>/certification-cycles", methods=["POST"])
def create_cycle(gb_id):
    _, role = auth()
    require_roles(role, ["CommitteeAdmin"])
    get_gb_or_404(gb_id)
    body = body_json()
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    if window_end <= window_start:
        raise ApiError(ERR_CYCLE_WINDOW_INVALID, 422,
                       "window_end must be strictly after window_start")
    for other in db.all_of("certification_cycles"):
        if other["governing_body_id"] != gb_id:
            continue
        if window_start < other["window_end"] and other["window_start"] < window_end:
            raise ApiError(ERR_CYCLE_WINDOW_OVERLAP, 409,
                           "cycle window overlaps an existing cycle of this body")
    cycle = db.create("certification_cycles", {
        "governing_body_id": gb_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "governance_score": None,
        "athlete_rep_score": None,
        "financial_score": None,
        "provisional_score": None,
        "final_score": None,
        "remediation_applied": False,
        "opened_at": None,
        "issued_by_user_id": None,
        "closed_by_user_id": None,
        "closed_at": None,
    })
    return respond_object(cycle, 201)


@bp.route("/api/governing-bodies/<gb_id>/certification-cycles", methods=["GET"])
def list_cycles(gb_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    check_gb_ownership(uid, role, gb_id)
    get_gb_or_404(gb_id)
    status = body_filter("status")
    now = timeutil.now()
    items = []
    for cycle in db.all_of("certification_cycles"):
        if cycle["governing_body_id"] != gb_id:
            continue
        cascades.due_cycle(cycle, now)
        if status is not None and cycle["status"] != status:
            continue
        items.append(cycle)
    return respond_list(db.sorted_created(items))


def _scores(body):
    scores = {}
    for field in ("governance_score", "athlete_rep_score", "financial_score"):
        v = body.get(field)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "%s is required and must be a number" % field)
        d = Decimal(str(v))
        if d < 0 or d > 100:
            raise ApiError(ERR_SCORE_OUT_OF_RANGE, 422,
                           "%s must be within 0..100" % field)
        scores[field] = d
    return scores["governance_score"], scores["athlete_rep_score"], \
        scores["financial_score"]


@bp.route("/api/certification-cycles/<cycle_id>/transitions", methods=["POST"])
def cycle_transition(cycle_id):
    uid, role = auth()
    require_roles(role, ["CertificationAuditor"])
    cycle = get_cycle_or_404(cycle_id)
    if cycle["status"] in ("CLOSED_PASSED", "CLOSED_FAILED"):
        raise already_terminal("certification cycle is closed")
    body = body_json()
    to_state = req_enum(body, "to_state", CYCLE_TRANSITION_STATES)
    now = timeutil.now()

    if to_state == "OPEN":
        if cycle["status"] != "SCHEDULED":
            raise invalid_state("OPEN is only reachable from SCHEDULED")
        if now < cycle["window_start"]:
            raise invalid_state("cycle window has not started")
        cycle["opened_at"] = now
        cycle["status"] = "OPEN"
        db.mark("certification_cycles", cycle)
        return respond_object(cycle)

    if to_state == "FINDINGS_ISSUED":
        if cycle["status"] not in ("OPEN", "REMEDIATION"):
            raise invalid_state(
                "FINDINGS_ISSUED is only reachable from OPEN or REMEDIATION")
        g, a, f = _scores(body)
        cycle["governance_score"] = g
        cycle["athlete_rep_score"] = a
        cycle["financial_score"] = f
        cycle["provisional_score"] = calc.provisional_score(g, a, f)
        cycle["issued_by_user_id"] = uid
        cycle["status"] = "FINDINGS_ISSUED"
        db.mark("certification_cycles", cycle)
        return respond_object(cycle)

    if to_state == "REMEDIATION":
        if cycle["status"] != "FINDINGS_ISSUED":
            raise invalid_state("REMEDIATION is only reachable from FINDINGS_ISSUED")
        if not (COMPLIANCE_PASS_THRESHOLD <= cycle["provisional_score"]
                < COMPLIANCE_EXCELLENT_THRESHOLD):
            raise invalid_state(
                "remediation requires a provisional score in [70, 85)")
        cycle["status"] = "REMEDIATION"
        db.mark("certification_cycles", cycle)
        return respond_object(cycle)

    if to_state == "CLOSED_PASSED":
        if cycle["status"] == "FINDINGS_ISSUED":
            if cycle["provisional_score"] < COMPLIANCE_EXCELLENT_THRESHOLD:
                raise invalid_state(
                    "fast-path pass requires a provisional score >= 85")
        elif cycle["status"] != "REMEDIATION":
            raise invalid_state(
                "CLOSED_PASSED is only reachable from FINDINGS_ISSUED or "
                "REMEDIATION")
        if now > cycle["opened_at"] + timeutil.days(CYCLE_MAX_DURATION_DAYS):
            raise invalid_state("cycle exceeded its 120-day maximum duration")
        if uid == cycle["issued_by_user_id"]:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                           "cycle closer must differ from findings issuer")
        if cycle["status"] == "REMEDIATION":
            cycle["final_score"] = calc.final_score_after_remediation(
                cycle["governance_score"], cycle["athlete_rep_score"],
                cycle["financial_score"])
            cycle["remediation_applied"] = True
        else:
            cycle["final_score"] = cycle["provisional_score"]
            cycle["remediation_applied"] = False
        cycle["closed_by_user_id"] = uid
        cycle["closed_at"] = now
        cycle["status"] = "CLOSED_PASSED"
        db.mark("certification_cycles", cycle)
        cascades.cascade_cycle_closed(cycle, passed=True)
        return respond_object(cycle)

    # CLOSED_FAILED
    if cycle["status"] == "FINDINGS_ISSUED":
        if cycle["provisional_score"] >= COMPLIANCE_PASS_THRESHOLD:
            raise invalid_state(
                "fail close from FINDINGS_ISSUED requires a provisional score "
                "below 70")
    elif cycle["status"] != "REMEDIATION":
        raise invalid_state(
            "CLOSED_FAILED is only reachable from FINDINGS_ISSUED or REMEDIATION")
    if uid == cycle["issued_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "cycle closer must differ from findings issuer")
    cycle["final_score"] = cycle["provisional_score"]
    cycle["remediation_applied"] = False
    cycle["closed_by_user_id"] = uid
    cycle["closed_at"] = now
    cycle["status"] = "CLOSED_FAILED"
    db.mark("certification_cycles", cycle)
    cascades.cascade_cycle_closed(cycle, passed=False)
    return respond_object(cycle)


# --- Complaint ----------------------------------------------------------------------
def body_filter(name):
    from flask import request
    v = request.args.get(name)
    return v if v else None


@bp.route("/api/governing-bodies/<gb_id>/complaints", methods=["POST"])
def create_complaint(gb_id):
    _, role = auth()
    require_roles(role, ["CommitteeAdmin", "CertificationAuditor", "Athlete",
                         "SafeSportOfficer"])
    get_gb_or_404(gb_id)
    body = body_json()
    category = req_enum(body, "category", COMPLAINT_CATEGORIES)
    severity = req_enum(body, "severity", COMPLAINT_SEVERITIES)
    description = req_str(body, "description")
    complaint = db.create("complaints", {
        "governing_body_id": gb_id,
        "category": category,
        "severity": severity,
        "description": description,
        "status": "FILED",
        "triaged_by_user_id": None,
        "resolved_by_user_id": None,
        "resolved_at": None,
    })
    return respond_object(complaint, 201)


@bp.route("/api/governing-bodies/<gb_id>/complaints", methods=["GET"])
def list_complaints(gb_id):
    uid, role = auth()
    require_roles(role, ALL_ROLES_READ)
    check_gb_ownership(uid, role, gb_id)
    get_gb_or_404(gb_id)
    status = body_filter("status")
    items = [c for c in db.all_of("complaints")
             if c["governing_body_id"] == gb_id
             and (status is None or c["status"] == status)]
    return respond_list(db.sorted_created(items))


@bp.route("/api/complaints/<complaint_id>/transitions", methods=["POST"])
def complaint_transition(complaint_id):
    uid, role = auth()
    require_roles(role, ["CertificationAuditor"])
    complaint = get_complaint_or_404(complaint_id)
    if complaint["status"] in ("SUBSTANTIATED", "DISMISSED"):
        raise already_terminal("complaint is already resolved")
    body = body_json()
    to_state = req_enum(body, "to_state", COMPLAINT_TRANSITION_STATES)

    if to_state == "TRIAGED":
        if complaint["status"] != "FILED":
            raise invalid_state("TRIAGED is only reachable from FILED")
        complaint["triaged_by_user_id"] = uid
        complaint["status"] = "TRIAGED"
        db.mark("complaints", complaint)
        return respond_object(complaint)

    if to_state == "INVESTIGATING":
        if complaint["status"] != "TRIAGED":
            raise invalid_state("INVESTIGATING is only reachable from TRIAGED")
        complaint["status"] = "INVESTIGATING"
        db.mark("complaints", complaint)
        return respond_object(complaint)

    # SUBSTANTIATED / DISMISSED (resolution; segregated from triage)
    if complaint["status"] != "INVESTIGATING":
        raise invalid_state("resolution is only reachable from INVESTIGATING")
    if uid == complaint["triaged_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "complaint resolver must differ from triager")
    complaint["resolved_by_user_id"] = uid
    complaint["resolved_at"] = timeutil.now()
    complaint["status"] = to_state
    db.mark("complaints", complaint)
    if to_state == "SUBSTANTIATED":
        cascades.cascade_complaint_substantiated(complaint)
    return respond_object(complaint)
