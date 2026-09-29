"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Jurisdictions ----------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/jurisdictions", headers=headers, params=params)

    def apply_law_change(self, jurisdiction_id, payload, headers):
        return self._request(
            "POST", f"/jurisdictions/{jurisdiction_id}/law-changes", payload, headers
        )

    # ---------------- Merchants ----------------
    def create_merchant(self, payload, headers):
        return self._request("POST", "/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/merchants/{merchant_id}", headers=headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/merchants", headers=headers, params=params)

    # ---------------- Cost documentation ----------------
    def create_cost_documentation(self, merchant_id, payload, headers):
        return self._request(
            "POST", f"/merchants/{merchant_id}/cost-documentations", payload, headers
        )

    def get_cost_documentation(self, cost_documentation_id, headers):
        return self._request(
            "GET", f"/cost-documentations/{cost_documentation_id}", headers=headers
        )

    def list_cost_documentations(self, headers, params=None):
        return self._request("GET", "/cost-documentations", headers=headers, params=params)

    # ---------------- Programs ----------------
    def create_program(self, payload, headers):
        return self._request("POST", "/surcharge-programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/surcharge-programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/surcharge-programs", headers=headers, params=params)

    def patch_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/surcharge-programs/{program_id}", payload, headers)

    def activate_program(self, program_id, headers, payload=None):
        return self._request(
            "POST", f"/surcharge-programs/{program_id}/activate", payload or {}, headers
        )

    def program_status_action(self, program_id, payload, headers):
        return self._request(
            "POST", f"/surcharge-programs/{program_id}/status-actions", payload, headers
        )

    def get_exposure_summary(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/surcharge-programs/{program_id}/exposure-summary",
            headers=headers,
            params=params,
        )

    def get_settlement_summary(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/surcharge-programs/{program_id}/settlement-summary",
            headers=headers,
            params=params,
        )

    # ---------------- Rate rules ----------------
    def create_rate_rule(self, program_id, payload, headers):
        return self._request(
            "POST", f"/surcharge-programs/{program_id}/rate-rules", payload, headers
        )

    def get_rate_rule(self, rate_rule_id, headers):
        return self._request("GET", f"/brand-rate-rules/{rate_rule_id}", headers=headers)

    def list_rate_rules(self, headers, params=None):
        return self._request("GET", "/brand-rate-rules", headers=headers, params=params)

    # ---------------- Network registrations ----------------
    def create_network_registration(self, program_id, payload, headers):
        return self._request(
            "POST", f"/surcharge-programs/{program_id}/network-registrations", payload, headers
        )

    def get_network_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/network-registrations/{registration_id}", headers=headers
        )

    def list_network_registrations(self, headers, params=None):
        return self._request("GET", "/network-registrations", headers=headers, params=params)

    def decide_network_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/network-registrations/{registration_id}/decision", payload, headers
        )

    def effectuate_network_registration(self, registration_id, headers, payload=None):
        return self._request(
            "POST",
            f"/network-registrations/{registration_id}/effectuate",
            payload or {},
            headers,
        )

    # ---------------- Disclosure artifacts ----------------
    def create_disclosure_artifact(self, program_id, payload, headers):
        return self._request(
            "POST", f"/surcharge-programs/{program_id}/disclosure-artifacts", payload, headers
        )

    def attest_disclosure_artifact(self, artifact_id, payload, headers):
        return self._request(
            "POST", f"/disclosure-artifacts/{artifact_id}/attest", payload, headers
        )

    def get_disclosure_artifact(self, artifact_id, headers):
        return self._request("GET", f"/disclosure-artifacts/{artifact_id}", headers=headers)

    def list_disclosure_artifacts(self, headers, params=None):
        return self._request("GET", "/disclosure-artifacts", headers=headers, params=params)

    # ---------------- Terminals ----------------
    def create_terminal(self, merchant_id, payload, headers):
        return self._request("POST", f"/merchants/{merchant_id}/terminals", payload, headers)

    def configure_terminal(self, terminal_id, payload, headers):
        return self._request("POST", f"/terminals/{terminal_id}/configure", payload, headers)

    def terminal_state_action(self, terminal_id, payload, headers):
        return self._request(
            "POST", f"/terminals/{terminal_id}/state-actions", payload, headers
        )

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/terminals/{terminal_id}", headers=headers)

    def list_terminals(self, headers, params=None):
        return self._request("GET", "/terminals", headers=headers, params=params)

    # ---------------- Transactions ----------------
    def create_transaction(self, payload, headers):
        return self._request("POST", "/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    # ---------------- Complaint cases ----------------
    def create_complaint_case(self, payload, headers):
        return self._request("POST", "/complaint-cases", payload, headers)

    def complaint_investigation_action(self, complaint_case_id, payload, headers):
        return self._request(
            "POST", f"/complaint-cases/{complaint_case_id}/investigation-actions", payload, headers
        )

    def complaint_remediation_action(self, complaint_case_id, payload, headers):
        return self._request(
            "POST", f"/complaint-cases/{complaint_case_id}/remediation-actions", payload, headers
        )

    def get_complaint_case(self, complaint_case_id, headers):
        return self._request("GET", f"/complaint-cases/{complaint_case_id}", headers=headers)

    def list_complaint_cases(self, headers, params=None):
        return self._request("GET", "/complaint-cases", headers=headers, params=params)

    # ---------------- Remediation refunds ----------------
    def create_refund(self, complaint_case_id, payload, headers):
        return self._request(
            "POST", f"/complaint-cases/{complaint_case_id}/refunds", payload, headers
        )

    def issue_refund(self, refund_id, headers, payload=None):
        return self._request(
            "POST", f"/remediation-refunds/{refund_id}/issue", payload or {}, headers
        )

    def void_refund(self, refund_id, payload, headers):
        return self._request(
            "POST", f"/remediation-refunds/{refund_id}/void", payload, headers
        )

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/remediation-refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/remediation-refunds", headers=headers, params=params)

    # ---------------- Logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
