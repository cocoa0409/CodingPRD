"""Worker endpoints: intake, read, OCC-guarded pension patch, death report,
and the worker-scoped list endpoints (earnings years, relationships, wage
reports, correction requests).
"""

from flask import Blueprint

import timeutil as tu
import validation as v
from db import store, stamp_common_new, touch, created_key
from envelope import ok, paginate
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_WORKER_NOT_FOUND,
)
from security import (
    ROLE_CLAIMANT,
    ROLE_CLAIMS_SPECIALIST,
    ROLE_EMPLOYER,
    ROLE_PROGRAM_ADMINISTRATOR,
    ROLE_SENIOR_ADJUDICATOR,
    authenticate,
    claimant_owns,
    is_claimant,
    require_role,
)
from serializers import (
    correction_dict,
    earnings_year_dict,
    relationship_dict,
    wage_report_dict,
    worker_dict,
)

bp = Blueprint("workers", __name__)

READ_ROLES = {ROLE_CLAIMS_SPECIALIST, ROLE_SENIOR_ADJUDICATOR, ROLE_PROGRAM_ADMINISTRATOR, ROLE_CLAIMANT}


def load_worker(worker_id):
    w = store.workers.get(worker_id)
    if w is None:
        raise ApiError(ERR_WORKER_NOT_FOUND, f"No worker with id {worker_id}.")
    return w


def _scope_worker(ctx, worker_id):
    """Claimant ownership on worker-path endpoints is a pure id comparison,
    evaluated before existence (PRD §2.9 layer 3 precedes layer 5)."""
    if is_claimant(ctx):
        claimant_owns(ctx, worker_id)
    return load_worker(worker_id)


@bp.route("/ssa/workers", methods=["POST"])
def create_worker():
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST, ROLE_PROGRAM_ADMINISTRATOR})
    body = v.get_body()
    full_name = v.req_str(body, "full_name")
    birth_year = v.req_int(body, "birth_year", min_v=1900, max_v=2100)
    birth_month = v.req_int(body, "birth_month", min_v=1, max_v=12)
    pension = v.opt_int(body, "noncovered_pension_monthly_cents", default=0, min_v=0)
    pension_start = v.opt_month(body, "noncovered_pension_start_month")
    worker = stamp_common_new(
        {
            "full_name": full_name,
            "birth_year": birth_year,
            "birth_month": birth_month,
            "noncovered_pension_monthly_cents": pension,
            "noncovered_pension_start_month": pension_start,
            "status": "LIVING",
            "death_date": None,
            "fra_months": 804 if birth_year >= 1960 else 792,
            "eligibility_year": birth_year + 62,
            "withdrawal_used": False,
        }
    )
    store.workers[worker["id"]] = worker
    return ok(worker_dict(worker), 201)


@bp.route("/ssa/workers/<worker_id>", methods=["GET"])
def get_worker(worker_id):
    ctx = authenticate()
    require_role(ctx, READ_ROLES)
    worker = _scope_worker(ctx, worker_id)
    return ok(worker_dict(worker))


@bp.route("/ssa/workers/<worker_id>", methods=["PATCH"])
def patch_worker(worker_id):
    """Record/update the non-covered pension; OCC-guarded; recomputes the
    worker's own ENTITLED/SUSPENDED claims (WEP) and auxiliary claims where
    this worker is the claimant (GPO) — both are claims with
    worker_id == this worker."""
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    pension = v.req_int(body, "noncovered_pension_monthly_cents", min_v=0)
    pension_start = v.req_month_nullable(body, "noncovered_pension_start_month")
    expected = v.req_int(body, "expected_worker_version", min_v=0)
    worker = load_worker(worker_id)
    if worker["status"] == "DECEASED":
        raise ApiError(ERR_INVALID_STATE, "A DECEASED worker record is terminal.")
    if expected != worker["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_worker_version does not match the worker's current version.")
    worker["noncovered_pension_monthly_cents"] = pension
    worker["noncovered_pension_start_month"] = pension_start
    touch(worker)
    from benefits import recompute_claim  # local import: benefits <- routes cycle guard

    affected = [
        c
        for c in store.claims.values()
        if c["worker_id"] == worker_id and c["status"] in ("ENTITLED", "SUSPENDED")
    ]
    affected.sort(key=created_key)
    for c in affected:
        recompute_claim(c, "PENSION_UPDATED")
        touch(c)
    return ok(worker_dict(worker))


@bp.route("/ssa/workers/<worker_id>/report-death", methods=["POST"])
def report_death(worker_id):
    """Worker LIVING -> DECEASED; cascades own ENTITLED/SUSPENDED claims to
    TERMINATED (benefit zeroed) and their ACTIVE payee cases to ENDED."""
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST})
    # Layer 4 — body well-formedness precedes path resolution (PRD §2.9).
    body = v.get_body()
    death_date = v.req_date(body, "death_date")
    worker = load_worker(worker_id)
    if worker["status"] != "LIVING":
        raise ApiError(ERR_INVALID_STATE, "Worker is already DECEASED.")
    if tu.parse_date_str(death_date) > store.clock_date():
        raise ApiError(ERR_INVALID_REQUEST, "death_date may not be later than the logical clock date.")
    worker["status"] = "DECEASED"
    worker["death_date"] = death_date
    touch(worker)
    affected_claims = [
        c
        for c in store.claims.values()
        if c["worker_id"] == worker_id and c["status"] in ("ENTITLED", "SUSPENDED")
    ]
    affected_claims.sort(key=created_key)
    for c in affected_claims:
        c["status"] = "TERMINATED"
        c["monthly_benefit_cents"] = 0
        c["suspended_since"] = None
        touch(c)
        for pc in store.payees.values():
            if pc["claim_id"] == c["id"] and pc["status"] == "ACTIVE":
                pc["status"] = "ENDED"
                touch(pc)
        c["has_active_payee"] = False
    return ok(worker_dict(worker))


def _list_worker_children(ctx, worker_id, table, serializer, roles):
    require_role(ctx, roles)
    _scope_worker(ctx, worker_id)
    rows = [r for r in table.values() if r["worker_id"] == worker_id]
    rows.sort(key=created_key)
    page, fields = paginate(rows)
    return ok([serializer(r) for r in page], page=fields)


@bp.route("/ssa/workers/<worker_id>/earnings-years", methods=["GET"])
def list_earnings_years(worker_id):
    ctx = authenticate()
    return _list_worker_children(ctx, worker_id, store.earnings_years, earnings_year_dict, READ_ROLES)


@bp.route("/ssa/workers/<worker_id>/relationships", methods=["GET"])
def list_worker_relationships(worker_id):
    ctx = authenticate()
    require_role(ctx, {ROLE_CLAIMS_SPECIALIST, ROLE_SENIOR_ADJUDICATOR, ROLE_CLAIMANT})
    _scope_worker(ctx, worker_id)
    rows = [
        r
        for r in store.relationships.values()
        if r["worker_id"] == worker_id or r["spouse_worker_id"] == worker_id
    ]
    rows.sort(key=created_key)
    page, fields = paginate(rows)
    return ok([relationship_dict(r) for r in page], page=fields)


@bp.route("/ssa/workers/<worker_id>/wage-reports", methods=["GET"])
def list_worker_wage_reports(worker_id):
    ctx = authenticate()
    return _list_worker_children(
        ctx,
        worker_id,
        store.wage_reports,
        wage_report_dict,
        {ROLE_CLAIMS_SPECIALIST, ROLE_PROGRAM_ADMINISTRATOR, ROLE_EMPLOYER, ROLE_CLAIMANT},
    )


@bp.route("/ssa/workers/<worker_id>/correction-requests", methods=["GET"])
def list_worker_corrections(worker_id):
    ctx = authenticate()
    return _list_worker_children(
        ctx,
        worker_id,
        store.corrections,
        correction_dict,
        {ROLE_CLAIMS_SPECIALIST, ROLE_SENIOR_ADJUDICATOR, ROLE_CLAIMANT},
    )
