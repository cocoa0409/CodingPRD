"""API client: one method per operation the PRD defines."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Resort ------------------------------------------------------------
    def create_resort(self, payload, headers):
        return self._request("POST", "/resorts", payload, headers)

    def get_resort(self, resort_id, headers):
        return self._request("GET", f"/resorts/{resort_id}", headers=headers)

    def update_resort(self, resort_id, payload, headers):
        return self._request("PUT", f"/resorts/{resort_id}", payload, headers)

    def add_manager(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/managers", payload, headers)

    def get_capacity(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/capacity", headers=headers, params=params)

    def get_attendance_capacity(self, resort_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/attendance-capacity", headers=headers, params=params
        )

    # --- Room types --------------------------------------------------------
    def create_room_type(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/room-types", payload, headers)

    def list_room_types(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/room-types", headers=headers, params=params)

    def get_room_type(self, resort_id, room_type_id, headers):
        return self._request("GET", f"/resorts/{resort_id}/room-types/{room_type_id}", headers=headers)

    # --- Reservations ------------------------------------------------------
    def create_reservation(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/reservations", payload, headers)

    def list_reservations(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/reservations", headers=headers, params=params)

    def get_reservation(self, resort_id, reservation_id, headers):
        return self._request("GET", f"/resorts/{resort_id}/reservations/{reservation_id}", headers=headers)

    def update_reservation(self, resort_id, reservation_id, payload, headers):
        return self._request(
            "PUT", f"/resorts/{resort_id}/reservations/{reservation_id}", payload, headers
        )

    def check_in_reservation(self, resort_id, reservation_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/reservations/{reservation_id}/check_in", headers=headers
        )

    def check_out_reservation(self, resort_id, reservation_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/reservations/{reservation_id}/check_out", headers=headers
        )

    def cancel_reservation(self, resort_id, reservation_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/reservations/{reservation_id}/cancel", headers=headers
        )

    def post_reservation_arcade_credit(self, resort_id, reservation_id, payload, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/reservations/{reservation_id}/arcade-credits", payload, headers
        )

    def list_reservation_wristbands(self, resort_id, reservation_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/reservations/{reservation_id}/wristbands",
            headers=headers, params=params,
        )

    def list_reservation_activity_bookings(self, resort_id, reservation_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/reservations/{reservation_id}/activity-bookings",
            headers=headers, params=params,
        )

    # --- Day passes --------------------------------------------------------
    def create_day_pass(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/day-passes", payload, headers)

    def list_day_passes(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/day-passes", headers=headers, params=params)

    def get_day_pass(self, resort_id, day_pass_id, headers):
        return self._request("GET", f"/resorts/{resort_id}/day-passes/{day_pass_id}", headers=headers)

    def void_day_pass(self, resort_id, day_pass_id, headers):
        return self._request("POST", f"/resorts/{resort_id}/day-passes/{day_pass_id}/void", headers=headers)

    def list_day_pass_wristbands(self, resort_id, day_pass_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/day-passes/{day_pass_id}/wristbands",
            headers=headers, params=params,
        )

    # --- Wristbands --------------------------------------------------------
    def create_wristband(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/wristbands", payload, headers)

    def list_wristbands(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/wristbands", headers=headers, params=params)

    def get_wristband(self, resort_id, wristband_id, headers):
        return self._request("GET", f"/resorts/{resort_id}/wristbands/{wristband_id}", headers=headers)

    def activate_wristband(self, resort_id, wristband_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/wristbands/{wristband_id}/activate", headers=headers
        )

    def revoke_wristband(self, resort_id, wristband_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/wristbands/{wristband_id}/revoke", headers=headers
        )

    def reissue_wristband(self, resort_id, wristband_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/wristbands/{wristband_id}/reissue", headers=headers
        )

    def post_arcade_grant(self, resort_id, wristband_id, payload, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/wristbands/{wristband_id}/arcade-grants", payload, headers
        )

    def post_arcade_redeem(self, resort_id, wristband_id, payload, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/wristbands/{wristband_id}/arcade-redeem", payload, headers
        )

    def list_wristband_arcade_credits(self, resort_id, wristband_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/wristbands/{wristband_id}/arcade-credits",
            headers=headers, params=params,
        )

    def list_wristband_successors(self, resort_id, wristband_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/wristbands/{wristband_id}/successors",
            headers=headers, params=params,
        )

    # --- Attractions -------------------------------------------------------
    def create_attraction(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/attractions", payload, headers)

    def list_attractions(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/attractions", headers=headers, params=params)

    def get_attraction(self, resort_id, attraction_id, headers):
        return self._request("GET", f"/resorts/{resort_id}/attractions/{attraction_id}", headers=headers)

    def list_attraction_water_quality_logs(self, resort_id, attraction_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/attractions/{attraction_id}/water-quality-logs",
            headers=headers, params=params,
        )

    def run_ops(self, resort_id, attraction_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/attractions/{attraction_id}/run_ops", headers=headers
        )

    # --- Lifeguard shifts --------------------------------------------------
    def create_lifeguard_shift(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/lifeguard-shifts", payload, headers)

    def list_lifeguard_shifts(self, resort_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/lifeguard-shifts", headers=headers, params=params
        )

    def get_lifeguard_shift(self, resort_id, shift_id, headers):
        return self._request("GET", f"/resorts/{resort_id}/lifeguard-shifts/{shift_id}", headers=headers)

    def start_lifeguard_shift(self, resort_id, shift_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/lifeguard-shifts/{shift_id}/start", headers=headers
        )

    def rotate_lifeguard_shift(self, resort_id, shift_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/lifeguard-shifts/{shift_id}/rotate", headers=headers
        )

    def resume_lifeguard_shift(self, resort_id, shift_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/lifeguard-shifts/{shift_id}/resume", headers=headers
        )

    def complete_lifeguard_shift(self, resort_id, shift_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/lifeguard-shifts/{shift_id}/complete", headers=headers
        )

    # --- Water quality -----------------------------------------------------
    def create_water_quality_log(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/water-quality-logs", payload, headers)

    def list_water_quality_logs(self, resort_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/water-quality-logs", headers=headers, params=params
        )

    def get_water_quality_log(self, resort_id, log_id, headers):
        return self._request("GET", f"/resorts/{resort_id}/water-quality-logs/{log_id}", headers=headers)

    def supersede_water_quality_log(self, resort_id, log_id, payload, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/water-quality-logs/{log_id}/supersede", payload, headers
        )

    # --- Admissions --------------------------------------------------------
    def post_admission(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/admissions", payload, headers)

    def list_admissions(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/admissions", headers=headers, params=params)

    def get_admission(self, resort_id, admission_event_id, headers):
        return self._request(
            "GET", f"/resorts/{resort_id}/admissions/{admission_event_id}", headers=headers
        )

    # --- Cabanas -----------------------------------------------------------
    def create_cabana(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/cabanas", payload, headers)

    def list_cabanas(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/cabanas", headers=headers, params=params)

    def get_cabana(self, resort_id, cabana_id, headers):
        return self._request("GET", f"/resorts/{resort_id}/cabanas/{cabana_id}", headers=headers)

    def list_cabana_bookings_for_cabana(self, resort_id, cabana_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/cabanas/{cabana_id}/bookings", headers=headers, params=params
        )

    def create_cabana_booking(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/cabana-bookings", payload, headers)

    def list_cabana_bookings(self, resort_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/cabana-bookings", headers=headers, params=params
        )

    def get_cabana_booking(self, resort_id, cabana_booking_id, headers):
        return self._request(
            "GET", f"/resorts/{resort_id}/cabana-bookings/{cabana_booking_id}", headers=headers
        )

    def confirm_cabana_booking(self, resort_id, cabana_booking_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/cabana-bookings/{cabana_booking_id}/confirm", headers=headers
        )

    def cancel_cabana_booking(self, resort_id, cabana_booking_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/cabana-bookings/{cabana_booking_id}/cancel", headers=headers
        )

    def release_cabana_booking(self, resort_id, cabana_booking_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/cabana-bookings/{cabana_booking_id}/release", headers=headers
        )

    def expire_cabana_holds(self, resort_id, headers):
        return self._request("POST", f"/resorts/{resort_id}/cabana-bookings/expire_holds", headers=headers)

    # --- Group bookings ----------------------------------------------------
    def create_group_booking(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/group-bookings", payload, headers)

    def list_group_bookings(self, resort_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/group-bookings", headers=headers, params=params
        )

    def get_group_booking(self, resort_id, group_booking_id, headers):
        return self._request(
            "GET", f"/resorts/{resort_id}/group-bookings/{group_booking_id}", headers=headers
        )

    def post_group_deposit(self, resort_id, group_booking_id, payload, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/group-bookings/{group_booking_id}/deposits", payload, headers
        )

    def confirm_group_booking(self, resort_id, group_booking_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/group-bookings/{group_booking_id}/confirm", headers=headers
        )

    def cancel_group_booking(self, resort_id, group_booking_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/group-bookings/{group_booking_id}/cancel", headers=headers
        )

    def list_group_members_for_group(self, resort_id, group_booking_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/group-bookings/{group_booking_id}/members",
            headers=headers, params=params,
        )

    def list_cabana_bookings_for_group(self, resort_id, group_booking_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/group-bookings/{group_booking_id}/cabana-bookings",
            headers=headers, params=params,
        )

    def list_activity_bookings_for_group(self, resort_id, group_booking_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/group-bookings/{group_booking_id}/activity-bookings",
            headers=headers, params=params,
        )

    def list_admissions_for_group(self, resort_id, group_booking_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/group-bookings/{group_booking_id}/admissions",
            headers=headers, params=params,
        )

    # --- Group members -----------------------------------------------------
    def create_group_member(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/group-members", payload, headers)

    def list_group_members(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/group-members", headers=headers, params=params)

    def get_group_member(self, resort_id, group_member_id, headers):
        return self._request(
            "GET", f"/resorts/{resort_id}/group-members/{group_member_id}", headers=headers
        )

    # --- Activities --------------------------------------------------------
    def create_activity_session(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/activities", payload, headers)

    def list_activity_sessions(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/activities", headers=headers, params=params)

    def get_activity_session(self, resort_id, activity_session_id, headers):
        return self._request(
            "GET", f"/resorts/{resort_id}/activities/{activity_session_id}", headers=headers
        )

    def create_activity_booking(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/activity-bookings", payload, headers)

    def list_activity_bookings(self, resort_id, headers, params=None):
        return self._request(
            "GET", f"/resorts/{resort_id}/activity-bookings", headers=headers, params=params
        )

    def get_activity_booking(self, resort_id, activity_booking_id, headers):
        return self._request(
            "GET", f"/resorts/{resort_id}/activity-bookings/{activity_booking_id}", headers=headers
        )

    def confirm_activity_booking(self, resort_id, activity_booking_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/activity-bookings/{activity_booking_id}/confirm",
            headers=headers,
        )

    def cancel_activity_booking(self, resort_id, activity_booking_id, headers):
        return self._request(
            "POST", f"/resorts/{resort_id}/activity-bookings/{activity_booking_id}/cancel",
            headers=headers,
        )

    # --- Arcade credits ----------------------------------------------------
    def list_arcade_credits(self, resort_id, headers, params=None):
        return self._request("GET", f"/resorts/{resort_id}/arcade-credits", headers=headers, params=params)

    def get_arcade_credit(self, resort_id, grant_id, headers):
        return self._request("GET", f"/resorts/{resort_id}/arcade-credits/{grant_id}", headers=headers)

    # --- Test-driving ------------------------------------------------------
    def set_current_utc(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/_clock/set_current_utc", payload, headers)

    def simulate_payment(self, resort_id, payload, headers):
        return self._request("POST", f"/resorts/{resort_id}/_payments/simulate", payload, headers)


api_client = ApiClient()