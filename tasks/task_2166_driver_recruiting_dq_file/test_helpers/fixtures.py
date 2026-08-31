"""Composite setup helpers.

Every test runs against a freshly restarted server, so each helper builds its
preconditions from scratch through PRD-declared endpoints only.  Setup calls use
the lenient validator so a broken precondition surfaces as "Setup step failed"
rather than as a confusing assertion inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_UTC
from .factories import (
    create_carrier_payload,
    create_clearinghouse_query_payload,
    create_driver_applicant_payload,
    create_driver_application_payload,
    create_drug_test_order_payload,
    create_employment_verification_payload,
    create_orientation_enrollment_payload,
    create_orientation_session_payload,
    create_road_test_payload,
    create_screening_check_payload,
    create_tuition_agreement_payload,
    record_screening_result_payload,
    record_verification_response_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_compliance_auditor_headers,
    make_recruiter_headers,
    make_safety_director_headers,
)

RECRUITER = TEST_USERS["recruiter_headers"]
DER = TEST_USERS["der_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
SCHOOL = TEST_USERS["school_coordinator_headers"]

DEFAULT_RECRUITER_ID = "rec-001"
DEFAULT_EXAMINER_ID = "exam-501"

#: The two adjacent segments that together blanket the whole 1,095-day window
#: when the logical clock sits at its startup instant.
FULL_EMPLOYMENT_HISTORY = [
    ("Blue Line Cartage", "2022-01-01", "2024-09-01"),
    ("Northgate Haul", "2024-09-01", "2026-08-01"),
]

#: Only the recent segment — leaves a 396-day unexplained gap.
PARTIAL_EMPLOYMENT_HISTORY = [
    ("Northgate Haul", "2024-09-01", "2026-08-01"),
]

DEFAULT_MEDICAL_CERT = {
    "status": "PRESENT",
    "effective_on": "2026-07-15",
    "expires_on": "2026-10-01",
    "source_ref": "NRCME-889201",
}

DEFAULT_CDL_COPY = {"status": "PRESENT", "effective_on": "2026-08-01"}


# ─── Tier 0: primitives ───────────────────────────────────────────────────────

def set_clock(to_iso8601: str, headers=None) -> str:
    """Advance the logical clock and return the resulting current_utc."""
    data = get_success_data(api_client.set_clock(to_iso8601, headers or RECRUITER))
    return data["current_utc"]


def read_clock(headers=None) -> str:
    return get_success_data(api_client.get_clock(headers or RECRUITER))["current_utc"]


def create_carrier(**overrides) -> dict:
    payload = create_carrier_payload(**overrides)
    return get_success_data(api_client.create_carrier(payload, SAFETY_DIRECTOR))


def create_applicant(carrier_id: str, **overrides) -> dict:
    payload = create_driver_applicant_payload(carrier_id, **overrides)
    return get_success_data(api_client.create_driver_applicant(payload, RECRUITER))


def create_application(applicant_id: str, **overrides) -> dict:
    payload = create_driver_application_payload(applicant_id, **overrides)
    return get_success_data(api_client.create_driver_application(payload, RECRUITER))


def submit_application(application_id: str, recruiter_user_id: str = DEFAULT_RECRUITER_ID) -> dict:
    return get_success_data(
        api_client.submit_application(application_id, make_recruiter_headers(recruiter_user_id))
    )


def fetch_carrier(carrier_id: str) -> dict:
    return get_success_data(api_client.get_carrier(carrier_id, SAFETY_DIRECTOR))


def carrier_version(carrier_id: str) -> int:
    return fetch_carrier(carrier_id)["version"]


def fetch_applicant(applicant_id: str) -> dict:
    return get_success_data(api_client.get_driver_applicant(applicant_id, RECRUITER))


def fetch_application(application_id: str) -> dict:
    return get_success_data(api_client.get_driver_application(application_id, RECRUITER))


def fetch_dq_file_for_application(application_id: str) -> dict:
    rows = get_success_data(
        api_client.list_dq_files(RECRUITER, params={"application_id": application_id})
    )
    assert rows, f"Setup step failed: no qualification file for application {application_id}"
    return rows[0]


def fetch_dq_file(dq_file_id: str) -> dict:
    return get_success_data(api_client.get_dq_file(dq_file_id, RECRUITER))


def dq_file_version(dq_file_id: str) -> int:
    return fetch_dq_file(dq_file_id)["version"]


def fetch_dq_document(dq_file_id: str, doc_type: str) -> dict:
    rows = get_success_data(
        api_client.list_dq_documents(
            RECRUITER, params={"dq_file_id": dq_file_id, "doc_type": doc_type}
        )
    )
    assert rows, f"Setup step failed: no {doc_type} document on file {dq_file_id}"
    return rows[0]


def list_all_dq_documents(dq_file_id: str):
    return get_success_data(
        api_client.list_dq_documents(RECRUITER, params={"dq_file_id": dq_file_id, "limit": 100})
    )


def file_dq_document(dq_file_id: str, doc_type: str, status: str, **fields) -> dict:
    """File or waive one artifact, always carrying the file's live version."""
    document = fetch_dq_document(dq_file_id, doc_type)
    payload = {"status": status, "expected_dq_file_version": dq_file_version(dq_file_id)}
    payload.update(fields)
    return get_success_data(api_client.update_dq_document(document["id"], payload, RECRUITER))


# ─── Tier 1: state progression on a single application ────────────────────────

def setup_submitted_application(
    carrier_overrides=None,
    applicant_overrides=None,
    position_type: str = "OTR",
    recruiter_user_id: str = DEFAULT_RECRUITER_ID,
) -> dict:
    """Carrier + applicant + application driven through DRAFT -> SUBMITTED.

    Returns a context dict carrying the carrier, applicant, application and the
    qualification file that submission minted.
    """
    carrier = create_carrier(**(carrier_overrides or {}))
    applicant = create_applicant(carrier["id"], **(applicant_overrides or {}))
    application = create_application(applicant["id"], position_type=position_type)
    application = submit_application(application["id"], recruiter_user_id)
    dq_file = fetch_dq_file_for_application(application["id"])
    return {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "applicant": applicant,
        "applicant_id": applicant["id"],
        "application": application,
        "application_id": application["id"],
        "dq_file": dq_file,
        "dq_file_id": dq_file["id"],
        "recruiter_user_id": recruiter_user_id,
    }


def setup_draft_application(carrier_overrides=None, applicant_overrides=None,
                            position_type: str = "OTR") -> dict:
    """Carrier + applicant + a DRAFT application that has not been submitted."""
    carrier = create_carrier(**(carrier_overrides or {}))
    applicant = create_applicant(carrier["id"], **(applicant_overrides or {}))
    application = create_application(applicant["id"], position_type=position_type)
    return {
        "carrier": carrier,
        "carrier_id": carrier["id"],
        "applicant": applicant,
        "applicant_id": applicant["id"],
        "application": application,
        "application_id": application["id"],
    }


def add_second_applicant(carrier_id: str, index: int = 2, **overrides) -> dict:
    """A sibling applicant at the same carrier, with distinct unique fields."""
    defaults = {
        "full_name": f"Bo Lund {index}",
        "email": f"bo.lund.{index}@example.com",
        "cdl_number": f"CDL-1100{index}",
    }
    defaults.update(overrides)
    return create_applicant(carrier_id, **defaults)


# ─── Tier 2: the pipelines that feed the qualification file ───────────────────

def record_employment_segment(
    application_id: str,
    employer_name: str,
    employed_from: str,
    employed_to: str,
    is_dot_regulated: bool = True,
) -> dict:
    payload = create_employment_verification_payload(
        application_id,
        employer_name=employer_name,
        employed_from=employed_from,
        employed_to=employed_to,
        is_dot_regulated=is_dot_regulated,
    )
    return get_success_data(api_client.create_employment_verification(payload, RECRUITER))


def request_and_verify_segment(verification_id: str, **response_overrides) -> dict:
    get_success_data(api_client.send_verification_request(verification_id, RECRUITER))
    payload = record_verification_response_payload(**response_overrides)
    return get_success_data(
        api_client.record_verification_response(verification_id, payload, RECRUITER)
    )


def add_verified_employment_history(application_id: str, segments=None):
    """Record each segment and drive it to RESPONDED_VERIFIED. Returns the rows."""
    verifications = []
    for employer_name, employed_from, employed_to in (segments or FULL_EMPLOYMENT_HISTORY):
        row = record_employment_segment(
            application_id, employer_name, employed_from, employed_to
        )
        verifications.append(request_and_verify_segment(row["id"]))
    return verifications


def drive_segment_to_good_faith(verification_id: str, clock_stops):
    """Three documented request rounds, each followed by a 14-day clock advance."""
    for index, instant in enumerate(clock_stops):
        get_success_data(api_client.send_verification_request(verification_id, RECRUITER))
        set_clock(instant)
        if index < len(clock_stops) - 1:
            get_success_data(api_client.mark_verification_no_response(verification_id, RECRUITER))
    return get_success_data(api_client.mark_verification_no_response(verification_id, RECRUITER))


def order_screening_check(application_id: str, check_type: str) -> dict:
    payload = create_screening_check_payload(application_id, check_type)
    return get_success_data(api_client.create_screening_check(payload, RECRUITER))


def record_screening_check_result(screening_check_id: str, **overrides) -> dict:
    payload = record_screening_result_payload(**overrides)
    return get_success_data(
        api_client.record_screening_result(screening_check_id, payload, RECRUITER)
    )


def adjudicate(screening_check_id: str, decision: str, headers=None) -> dict:
    return get_success_data(
        api_client.adjudicate_screening_check(
            screening_check_id, {"decision": decision}, headers or SAFETY_DIRECTOR
        )
    )


def pass_screening_check(application_id: str, check_type: str, **result_overrides) -> dict:
    check = order_screening_check(application_id, check_type)
    record_screening_check_result(check["id"], **result_overrides)
    return adjudicate(check["id"], "PASS")


def pass_all_screening_checks(application_id: str, issued_on: str = "2026-07-01") -> dict:
    """Order, record and PASS one MVR, one PSP and one CRIMINAL report."""
    return {
        check_type: pass_screening_check(application_id, check_type, issued_on=issued_on)
        for check_type in ("MVR", "PSP", "CRIMINAL")
    }


def open_clearinghouse_query(application_id: str, query_type: str = "FULL") -> dict:
    payload = create_clearinghouse_query_payload(application_id, query_type)
    return get_success_data(api_client.create_clearinghouse_query(payload, DER))


def grant_consent(clearinghouse_query_id: str, applicant_id: str) -> dict:
    return get_success_data(
        api_client.consent_decision(
            clearinghouse_query_id, {"decision": "GRANT"}, make_applicant_headers(applicant_id)
        )
    )


def record_clearinghouse_result(clearinghouse_query_id: str, result: str) -> dict:
    return get_success_data(
        api_client.record_clearinghouse_result(clearinghouse_query_id, {"result": result}, DER)
    )


def clear_clearinghouse(application_id: str, applicant_id: str, query_type: str = "FULL") -> dict:
    """Open a query, take the driver's consent and record a NO_INFO result."""
    query = open_clearinghouse_query(application_id, query_type)
    grant_consent(query["id"], applicant_id)
    return record_clearinghouse_result(query["id"], "NO_INFO")


def order_drug_test(application_id: str, test_type: str = "PRE_EMPLOYMENT") -> dict:
    payload = create_drug_test_order_payload(application_id, test_type)
    return get_success_data(api_client.create_drug_test_order(payload, DER))


def collect_specimen(drug_test_order_id: str, collected_at: str = "2026-08-01T09:00:00Z") -> dict:
    return get_success_data(
        api_client.record_collection(drug_test_order_id, {"collected_at": collected_at}, DER)
    )


def record_lab_result(drug_test_order_id: str, lab_result: str) -> dict:
    return get_success_data(
        api_client.record_lab_result(drug_test_order_id, {"lab_result": lab_result}, DER)
    )


def record_mro_verification(drug_test_order_id: str, mro_decision: str) -> dict:
    return get_success_data(
        api_client.record_mro_verification(
            drug_test_order_id, {"mro_decision": mro_decision}, DER
        )
    )


def complete_negative_drug_test(
    application_id: str,
    test_type: str = "PRE_EMPLOYMENT",
    collected_at: str = "2026-08-01T09:00:00Z",
) -> dict:
    """Order -> collect -> LAB_NEGATIVE -> MRO_VERIFIED_NEGATIVE."""
    order = order_drug_test(application_id, test_type)
    collect_specimen(order["id"], collected_at)
    record_lab_result(order["id"], "NEGATIVE")
    return record_mro_verification(order["id"], "VERIFIED_NEGATIVE")


def book_road_test(
    application_id: str,
    examiner_user_id: str = DEFAULT_EXAMINER_ID,
    scheduled_at: str = "2026-08-05T14:00:00Z",
    vehicle_class: str = "CLASS_A",
) -> dict:
    payload = create_road_test_payload(
        application_id,
        examiner_user_id=examiner_user_id,
        scheduled_at=scheduled_at,
        vehicle_class=vehicle_class,
    )
    return get_success_data(api_client.create_road_test(payload, RECRUITER))


def record_road_test(road_test_id: str, examiner_user_id: str, **payload_overrides) -> dict:
    payload = {"outcome": "PASSED", "score_pretrip": 90, "score_skills": 86, "score_road": 78}
    payload.update(payload_overrides)
    if payload["outcome"] == "NO_SHOW":
        for score_field in ("score_pretrip", "score_skills", "score_road"):
            payload.pop(score_field, None)
    return get_success_data(
        api_client.record_road_test_result(
            road_test_id, payload, make_safety_director_headers(examiner_user_id)
        )
    )


def pass_road_test(
    application_id: str,
    examiner_user_id: str = DEFAULT_EXAMINER_ID,
    scheduled_at: str = "2026-08-05T14:00:00Z",
    score_pretrip: int = 90,
    score_skills: int = 86,
    score_road: int = 78,
) -> dict:
    road_test = book_road_test(application_id, examiner_user_id, scheduled_at)
    return record_road_test(
        road_test["id"],
        examiner_user_id,
        outcome="PASSED",
        score_pretrip=score_pretrip,
        score_skills=score_skills,
        score_road=score_road,
    )


def create_open_session(carrier_id: str, **overrides) -> dict:
    """Create a class and move it PLANNED -> OPEN. Returns the opened session."""
    payload = create_orientation_session_payload(carrier_id, **overrides)
    session = get_success_data(api_client.create_orientation_session(payload, RECRUITER))
    return get_success_data(api_client.open_orientation_session(session["id"], RECRUITER))


def reserve_seat(session_id: str, application_id: str, expected_session_version: int = None) -> dict:
    if expected_session_version is None:
        expected_session_version = get_success_data(
            api_client.get_orientation_session(session_id, RECRUITER)
        )["version"]
    payload = create_orientation_enrollment_payload(
        session_id, application_id, expected_session_version
    )
    return get_success_data(api_client.create_orientation_enrollment(payload, RECRUITER))


def complete_session(session_id: str, attended_enrollment_ids) -> dict:
    return get_success_data(
        api_client.complete_orientation_session(
            session_id, {"attended_enrollment_ids": list(attended_enrollment_ids)}, RECRUITER
        )
    )


# ─── Tier 3: full lifecycle shortcuts ─────────────────────────────────────────

def setup_road_test_passed_application(
    carrier_overrides=None,
    applicant_overrides=None,
    examiner_user_id: str = DEFAULT_EXAMINER_ID,
    recruiter_user_id: str = DEFAULT_RECRUITER_ID,
    **road_test_scores,
) -> dict:
    """Submitted application + verified-negative specimen + a PASSED road test."""
    ctx = setup_submitted_application(
        carrier_overrides=carrier_overrides,
        applicant_overrides=applicant_overrides,
        recruiter_user_id=recruiter_user_id,
    )
    ctx["drug_test"] = complete_negative_drug_test(ctx["application_id"])
    ctx["road_test"] = pass_road_test(
        ctx["application_id"], examiner_user_id=examiner_user_id, **road_test_scores
    )
    ctx["examiner_user_id"] = examiner_user_id
    ctx["application"] = fetch_application(ctx["application_id"])
    return ctx


def setup_qualified_application(
    carrier_overrides=None,
    applicant_overrides=None,
    recruiter_user_id: str = DEFAULT_RECRUITER_ID,
    examiner_user_id: str = DEFAULT_EXAMINER_ID,
    employment_segments=None,
    waive_employment_document: bool = False,
    cdl_copy=DEFAULT_CDL_COPY,
    medical_cert=DEFAULT_MEDICAL_CERT,
    clearinghouse_query_type: str = "FULL",
    session_overrides=None,
    clock_at_completion: str = "2026-08-12T22:00:00Z",
    complete_orientation: bool = True,
) -> dict:
    """Drive one application all the way to QUALIFIED with a COMPLETE file.

    The chain is: submit -> employment history -> three PASSED screening checks
    -> a cleared Clearinghouse query -> a verified-negative specimen -> the two
    hand-filed artifacts -> a PASSED road test -> an attended orientation class.
    """
    ctx = setup_submitted_application(
        carrier_overrides=carrier_overrides,
        applicant_overrides=applicant_overrides,
        recruiter_user_id=recruiter_user_id,
    )
    application_id = ctx["application_id"]

    ctx["verifications"] = add_verified_employment_history(application_id, employment_segments)
    ctx["screening_checks"] = pass_all_screening_checks(application_id)
    ctx["clearinghouse_query"] = clear_clearinghouse(
        application_id, ctx["applicant_id"], clearinghouse_query_type
    )
    ctx["drug_test"] = complete_negative_drug_test(application_id)

    dq_file_id = ctx["dq_file_id"]
    if cdl_copy:
        ctx["cdl_copy_document"] = file_dq_document(dq_file_id, "CDL_COPY", **cdl_copy)
    if medical_cert:
        ctx["medical_cert_document"] = file_dq_document(dq_file_id, "MEDICAL_CERT", **medical_cert)
    if waive_employment_document:
        ctx["employment_document"] = file_dq_document(
            dq_file_id, "EMPLOYMENT_VERIFICATION", status="WAIVED", effective_on="2026-08-01"
        )

    ctx["road_test"] = pass_road_test(application_id, examiner_user_id=examiner_user_id)
    ctx["examiner_user_id"] = examiner_user_id

    session = create_open_session(ctx["carrier_id"], **(session_overrides or {}))
    ctx["session"] = session
    ctx["session_id"] = session["id"]
    ctx["session_version_after_open"] = session["version"]
    enrollment = reserve_seat(session["id"], application_id, session["version"])
    ctx["enrollment"] = enrollment
    ctx["enrollment_id"] = enrollment["id"]

    if complete_orientation:
        set_clock(clock_at_completion)
        ctx["session"] = complete_session(session["id"], [enrollment["id"]])

    ctx["application"] = fetch_application(application_id)
    ctx["dq_file"] = fetch_dq_file(dq_file_id)
    return ctx


def hire_from_context(ctx: dict, hired_on: str = "2026-08-13") -> dict:
    """Consume a funded seat for the context's application."""
    payload = {
        "application_id": ctx["application_id"],
        "hired_on": hired_on,
        "expected_carrier_version": carrier_version(ctx["carrier_id"]),
    }
    hire = get_success_data(api_client.create_hire_record(payload, SAFETY_DIRECTOR))
    ctx["hire"] = hire
    ctx["hire_id"] = hire["id"]
    return hire


def setup_hired_applicant(hired_on: str = "2026-08-13", **qualify_options) -> dict:
    """A QUALIFIED application driven through POST /hire-records."""
    ctx = setup_qualified_application(**qualify_options)
    hire_from_context(ctx, hired_on)
    ctx["application"] = fetch_application(ctx["application_id"])
    ctx["carrier"] = fetch_carrier(ctx["carrier_id"])
    return ctx


def terminate_hire(hire_id: str, **overrides) -> dict:
    payload = {
        "terminated_on": "2026-08-20",
        "termination_type": "VOLUNTARY",
        "rehire_flag": "ELIGIBLE",
    }
    payload.update(overrides)
    return get_success_data(
        api_client.terminate_hire_record(hire_id, payload, SAFETY_DIRECTOR)
    )


# ─── Tier 4: the tuition ledger ───────────────────────────────────────────────

def create_tuition_agreement(applicant_id: str, **overrides) -> dict:
    payload = create_tuition_agreement_payload(applicant_id, **overrides)
    return get_success_data(api_client.create_tuition_agreement(payload, SCHOOL))


def activate_tuition_agreement(tuition_agreement_id: str) -> dict:
    return get_success_data(api_client.activate_tuition_agreement(tuition_agreement_id, SCHOOL))


def accrue_months(tuition_agreement_id: str, service_months) -> dict:
    agreement = None
    for service_month in service_months:
        agreement = get_success_data(
            api_client.accrue_month(
                tuition_agreement_id, {"service_month": service_month}, SCHOOL
            )
        )
    return agreement


def setup_active_tuition_agreement(
    tuition_total_cents: int = 115205,
    commitment_months: int = 12,
    service_months=(),
    hired_on: str = "2026-08-13",
    **qualify_options,
) -> dict:
    """A hired driver holding an ACTIVE agreement with `service_months` accrued."""
    ctx = setup_hired_applicant(hired_on=hired_on, **qualify_options)
    agreement = create_tuition_agreement(
        ctx["applicant_id"],
        tuition_total_cents=tuition_total_cents,
        commitment_months=commitment_months,
    )
    agreement = activate_tuition_agreement(agreement["id"])
    if service_months:
        agreement = accrue_months(agreement["id"], service_months)
    ctx["tuition_agreement"] = agreement
    ctx["tuition_agreement_id"] = agreement["id"]
    return ctx


# ─── Tier 5: annual-review readiness ──────────────────────────────────────────

def setup_file_due_for_annual_review(
    review_clock: str = "2027-09-01T00:00:00Z",
    mvr_issued_on: str = "2027-08-15",
    recruiter_user_id: str = DEFAULT_RECRUITER_ID,
    carrier_overrides=None,
) -> dict:
    """A submitted application whose file is OVERDUE and carries a current MVR."""
    ctx = setup_submitted_application(
        carrier_overrides=carrier_overrides, recruiter_user_id=recruiter_user_id
    )
    set_clock(review_clock)
    ctx["mvr_check"] = pass_screening_check(
        ctx["application_id"], "MVR", issued_on=mvr_issued_on
    )
    ctx["dq_file"] = fetch_dq_file(ctx["dq_file_id"])
    return ctx


def certify_annual_review(dq_file_id: str, auditor_user_id: str = "aud-900",
                          certification_note: str = "FY2027 review") -> dict:
    return get_success_data(
        api_client.annual_review(
            dq_file_id,
            {"certification_note": certification_note},
            make_compliance_auditor_headers(auditor_user_id),
        )
    )


def revoke_annual_review(dq_file_id: str, auditor_user_id: str = "aud-900",
                         reason: str = "AUDITOR_ERROR") -> dict:
    return get_success_data(
        api_client.revoke_certification(
            dq_file_id, {"reason": reason}, make_compliance_auditor_headers(auditor_user_id)
        )
    )


def completeness(dq_file_id: str, variant: str = None) -> dict:
    params = {"variant": variant} if variant else None
    return get_success_data(
        api_client.get_dq_file_completeness(dq_file_id, AUDITOR, params=params)
    )


def coverage(application_id: str, variant: str = None) -> dict:
    params = {"variant": variant} if variant else None
    return get_success_data(
        api_client.get_employment_coverage(application_id, AUDITOR, params=params)
    )


__all__ = [name for name in dir() if not name.startswith("_")]
