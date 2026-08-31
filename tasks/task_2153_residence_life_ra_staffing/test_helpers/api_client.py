"""API client: one method per endpoint published by the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/residence-life"


class ApiClient(GenericApiClient):
    # ---------------- reads: single resource ----------------
    def get_building(self, building_id, headers):
        return self._request("GET", f"{PREFIX}/buildings/{building_id}", headers=headers)

    def get_floor(self, floor_id, headers):
        return self._request("GET", f"{PREFIX}/floors/{floor_id}", headers=headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"{PREFIX}/rooms/{room_id}", headers=headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"{PREFIX}/students/{student_id}", headers=headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/ra-applications/{application_id}", headers=headers
        )

    def get_ra(self, ra_id, headers):
        return self._request("GET", f"{PREFIX}/ras/{ra_id}", headers=headers)

    def get_duty_shift(self, shift_id, headers):
        return self._request("GET", f"{PREFIX}/duty-shifts/{shift_id}", headers=headers)

    def get_incident_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/incident-reports/{report_id}", headers=headers
        )

    def get_conduct_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/conduct-cases/{case_id}", headers=headers)

    def get_room_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/room-inspections/{inspection_id}", headers=headers
        )

    def get_damage_charge(self, charge_id, headers):
        return self._request(
            "GET", f"{PREFIX}/damage-charges/{charge_id}", headers=headers
        )

    def get_room_change_case(self, case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/room-change-cases/{case_id}", headers=headers
        )

    def get_program_event(self, event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/program-events/{event_id}", headers=headers
        )

    def get_break_housing_request(self, request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/break-housing-requests/{request_id}", headers=headers
        )

    # ---------------- reads: collections ----------------
    def list_buildings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/buildings", headers=headers, params=params)

    def list_floors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/floors", headers=headers, params=params)

    def list_rooms(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rooms", headers=headers, params=params)

    def list_students(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/students", headers=headers, params=params)

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/ra-applications", headers=headers, params=params
        )

    def list_ras(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ras", headers=headers, params=params)

    def list_duty_shifts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/duty-shifts", headers=headers, params=params
        )

    def list_incident_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/incident-reports", headers=headers, params=params
        )

    def list_conduct_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/conduct-cases", headers=headers, params=params
        )

    def list_room_inspections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/room-inspections", headers=headers, params=params
        )

    def list_damage_charges(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/damage-charges", headers=headers, params=params
        )

    def list_room_change_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/room-change-cases", headers=headers, params=params
        )

    def list_program_events(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/program-events", headers=headers, params=params
        )

    def list_break_housing_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/break-housing-requests", headers=headers, params=params
        )

    # ---------------- computed reads ----------------
    def get_census(self, building_id, headers):
        return self._request(
            "GET", f"{PREFIX}/buildings/{building_id}/census", headers=headers
        )

    def get_programming_summary(self, floor_id, headers):
        return self._request(
            "GET", f"{PREFIX}/floors/{floor_id}/programming-summary", headers=headers
        )

    def get_duty_load(self, ra_id, headers):
        return self._request("GET", f"{PREFIX}/ras/{ra_id}/duty-load", headers=headers)

    # ---------------- writes: housing inventory ----------------
    def create_building(self, payload, headers):
        return self._request("POST", f"{PREFIX}/buildings", payload, headers)

    def set_building_posture(self, building_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/buildings/{building_id}/posture", payload, headers
        )

    def run_consolidation(self, building_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/buildings/{building_id}/consolidation", payload, headers
        )

    def create_floor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/floors", payload, headers)

    def allocate_floor_budget(self, floor_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/floors/{floor_id}/budget-allocations", payload, headers
        )

    def create_room(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rooms", payload, headers)

    def set_room_status(self, room_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rooms/{room_id}/status", payload, headers
        )

    def create_student(self, payload, headers):
        return self._request("POST", f"{PREFIX}/students", payload, headers)

    def room_assignment(self, student_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/students/{student_id}/room-assignment", payload, headers
        )

    # ---------------- writes: RA recruitment / training / employment ----------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ra-applications", payload, headers)

    def submit_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ra-applications/{application_id}/submit", payload, headers
        )

    def review_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ra-applications/{application_id}/review", payload, headers
        )

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/ra-applications/{application_id}/decision",
            payload,
            headers,
        )

    def respond_to_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/ra-applications/{application_id}/response",
            payload,
            headers,
        )

    def log_training_module(self, ra_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ras/{ra_id}/training-records", payload, headers
        )

    def ra_certification(self, ra_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ras/{ra_id}/certification", payload, headers
        )

    def ra_employment(self, ra_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ras/{ra_id}/employment", payload, headers
        )

    def assign_ra_floor(self, ra_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/ras/{ra_id}/floor-assignment", payload, headers
        )

    # ---------------- writes: duty rotation ----------------
    def create_duty_shift(self, payload, headers):
        return self._request("POST", f"{PREFIX}/duty-shifts", payload, headers)

    def assign_duty_shift(self, shift_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/duty-shifts/{shift_id}/assignment", payload, headers
        )

    def auto_fill_duty_shift(self, shift_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/duty-shifts/{shift_id}/auto-fill", payload, headers
        )

    def swap_duty_shift(self, shift_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/duty-shifts/{shift_id}/swap", payload, headers
        )

    def duty_shift_outcome(self, shift_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/duty-shifts/{shift_id}/outcome", payload, headers
        )

    # ---------------- writes: incidents and conduct ----------------
    def create_incident_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/incident-reports", payload, headers)

    def submit_incident_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/incident-reports/{report_id}/submit", payload, headers
        )

    def triage_incident_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/incident-reports/{report_id}/triage", payload, headers
        )

    def schedule_hearing(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/conduct-cases/{case_id}/hearing", payload, headers
        )

    def decide_conduct_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/conduct-cases/{case_id}/decision", payload, headers
        )

    # ---------------- writes: inspections and damage billing ----------------
    def create_room_inspection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/room-inspections", payload, headers)

    def complete_room_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/room-inspections/{inspection_id}/completion",
            payload,
            headers,
        )

    def bill_damage_charge(self, charge_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/damage-charges/{charge_id}/billing", payload, headers
        )

    def appeal_damage_charge(self, charge_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/damage-charges/{charge_id}/appeal", payload, headers
        )

    def resolve_damage_appeal(self, charge_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/damage-charges/{charge_id}/appeal-resolution",
            payload,
            headers,
        )

    def settle_damage_charge(self, charge_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/damage-charges/{charge_id}/settlement", payload, headers
        )

    # ---------------- writes: mediation and room change ----------------
    def create_room_change_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/room-change-cases", payload, headers)

    def mediation_action(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/room-change-cases/{case_id}/mediation", payload, headers
        )

    def placement_request(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/room-change-cases/{case_id}/placement-request",
            payload,
            headers,
        )

    def placement_decision(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/room-change-cases/{case_id}/placement-decision",
            payload,
            headers,
        )

    def placement_completion(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/room-change-cases/{case_id}/placement-completion",
            payload,
            headers,
        )

    def placement_revert(self, case_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/room-change-cases/{case_id}/placement-revert",
            payload,
            headers,
        )

    # ---------------- writes: floor programming ----------------
    def create_program_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/program-events", payload, headers)

    def decide_program_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/program-events/{event_id}/decision", payload, headers
        )

    def program_event_outcome(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/program-events/{event_id}/outcome", payload, headers
        )

    def reimburse_program_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/program-events/{event_id}/reimbursement", payload, headers
        )

    # ---------------- writes: break housing ----------------
    def create_break_housing_request(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/break-housing-requests", payload, headers
        )

    def decide_break_housing_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/break-housing-requests/{request_id}/decision",
            payload,
            headers,
        )

    def break_housing_occupancy(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/break-housing-requests/{request_id}/occupancy",
            payload,
            headers,
        )

    # ---------------- the logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
