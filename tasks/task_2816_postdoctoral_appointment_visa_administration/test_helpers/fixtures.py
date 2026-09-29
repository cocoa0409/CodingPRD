"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only declared operations. Setup calls use the
lenient validator so a broken precondition reports as a setup failure rather
than as a confusing assertion error.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_LOGICAL_CLOCK, TEST_DEFAULTS
from .factories import (
    accept_offer_payload,
    adjudication_payload,
    create_appointment_payload,
    create_faculty_mentor_payload,
    create_funding_source_payload,
    create_grievance_payload,
    create_lab_access_grant_payload,
    create_laboratory_payload,
    create_postdoc_payload,
    finalize_payload,
    grievance_resolution_payload,
    initiate_exit_payload,
    ip_assignment_payload,
    recommendation_payload,
    review_document_payload,
    screening_decision_payload,
    submit_document_payload,
    submit_petition_payload,
    verification_payload,
)
from .test_users import (
    EXPORT_REVIEWER_USER_ID,
    HR_APPROVER_USER_ID,
    OFFICER_ALT_USER_ID,
    OFFICER_USER_ID,
    SCHOLAR_ADVISOR_USER_ID,
    TEST_USERS,
    make_export_reviewer_headers,
    make_faculty_mentor_headers,
    make_hr_approver_headers,
    make_officer_headers,
    make_postdoc_headers,
    make_scholar_advisor_headers,
)

OFFICER = TEST_USERS["officer_headers"]
HR = TEST_USERS["hr_approver_headers"]
REVIEWER = TEST_USERS["export_reviewer_headers"]
ADVISOR = TEST_USERS["scholar_advisor_headers"]


# ─── The logical clock ────────────────────────────────────────────────────

def set_clock(current_utc: str, headers: dict = OFFICER) -> None:
    """Set the server's logical UTC clock; every later logical read returns it."""
    get_success_data(api_client.set_clock(current_utc, headers))


def reset_clock(headers: dict = OFFICER) -> None:
    set_clock(DEFAULT_LOGICAL_CLOCK, headers)


# ─── Registry primitives ──────────────────────────────────────────────────

def register_postdoc(headers: dict = OFFICER, **overrides) -> dict:
    return get_success_data(
        api_client.create_postdoc(create_postdoc_payload(**overrides), headers)
    )


def register_faculty_mentor(headers: dict = OFFICER, **overrides) -> dict:
    return get_success_data(
        api_client.create_faculty_mentor(create_faculty_mentor_payload(**overrides), headers)
    )


def register_funding_source(verify: bool = True, headers: dict = OFFICER,
                            approver_headers: dict = HR, **overrides) -> dict:
    """Register an award and, unless told otherwise, verify it."""
    award = get_success_data(
        api_client.create_funding_source(create_funding_source_payload(**overrides), headers)
    )
    if verify:
        award = get_success_data(
            api_client.verify_funding_source(
                award["id"], verification_payload("VERIFY"), approver_headers
            )
        )
    return award


def register_laboratory(headers: dict = OFFICER, **overrides) -> dict:
    return get_success_data(
        api_client.create_laboratory(create_laboratory_payload(**overrides), headers)
    )


# ─── Appointment lifecycle primitives ─────────────────────────────────────

def draft_appointment(postdoc_id: str, mentor_id: str, funding_source_id: str,
                      headers: dict = OFFICER, **overrides) -> dict:
    return get_success_data(
        api_client.create_appointment(
            create_appointment_payload(postdoc_id, mentor_id, funding_source_id, **overrides),
            headers,
        )
    )


def issue_offer(appointment_id: str, headers: dict = OFFICER) -> dict:
    return get_success_data(api_client.issue_offer(appointment_id, headers))


def accept_offer(appointment_id: str, postdoc_id: str,
                 processing_track: Optional[str] = None) -> dict:
    return get_success_data(
        api_client.accept_offer(
            appointment_id,
            make_postdoc_headers(postdoc_id),
            accept_offer_payload(processing_track),
        )
    )


def activate_appointment(appointment_id: str, headers: dict = OFFICER) -> dict:
    return get_success_data(api_client.activate_appointment(appointment_id, headers))


def read_appointment(appointment_id: str, headers: dict = OFFICER) -> dict:
    return get_success_data(api_client.get_appointment(appointment_id, headers))


def appointment_version(appointment_id: str, headers: dict = OFFICER) -> int:
    """Re-read the appointment's concurrency version before a guarded write."""
    return read_appointment(appointment_id, headers)["version"]


def read_funding_source(funding_source_id: str, headers: dict = HR) -> dict:
    return get_success_data(api_client.get_funding_source(funding_source_id, headers))


def read_postdoc(postdoc_id: str, headers: dict = OFFICER) -> dict:
    return get_success_data(api_client.get_postdoc(postdoc_id, headers))


def read_faculty_mentor(mentor_id: str, headers: dict = OFFICER) -> dict:
    return get_success_data(api_client.get_faculty_mentor(mentor_id, headers))


def read_laboratory(laboratory_id: str, headers: dict = OFFICER) -> dict:
    return get_success_data(api_client.get_laboratory(laboratory_id, headers))


# ─── Cascade-created children: reverse-lookup reads ───────────────────────

def list_visa_cases(appointment_id: str, headers: dict = ADVISOR,
                    params: Optional[Dict[str, Any]] = None) -> List[dict]:
    return get_success_data(
        api_client.list_visa_cases_for_appointment(appointment_id, headers, params)
    )


def latest_visa_case(appointment_id: str, headers: dict = ADVISOR) -> dict:
    cases = list_visa_cases(appointment_id, headers)
    assert cases, f"Expected a visa case for appointment {appointment_id}"
    return cases[-1]


def list_development_documents(appointment_id: str, headers: dict = OFFICER,
                               params: Optional[Dict[str, Any]] = None) -> List[dict]:
    return get_success_data(
        api_client.list_development_documents_for_appointment(
            appointment_id, headers, params
        )
    )


def development_document_of_type(appointment_id: str, doc_type: str,
                                 headers: dict = OFFICER) -> dict:
    docs = list_development_documents(appointment_id, headers, {"doc_type": doc_type})
    assert docs, f"Expected a {doc_type} document for appointment {appointment_id}"
    return docs[0]


def list_screening_cycles(appointment_id: str, headers: dict = REVIEWER,
                          params: Optional[Dict[str, Any]] = None) -> List[dict]:
    return get_success_data(
        api_client.list_export_control_reviews_for_appointment(
            appointment_id, headers, params
        )
    )


def queued_screening_cycle(appointment_id: str, headers: dict = REVIEWER) -> dict:
    """Discover the screening cycle a cascade left in QUEUED."""
    cycles = list_screening_cycles(appointment_id, headers, {"status": "QUEUED"})
    assert cycles, f"Expected a QUEUED screening cycle for appointment {appointment_id}"
    return cycles[0]


def read_exit_record(appointment_id: str, headers: dict = OFFICER) -> dict:
    records = get_success_data(
        api_client.list_exit_record_for_appointment(appointment_id, headers)
    )
    assert records, f"Expected an exit record for appointment {appointment_id}"
    return records[0]


def list_lab_access_grants(headers: dict = OFFICER,
                           params: Optional[Dict[str, Any]] = None) -> List[dict]:
    return get_success_data(api_client.list_lab_access_grants(headers, params))


def decide_screening(review_id: str, restricted_party_hit: bool = False,
                     controlled_technology_flag: bool = False,
                     headers: dict = REVIEWER) -> dict:
    return get_success_data(
        api_client.decide_export_control_review(
            review_id,
            screening_decision_payload(restricted_party_hit, controlled_technology_flag),
            headers,
        )
    )


def clear_pending_screening(appointment_id: str, restricted_party_hit: bool = False,
                            controlled_technology_flag: bool = False,
                            headers: dict = REVIEWER) -> dict:
    """Decide the appointment's outstanding QUEUED screening cycle."""
    cycle = queued_screening_cycle(appointment_id, headers)
    return decide_screening(
        cycle["id"], restricted_party_hit, controlled_technology_flag, headers
    )


def create_lab_access_grant(appointment_id: str, laboratory_id: str, mentor_id: str,
                            expected_version: Optional[int] = None, **overrides) -> dict:
    """Request bench seats, re-reading the appointment version when not supplied."""
    version = (
        expected_version if expected_version is not None
        else appointment_version(appointment_id)
    )
    return get_success_data(
        api_client.create_lab_access_grant(
            create_lab_access_grant_payload(
                appointment_id, laboratory_id, version, **overrides
            ),
            make_faculty_mentor_headers(mentor_id),
        )
    )


# ─── Scenario container ───────────────────────────────────────────────────

class Scenario:
    """The records a composite setup produced, plus the identities that act."""

    def __init__(self, postdoc: dict, mentor: dict, funding_source: dict,
                 laboratory: Optional[dict] = None, appointment: Optional[dict] = None,
                 officer_user_id: str = OFFICER_USER_ID):
        self.postdoc = postdoc
        self.mentor = mentor
        self.funding_source = funding_source
        self.laboratory = laboratory
        self.appointment = appointment
        self.officer_user_id = officer_user_id

    # -- identities ------------------------------------------------------
    @property
    def officer_headers(self) -> dict:
        return make_officer_headers(self.officer_user_id)

    @property
    def mentor_headers(self) -> dict:
        return make_faculty_mentor_headers(self.mentor["id"])

    @property
    def postdoc_headers(self) -> dict:
        return make_postdoc_headers(self.postdoc["id"])

    @property
    def hr_headers(self) -> dict:
        return HR

    @property
    def reviewer_headers(self) -> dict:
        return REVIEWER

    @property
    def advisor_headers(self) -> dict:
        return ADVISOR

    # -- convenience ids -------------------------------------------------
    @property
    def appointment_id(self) -> str:
        return self.appointment["id"]

    # -- re-reads --------------------------------------------------------
    def refresh_appointment(self) -> dict:
        self.appointment = read_appointment(self.appointment_id, self.officer_headers)
        return self.appointment

    def refresh_funding_source(self) -> dict:
        self.funding_source = read_funding_source(self.funding_source["id"])
        return self.funding_source

    def refresh_postdoc(self) -> dict:
        self.postdoc = read_postdoc(self.postdoc["id"], self.officer_headers)
        return self.postdoc

    def refresh_mentor(self) -> dict:
        self.mentor = read_faculty_mentor(self.mentor["id"], self.officer_headers)
        return self.mentor

    def version(self) -> int:
        return appointment_version(self.appointment_id, self.officer_headers)


# ─── Tier 1: registries ───────────────────────────────────────────────────

def setup_registries(postdoc_overrides: Optional[dict] = None,
                     mentor_overrides: Optional[dict] = None,
                     funding_overrides: Optional[dict] = None,
                     laboratory_overrides: Optional[dict] = None,
                     verify_award: bool = True,
                     with_laboratory: bool = False,
                     officer_user_id: str = OFFICER_USER_ID) -> Scenario:
    """One scholar, one mentor, one award and optionally one laboratory."""
    officer = make_officer_headers(officer_user_id)
    mentor = register_faculty_mentor(officer, **(mentor_overrides or {}))
    funding = register_funding_source(
        verify=verify_award, headers=officer, **(funding_overrides or {})
    )
    postdoc = register_postdoc(officer, **(postdoc_overrides or {}))
    laboratory = (
        register_laboratory(officer, **(laboratory_overrides or {}))
        if with_laboratory or laboratory_overrides is not None else None
    )
    return Scenario(postdoc, mentor, funding, laboratory,
                    officer_user_id=officer_user_id)


# ─── Tier 2: appointment states ───────────────────────────────────────────

def setup_draft_appointment(appointment_overrides: Optional[dict] = None,
                            **registry_kwargs) -> Scenario:
    """Registries plus one DRAFT appointment."""
    scenario = setup_registries(**registry_kwargs)
    scenario.appointment = draft_appointment(
        scenario.postdoc["id"], scenario.mentor["id"], scenario.funding_source["id"],
        scenario.officer_headers, **(appointment_overrides or {}),
    )
    return scenario


def setup_offer_issued(appointment_overrides: Optional[dict] = None,
                       **registry_kwargs) -> Scenario:
    """Registries plus one appointment advanced DRAFT to OFFER_ISSUED."""
    scenario = setup_draft_appointment(appointment_overrides, **registry_kwargs)
    scenario.appointment = issue_offer(scenario.appointment_id, scenario.officer_headers)
    return scenario


def setup_offer_accepted(appointment_overrides: Optional[dict] = None,
                         processing_track: Optional[str] = None,
                         **registry_kwargs) -> Scenario:
    """Registries plus one appointment advanced to OFFER_ACCEPTED."""
    scenario = setup_offer_issued(appointment_overrides, **registry_kwargs)
    scenario.appointment = accept_offer(
        scenario.appointment_id, scenario.postdoc["id"], processing_track
    )
    return scenario


def setup_cleared_appointment(appointment_overrides: Optional[dict] = None,
                              restricted_party_hit: bool = False,
                              controlled_technology_flag: bool = False,
                              processing_track: Optional[str] = None,
                              **registry_kwargs) -> Scenario:
    """An OFFER_ACCEPTED appointment whose first screening cycle has been decided."""
    scenario = setup_offer_accepted(
        appointment_overrides, processing_track, **registry_kwargs
    )
    scenario.screening = clear_pending_screening(
        scenario.appointment_id, restricted_party_hit, controlled_technology_flag
    )
    scenario.refresh_appointment()
    return scenario


def approve_development_documents(scenario: Scenario) -> List[dict]:
    """Drive every funder-mandated document to APPROVED.

    The mentor submits, the scholar acknowledges, and the officer approves; the
    acknowledgement is recorded because an IDP may only be approved while
    `postdoc_acknowledged` is true.
    """
    approved = []
    for doc in list_development_documents(scenario.appointment_id, scenario.officer_headers):
        get_success_data(
            api_client.submit_development_document(
                doc["id"], submit_document_payload(), scenario.mentor_headers
            )
        )
        get_success_data(
            api_client.acknowledge_development_document(doc["id"], scenario.postdoc_headers)
        )
        approved.append(
            get_success_data(
                api_client.review_development_document(
                    doc["id"], review_document_payload("APPROVE"), scenario.officer_headers
                )
            )
        )
    return approved


def setup_active_appointment(appointment_overrides: Optional[dict] = None,
                             restricted_party_hit: bool = False,
                             controlled_technology_flag: bool = False,
                             **registry_kwargs) -> Scenario:
    """An appointment driven all the way to ACTIVE."""
    scenario = setup_cleared_appointment(
        appointment_overrides, restricted_party_hit, controlled_technology_flag,
        **registry_kwargs,
    )
    approve_development_documents(scenario)
    scenario.appointment = activate_appointment(
        scenario.appointment_id, scenario.officer_headers
    )
    return scenario


def setup_active_with_bench_grant(appointment_overrides: Optional[dict] = None,
                                  grant_overrides: Optional[dict] = None,
                                  laboratory_overrides: Optional[dict] = None,
                                  **registry_kwargs) -> Scenario:
    """An ACTIVE appointment holding one PROVISIONED bench-access grant."""
    registry_kwargs.setdefault("with_laboratory", True)
    if laboratory_overrides is not None:
        registry_kwargs["laboratory_overrides"] = laboratory_overrides
    scenario = setup_active_appointment(appointment_overrides, **registry_kwargs)
    scenario.grant = create_lab_access_grant(
        scenario.appointment_id, scenario.laboratory["id"], scenario.mentor["id"],
        **(grant_overrides or {}),
    )
    return scenario


# ─── Tier 3: the sponsorship pipeline ─────────────────────────────────────

def submit_petition(visa_case_id: str, processing_track: Optional[str] = None,
                   headers: dict = ADVISOR) -> dict:
    return get_success_data(
        api_client.submit_petition(
            visa_case_id, headers, submit_petition_payload(processing_track)
        )
    )


def adjudicate(visa_case_id: str, outcome: str, decision_note: Optional[str] = None,
               headers: dict = ADVISOR) -> dict:
    return get_success_data(
        api_client.record_adjudication(
            visa_case_id, adjudication_payload(outcome, decision_note), headers
        )
    )


def setup_sponsored_offer_accepted(appointment_overrides: Optional[dict] = None,
                                   postdoc_overrides: Optional[dict] = None,
                                   processing_track: Optional[str] = None,
                                   **registry_kwargs) -> Scenario:
    """An OFFER_ACCEPTED appointment for a scholar who needs sponsorship, so the
    acceptance cascade has selected a category and created the visa case."""
    overrides = {"requires_sponsorship": True}
    overrides.update(postdoc_overrides or {})
    registry_kwargs["postdoc_overrides"] = overrides
    scenario = setup_offer_accepted(
        appointment_overrides, processing_track, **registry_kwargs
    )
    scenario.visa_case = latest_visa_case(scenario.appointment_id)
    return scenario


def setup_visa_submitted(appointment_overrides: Optional[dict] = None,
                         postdoc_overrides: Optional[dict] = None,
                         processing_track: Optional[str] = None,
                         filed_at: Optional[str] = None,
                         **registry_kwargs) -> Scenario:
    """A sponsored appointment whose petition has been filed once."""
    scenario = setup_sponsored_offer_accepted(
        appointment_overrides, postdoc_overrides, processing_track, **registry_kwargs
    )
    if filed_at:
        set_clock(filed_at, scenario.officer_headers)
    scenario.visa_case = submit_petition(scenario.visa_case["id"], processing_track)
    return scenario


# ─── Tier 4: reappointment review, notice and grievance ───────────────────

def open_review(appointment_id: str, headers: dict = OFFICER) -> dict:
    return get_success_data(api_client.open_reappointment_review(appointment_id, headers))


def record_recommendation(review_id: str, recommendation: str, mentor_id: str,
                          note: str = "Written recommendation.") -> dict:
    return get_success_data(
        api_client.record_recommendation(
            review_id, recommendation_payload(recommendation, note),
            make_faculty_mentor_headers(mentor_id),
        )
    )


def finalize_review(review_id: str, decision: str, headers: dict = OFFICER) -> dict:
    return get_success_data(
        api_client.finalize_reappointment_review(review_id, finalize_payload(decision), headers)
    )


def setup_review_recommended(scenario: Scenario, recommendation: str,
                             clock: Optional[str] = None) -> dict:
    """Open a review on an ACTIVE appointment and record the mentor's recommendation."""
    if clock:
        set_clock(clock, scenario.officer_headers)
    review = open_review(scenario.appointment_id, scenario.officer_headers)
    record_recommendation(review["id"], recommendation, scenario.mentor["id"])
    return review


def setup_finalized_non_renewed(appointment_overrides: Optional[dict] = None,
                                review_clock: str = "2027-05-01T10:00:00Z",
                                **registry_kwargs) -> Scenario:
    """An ACTIVE appointment carried through to FINALIZED_NON_RENEWED, so the
    notice policy fields and the grievance window are populated."""
    scenario = setup_active_appointment(appointment_overrides, **registry_kwargs)
    review = setup_review_recommended(scenario, "NON_RENEW", review_clock)
    scenario.review = finalize_review(
        review["id"], "NON_RENEW", scenario.officer_headers
    )
    scenario.refresh_appointment()
    return scenario


def file_grievance(review_id: str, postdoc_id: str, category: str = "PROCEDURAL",
                   narrative: str = "The scholar's written statement.") -> dict:
    return get_success_data(
        api_client.create_grievance(
            create_grievance_payload(review_id, category, narrative),
            make_postdoc_headers(postdoc_id),
        )
    )


def resolve_grievance(grievance_id: str, outcome: str, headers: dict = OFFICER,
                      note: str = "The officer's rationale.") -> dict:
    return get_success_data(
        api_client.resolve_grievance(
            grievance_id, grievance_resolution_payload(outcome, note), headers
        )
    )


# ─── Tier 5: exit processing and separation ───────────────────────────────

def initiate_exit(appointment_id: str, exit_reason: str = "TERM_COMPLETION",
                  headers: dict = OFFICER) -> dict:
    return get_success_data(
        api_client.initiate_exit(appointment_id, initiate_exit_payload(exit_reason), headers)
    )


def sign_ip_assignment(exit_record_id: str, postdoc_id: str,
                       ip_disclosure_count: int = 0) -> dict:
    return get_success_data(
        api_client.sign_ip_assignment(
            exit_record_id, ip_assignment_payload(ip_disclosure_count),
            make_postdoc_headers(postdoc_id),
        )
    )


def setup_exit_initiated(appointment_overrides: Optional[dict] = None,
                         exit_reason: str = "TERM_COMPLETION",
                         **registry_kwargs) -> Scenario:
    """An ACTIVE appointment with exit processing opened against it."""
    scenario = setup_active_appointment(appointment_overrides, **registry_kwargs)
    scenario.exit_record = initiate_exit(
        scenario.appointment_id, exit_reason, scenario.officer_headers
    )
    return scenario


# ─── Predecessor chains for the rank ledger ───────────────────────────────

def setup_predecessor_chain(predecessor_overrides: dict,
                            successor_overrides: dict,
                            drive_predecessor_to: str = "ACTIVE",
                            **registry_kwargs) -> Scenario:
    """One scholar holding a first term plus a successor term that names it.

    `drive_predecessor_to` is how far the first term is advanced before the
    successor is drafted, which is what decides whether the first term's months
    count toward the successor's `months_in_rank_at_start`.
    """
    scenario = setup_registries(**registry_kwargs)
    first = draft_appointment(
        scenario.postdoc["id"], scenario.mentor["id"], scenario.funding_source["id"],
        scenario.officer_headers, **predecessor_overrides,
    )
    if drive_predecessor_to in ("OFFER_ISSUED", "OFFER_ACCEPTED", "ACTIVE"):
        first = issue_offer(first["id"], scenario.officer_headers)
    if drive_predecessor_to in ("OFFER_ACCEPTED", "ACTIVE"):
        first = accept_offer(first["id"], scenario.postdoc["id"])
    if drive_predecessor_to == "ACTIVE":
        clear_pending_screening(first["id"])
        temp = Scenario(scenario.postdoc, scenario.mentor, scenario.funding_source,
                        scenario.laboratory, first, scenario.officer_user_id)
        approve_development_documents(temp)
        first = activate_appointment(first["id"], scenario.officer_headers)
    scenario.predecessor = first
    successor_overrides = dict(successor_overrides)
    successor_overrides["predecessor_appointment_id"] = first["id"]
    scenario.appointment = draft_appointment(
        scenario.postdoc["id"], scenario.mentor["id"], scenario.funding_source["id"],
        scenario.officer_headers, **successor_overrides,
    )
    return scenario
