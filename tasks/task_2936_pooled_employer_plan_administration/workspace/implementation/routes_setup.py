"""PRD 3.1 -- provider registration, the plan document and the provider layer."""

from flask import Blueprint, g

import authz
import calc
import clockcal
import envelope
import recompute
import store
import validate
from errors import fail

bp = Blueprint("setup", __name__)

VESTING_SCHEDULES = ("IMMEDIATE", "GRADED_2_6", "CLIFF_3YR")
VESTING_RANK = {"IMMEDIATE": 0, "GRADED_2_6": 1, "CLIFF_3YR": 2}
MATCH_FORMULA_CODES = (
    "SAFE_HARBOR_BASIC",
    "SAFE_HARBOR_ENHANCED",
    "DISCRETIONARY_TIERED",
    "NONE",
)
PROVIDER_TYPES = ("RECORDKEEPER", "TPA", "TRUSTEE", "INVESTMENT_MANAGER", "AUDITOR_FIRM")
FIDUCIARY_ROLES = (
    "NAMED_FIDUCIARY_3_16",
    "INVESTMENT_MANAGER_3_38",
    "TRUSTEE_403A",
    "NON_FIDUCIARY_MINISTERIAL",
)


def need(collection, rid, error_id):
    row = store.get(collection, rid)
    if row is None:
        fail(error_id)
    return row


# ==========================================================================
# PooledPlanProvider
# ==========================================================================


@bp.post("/pep/plan-providers")
def create_provider():
    authz.identify()
    authz.authorize("RegulatorOps")
    b = validate.body()
    legal_name = validate.req_str(b, "legal_name", 1, 200)
    ein = validate.req_digits(b, "ein", 9)
    bond = validate.req_int(b, "fidelity_bond_amount_cents", 0)

    for row in store.all_rows("providers"):
        if row["ein"] == ein:
            fail("ERR_DUPLICATE_PROVIDER_EIN")

    record = store.insert(
        "providers",
        {
            "legal_name": legal_name,
            "ein": ein,
            "fidelity_bond_amount_cents": bond,
            "registration_status": "PENDING_REGISTRATION",
            "registration_number": None,
            "registration_effective_date": None,
            "registered_at": None,
        },
    )
    return envelope.ok_created(envelope.VIEWS["providers"](record))


@bp.post("/pep/plan-providers/<pid>/register")
def register_provider(pid):
    authz.identify()
    authz.authorize("RegulatorOps")
    provider = need("providers", pid, "ERR_PLAN_PROVIDER_NOT_FOUND")
    b = validate.body()
    effective = validate.req_date(b, "registration_effective_date")
    if effective < clockcal.today():
        fail(
            "ERR_VALIDATION",
            "`registration_effective_date` may not be earlier than the logical-clock date.",
        )
    if provider["registration_status"] != "PENDING_REGISTRATION":
        fail("ERR_PROVIDER_NOT_PENDING")
    if provider["fidelity_bond_amount_cents"] < calc.BOND_FLOOR_CENTS:
        fail("ERR_FIDELITY_BOND_BELOW_FLOOR")

    store.DB["_approval_ordinal"] += 1
    provider["registration_status"] = "REGISTERED"
    provider["registration_number"] = "PPP-%04d" % store.DB["_approval_ordinal"]
    provider["registration_effective_date"] = clockcal.fmt_date(effective)
    provider["registered_at"] = clockcal.stamp()
    authz.touch().bump(provider)
    return envelope.ok_object(envelope.VIEWS["providers"](provider))


@bp.get("/pep/plan-providers/<pid>")
def read_provider(pid):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider")
    provider = need("providers", pid, "ERR_PLAN_PROVIDER_NOT_FOUND")
    authz.own_provider(provider)
    return envelope.ok_object(envelope.VIEWS["providers"](provider))


@bp.get("/pep/plan-providers/<pid>/plan-documents")
def list_provider_plans(pid):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider")
    provider = need("providers", pid, "ERR_PLAN_PROVIDER_NOT_FOUND")
    authz.own_provider(provider)
    return envelope.paginate(store.plans_of_provider(provider), envelope.VIEWS["plans"])


# ==========================================================================
# PlanDocument
# ==========================================================================


@bp.post("/pep/plan-documents")
def create_plan():
    authz.identify()
    authz.authorize("PooledPlanProvider")
    b = validate.body()

    # The sponsoring provider foreign key is the ownership subject itself, so
    # it is compared to X-User-ID before it is resolved.
    candidate = validate.fk_candidate(b, "pooled_plan_provider_id")
    if candidate is not None and candidate != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    provider = validate.resolve_fk(
        b, "pooled_plan_provider_id", "providers", "ERR_PLAN_PROVIDER_NOT_FOUND"
    )

    validate.require_fk_shape(b, "pooled_plan_provider_id")
    plan_name = validate.req_str(b, "plan_name", 1, 200)
    plan_number = validate.req_digits(b, "plan_number", 3)
    plan_year_end = validate.req_date(b, "plan_year_end_date")
    min_age = validate.req_int(b, "base_eligibility_min_age", 18, 21)
    months = validate.req_int(b, "base_eligibility_service_months", 0, 12)
    vesting = validate.req_enum(b, "base_vesting_schedule", VESTING_SCHEDULES)
    match_code = validate.req_enum(b, "base_match_formula_code", MATCH_FORMULA_CODES)

    for row in store.plans_of_provider(provider):
        if row["plan_number"] == plan_number:
            fail("ERR_DUPLICATE_PLAN_NUMBER")

    record = {
        "pooled_plan_provider_id": provider["id"],
        "plan_name": plan_name,
        "plan_number": plan_number,
        "plan_year_end_date": clockcal.fmt_date(plan_year_end),
        "status": "DRAFT",
        "effective_date": None,
        "base_eligibility_min_age": min_age,
        "base_eligibility_service_months": months,
        "base_vesting_schedule": vesting,
        "base_match_formula_code": match_code,
    }
    record.update(recompute.new_plan_totals())
    store.insert("plans", record)
    return envelope.ok_created(envelope.VIEWS["plans"](record))


@bp.post("/pep/plan-documents/<plan_id>/activate")
def activate_plan(plan_id):
    authz.identify()
    authz.authorize("PooledPlanProvider")
    plan = need("plans", plan_id, "ERR_PLAN_DOCUMENT_NOT_FOUND")
    authz.own(plan=plan)

    if plan["status"] != "DRAFT":
        fail("ERR_PLAN_ALREADY_ACTIVE")
    provider = store.get("providers", plan["pooled_plan_provider_id"])
    if provider is None or provider["registration_status"] != "REGISTERED":
        fail("ERR_PROVIDER_NOT_REGISTERED")
    if not _acknowledged_role(plan, "NAMED_FIDUCIARY_3_16"):
        fail("ERR_NAMED_FIDUCIARY_NOT_ACKNOWLEDGED")
    if not _acknowledged_role(plan, "TRUSTEE_403A"):
        fail("ERR_TRUSTEE_NOT_ACKNOWLEDGED")

    plan["status"] = "ACTIVE"
    plan["effective_date"] = clockcal.fmt_date(clockcal.today())
    authz.touch().bump(plan)
    return envelope.ok_object(envelope.VIEWS["plans"](plan))


def _acknowledged_role(plan, role):
    for alloc in store.allocations_of_plan(plan):
        if (
            alloc["fiduciary_role"] == role
            and alloc["status"] == "ALLOCATED"
            and alloc["acknowledged_at"] is not None
        ):
            return True
    return False


@bp.get("/pep/plan-documents/<plan_id>")
def read_plan(plan_id):
    authz.identify()
    authz.authorize(*authz.ANY_ROLE)
    plan = need("plans", plan_id, "ERR_PLAN_DOCUMENT_NOT_FOUND")
    authz.own(plan=plan)
    return envelope.ok_object(envelope.VIEWS["plans"](plan))


def _plan_sub_list(plan_id, roles, rows_fn, collection):
    authz.identify()
    authz.authorize(*roles)
    plan = need("plans", plan_id, "ERR_PLAN_DOCUMENT_NOT_FOUND")
    authz.own(plan=plan)
    return envelope.paginate(rows_fn(plan), envelope.VIEWS[collection])


@bp.get("/pep/plan-documents/<plan_id>/service-providers")
def list_plan_service_providers(plan_id):
    return _plan_sub_list(
        plan_id,
        ("RegulatorOps", "PooledPlanProvider", "IndependentAuditor"),
        store.service_providers_of_plan,
        "service_providers",
    )


@bp.get("/pep/plan-documents/<plan_id>/adopting-employers")
def list_plan_employers(plan_id):
    return _plan_sub_list(
        plan_id,
        ("RegulatorOps", "PooledPlanProvider", "IndependentAuditor"),
        store.employers_of_plan,
        "employers",
    )


@bp.get("/pep/plan-documents/<plan_id>/fiduciary-role-allocations")
def list_plan_allocations(plan_id):
    return _plan_sub_list(
        plan_id,
        ("RegulatorOps", "PooledPlanProvider", "ServiceProvider", "IndependentAuditor"),
        store.allocations_of_plan,
        "allocations",
    )


@bp.get("/pep/plan-documents/<plan_id>/compliance-tests")
def list_plan_tests(plan_id):
    return _plan_sub_list(
        plan_id,
        ("RegulatorOps", "PooledPlanProvider", "IndependentAuditor"),
        store.tests_of_plan,
        "tests",
    )


@bp.get("/pep/plan-documents/<plan_id>/plan-filings")
def list_plan_filings(plan_id):
    return _plan_sub_list(
        plan_id,
        ("RegulatorOps", "PooledPlanProvider", "IndependentAuditor"),
        store.filings_of_plan,
        "filings",
    )


@bp.get("/pep/plan-documents/<plan_id>/fee-disclosures")
def list_plan_disclosures(plan_id):
    return _plan_sub_list(
        plan_id,
        ("RegulatorOps", "PooledPlanProvider", "AdoptingEmployer"),
        store.disclosures_of_plan,
        "disclosures",
    )


# ==========================================================================
# ServiceProvider
# ==========================================================================


@bp.post("/pep/service-providers")
def create_service_provider():
    authz.identify()
    authz.authorize("PooledPlanProvider")
    b = validate.body()

    plan = validate.resolve_fk(
        b, "plan_document_id", "plans", "ERR_PLAN_DOCUMENT_NOT_FOUND"
    )
    affiliate = validate.resolve_fk(
        b,
        "affiliated_service_provider_id",
        "service_providers",
        "ERR_SERVICE_PROVIDER_NOT_FOUND",
        required=False,
    )
    authz.own_if(plan=plan)

    validate.require_fk_shape(b, "plan_document_id")
    legal_name = validate.req_str(b, "legal_name", 1, 200)
    provider_type = validate.req_enum(b, "provider_type", PROVIDER_TYPES)
    bps = validate.req_int(b, "revenue_sharing_bps", 0, 500)
    direct_fee = validate.req_int(b, "direct_fee_cents_per_participant", 0)
    if validate.present(b, "affiliated_service_provider_id") and not isinstance(
        b["affiliated_service_provider_id"], str
    ):
        fail("ERR_VALIDATION", "`affiliated_service_provider_id` must be a string.")

    if affiliate is not None and affiliate["plan_document_id"] != plan["id"]:
        fail("ERR_INVALID_AFFILIATION")

    record = store.insert(
        "service_providers",
        {
            "plan_document_id": plan["id"],
            "legal_name": legal_name,
            "provider_type": provider_type,
            "revenue_sharing_bps": bps,
            "direct_fee_cents_per_participant": direct_fee,
            "affiliated_service_provider_id": affiliate["id"] if affiliate else None,
            "holds_fiduciary_role": False,
        },
    )
    return envelope.ok_created(envelope.VIEWS["service_providers"](record))


@bp.get("/pep/service-providers/<sp_id>")
def read_service_provider(sp_id):
    authz.identify()
    authz.authorize(
        "RegulatorOps", "PooledPlanProvider", "ServiceProvider", "IndependentAuditor"
    )
    sp = need("service_providers", sp_id, "ERR_SERVICE_PROVIDER_NOT_FOUND")
    authz.own(plan=store.plan_of_service_provider(sp))
    return envelope.ok_object(envelope.VIEWS["service_providers"](sp))


@bp.get("/pep/service-providers/<sp_id>/affiliates")
def list_service_provider_affiliates(sp_id):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider", "IndependentAuditor")
    sp = need("service_providers", sp_id, "ERR_SERVICE_PROVIDER_NOT_FOUND")
    authz.own(plan=store.plan_of_service_provider(sp))
    rows = store.where("service_providers", affiliated_service_provider_id=sp["id"])
    return envelope.paginate(rows, envelope.VIEWS["service_providers"])


@bp.get("/pep/service-providers/<sp_id>/fiduciary-role-allocations")
def list_service_provider_allocations(sp_id):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider", "ServiceProvider")
    sp = need("service_providers", sp_id, "ERR_SERVICE_PROVIDER_NOT_FOUND")
    authz.own(plan=store.plan_of_service_provider(sp))
    rows = store.where("allocations", service_provider_id=sp["id"])
    return envelope.paginate(rows, envelope.VIEWS["allocations"])


@bp.get("/pep/service-providers/<sp_id>/attested-filings")
def list_service_provider_attested_filings(sp_id):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider", "IndependentAuditor")
    sp = need("service_providers", sp_id, "ERR_SERVICE_PROVIDER_NOT_FOUND")
    authz.own(plan=store.plan_of_service_provider(sp))
    rows = store.where("filings", audit_firm_service_provider_id=sp["id"])
    return envelope.paginate(rows, envelope.VIEWS["filings"])


# ==========================================================================
# FiduciaryRoleAllocation
# ==========================================================================


def _recompute_holds_fiduciary_role(sp, touch):
    if sp is None:
        return
    holds = any(
        a["status"] == "ALLOCATED"
        for a in store.where("allocations", service_provider_id=sp["id"])
    )
    if sp["holds_fiduciary_role"] != holds:
        sp["holds_fiduciary_role"] = holds
        touch.bump(sp)


@bp.post("/pep/fiduciary-role-allocations")
def create_allocation():
    authz.identify()
    authz.authorize("PooledPlanProvider")
    b = validate.body()

    plan = validate.resolve_fk(
        b, "plan_document_id", "plans", "ERR_PLAN_DOCUMENT_NOT_FOUND"
    )
    sp = validate.resolve_fk(
        b, "service_provider_id", "service_providers", "ERR_SERVICE_PROVIDER_NOT_FOUND"
    )
    authz.own_if(plan=plan)

    validate.require_fk_shape(b, "plan_document_id")
    validate.require_fk_shape(b, "service_provider_id")
    role = validate.req_enum(b, "fiduciary_role", FIDUCIARY_ROLES)
    effective_from = validate.req_date(b, "effective_from")
    effective_to = validate.req_date(b, "effective_to")
    expected = validate.req_int(b, "expected_plan_document_version")

    if expected != plan["version"]:
        fail("ERR_STALE_PLAN_VERSION")

    if effective_to < effective_from:
        fail("ERR_INVALID_ALLOCATION_WINDOW")

    incumbents = [
        a
        for a in store.allocations_of_plan(plan)
        if a["fiduciary_role"] == role and a["status"] == "ALLOCATED"
    ]
    for incumbent in incumbents:
        inc_from = clockcal.parse_date(incumbent["effective_from"])
        inc_to = clockcal.parse_date(incumbent["effective_to"])
        # Closed windows: touching at a single day counts as a collision.
        if effective_from <= inc_to and inc_from <= effective_to:
            fail("ERR_ALLOCATION_WINDOW_OVERLAP")

    touch = authz.touch()
    record = store.insert(
        "allocations",
        {
            "plan_document_id": plan["id"],
            "service_provider_id": sp["id"],
            "fiduciary_role": role,
            "effective_from": clockcal.fmt_date(effective_from),
            "effective_to": clockcal.fmt_date(effective_to),
            "status": "ALLOCATED",
            "acknowledged_at": None,
            "acknowledgment_statement": None,
            "revoked_at": None,
            "revoked_reason": None,
        },
    )

    outgoing = []
    for incumbent in incumbents:
        inc_from = clockcal.parse_date(incumbent["effective_from"])
        if effective_from > inc_from:
            incumbent["status"] = "REVOKED"
            incumbent["revoked_at"] = clockcal.stamp()
            incumbent["revoked_reason"] = "SUPERSEDED_BY_NEW_ALLOCATION"
            touch.bump(incumbent)
            outgoing.append(store.get("service_providers", incumbent["service_provider_id"]))

    for firm in outgoing:
        _recompute_holds_fiduciary_role(firm, touch)
    _recompute_holds_fiduciary_role(sp, touch)
    touch.bump(plan)

    return envelope.ok_created(envelope.VIEWS["allocations"](record))


@bp.post("/pep/fiduciary-role-allocations/<alloc_id>/acknowledge")
def acknowledge_allocation(alloc_id):
    authz.identify()
    authz.authorize("ServiceProvider")
    alloc = need("allocations", alloc_id, "ERR_FIDUCIARY_ALLOCATION_NOT_FOUND")
    authz.own(
        plan=store.plan_of_allocation(alloc),
        named_provider_id=alloc["service_provider_id"],
    )
    b = validate.body()
    statement = validate.req_str(b, "acknowledgment_statement", 1, None)

    if alloc["acknowledged_at"] is not None or alloc["status"] == "REVOKED":
        fail("ERR_ALLOCATION_ALREADY_ACKNOWLEDGED")

    alloc["acknowledged_at"] = clockcal.stamp()
    alloc["acknowledgment_statement"] = statement
    authz.touch().bump(alloc)
    return envelope.ok_object(envelope.VIEWS["allocations"](alloc))


@bp.get("/pep/fiduciary-role-allocations/<alloc_id>")
def read_allocation(alloc_id):
    authz.identify()
    authz.authorize("RegulatorOps", "PooledPlanProvider", "ServiceProvider")
    alloc = need("allocations", alloc_id, "ERR_FIDUCIARY_ALLOCATION_NOT_FOUND")
    authz.own(plan=store.plan_of_allocation(alloc))
    return envelope.ok_object(envelope.VIEWS["allocations"](alloc))
