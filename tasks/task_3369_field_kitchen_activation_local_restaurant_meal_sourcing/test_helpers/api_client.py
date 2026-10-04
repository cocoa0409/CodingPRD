"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/field-ops"


class ApiClient(GenericApiClient):
    # --- activations ---------------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", f"{BASE}/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", f"{BASE}/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"{BASE}/incidents/{incident_id}", headers=headers)

    def transition_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/incidents/{incident_id}/transitions", payload, headers
        )

    def get_accountability_report(self, incident_id, headers):
        return self._request(
            "GET", f"{BASE}/incidents/{incident_id}/accountability-report", headers=headers
        )

    # --- assessments ---------------------------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", f"{BASE}/assessments", payload, headers)

    def list_incident_assessments(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/incidents/{incident_id}/assessments", headers=headers, params=params
        )

    # --- field kitchens ------------------------------------------------------
    def create_field_kitchen(self, payload, headers):
        return self._request("POST", f"{BASE}/field-kitchens", payload, headers)

    def list_field_kitchens(self, headers, params=None):
        return self._request("GET", f"{BASE}/field-kitchens", headers=headers, params=params)

    def get_field_kitchen(self, field_kitchen_id, headers):
        return self._request(
            "GET", f"{BASE}/field-kitchens/{field_kitchen_id}", headers=headers
        )

    def transition_field_kitchen(self, field_kitchen_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/field-kitchens/{field_kitchen_id}/transitions",
            payload,
            headers,
        )

    def inspect_field_kitchen(self, field_kitchen_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/field-kitchens/{field_kitchen_id}/inspections",
            payload,
            headers,
        )

    # --- partner kitchens ----------------------------------------------------
    def create_partner_kitchen(self, payload, headers):
        return self._request("POST", f"{BASE}/partner-kitchens", payload, headers)

    def list_incident_partner_kitchens(self, incident_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/incidents/{incident_id}/partner-kitchens",
            headers=headers,
            params=params,
        )

    def get_partner_kitchen(self, partner_kitchen_id, headers):
        return self._request(
            "GET", f"{BASE}/partner-kitchens/{partner_kitchen_id}", headers=headers
        )

    def transition_partner_kitchen(self, partner_kitchen_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/partner-kitchens/{partner_kitchen_id}/transitions",
            payload,
            headers,
        )

    # --- production batches --------------------------------------------------
    def create_meal_order(self, payload, headers):
        return self._request("POST", f"{BASE}/meal-orders", payload, headers)

    def list_meal_orders(self, headers, params=None):
        return self._request("GET", f"{BASE}/meal-orders", headers=headers, params=params)

    def get_meal_order(self, meal_order_id, headers):
        return self._request("GET", f"{BASE}/meal-orders/{meal_order_id}", headers=headers)

    def transition_meal_order(self, meal_order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/meal-orders/{meal_order_id}/transitions", payload, headers
        )

    # --- producers -----------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", f"{BASE}/suppliers", payload, headers)

    def list_incident_suppliers(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/incidents/{incident_id}/suppliers", headers=headers, params=params
        )

    # --- sourcing orders -----------------------------------------------------
    def create_ingredient_purchase(self, payload, headers):
        return self._request("POST", f"{BASE}/ingredient-purchases", payload, headers)

    def list_ingredient_purchases(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/ingredient-purchases", headers=headers, params=params
        )

    def get_ingredient_purchase(self, purchase_id, headers):
        return self._request(
            "GET", f"{BASE}/ingredient-purchases/{purchase_id}", headers=headers
        )

    def transition_ingredient_purchase(self, purchase_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/ingredient-purchases/{purchase_id}/transitions",
            payload,
            headers,
        )

    # --- receiving sites -----------------------------------------------------
    def create_distribution_site(self, payload, headers):
        return self._request("POST", f"{BASE}/distribution-sites", payload, headers)

    def list_incident_distribution_sites(self, incident_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/incidents/{incident_id}/distribution-sites",
            headers=headers,
            params=params,
        )

    # --- delivery runs -------------------------------------------------------
    def create_distribution_run(self, payload, headers):
        return self._request("POST", f"{BASE}/distribution-runs", payload, headers)

    def list_distribution_runs(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/distribution-runs", headers=headers, params=params
        )

    def get_distribution_run(self, run_id, headers):
        return self._request(
            "GET", f"{BASE}/distribution-runs/{run_id}", headers=headers
        )

    def transition_distribution_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/distribution-runs/{run_id}/transitions", payload, headers
        )

    # --- delivery stops ------------------------------------------------------
    def create_distribution_stop(self, payload, headers):
        return self._request("POST", f"{BASE}/distribution-stops", payload, headers)

    def list_distribution_stops(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/distribution-stops", headers=headers, params=params
        )

    def get_distribution_stop(self, stop_id, headers):
        return self._request(
            "GET", f"{BASE}/distribution-stops/{stop_id}", headers=headers
        )

    def transition_distribution_stop(self, stop_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/distribution-stops/{stop_id}/transitions", payload, headers
        )

    # --- donor commitments ---------------------------------------------------
    def create_donor_commitment(self, payload, headers):
        return self._request("POST", f"{BASE}/donor-commitments", payload, headers)

    def list_incident_donor_commitments(self, incident_id, headers, params=None):
        return self._request(
            "GET",
            f"{BASE}/incidents/{incident_id}/donor-commitments",
            headers=headers,
            params=params,
        )

    def transition_donor_commitment(self, commitment_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/donor-commitments/{commitment_id}/transitions",
            payload,
            headers,
        )

    # --- logical clock -------------------------------------------------------
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
