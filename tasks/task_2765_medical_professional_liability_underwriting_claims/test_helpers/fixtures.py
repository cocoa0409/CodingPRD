"""Composite state builders and the pytest fixtures that expose them.

Every builder drives the public endpoints only: the harness restarts the
server with an empty store before each test, so all state is constructed
here from the outside in.
"""
import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    TEST_USERS,
    make_insured_headers,
)

UW = TEST_USERS["underwriting_officer_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
ADJ2 = TEST_USERS["claims_adjuster_two_headers"]
APPROVER = TEST_USERS["claims_committee_approver_headers"]
CHAIR = TEST_USERS["peer_review_chair_headers"]
ANALYST = TEST_USERS["actuarial_analyst_headers"]
CHIEF = TEST_USERS["chief_actuary_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ----------------------------------------------------------------- the clock
def advance_clock(api, to_iso8601, headers=UW):
    """Sets the logical clock and hands back the checkpoint sweep report."""
    return validate_success(api.set_clock(to_iso8601, headers))


# ------------------------------------------------------- the rate manual tier
def build_specialty_class(api, **overrides):
    payload = factories.specialty_class_payload(**overrides)
    return validate_success(api.create_specialty_class(payload, ANALYST), 201)


def build_orthopedic_class(api, **overrides):
    """A second rating class, used where two specialties must coexist."""
    defaults = {
        "specialty_code": "ORTHOPEDIC_SURGERY",
        "base_class_code": "CLASS_5",
        "base_rate_per_million": 32000.00,
        "hazard_index": 6.0,
        "benchmark_severity": 480000.00,
    }
    defaults.update(overrides)
    return build_specialty_class(api, **defaults)


# ------------------------------------------------------------- insured tier
def build_insured(api, specialty_class_id, **overrides):
    payload = factories.insured_payload(specialty_class_id, **overrides)
    return validate_success(api.create_insured(payload, UW), 201)


def credential_insured(api, insured_id, credentialing_status="CREDENTIALED",
                       credentialing_expires_on="2028-01-01"):
    payload = factories.credentialing_decision_payload(
        credentialing_status, credentialing_expires_on
    )
    return validate_success(api.record_credentialing_decision(insured_id, payload, UW))


def build_credentialed_insured(api, specialty_class_id,
                               credentialing_expires_on="2028-01-01", **overrides):
    """An insured whose credentialing axis will support term issuance."""
    insured = build_insured(api, specialty_class_id, **overrides)
    return credential_insured(
        api, insured["id"], "CREDENTIALED", credentialing_expires_on
    )


def enrol_insured(api, insured_id, program_code="SIM_LAB",
                  enrolled_on="2026-08-05", insured_version=None):
    """Enrols against the insured's freshly read version, as §2.9 requires."""
    if insured_version is None:
        insured_version = validate_success(api.get_insured(insured_id, UW))["version"]
    payload = factories.enrollment_payload(
        program_code=program_code,
        enrolled_on=enrolled_on,
        expected_insured_version=insured_version,
    )
    return validate_success(api.create_enrollment(insured_id, payload, UW), 201)


def complete_enrolment(api, enrollment_id, completed_on="2026-08-10",
                       attestation_reference="SIM-2026-0001"):
    payload = factories.enrollment_completion_payload(
        completed_on, attestation_reference
    )
    return validate_success(api.complete_enrollment(enrollment_id, payload, UW))


# --------------------------------------------------------- peer review tier
def build_peer_review_case(api, insured_id, **overrides):
    payload = factories.peer_review_case_payload(insured_id, **overrides)
    return validate_success(api.create_peer_review_case(payload, CHAIR), 201)


def build_reviews_complete_case(api, insured_id, chart_outcome="CONCERN",
                                external_outcome="CONCERN"):
    """Drives a referral through the two-track fork-join to REVIEWS_COMPLETE."""
    case = build_peer_review_case(api, insured_id)
    validate_success(api.record_review_track(
        case["id"], factories.review_track_payload("CHART", chart_outcome), CHAIR
    ))
    return validate_success(api.record_review_track(
        case["id"], factories.review_track_payload("EXTERNAL", external_outcome), CHAIR
    ))


def close_peer_review_case(api, case_id, vote_result="DEVIATION_MINOR",
                           votes_for=4, votes_against=1):
    payload = factories.committee_vote_payload(vote_result, votes_for, votes_against)
    return validate_success(api.record_committee_vote(case_id, payload, CHAIR))


# ---------------------------------------------------------------- policy tier
def build_policy(api, insured_id, **overrides):
    payload = factories.policy_payload(insured_id, **overrides)
    return validate_success(api.create_policy(payload, UW), 201)


def build_term(api, policy_id, effective_date="2026-09-01",
               expiration_date="2027-09-01", predecessor_term_id=None,
               policy_version=None, **overrides):
    """Adds a term, reading the policy's current version first per §2.9."""
    if policy_version is None:
        policy_version = validate_success(api.get_policy(policy_id, UW))["version"]
    payload = factories.policy_term_payload(
        effective_date=effective_date,
        expiration_date=expiration_date,
        expected_policy_version=policy_version,
        predecessor_term_id=predecessor_term_id,
        **overrides,
    )
    return validate_success(api.create_policy_term(policy_id, payload, UW), 201)


def issue_term(api, term_id):
    return validate_success(api.issue_policy_term(term_id, UW))


def cancel_term(api, term_id, cancel_type="PRO_RATA",
                cancel_effective_date="2027-03-01"):
    payload = factories.cancellation_payload(cancel_type, cancel_effective_date)
    return validate_success(api.cancel_policy_term(term_id, payload, UW))


def build_in_force_term(api, policy_id, effective_date="2026-09-01",
                        expiration_date="2027-09-01", **overrides):
    """Advances the clock onto the effective date so issuance binds live cover."""
    term = build_term(api, policy_id, effective_date, expiration_date, **overrides)
    advance_clock(api, f"{effective_date}T00:00:00Z")
    return issue_term(api, term["id"])


def build_expired_term(api, policy_id, effective_date="2026-09-01",
                       expiration_date="2027-09-01", **overrides):
    """One clock advance past the expiration date promotes and then expires it."""
    term = build_term(api, policy_id, effective_date, expiration_date, **overrides)
    issue_term(api, term["id"])
    advance_clock(api, f"{expiration_date}T00:00:00Z")
    return validate_success(api.get_policy_term(term["id"], UW))


def build_tail(api, policy_id, triggering_term_id, **overrides):
    payload = factories.tail_endorsement_payload(triggering_term_id, **overrides)
    return validate_success(
        api.create_tail_endorsement(policy_id, payload, UW), 201
    )


def issue_tail(api, tail_id):
    return validate_success(api.issue_tail_endorsement(tail_id, UW))


# --------------------------------------------------- the standard cover stack
def build_covered_book(api):
    """The recurring baseline: a rated class, a credentialed insured, a
    claims-made policy and one live term running 2026-09-01 to 2027-09-01."""
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"])
    term = build_in_force_term(api, policy["id"])
    return {
        "specialty_class": specialty,
        "insured": validate_success(api.get_insured(insured["id"], UW)),
        "policy": validate_success(api.get_policy(policy["id"], UW)),
        "term": term,
    }


# ------------------------------------------------------------------ claim tier
def build_claim(api, insured_id, **overrides):
    payload = factories.claim_payload(insured_id, **overrides)
    return validate_success(api.create_claim(payload, ADJ), 201)


def decide_coverage(api, claim_id, coverage_status="COVERED",
                    reserved_rights_reason=None):
    payload = factories.coverage_decision_payload(
        coverage_status, reserved_rights_reason
    )
    return validate_success(api.record_coverage_decision(claim_id, payload, ADJ))


def build_investigated_claim(api, insured_id, coverage_status="COVERED",
                             **overrides):
    """A claim carried through intake into INVESTIGATION with cover decided."""
    claim = build_claim(api, insured_id, **overrides)
    return decide_coverage(api, claim["id"], coverage_status)


def build_litigated_claim(api, insured_id, suit_filed_on="2026-12-01",
                          **overrides):
    claim = build_investigated_claim(api, insured_id, **overrides)
    payload = factories.litigation_payload(suit_filed_on)
    return validate_success(api.record_litigation(claim["id"], payload, ADJ))


def post_reserve(api, claim_id, method="FORMULA_BASIS",
                 effective_at="2026-11-05T00:00:00Z", claim_version=None,
                 **overrides):
    """Posts a reserve entry against the claim's freshly read version."""
    if claim_version is None:
        claim_version = validate_success(api.get_claim(claim_id, ADJ))["version"]
    payload = factories.reserve_entry_payload(
        method=method,
        effective_at=effective_at,
        expected_claim_version=claim_version,
        **overrides,
    )
    return validate_success(api.create_reserve_entry(claim_id, payload, ADJ), 201)


def dispose_claim(api, claim_id, disposition="DEFENSE_VERDICT",
                  resolved_on="2027-02-01", verdict_amount=None):
    payload = factories.disposition_payload(disposition, resolved_on, verdict_amount)
    return validate_success(api.record_disposition(claim_id, payload, ADJ))


# --------------------------------------------------------- defence panel tier
def build_counsel_firm(api, **overrides):
    payload = factories.counsel_firm_payload(**overrides)
    return validate_success(api.create_counsel_firm(payload, APPROVER), 201)


def change_panel_status(api, firm_id, panel_status="REMOVED",
                       reason="Panel audit finding."):
    payload = factories.panel_status_payload(panel_status, reason)
    return validate_success(api.change_panel_status(firm_id, payload, APPROVER))


def assign_counsel(api, claim_id):
    return validate_success(api.create_counsel_assignment(claim_id, ADJ), 201)


def decline_assignment(api, assignment_id, decline_reason="CONFLICT_OF_INTEREST"):
    payload = factories.decline_payload(decline_reason)
    return validate_success(
        api.decline_counsel_assignment(assignment_id, payload, ADJ)
    )


def pay_expense(api, claim_id, assignment_id, amount=20000.00,
                invoice_reference="INV-0001"):
    payload = factories.expense_payment_payload(
        amount, invoice_reference, assignment_id
    )
    return validate_success(api.pay_expense(claim_id, payload, ADJ))


def build_defended_claim(api, insured_id, **overrides):
    """A litigated claim with one panel firm admitted and counsel assigned."""
    firm = build_counsel_firm(api)
    claim = build_litigated_claim(api, insured_id, **overrides)
    assignment = assign_counsel(api, claim["id"])
    return {
        "firm": validate_success(api.get_counsel_firm(firm["id"], APPROVER)),
        "claim": validate_success(api.get_claim(claim["id"], ADJ)),
        "assignment": assignment,
    }


# ----------------------------------------------------------- negotiation tier
def open_negotiation(api, claim_id, proposed_amount=400000.00,
                     authority_requested=400000.00, claim_version=None,
                     headers=None):
    if claim_version is None:
        claim_version = validate_success(api.get_claim(claim_id, ADJ))["version"]
    payload = factories.negotiation_payload(
        proposed_amount=proposed_amount,
        authority_requested=authority_requested,
        expected_claim_version=claim_version,
    )
    return validate_success(
        api.create_settlement_negotiation(claim_id, payload, headers or ADJ), 201
    )


def decide_authority(api, negotiation_id, decision="GRANT",
                     granted_amount=400000.00, headers=None):
    payload = factories.authority_decision_payload(decision, granted_amount)
    return validate_success(
        api.record_authority_decision(negotiation_id, payload, headers or APPROVER)
    )


def request_consent(api, negotiation_id):
    return validate_success(api.request_consent(negotiation_id, ADJ))


def respond_to_consent(api, negotiation_id, insured_id, response="CONSENTED",
                       veto_reason=None):
    """The one write reserved to the Insured role, so the acting identity is
    the claim's own insured."""
    payload = factories.consent_response_payload(response, veto_reason)
    return validate_success(api.record_consent_response(
        negotiation_id, payload, make_insured_headers(insured_id)
    ))


def revise_negotiation(api, negotiation_id, proposed_amount=300000.00,
                       authority_requested=300000.00):
    payload = factories.revision_payload(proposed_amount, authority_requested)
    return validate_success(api.revise_negotiation(negotiation_id, payload, ADJ))


def invoke_hammer(api, negotiation_id, notice_sent_on="2027-01-15"):
    payload = factories.hammer_invocation_payload(notice_sent_on)
    return validate_success(api.invoke_hammer(negotiation_id, payload, APPROVER))


def pay_settlement(api, negotiation_id, payment_date="2027-02-01"):
    payload = factories.settlement_payment_payload(payment_date)
    return validate_success(api.pay_settlement(negotiation_id, payload, ADJ))


def build_authorised_negotiation(api, claim_id, proposed_amount=400000.00,
                                 authority_requested=400000.00,
                                 granted_amount=None):
    """A negotiation carried to AUTHORITY_GRANTED by a second operator."""
    negotiation = open_negotiation(
        api, claim_id, proposed_amount, authority_requested
    )
    return decide_authority(
        api, negotiation["id"], "GRANT",
        authority_requested if granted_amount is None else granted_amount,
    )


def build_vetoed_negotiation(api, claim_id, insured_id, proposed_amount=400000.00):
    """A negotiation driven through consent to the physician's veto."""
    negotiation = build_authorised_negotiation(api, claim_id, proposed_amount,
                                               proposed_amount)
    request_consent(api, negotiation["id"])
    return respond_to_consent(
        api, negotiation["id"], insured_id, "VETOED", "Reputational exposure."
    )


# ------------------------------------------------------------ data bank tier
def npdb_report_for_claim(api, claim_id):
    """The obligation is minted by the system, so it is found rather than made."""
    reports, _ = _paginated(api.list_npdb_reports(COMPLIANCE, {"claim_id": claim_id}))
    return reports[0] if reports else None


def submit_npdb_report(api, report_id, submitted_on="2027-02-15",
                       submitter_note="Transmitted to the data bank."):
    payload = factories.npdb_submission_payload(submitted_on, submitter_note)
    return validate_success(api.submit_npdb_report(report_id, payload, COMPLIANCE))


def void_npdb_report(api, report_id, void_reason="Duplicate obligation."):
    payload = factories.npdb_void_payload(void_reason)
    return validate_success(api.void_npdb_report(report_id, payload, COMPLIANCE))


def _paginated(response):
    return validate_paginated(response)


# ---------------------------------------------------------- rate filing tier
def build_rate_filing(api, specialty_class_id, **overrides):
    payload = factories.rate_filing_payload(specialty_class_id, **overrides)
    return validate_success(api.create_rate_filing(payload, ANALYST), 201)


def submit_rate_filing(api, filing_id):
    return validate_success(api.submit_rate_filing(filing_id, ANALYST))


def decide_rate_filing(api, filing_id, decision="APPROVE",
                       decision_note="Approved."):
    payload = factories.filing_decision_payload(decision, decision_note)
    return validate_success(api.decide_rate_filing(filing_id, payload, CHIEF))


def build_submitted_filing(api, specialty_class_id, **overrides):
    filing = build_rate_filing(api, specialty_class_id, **overrides)
    return submit_rate_filing(api, filing["id"])


# ============================================================================
# pytest fixtures
# ============================================================================
@pytest.fixture
def api():
    """A client bound to the harness base URL, one per test."""
    return ApiClient()


@pytest.fixture
def underwriting_officer_headers():
    return UW


@pytest.fixture
def claims_adjuster_headers():
    return ADJ


@pytest.fixture
def second_claims_adjuster_headers():
    return ADJ2


@pytest.fixture
def claims_committee_approver_headers():
    return APPROVER


@pytest.fixture
def peer_review_chair_headers():
    return CHAIR


@pytest.fixture
def actuarial_analyst_headers():
    return ANALYST


@pytest.fixture
def chief_actuary_headers():
    return CHIEF


@pytest.fixture
def compliance_officer_headers():
    return COMPLIANCE


@pytest.fixture
def specialty_class(api):
    """The obstetrics rating class the rest of the ladder is priced from."""
    return build_specialty_class(api)


@pytest.fixture
def insured(api, specialty_class):
    """A registered but not yet credentialed insured."""
    return build_insured(api, specialty_class["id"])


@pytest.fixture
def credentialed_insured(api, specialty_class):
    return build_credentialed_insured(api, specialty_class["id"])


@pytest.fixture
def quoted_policy(api, credentialed_insured):
    """A claims-made policy at the one-million limit with no consent clause."""
    return build_policy(api, credentialed_insured["id"])


@pytest.fixture
def draft_term(api, quoted_policy):
    """A first, step-one term still in DRAFT, rated but unbound."""
    return build_term(api, quoted_policy["id"])


@pytest.fixture
def covered_book(api):
    """Rating class, credentialed insured, policy and one live term."""
    return build_covered_book(api)


@pytest.fixture
def counsel_firm(api):
    return build_counsel_firm(api)


@pytest.fixture
def investigated_claim(api, covered_book):
    """A covered claim on a live term, sitting in INVESTIGATION."""
    claim = build_investigated_claim(api, covered_book["insured"]["id"])
    return {"book": covered_book, "claim": claim}


@pytest.fixture
def litigated_claim(api, covered_book):
    claim = build_litigated_claim(api, covered_book["insured"]["id"])
    return {"book": covered_book, "claim": claim}


@pytest.fixture
def defended_claim(api, covered_book):
    """A litigated claim with counsel selected from a one-firm panel."""
    bundle = build_defended_claim(api, covered_book["insured"]["id"])
    bundle["book"] = covered_book
    return bundle


@pytest.fixture
def reviews_complete_case(api, credentialed_insured):
    """A peer review case whose two tracks have both landed."""
    return build_reviews_complete_case(api, credentialed_insured["id"])


@pytest.fixture
def submitted_rate_filing(api, specialty_class):
    return build_submitted_filing(api, specialty_class["id"])
