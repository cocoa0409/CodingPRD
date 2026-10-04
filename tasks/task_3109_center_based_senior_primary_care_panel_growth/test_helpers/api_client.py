"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ---------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---- centers ----------------------------------------------------------
    def create_center(self, payload, headers):
        return self._request("POST", "/senior-care/centers", payload, headers)

    def list_centers(self, headers, params=None):
        return self._request("GET", "/senior-care/centers", headers=headers, params=params)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/senior-care/centers/{center_id}", headers=headers)

    def open_center(self, center_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/centers/{center_id}/open", payload or {}, headers
        )

    def close_center(self, center_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/centers/{center_id}/close", payload or {}, headers
        )

    # ---- care teams -------------------------------------------------------
    def create_care_team(self, center_id, payload, headers):
        return self._request(
            "POST", f"/senior-care/centers/{center_id}/care-teams", payload, headers
        )

    def list_care_teams(self, headers, params=None):
        return self._request("GET", "/senior-care/care-teams", headers=headers, params=params)

    def list_center_care_teams(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/senior-care/centers/{center_id}/care-teams", headers=headers, params=params
        )

    def get_care_team(self, team_id, headers):
        return self._request("GET", f"/senior-care/care-teams/{team_id}", headers=headers)

    def patch_care_team(self, team_id, payload, headers):
        return self._request("PATCH", f"/senior-care/care-teams/{team_id}", payload, headers)

    def list_team_attributions(self, team_id, headers, params=None):
        return self._request(
            "GET", f"/senior-care/care-teams/{team_id}/attributions", headers=headers, params=params
        )

    def list_team_appointments(self, team_id, headers, params=None):
        return self._request(
            "GET", f"/senior-care/care-teams/{team_id}/appointments", headers=headers, params=params
        )

    # ---- rooms ------------------------------------------------------------
    def create_room(self, center_id, payload, headers):
        return self._request(
            "POST", f"/senior-care/centers/{center_id}/rooms", payload, headers
        )

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/senior-care/rooms", headers=headers, params=params)

    def list_center_rooms(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/senior-care/centers/{center_id}/rooms", headers=headers, params=params
        )

    def get_room(self, room_id, headers):
        return self._request("GET", f"/senior-care/rooms/{room_id}", headers=headers)

    # ---- vehicles ---------------------------------------------------------
    def create_vehicle(self, center_id, payload, headers):
        return self._request(
            "POST", f"/senior-care/centers/{center_id}/vehicles", payload, headers
        )

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/senior-care/vehicles", headers=headers, params=params)

    def list_center_vehicles(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/senior-care/centers/{center_id}/vehicles", headers=headers, params=params
        )

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/senior-care/vehicles/{vehicle_id}", headers=headers)

    def list_vehicle_ride_requests(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/senior-care/vehicles/{vehicle_id}/ride-requests",
            headers=headers, params=params,
        )

    # ---- outreach events --------------------------------------------------
    def create_outreach_event(self, center_id, payload, headers):
        return self._request(
            "POST", f"/senior-care/centers/{center_id}/outreach-events", payload, headers
        )

    def list_outreach_events(self, headers, params=None):
        return self._request(
            "GET", "/senior-care/outreach-events", headers=headers, params=params
        )

    def list_center_outreach_events(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/senior-care/centers/{center_id}/outreach-events",
            headers=headers, params=params,
        )

    def get_outreach_event(self, event_id, headers):
        return self._request(
            "GET", f"/senior-care/outreach-events/{event_id}", headers=headers
        )

    # ---- patients ---------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/senior-care/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/senior-care/patients/{patient_id}", headers=headers)

    def list_patient_attributions(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/senior-care/patients/{patient_id}/attributions",
            headers=headers, params=params,
        )

    def list_patient_triage_cases(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/senior-care/patients/{patient_id}/triage-cases",
            headers=headers, params=params,
        )

    # ---- health plans -----------------------------------------------------
    def create_health_plan(self, payload, headers):
        return self._request("POST", "/senior-care/health-plans", payload, headers)

    def get_health_plan(self, plan_id, headers):
        return self._request("GET", f"/senior-care/health-plans/{plan_id}", headers=headers)

    def get_plan_quote(self, plan_id, params, headers):
        return self._request(
            "GET", f"/senior-care/health-plans/{plan_id}/quote", headers=headers, params=params
        )

    # ---- patient attributions ---------------------------------------------
    def create_attribution(self, payload, headers):
        return self._request("POST", "/senior-care/patient-attributions", payload, headers)

    def list_attributions(self, headers, params=None):
        return self._request(
            "GET", "/senior-care/patient-attributions", headers=headers, params=params
        )

    def get_attribution(self, attribution_id, headers):
        return self._request(
            "GET", f"/senior-care/patient-attributions/{attribution_id}", headers=headers
        )

    def activate_attribution(self, attribution_id, payload, headers):
        return self._request(
            "POST", f"/senior-care/patient-attributions/{attribution_id}/activate",
            payload, headers,
        )

    def disenroll_attribution(self, attribution_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/patient-attributions/{attribution_id}/disenroll",
            payload or {}, headers,
        )

    def reattribute_attribution(self, attribution_id, payload, headers):
        return self._request(
            "POST", f"/senior-care/patient-attributions/{attribution_id}/reattribute",
            payload, headers,
        )

    # ---- appointments -----------------------------------------------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/senior-care/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/senior-care/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/senior-care/appointments/{appointment_id}", headers=headers
        )

    def check_in_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/appointments/{appointment_id}/check-in",
            payload or {}, headers,
        )

    def complete_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/appointments/{appointment_id}/complete",
            payload or {}, headers,
        )

    def cancel_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/appointments/{appointment_id}/cancel",
            payload or {}, headers,
        )

    def create_ride_request(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/appointments/{appointment_id}/ride-requests",
            payload or {}, headers,
        )

    def list_appointment_ride_requests(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/senior-care/appointments/{appointment_id}/ride-requests",
            headers=headers, params=params,
        )

    # ---- ride requests ----------------------------------------------------
    def list_ride_requests(self, headers, params=None):
        return self._request("GET", "/senior-care/ride-requests", headers=headers, params=params)

    def get_ride_request(self, ride_id, headers):
        return self._request("GET", f"/senior-care/ride-requests/{ride_id}", headers=headers)

    def dispatch_ride(self, ride_id, payload, headers):
        return self._request(
            "POST", f"/senior-care/ride-requests/{ride_id}/dispatch", payload, headers
        )

    def start_pickup_ride(self, ride_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/ride-requests/{ride_id}/start-pickup",
            payload or {}, headers,
        )

    def mark_no_show_ride(self, ride_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/ride-requests/{ride_id}/mark-no-show",
            payload or {}, headers,
        )

    def recover_ride(self, ride_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/ride-requests/{ride_id}/recover",
            payload or {}, headers,
        )

    # ---- triage cases -----------------------------------------------------
    def create_triage_case(self, payload, headers):
        return self._request("POST", "/senior-care/triage-cases", payload, headers)

    def list_triage_cases(self, headers, params=None):
        return self._request("GET", "/senior-care/triage-cases", headers=headers, params=params)

    def get_triage_case(self, case_id, headers):
        return self._request("GET", f"/senior-care/triage-cases/{case_id}", headers=headers)

    def divert_triage_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/senior-care/triage-cases/{case_id}/divert", payload, headers
        )

    def refer_ed_triage_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/triage-cases/{case_id}/refer-ed",
            payload or {}, headers,
        )

    def advise_self_care_triage_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/triage-cases/{case_id}/advise-self-care",
            payload or {}, headers,
        )

    # ---- cost claims ------------------------------------------------------
    def create_cost_claim(self, payload, headers):
        return self._request("POST", "/senior-care/cost-claims", payload, headers)

    def list_cost_claims(self, headers, params=None):
        return self._request("GET", "/senior-care/cost-claims", headers=headers, params=params)

    def get_cost_claim(self, claim_id, headers):
        return self._request("GET", f"/senior-care/cost-claims/{claim_id}", headers=headers)

    def adjudicate_cost_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/senior-care/cost-claims/{claim_id}/adjudicate", payload, headers
        )

    def reject_cost_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/cost-claims/{claim_id}/reject", payload or {}, headers
        )

    # ---- monthly settlements ----------------------------------------------
    def create_monthly_settlement(self, payload, headers):
        return self._request("POST", "/senior-care/monthly-settlements", payload, headers)

    def list_monthly_settlements(self, headers, params=None):
        return self._request(
            "GET", "/senior-care/monthly-settlements", headers=headers, params=params
        )

    def get_monthly_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/senior-care/monthly-settlements/{settlement_id}", headers=headers
        )

    def close_provisional_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/senior-care/monthly-settlements/{settlement_id}/close-provisional",
            payload, headers,
        )

    def finalize_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/monthly-settlements/{settlement_id}/finalize",
            payload or {}, headers,
        )

    def void_settlement(self, settlement_id, headers, payload=None):
        return self._request(
            "POST", f"/senior-care/monthly-settlements/{settlement_id}/void",
            payload or {}, headers,
        )


api_client = ApiClient()
