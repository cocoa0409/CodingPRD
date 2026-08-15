"""ThroughputGuarantee endpoints (PRD §3.9)."""
from flask import Blueprint

from db import children, store
from errors import (ApiError, ERR_GUARANTEE_WINDOW_VIOLATION, bad_request,
                    invalid_state, not_found)
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SITE_SUPERVISOR as SS
from middleware import ROLE_SERVICE_MANAGER as SM
from response import success, success_list
from services import calculations as calc
from services.domain import (common_fields, guarantee_of_project, maybe_close_project,
                             post_ledger_entry, pub, pubs, touch)
from timeutil import parse_dt
from validation import as_enum, as_num, as_str, body, paginate, pagination, req

bp = Blueprint("guarantees", __name__)

READ_ROLES = {FA, PE, SS, SM}
OUTCOMES = ("MET", "MISSED")


def get_guarantee(guarantee_id):
    g = store.guarantees.get(guarantee_id)
    if g is None:
        raise not_found("Throughput guarantee not found")
    return g


@bp.get("/robotics/throughput-guarantees/<guarantee_id>")
def get_one_guarantee(guarantee_id):
    authenticate(READ_ROLES)
    return success(pub(get_guarantee(guarantee_id)))


@bp.get("/robotics/cell-projects/<project_id>/throughput-guarantee")
def get_project_guarantee(project_id):
    authenticate(READ_ROLES)
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    limit, offset = pagination()
    items = children("guarantees", "cell_project_id", project_id)
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.post("/robotics/throughput-guarantees/<guarantee_id>/close")
def close_guarantee(guarantee_id):
    authenticate({SM})
    g = get_guarantee(guarantee_id)
    if g["guarantee_status"] != "MEASURING":
        raise invalid_state("Only a MEASURING guarantee can be closed")
    # Window compliance (priority 11): close requires clock >= window_end_utc.
    window_end = parse_dt(g["window_end_utc"], "window_end_utc")
    if store.logical_clock < window_end:
        raise ApiError(ERR_GUARANTEE_WINDOW_VIOLATION, 422,
                       "The guarantee window has not fully elapsed")
    b = body()
    outcome = as_enum(req(b, "outcome"), "outcome", OUTCOMES)
    observed_ct = as_num(req(b, "observed_cycle_time_s"), "observed_cycle_time_s")
    observed_uptime = as_num(req(b, "observed_uptime_pct"), "observed_uptime_pct", 0, 100)
    project = store.projects[g["cell_project_id"]]
    met_conditions = (
        calc.d(observed_ct) <= calc.d(project["contracted_cycle_time_s"])
        and calc.d(observed_uptime) >= calc.d(project["guaranteed_oee_pct"])
    )
    if outcome == "MET" and not met_conditions:
        raise bad_request(
            "outcome MET requires observed_cycle_time_s <= contracted_cycle_time_s "
            "and observed_uptime_pct >= guaranteed_oee_pct")
    if outcome == "MISSED" and met_conditions:
        raise bad_request(
            "outcome MISSED requires observed_cycle_time_s > contracted_cycle_time_s "
            "or observed_uptime_pct < guaranteed_oee_pct")
    g["observed_cycle_time_s"] = observed_ct
    g["observed_uptime_pct"] = observed_uptime
    if outcome == "MET":
        g["guarantee_status"] = "MET"
        # Final RELEASE zeroes the remaining retention balance.
        post_ledger_entry(project, "RELEASE", -project["retention_balance_cents"], g["id"])
    else:
        shortfall = calc.throughput_shortfall(
            observed_ct, project["contracted_cycle_time_s"],
            observed_uptime, project["guaranteed_oee_pct"])
        g["shortfall_pct"] = shortfall
        g["guarantee_status"] = "MISSED"
        penalty = calc.guarantee_penalty_cents(
            project["retention_balance_cents"], project["contract_value_cents"], shortfall)
        post_ledger_entry(project, "PENALTY", -penalty, g["id"])
    touch(g)
    maybe_close_project(project)
    touch(project)
    return success(pub(g))


@bp.post("/robotics/throughput-guarantees/<guarantee_id>/waive")
def waive_guarantee(guarantee_id):
    authenticate({FA})
    g = get_guarantee(guarantee_id)
    if g["guarantee_status"] != "MEASURING":
        raise invalid_state("Only a MEASURING guarantee can be waived")
    # Waive requires the clock to read strictly before window_end_utc.
    window_end = parse_dt(g["window_end_utc"], "window_end_utc")
    if not store.logical_clock < window_end:
        raise ApiError(ERR_GUARANTEE_WINDOW_VIOLATION, 422,
                       "The guarantee window has already elapsed")
    b = body()
    as_str(req(b, "waiver_reference"), "waiver_reference")
    project = store.projects[g["cell_project_id"]]
    balance = project["retention_balance_cents"]
    release_half = calc.rhu_int(calc.d(balance) * calc.Decimal("0.5"))
    remainder = balance - release_half
    post_ledger_entry(project, "RELEASE", -release_half, g["id"])
    post_ledger_entry(project, "ADJUST", -remainder, g["id"])
    g["guarantee_status"] = "WAIVED"
    touch(g)
    maybe_close_project(project)
    touch(project)
    return success(pub(g))
