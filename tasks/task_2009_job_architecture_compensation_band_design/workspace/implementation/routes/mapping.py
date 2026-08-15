"""MappingDecision lifecycle (§3.7)."""
from datetime import timedelta
from flask import Blueprint, request
from db import store, new_id
from middleware import require_roles, get_auth
from response import success_object, success_list
from errors import (
    not_found, invalid_request, invalid_enum, invalid_state_transition,
    already_terminal, stale_version, program_state_forbids,
    segregation_of_duties, ownership_mismatch, referenced_entity_state,
    department_pool_exhausted, reverse_window_expired,
)
from services.common import (
    now_iso, require_fields, parse_pagination, sort_by_created_at, paginate, bump,
)
from services import clock
from services.employee_health import (
    recompute_employee_health, recompute_department_payroll,
    recompute_program_payroll, current_program,
)
from services.pricing import _to_date

bp = Blueprint("mapping", __name__)

MD_STATES = ["DRAFT", "SUBMITTED", "HRBP_REVIEWED", "COMP_TRIAGED", "APPROVED",
             "REJECTED", "RETURNED", "WITHDRAWN", "REVERSED"]
MD_TERMINAL = {"REJECTED", "WITHDRAWN", "REVERSED"}


def md_view(m):
    return {k: m[k] for k in ("id", "employee_id", "from_job_profile_id",
                              "to_job_profile_id", "justification", "kind",
                              "provisional_adjustment_cents", "final_adjustment_cents",
                              "pre_salary_cents", "status",
                              "submitted_by_user_id", "decided_by_user_id",
                              "approved_at", "created_at", "updated_at", "version")}


def get_md_or_404(mid):
    m = store.mapping_decisions.get(mid)
    if m is None:
        raise not_found("mapping decision not found")
    return m


def _get_employee(eid):
    e = store.employees.get(eid)
    if e is None:
        raise not_found("employee not found")
    return e


def _check_ownership(user_id, employee):
    if employee["department_id"] != user_id:
        raise ownership_mismatch()


def _compute_kind(employee, to_profile):
    from_prof = store.job_profiles[employee["job_profile_id"]]
    from_rank = store.job_levels[from_prof["job_level_id"]]["rank_order"]
    to_rank = store.job_levels[to_profile["job_level_id"]]["rank_order"]
    if to_rank > from_rank:
        return "UPSLOT"
    if to_rank < from_rank:
        return "DOWNSLOT"
    return "LATERAL"


def _select_band_provisional(to_profile, geo_id):
    """PRICED / COMP_APPROVED / PUBLISHED for current program; latest created_at."""
    prog = current_program()
    if prog is None:
        return None
    matches = []
    for b in store.pay_bands.values():
        if b["comp_program_id"] != prog["id"]:
            continue
        if b["job_family_id"] != to_profile["job_family_id"]:
            continue
        if b["job_level_id"] != to_profile["job_level_id"]:
            continue
        if b["geo_zone_id"] != geo_id:
            continue
        if b["status"] not in ("PRICED", "COMP_APPROVED", "PUBLISHED"):
            continue
        matches.append(b)
    if not matches:
        return None
    matches.sort(key=lambda b: (b["created_at"], b["id"]))
    return matches[-1]


def _select_band_final(to_profile, geo_id):
    prog = current_program()
    if prog is None:
        return None
    matches = []
    for b in store.pay_bands.values():
        if b["comp_program_id"] != prog["id"]:
            continue
        if b["job_family_id"] != to_profile["job_family_id"]:
            continue
        if b["job_level_id"] != to_profile["job_level_id"]:
            continue
        if b["geo_zone_id"] != geo_id:
            continue
        if b["status"] != "PUBLISHED":
            continue
        matches.append(b)
    if not matches:
        return None
    matches.sort(key=lambda b: (b["created_at"], b["id"]))
    return matches[-1]


def _reslot_adjustment(band, salary, kind):
    """Returns (new_salary, adjustment)."""
    if kind in ("UPSLOT", "LATERAL"):
        new_salary = max(salary, band["min_cents"])
        return new_salary, new_salary - salary
    # DOWNSLOT
    return salary, 0


@bp.route("/comp/mapping-decisions", methods=["POST"])
def create_mapping():
    user_id, _ = require_roles("DepartmentManager")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["employee_id", "to_job_profile_id"])
    employee_id = body["employee_id"]
    to_pid = body["to_job_profile_id"]
    e = store.employees.get(employee_id)
    if e is None:
        raise not_found("employee not found")
    if to_pid not in store.job_profiles:
        raise not_found("job profile not found")
    _check_ownership(user_id, e)
    justification = body.get("justification")
    if justification is not None and not isinstance(justification, str):
        raise invalid_request("justification must be a string")
    now = now_iso()
    m = {"id": new_id(), "employee_id": employee_id,
         "from_job_profile_id": None, "to_job_profile_id": to_pid,
         "justification": justification, "kind": None,
         "provisional_adjustment_cents": None, "final_adjustment_cents": None,
         "pre_salary_cents": None, "status": "DRAFT",
         "submitted_by_user_id": None, "decided_by_user_id": None,
         "approved_at": None,
         "created_at": now, "updated_at": now, "version": 1}
    store.mapping_decisions[m["id"]] = m
    return success_object(md_view(m), 201)


@bp.route("/comp/mapping-decisions", methods=["GET"])
def list_mappings():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.mapping_decisions.values())
    for arg in ("employee_id", "from_job_profile_id", "to_job_profile_id"):
        v = request.args.get(arg)
        if v is not None:
            rows = [m for m in rows if m.get(arg) == v]
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in MD_STATES:
            raise invalid_enum("status is not a declared member")
        rows = [m for m in rows if m["status"] == status_filter]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([md_view(m) for m in page], limit, offset, total)


@bp.route("/comp/mapping-decisions/<mid>", methods=["GET"])
def get_mapping(mid):
    get_auth()
    return success_object(md_view(get_md_or_404(mid)))


def _do_submit(m, user_id):
    """Shared submit logic for submit and resubmit."""
    e = _get_employee(m["employee_id"])
    _check_ownership(user_id, e)
    prog = current_program()
    if prog is None or prog["status"] != "MAPPING_OPEN":
        raise program_state_forbids("mapping submit requires program MAPPING_OPEN")
    if e["status"] != "ACTIVE":
        raise referenced_entity_state("employee not ACTIVE")
    to_profile = store.job_profiles.get(m["to_job_profile_id"])
    if to_profile is None:
        raise not_found("job profile not found")
    if to_profile["status"] != "APPROVED":
        raise referenced_entity_state("to_job_profile must be APPROVED")
    # snapshot + compute
    m["from_job_profile_id"] = e["job_profile_id"]
    m["kind"] = _compute_kind(e, to_profile)
    band = _select_band_provisional(to_profile, e["geo_zone_id"])
    if band is None:
        m["provisional_adjustment_cents"] = None
    else:
        _, adj = _reslot_adjustment(band, e["base_salary_cents"], m["kind"])
        m["provisional_adjustment_cents"] = adj
    m["submitted_by_user_id"] = user_id
    m["status"] = "SUBMITTED"
    bump(m)


@bp.route("/comp/mapping-decisions/<mid>/submit", methods=["POST"])
def submit_mapping(mid):
    user_id, _ = require_roles("DepartmentManager")
    m = get_md_or_404(mid)
    if m["status"] in MD_TERMINAL:
        raise already_terminal("mapping decision is terminal")
    if m["status"] != "DRAFT":
        raise invalid_state_transition("submit declared only from DRAFT")
    _do_submit(m, user_id)
    return success_object(md_view(m))


@bp.route("/comp/mapping-decisions/<mid>/hrbp-review", methods=["POST"])
def hrbp_review(mid):
    require_roles("HRBP")
    m = get_md_or_404(mid)
    if m["status"] in MD_TERMINAL:
        raise already_terminal("mapping decision is terminal")
    if m["status"] != "SUBMITTED":
        raise invalid_state_transition("hrbp-review declared only from SUBMITTED")
    m["status"] = "HRBP_REVIEWED"
    bump(m)
    return success_object(md_view(m))


@bp.route("/comp/mapping-decisions/<mid>/comp-triage", methods=["POST"])
def comp_triage(mid):
    require_roles("CompAnalyst")
    m = get_md_or_404(mid)
    if m["status"] in MD_TERMINAL:
        raise already_terminal("mapping decision is terminal")
    if m["status"] != "HRBP_REVIEWED":
        raise invalid_state_transition("comp-triage declared only from HRBP_REVIEWED")
    m["status"] = "COMP_TRIAGED"
    bump(m)
    return success_object(md_view(m))


@bp.route("/comp/mapping-decisions/<mid>/approve", methods=["POST"])
def approve_mapping(mid):
    user_id, _ = require_roles("CompManager")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["expected_employee_version"])
    m = get_md_or_404(mid)
    e = _get_employee(m["employee_id"])
    # OCC (tier 5)
    expected = body["expected_employee_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("expected_employee_version must be an integer")
    if expected != e["version"]:
        raise stale_version()
    # Transition legality (tier 7)
    if m["status"] in MD_TERMINAL:
        raise already_terminal("mapping decision is terminal")
    if m["status"] != "COMP_TRIAGED":
        raise invalid_state_transition("approve declared only from COMP_TRIAGED")
    # SoD (tier 9)
    if m["submitted_by_user_id"] is not None and user_id == m["submitted_by_user_id"]:
        raise segregation_of_duties()
    # Referenced state (tier 10): employee ACTIVE + target band PUBLISHED
    if e["status"] != "ACTIVE":
        raise referenced_entity_state("employee not ACTIVE")
    to_profile = store.job_profiles.get(m["to_job_profile_id"])
    if to_profile is None:
        raise not_found("job profile not found")
    band = _select_band_final(to_profile, e["geo_zone_id"])
    if band is None:
        raise referenced_entity_state("target band not PUBLISHED")
    # Compute FINAL adjustment
    kind = m["kind"]
    new_salary, final_adj = _reslot_adjustment(band, e["base_salary_cents"], kind)
    # Fiscal (tier 13)
    if final_adj > 0:
        dept = store.departments.get(e["department_id"])
        headroom = dept["adjustment_pool_cents"] - dept["committed_pool_cents"]
        if final_adj > headroom:
            raise department_pool_exhausted()
    # Apply cascade
    m["pre_salary_cents"] = e["base_salary_cents"]
    e["job_profile_id"] = m["to_job_profile_id"]
    e["base_salary_cents"] = new_salary
    if kind == "DOWNSLOT":
        if new_salary > band["max_cents"]:
            e["red_circled"] = True
    recompute_employee_health(e)
    bump(e)
    m["final_adjustment_cents"] = final_adj
    m["status"] = "APPROVED"
    from services import clock as _clock
    m["approved_at"] = _clock.now_iso()
    m["decided_by_user_id"] = user_id
    bump(m)
    dept = store.departments.get(e["department_id"])
    if dept is not None:
        if final_adj > 0:
            dept["committed_pool_cents"] += final_adj
        recompute_department_payroll(dept)
        bump(dept)
    prog = current_program()
    if prog is not None:
        recompute_program_payroll(prog)
        bump(prog)
    return success_object(md_view(m))


@bp.route("/comp/mapping-decisions/<mid>/reject", methods=["POST"])
def reject_mapping(mid):
    user_id, _ = require_roles("CompManager")
    m = get_md_or_404(mid)
    if m["status"] in MD_TERMINAL:
        raise already_terminal("mapping decision is terminal")
    if m["status"] != "COMP_TRIAGED":
        raise invalid_state_transition("reject declared only from COMP_TRIAGED")
    m["status"] = "REJECTED"
    m["decided_by_user_id"] = user_id
    bump(m)
    return success_object(md_view(m))


@bp.route("/comp/mapping-decisions/<mid>/return", methods=["POST"])
def return_mapping(mid):
    user_id, role = require_roles("HRBP", "CompAnalyst")
    m = get_md_or_404(mid)
    if m["status"] in MD_TERMINAL:
        raise already_terminal("mapping decision is terminal")
    allowed = False
    if role == "HRBP" and m["status"] == "SUBMITTED":
        allowed = True
    elif role == "CompAnalyst" and m["status"] == "HRBP_REVIEWED":
        allowed = True
    if not allowed:
        raise invalid_state_transition("return not declared for current state/role")
    m["status"] = "RETURNED"
    bump(m)
    return success_object(md_view(m))


@bp.route("/comp/mapping-decisions/<mid>/resubmit", methods=["POST"])
def resubmit_mapping(mid):
    user_id, _ = require_roles("DepartmentManager")
    m = get_md_or_404(mid)
    if m["status"] in MD_TERMINAL:
        raise already_terminal("mapping decision is terminal")
    if m["status"] != "RETURNED":
        raise invalid_state_transition("resubmit declared only from RETURNED")
    _do_submit(m, user_id)
    return success_object(md_view(m))


@bp.route("/comp/mapping-decisions/<mid>/withdraw", methods=["POST"])
def withdraw_mapping(mid):
    user_id, _ = require_roles("DepartmentManager")
    m = get_md_or_404(mid)
    if m["status"] in MD_TERMINAL:
        raise already_terminal("mapping decision is terminal")
    if m["status"] not in ("DRAFT", "SUBMITTED", "RETURNED"):
        raise invalid_state_transition("withdraw declared only from DRAFT, SUBMITTED, RETURNED")
    e = _get_employee(m["employee_id"])
    _check_ownership(user_id, e)
    m["status"] = "WITHDRAWN"
    bump(m)
    return success_object(md_view(m))


@bp.route("/comp/mapping-decisions/<mid>/reverse", methods=["POST"])
def reverse_mapping(mid):
    require_roles("CompManager")
    m = get_md_or_404(mid)
    if m["status"] in MD_TERMINAL:
        raise already_terminal("mapping decision is terminal")
    if m["status"] != "APPROVED":
        raise invalid_state_transition("reverse declared only from APPROVED")
    prog = current_program()
    if prog is None or prog["status"] not in ("MAPPING_OPEN", "PUBLISHED"):
        raise program_state_forbids("reverse requires program MAPPING_OPEN or PUBLISHED")
    # 30-day reversal window
    anchor = _to_date(m["approved_at"])
    now_date = clock.now().date()
    if now_date > anchor + timedelta(days=30):
        raise reverse_window_expired()
    e = _get_employee(m["employee_id"])
    # Compensation
    e["base_salary_cents"] = m["pre_salary_cents"]
    e["job_profile_id"] = m["from_job_profile_id"]
    recompute_employee_health(e)
    bump(e)
    dept = store.departments.get(e["department_id"])
    if dept is not None:
        if m["final_adjustment_cents"] and m["final_adjustment_cents"] > 0:
            dept["committed_pool_cents"] -= m["final_adjustment_cents"]
        recompute_department_payroll(dept)
        bump(dept)
    if prog is not None:
        recompute_program_payroll(prog)
        bump(prog)
    m["status"] = "REVERSED"
    bump(m)
    return success_object(md_view(m))
