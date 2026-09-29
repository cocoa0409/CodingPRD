"""API client — one method per endpoint of the Shellfish Harvest Classification API.

Every path is mounted under the `/shellfish` prefix (PRD §4).
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/shellfish"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Growing areas (PRD §3.1 – §3.3)
    # ------------------------------------------------------------------
    def create_growing_area(self, payload, headers):
        return self._request("POST", f"{PREFIX}/growing-areas", payload, headers)

    def get_growing_area(self, area_id, headers):
        return self._request("GET", f"{PREFIX}/growing-areas/{area_id}", headers=headers)

    def list_growing_areas(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/growing-areas", headers=headers, params=params)

    def create_classification_decision(self, area_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/growing-areas/{area_id}/classification-decisions",
            payload, headers,
        )

    def reopen_growing_area(self, area_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/growing-areas/{area_id}/reopen", payload, headers,
        )

    def get_classification_summary(self, area_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/growing-areas/{area_id}/classification-summary",
            headers=headers, params=params,
        )

    def create_water_sample(self, area_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/growing-areas/{area_id}/water-samples", payload, headers,
        )

    def list_water_samples(self, area_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/growing-areas/{area_id}/water-samples",
            headers=headers, params=params,
        )

    def create_rainfall_event(self, area_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/growing-areas/{area_id}/rainfall-events", payload, headers,
        )

    def list_rainfall_events(self, area_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/growing-areas/{area_id}/rainfall-events",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Leases (PRD §3.4)
    # ------------------------------------------------------------------
    def create_lease(self, payload, headers):
        return self._request("POST", f"{PREFIX}/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"{PREFIX}/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/leases", headers=headers, params=params)

    def submit_lease(self, lease_id, payload, headers):
        return self._request("POST", f"{PREFIX}/leases/{lease_id}/submit", payload, headers)

    def navigation_review(self, lease_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/navigation-review", payload, headers,
        )

    def environmental_review(self, lease_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/leases/{lease_id}/environmental-review", payload, headers,
        )

    def decide_lease(self, lease_id, payload, headers):
        return self._request("POST", f"{PREFIX}/leases/{lease_id}/decision", payload, headers)

    # ------------------------------------------------------------------
    # Hatcheries and seed lots (PRD §3.5)
    # ------------------------------------------------------------------
    def create_hatchery(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hatcheries", payload, headers)

    def get_hatchery(self, hatchery_id, headers):
        return self._request("GET", f"{PREFIX}/hatcheries/{hatchery_id}", headers=headers)

    def create_seed_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seed-lots", payload, headers)

    def get_seed_lot(self, seed_lot_id, headers):
        return self._request("GET", f"{PREFIX}/seed-lots/{seed_lot_id}", headers=headers)

    def list_seed_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/seed-lots", headers=headers, params=params)

    def screen_seed_lot(self, seed_lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/seed-lots/{seed_lot_id}/screening", payload, headers,
        )

    def start_nursery(self, seed_lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/seed-lots/{seed_lot_id}/nursery-start", payload, headers,
        )

    def complete_nursery(self, seed_lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/seed-lots/{seed_lot_id}/nursery-complete", payload, headers,
        )

    # ------------------------------------------------------------------
    # Grow-out units and husbandry (PRD §3.6)
    # ------------------------------------------------------------------
    def create_growout_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/growout-units", payload, headers)

    def get_growout_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/growout-units/{unit_id}", headers=headers)

    def list_growout_units(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/growout-units", headers=headers, params=params)

    def create_husbandry_log(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/growout-units/{unit_id}/husbandry-logs", payload, headers,
        )

    def list_husbandry_logs(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/growout-units/{unit_id}/husbandry-logs",
            headers=headers, params=params,
        )

    def retrieve_growout_unit(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/growout-units/{unit_id}/retrieve", payload, headers,
        )

    def void_growout_unit(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/growout-units/{unit_id}/void", payload, headers,
        )

    # ------------------------------------------------------------------
    # Vessels and harvest authorizations (PRD §3.7)
    # ------------------------------------------------------------------
    def create_harvest_vessel(self, payload, headers):
        return self._request("POST", f"{PREFIX}/harvest-vessels", payload, headers)

    def get_harvest_vessel(self, vessel_id, headers):
        return self._request("GET", f"{PREFIX}/harvest-vessels/{vessel_id}", headers=headers)

    def create_harvest_authorization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/harvest-authorizations", payload, headers)

    def get_harvest_authorization(self, auth_id, headers):
        return self._request(
            "GET", f"{PREFIX}/harvest-authorizations/{auth_id}", headers=headers,
        )

    def list_harvest_authorizations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/harvest-authorizations", headers=headers, params=params,
        )

    def activate_harvest_authorization(self, auth_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/harvest-authorizations/{auth_id}/activate", payload, headers,
        )

    def close_harvest_authorization(self, auth_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/harvest-authorizations/{auth_id}/close", payload, headers,
        )

    def create_harvest_lot(self, auth_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/harvest-authorizations/{auth_id}/harvest-lots",
            payload, headers,
        )

    def list_authorization_harvest_lots(self, auth_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/harvest-authorizations/{auth_id}/harvest-lots",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Harvest lots (PRD §3.8, §3.9)
    # ------------------------------------------------------------------
    def get_harvest_lot(self, lot_id, headers):
        return self._request("GET", f"{PREFIX}/harvest-lots/{lot_id}", headers=headers)

    def list_harvest_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/harvest-lots", headers=headers, params=params)

    def tag_harvest_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/harvest-lots/{lot_id}/tag", payload, headers)

    def void_harvest_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/harvest-lots/{lot_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # Dealers (PRD §3.9)
    # ------------------------------------------------------------------
    def create_dealer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"{PREFIX}/dealers/{dealer_id}", headers=headers)

    def renew_dealer_certification(self, dealer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dealers/{dealer_id}/certification-renewals", payload, headers,
        )

    def suspend_dealer(self, dealer_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers/{dealer_id}/suspend", payload, headers)

    def reinstate_dealer(self, dealer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dealers/{dealer_id}/reinstate", payload, headers,
        )

    # ------------------------------------------------------------------
    # Shipments (PRD §3.9)
    # ------------------------------------------------------------------
    def create_shipment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"{PREFIX}/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/shipments", headers=headers, params=params)

    def ship_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/ship", payload, headers,
        )

    # ------------------------------------------------------------------
    # Illness investigations (PRD §3.9)
    # ------------------------------------------------------------------
    def create_illness_investigation(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/shipments/{shipment_id}/illness-investigations",
            payload, headers,
        )

    def list_shipment_illness_investigations(self, shipment_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/shipments/{shipment_id}/illness-investigations",
            headers=headers, params=params,
        )

    def get_illness_investigation(self, investigation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/illness-investigations/{investigation_id}", headers=headers,
        )

    def run_traceback(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/illness-investigations/{investigation_id}/traceback",
            payload, headers,
        )

    def confirm_illness_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/illness-investigations/{investigation_id}/confirm",
            payload, headers,
        )

    def close_illness_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/illness-investigations/{investigation_id}/close",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Vibrio control plans (PRD §3.8)
    # ------------------------------------------------------------------
    def create_vibrio_control_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vibrio-control-plans", payload, headers)

    def get_vibrio_control_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/vibrio-control-plans/{plan_id}", headers=headers,
        )

    def list_vibrio_control_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/vibrio-control-plans", headers=headers, params=params,
        )


api_client = ApiClient()
