"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the /sterilization prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/sterilization"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/customers", headers=headers, params=params)

    def set_customer_status(self, customer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/customers/{customer_id}/status", payload, headers
        )

    def list_customer_products(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/customers/{customer_id}/products", headers=headers, params=params
        )

    # -------------------------------------------------------- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{PREFIX}/products/{product_id}", headers=headers)

    # ------------------------------------------------- EmissionPermit ----
    def create_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/emission-permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/emission-permits/{permit_id}", headers=headers)

    def set_permit_status(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/emission-permits/{permit_id}/status", payload, headers
        )

    def list_permit_chambers(self, permit_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/emission-permits/{permit_id}/chambers",
            headers=headers,
            params=params,
        )

    # -------------------------------------------------------- Chamber ----
    def create_chamber(self, payload, headers):
        return self._request("POST", f"{PREFIX}/chambers", payload, headers)

    def get_chamber(self, chamber_id, headers):
        return self._request("GET", f"{PREFIX}/chambers/{chamber_id}", headers=headers)

    def set_chamber_status(self, chamber_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chambers/{chamber_id}/status", payload, headers
        )

    # ---------------------------------------------------- CycleRecipe ----
    def create_recipe(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cycle-recipes", payload, headers)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"{PREFIX}/cycle-recipes/{recipe_id}", headers=headers)

    def approve_recipe(self, recipe_id, headers):
        return self._request(
            "POST", f"{PREFIX}/cycle-recipes/{recipe_id}/approve", {}, headers
        )

    # -------------------------------------------- ProductQualification ---
    def create_qualification(self, payload, headers):
        return self._request("POST", f"{PREFIX}/qualifications", payload, headers)

    def get_qualification(self, qualification_id, headers):
        return self._request(
            "GET", f"{PREFIX}/qualifications/{qualification_id}", headers=headers
        )

    def list_qualifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/qualifications", headers=headers, params=params)

    def create_dose_audit(self, qualification_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/qualifications/{qualification_id}/dose-audits", payload, headers
        )

    def list_dose_audits(self, qualification_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/qualifications/{qualification_id}/dose-audits",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ Lot ----
    def create_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"{PREFIX}/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/lots", headers=headers, params=params)

    def release_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/release", payload, headers)

    def create_aeration_record(self, lot_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/lots/{lot_id}/aeration-records", payload or {}, headers
        )

    def list_aeration_records(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lots/{lot_id}/aeration-records", headers=headers, params=params
        )

    def create_adverse_event(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/lots/{lot_id}/adverse-events", payload, headers
        )

    def list_adverse_events(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lots/{lot_id}/adverse-events", headers=headers, params=params
        )

    # ---------------------------------------------------------- Cycle ----
    def create_cycle(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cycles", headers=headers, params=params)

    def create_load_position(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cycles/{cycle_id}/load-positions", payload, headers
        )

    def delete_load_position(self, cycle_id, position_id, headers):
        return self._request(
            "DELETE",
            f"{PREFIX}/cycles/{cycle_id}/load-positions/{position_id}",
            headers=headers,
        )

    def ready_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/cycles/{cycle_id}/ready", {}, headers)

    def start_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/cycles/{cycle_id}/start", {}, headers)

    def complete_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/cycles/{cycle_id}/complete", {}, headers)

    def abort_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cycles/{cycle_id}/abort", payload, headers)

    def dosimetry_close(self, cycle_id, headers):
        return self._request(
            "POST", f"{PREFIX}/cycles/{cycle_id}/dosimetry-close", {}, headers
        )

    # --------------------------------------------------- LoadPosition ----
    def get_load_position(self, position_id, headers):
        return self._request(
            "GET", f"{PREFIX}/load-positions/{position_id}", headers=headers
        )

    def list_load_positions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/load-positions", headers=headers, params=params)

    def create_indicator(self, position_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/load-positions/{position_id}/indicators", payload, headers
        )

    def list_indicators(self, position_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/load-positions/{position_id}/indicators",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------ Indicator ----
    def record_reading(self, indicator_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/indicators/{indicator_id}/reading", payload, headers
        )

    # ------------------------------------------------- AerationRecord ----
    def record_residual_test(self, record_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/aeration-records/{record_id}/residual-test", payload, headers
        )

    # --------------------------------------------------- AdverseEvent ----
    def disposition_adverse_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/adverse-events/{event_id}/disposition", payload, headers
        )

    # ---------------------------------------------------- logical clock --
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
