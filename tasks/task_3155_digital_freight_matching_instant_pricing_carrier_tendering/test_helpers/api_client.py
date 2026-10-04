"""API client: one method per operation declared in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/v1"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- platform
    def set_current_utc(self, current_utc, headers):
        return self._request("POST", f"{API_PREFIX}/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def run_sweep(self, headers):
        return self._request("POST", f"{API_PREFIX}/_ops/sweep", {}, headers)

    # ----------------------------------------------------------------- shipper
    def create_shipper(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/shippers", payload, headers)

    def get_shipper(self, shipper_id, headers):
        return self._request("GET", f"{API_PREFIX}/shippers/{shipper_id}", headers=headers)

    def suspend_shipper(self, shipper_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/shippers/{shipper_id}/suspend",
                             payload, headers)

    def list_shipper_loads(self, shipper_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/shippers/{shipper_id}/loads",
                             params, headers)

    def list_shipper_lane_contracts(self, shipper_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/shippers/{shipper_id}/lane-contracts",
                             params, headers)

    # ----------------------------------------------------------------- carrier
    def create_carrier(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"{API_PREFIX}/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/carriers", params, headers)

    def verify_authority(self, carrier_id, headers):
        return self._request("POST", f"{API_PREFIX}/carriers/{carrier_id}/verify-authority",
                             {}, headers)

    def attest_insurance(self, carrier_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/carriers/{carrier_id}/attest-insurance",
                             payload, headers)

    def verify_safety(self, carrier_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/carriers/{carrier_id}/verify-safety",
                             payload, headers)

    def suspend_carrier(self, carrier_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/carriers/{carrier_id}/suspend",
                             payload, headers)

    def reinstate_carrier(self, carrier_id, headers):
        return self._request("POST", f"{API_PREFIX}/carriers/{carrier_id}/reinstate",
                             {}, headers)

    def list_carrier_equipment(self, carrier_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/carriers/{carrier_id}/equipment",
                             params, headers)

    def list_carrier_bookings(self, carrier_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/carriers/{carrier_id}/bookings",
                             params, headers)

    def list_carrier_claims(self, carrier_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/carriers/{carrier_id}/claims",
                             params, headers)

    # -------------------------------------------------------- carrier equipment
    def create_equipment(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/carrier-equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"{API_PREFIX}/carrier-equipment/{equipment_id}",
                             headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/carrier-equipment", params, headers)

    def set_equipment_status(self, equipment_id, status, headers):
        return self._request("POST", f"{API_PREFIX}/carrier-equipment/{equipment_id}/status",
                             {"status": status}, headers)

    # ---------------------------------------------------------------- facility
    def create_facility(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"{API_PREFIX}/facilities/{facility_id}", headers=headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/facilities", params, headers)

    def list_facility_appointments(self, facility_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/facilities/{facility_id}/appointments",
                             params, headers)

    def list_facility_detention_events(self, facility_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/facilities/{facility_id}/detention-events",
                             params, headers)

    def list_facility_lane_contracts(self, facility_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/facilities/{facility_id}/lane-contracts",
                             params, headers)

    # ------------------------------------------------------------ lane contract
    def create_lane_contract(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/lane-contracts", payload, headers)

    def get_lane_contract(self, contract_id, headers):
        return self._request("GET", f"{API_PREFIX}/lane-contracts/{contract_id}",
                             headers=headers)

    def list_lane_contracts(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/lane-contracts", params, headers)

    def activate_lane_contract(self, contract_id, headers):
        return self._request("POST", f"{API_PREFIX}/lane-contracts/{contract_id}/activate",
                             {}, headers)

    def list_lane_contract_loads(self, contract_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/lane-contracts/{contract_id}/loads",
                             params, headers)

    # -------------------------------------------------------------------- load
    def create_load(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/loads", payload, headers)

    def get_load(self, load_id, headers):
        return self._request("GET", f"{API_PREFIX}/loads/{load_id}", headers=headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/loads", params, headers)

    def post_load(self, load_id, headers):
        return self._request("POST", f"{API_PREFIX}/loads/{load_id}/post", {}, headers)

    def reprice_load(self, load_id, new_market_band, headers):
        return self._request("POST", f"{API_PREFIX}/loads/{load_id}/reprice",
                             {"new_market_band": new_market_band}, headers)

    def repost_load(self, load_id, expected_shipper_version, headers):
        return self._request("POST", f"{API_PREFIX}/loads/{load_id}/repost",
                             {"expected_shipper_version": expected_shipper_version}, headers)

    def cancel_load(self, load_id, headers):
        return self._request("POST", f"{API_PREFIX}/loads/{load_id}/cancel", {}, headers)

    def void_load(self, load_id, retry_idempotency_key, headers):
        return self._request("POST", f"{API_PREFIX}/loads/{load_id}/void",
                             {"retry_idempotency_key": retry_idempotency_key}, headers)

    def report_tracking_ping(self, load_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/loads/{load_id}/tracking-pings",
                             payload, headers)

    def list_load_tracking_pings(self, load_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/loads/{load_id}/tracking-pings",
                             params, headers)

    def list_load_status_events(self, load_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/loads/{load_id}/status-events",
                             params, headers)

    def list_load_rate_quotes(self, load_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/loads/{load_id}/rate-quotes",
                             params, headers)

    def list_load_appointments(self, load_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/loads/{load_id}/appointments",
                             params, headers)

    def list_load_detention_events(self, load_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/loads/{load_id}/detention-events",
                             params, headers)

    def list_load_claims(self, load_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/loads/{load_id}/claims", params, headers)

    def list_load_settlements(self, load_id, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/loads/{load_id}/carrier-settlements",
                             params, headers)

    # -------------------------------------------------------------- rate quote
    def get_rate_quote(self, quote_id, headers):
        return self._request("GET", f"{API_PREFIX}/rate-quotes/{quote_id}", headers=headers)

    def list_rate_quotes(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/rate-quotes", params, headers)

    def view_rate_quote(self, quote_id, headers):
        return self._request("POST", f"{API_PREFIX}/rate-quotes/{quote_id}/view", {}, headers)

    def decline_rate_quote(self, quote_id, headers):
        return self._request("POST", f"{API_PREFIX}/rate-quotes/{quote_id}/decline", {}, headers)

    # ----------------------------------------------------------------- booking
    def create_booking(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{API_PREFIX}/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/bookings", params, headers)

    def create_booking_appointment(self, booking_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/appointments",
                             payload, headers)

    def invoice_booking(self, booking_id, headers):
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/invoice", {}, headers)

    def cancel_booking_in_transit(self, booking_id, reason_code, headers):
        return self._request("POST", f"{API_PREFIX}/bookings/{booking_id}/cancel-in-transit",
                             {"reason_code": reason_code}, headers)

    # ------------------------------------------------------------- appointment
    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"{API_PREFIX}/appointments/{appointment_id}",
                             headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/appointments", params, headers)

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/appointments/{appointment_id}/reschedule",
                             payload, headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"{API_PREFIX}/appointments/{appointment_id}/complete",
                             {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"{API_PREFIX}/appointments/{appointment_id}/cancel",
                             {}, headers)

    def restore_appointment(self, appointment_id, headers):
        return self._request("POST", f"{API_PREFIX}/appointments/{appointment_id}/restore",
                             {}, headers)

    # ---------------------------------------------------------------- detention
    def get_detention_event(self, detention_id, headers):
        return self._request("GET", f"{API_PREFIX}/detention-events/{detention_id}",
                             headers=headers)

    def list_detention_events(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/detention-events", params, headers)

    def waive_detention_event(self, detention_id, reason_code, headers):
        return self._request("POST", f"{API_PREFIX}/detention-events/{detention_id}/waive",
                             {"reason_code": reason_code}, headers)

    # ------------------------------------------------------------ tracking ping
    def get_tracking_ping(self, ping_id, headers):
        return self._request("GET", f"{API_PREFIX}/tracking-pings/{ping_id}", headers=headers)

    def list_tracking_pings(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/tracking-pings", params, headers)

    # ------------------------------------------------------------- status event
    def get_status_event(self, event_id, headers):
        return self._request("GET", f"{API_PREFIX}/status-events/{event_id}", headers=headers)

    def list_status_events(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/status-events", params, headers)

    def append_status_event(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/status-events", payload, headers)

    # ------------------------------------------------------------------- claim
    def file_claim(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{API_PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/claims", params, headers)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"{API_PREFIX}/claims/{claim_id}/review", {}, headers)

    def request_claim_info(self, claim_id, note, headers):
        return self._request("POST", f"{API_PREFIX}/claims/{claim_id}/request-info",
                             {"note": note}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"{API_PREFIX}/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, reason_code, headers):
        return self._request("POST", f"{API_PREFIX}/claims/{claim_id}/deny",
                             {"reason_code": reason_code}, headers)

    def escalate_claim(self, claim_id, headers):
        return self._request("POST", f"{API_PREFIX}/claims/{claim_id}/escalate", {}, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"{API_PREFIX}/claims/{claim_id}/settle", {}, headers)

    # -------------------------------------------------------------- settlement
    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"{API_PREFIX}/carrier-settlements/{settlement_id}",
                             headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/carrier-settlements", params, headers)

    def unready_settlement(self, settlement_id, headers):
        return self._request("POST", f"{API_PREFIX}/carrier-settlements/{settlement_id}/unready",
                             {}, headers)

    def payout_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"{API_PREFIX}/carrier-settlements/{settlement_id}/payout",
                             payload, headers)

    def clawback_settlement(self, settlement_id, headers):
        return self._request("POST", f"{API_PREFIX}/carrier-settlements/{settlement_id}/clawback",
                             {}, headers)


api_client = ApiClient()