"""API client: one method per endpoint defined in the PRD.

Every endpoint is mounted under the `/rtw` prefix, with the sole exception of
the logical-clock control endpoint.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/rtw"


class ApiClient(GenericApiClient):
    # ── Employees & claims ────────────────────────────────────────────────

    def create_employee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"{PREFIX}/employees/{employee_id}", headers=headers)

    def create_claim(self, employee_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/employees/{employee_id}/claims", payload, headers
        )

    def list_employee_claims(self, employee_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/employees/{employee_id}/claims", headers=headers, params=params
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def set_adjuster_authorization(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/adjuster-authorization", payload, headers
        )

    # ── Treating providers ────────────────────────────────────────────────

    def create_treating_provider(self, payload, headers):
        return self._request("POST", f"{PREFIX}/treating-providers", payload, headers)

    def get_treating_provider(self, provider_id, headers):
        return self._request(
            "GET", f"{PREFIX}/treating-providers/{provider_id}", headers=headers
        )

    def update_treating_provider(self, provider_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/treating-providers/{provider_id}", payload, headers
        )

    # ── Restriction intake ────────────────────────────────────────────────

    def create_restriction_set(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/restriction-sets", payload, headers
        )

    def list_claim_restriction_sets(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/restriction-sets", headers=headers, params=params
        )

    def get_restriction_set(self, restriction_set_id, headers):
        return self._request(
            "GET", f"{PREFIX}/restriction-sets/{restriction_set_id}", headers=headers
        )

    def list_restriction_sets(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/restriction-sets", headers=headers, params=params
        )

    def submit_restriction_set(self, restriction_set_id, headers):
        return self._request(
            "POST", f"{PREFIX}/restriction-sets/{restriction_set_id}/submit", {}, headers
        )

    def request_restriction_set_clarification(self, restriction_set_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/restriction-sets/{restriction_set_id}/request-clarification",
            payload,
            headers,
        )

    def verify_restriction_set(self, restriction_set_id, headers):
        return self._request(
            "POST", f"{PREFIX}/restriction-sets/{restriction_set_id}/verify", {}, headers
        )

    def activate_restriction_set(self, restriction_set_id, headers):
        return self._request(
            "POST", f"{PREFIX}/restriction-sets/{restriction_set_id}/activate", {}, headers
        )

    # ── Supervisors & training ────────────────────────────────────────────

    def create_supervisor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/supervisors", payload, headers)

    def get_supervisor(self, supervisor_id, headers):
        return self._request("GET", f"{PREFIX}/supervisors/{supervisor_id}", headers=headers)

    def create_training_record(self, supervisor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/supervisors/{supervisor_id}/training-records", payload, headers
        )

    def list_supervisor_training_records(self, supervisor_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/supervisors/{supervisor_id}/training-records",
            headers=headers,
            params=params,
        )

    def get_training_record(self, training_record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/training-records/{training_record_id}", headers=headers
        )

    def renew_training_record(self, training_record_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/training-records/{training_record_id}/renew", payload, headers
        )

    # ── Transitional job bank ─────────────────────────────────────────────

    def create_transitional_job(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transitional-jobs", payload, headers)

    def get_transitional_job(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/transitional-jobs/{job_id}", headers=headers)

    def list_transitional_jobs(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/transitional-jobs", headers=headers, params=params
        )

    def update_transitional_job(self, job_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/transitional-jobs/{job_id}", payload, headers
        )

    # ── Placements ────────────────────────────────────────────────────────

    def create_placement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/placements", payload, headers)

    def auto_match_placement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/placements/auto-match", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"{PREFIX}/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/placements", headers=headers, params=params)

    def list_claim_placements(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/placements", headers=headers, params=params
        )

    def submit_placement_to_adjuster(self, placement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/submit-to-adjuster", {}, headers
        )

    def list_placement_directives(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/placements/{placement_id}/adjuster-directives",
            headers=headers,
            params=params,
        )

    def decide_adjuster_directive(self, directive_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/adjuster-directives/{directive_id}/decide", payload, headers
        )

    def activate_placement(self, placement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/activate", {}, headers
        )

    def suspend_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/suspend", payload, headers
        )

    def resume_placement(self, placement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/resume", {}, headers
        )

    def extend_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/extend", payload, headers
        )

    def complete_placement(self, placement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/complete", {}, headers
        )

    def terminate_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/terminate", payload, headers
        )

    def log_placement_hours(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/hours-log", payload, headers
        )

    # ── Progression reviews ───────────────────────────────────────────────

    def list_placement_progression_reviews(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/placements/{placement_id}/progression-reviews",
            headers=headers,
            params=params,
        )

    def get_progression_review(self, review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/progression-reviews/{review_id}", headers=headers
        )

    def open_progression_review(self, review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/progression-reviews/{review_id}/open", {}, headers
        )

    def decide_progression_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/progression-reviews/{review_id}/decide", payload, headers
        )

    # ── Compliance monitoring ─────────────────────────────────────────────

    def create_compliance_audit(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/compliance-audits", payload, headers
        )

    def list_compliance_audits(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/placements/{placement_id}/compliance-audits",
            headers=headers,
            params=params,
        )

    # ── Reinjury reporting ────────────────────────────────────────────────

    def create_reinjury_report(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/reinjury-reports", payload, headers
        )

    def list_reinjury_reports(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/placements/{placement_id}/reinjury-reports",
            headers=headers,
            params=params,
        )

    def triage_reinjury_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/reinjury-reports/{report_id}/triage", payload, headers
        )

    # ── Case-review panel ─────────────────────────────────────────────────

    def create_case_review(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/placements/{placement_id}/case-reviews", payload, headers
        )

    def list_placement_case_reviews(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/placements/{placement_id}/case-reviews",
            headers=headers,
            params=params,
        )

    def get_case_review(self, case_review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/case-reviews/{case_review_id}", headers=headers
        )

    def open_case_review_voting(self, case_review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/case-reviews/{case_review_id}/open-voting", {}, headers
        )

    def cast_case_review_vote(self, case_review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/case-reviews/{case_review_id}/votes", payload, headers
        )

    def list_case_review_votes(self, case_review_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/case-reviews/{case_review_id}/votes", headers=headers, params=params
        )

    def close_case_review(self, case_review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/case-reviews/{case_review_id}/close", {}, headers
        )

    # ── Wage-differential ledger ──────────────────────────────────────────

    def create_wage_entry(self, placement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/placements/{placement_id}/wage-differential-entries",
            payload,
            headers,
        )

    def list_wage_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/wage-differential-entries", headers=headers, params=params
        )

    def get_wage_entry(self, entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/wage-differential-entries/{entry_id}", headers=headers
        )

    def reverse_wage_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wage-differential-entries/{entry_id}/reverse", payload, headers
        )

    # ── Program metrics ───────────────────────────────────────────────────

    def get_program_metrics(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/programs/metrics", headers=headers, params=params
        )

    # ── Logical clock ─────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
