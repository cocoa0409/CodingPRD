"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Dealers ──────────────────────────────────────
    def create_dealer(self, payload, headers):
        return self._request("POST", "/alarm-funding/dealers", payload, headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/alarm-funding/dealers", headers=headers, params=params)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/alarm-funding/dealers/{dealer_id}", headers=headers)

    def recompute_dealer_chargeback_rate(self, dealer_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/dealers/{dealer_id}/chargeback-rate-recompute",
            payload, headers,
        )

    def suspend_dealer(self, dealer_id, headers):
        return self._request("POST", f"/alarm-funding/dealers/{dealer_id}/suspend", None, headers)

    def reinstate_dealer(self, dealer_id, headers):
        return self._request("POST", f"/alarm-funding/dealers/{dealer_id}/reinstate", None, headers)

    def release_holdback(self, dealer_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/dealers/{dealer_id}/holdback-releases", payload, headers,
        )

    def reverse_holdback(self, dealer_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/dealers/{dealer_id}/holdback-reversals", payload, headers,
        )

    # ─── Dealer packages ──────────────────────────────
    def create_package(self, payload, headers):
        return self._request("POST", "/alarm-funding/dealer-packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request(
            "GET", "/alarm-funding/dealer-packages", headers=headers, params=params,
        )

    def get_package(self, package_id, headers):
        return self._request(
            "GET", f"/alarm-funding/dealer-packages/{package_id}", headers=headers,
        )

    def submit_package(self, package_id, headers):
        return self._request(
            "POST", f"/alarm-funding/dealer-packages/{package_id}/submit", None, headers,
        )

    def withdraw_package(self, package_id, headers):
        return self._request(
            "POST", f"/alarm-funding/dealer-packages/{package_id}/withdraw", None, headers,
        )

    def approve_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/dealer-packages/{package_id}/approve", payload, headers,
        )

    def reopen_package(self, package_id, headers):
        return self._request(
            "POST", f"/alarm-funding/dealer-packages/{package_id}/reopen", None, headers,
        )

    def fund_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/dealer-packages/{package_id}/fund", payload, headers,
        )

    def decline_package(self, package_id, headers):
        return self._request(
            "POST", f"/alarm-funding/dealer-packages/{package_id}/decline", None, headers,
        )

    def declare_contract(self, package_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/dealer-packages/{package_id}/contracts", payload, headers,
        )

    # ─── Contracts ────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/alarm-funding/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/alarm-funding/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/alarm-funding/contracts/{contract_id}", headers=headers)

    def fund_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/contracts/{contract_id}/fund", payload, headers,
        )

    def cancel_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/alarm-funding/contracts/{contract_id}/cancel", None, headers,
        )

    def adjudicate_chargeback(self, contract_id, headers):
        return self._request(
            "POST", f"/alarm-funding/contracts/{contract_id}/chargeback", None, headers,
        )

    def reactivate_service(self, contract_id, headers):
        return self._request(
            "POST", f"/alarm-funding/contracts/{contract_id}/reactivate-service", None, headers,
        )

    def get_chargeback_preview(self, contract_id, headers):
        return self._request(
            "GET", f"/alarm-funding/contracts/{contract_id}/chargeback-preview", headers=headers,
        )

    def get_contract_false_alarm_ratio(self, contract_id, headers):
        return self._request(
            "GET", f"/alarm-funding/contracts/{contract_id}/false-alarm-ratio", headers=headers,
        )

    def list_contract_sites(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/alarm-funding/contracts/{contract_id}/sites",
            headers=headers, params=params,
        )

    def list_contract_attrition_flags(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/alarm-funding/contracts/{contract_id}/attrition-flags",
            headers=headers, params=params,
        )

    def list_contract_owners(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/alarm-funding/contracts/{contract_id}/owners",
            headers=headers, params=params,
        )

    # ─── Customers ────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/alarm-funding/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/alarm-funding/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/alarm-funding/customers/{customer_id}", headers=headers)

    def list_customer_contract_owners(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/alarm-funding/customers/{customer_id}/contract-owners",
            headers=headers, params=params,
        )

    def list_customer_assumption_requests(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/alarm-funding/customers/{customer_id}/assumption-requests",
            headers=headers, params=params,
        )

    # ─── Installations ────────────────────────────────
    def create_installation(self, payload, headers):
        return self._request("POST", "/alarm-funding/installations", payload, headers)

    def list_installations(self, headers, params=None):
        return self._request("GET", "/alarm-funding/installations", headers=headers, params=params)

    def get_installation(self, installation_id, headers):
        return self._request(
            "GET", f"/alarm-funding/installations/{installation_id}", headers=headers,
        )

    def complete_installation(self, installation_id, headers):
        return self._request(
            "POST", f"/alarm-funding/installations/{installation_id}/complete", None, headers,
        )

    def mark_installation_failed(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/installations/{installation_id}/mark-failed",
            payload, headers,
        )

    def request_installation_waiver(self, installation_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/installations/{installation_id}/waiver", payload, headers,
        )

    # ─── Monitoring ───────────────────────────────────
    def list_monitoring_accounts(self, headers, params=None):
        return self._request(
            "GET", "/alarm-funding/monitoring-accounts", headers=headers, params=params,
        )

    def get_monitoring_account(self, account_id, headers):
        return self._request(
            "GET", f"/alarm-funding/monitoring-accounts/{account_id}", headers=headers,
        )

    def get_account_false_alarm_ratio(self, account_id, headers):
        return self._request(
            "GET", f"/alarm-funding/monitoring-accounts/{account_id}/false-alarm-ratio",
            headers=headers,
        )

    def trigger_monitoring_transfer(self, account_id, headers):
        return self._request(
            "POST", f"/alarm-funding/monitoring-transfers/{account_id}/trigger", None, headers,
        )

    # ─── Alarm events ─────────────────────────────────
    def create_alarm_event(self, payload, headers):
        return self._request("POST", "/alarm-funding/alarm-events", payload, headers)

    def list_alarm_events(self, headers, params=None):
        return self._request("GET", "/alarm-funding/alarm-events", headers=headers, params=params)

    def get_alarm_event(self, alarm_id, headers):
        return self._request("GET", f"/alarm-funding/alarm-events/{alarm_id}", headers=headers)

    def verify_alarm_event(self, alarm_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/alarm-events/{alarm_id}/verification", payload, headers,
        )

    def place_alarm_legal_hold(self, alarm_id, headers):
        return self._request(
            "POST", f"/alarm-funding/alarm-events/{alarm_id}/legal-hold", None, headers,
        )

    def release_alarm_legal_hold(self, alarm_id, headers):
        return self._request(
            "POST", f"/alarm-funding/alarm-events/{alarm_id}/legal-hold-release", None, headers,
        )

    # ─── Dispatch ─────────────────────────────────────
    def create_dispatch_request(self, payload, headers):
        return self._request("POST", "/alarm-funding/dispatch-requests", payload, headers)

    def list_dispatch_requests(self, headers, params=None):
        return self._request(
            "GET", "/alarm-funding/dispatch-requests", headers=headers, params=params,
        )

    def get_dispatch_request(self, dispatch_id, headers):
        return self._request(
            "GET", f"/alarm-funding/dispatch-requests/{dispatch_id}", headers=headers,
        )

    def dispatch_request(self, dispatch_id, headers):
        return self._request(
            "POST", f"/alarm-funding/dispatch-requests/{dispatch_id}/dispatch", None, headers,
        )

    def abort_dispatch(self, dispatch_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/dispatch-requests/{dispatch_id}/abort", payload, headers,
        )

    def complete_dispatch(self, dispatch_id, headers):
        return self._request(
            "POST", f"/alarm-funding/dispatch-requests/{dispatch_id}/complete", None, headers,
        )

    # ─── Alarm reduction actions ──────────────────────
    def create_reduction_action(self, payload, headers):
        return self._request("POST", "/alarm-funding/alarm-reduction-actions", payload, headers)

    def list_reduction_actions(self, headers, params=None):
        return self._request(
            "GET", "/alarm-funding/alarm-reduction-actions", headers=headers, params=params,
        )

    def get_reduction_action(self, action_id, headers):
        return self._request(
            "GET", f"/alarm-funding/alarm-reduction-actions/{action_id}", headers=headers,
        )

    # ─── Attrition ────────────────────────────────────
    def run_attrition_sweep(self, payload, headers):
        return self._request("POST", "/alarm-funding/attrition-sweeps/run", payload, headers)

    def list_attrition_sweeps(self, headers, params=None):
        return self._request(
            "GET", "/alarm-funding/attrition-sweeps", headers=headers, params=params,
        )

    def get_attrition_sweep(self, sweep_id, headers):
        return self._request(
            "GET", f"/alarm-funding/attrition-sweeps/{sweep_id}", headers=headers,
        )

    def list_sweep_flags(self, sweep_id, headers, params=None):
        return self._request(
            "GET", f"/alarm-funding/attrition-sweeps/{sweep_id}/flags",
            headers=headers, params=params,
        )

    # ─── Service visits ───────────────────────────────
    def create_service_visit(self, payload, headers):
        return self._request("POST", "/alarm-funding/service-visits", payload, headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", "/alarm-funding/service-visits", headers=headers, params=params)

    def get_service_visit(self, visit_id, headers):
        return self._request(
            "GET", f"/alarm-funding/service-visits/{visit_id}", headers=headers,
        )

    def schedule_service_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/service-visits/{visit_id}/schedule", payload, headers,
        )

    def perform_service_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/alarm-funding/service-visits/{visit_id}/perform", None, headers,
        )

    def cancel_service_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/alarm-funding/service-visits/{visit_id}/cancel", None, headers,
        )

    # ─── Assumption ───────────────────────────────────
    def create_assumption_request(self, payload, headers):
        return self._request("POST", "/alarm-funding/assumption-requests", payload, headers)

    def list_assumption_requests(self, headers, params=None):
        return self._request(
            "GET", "/alarm-funding/assumption-requests", headers=headers, params=params,
        )

    def get_assumption_request(self, request_id, headers):
        return self._request(
            "GET", f"/alarm-funding/assumption-requests/{request_id}", headers=headers,
        )

    def list_assumption_owners(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/alarm-funding/assumption-requests/{request_id}/owners",
            headers=headers, params=params,
        )

    def accept_assumption_request(self, request_id, headers):
        return self._request(
            "POST", f"/alarm-funding/assumption-requests/{request_id}/accept", None, headers,
        )

    def reject_assumption_request(self, request_id, headers):
        return self._request(
            "POST", f"/alarm-funding/assumption-requests/{request_id}/reject", None, headers,
        )

    def complete_assumption_request(self, request_id, headers):
        return self._request(
            "POST", f"/alarm-funding/assumption-requests/{request_id}/complete", None, headers,
        )

    # ─── Contract owners ──────────────────────────────
    def list_all_contract_owners(self, headers, params=None):
        return self._request(
            "GET", "/alarm-funding/contract-owners", headers=headers, params=params,
        )

    # ─── Rescission ───────────────────────────────────
    def create_rescission_request(self, payload, headers):
        return self._request("POST", "/alarm-funding/rescission-requests", payload, headers)

    def list_rescission_requests(self, headers, params=None):
        return self._request(
            "GET", "/alarm-funding/rescission-requests", headers=headers, params=params,
        )

    def get_rescission_request(self, request_id, headers):
        return self._request(
            "GET", f"/alarm-funding/rescission-requests/{request_id}", headers=headers,
        )

    def decide_rescission_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/alarm-funding/rescission-requests/{request_id}/decision",
            payload, headers,
        )

    # ─── Logical clock (test-driving) ─────────────────
    def set_clock(self, payload, headers):
        return self._request(
            "POST", "/alarm-funding/_clock/set_current_utc", payload, headers,
        )


api_client = ApiClient()