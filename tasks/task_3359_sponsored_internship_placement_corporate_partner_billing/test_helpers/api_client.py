"""API client: one method per endpoint in the PRD's HTTP contract (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin endpoint-per-method wrapper over the shared request helper."""

    # --- Partners ---------------------------------------------------------
    def create_partner(self, payload, headers):
        return self._request("POST", "/partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/partners/{partner_id}", headers=headers)

    def list_partner_agreements(self, partner_id, headers, params=None):
        return self._request(
            "GET", f"/partners/{partner_id}/agreements", headers=headers, params=params
        )

    # --- Students ---------------------------------------------------------
    def register_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def record_eligibility_decision(self, student_id, payload, headers):
        return self._request(
            "POST", f"/students/{student_id}/eligibility-decisions", payload, headers
        )

    def enroll_student(self, student_id, payload, headers):
        return self._request(
            "POST", f"/students/{student_id}/enrollments", payload, headers
        )

    def list_student_stipends(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/students/{student_id}/stipend-statements", headers=headers, params=params
        )

    def list_student_checkpoints(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/students/{student_id}/outcome-checkpoints", headers=headers, params=params
        )

    def list_student_credit_grants(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/students/{student_id}/credit-grants", headers=headers, params=params
        )

    # --- Cohorts ----------------------------------------------------------
    def create_cohort(self, payload, headers):
        return self._request("POST", "/cohorts", payload, headers)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/cohorts/{cohort_id}", headers=headers)

    def list_cohort_students(self, cohort_id, headers, params=None):
        return self._request(
            "GET", f"/cohorts/{cohort_id}/students", headers=headers, params=params
        )

    # --- Agreements -------------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def activate_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/agreements/{agreement_id}/activations", payload, headers
        )

    # --- Placements -------------------------------------------------------
    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def schedule_interview(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/interviews", payload, headers
        )

    def list_interviews(self, placement_id, headers, params=None):
        return self._request(
            "GET", f"/placements/{placement_id}/interviews", headers=headers, params=params
        )

    def record_interview_outcome(self, interview_id, payload, headers):
        return self._request(
            "POST", f"/interviews/{interview_id}/outcomes", payload, headers
        )

    def extend_offer(self, placement_id, headers, payload=None):
        return self._request(
            "POST", f"/placements/{placement_id}/offers", payload or {}, headers
        )

    def accept_offer(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/acceptance", payload, headers
        )

    def complete_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/completions", payload, headers
        )

    def terminate_placement(self, placement_id, headers, payload=None):
        return self._request(
            "POST", f"/placements/{placement_id}/terminations", payload or {}, headers
        )

    # --- Stipends ---------------------------------------------------------
    def create_stipend_statement(self, payload, headers):
        return self._request("POST", "/stipend-statements", payload, headers)

    def pay_stipend_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", f"/stipend-statements/{statement_id}/payments", payload or {}, headers
        )

    def void_stipend_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", f"/stipend-statements/{statement_id}/voids", payload or {}, headers
        )

    # --- Satisfaction -----------------------------------------------------
    def submit_satisfaction_record(self, payload, headers):
        return self._request("POST", "/satisfaction-records", payload, headers)

    def list_satisfaction_records(self, placement_id, headers, params=None):
        return self._request(
            "GET", f"/placements/{placement_id}/satisfaction-records",
            headers=headers, params=params,
        )

    # --- Invoices ---------------------------------------------------------
    def issue_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    def void_invoice(self, invoice_id, headers, payload=None):
        return self._request(
            "POST", f"/invoices/{invoice_id}/voids", payload or {}, headers
        )

    # --- Outcome checkpoints ---------------------------------------------
    def record_outcome_checkpoint(self, checkpoint_id, payload, headers):
        return self._request(
            "POST", f"/outcome-checkpoints/{checkpoint_id}/records", payload, headers
        )

    # --- Credit grants ----------------------------------------------------
    def create_credit_grant(self, payload, headers):
        return self._request("POST", "/credit-grants", payload, headers)

    def update_credit_grant(self, grant_id, payload, headers):
        return self._request("PATCH", f"/credit-grants/{grant_id}", payload, headers)

    # --- Logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
