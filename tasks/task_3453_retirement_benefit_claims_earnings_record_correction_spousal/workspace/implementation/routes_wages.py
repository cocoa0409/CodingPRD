"""Employer wage reports (POST /ssa/wage-reports).

Reports for one (worker, tax_year) credit strictly in created_at ASC order:
each covered report's posted_amount_cents is min(amount_cents, headroom
remaining under that year's taxable maximum). Non-covered reports credit
their full amount into the year's noncovered_earnings_cents, which is
informational and never enters AIME. The EarningsYear row is upserted.
"""

from flask import Blueprint

import calc
import validation as v
from db import store, stamp_new, stamp_common_new, touch, created_key
from envelope import ok
from errors import ApiError, ERR_WORKER_NOT_FOUND
from security import (
    ROLE_EMPLOYER,
    ROLE_PROGRAM_ADMINISTRATOR,
    authenticate,
    require_role,
)
from serializers import wage_report_dict

bp = Blueprint("wage_reports", __name__)


def _earnings_row_for(worker_id, tax_year):
    for r in store.earnings_years.values():
        if r["worker_id"] == worker_id and r["tax_year"] == tax_year:
            return r
    return None


def _reports_for(worker_id, tax_year):
    rows = [
        r
        for r in store.wage_reports.values()
        if r["worker_id"] == worker_id and r["tax_year"] == tax_year
    ]
    rows.sort(key=created_key)
    return rows


def _recompute_earnings_row(worker_id, tax_year):
    reports = _reports_for(worker_id, tax_year)
    covered_posted = sum(r["posted_amount_cents"] for r in reports if r["covered_employment"])
    noncovered_posted = sum(r["posted_amount_cents"] for r in reports if not r["covered_employment"])
    posted = min(covered_posted, calc.taxable_max_cents(tax_year))
    row = _earnings_row_for(worker_id, tax_year)
    if row is None:
        row = stamp_common_new(
            {
                "worker_id": worker_id,
                "tax_year": tax_year,
                "posted_earnings_cents": posted,
                "noncovered_earnings_cents": noncovered_posted,
                "corrected": False,
            }
        )
        store.earnings_years[row["id"]] = row
    else:
        row["posted_earnings_cents"] = posted
        row["noncovered_earnings_cents"] = noncovered_posted
        touch(row)
    return row


@bp.route("/ssa/wage-reports", methods=["POST"])
def create_wage_report():
    ctx = authenticate()
    require_role(ctx, {ROLE_EMPLOYER, ROLE_PROGRAM_ADMINISTRATOR})
    body = v.get_body()
    worker_id = v.req_str(body, "worker_id")
    employer_name = v.req_str(body, "employer_name")
    tax_year = v.req_int(body, "tax_year", min_v=1986, max_v=2100)
    amount = v.req_int(body, "amount_cents", min_v=1)
    covered = v.req_bool(body, "covered_employment", default=True)
    if worker_id not in store.workers:
        raise ApiError(ERR_WORKER_NOT_FOUND, f"No worker with id {worker_id}.")
    if covered:
        credited_so_far = sum(
            r["posted_amount_cents"] for r in _reports_for(worker_id, tax_year) if r["covered_employment"]
        )
        headroom = max(0, calc.taxable_max_cents(tax_year) - credited_so_far)
        posted_amount = min(amount, headroom)
    else:
        posted_amount = amount
    report = stamp_new(
        {
            "worker_id": worker_id,
            "employer_name": employer_name,
            "tax_year": tax_year,
            "amount_cents": amount,
            "covered_employment": covered,
            "posted_amount_cents": posted_amount,
            "status": "POSTED",
        }
    )
    store.wage_reports[report["id"]] = report
    _recompute_earnings_row(worker_id, tax_year)
    return ok(wage_report_dict(report), 201)
