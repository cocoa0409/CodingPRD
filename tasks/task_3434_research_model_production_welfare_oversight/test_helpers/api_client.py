"""API client: one method per endpoint defined in PRD Section 4.

All paths carry the ``/api`` prefix exactly as tabulated in PRD Section 4,
with the single exception of the logical-clock control: PRD Section 2.5 —
"POST /_clock/set_current_utc. This is the one and only endpoint not mounted
under /api".
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._request("POST", "/api/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/api/facilities/{facility_id}", headers=headers)

    def transition_facility(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/api/facilities/{facility_id}/transition", payload, headers
        )

    def list_facility_rooms(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/api/facilities/{facility_id}/rooms", headers=headers, params=params
        )

    def list_facility_protocols(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/api/facilities/{facility_id}/protocols", headers=headers, params=params
        )

    def list_facility_inspections(self, facility_id, headers, params=None):
        return self._request(
            "GET", f"/api/facilities/{facility_id}/inspections", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Barrier rooms
    # ------------------------------------------------------------------
    def create_room(self, payload, headers):
        return self._request("POST", "/api/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/api/rooms/{room_id}", headers=headers)

    def transition_room(self, room_id, payload, headers):
        return self._request(
            "POST", f"/api/rooms/{room_id}/transition", payload, headers
        )

    def list_room_health_screens(self, room_id, headers, params=None):
        return self._request(
            "GET", f"/api/rooms/{room_id}/health-screens", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Strains
    # ------------------------------------------------------------------
    def create_strain(self, payload, headers):
        return self._request("POST", "/api/strains", payload, headers)

    def get_strain(self, strain_id, headers):
        return self._request("GET", f"/api/strains/{strain_id}", headers=headers)

    def list_strain_orders(self, strain_id, headers, params=None):
        return self._request(
            "GET", f"/api/strains/{strain_id}/orders", headers=headers, params=params
        )

    def list_strain_contracts(self, strain_id, headers, params=None):
        return self._request(
            "GET", f"/api/strains/{strain_id}/contracts", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Colonies
    # ------------------------------------------------------------------
    def create_colony(self, payload, headers):
        return self._request("POST", "/api/colonies", payload, headers)

    def list_colonies(self, headers, params=None):
        return self._request("GET", "/api/colonies", headers=headers, params=params)

    def get_colony(self, colony_id, headers):
        return self._request("GET", f"/api/colonies/{colony_id}", headers=headers)

    def transition_colony(self, colony_id, payload, headers):
        return self._request(
            "POST", f"/api/colonies/{colony_id}/transition", payload, headers
        )

    def record_snp_panel(self, colony_id, payload, headers):
        return self._request(
            "POST", f"/api/colonies/{colony_id}/snp-panel", payload, headers
        )

    def list_colony_cohorts(self, colony_id, headers, params=None):
        return self._request(
            "GET", f"/api/colonies/{colony_id}/cohorts", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Cohorts
    # ------------------------------------------------------------------
    def create_cohort(self, payload, headers):
        return self._request("POST", "/api/cohorts", payload, headers)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/api/cohorts/{cohort_id}", headers=headers)

    def transition_cohort(self, cohort_id, payload, headers):
        return self._request(
            "POST", f"/api/cohorts/{cohort_id}/transition", payload, headers
        )

    def list_cohort_allocations(self, cohort_id, headers, params=None):
        return self._request(
            "GET", f"/api/cohorts/{cohort_id}/allocations", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Health screens
    # ------------------------------------------------------------------
    def create_health_screen(self, payload, headers):
        return self._request("POST", "/api/health-screens", payload, headers)

    def result_health_screen(self, screen_id, payload, headers):
        return self._request(
            "POST", f"/api/health-screens/{screen_id}/result", payload, headers
        )

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def transition_customer(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/transition", payload, headers
        )

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/api/customers/{customer_id}/orders", headers=headers, params=params
        )

    def list_customer_contracts(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/api/customers/{customer_id}/contracts", headers=headers, params=params
        )

    def list_customer_inspections(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/api/customers/{customer_id}/inspections", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def transition_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/orders/{order_id}/transition", payload, headers
        )

    def list_order_allocations(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/orders/{order_id}/allocations", headers=headers, params=params
        )

    def list_order_shipments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/api/orders/{order_id}/shipments", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Allocations
    # ------------------------------------------------------------------
    def create_allocation(self, payload, headers):
        return self._request("POST", "/api/allocations", payload, headers)

    def release_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/api/allocations/{allocation_id}/release", {}, headers
        )

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", "/api/shipments", payload, headers)

    def transition_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # IACUC protocols
    # ------------------------------------------------------------------
    def create_protocol(self, payload, headers):
        return self._request("POST", "/api/protocols", payload, headers)

    def transition_protocol(self, protocol_id, payload, headers):
        return self._request(
            "POST", f"/api/protocols/{protocol_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Welfare inspections
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/api/inspections", payload, headers)

    def report_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/api/inspections/{inspection_id}/report", payload, headers
        )

    def verify_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"/api/inspections/{inspection_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------
    # Service contracts
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/api/contracts", payload, headers)

    def transition_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/contracts/{contract_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock (PRD Section 2.5 — intentionally outside /api prefix)
    # ------------------------------------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
