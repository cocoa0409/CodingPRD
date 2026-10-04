"""Composite setup helpers: multi-step state builders shared by many tests.

Every helper builds preconditions from scratch through the public API and uses
the lenient get_success_data validator, so a setup failure surfaces as a clear
error at the failing step. Ownership-gated calls always thread the real
ApplicantCompany id into X-User-ID via make_applicant_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_applicant_headers, make_innovator_headers
from .factories import (
    applicant_payload, reference_product_payload, listed_patent_payload,
    protected_indication_payload, application_payload, be_study_payload,
    certification_payload, amendment_payload, facility_payload, inspection_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["regulatory_reviewer_headers"]
INSPECTOR = TEST_USERS["facility_inspector_headers"]


def set_clock(to_iso8601: str) -> None:
    """Advance the logical clock (forward-only) as ProgramAdmin."""
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def make_applicant(**overrides) -> dict:
    return get_success_data(api_client.create_applicant_company(applicant_payload(**overrides), ADMIN))


def make_reference_product(**overrides) -> dict:
    return get_success_data(api_client.create_reference_product(reference_product_payload(**overrides), ADMIN))


def make_listed_patent(rld, **overrides) -> dict:
    headers = make_innovator_headers(rld["patent_owner_user_id"])
    return get_success_data(api_client.create_listed_patent(rld["id"], listed_patent_payload(**overrides), headers))


def make_protected_indication(rld_id, **overrides) -> dict:
    return get_success_data(api_client.create_protected_indication(rld_id, protected_indication_payload(**overrides), ADMIN))


def make_application(rld_id, applicant_id, **overrides) -> dict:
    headers = make_applicant_headers(applicant_id)
    return get_success_data(api_client.create_application(application_payload(rld_id, applicant_id, **overrides), headers))


def get_application(app_id) -> dict:
    return get_success_data(api_client.get_application(app_id, ADMIN))


def add_be_study(app_id, applicant_id, **overrides) -> dict:
    headers = make_applicant_headers(applicant_id)
    return get_success_data(api_client.create_be_study(app_id, be_study_payload(**overrides), headers))


def add_certification(app_id, applicant_id, patent_id, certification_type="PARAGRAPH_IV_CHALLENGE") -> dict:
    """File a certification, refreshing the OCC token from a live read first."""
    headers = make_applicant_headers(applicant_id)
    version = get_application(app_id)["version"]
    payload = certification_payload(patent_id, version, certification_type=certification_type)
    return get_success_data(api_client.create_patent_certification(app_id, payload, headers))


def add_amendment(app_id, applicant_id, classification="MINOR", contains_new_be_data=False, notes=None) -> dict:
    headers = make_applicant_headers(applicant_id)
    version = get_application(app_id)["version"]
    payload = amendment_payload(version, classification=classification,
                                contains_new_be_data=contains_new_be_data)
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.create_amendment(app_id, payload, headers))


def make_facility(applicant_id, **overrides) -> dict:
    headers = make_applicant_headers(applicant_id)
    return get_success_data(api_client.create_facility(facility_payload(applicant_id, **overrides), headers))


def schedule_inspection(facility_id, application_id, **overrides) -> dict:
    return get_success_data(api_client.create_inspection(inspection_payload(facility_id, application_id, **overrides), REVIEWER))


def record_outcome(inspection_id, outcome) -> dict:
    return get_success_data(api_client.record_inspection_outcome(inspection_id, {"outcome": outcome}, INSPECTOR))


def schedule_and_pass_inspection(facility_id, application_id, **overrides) -> dict:
    insp = schedule_inspection(facility_id, application_id, **overrides)
    return record_outcome(insp["id"], "PASSED")


def submit_application(app_id, applicant_id) -> dict:
    return get_success_data(api_client.submit_application(app_id, make_applicant_headers(applicant_id)))


def approve_application(app_id) -> dict:
    return get_success_data(api_client.approval_decision(app_id, {"decision": "APPROVE"}, REVIEWER))


def send_notice(cert_id, applicant_id) -> dict:
    return get_success_data(api_client.create_notice(cert_id, make_applicant_headers(applicant_id)))


def list_cycles(app_id) -> list:
    return get_success_data(api_client.list_review_cycles(app_id, REVIEWER))


def list_awards(**params) -> list:
    return get_success_data(api_client.list_exclusivity_awards(REVIEWER, params=params))


def setup_submitted(priority="STANDARD", rld_overrides=None, app_overrides=None,
                    with_facility=False, patent_expiry=None, cert_type=None) -> dict:
    """Applicant + reference product + application with one ACCEPTED BE study,
    optionally a listed patent + certification and a PASSED domestic inspection;
    ends with the application submitted (RECEIVED). Returns a context dict."""
    applicant = make_applicant()
    rld = make_reference_product(**(rld_overrides or {}))
    app = make_application(rld["id"], applicant["id"], review_priority=priority,
                           **(app_overrides or {}))
    ctx = {"applicant": applicant, "rld": rld, "app": app}
    ctx["study"] = add_be_study(app["id"], applicant["id"])
    if patent_expiry is not None:
        ctx["patent"] = make_listed_patent(rld, expiry_date=patent_expiry)
        ctx["cert"] = add_certification(app["id"], applicant["id"], ctx["patent"]["id"],
                                        cert_type or "PARAGRAPH_IV_CHALLENGE")
    if with_facility:
        ctx["facility"] = make_facility(applicant["id"])
        ctx["inspection"] = schedule_and_pass_inspection(ctx["facility"]["id"], app["id"])
    ctx["app"] = submit_application(app["id"], applicant["id"])
    return ctx


def setup_approved(**kwargs) -> dict:
    """Submitted application with a PASSED domestic inspection, approved at the
    default clock with no patent block. Returns a context dict."""
    kwargs["with_facility"] = True
    ctx = setup_submitted(**kwargs)
    ctx["app"] = approve_application(ctx["app"]["id"])
    return ctx


def setup_tentative_p3(patent_expiry="2027-02-01") -> dict:
    """P3-defer application driven to TENTATIVE_APPROVAL at the default clock
    (patent expiry still in the future blocks full approval)."""
    ctx = setup_submitted(with_facility=True, patent_expiry=patent_expiry,
                          cert_type="PARAGRAPH_III_DEFER")
    ctx["app"] = approve_application(ctx["app"]["id"])
    return ctx
