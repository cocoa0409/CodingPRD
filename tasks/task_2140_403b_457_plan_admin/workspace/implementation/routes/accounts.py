"""Provider contracts (VendorAccount)."""
from flask import Blueprint, g, request

import auth
import calc
import derive
import envelope
import serialize
import store
import validate as V
from auth import endpoint
from errors import ApiError

bp = Blueprint("accounts", __name__)


@bp.post("/plan-admin/vendor-accounts")
@endpoint(["PlanSponsorAdmin", "VendorRepresentative"])
def create_vendor_account():
    body = V.body_of(request)
    participant_id = V.req_str(body, "participant_id")
    plan_id = V.req_str(body, "plan_id")
    vendor_id = V.req_str(body, "vendor_id")
    contract_number = V.req_str(body, "contract_number")
    accumulated = V.opt_int(body, "accumulated_benefit_cents", 0, minimum=0)
    vested_bps = V.opt_int(body, "vested_percentage_bps", 10000, minimum=0, maximum=10000)
    prior_years = V.opt_int(body, "prior_years_elective_deferrals_cents", 0, minimum=0)

    participant = auth.participant(participant_id)     # rung 5
    plan = auth.plan(plan_id)                          # rung 5
    auth.vendor(vendor_id)                             # rung 5

    if g.role == "VendorRepresentative":               # rung 6
        auth.require(vendor_id == g.user_id)
    else:
        auth.own_plan(plan)

    if plan["status"] not in ("ACTIVE", "FROZEN"):     # rung 10
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "The governing plan is %s." % plan["status"])
    if (plan["nondiscrimination_regime"] == "TOP_HAT_457"
            and not participant["is_select_management_or_hce"]):   # rung 18
        raise ApiError("ERR_NOT_TOP_HAT_ELIGIBLE",
                       "A top-hat 457(b) plan admits only select management or highly "
                       "compensated employees.")

    row = store.common_fields()
    row.update({
        "participant_id": participant_id,
        "plan_id": plan_id,
        "vendor_id": vendor_id,
        "contract_number": contract_number,
        "accumulated_benefit_cents": accumulated,
        "vested_percentage_bps": vested_bps,
        "vested_balance_cents": calc.vested_balance(accumulated, vested_bps),
        "outstanding_loan_balance_cents": 0,
        "highest_outstanding_loan_12mo_cents": 0,
        "ytd_elective_deferrals_cents": 0,
        "ytd_employer_contributions_cents": 0,
        "prior_years_elective_deferrals_cents": prior_years,
        "pending_lost_earnings_cents": 0,
        "last_balance_report_date": None,
        "status": "OPEN",
    })
    store.vendor_accounts[row["id"]] = row
    derive.recompute_participant(participant)
    return envelope.created(serialize.vendor_account(row))


@bp.get("/plan-admin/vendor-accounts/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_vendor_account(row_id):
    return envelope.ok(serialize.vendor_account(auth.vendor_account(row_id)))


@bp.get("/plan-admin/vendor-accounts")
@endpoint(auth.ALL_ROLES)
def list_vendor_accounts():
    args = request.args
    limit, offset = V.pagination(args)
    participant_id = args.get("participant_id")
    plan_id = args.get("plan_id")
    vendor_id = args.get("vendor_id")
    status = V.query_enum(args, "status", {"OPEN", "CLOSED"})
    items = store.rows(store.vendor_accounts)
    if participant_id:
        items = [a for a in items if a["participant_id"] == participant_id]
    if plan_id:
        items = [a for a in items if a["plan_id"] == plan_id]
    if vendor_id:
        items = [a for a in items if a["vendor_id"] == vendor_id]
    if status:
        items = [a for a in items if a["status"] == status]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.vendor_account(a) for a in page], limit, offset, total)


@bp.post("/plan-admin/vendor-accounts/<row_id>/balance-report")
@endpoint(["VendorRepresentative"])
def balance_report(row_id):
    body = V.body_of(request)
    expected_version = V.req_int(body, "expected_vendor_account_version")
    as_of_date = V.req_date(body, "as_of_date")
    accumulated = V.req_int(body, "accumulated_benefit_cents", minimum=0)
    outstanding = V.req_int(body, "outstanding_loan_balance_cents", minimum=0)
    highest = V.req_int(body, "highest_outstanding_loan_12mo_cents", minimum=0)
    ytd_elective = V.opt_int(body, "ytd_elective_deferrals_cents", minimum=0)
    ytd_employer = V.opt_int(body, "ytd_employer_contributions_cents", minimum=0)
    prior_years = V.opt_int(body, "prior_years_elective_deferrals_cents", minimum=0)

    va = auth.vendor_account(row_id)                 # rung 4
    auth.require(va["vendor_id"] == g.user_id)       # rung 6
    if expected_version != va["version"]:            # rung 8
        raise ApiError("ERR_STALE_VERSION",
                       "expected_vendor_account_version does not match the contract's version.")
    if as_of_date > store.today():                   # rung 29
        raise ApiError("ERR_DATE_IN_FUTURE", "as_of_date is in the future.")

    va["accumulated_benefit_cents"] = accumulated
    va["outstanding_loan_balance_cents"] = outstanding
    va["highest_outstanding_loan_12mo_cents"] = highest
    if ytd_elective is not None:
        va["ytd_elective_deferrals_cents"] = ytd_elective
    if ytd_employer is not None:
        va["ytd_employer_contributions_cents"] = ytd_employer
    if prior_years is not None:
        va["prior_years_elective_deferrals_cents"] = prior_years
    derive.recompute_vendor_account(va)
    va["last_balance_report_date"] = as_of_date.isoformat()
    store.touch(va)

    participant = store.participants.get(va["participant_id"])
    if participant:
        derive.recompute_participant(participant, bump=True)
    plan = store.plans.get(va["plan_id"])
    if plan:
        derive.recompute_plan_excess(plan)
    return envelope.ok(serialize.vendor_account(va))
