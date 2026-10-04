"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- hospitals ---
    def create_hospital(self, payload, headers):
        return self._request("POST", "/api/hospitals", payload, headers)

    def get_hospital(self, hospital_id, headers):
        return self._request("GET", f"/api/hospitals/{hospital_id}", headers=headers)

    def list_hospital_houses(self, hospital_id, headers, params=None):
        return self._request("GET", f"/api/hospitals/{hospital_id}/houses", headers=headers, params=params)

    def list_hospital_referrals(self, hospital_id, headers, params=None):
        return self._request("GET", f"/api/hospitals/{hospital_id}/referrals", headers=headers, params=params)

    def list_hospital_care_spaces(self, hospital_id, headers, params=None):
        return self._request("GET", f"/api/hospitals/{hospital_id}/care-spaces", headers=headers, params=params)

    # --- houses / rooms ---
    def create_house(self, payload, headers):
        return self._request("POST", "/api/houses", payload, headers)

    def get_house(self, house_id, headers):
        return self._request("GET", f"/api/houses/{house_id}", headers=headers)

    def get_supply_inventory(self, house_id, headers):
        return self._request("GET", f"/api/houses/{house_id}/supply-inventory", headers=headers)

    def create_room(self, house_id, payload, headers):
        return self._request("POST", f"/api/houses/{house_id}/rooms", payload, headers)

    def list_rooms(self, house_id, headers, params=None):
        return self._request("GET", f"/api/houses/{house_id}/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/api/rooms/{room_id}", headers=headers)

    def list_room_stay_requests(self, room_id, headers, params=None):
        return self._request("GET", f"/api/rooms/{room_id}/stay-requests", headers=headers, params=params)

    def set_room_status(self, room_id, payload, headers):
        return self._request("POST", f"/api/rooms/{room_id}/set-status", payload, headers)

    # --- families ---
    def create_family(self, payload, headers):
        return self._request("POST", "/api/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/api/families/{family_id}", headers=headers)

    def list_family_referrals(self, family_id, headers, params=None):
        return self._request("GET", f"/api/families/{family_id}/referrals", headers=headers, params=params)

    def list_family_stay_requests(self, family_id, headers, params=None):
        return self._request("GET", f"/api/families/{family_id}/stay-requests", headers=headers, params=params)

    def list_family_care_space_bookings(self, family_id, headers, params=None):
        return self._request("GET", f"/api/families/{family_id}/care-space-bookings", headers=headers, params=params)

    # --- referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/api/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/api/referrals/{referral_id}", headers=headers)

    def verify_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/api/referrals/{referral_id}/verify", payload, headers)

    def revoke_referral(self, referral_id, headers):
        return self._request("POST", f"/api/referrals/{referral_id}/revoke", {}, headers)

    # --- stay requests ---
    def create_stay_request(self, payload, headers):
        return self._request("POST", "/api/stay-requests", payload, headers)

    def get_stay_request(self, request_id, headers):
        return self._request("GET", f"/api/stay-requests/{request_id}", headers=headers)

    def list_stay_requests(self, headers, params=None):
        return self._request("GET", "/api/stay-requests", headers=headers, params=params)

    def offer_stay_request(self, request_id, payload, headers):
        return self._request("POST", f"/api/stay-requests/{request_id}/offer", payload, headers)

    def respond_stay_request(self, request_id, payload, headers):
        return self._request("POST", f"/api/stay-requests/{request_id}/respond", payload, headers)

    def cancel_stay_request(self, request_id, headers):
        return self._request("POST", f"/api/stay-requests/{request_id}/cancel", {}, headers)

    def check_in_stay_request(self, request_id, headers):
        return self._request("POST", f"/api/stay-requests/{request_id}/check-in", {}, headers)

    # --- stays ---
    def get_stay(self, stay_id, headers):
        return self._request("GET", f"/api/stays/{stay_id}", headers=headers)

    def list_stays(self, headers, params=None):
        return self._request("GET", "/api/stays", headers=headers, params=params)

    def register_guest(self, stay_id, payload, headers):
        return self._request("POST", f"/api/stays/{stay_id}/guests", payload, headers)

    def list_guests(self, stay_id, headers, params=None):
        return self._request("GET", f"/api/stays/{stay_id}/guests", headers=headers, params=params)

    def record_screening(self, stay_id, payload, headers):
        return self._request("POST", f"/api/stays/{stay_id}/screenings", payload, headers)

    def list_screenings(self, stay_id, headers, params=None):
        return self._request("GET", f"/api/stays/{stay_id}/screenings", headers=headers, params=params)

    def request_extension(self, stay_id, payload, headers):
        return self._request("POST", f"/api/stays/{stay_id}/request-extension", payload, headers)

    def review_stay(self, stay_id, payload, headers):
        return self._request("POST", f"/api/stays/{stay_id}/review", payload, headers)

    def check_out_stay(self, stay_id, headers):
        return self._request("POST", f"/api/stays/{stay_id}/check-out", {}, headers)

    # --- contribution requests ---
    def create_contribution_request(self, stay_id, payload, headers):
        return self._request("POST", f"/api/stays/{stay_id}/contribution-requests", payload, headers)

    def list_contribution_requests(self, stay_id, headers, params=None):
        return self._request("GET", f"/api/stays/{stay_id}/contribution-requests", headers=headers, params=params)

    def get_contribution_request(self, cr_id, headers):
        return self._request("GET", f"/api/contribution-requests/{cr_id}", headers=headers)

    def record_payment(self, cr_id, payload, headers):
        return self._request("POST", f"/api/contribution-requests/{cr_id}/record-payment", payload, headers)

    def waive_contribution_request(self, cr_id, headers):
        return self._request("POST", f"/api/contribution-requests/{cr_id}/waive", {}, headers)

    # --- volunteer program ---
    def create_volunteer_group(self, payload, headers):
        return self._request("POST", "/api/volunteer-groups", payload, headers)

    def get_volunteer_group(self, group_id, headers):
        return self._request("GET", f"/api/volunteer-groups/{group_id}", headers=headers)

    def certify_volunteer_group(self, group_id, payload, headers):
        return self._request("POST", f"/api/volunteer-groups/{group_id}/certify", payload, headers)

    def list_group_meal_shifts(self, group_id, headers, params=None):
        return self._request("GET", f"/api/volunteer-groups/{group_id}/meal-shifts", headers=headers, params=params)

    def create_meal_shift(self, house_id, payload, headers):
        return self._request("POST", f"/api/houses/{house_id}/meal-shifts", payload, headers)

    def list_meal_shifts(self, house_id, headers, params=None):
        return self._request("GET", f"/api/houses/{house_id}/meal-shifts", headers=headers, params=params)

    def claim_meal_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/api/meal-shifts/{shift_id}/claim", payload, headers)

    def complete_meal_shift(self, shift_id, payload, headers):
        return self._request("POST", f"/api/meal-shifts/{shift_id}/complete", payload, headers)

    def cancel_meal_shift(self, shift_id, headers):
        return self._request("POST", f"/api/meal-shifts/{shift_id}/cancel", {}, headers)

    # --- care spaces ---
    def create_care_space(self, hospital_id, payload, headers):
        return self._request("POST", f"/api/hospitals/{hospital_id}/care-spaces", payload, headers)

    def get_care_space(self, care_space_id, headers):
        return self._request("GET", f"/api/care-spaces/{care_space_id}", headers=headers)

    def create_care_space_booking(self, care_space_id, payload, headers):
        return self._request("POST", f"/api/care-spaces/{care_space_id}/bookings", payload, headers)

    def list_care_space_bookings(self, care_space_id, headers, params=None):
        return self._request("GET", f"/api/care-spaces/{care_space_id}/bookings", headers=headers, params=params)

    def cancel_care_space_booking(self, booking_id, headers):
        return self._request("POST", f"/api/care-space-bookings/{booking_id}/cancel", {}, headers)

    # --- in-kind donations ---
    def create_in_kind_donation(self, house_id, payload, headers):
        return self._request("POST", f"/api/houses/{house_id}/in-kind-donations", payload, headers)

    def list_in_kind_donations(self, house_id, headers, params=None):
        return self._request("GET", f"/api/houses/{house_id}/in-kind-donations", headers=headers, params=params)

    def distribute_in_kind_donation(self, donation_id, payload, headers):
        return self._request("POST", f"/api/in-kind-donations/{donation_id}/distribute", payload, headers)

    # --- ops sweeps ---
    def run_assignment_sweep(self, house_id, headers):
        return self._request("POST", f"/api/houses/{house_id}/run-assignment-sweep", {}, headers)

    def run_stay_review_sweep(self, house_id, headers):
        return self._request("POST", f"/api/houses/{house_id}/run-stay-review-sweep", {}, headers)


api_client = ApiClient()
