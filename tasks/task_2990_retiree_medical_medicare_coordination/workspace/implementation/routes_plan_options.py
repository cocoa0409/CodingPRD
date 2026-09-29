"""PlanOption endpoints: catalogue, activation, the actuarial-equivalence chain
and plan change notices (PRD 3.1, 3.2)."""

from flask import Blueprint, request

import calc
import errors
from auth import (ALL_ROLES, ROLE_ACTUARY, ROLE_BENEFITS_ADMIN,
                  ROLE_COMPLIANCE_OFFICER, require_caller)
from domain import body_reference, get_plan_option, get_plan_year
from envelope import object_response, paginate
from errors import fail
from routes_retirees import GRANDFATHER_GROUPS
from store import base_record, db, now, order_asc, touch
from validate import read_body

bp = Blueprint("plan_options", __name__)

COVERAGE_CLASSES = ("PRE_MEDICARE_GROUP", "MEDICARE_GROUP_WRAP",
                    "INDIVIDUAL_EXCHANGE_HRA")
SUBSIDY_VEHICLES = ("RDS", "EGWP", "NONE")
OPTION_STATUSES = ("DRAFT", "ACTIVE", "CLOSED_TO_NEW", "RETIRED")
CERTIFICATION_STATUSES = ("NOT_STARTED", "ATTESTED", "CERTIFIED", "REJECTED")
CERTIFICATION_DECISIONS = ("CERTIFY", "REJECT")
CHANGE_TYPES = ("PREMIUM_INCREASE", "PLAN_TERMINATION")

ATTESTABLE_STATUSES = ("DRAFT", "ACTIVE", "CLOSED_TO_NEW")
ATTESTATION_ENTRY_STATUSES = ("NOT_STARTED", "REJECTED")


@bp.post("/retiree-benefits/plan-options")
def create_plan_option():
    require_caller((ROLE_BENEFITS_ADMIN,))
    body = read_body()
    body_reference(body, "plan_year_id", get_plan_year)

    plan_year_id = body.string("plan_year_id")
    plan_code = body.string("plan_code", min_len=1, max_len=32)
    coverage_class = body.enum("coverage_class", COVERAGE_CLASSES)
    monthly_premium_cents = body.cents("monthly_premium_cents")
    requires_part_b = body.boolean("requires_medicare_part_b")
    allowed_groups = body.enum_array("allowed_grandfather_groups",
                                     GRANDFATHER_GROUPS, non_empty=True)
    subsidy_vehicle = body.enum("subsidy_vehicle", SUBSIDY_VEHICLES)
    gross_bps = body.bps("rx_gross_value_bps")
    net_bps = body.bps("rx_net_value_bps")

    for existing in db.plan_options.values():
        if (existing["plan_year_id"] == plan_year_id
                and existing["plan_code"] == plan_code):
            fail(errors.ERR_DUPLICATE_PLAN_CODE)

    record = base_record()
    record.update({
        "plan_year_id": plan_year_id,
        "plan_code": plan_code,
        "coverage_class": coverage_class,
        "monthly_premium_cents": monthly_premium_cents,
        "requires_medicare_part_b": requires_part_b,
        "allowed_grandfather_groups": allowed_groups,
        "subsidy_vehicle": subsidy_vehicle,
        "rx_gross_value_bps": gross_bps,
        "rx_net_value_bps": net_bps,
        "status": "DRAFT",
        "subsidy_certification_status": "NOT_STARTED",
        "gross_test_passed": False,
        "net_test_passed": False,
        "equivalence_margin_bps": 0,
        "attested_by_user_id": None,
        "certified_by_user_id": None,
        "enrolled_count": 0,
        "pending_change_type": None,
        "pending_change_effective_date": None,
        "pending_new_monthly_premium_cents": None,
        "change_notice_issued_at": None,
    })
    db.plan_options[record["id"]] = record
    return object_response(record, 201)


@bp.get("/retiree-benefits/plan-options/<plan_option_id>")
def read_plan_option(plan_option_id):
    require_caller(ALL_ROLES)
    return object_response(get_plan_option(plan_option_id))


@bp.get("/retiree-benefits/plan-options")
def list_plan_options():
    require_caller(ALL_ROLES)
    rows = list(db.plan_options.values())
    for field in ("plan_year_id", "coverage_class", "status",
                  "subsidy_certification_status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginate(order_asc(rows))


@bp.post("/retiree-benefits/plan-options/<plan_option_id>/activate")
def activate_plan_option(plan_option_id):
    require_caller((ROLE_BENEFITS_ADMIN,))
    option = get_plan_option(plan_option_id)

    if option["status"] != "DRAFT":
        fail(errors.ERR_PLAN_OPTION_NOT_ACTIVE,
             "Only a DRAFT plan option can be activated.")

    plan_year = db.plan_years.get(option["plan_year_id"])
    if plan_year is None or plan_year["status"] not in ("DRAFT", "OPEN"):
        fail(errors.ERR_PLAN_YEAR_NOT_OPEN,
             "Activation requires the owning plan year to be DRAFT or OPEN.")

    option["status"] = "ACTIVE"
    touch(option)
    return object_response(option)


@bp.post("/retiree-benefits/plan-options/<plan_option_id>/attest")
def attest_plan_option(plan_option_id):
    caller = require_caller((ROLE_ACTUARY,))
    option = get_plan_option(plan_option_id)
    body = read_body()
    gross_bps = body.bps("rx_gross_value_bps")
    net_bps = body.bps("rx_net_value_bps")

    if option["subsidy_vehicle"] == "NONE":
        fail(errors.ERR_INVALID_REQUEST,
             "An option whose subsidy_vehicle is NONE cannot be attested.")
    if option["subsidy_certification_status"] not in ATTESTATION_ENTRY_STATUSES:
        fail(errors.ERR_INVALID_REQUEST,
             "Attestation requires subsidy_certification_status NOT_STARTED or "
             "REJECTED.")
    if option["status"] not in ATTESTABLE_STATUSES:
        fail(errors.ERR_PLAN_OPTION_NOT_ACTIVE,
             "A RETIRED plan option is beyond attestation.")

    results = calc.equivalence_results(gross_bps, net_bps)
    if not results["gross_test_passed"]:
        fail(errors.ERR_ACTUARIAL_GROSS_TEST_FAILED)
    if option["subsidy_vehicle"] == "EGWP" and not results["net_test_passed"]:
        fail(errors.ERR_ACTUARIAL_NET_TEST_FAILED)

    option["rx_gross_value_bps"] = gross_bps
    option["rx_net_value_bps"] = net_bps
    option["gross_test_passed"] = results["gross_test_passed"]
    option["net_test_passed"] = results["net_test_passed"]
    option["equivalence_margin_bps"] = results["equivalence_margin_bps"]
    option["attested_by_user_id"] = caller.user_id
    option["subsidy_certification_status"] = "ATTESTED"
    touch(option)
    return object_response(option)


@bp.post("/retiree-benefits/plan-options/<plan_option_id>/subsidy-certification")
def certify_subsidy(plan_option_id):
    caller = require_caller((ROLE_COMPLIANCE_OFFICER,))
    option = get_plan_option(plan_option_id)
    body = read_body()
    decision = body.enum("decision", CERTIFICATION_DECISIONS)

    if option["subsidy_certification_status"] != "ATTESTED":
        fail(errors.ERR_INVALID_REQUEST,
             "A subsidy decision requires subsidy_certification_status ATTESTED.")
    if option["attested_by_user_id"] is not None \
            and caller.user_id == option["attested_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The attesting actuary may not certify their own attestation.")

    option["certified_by_user_id"] = caller.user_id
    option["subsidy_certification_status"] = (
        "CERTIFIED" if decision == "CERTIFY" else "REJECTED")
    touch(option)
    return object_response(option)


@bp.post("/retiree-benefits/plan-options/<plan_option_id>/change-notice")
def issue_change_notice(plan_option_id):
    require_caller((ROLE_BENEFITS_ADMIN,))
    option = get_plan_option(plan_option_id)
    body = read_body()
    change_type = body.enum("change_type", CHANGE_TYPES)
    effective_date = body.instant("effective_date")
    new_premium = body.cents("new_monthly_premium_cents", required=False,
                             nullable=True, default=None)

    if change_type == "PREMIUM_INCREASE" and new_premium is None:
        fail(errors.ERR_INVALID_REQUEST,
             "A PREMIUM_INCREASE notice requires new_monthly_premium_cents.")

    if option["status"] != "ACTIVE":
        fail(errors.ERR_PLAN_OPTION_NOT_ACTIVE)

    plan_year = db.plan_years.get(option["plan_year_id"])
    required_days = plan_year["notice_lead_days"] if plan_year else 0
    if calc.whole_days_between(now(), effective_date) < required_days:
        fail(errors.ERR_NOTICE_LEAD_TIME_INSUFFICIENT)

    option["change_notice_issued_at"] = now()
    option["pending_change_type"] = change_type
    option["pending_change_effective_date"] = effective_date
    option["pending_new_monthly_premium_cents"] = (
        new_premium if change_type == "PREMIUM_INCREASE" else None)
    touch(option)
    return object_response(option)
