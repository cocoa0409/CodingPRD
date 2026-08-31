"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ---- Literary properties & chain of title ----------------------------
    def create_literary_property(self, payload, headers):
        return self._request("POST", "/literary-properties", payload, headers)

    def get_literary_property(self, property_id, headers):
        return self._request(
            "GET", f"/literary-properties/{property_id}", headers=headers
        )

    def list_literary_properties(self, headers, params=None):
        return self._request("GET", "/literary-properties", params, headers)

    def file_rights_document(self, property_id, payload, headers):
        return self._request(
            "POST", f"/literary-properties/{property_id}/rights-documents",
            payload, headers,
        )

    def list_property_rights_documents(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/literary-properties/{property_id}/rights-documents",
            params, headers,
        )

    def get_rights_chain_document(self, document_id, headers):
        return self._request(
            "GET", f"/rights-chain-documents/{document_id}", headers=headers
        )

    def list_rights_chain_documents(self, headers, params=None):
        return self._request("GET", "/rights-chain-documents", params, headers)

    # ---- Submissions & release forms -------------------------------------
    def create_submission(self, payload, headers):
        return self._request("POST", "/submissions", payload, headers)

    def get_submission(self, submission_id, headers):
        return self._request("GET", f"/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/submissions", params, headers)

    def create_release_form(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/submissions/{submission_id}/release-forms", payload, headers
        )

    def list_submission_release_forms(self, submission_id, headers, params=None):
        return self._request(
            "GET", f"/submissions/{submission_id}/release-forms", params, headers
        )

    def get_release_form(self, release_form_id, headers):
        return self._request(
            "GET", f"/release-forms/{release_form_id}", headers=headers
        )

    def send_release_form(self, release_form_id, headers):
        return self._request(
            "POST", f"/release-forms/{release_form_id}/send", {}, headers
        )

    def execute_release_form(self, release_form_id, payload, headers):
        return self._request(
            "POST", f"/release-forms/{release_form_id}/execute", payload, headers
        )

    def waive_release_form(self, release_form_id, payload, headers):
        return self._request(
            "POST", f"/release-forms/{release_form_id}/waive", payload, headers
        )

    def clear_intake(self, submission_id, headers):
        return self._request(
            "POST", f"/submissions/{submission_id}/clear-intake", {}, headers
        )

    def withdraw_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/submissions/{submission_id}/withdraw", payload, headers
        )

    # ---- Readers, assignments, coverage reports --------------------------
    def create_reader(self, payload, headers):
        return self._request("POST", "/readers", payload, headers)

    def get_reader(self, reader_id, headers):
        return self._request("GET", f"/readers/{reader_id}", headers=headers)

    def list_readers(self, headers, params=None):
        return self._request("GET", "/readers", params, headers)

    def patch_reader(self, reader_id, payload, headers):
        return self._request("PATCH", f"/readers/{reader_id}", payload, headers)

    def assign_reader(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/submissions/{submission_id}/assign-reader", payload, headers
        )

    def get_coverage_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/coverage-assignments/{assignment_id}", headers=headers
        )

    def list_coverage_assignments(self, headers, params=None):
        return self._request("GET", "/coverage-assignments", params, headers)

    def start_coverage_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/coverage-assignments/{assignment_id}/start", {}, headers
        )

    def recall_coverage_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/coverage-assignments/{assignment_id}/recall", payload, headers
        )

    def get_coverage_report(self, report_id, headers):
        return self._request("GET", f"/coverage-reports/{report_id}", headers=headers)

    def list_coverage_reports(self, headers, params=None):
        return self._request("GET", "/coverage-reports", params, headers)

    def patch_coverage_report(self, report_id, payload, headers):
        return self._request(
            "PATCH", f"/coverage-reports/{report_id}", payload, headers
        )

    def submit_coverage_report(self, report_id, headers):
        return self._request(
            "POST", f"/coverage-reports/{report_id}/submit", {}, headers
        )

    def request_report_revision(self, report_id, payload, headers):
        return self._request(
            "POST", f"/coverage-reports/{report_id}/request-revision", payload, headers
        )

    def approve_coverage_report(self, report_id, headers):
        return self._request(
            "POST", f"/coverage-reports/{report_id}/approve", {}, headers
        )

    def reject_coverage_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/coverage-reports/{report_id}/reject", payload, headers
        )

    # ---- Tracking board ---------------------------------------------------
    def get_tracking_board_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/tracking-board-entries/{entry_id}", headers=headers
        )

    def list_tracking_board_entries(self, headers, params=None):
        return self._request("GET", "/tracking-board-entries", params, headers)

    # ---- Option agreements -------------------------------------------------
    def create_option_agreement(self, payload, headers):
        return self._request("POST", "/option-agreements", payload, headers)

    def get_option_agreement(self, option_id, headers):
        return self._request("GET", f"/option-agreements/{option_id}", headers=headers)

    def list_option_agreements(self, headers, params=None):
        return self._request("GET", "/option-agreements", params, headers)

    def execute_option(self, option_id, headers):
        return self._request(
            "POST", f"/option-agreements/{option_id}/execute", {}, headers
        )

    def extend_option(self, option_id, headers):
        return self._request(
            "POST", f"/option-agreements/{option_id}/extend", {}, headers
        )

    def exercise_option(self, option_id, headers):
        return self._request(
            "POST", f"/option-agreements/{option_id}/exercise", {}, headers
        )

    def lapse_option(self, option_id, headers):
        return self._request(
            "POST", f"/option-agreements/{option_id}/lapse", {}, headers
        )

    def terminate_option(self, option_id, payload, headers):
        return self._request(
            "POST", f"/option-agreements/{option_id}/terminate", payload, headers
        )

    # ---- Development projects ---------------------------------------------
    def create_development_project(self, payload, headers):
        return self._request("POST", "/development-projects", payload, headers)

    def get_development_project(self, project_id, headers):
        return self._request(
            "GET", f"/development-projects/{project_id}", headers=headers
        )

    def list_development_projects(self, headers, params=None):
        return self._request("GET", "/development-projects", params, headers)

    def place_in_turnaround(self, project_id, payload, headers):
        return self._request(
            "POST", f"/development-projects/{project_id}/place-in-turnaround",
            payload, headers,
        )

    def serve_reversion_notice(self, project_id, headers):
        return self._request(
            "POST", f"/development-projects/{project_id}/reversion-notice", {}, headers
        )

    # ---- Writers, engagements, milestones ----------------------------------
    def create_writer(self, payload, headers):
        return self._request("POST", "/writers", payload, headers)

    def get_writer(self, writer_id, headers):
        return self._request("GET", f"/writers/{writer_id}", headers=headers)

    def list_writers(self, headers, params=None):
        return self._request("GET", "/writers", params, headers)

    def create_writer_engagement(self, payload, headers):
        return self._request("POST", "/writer-engagements", payload, headers)

    def get_writer_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"/writer-engagements/{engagement_id}", headers=headers
        )

    def list_writer_engagements(self, headers, params=None):
        return self._request("GET", "/writer-engagements", params, headers)

    def attach_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/writer-engagements/{engagement_id}/attach", {}, headers
        )

    def deliver_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/writer-engagements/{engagement_id}/deliver", payload, headers
        )

    def complete_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/writer-engagements/{engagement_id}/complete", {}, headers
        )

    def terminate_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/writer-engagements/{engagement_id}/terminate", payload, headers
        )

    def get_milestone_payment(self, milestone_id, headers):
        return self._request(
            "GET", f"/milestone-payments/{milestone_id}", headers=headers
        )

    def list_milestone_payments(self, headers, params=None):
        return self._request("GET", "/milestone-payments", params, headers)

    def approve_milestone_payment(self, milestone_id, headers):
        return self._request(
            "POST", f"/milestone-payments/{milestone_id}/approve", {}, headers
        )

    def pay_milestone_payment(self, milestone_id, headers):
        return self._request(
            "POST", f"/milestone-payments/{milestone_id}/pay", {}, headers
        )

    # ---- Greenlight committee ----------------------------------------------
    def create_committee_member(self, payload, headers):
        return self._request("POST", "/committee-members", payload, headers)

    def get_committee_member(self, member_id, headers):
        return self._request(
            "GET", f"/committee-members/{member_id}", headers=headers
        )

    def list_committee_members(self, headers, params=None):
        return self._request("GET", "/committee-members", params, headers)

    def patch_committee_member(self, member_id, payload, headers):
        return self._request(
            "PATCH", f"/committee-members/{member_id}", payload, headers
        )

    def list_member_votes(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/committee-members/{member_id}/votes", params, headers
        )

    def create_greenlight_review(self, payload, headers):
        return self._request("POST", "/greenlight-reviews", payload, headers)

    def get_greenlight_review(self, review_id, headers):
        return self._request(
            "GET", f"/greenlight-reviews/{review_id}", headers=headers
        )

    def list_greenlight_reviews(self, headers, params=None):
        return self._request("GET", "/greenlight-reviews", params, headers)

    def open_voting(self, review_id, headers):
        return self._request(
            "POST", f"/greenlight-reviews/{review_id}/open-voting", {}, headers
        )

    def cast_vote(self, review_id, payload, headers):
        return self._request(
            "POST", f"/greenlight-reviews/{review_id}/votes", payload, headers
        )

    def list_review_votes(self, review_id, headers, params=None):
        return self._request(
            "GET", f"/greenlight-reviews/{review_id}/votes", params, headers
        )

    def close_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/greenlight-reviews/{review_id}/close", payload, headers
        )

    def withdraw_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/greenlight-reviews/{review_id}/withdraw", payload, headers
        )


api_client = ApiClient()
