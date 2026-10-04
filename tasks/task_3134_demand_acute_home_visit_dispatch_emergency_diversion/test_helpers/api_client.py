"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/dh/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---- markets -----------------------------------------------------------
    def create_market(self, payload, headers):
        return self._request("POST", "/dh/markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/dh/markets", headers=headers, params=params)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/dh/markets/{market_id}", headers=headers)

    # ---- payer contracts / formulary --------------------------------------
    def create_payer_contract(self, payload, headers):
        return self._request("POST", "/dh/payer-contracts", payload, headers)

    def list_payer_contracts(self, headers, params=None):
        return self._request("GET", "/dh/payer-contracts", headers=headers, params=params)

    def get_payer_contract(self, contract_id, headers):
        return self._request("GET", f"/dh/payer-contracts/{contract_id}", headers=headers)

    def activate_payer_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/dh/payer-contracts/{contract_id}/activate", {}, headers
        )

    def terminate_payer_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/dh/payer-contracts/{contract_id}/terminate", {}, headers
        )

    def create_formulary_entry(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/dh/payer-contracts/{contract_id}/formulary-entries", payload, headers
        )

    def list_formulary_entries(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/dh/payer-contracts/{contract_id}/formulary-entries",
            headers=headers, params=params,
        )

    # ---- patients -----------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/dh/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/dh/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/dh/patients/{patient_id}", headers=headers)

    def list_patient_visit_requests(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/dh/patients/{patient_id}/visit-requests",
            headers=headers, params=params,
        )

    # ---- care teams ----------------------------------------------------------
    def create_care_team(self, payload, headers):
        return self._request("POST", "/dh/care-teams", payload, headers)

    def list_care_teams(self, headers, params=None):
        return self._request("GET", "/dh/care-teams", headers=headers, params=params)

    def get_care_team(self, team_id, headers):
        return self._request("GET", f"/dh/care-teams/{team_id}", headers=headers)

    def care_team_go_available(self, team_id, headers):
        return self._request(
            "POST", f"/dh/care-teams/{team_id}/go-available", {}, headers
        )

    def care_team_go_off_duty(self, team_id, headers):
        return self._request(
            "POST", f"/dh/care-teams/{team_id}/go-off-duty", {}, headers
        )

    # ---- vehicle shifts ------------------------------------------------------
    def create_vehicle_shift(self, payload, headers):
        return self._request("POST", "/dh/vehicle-shifts", payload, headers)

    def list_vehicle_shifts(self, headers, params=None):
        return self._request("GET", "/dh/vehicle-shifts", headers=headers, params=params)

    def get_vehicle_shift(self, shift_id, headers):
        return self._request("GET", f"/dh/vehicle-shifts/{shift_id}", headers=headers)

    def start_vehicle_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/dh/vehicle-shifts/{shift_id}/start", {}, headers
        )

    def extend_vehicle_shift(self, shift_id, payload, headers):
        return self._request(
            "POST", f"/dh/vehicle-shifts/{shift_id}/extend", payload, headers
        )

    def close_vehicle_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/dh/vehicle-shifts/{shift_id}/close", {}, headers
        )

    def cancel_vehicle_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/dh/vehicle-shifts/{shift_id}/cancel", {}, headers
        )

    # ---- visit requests -------------------------------------------------------
    def create_visit_request(self, payload, headers):
        return self._request("POST", "/dh/visit-requests", payload, headers)

    def list_visit_requests(self, headers, params=None):
        return self._request("GET", "/dh/visit-requests", headers=headers, params=params)

    def get_visit_request(self, vr_id, headers):
        return self._request("GET", f"/dh/visit-requests/{vr_id}", headers=headers)

    def list_visit_triage_assessments(self, vr_id, headers, params=None):
        return self._request(
            "GET", f"/dh/visit-requests/{vr_id}/triage-assessments",
            headers=headers, params=params,
        )

    def list_visit_dispatch_assignments(self, vr_id, headers, params=None):
        return self._request(
            "GET", f"/dh/visit-requests/{vr_id}/dispatch-assignments",
            headers=headers, params=params,
        )

    def list_visit_follow_up_notices(self, vr_id, headers, params=None):
        return self._request(
            "GET", f"/dh/visit-requests/{vr_id}/follow-up-notices",
            headers=headers, params=params,
        )

    def list_visit_monitoring_checkins(self, vr_id, headers, params=None):
        return self._request(
            "GET", f"/dh/visit-requests/{vr_id}/monitoring-checkins",
            headers=headers, params=params,
        )

    def list_visit_ems_handoffs(self, vr_id, headers, params=None):
        return self._request(
            "GET", f"/dh/visit-requests/{vr_id}/ems-handoffs",
            headers=headers, params=params,
        )

    def list_visit_encounters(self, vr_id, headers, params=None):
        return self._request(
            "GET", f"/dh/visit-requests/{vr_id}/encounters",
            headers=headers, params=params,
        )

    def list_visit_disposition_decisions(self, vr_id, headers, params=None):
        return self._request(
            "GET", f"/dh/visit-requests/{vr_id}/disposition-decisions",
            headers=headers, params=params,
        )

    def list_visit_facility_transports(self, vr_id, headers, params=None):
        return self._request(
            "GET", f"/dh/visit-requests/{vr_id}/facility-transports",
            headers=headers, params=params,
        )

    def create_triage_assessment(self, vr_id, payload, headers):
        return self._request(
            "POST", f"/dh/visit-requests/{vr_id}/triage-assessments", payload, headers
        )

    def create_dispatch_offer(self, vr_id, payload, headers):
        return self._request(
            "POST", f"/dh/visit-requests/{vr_id}/dispatch-offers", payload, headers
        )

    def create_follow_up_notice(self, vr_id, payload, headers):
        return self._request(
            "POST", f"/dh/visit-requests/{vr_id}/follow-up-notices", payload, headers
        )

    def create_monitoring_checkin(self, vr_id, payload, headers):
        return self._request(
            "POST", f"/dh/visit-requests/{vr_id}/monitoring-checkins", payload, headers
        )

    # ---- triage assessments -----------------------------------------------------
    def get_triage_assessment(self, triage_id, headers):
        return self._request(
            "GET", f"/dh/triage-assessments/{triage_id}", headers=headers
        )

    def submit_triage_assessment(self, triage_id, payload, headers):
        return self._request(
            "POST", f"/dh/triage-assessments/{triage_id}/submit", payload, headers
        )

    def get_triage_ems_handoff(self, triage_id, headers, params=None):
        return self._request(
            "GET", f"/dh/triage-assessments/{triage_id}/ems-handoff",
            headers=headers, params=params,
        )

    # ---- dispatch assignments ----------------------------------------------------
    def list_dispatch_assignments(self, headers, params=None):
        return self._request(
            "GET", "/dh/dispatch-assignments", headers=headers, params=params
        )

    def get_dispatch_assignment(self, da_id, headers):
        return self._request(
            "GET", f"/dh/dispatch-assignments/{da_id}", headers=headers
        )

    def accept_dispatch(self, da_id, headers):
        return self._request(
            "POST", f"/dh/dispatch-assignments/{da_id}/accept", {}, headers
        )

    def reject_dispatch(self, da_id, headers):
        return self._request(
            "POST", f"/dh/dispatch-assignments/{da_id}/reject", {}, headers
        )

    def cancel_dispatch(self, da_id, headers):
        return self._request(
            "POST", f"/dh/dispatch-assignments/{da_id}/cancel", {}, headers
        )

    def arrive_dispatch(self, da_id, headers):
        return self._request(
            "POST", f"/dh/dispatch-assignments/{da_id}/arrive", {}, headers
        )

    # ---- encounters -----------------------------------------------------------------
    def list_encounters(self, headers, params=None):
        return self._request("GET", "/dh/encounters", headers=headers, params=params)

    def get_encounter(self, enc_id, headers):
        return self._request("GET", f"/dh/encounters/{enc_id}", headers=headers)

    def list_encounter_diagnostic_orders(self, enc_id, headers, params=None):
        return self._request(
            "GET", f"/dh/encounters/{enc_id}/diagnostic-orders",
            headers=headers, params=params,
        )

    def create_diagnostic_order(self, enc_id, payload, headers):
        return self._request(
            "POST", f"/dh/encounters/{enc_id}/diagnostic-orders", payload, headers
        )

    def begin_disposition_review(self, enc_id, headers):
        return self._request(
            "POST", f"/dh/encounters/{enc_id}/begin-disposition-review", {}, headers
        )

    def create_disposition_decision(self, enc_id, payload, headers):
        return self._request(
            "POST", f"/dh/encounters/{enc_id}/disposition-decisions", payload, headers
        )

    def abort_encounter(self, enc_id, headers):
        return self._request(
            "POST", f"/dh/encounters/{enc_id}/abort", {}, headers
        )

    def list_encounter_disposition_decisions(self, enc_id, headers, params=None):
        return self._request(
            "GET", f"/dh/encounters/{enc_id}/disposition-decisions",
            headers=headers, params=params,
        )

    # ---- diagnostic orders ------------------------------------------------------------
    def get_diagnostic_order(self, order_id, headers):
        return self._request("GET", f"/dh/diagnostic-orders/{order_id}", headers=headers)

    def collect_diagnostic_order(self, order_id, headers):
        return self._request(
            "POST", f"/dh/diagnostic-orders/{order_id}/collect", {}, headers
        )

    def result_diagnostic_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/dh/diagnostic-orders/{order_id}/result", payload, headers
        )

    def verify_diagnostic_order(self, order_id, headers):
        return self._request(
            "POST", f"/dh/diagnostic-orders/{order_id}/verify", {}, headers
        )

    def amend_diagnostic_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/dh/diagnostic-orders/{order_id}/amend", payload, headers
        )

    def cancel_diagnostic_order(self, order_id, headers):
        return self._request(
            "POST", f"/dh/diagnostic-orders/{order_id}/cancel", {}, headers
        )

    def list_order_claim_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/dh/diagnostic-orders/{order_id}/claim-lines",
            headers=headers, params=params,
        )

    # ---- disposition decisions / facility transports -------------------------------------
    def get_disposition_decision(self, disp_id, headers):
        return self._request(
            "GET", f"/dh/disposition-decisions/{disp_id}", headers=headers
        )

    def get_disposition_facility_transport(self, disp_id, headers, params=None):
        return self._request(
            "GET", f"/dh/disposition-decisions/{disp_id}/facility-transport",
            headers=headers, params=params,
        )

    def mark_transport_arrived(self, transport_id, headers):
        return self._request(
            "POST", f"/dh/facility-transports/{transport_id}/mark-arrived", {}, headers
        )

    def cancel_transport(self, transport_id, headers):
        return self._request(
            "POST", f"/dh/facility-transports/{transport_id}/cancel", {}, headers
        )

    # ---- claims ---------------------------------------------------------------------------
    def list_claims(self, headers, params=None):
        return self._request("GET", "/dh/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/dh/claims/{claim_id}", headers=headers)

    def list_claim_lines(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/dh/claims/{claim_id}/claim-lines", headers=headers, params=params
        )

    def submit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/dh/claims/{claim_id}/submit", payload, headers
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/dh/claims/{claim_id}/adjudicate", payload, headers
        )

    def appeal_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/dh/claims/{claim_id}/appeal", {}, headers
        )

    def resubmit_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/dh/claims/{claim_id}/resubmit", {}, headers
        )

    # ---- follow-up notices --------------------------------------------------------------------
    def get_follow_up_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/dh/follow-up-notices/{notice_id}", headers=headers
        )

    def mark_notice_sent(self, notice_id, headers):
        return self._request(
            "POST", f"/dh/follow-up-notices/{notice_id}/mark-sent", {}, headers
        )

    def mark_notice_failed(self, notice_id, headers):
        return self._request(
            "POST", f"/dh/follow-up-notices/{notice_id}/mark-failed", {}, headers
        )

    # ---- monitoring check-ins -------------------------------------------------------------------
    def get_monitoring_checkin(self, chk_id, headers):
        return self._request("GET", f"/dh/monitoring-checkins/{chk_id}", headers=headers)

    def complete_monitoring_checkin(self, chk_id, payload, headers):
        return self._request(
            "POST", f"/dh/monitoring-checkins/{chk_id}/complete", payload, headers
        )

    def escalate_monitoring_checkin(self, chk_id, headers):
        return self._request(
            "POST", f"/dh/monitoring-checkins/{chk_id}/escalate", {}, headers
        )


api_client = ApiClient()
