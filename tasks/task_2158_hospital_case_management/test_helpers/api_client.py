"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------------------------------------------------------- payers
    def create_payer(self, payload, headers):
        return self._request("POST", "/payers", payload, headers)

    def get_payer(self, payer_id, headers):
        return self._request("GET", f"/payers/{payer_id}", headers=headers)

    # -------------------------------------------------------------- patients
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ------------------------------------------------------------- providers
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def suspend_provider(self, provider_id, headers):
        return self._request("POST", f"/providers/{provider_id}/suspend", {}, headers)

    # ----------------------------------------------------- network contracts
    def create_network_contract(self, payload, headers):
        return self._request("POST", "/network-contracts", payload, headers)

    def get_network_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/network-contracts/{contract_id}", headers=headers
        )

    def list_network_contracts(self, headers, params=None):
        return self._request("GET", "/network-contracts", headers=headers, params=params)

    # -------------------------------------------------------------- vehicles
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def take_vehicle_out_of_service(self, vehicle_id, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/out-of-service", {}, headers
        )

    # -------------------------------------------------------------- episodes
    def create_episode(self, payload, headers):
        return self._request("POST", "/episodes", payload, headers)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/episodes/{episode_id}", headers=headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", "/episodes", headers=headers, params=params)

    def record_readmission_bundle(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/episodes/{episode_id}/readmission-bundle", payload, headers
        )

    def mark_ready(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/episodes/{episode_id}/mark-ready", payload, headers
        )

    def revert_to_planning(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/episodes/{episode_id}/revert-to-planning", payload, headers
        )

    def discharge_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/discharge", {}, headers)

    def get_throughput(self, episode_id, headers):
        return self._request(
            "GET", f"/episodes/{episode_id}/throughput", headers=headers
        )

    # ------------------------------------------------------------ screenings
    def create_screening(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/episodes/{episode_id}/screenings", payload, headers
        )

    def submit_screening(self, screening_id, headers):
        return self._request("POST", f"/screenings/{screening_id}/submit", {}, headers)

    def list_screenings(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/episodes/{episode_id}/screenings", headers=headers, params=params
        )

    # -------------------------------------------------------------- barriers
    def create_barrier(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/episodes/{episode_id}/barriers", payload, headers
        )

    def change_barrier_status(self, barrier_id, payload, headers):
        return self._request("POST", f"/barriers/{barrier_id}/status", payload, headers)

    def list_barriers(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/episodes/{episode_id}/barriers", headers=headers, params=params
        )

    # ---------------------------------------------------- referrals / offers
    def create_referral(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/episodes/{episode_id}/referrals", payload, headers
        )

    def broadcast_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/broadcast", payload, headers
        )

    def create_offer(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/offers", payload, headers
        )

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/withdraw", {}, headers)

    def document_choice(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/referrals/{referral_id}/document-choice", payload, headers
        )

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    # -------------------------------------------------------- authorizations
    def create_authorization(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/episodes/{episode_id}/authorizations", payload, headers
        )

    def decide_authorization(self, authorization_id, payload, headers):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/decide", payload, headers
        )

    def appeal_authorization(self, authorization_id, payload, headers):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/appeal", payload, headers
        )

    def get_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"/authorizations/{authorization_id}", headers=headers
        )

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    # ------------------------------------------------------ logistics orders
    def create_logistics_order(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/episodes/{episode_id}/logistics-orders", payload, headers
        )

    def confirm_logistics_order(self, order_id, headers):
        return self._request(
            "POST", f"/logistics-orders/{order_id}/confirm", {}, headers
        )

    def cancel_logistics_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/logistics-orders/{order_id}/cancel", payload, headers
        )

    def get_logistics_order(self, order_id, headers):
        return self._request("GET", f"/logistics-orders/{order_id}", headers=headers)

    def list_logistics_orders(self, headers, params=None):
        return self._request(
            "GET", "/logistics-orders", headers=headers, params=params
        )

    # ------------------------------------------------------------- raw paths
    def get_raw(self, path, headers=None, params=None):
        """Escape hatch for tests that must send a request with no auth headers."""
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
