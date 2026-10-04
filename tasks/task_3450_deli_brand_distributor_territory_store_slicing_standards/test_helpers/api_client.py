"""API client: one method per endpoint defined in PRD §4.

All business endpoints live under the /api prefix. The logical-clock
endpoint POST /_clock/set_current_utc is UNPREFIXED (PRD §2.5, §4).
"""
from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/api"
CLOCK_PATH = "/_clock/set_current_utc"  # unprefixed, per PRD §2.5


class ApiClient(GenericApiClient):
    # ----- logical clock (unprefixed) -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    # ----- distributors -----
    def create_distributor(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/distributors", payload, headers)

    def list_distributors(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/distributors", headers=headers, params=params)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"{API_PREFIX}/distributors/{distributor_id}", headers=headers)

    def suspend_distributor(self, distributor_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/distributors/{distributor_id}/suspend", payload or {}, headers)

    def reinstate_distributor(self, distributor_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/distributors/{distributor_id}/reinstate", payload or {}, headers)

    def terminate_distributor(self, distributor_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/distributors/{distributor_id}/terminate", payload or {}, headers)

    # ----- territories -----
    def create_territory(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/territories", payload, headers)

    def list_territories(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/territories", headers=headers, params=params)

    def get_territory(self, territory_id, headers):
        return self._request("GET", f"{API_PREFIX}/territories/{territory_id}", headers=headers)

    def grant_territory(self, territory_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/territories/{territory_id}/grant", payload, headers)

    def revoke_territory(self, territory_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/territories/{territory_id}/revoke", payload or {}, headers)

    # ----- accounts -----
    def create_account(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{API_PREFIX}/accounts/{account_id}", headers=headers)

    def review_account(self, account_id, decision, headers):
        return self._request("POST", f"{API_PREFIX}/accounts/{account_id}/review", {"decision": decision}, headers)

    def suspend_account(self, account_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/accounts/{account_id}/suspend", payload or {}, headers)

    def reinstate_account(self, account_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/accounts/{account_id}/reinstate", payload or {}, headers)

    # ----- products -----
    def create_product(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{API_PREFIX}/products/{product_id}", headers=headers)

    # ----- account product authorizations -----
    def create_authorization(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/account-product-authorizations", payload, headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/account-product-authorizations", headers=headers, params=params)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"{API_PREFIX}/account-product-authorizations/{authorization_id}", headers=headers)

    def revoke_authorization(self, authorization_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/account-product-authorizations/{authorization_id}/revoke", payload or {}, headers)

    # ----- orders / order lines -----
    def create_order(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{API_PREFIX}/orders/{order_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"{API_PREFIX}/order-lines/{order_line_id}", headers=headers)

    def allocate_week(self, delivery_week, headers):
        return self._request("POST", f"{API_PREFIX}/orders/allocate-week", {"delivery_week": delivery_week}, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/orders/{order_id}/cancel", payload or {}, headers)

    # ----- plants -----
    def create_plant(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"{API_PREFIX}/plants/{plant_id}", headers=headers)

    # ----- production runs -----
    def create_production_run(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/production-runs", headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"{API_PREFIX}/production-runs/{run_id}", headers=headers)

    def complete_production_run(self, run_id, actual_units, waste_units, headers):
        payload = {"actual_units": actual_units, "waste_units": waste_units}
        return self._request("POST", f"{API_PREFIX}/production-runs/{run_id}/complete", payload, headers)

    # ----- lots -----
    def list_lots(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"{API_PREFIX}/lots/{lot_id}", headers=headers)

    # ----- deliveries -----
    def create_delivery(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/deliveries", payload, headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"{API_PREFIX}/deliveries/{delivery_id}", headers=headers)

    def confirm_delivery(self, delivery_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/deliveries/{delivery_id}/confirm", payload or {}, headers)

    def reject_delivery(self, delivery_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/deliveries/{delivery_id}/reject", payload or {}, headers)

    # ----- service visits -----
    def create_service_visit(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/service-visits", payload, headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/service-visits", headers=headers, params=params)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"{API_PREFIX}/service-visits/{visit_id}", headers=headers)

    def submit_service_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/service-visits/{visit_id}/submit", payload, headers)

    def review_service_visit(self, visit_id, verdict, headers):
        return self._request("POST", f"{API_PREFIX}/service-visits/{visit_id}/review", {"verdict": verdict}, headers)

    # ----- slicers -----
    def create_slicer(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/slicers", payload, headers)

    def list_slicers(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/slicers", headers=headers, params=params)

    def get_slicer(self, slicer_id, headers):
        return self._request("GET", f"{API_PREFIX}/slicers/{slicer_id}", headers=headers)

    def decommission_slicer(self, slicer_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/slicers/{slicer_id}/decommission", payload or {}, headers)

    # ----- opened product logs -----
    def create_opened_product_log(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/opened-product-logs", payload, headers)

    def list_opened_product_logs(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/opened-product-logs", headers=headers, params=params)

    def get_opened_product_log(self, log_id, headers):
        return self._request("GET", f"{API_PREFIX}/opened-product-logs/{log_id}", headers=headers)

    def pull_opened_product_log(self, log_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/opened-product-logs/{log_id}/pull", payload or {}, headers)

    # ----- training certifications -----
    def create_training_certification(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/training-certifications", payload, headers)

    def list_training_certifications(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/training-certifications", headers=headers, params=params)

    def get_training_certification(self, cert_id, headers):
        return self._request("GET", f"{API_PREFIX}/training-certifications/{cert_id}", headers=headers)

    def revoke_training_certification(self, cert_id, headers, payload=None):
        return self._request("POST", f"{API_PREFIX}/training-certifications/{cert_id}/revoke", payload or {}, headers)

    # ----- promo programs -----
    def create_promo_program(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/promo-programs", payload, headers)

    def list_promo_programs(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/promo-programs", headers=headers, params=params)

    def get_promo_program(self, program_id, headers):
        return self._request("GET", f"{API_PREFIX}/promo-programs/{program_id}", headers=headers)

    def authorize_promo_program(self, program_id, decision, headers):
        return self._request("POST", f"{API_PREFIX}/promo-programs/{program_id}/authorize", {"decision": decision}, headers)

    def settle_promo_program(self, program_id, redemption_lines, headers):
        return self._request("POST", f"{API_PREFIX}/promo-programs/{program_id}/settle", {"redemption_lines": redemption_lines}, headers)

    # ----- incidents -----
    def create_incident(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"{API_PREFIX}/incidents/{incident_id}", headers=headers)

    def transition_incident(self, incident_id, to, headers, resolution_outcome=None):
        payload = {"to": to}
        if resolution_outcome is not None:
            payload["resolution_outcome"] = resolution_outcome
        return self._request("POST", f"{API_PREFIX}/incidents/{incident_id}/transition", payload, headers)


api_client = ApiClient()
