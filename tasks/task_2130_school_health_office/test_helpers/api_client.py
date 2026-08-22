"""API client: one method per endpoint declared by the School Health Office API."""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/health-office"


class ApiClient(GenericApiClient):
    # ---- Buildings -------------------------------------------------------
    def create_school(self, payload, headers=None):
        return self._request("POST", f"{BASE}/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"{BASE}/schools/{school_id}", headers=headers)

    # ---- Nurses ----------------------------------------------------------
    def create_nurse(self, payload, headers):
        return self._request("POST", f"{BASE}/nurses", payload, headers)

    def get_nurse(self, nurse_id, headers):
        return self._request("GET", f"{BASE}/nurses/{nurse_id}", headers=headers)

    def patch_nurse(self, nurse_id, payload, headers):
        return self._request("PATCH", f"{BASE}/nurses/{nurse_id}", payload, headers)

    # ---- Coverage blocks -------------------------------------------------
    def create_coverage_assignment(self, payload, headers):
        return self._request("POST", f"{BASE}/coverage-assignments", payload, headers)

    def list_coverage_assignments(self, headers, params=None):
        return self._request("GET", f"{BASE}/coverage-assignments", headers=headers, params=params)

    def get_coverage_assignment(self, coverage_id, headers):
        return self._request("GET", f"{BASE}/coverage-assignments/{coverage_id}", headers=headers)

    def end_coverage_assignment(self, coverage_id, payload, headers):
        return self._request("POST", f"{BASE}/coverage-assignments/{coverage_id}/end", payload, headers)

    # ---- Students --------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", f"{BASE}/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"{BASE}/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", f"{BASE}/students", headers=headers, params=params)

    def patch_student(self, student_id, payload, headers):
        return self._request("PATCH", f"{BASE}/students/{student_id}", payload, headers)

    # ---- Action plans ----------------------------------------------------
    def create_action_plan(self, payload, headers):
        return self._request("POST", f"{BASE}/action-plans", payload, headers)

    def get_action_plan(self, plan_id, headers):
        return self._request("GET", f"{BASE}/action-plans/{plan_id}", headers=headers)

    def list_action_plans(self, headers, params=None):
        return self._request("GET", f"{BASE}/action-plans", headers=headers, params=params)

    def submit_action_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"{BASE}/action-plans/{plan_id}/submit", payload or {}, headers)

    def guardian_consent_action_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"{BASE}/action-plans/{plan_id}/guardian-consent", payload or {}, headers)

    def decide_action_plan(self, plan_id, payload, headers):
        return self._request("POST", f"{BASE}/action-plans/{plan_id}/decision", payload, headers)

    def revoke_action_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"{BASE}/action-plans/{plan_id}/revoke", payload or {}, headers)

    # ---- Medication orders ----------------------------------------------
    def create_medication_authorization(self, payload, headers):
        return self._request("POST", f"{BASE}/medication-authorizations", payload, headers)

    def get_medication_authorization(self, auth_id, headers):
        return self._request("GET", f"{BASE}/medication-authorizations/{auth_id}", headers=headers)

    def list_medication_authorizations(self, headers, params=None):
        return self._request("GET", f"{BASE}/medication-authorizations", headers=headers, params=params)

    def consent_medication_authorization(self, auth_id, payload, headers):
        return self._request("POST", f"{BASE}/medication-authorizations/{auth_id}/consent", payload, headers)

    def clinical_review_medication_authorization(self, auth_id, payload, headers):
        return self._request("POST", f"{BASE}/medication-authorizations/{auth_id}/clinical-review", payload, headers)

    # ---- Stock lots ------------------------------------------------------
    def create_stock_lot(self, payload, headers):
        return self._request("POST", f"{BASE}/medication-stock-lots", payload, headers)

    def get_stock_lot(self, lot_id, headers):
        return self._request("GET", f"{BASE}/medication-stock-lots/{lot_id}", headers=headers)

    def list_stock_lots(self, headers, params=None):
        return self._request("GET", f"{BASE}/medication-stock-lots", headers=headers, params=params)

    def lot_inventory_action(self, lot_id, payload, headers):
        return self._request("POST", f"{BASE}/medication-stock-lots/{lot_id}/inventory-action", payload, headers)

    # ---- Encounters ------------------------------------------------------
    def create_health_visit(self, payload, headers):
        return self._request("POST", f"{BASE}/health-visits", payload, headers)

    def get_health_visit(self, visit_id, headers):
        return self._request("GET", f"{BASE}/health-visits/{visit_id}", headers=headers)

    def list_health_visits(self, headers, params=None):
        return self._request("GET", f"{BASE}/health-visits", headers=headers, params=params)

    def assess_health_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{BASE}/health-visits/{visit_id}/assess", payload, headers)

    def dispose_health_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{BASE}/health-visits/{visit_id}/dispose", payload, headers)

    def close_health_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"{BASE}/health-visits/{visit_id}/close", payload or {}, headers)

    def reopen_health_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"{BASE}/health-visits/{visit_id}/reopen", payload or {}, headers)

    # ---- Administration records -----------------------------------------
    def create_administration_record(self, payload, headers):
        return self._request("POST", f"{BASE}/administration-records", payload, headers)

    def create_stock_emergency_record(self, payload, headers):
        return self._request("POST", f"{BASE}/administration-records/stock-emergency", payload, headers)

    def get_administration_record(self, record_id, headers):
        return self._request("GET", f"{BASE}/administration-records/{record_id}", headers=headers)

    def list_administration_records(self, headers, params=None):
        return self._request("GET", f"{BASE}/administration-records", headers=headers, params=params)

    def record_administration_outcome(self, record_id, payload, headers):
        return self._request("POST", f"{BASE}/administration-records/{record_id}/outcome", payload, headers)

    def void_administration_record(self, record_id, payload, headers):
        return self._request("POST", f"{BASE}/administration-records/{record_id}/void", payload, headers)

    # ---- Screenings ------------------------------------------------------
    def create_screening(self, payload, headers):
        return self._request("POST", f"{BASE}/screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"{BASE}/screenings/{screening_id}", headers=headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", f"{BASE}/screenings", headers=headers, params=params)

    def record_screening_result(self, screening_id, payload, headers):
        return self._request("POST", f"{BASE}/screenings/{screening_id}/record-result", payload, headers)

    def screening_follow_up(self, screening_id, payload, headers):
        return self._request("POST", f"{BASE}/screenings/{screening_id}/follow-up", payload, headers)

    # ---- Disclosure requests --------------------------------------------
    def create_disclosure_request(self, payload, headers):
        return self._request("POST", f"{BASE}/disclosure-requests", payload, headers)

    def get_disclosure_request(self, request_id, headers):
        return self._request("GET", f"{BASE}/disclosure-requests/{request_id}", headers=headers)

    def list_disclosure_requests(self, headers, params=None):
        return self._request("GET", f"{BASE}/disclosure-requests", headers=headers, params=params)

    def submit_disclosure_request(self, request_id, headers, payload=None):
        return self._request("POST", f"{BASE}/disclosure-requests/{request_id}/submit", payload or {}, headers)

    def guardian_consent_disclosure_request(self, request_id, payload, headers):
        return self._request("POST", f"{BASE}/disclosure-requests/{request_id}/guardian-consent", payload, headers)

    def decide_disclosure_request(self, request_id, payload, headers):
        return self._request("POST", f"{BASE}/disclosure-requests/{request_id}/decide", payload, headers)

    def release_disclosure_request(self, request_id, headers, payload=None):
        return self._request("POST", f"{BASE}/disclosure-requests/{request_id}/release", payload or {}, headers)

    # ---- Clock and operations -------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    def run_daily_checkpoint(self, payload, headers):
        return self._request("POST", f"{BASE}/_ops/run-daily-checkpoint", payload or {}, headers)


api_client = ApiClient()
