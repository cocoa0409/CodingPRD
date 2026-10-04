"""API client: one method per endpoint defined in the PRD (§4).

All routes are mounted under /metrology except the logical-clock endpoint,
which is mounted at the server root (PRD §2.4) and therefore NOT prefixed.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Programs & pricing ---
    def create_program(self, payload, headers):
        return self._request("POST", "/metrology/programs", payload, headers)

    def pricing_update(self, program_id, payload, headers):
        return self._request(
            "POST", f"/metrology/programs/{program_id}/pricing-update", payload, headers
        )

    # --- Material lots ---
    def create_material_lot(self, payload, headers):
        return self._request("POST", "/metrology/material-lots", payload, headers)

    def get_material_lot(self, lot_id, headers):
        return self._request("GET", f"/metrology/material-lots/{lot_id}", headers=headers)

    def list_material_lots(self, headers, params=None):
        return self._request("GET", "/metrology/material-lots", headers=headers, params=params)

    def transition_material_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/metrology/material-lots/{lot_id}/transitions", payload, headers
        )

    def list_value_assignment_methods(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/metrology/material-lots/{lot_id}/value-assignment-methods",
            headers=headers, params=params,
        )

    def list_lot_certificates(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/metrology/material-lots/{lot_id}/certificates",
            headers=headers, params=params,
        )

    def list_lot_pt_rounds(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/metrology/material-lots/{lot_id}/pt-rounds",
            headers=headers, params=params,
        )

    # --- Value assignment methods ---
    def create_value_assignment_method(self, payload, headers):
        return self._request("POST", "/metrology/value-assignment-methods", payload, headers)

    def transition_value_assignment_method(self, method_id, payload, headers):
        return self._request(
            "POST", f"/metrology/value-assignment-methods/{method_id}/transitions",
            payload, headers,
        )

    # --- Certificates ---
    def create_certificate(self, payload, headers):
        return self._request("POST", "/metrology/certificates", payload, headers)

    def transition_certificate(self, cert_id, payload, headers):
        return self._request(
            "POST", f"/metrology/certificates/{cert_id}/transitions", payload, headers
        )

    # --- Customers & sales orders ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/metrology/customers", payload, headers)

    def create_sales_order(self, payload, headers):
        return self._request("POST", "/metrology/sales-orders", payload, headers)

    def transition_sales_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/metrology/sales-orders/{order_id}/transitions", payload, headers
        )

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/metrology/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/metrology/sales-orders", headers=headers, params=params)

    # --- Calibration services & orders ---
    def create_calibration_service(self, payload, headers):
        return self._request("POST", "/metrology/calibration-services", payload, headers)

    def create_calibration_order(self, payload, headers):
        return self._request("POST", "/metrology/calibration-orders", payload, headers)

    def transition_calibration_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/metrology/calibration-orders/{order_id}/transitions", payload, headers
        )

    def get_calibration_order(self, order_id, headers):
        return self._request(
            "GET", f"/metrology/calibration-orders/{order_id}", headers=headers
        )

    def list_calibration_orders(self, headers, params=None):
        return self._request(
            "GET", "/metrology/calibration-orders", headers=headers, params=params
        )

    # --- Traceability ---
    def create_traceability_link(self, payload, headers):
        return self._request("POST", "/metrology/traceability-links", payload, headers)

    def get_traceability_link(self, link_id, headers):
        return self._request("GET", f"/metrology/traceability-links/{link_id}", headers=headers)

    def list_traceability_links(self, headers, params=None):
        return self._request("GET", "/metrology/traceability-links", headers=headers, params=params)

    # --- PT rounds / participant results ---
    def create_pt_round(self, payload, headers):
        return self._request("POST", "/metrology/pt-rounds", payload, headers)

    def transition_pt_round(self, round_id, payload, headers):
        return self._request(
            "POST", f"/metrology/pt-rounds/{round_id}/transitions", payload, headers
        )

    def create_participant_result(self, round_id, payload, headers):
        return self._request(
            "POST", f"/metrology/pt-rounds/{round_id}/participant-results", payload, headers
        )

    def get_participant_result(self, result_id, headers):
        return self._request(
            "GET", f"/metrology/pt-participant-results/{result_id}", headers=headers
        )

    def list_participant_results(self, headers, params=None):
        return self._request(
            "GET", "/metrology/pt-participant-results", headers=headers, params=params
        )

    # --- Logical clock (UNPREFIXED — mounted at server root per PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
