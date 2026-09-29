"""PRD 3.6 / 3.7 -- coverage and nondiscrimination testing, and the
plan-level annual return with its fork-join clearance."""

from flask import Blueprint, g

import authz
import calc
import clockcal
import envelope
import recompute
import store
import validate
from errors import fail
from routes_setup import need

bp = Blueprint("compliance", __name__)

TEST_TYPES = ("COVERAGE_410B_RATIO", "ADP", "ACP")
SCOPES = ("PLAN_LEVEL", "EMPLOYER_LEVEL")
AUDIT_OPINIONS = ("UNMODIFIED", "QUALIFIED", "DISCLAIMER")
POPULATION_STATUSES = ("ACTIVE", "SUSPENDED")
SCHEDULE_H_TIMELINESS = ("LATE", "CORRECTION_COMPUTED", "CORRECTED")
PLAN_YEAR_MIN = 2020
PLAN_YEAR_MAX = 2030


def _test_population(test):
    """Identical for every test type; depends only on `scope`. Employers in
    APPLIED, ELECTIONS_SUBMITTED, RETURNED_FOR_REVISION and EXITED are excluded
    at either scope."""
    if test["scope"] == "EMPLOYER_LEVEL":
        employer = store.get("employers", test["adopting_employer_id"])
        candidates = [employer] if employer is not None else []
    else:
        candidates = store.employers_of_plan(store.plan_of_test(test))
    return [e for e in candidates if e["adoption_status"] in POPULATION_STATUSES]


# ==========================================================================
# ComplianceTest
# ==========================================================================


@bp.post("/pep/compliance-tests")
def create_test():
    authz.identify()
    authz.authorize("PooledPlanProvider")
    b = validate.body()

    plan = validate.resolve_fk(
        b, "plan_document_id", "plans", "ERR_PLAN_DOCUMENT_NOT_FOUND"
    )
    employer = validate.resolve_fk(
        b,
        "adopting_employer_id",
        "employers",
        "ERR_ADOPTING_EMPLOYER_NOT_FOUND",
        required=False,
    )
    authz.own_if(plan=plan)

    validate.require_fk_shape(b, "plan_document_id")
    test_type = validate.req_enum(b, "test_type", TEST_TYPES)
    scope = validate.req_enum(b, "scope", SCOPES)
    plan_year = validate.req_int(b, "plan_year", PLAN_YEAR_MIN, PLAN_YEAR_MAX)
    if validate.present(b, "adopting_employer_id") and not isinstance(
        b["adopting_employer_id"], str
    ):
        fail("ERR_VALIDATION", "`adopting_employer_id` must be a string.")

    if plan["status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_ACTIVE")

    # Priority 35: the scope and the employer reference must agree.
    if scope == "EMPLOYER_LEVEL" and employer is None:
        fail("ERR_TEST_SCOPE_MISMATCH")
    if scope == "PLAN_LEVEL" and employer is not None:
        fail("ERR_TEST_SCOPE_MISMATCH")

    # Priority 36: a named employer must belong to the named plan.
    if employer is not None and employer["plan_document_id"] != plan["id"]:
        fail("ERR_EMPLOYER_PLAN_MISMATCH")

    # Priority 57: at most one non-CLOSED test per plan/type/scope/year/employer.
    employer_id = employer["id"] if employer is not None else None
    for other in store.tests_of_plan(plan):
        if (
            other["status"] != "CLOSED"
            and other["test_type"] == test_type
            and other["scope"] == scope
            and other["plan_year"] == plan_year
            and other["adopting_employer_id"] == employer_id
        ):
            fail("ERR_DUPLICATE_COMPLIANCE_TEST")

    # Priority 64: an employer-level test needs a defined nondiscrimination track.
    if scope == "EMPLOYER_LEVEL" and store.approved_election(employer) is None:
        fail("ERR_NO_APPROVED_ELECTION")

    record = store.insert(
        "tests",
        {
            "plan_document_id": plan["id"],
            "adopting_employer_id": employer_id,
            "test_type": test_type,
            "scope": scope,
            "plan_year": plan_year,
            "status": "SCHEDULED",
            "population_hce_count": None,
            "population_nhce_count": None,
            "benefiting_hce_count": None,
            "benefiting_nhce_count": None,
            "hce_benefiting_pct": None,
            "nhce_benefiting_pct": None,
            "ratio_pct": None,
            "hce_avg_deferral_pct": None,
            "nhce_avg_deferral_pct": None,
            "adp_limit_pct": None,
            "exemption_applied": False,
            "run_at": None,
            "failure_reason": None,
            "closed_reason": None,
        },
    )
    return envelope.ok_created(envelope.VIEWS["tests"](record))


@bp.post("/pep/compliance-tests/<test_id>/run")
def run_test(test_id):
    authz.identify()
    authz.authorize("ServiceProvider")
    test = need("tests", test_id, "ERR_COMPLIANCE_TEST_NOT_FOUND")
    plan = store.plan_of_test(test)
    authz.own(plan=plan)

    if plan["status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_ACTIVE")
    if test["status"] != "SCHEDULED":
        fail("ERR_TEST_INVALID_STATE")

    population = _test_population(test)
    if not population:
        fail("ERR_TEST_INVALID_STATE")

    test["run_at"] = clockcal.stamp()
    test["population_hce_count"] = sum(e["hce_count"] for e in population)
    test["population_nhce_count"] = sum(e["nhce_count"] for e in population)
    test["benefiting_hce_count"] = sum(e["benefiting_hce_count"] for e in population)
    test["benefiting_nhce_count"] = sum(e["benefiting_nhce_count"] for e in population)

    if test["test_type"] == "COVERAGE_410B_RATIO":
        hce_pct, nhce_pct, ratio = calc.coverage_ratio(
            test["benefiting_hce_count"],
            test["population_hce_count"],
            test["benefiting_nhce_count"],
            test["population_nhce_count"],
        )
        test["hce_benefiting_pct"] = hce_pct
        test["nhce_benefiting_pct"] = nhce_pct
        test["ratio_pct"] = ratio
        if ratio >= calc.COVERAGE_RATIO_PASS_PCT:
            test["status"] = "PASSED"
        else:
            test["status"] = "FAILED"
            test["failure_reason"] = "RATIO_BELOW_THRESHOLD"
    else:
        exempt = True
        for employer in population:
            election = store.approved_election(employer)
            if election is None or election["nondiscrimination_track"] != (
                "SAFE_HARBOR_EXEMPT"
            ):
                exempt = False
                break
        if exempt:
            test["exemption_applied"] = True
            test["status"] = "PASSED"
        else:
            nhce_avg = calc.weighted_average(
                [(e["nhce_avg_deferral_pct"], e["nhce_count"]) for e in population]
            )
            hce_avg = calc.weighted_average(
                [(e["hce_avg_deferral_pct"], e["hce_count"]) for e in population]
            )
            limit = calc.adp_limit(nhce_avg)
            test["nhce_avg_deferral_pct"] = nhce_avg
            test["hce_avg_deferral_pct"] = hce_avg
            test["adp_limit_pct"] = limit
            if hce_avg <= limit:
                test["status"] = "PASSED"
            else:
                test["status"] = "FAILED"
                test["failure_reason"] = "HCE_AVERAGE_EXCEEDS_LIMIT"

    authz.touch().bump(test)
    return envelope.ok_object(envelope.VIEWS["tests"](test))


@bp.get("/pep/compliance-tests/<test_id>")
def read_test(test_id):
    authz.identify()
    authz.authorize(
        "RegulatorOps", "PooledPlanProvider", "AdoptingEmployer", "IndependentAuditor"
    )
    test = need("tests", test_id, "ERR_COMPLIANCE_TEST_NOT_FOUND")
    employer = (
        store.get("employers", test["adopting_employer_id"])
        if test["adopting_employer_id"]
        else None
    )
    authz.own(plan=store.plan_of_test(test), employer=employer)
    return envelope.ok_object(envelope.VIEWS["tests"](test))


# ==========================================================================
# PlanFiling -- the fork-join annual return
# ==========================================================================


def _schedule_h_line(plan):
    """Every deposit of the plan that is POSTED and delinquent; a funded
    correction does not remove a deposit from this line."""
    return sum(
        d["amount_cents"]
        for d in store.deposits_of_plan(plan)
        if d["deposit_status"] == "POSTED"
        and d["timeliness_status"] in SCHEDULE_H_TIMELINESS
    )


def _holds_allocated_role(plan, sp_id):
    for alloc in store.allocations_of_plan(plan):
        if alloc["service_provider_id"] == sp_id and alloc["status"] == "ALLOCATED":
            return True
    return False


def _independent(plan, firm):
    """The named audit firm may hold no ALLOCATED fiduciary role on the plan and
    may not be linked by `affiliated_service_provider_id` in either direction to
    a provider that holds one."""
    if _holds_allocated_role(plan, firm["id"]):
        return False
    linked = set()
    if firm["affiliated_service_provider_id"]:
        linked.add(firm["affiliated_service_provider_id"])
    for other in store.all_rows("service_providers"):
        if other["affiliated_service_provider_id"] == firm["id"]:
            linked.add(other["id"])
    for sp_id in linked:
        if _holds_allocated_role(plan, sp_id):
            return False
    return True


def _join(filing):
    """Where the fork-join lands once a branch has cleared."""
    audit_done = not filing["audit_required"] or filing["audit_attested_at"] is not None
    data_done = filing["employer_data_certified_at"] is not None
    if audit_done and data_done:
        filing["filing_status"] = "READY_TO_FILE"
    else:
        filing["filing_status"] = "PARTIALLY_CLEARED"


@bp.post("/pep/plan-filings")
def create_filing():
    authz.identify()
    authz.authorize("PooledPlanProvider")
    b = validate.body()

    plan = validate.resolve_fk(
        b, "plan_document_id", "plans", "ERR_PLAN_DOCUMENT_NOT_FOUND"
    )
    authz.own_if(plan=plan)

    validate.require_fk_shape(b, "plan_document_id")
    plan_year = validate.req_int(b, "plan_year", PLAN_YEAR_MIN, PLAN_YEAR_MAX)

    for other in store.filings_of_plan(plan):
        if other["plan_year"] == plan_year:
            fail("ERR_DUPLICATE_FILING_YEAR")

    record = store.insert(
        "filings",
        {
            "plan_document_id": plan["id"],
            "plan_year": plan_year,
            "filing_status": "DRAFT",
            "prepared_by_user_id": None,
            "prepared_at": None,
            "audit_attested_at": None,
            "audit_opinion": None,
            "audit_firm_service_provider_id": None,
            "employer_data_certified_at": None,
            "certified_by_user_id": None,
            "certified_employer_count": None,
            "late_deposit_schedule_h_line_cents": None,
            "fidelity_bond_minimum_cents": None,
            "audit_required": False,
            "filing_deadline_date": None,
            "filed_date": None,
            "is_late_filing": False,
            "acknowledgment_reference": None,
        },
    )
    return envelope.ok_created(envelope.VIEWS["filings"](record))


@bp.post("/pep/plan-filings/<filing_id>/prepare")
def prepare_filing(filing_id):
    authz.identify()
    authz.authorize("ServiceProvider")
    filing = need("filings", filing_id, "ERR_PLAN_FILING_NOT_FOUND")
    plan = store.plan_of_filing(filing)
    authz.own(plan=plan)

    if plan["status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_ACTIVE")
    if filing["filing_status"] != "DRAFT":
        fail("ERR_FILING_INVALID_STATE")
    if plan["compliance_posture"] == "FROZEN":
        fail("ERR_PLAN_COMPLIANCE_FROZEN")
    for test in store.tests_of_plan(plan):
        if (
            test["scope"] == "PLAN_LEVEL"
            and test["plan_year"] == filing["plan_year"]
            and test["status"] == "SCHEDULED"
        ):
            fail("ERR_PLAN_LEVEL_TEST_OUTSTANDING")

    filing["filing_status"] = "PREPARED"
    filing["prepared_by_user_id"] = g.user_id
    filing["prepared_at"] = clockcal.stamp()
    filing["late_deposit_schedule_h_line_cents"] = _schedule_h_line(plan)
    filing["audit_required"] = plan["audit_required"]
    filing["fidelity_bond_minimum_cents"] = calc.fidelity_bond_minimum(
        plan["total_assets_cents"]
    )
    filing["filing_deadline_date"] = clockcal.fmt_date(
        calc.filing_deadline_date(clockcal.parse_date(plan["plan_year_end_date"]))
    )
    authz.touch().bump(filing)
    return envelope.ok_object(envelope.VIEWS["filings"](filing))


@bp.post("/pep/plan-filings/<filing_id>/attest")
def attest_filing(filing_id):
    authz.identify()
    authz.authorize("IndependentAuditor")
    filing = need("filings", filing_id, "ERR_PLAN_FILING_NOT_FOUND")
    plan = store.plan_of_filing(filing)
    authz.own(plan=plan)

    b = validate.body()
    firm = validate.resolve_fk(
        b,
        "audit_firm_service_provider_id",
        "service_providers",
        "ERR_SERVICE_PROVIDER_NOT_FOUND",
    )
    validate.require_fk_shape(b, "audit_firm_service_provider_id")
    opinion = validate.req_enum(b, "audit_opinion", AUDIT_OPINIONS)

    if (
        filing["filing_status"] not in ("PREPARED", "PARTIALLY_CLEARED")
        or filing["audit_attested_at"] is not None
    ):
        fail("ERR_FILING_INVALID_STATE")
    if not filing["audit_required"]:
        fail("ERR_AUDIT_NOT_REQUIRED")

    if (
        firm["plan_document_id"] != plan["id"]
        or firm["provider_type"] != "AUDITOR_FIRM"
    ):
        fail("ERR_NOT_AN_AUDITOR_FIRM")
    if not _independent(plan, firm):
        fail("ERR_AUDITOR_NOT_INDEPENDENT")
    if firm["id"] == filing["prepared_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    provider = store.get("providers", plan["pooled_plan_provider_id"])
    minimum = filing["fidelity_bond_minimum_cents"] or 0
    if provider is None or provider["fidelity_bond_amount_cents"] < minimum:
        fail("ERR_FIDELITY_BOND_INSUFFICIENT")

    filing["audit_attested_at"] = clockcal.stamp()
    filing["audit_opinion"] = opinion
    filing["audit_firm_service_provider_id"] = firm["id"]
    _join(filing)
    authz.touch().bump(filing)
    return envelope.ok_object(envelope.VIEWS["filings"](filing))


@bp.post("/pep/plan-filings/<filing_id>/certify-employer-data")
def certify_filing(filing_id):
    authz.identify()
    authz.authorize("PooledPlanProvider")
    filing = need("filings", filing_id, "ERR_PLAN_FILING_NOT_FOUND")
    plan = store.plan_of_filing(filing)
    authz.own(plan=plan)

    if (
        filing["filing_status"] not in ("PREPARED", "PARTIALLY_CLEARED")
        or filing["employer_data_certified_at"] is not None
    ):
        fail("ERR_FILING_INVALID_STATE")

    in_return = [
        e for e in store.employers_of_plan(plan) if e["adoption_status"] != "EXITED"
    ]
    for employer in in_return:
        if store.approved_election(employer) is None:
            fail("ERR_EMPLOYER_ELECTIONS_INCOMPLETE")

    filing["employer_data_certified_at"] = clockcal.stamp()
    filing["certified_by_user_id"] = g.user_id
    filing["certified_employer_count"] = len(in_return)
    _join(filing)
    authz.touch().bump(filing)
    return envelope.ok_object(envelope.VIEWS["filings"](filing))


@bp.post("/pep/plan-filings/<filing_id>/file")
def file_filing(filing_id):
    authz.identify()
    authz.authorize("RegulatorOps")
    filing = need("filings", filing_id, "ERR_PLAN_FILING_NOT_FOUND")
    plan = store.plan_of_filing(filing)
    authz.own(plan=plan)

    if filing["filing_status"] != "READY_TO_FILE":
        fail("ERR_FILING_INVALID_STATE")
    if plan["compliance_posture"] == "FROZEN":
        fail("ERR_PLAN_COMPLIANCE_FROZEN")
    if filing["audit_required"] and filing["audit_opinion"] == "DISCLAIMER":
        fail("ERR_AUDIT_OPINION_UNACCEPTABLE")

    filed = clockcal.today()
    deadline = clockcal.parse_date(filing["filing_deadline_date"])
    filing["filing_status"] = "FILED"
    filing["filed_date"] = clockcal.fmt_date(filed)
    filing["is_late_filing"] = filed > deadline
    filing["acknowledgment_reference"] = "ACK-%06d" % store.next_seq()
    authz.touch().bump(filing)
    return envelope.ok_object(envelope.VIEWS["filings"](filing))


@bp.get("/pep/plan-filings/<filing_id>")
def read_filing(filing_id):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider", "IndependentAuditor")
    filing = need("filings", filing_id, "ERR_PLAN_FILING_NOT_FOUND")
    authz.own(plan=store.plan_of_filing(filing))
    return envelope.ok_object(envelope.VIEWS["filings"](filing))
