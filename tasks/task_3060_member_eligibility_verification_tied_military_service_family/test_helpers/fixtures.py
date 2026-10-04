"""Composite state builders and the pytest fixtures that expose them.

Every builder drives the public endpoints only: the harness restarts the
server with an empty store before each test, so all state is constructed
from the outside in. The approval pipeline used everywhere is: case ->
service record (direct-service) -> evidence -> submit -> record
reconstruction APPROVE by officer A (verifies the records) -> decide
APPROVE by officer B (a different officer, satisfying segregation of
duties).
"""
import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    OFFICER_A_ID,
    OFFICER_B_ID,
    TEST_USERS,
    make_member_headers,
    make_officer_headers,
)

APPLICANT = TEST_USERS["applicant_headers"]
OFFICER_A = TEST_USERS["officer_a_headers"]
OFFICER_B = TEST_USERS["officer_b_headers"]
OFFICER_C = TEST_USERS["officer_c_headers"]
BENEFITS = TEST_USERS["benefits_officer_headers"]
PRODUCT_ADMIN = TEST_USERS["product_admin_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------- clock
def set_clock(api, to_iso8601):
    return validate_success(api.set_clock(to_iso8601, ADMIN))


def ensure_clock(api, to_iso8601="2026-09-01T00:00:00Z"):
    """Pin the logical clock (idempotent — the default is 2026-09-01)."""
    return set_clock(api, to_iso8601)


# ------------------------------------------------------------- case tier
def build_case(api, **overrides):
    """Open an eligibility case in INTAKE."""
    payload = factories.eligibility_case_payload(**overrides)
    return validate_success(api.create_eligibility_case(payload, APPLICANT), 201)


def add_service_record(api, case_id, **overrides):
    payload = factories.service_record_payload(**overrides)
    return validate_success(api.create_service_record(case_id, payload, APPLICANT), 201)


def add_evidence(api, case_id, content_hash=None, **overrides):
    payload = factories.evidence_payload(content_hash=content_hash, **overrides)
    return validate_success(api.upload_evidence(case_id, payload, APPLICANT), 201)


def submit_case(api, case_id):
    return validate_success(api.submit_case(case_id, APPLICANT))


def reconstruct_case(api, case_id, decision="APPROVE",
                     decision_note="archives matched", officer=OFFICER_A):
    payload = {"decision": decision, "decision_note": decision_note}
    return validate_success(api.record_reconstruction(case_id, payload, officer))


def decide_case(api, case_id, decision="APPROVE", officer=OFFICER_B, **extra):
    payload = factories.decide_payload(decision, **extra)
    return validate_success(api.decide_case(case_id, payload, officer))


# ----------------------------------------------------------- member tier
def approve_direct_member(api, name="Direct Member", dob="1980-01-01",
                          discharge="HONORABLE",
                          start="2000-01-01", end="2006-01-01",
                          still_serving=False, doc_type=None, **case_overrides):
    """Drive a direct-service case all the way to APPROVED.

    Returns (case, member_id). The service record is verified via the
    record-reconstruction path (officer A), then approved by officer B.
    """
    case = build_case(api, applicant_legal_name=name, applicant_dob=dob,
                      basis_type="DIRECT_SERVICE", **case_overrides)
    if still_serving:
        record = add_service_record(
            api, case["id"], branch="ARMY", component="ACTIVE_DUTY",
            service_start_date=start, service_end_date=None,
            discharge_characterization="STILL_SERVING",
        )
    else:
        record = add_service_record(
            api, case["id"], service_start_date=start, service_end_date=end,
            discharge_characterization=discharge,
        )
    evidence_kwargs = {"covers_service_record_id": record["id"]}
    if doc_type is not None:
        evidence_kwargs["doc_type"] = doc_type
    add_evidence(api, case["id"], **evidence_kwargs)
    submit_case(api, case["id"])
    reconstruct_case(api, case["id"])
    decided = decide_case(api, case["id"], "APPROVE")
    return decided, decided["member_id"]


def approve_family_member(api, sponsor_member_id, relationship,
                          name="Family Member", dob="2000-01-01",
                          doc_type=None, decide_officer=OFFICER_B,
                          **case_overrides):
    """Drive a family-derivation case to APPROVED.

    Family cases carry no service record, so no reconstruction is needed;
    approval runs straight from UNDER_REVIEW. Returns (case, member_id).
    """
    evidence_kwargs = {}
    if doc_type is not None:
        evidence_kwargs["doc_type"] = doc_type
    case = build_case(
        api, applicant_legal_name=name, applicant_dob=dob,
        basis_type="FAMILY_DERIVATION", sponsor_member_id=sponsor_member_id,
        claimed_relationship=relationship, **case_overrides,
    )
    add_evidence(api, case["id"], **evidence_kwargs)
    submit_case(api, case["id"])
    decided = decide_case(api, case["id"], "APPROVE", officer=decide_officer)
    return decided, decided["member_id"]


def get_member(api, member_id):
    return validate_success(api.get_member(member_id, OFFICER_A))


def member_version(api, member_id):
    return get_member(api, member_id)["version"]


# ----------------------------------------------------------- product tier
def build_offering(api, categories=None, product_line="BANKING", **overrides):
    payload = factories.product_offering_payload(
        product_line=product_line, **overrides
    )
    if categories is not None:
        payload["allowed_categories"] = list(categories)
    return validate_success(api.create_product_offering(payload, PRODUCT_ADMIN), 201)


def open_entitlement(api, member_id, offering_id, exposure_cents=None, **overrides):
    payload = factories.entitlement_payload(offering_id, **overrides)
    if exposure_cents is not None:
        payload["exposure_cents"] = exposure_cents
    return validate_success(
        api.create_entitlement(member_id, payload, make_member_headers(member_id)), 201
    )


# ---------------------------------------------------------- household tier
def build_household(api, primary_member_id, **overrides):
    payload = factories.household_payload(primary_member_id, **overrides)
    return validate_success(
        api.create_household(payload, make_member_headers(primary_member_id)), 201
    )


# --------------------------------------------------------- deployment tier
def register_order(api, member_id, expected_member_version=None, **overrides):
    """Register a deployment order with a fresh OCC version when not given."""
    if expected_member_version is None:
        expected_member_version = member_version(api, member_id)
    payload = factories.deployment_order_payload(expected_member_version, **overrides)
    return validate_success(
        api.create_deployment_order(member_id, payload, OFFICER_A), 201
    )


# ------------------------------------------------------------- claim tier
def file_rate_claim(api, member_id, deployment_order_id, base_rate_bps,
                    monthly_interest_cents, obligation_label=None):
    overrides = {
        "claim_type": "RATE_REDUCTION",
        "deployment_order_id": deployment_order_id,
        "base_rate_bps": base_rate_bps,
        "monthly_interest_cents": monthly_interest_cents,
    }
    if obligation_label is not None:
        overrides["obligation_label"] = obligation_label
    payload = factories.protection_claim_payload(**overrides)
    return validate_success(
        api.create_protection_claim(
            member_id, payload, make_member_headers(member_id)
        ),
        201,
    )


def decide_claim(api, claim_id, decision="APPROVE", officer=OFFICER_A):
    return validate_success(
        api.decide_protection_claim(claim_id, {"decision": decision}, officer)
    )


# ------------------------------------------------------- composite bundles
def setup_active_member_with_deployment(
    api, start_date="2026-09-01", end_date="2027-03-01", scra_eligible=True,
    name="Deployed Member", clock="2026-09-01T00:00:00Z",
):
    """An ACTIVE direct-service member plus one deployment order.

    Returns (member_id, order). When start_date <= the clock date the order
    auto-activates to ACTIVE and flips the member posture to DEPLOYED.
    """
    ensure_clock(api, clock)
    _, member_id = approve_direct_member(api, name=name, still_serving=True)
    order = register_order(
        api, member_id, start_date=start_date, end_date=end_date,
        scra_eligible=scra_eligible,
    )
    return member_id, order


def setup_member_spouse_survivor_case(
    api, sponsor_name="Deceased Sponsor", spouse_name="Surviving Spouse",
    exposure_cents=None, offering_categories=None, clock="2026-09-01T00:00:00Z",
):
    """Sponsor + spouse members; sponsor deceased with a survivor case OPEN
    naming the spouse. Returns a dict of the moving parts. The offering (when
    requested) is created but no entitlement is opened — callers control
    exposure composition themselves."""
    ensure_clock(api, clock)
    case, sponsor_id = approve_direct_member(api, name=sponsor_name)
    _, spouse_id = approve_family_member(
        api, sponsor_id, "SPOUSE", name=spouse_name,
        doc_type="MARRIAGE_CERTIFICATE",
    )
    bundle = {"sponsor_id": sponsor_id, "spouse_id": spouse_id,
              "sponsor_case": case}
    if exposure_cents is not None:
        offering = build_offering(
            api, categories=offering_categories or [
                "VETERAN_HONORABLE", "FAMILY_SPOUSE", "FAMILY_CHILD",
            ],
            product_line="INSURANCE",
        )
        bundle["offering"] = offering
    validate_success(
        api.mark_deceased(sponsor_id, {"beneficiary_member_id": spouse_id}, BENEFITS)
    )
    cases = validate_success(
        api.list_member_survivor_cases(sponsor_id, BENEFITS)
    )
    bundle["survivor_case"] = cases[0]
    return bundle


# ------------------------------------------------------------ pytest glue
@pytest.fixture
def api():
    """Session client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def direct_member(api):
    """One approved direct-service (VETERAN_HONORABLE) member."""
    _, member_id = approve_direct_member(api, name="Fixture Veteran")
    return get_member(api, member_id)


@pytest.fixture
def active_duty_member(api):
    """One approved still-serving (ENLISTED_ACTIVE) member."""
    _, member_id = approve_direct_member(
        api, name="Fixture Active Duty", still_serving=True
    )
    return get_member(api, member_id)
