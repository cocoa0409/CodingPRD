"""API client: one method per endpoint defined in the PRD (section 4).

The logical-clock endpoint lives deliberately OUTSIDE the /evfleet mount and
is routed unprefixed; every other path carries the /evfleet prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/evfleet"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Platform: logical clock (UNPREFIXED — outside /evfleet, PRD section 2.4)
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Fleet customers
    # ------------------------------------------------------------------
    def create_fleet_customer(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/fleet-customers", payload, headers)

    def get_fleet_customer(self, customer_id, headers):
        return self._request("GET", f"{API_PREFIX}/fleet-customers/{customer_id}", headers=headers)

    def list_fleet_customer_depots(self, customer_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/fleet-customers/{customer_id}/depots", headers=headers, params=params)

    def list_fleet_customer_uptime_contracts(self, customer_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/fleet-customers/{customer_id}/uptime-contracts", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Depots and charging projects
    # ------------------------------------------------------------------
    def create_depot(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/depots", payload, headers)

    def get_depot(self, depot_id, headers):
        return self._request("GET", f"{API_PREFIX}/depots/{depot_id}", headers=headers)

    def list_depot_charging_projects(self, depot_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/depots/{depot_id}/charging-projects", headers=headers, params=params)

    def create_charging_project(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/charging-projects", payload, headers)

    def transition_charging_project(self, project_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/charging-projects/{project_id}/transition", payload, headers)

    # ------------------------------------------------------------------
    # Suppliers and battery modules
    # ------------------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"{API_PREFIX}/suppliers/{supplier_id}", headers=headers)

    def list_supplier_battery_modules(self, supplier_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/suppliers/{supplier_id}/battery-modules", headers=headers, params=params)

    def create_readiness_audit(self, supplier_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/suppliers/{supplier_id}/readiness-audits", payload, headers)

    def create_battery_module(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/battery-modules", payload, headers)

    def transition_battery_module(self, module_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/battery-modules/{module_id}/transition", payload, headers)

    # ------------------------------------------------------------------
    # Vehicle orders and vehicles
    # ------------------------------------------------------------------
    def create_vehicle_order(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/vehicle-orders", payload, headers)

    def get_vehicle_order(self, order_id, headers):
        return self._request("GET", f"{API_PREFIX}/vehicle-orders/{order_id}", headers=headers)

    def list_vehicle_orders(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/vehicle-orders", headers=headers, params=params)

    def transition_vehicle_order(self, order_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/vehicle-orders/{order_id}/transition", payload, headers)

    def create_vehicle(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"{API_PREFIX}/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/vehicles", headers=headers, params=params)

    def transition_vehicle(self, vehicle_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/vehicles/{vehicle_id}/transition", payload, headers)

    def report_battery_health(self, vehicle_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/vehicles/{vehicle_id}/battery-health", payload, headers)

    # ------------------------------------------------------------------
    # Service network: centers, mobile vans, visits, parts stock
    # ------------------------------------------------------------------
    def create_service_center(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/service-centers", payload, headers)

    def get_service_center(self, center_id, headers):
        return self._request("GET", f"{API_PREFIX}/service-centers/{center_id}", headers=headers)

    def list_service_center_mobile_vans(self, center_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/service-centers/{center_id}/mobile-vans", headers=headers, params=params)

    def list_service_center_parts_stocks(self, center_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/service-centers/{center_id}/parts-stocks", headers=headers, params=params)

    def create_mobile_van(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/mobile-vans", payload, headers)

    def create_service_visit(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/service-visits", payload, headers)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"{API_PREFIX}/service-visits/{visit_id}", headers=headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/service-visits", headers=headers, params=params)

    def transition_service_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/service-visits/{visit_id}/transition", payload, headers)

    def upsert_parts_stock(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/parts-stocks", payload, headers)

    # ------------------------------------------------------------------
    # Software campaigns
    # ------------------------------------------------------------------
    def create_software_campaign(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/software-campaigns", payload, headers)

    def get_software_campaign(self, campaign_id, headers):
        return self._request("GET", f"{API_PREFIX}/software-campaigns/{campaign_id}", headers=headers)

    def transition_software_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/software-campaigns/{campaign_id}/transition", payload, headers)

    def record_vehicle_result(self, campaign_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/software-campaigns/{campaign_id}/vehicle-results", payload, headers)

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"{API_PREFIX}/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/warranty-claims", headers=headers, params=params)

    def diagnose_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/warranty-claims/{claim_id}/diagnose", payload, headers)

    def adjudicate_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/warranty-claims/{claim_id}/adjudicate", payload, headers)

    # ------------------------------------------------------------------
    # Uptime contracts
    # ------------------------------------------------------------------
    def create_uptime_contract(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/uptime-contracts", payload, headers)

    def append_downtime_event(self, contract_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/uptime-contracts/{contract_id}/downtime-events", payload, headers)

    def close_uptime_month(self, contract_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/uptime-contracts/{contract_id}/close-month", payload, headers)


api_client = ApiClient()
