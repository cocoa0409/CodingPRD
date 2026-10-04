"""API client: one method per endpoint in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- workers ---------------------------------------------------------
    def register_worker(self, payload, headers=None):
        return self._request("POST", "/api/workers", payload, headers)

    def get_worker(self, worker_id, headers, params=None):
        return self._request("GET", f"/api/workers/{worker_id}", headers=headers, params=params)

    def create_settlement_request(self, worker_id, payload, headers):
        return self._request(
            "POST", f"/api/workers/{worker_id}/settlement-requests", payload, headers
        )

    def list_worker_qualifications(self, worker_id, headers, params=None):
        return self._request(
            "GET", f"/api/workers/{worker_id}/qualifications", headers=headers, params=params
        )

    def worker_qualification_action(self, worker_id, payload, headers):
        return self._request(
            "POST", f"/api/workers/{worker_id}/qualifications", payload, headers
        )

    def list_worker_incidents(self, worker_id, headers, params=None):
        return self._request(
            "GET", f"/api/workers/{worker_id}/incidents", headers=headers, params=params
        )

    def create_incident(self, worker_id, payload, headers):
        return self._request("POST", f"/api/workers/{worker_id}/incidents", payload, headers)

    # --- programs --------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/api/programs", payload, headers)

    def get_program(self, program_id, headers, params=None):
        return self._request("GET", f"/api/programs/{program_id}", headers=headers, params=params)

    def program_state(self, program_id, payload, headers):
        return self._request(
            "POST", f"/api/programs/{program_id}/program-state", payload, headers
        )

    # --- spec units ------------------------------------------------------
    def list_spec_units(self, headers, params=None):
        return self._request("GET", "/api/spec-units", headers=headers, params=params)

    def create_spec_unit(self, payload, headers):
        return self._request("POST", "/api/spec-units", payload, headers)

    def get_spec_unit(self, unit_id, headers):
        return self._request("GET", f"/api/spec-units/{unit_id}", headers=headers)

    def advance_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/api/spec-units/{unit_id}/advance-unit", payload, headers)

    def create_item(self, unit_id, payload, headers):
        return self._request("POST", f"/api/spec-units/{unit_id}/items", payload, headers)

    # --- items -----------------------------------------------------------
    def list_items(self, headers, params=None):
        return self._request("GET", "/api/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/api/items/{item_id}", headers=headers)

    def dispatch_panel(self, item_id, headers, payload=None):
        return self._request(
            "POST", f"/api/items/{item_id}/dispatch-panel", payload or {}, headers
        )

    def reviewer_action(self, item_id, payload, headers):
        return self._request("POST", f"/api/items/{item_id}/reviewer-action", payload, headers)

    def submit_rework(self, item_id, payload, headers):
        return self._request("POST", f"/api/items/{item_id}/submit-rework", payload, headers)

    def list_commits(self, item_id, headers, params=None):
        return self._request("GET", f"/api/items/{item_id}/commits", headers=headers, params=params)

    def list_appeal_cases(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/api/items/{item_id}/appeal-cases", headers=headers, params=params
        )

    # --- commits ---------------------------------------------------------
    def get_commit(self, commit_id, headers):
        return self._request("GET", f"/api/commits/{commit_id}", headers=headers)

    def commit_label(self, commit_id, payload, headers):
        return self._request("POST", f"/api/commits/{commit_id}/commit-label", payload, headers)

    def create_gold_audit(self, commit_id, payload, headers):
        return self._request("POST", f"/api/commits/{commit_id}/gold-audits", payload, headers)

    def grade_gold_audit(self, gold_audit_id, payload, headers):
        return self._request(
            "POST", f"/api/gold-audits/{gold_audit_id}/grade-audit", payload, headers
        )

    def create_payout_record(self, commit_id, payload, headers):
        return self._request("POST", f"/api/commits/{commit_id}/payout-records", payload, headers)

    # --- appeals ---------------------------------------------------------
    def file_appeal(self, payload, headers):
        return self._request("POST", "/api/appeal-cases", payload, headers)

    def advance_appeal(self, case_id, payload, headers):
        return self._request("POST", f"/api/appeal-cases/{case_id}/advance-appeal", payload, headers)

    def concur_appeal(self, case_id, payload, headers):
        return self._request("POST", f"/api/appeal-cases/{case_id}/concur", payload, headers)

    # --- clock -----------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


api_client = ApiClient()