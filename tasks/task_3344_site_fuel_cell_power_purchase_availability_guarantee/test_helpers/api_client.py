"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Site ---------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/power/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/power/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/power/sites/{site_id}", headers=headers)

    def list_site_ppas(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/power/sites/{site_id}/ppas", headers=headers, params=params
        )

    def evaluate_site(self, site_id, headers, payload=None):
        return self._request(
            "POST", f"/power/sites/{site_id}/evaluate", payload or {}, headers
        )

    def freeze_site(self, site_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/power/sites/{site_id}/freeze", payload, headers)

    def unfreeze_site(self, site_id, headers):
        return self._request("POST", f"/power/sites/{site_id}/unfreeze", {}, headers)

    def transfer_ppa(self, site_id, headers, payload):
        return self._request(
            "POST", f"/power/sites/{site_id}/transfer-ppa", payload, headers
        )

    # --- Customer -----------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/power/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/power/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/power/customers/{customer_id}", headers=headers)

    def list_customer_ppas(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/power/customers/{customer_id}/ppas", headers=headers, params=params
        )

    def list_customer_fuel_deliveries(self, customer_id, headers, params=None):
        return self._request(
            "GET",
            f"/power/customers/{customer_id}/fuel-deliveries",
            headers=headers,
            params=params,
        )

    def apply_exposure_hold(self, customer_id, headers):
        return self._request(
            "POST", f"/power/customers/{customer_id}/apply-exposure-hold", {}, headers
        )

    def release_exposure_hold(self, customer_id, headers):
        return self._request(
            "POST", f"/power/customers/{customer_id}/release-exposure-hold", {}, headers
        )

    def offer_renewal(self, customer_id, headers):
        return self._request(
            "POST", f"/power/customers/{customer_id}/offer-renewal", {}, headers
        )

    def accept_renewal(self, customer_id, headers):
        return self._request(
            "POST", f"/power/customers/{customer_id}/accept-renewal", {}, headers
        )

    def decline_renewal(self, customer_id, headers):
        return self._request(
            "POST", f"/power/customers/{customer_id}/decline-renewal", {}, headers
        )

    # --- Ppa ----------------------------------------------------------------
    def create_ppa(self, payload, headers):
        return self._request("POST", "/power/ppas", payload, headers)

    def list_ppas(self, headers, params=None):
        return self._request("GET", "/power/ppas", headers=headers, params=params)

    def get_ppa(self, ppa_id, headers):
        return self._request("GET", f"/power/ppas/{ppa_id}", headers=headers)

    def list_ppa_transfers(self, ppa_id, headers, params=None):
        return self._request(
            "GET", f"/power/ppas/{ppa_id}/transfers", headers=headers, params=params
        )

    def activate_ppa(self, ppa_id, headers, payload=None):
        return self._request("POST", f"/power/ppas/{ppa_id}/activate", payload or {}, headers)

    def request_exit(self, ppa_id, headers, payload=None):
        return self._request(
            "POST", f"/power/ppas/{ppa_id}/request-exit", payload or {}, headers
        )

    def cure_ppa(self, ppa_id, headers, payload=None):
        return self._request("POST", f"/power/ppas/{ppa_id}/cure", payload or {}, headers)

    def terminate_ppa(self, ppa_id, headers, payload=None):
        return self._request(
            "POST", f"/power/ppas/{ppa_id}/terminate", payload or {}, headers
        )

    def renew_ppa(self, ppa_id, headers, payload=None):
        return self._request("POST", f"/power/ppas/{ppa_id}/renew", payload or {}, headers)

    def adjust_contract(self, ppa_id, headers, payload):
        return self._request(
            "POST", f"/power/ppas/{ppa_id}/adjust-contract", payload, headers
        )

    # --- ServicePlan --------------------------------------------------------
    def create_service_plan(self, ppa_id, headers, payload):
        return self._request(
            "POST", f"/power/ppas/{ppa_id}/service-plans", payload, headers
        )

    def list_service_plans(self, ppa_id, headers, params=None):
        return self._request(
            "GET", f"/power/ppas/{ppa_id}/service-plans", headers=headers, params=params
        )

    def get_service_plan(self, ppa_id, plan_id, headers):
        return self._request(
            "GET", f"/power/ppas/{ppa_id}/service-plans/{plan_id}", headers=headers
        )

    def schedule_replacement(self, ppa_id, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/power/ppas/{ppa_id}/service-plans/{plan_id}/schedule-replacement",
            payload or {},
            headers,
        )

    def dispatch_module_replacement(self, ppa_id, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/power/ppas/{ppa_id}/service-plans/{plan_id}/dispatch-module-replacement",
            payload or {},
            headers,
        )

    # --- FuelDelivery -------------------------------------------------------
    def create_fuel_delivery(self, site_id, headers, payload):
        return self._request(
            "POST", f"/power/sites/{site_id}/fuel-deliveries", payload, headers
        )

    def list_site_fuel_deliveries(self, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/power/sites/{site_id}/fuel-deliveries",
            headers=headers,
            params=params,
        )

    def get_fuel_delivery(self, site_id, delivery_id, headers):
        return self._request(
            "GET",
            f"/power/sites/{site_id}/fuel-deliveries/{delivery_id}",
            headers=headers,
        )

    def dispatch_fuel_delivery(self, site_id, delivery_id, headers, payload=None):
        return self._request(
            "POST",
            f"/power/sites/{site_id}/fuel-deliveries/{delivery_id}/dispatch",
            payload or {},
            headers,
        )

    def confirm_fuel_delivery(self, site_id, delivery_id, headers, payload=None):
        return self._request(
            "POST",
            f"/power/sites/{site_id}/fuel-deliveries/{delivery_id}/confirm",
            payload or {},
            headers,
        )

    def cancel_fuel_delivery(self, site_id, delivery_id, headers, payload=None):
        return self._request(
            "POST",
            f"/power/sites/{site_id}/fuel-deliveries/{delivery_id}/cancel",
            payload or {},
            headers,
        )

    def take_resource_hold(self, site_id, headers, payload):
        return self._request(
            "POST", f"/power/sites/{site_id}/resource-holds", payload, headers
        )

    def release_resource_hold(self, site_id, headers, payload):
        return self._request(
            "POST", f"/power/sites/{site_id}/release-resource-hold", payload, headers
        )

    # --- SettlementLine -----------------------------------------------------
    def create_settlement_line(self, ppa_id, headers, payload):
        return self._request(
            "POST", f"/power/ppas/{ppa_id}/settlement-lines", payload, headers
        )

    def list_settlement_lines(self, ppa_id, headers, params=None):
        return self._request(
            "GET",
            f"/power/ppas/{ppa_id}/settlement-lines",
            headers=headers,
            params=params,
        )

    def get_settlement_line(self, ppa_id, line_id, headers):
        return self._request(
            "GET", f"/power/ppas/{ppa_id}/settlement-lines/{line_id}", headers=headers
        )

    def validate_settlement_line(self, ppa_id, line_id, headers, payload=None):
        return self._request(
            "POST",
            f"/power/ppas/{ppa_id}/settlement-lines/{line_id}/validate",
            payload or {},
            headers,
        )

    def approve_settlement_line(self, ppa_id, line_id, headers, payload=None):
        return self._request(
            "POST",
            f"/power/ppas/{ppa_id}/settlement-lines/{line_id}/approve",
            payload or {},
            headers,
        )

    def settle_settlement_line(self, ppa_id, line_id, headers, payload=None):
        return self._request(
            "POST",
            f"/power/ppas/{ppa_id}/settlement-lines/{line_id}/settle",
            payload or {},
            headers,
        )

    def reverse_settlement_line(self, ppa_id, line_id, headers, payload=None):
        return self._request(
            "POST",
            f"/power/ppas/{ppa_id}/settlement-lines/{line_id}/reverse",
            payload or {},
            headers,
        )

    # --- PpaAccrual ---------------------------------------------------------
    def create_accrual(self, payload, headers):
        return self._request("POST", "/power/ppa-accruals", payload, headers)

    def list_accruals(self, headers, params=None):
        return self._request("GET", "/power/ppa-accruals", headers=headers, params=params)

    def get_accrual(self, accrual_id, headers):
        return self._request("GET", f"/power/ppa-accruals/{accrual_id}", headers=headers)

    def list_accrual_applied_allowances(self, accrual_id, headers, params=None):
        return self._request(
            "GET",
            f"/power/ppa-accruals/{accrual_id}/applied-allowances",
            headers=headers,
            params=params,
        )

    def reconcile_accruals(self, ppa_id, headers, payload=None):
        return self._request(
            "POST", f"/power/ppas/{ppa_id}/reconcile-accruals", payload or {}, headers
        )

    def list_ppa_fuel_deliveries(self, ppa_id, headers, params=None):
        return self._request(
            "GET", f"/power/ppas/{ppa_id}/fuel-deliveries", headers=headers, params=params
        )

    # --- SettlementAllowance ------------------------------------------------
    def issue_allowance(self, ppa_id, headers, payload):
        return self._request("POST", f"/power/ppas/{ppa_id}/allowances", payload, headers)

    def list_allowances(self, ppa_id, headers, params=None):
        return self._request(
            "GET", f"/power/ppas/{ppa_id}/allowances", headers=headers, params=params
        )

    def get_allowance(self, ppa_id, allowance_id, headers):
        return self._request(
            "GET", f"/power/ppas/{ppa_id}/allowances/{allowance_id}", headers=headers
        )

    def apply_allowance(self, ppa_id, allowance_id, headers, payload=None):
        return self._request(
            "POST",
            f"/power/ppas/{ppa_id}/allowances/{allowance_id}/apply",
            payload or {},
            headers,
        )

    # --- PpaTransition ------------------------------------------------------
    def list_transitions(self, headers, params=None):
        return self._request("GET", "/power/ppa-transitions", headers=headers, params=params)

    def get_transition(self, transition_id, headers):
        return self._request(
            "GET", f"/power/ppa-transitions/{transition_id}", headers=headers
        )

    def list_ppa_transitions(self, ppa_id, headers, params=None):
        return self._request(
            "GET", f"/power/ppas/{ppa_id}/transitions", headers=headers, params=params
        )

    # --- Batch operations ---------------------------------------------------
    def recompute_index_bases(self, headers, payload=None):
        return self._request(
            "POST", "/power/_ops/recompute-index-bases", payload or {}, headers
        )

    def rollover_period(self, headers, payload=None):
        return self._request(
            "POST", "/power/_ops/rollover-period", payload or {}, headers
        )

    # --- Logical clock ------------------------------------------------------
    def set_current_utc(self, headers, current_utc):
        return self._request(
            "POST", "/power/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


api_client = ApiClient()