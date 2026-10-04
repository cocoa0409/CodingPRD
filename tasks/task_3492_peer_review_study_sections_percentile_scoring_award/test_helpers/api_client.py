"""API client: one method per endpoint defined in the PRD.

This module is import-safe both ways:

    import test_helpers.api_client as ac
    ac.get_application(...)            # module-level function (works)

    from test_helpers.api_client import ApiClient
    ApiClient().get_application(...)   # class instance method (works)

The module-level functions delegate to a single internal ApiClient instance
created at import time (the runner injects API_BASE_URL before pytest starts,
so import-time construction reads the correct base URL).

Path note: the clock operation lives outside the business prefix at
/_clock/set_current_utc (PRD: "a separate operator capability for driving the
logical clock lives outside that prefix"); all other paths sit under /grants.
"""
from prd_bench_local_runner.testing import GenericApiClient

GRANTS = "/grants"
CLOCK_PATH = "/_clock/set_current_utc"


class ApiClient(GenericApiClient):
    """PRD-specific endpoint methods; transport inherited from the framework."""

    # --- Clock (outside the business surface) ------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", CLOCK_PATH, payload, headers)

    # --- FundingOpportunity -------------------------------------------------
    def create_funding_opportunity(self, payload, headers):
        return self._request("POST", f"{GRANTS}/funding-opportunities", payload, headers)

    def get_funding_opportunity(self, foa_id, headers):
        return self._request("GET", f"{GRANTS}/funding-opportunities/{foa_id}", headers=headers)

    def close_funding_opportunity(self, foa_id, headers):
        return self._request("POST", f"{GRANTS}/funding-opportunities/{foa_id}/close", {}, headers)

    # --- Institute ----------------------------------------------------------
    def create_institute(self, payload, headers):
        return self._request("POST", f"{GRANTS}/institutes", payload, headers)

    def get_institute(self, institute_id, headers):
        return self._request("GET", f"{GRANTS}/institutes/{institute_id}", headers=headers)

    def publish_payline_decision(self, institute_id, payload, headers):
        return self._request("POST", f"{GRANTS}/institutes/{institute_id}/payline-decisions", payload, headers)

    # --- Institution --------------------------------------------------------
    def create_institution(self, payload, headers):
        return self._request("POST", f"{GRANTS}/institutions", payload, headers)

    def get_institution(self, institution_id, headers):
        return self._request("GET", f"{GRANTS}/institutions/{institution_id}", headers=headers)

    # --- Applicant ----------------------------------------------------------
    def create_applicant(self, payload, headers):
        return self._request("POST", f"{GRANTS}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{GRANTS}/applicants/{applicant_id}", headers=headers)

    # --- Application --------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{GRANTS}/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{GRANTS}/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{GRANTS}/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"{GRANTS}/applications/{application_id}/submit", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"{GRANTS}/applications/{application_id}/withdraw", {}, headers)

    def refer_application(self, application_id, payload, headers):
        return self._request("POST", f"{GRANTS}/applications/{application_id}/referral", payload, headers)

    def select_pay_application(self, application_id, payload, headers):
        return self._request("POST", f"{GRANTS}/applications/{application_id}/select-pay", payload, headers)

    def list_council_reviews(self, application_id, headers, params=None):
        return self._request("GET", f"{GRANTS}/applications/{application_id}/council-reviews", headers=headers, params=params)

    def list_application_jit_requests(self, application_id, headers, params=None):
        return self._request("GET", f"{GRANTS}/applications/{application_id}/jit-requests", headers=headers, params=params)

    # --- StudySection -------------------------------------------------------
    def create_study_section(self, payload, headers):
        return self._request("POST", f"{GRANTS}/study-sections", payload, headers)

    def get_study_section(self, section_id, headers):
        return self._request("GET", f"{GRANTS}/study-sections/{section_id}", headers=headers)

    def convene_study_section(self, section_id, headers):
        return self._request("POST", f"{GRANTS}/study-sections/{section_id}/convene", {}, headers)

    def release_section_scores(self, section_id, headers):
        return self._request("POST", f"{GRANTS}/study-sections/{section_id}/release-scores", {}, headers)

    # --- Reviewer -----------------------------------------------------------
    def create_reviewer(self, payload, headers):
        return self._request("POST", f"{GRANTS}/reviewers", payload, headers)

    def list_reviewers(self, headers, params=None):
        return self._request("GET", f"{GRANTS}/reviewers", headers=headers, params=params)

    def get_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"{GRANTS}/reviewers/{reviewer_id}", headers=headers)

    def reviewer_respond(self, reviewer_id, payload, headers):
        return self._request("POST", f"{GRANTS}/reviewers/{reviewer_id}/respond", payload, headers)

    def reviewer_declare_conflict(self, reviewer_id, payload, headers):
        return self._request("POST", f"{GRANTS}/reviewers/{reviewer_id}/declare-conflict", payload, headers)

    # --- Assignment ---------------------------------------------------------
    def create_assignment(self, payload, headers):
        return self._request("POST", f"{GRANTS}/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", f"{GRANTS}/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"{GRANTS}/assignments/{assignment_id}", headers=headers)

    def assignment_respond(self, assignment_id, payload, headers):
        return self._request("POST", f"{GRANTS}/assignments/{assignment_id}/respond", payload, headers)

    def submit_critique(self, assignment_id, payload, headers):
        return self._request("POST", f"{GRANTS}/assignments/{assignment_id}/submit-critique", payload, headers)

    # --- CouncilReview ------------------------------------------------------
    def create_council_review(self, payload, headers):
        return self._request("POST", f"{GRANTS}/council-reviews", payload, headers)

    # --- JitRequest ---------------------------------------------------------
    def get_jit_request(self, jit_request_id, headers):
        return self._request("GET", f"{GRANTS}/jit-requests/{jit_request_id}", headers=headers)

    def submit_jit_items(self, jit_request_id, payload, headers):
        return self._request("POST", f"{GRANTS}/jit-requests/{jit_request_id}/submit-items", payload, headers)

    def adjudicate_jit_request(self, jit_request_id, payload, headers):
        return self._request("POST", f"{GRANTS}/jit-requests/{jit_request_id}/adjudicate", payload, headers)

    # --- Award --------------------------------------------------------------
    def issue_award(self, application_id, payload, headers):
        return self._request("POST", f"{GRANTS}/applications/{application_id}/award", payload, headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", f"{GRANTS}/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"{GRANTS}/awards/{award_id}", headers=headers)

    # --- ProgressReport -----------------------------------------------------
    def create_progress_report(self, award_id, payload, headers):
        return self._request("POST", f"{GRANTS}/awards/{award_id}/progress-reports", payload, headers)

    def list_progress_reports(self, award_id, headers, params=None):
        return self._request("GET", f"{GRANTS}/awards/{award_id}/progress-reports", headers=headers, params=params)

    def accept_progress_report(self, report_id, headers):
        return self._request("POST", f"{GRANTS}/progress-reports/{report_id}/accept", {}, headers)

    # --- AwardModification --------------------------------------------------
    def create_award_modification(self, award_id, payload, headers):
        return self._request("POST", f"{GRANTS}/awards/{award_id}/modifications", payload, headers)

    def list_award_modifications(self, award_id, headers, params=None):
        return self._request("GET", f"{GRANTS}/awards/{award_id}/modifications", headers=headers, params=params)

    def adjudicate_modification(self, modification_id, payload, headers):
        return self._request("POST", f"{GRANTS}/award-modifications/{modification_id}/adjudicate", payload, headers)

    # --- TransferRequest ----------------------------------------------------
    def create_transfer_request(self, award_id, payload, headers):
        return self._request("POST", f"{GRANTS}/awards/{award_id}/transfer-requests", payload, headers)

    def list_transfer_requests(self, headers, params=None):
        return self._request("GET", f"{GRANTS}/transfer-requests", headers=headers, params=params)

    def get_transfer_request(self, transfer_id, headers):
        return self._request("GET", f"{GRANTS}/transfer-requests/{transfer_id}", headers=headers)

    def relinquish_transfer(self, transfer_id, headers):
        return self._request("POST", f"{GRANTS}/transfer-requests/{transfer_id}/relinquish", {}, headers)

    def decide_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"{GRANTS}/transfer-requests/{transfer_id}/decide", payload, headers)


# Internal shared client. NOT exported under the name "api_client" at package
# level — the package __init__ re-exports this module itself so that
# `import test_helpers.api_client as ac` always binds the module.
_default_client = ApiClient()


def get_default_client() -> ApiClient:
    """Return the shared ApiClient singleton."""
    return _default_client


# --- Module-level delegates -------------------------------------------------

def set_clock(payload, headers):
    return _default_client.set_clock(payload, headers)


def create_funding_opportunity(payload, headers):
    return _default_client.create_funding_opportunity(payload, headers)


def get_funding_opportunity(foa_id, headers):
    return _default_client.get_funding_opportunity(foa_id, headers)


def close_funding_opportunity(foa_id, headers):
    return _default_client.close_funding_opportunity(foa_id, headers)


def create_institute(payload, headers):
    return _default_client.create_institute(payload, headers)


def get_institute(institute_id, headers):
    return _default_client.get_institute(institute_id, headers)


def publish_payline_decision(institute_id, payload, headers):
    return _default_client.publish_payline_decision(institute_id, payload, headers)


def create_institution(payload, headers):
    return _default_client.create_institution(payload, headers)


def get_institution(institution_id, headers):
    return _default_client.get_institution(institution_id, headers)


def create_applicant(payload, headers):
    return _default_client.create_applicant(payload, headers)


def get_applicant(applicant_id, headers):
    return _default_client.get_applicant(applicant_id, headers)


def create_application(payload, headers):
    return _default_client.create_application(payload, headers)


def list_applications(headers, params=None):
    return _default_client.list_applications(headers, params=params)


def get_application(application_id, headers):
    return _default_client.get_application(application_id, headers)


def submit_application(application_id, headers):
    return _default_client.submit_application(application_id, headers)


def withdraw_application(application_id, headers):
    return _default_client.withdraw_application(application_id, headers)


def refer_application(application_id, payload, headers):
    return _default_client.refer_application(application_id, payload, headers)


def select_pay_application(application_id, payload, headers):
    return _default_client.select_pay_application(application_id, payload, headers)


def list_council_reviews(application_id, headers, params=None):
    return _default_client.list_council_reviews(application_id, headers, params=params)


def list_application_jit_requests(application_id, headers, params=None):
    return _default_client.list_application_jit_requests(application_id, headers, params=params)


def create_study_section(payload, headers):
    return _default_client.create_study_section(payload, headers)


def get_study_section(section_id, headers):
    return _default_client.get_study_section(section_id, headers)


def convene_study_section(section_id, headers):
    return _default_client.convene_study_section(section_id, headers)


def release_section_scores(section_id, headers):
    return _default_client.release_section_scores(section_id, headers)


def create_reviewer(payload, headers):
    return _default_client.create_reviewer(payload, headers)


def list_reviewers(headers, params=None):
    return _default_client.list_reviewers(headers, params=params)


def get_reviewer(reviewer_id, headers):
    return _default_client.get_reviewer(reviewer_id, headers)


def reviewer_respond(reviewer_id, payload, headers):
    return _default_client.reviewer_respond(reviewer_id, payload, headers)


def reviewer_declare_conflict(reviewer_id, payload, headers):
    return _default_client.reviewer_declare_conflict(reviewer_id, payload, headers)


def create_assignment(payload, headers):
    return _default_client.create_assignment(payload, headers)


def list_assignments(headers, params=None):
    return _default_client.list_assignments(headers, params=params)


def get_assignment(assignment_id, headers):
    return _default_client.get_assignment(assignment_id, headers)


def assignment_respond(assignment_id, payload, headers):
    return _default_client.assignment_respond(assignment_id, payload, headers)


def submit_critique(assignment_id, payload, headers):
    return _default_client.submit_critique(assignment_id, payload, headers)


def create_council_review(payload, headers):
    return _default_client.create_council_review(payload, headers)


def get_jit_request(jit_request_id, headers):
    return _default_client.get_jit_request(jit_request_id, headers)


def submit_jit_items(jit_request_id, payload, headers):
    return _default_client.submit_jit_items(jit_request_id, payload, headers)


def adjudicate_jit_request(jit_request_id, payload, headers):
    return _default_client.adjudicate_jit_request(jit_request_id, payload, headers)


def issue_award(application_id, payload, headers):
    return _default_client.issue_award(application_id, payload, headers)


def list_awards(headers, params=None):
    return _default_client.list_awards(headers, params=params)


def get_award(award_id, headers):
    return _default_client.get_award(award_id, headers)


def create_progress_report(award_id, payload, headers):
    return _default_client.create_progress_report(award_id, payload, headers)


def list_progress_reports(award_id, headers, params=None):
    return _default_client.list_progress_reports(award_id, headers, params=params)


def accept_progress_report(report_id, headers):
    return _default_client.accept_progress_report(report_id, headers)


def create_award_modification(award_id, payload, headers):
    return _default_client.create_award_modification(award_id, payload, headers)


def list_award_modifications(award_id, headers, params=None):
    return _default_client.list_award_modifications(award_id, headers, params=params)


def adjudicate_modification(modification_id, payload, headers):
    return _default_client.adjudicate_modification(modification_id, payload, headers)


def create_transfer_request(award_id, payload, headers):
    return _default_client.create_transfer_request(award_id, payload, headers)


def list_transfer_requests(headers, params=None):
    return _default_client.list_transfer_requests(headers, params=params)


def get_transfer_request(transfer_id, headers):
    return _default_client.get_transfer_request(transfer_id, headers)


def relinquish_transfer(transfer_id, headers):
    return _default_client.relinquish_transfer(transfer_id, headers)


def decide_transfer(transfer_id, payload, headers):
    return _default_client.decide_transfer(transfer_id, payload, headers)
