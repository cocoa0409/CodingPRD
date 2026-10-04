"""API client: one method per endpoint defined in the PRD Section 4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Fleets ---
    def create_fleet(self, payload, headers):
        return self._request("POST", "/api/fleets", payload, headers)

    def get_fleet(self, fleet_id, headers):
        return self._request("GET", f"/api/fleets/{fleet_id}", headers=headers)

    def set_fleet_posture(self, fleet_id, payload, headers):
        return self._request("POST", f"/api/fleets/{fleet_id}/posture", payload, headers)

    def get_leaderboard(self, fleet_id, headers, params=None):
        return self._request("GET", f"/api/fleets/{fleet_id}/leaderboard", headers=headers, params=params)

    def run_maintenance(self, fleet_id, headers):
        return self._request("POST", f"/api/fleets/{fleet_id}/run-maintenance", {}, headers)

    def list_fleet_terminals(self, fleet_id, headers, params=None):
        return self._request("GET", f"/api/fleets/{fleet_id}/terminals", headers=headers, params=params)

    def list_fleet_camera_policies(self, fleet_id, headers, params=None):
        return self._request("GET", f"/api/fleets/{fleet_id}/camera-policies", headers=headers, params=params)

    def list_fleet_safety_events(self, fleet_id, headers, params=None):
        return self._request("GET", f"/api/fleets/{fleet_id}/safety-events", headers=headers, params=params)

    def list_fleet_litigation_holds(self, fleet_id, headers, params=None):
        return self._request("GET", f"/api/fleets/{fleet_id}/litigation-holds", headers=headers, params=params)

    def list_fleet_score_snapshots(self, fleet_id, headers, params=None):
        return self._request("GET", f"/api/fleets/{fleet_id}/score-snapshots", headers=headers, params=params)

    def list_fleet_incentive_awards(self, fleet_id, headers, params=None):
        return self._request("GET", f"/api/fleets/{fleet_id}/incentive-awards", headers=headers, params=params)

    def compute_score_snapshot(self, fleet_id, payload, headers):
        return self._request("POST", f"/api/fleets/{fleet_id}/score-snapshots/compute", payload, headers)

    # --- Terminals ---
    def create_terminal(self, payload, headers):
        return self._request("POST", "/api/terminals", payload, headers)

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/api/terminals/{terminal_id}", headers=headers)

    def list_terminal_drivers(self, terminal_id, headers, params=None):
        return self._request("GET", f"/api/terminals/{terminal_id}/drivers", headers=headers, params=params)

    def list_terminal_vehicles(self, terminal_id, headers, params=None):
        return self._request("GET", f"/api/terminals/{terminal_id}/vehicles", headers=headers, params=params)

    def list_terminal_union_agreements(self, terminal_id, headers, params=None):
        return self._request("GET", f"/api/terminals/{terminal_id}/union-agreements", headers=headers, params=params)

    # --- Union agreements ---
    def create_union_agreement(self, payload, headers):
        return self._request("POST", "/api/union-agreements", payload, headers)

    def get_union_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/union-agreements/{agreement_id}", headers=headers)

    def ratify_union_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/union-agreements/{agreement_id}/ratify", {}, headers)

    def expire_union_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/union-agreements/{agreement_id}/expire", {}, headers)

    # --- Drivers ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/api/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/api/drivers/{driver_id}", headers=headers)

    def set_driver_status(self, driver_id, payload, headers):
        return self._request("POST", f"/api/drivers/{driver_id}/status", payload, headers)

    def list_driver_safety_events(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/drivers/{driver_id}/safety-events", headers=headers, params=params)

    def list_driver_coaching_sessions(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/drivers/{driver_id}/coaching-sessions", headers=headers, params=params)

    def create_coaching_session(self, driver_id, payload, headers):
        return self._request("POST", f"/api/drivers/{driver_id}/coaching-sessions", payload, headers)

    def list_driver_escalation_cases(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/drivers/{driver_id}/escalation-cases", headers=headers, params=params)

    def list_driver_exoneration_claims(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/drivers/{driver_id}/exoneration-claims", headers=headers, params=params)

    def list_driver_litigation_holds(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/drivers/{driver_id}/litigation-holds", headers=headers, params=params)

    def list_driver_incentive_awards(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/drivers/{driver_id}/incentive-awards", headers=headers, params=params)

    def list_driver_score_snapshots(self, driver_id, headers, params=None):
        return self._request("GET", f"/api/drivers/{driver_id}/score-snapshots", headers=headers, params=params)

    # --- Vehicles ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/api/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/api/vehicles/{vehicle_id}", headers=headers)

    def decommission_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/api/vehicles/{vehicle_id}/decommission", {}, headers)

    def list_vehicle_safety_events(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/api/vehicles/{vehicle_id}/safety-events", headers=headers, params=params)

    # --- Camera policies ---
    def create_camera_policy(self, payload, headers):
        return self._request("POST", "/api/camera-policies", payload, headers)

    def get_camera_policy(self, policy_id, headers):
        return self._request("GET", f"/api/camera-policies/{policy_id}", headers=headers)

    def patch_camera_policy(self, policy_id, payload, headers):
        return self._request("PATCH", f"/api/camera-policies/{policy_id}", payload, headers)

    def activate_camera_policy(self, policy_id, headers):
        return self._request("POST", f"/api/camera-policies/{policy_id}/activate", {}, headers)

    def archive_camera_policy(self, policy_id, headers):
        return self._request("POST", f"/api/camera-policies/{policy_id}/archive", {}, headers)

    # --- Safety events ---
    def create_safety_event(self, payload, headers):
        return self._request("POST", "/api/safety-events", payload, headers)

    def get_safety_event(self, event_id, headers):
        return self._request("GET", f"/api/safety-events/{event_id}", headers=headers)

    def review_safety_event(self, event_id, payload, headers):
        return self._request("POST", f"/api/safety-events/{event_id}/review", payload, headers)

    def list_event_footage_clips(self, event_id, headers, params=None):
        return self._request("GET", f"/api/safety-events/{event_id}/footage-clips", headers=headers, params=params)

    def list_event_review_decisions(self, event_id, headers, params=None):
        return self._request("GET", f"/api/safety-events/{event_id}/review-decisions", headers=headers, params=params)

    def list_event_coaching_sessions(self, event_id, headers, params=None):
        return self._request("GET", f"/api/safety-events/{event_id}/coaching-sessions", headers=headers, params=params)

    def list_event_escalation_cases(self, event_id, headers, params=None):
        return self._request("GET", f"/api/safety-events/{event_id}/escalation-cases", headers=headers, params=params)

    def create_exoneration_claim(self, event_id, payload, headers):
        return self._request("POST", f"/api/safety-events/{event_id}/exoneration-claims", payload, headers)

    def list_event_exoneration_claims(self, event_id, headers, params=None):
        return self._request("GET", f"/api/safety-events/{event_id}/exoneration-claims", headers=headers, params=params)

    def list_event_litigation_holds(self, event_id, headers, params=None):
        return self._request("GET", f"/api/safety-events/{event_id}/litigation-holds", headers=headers, params=params)

    # --- Footage clips ---
    def create_footage_clip(self, payload, headers):
        return self._request("POST", "/api/footage-clips", payload, headers)

    def get_footage_clip(self, clip_id, headers):
        return self._request("GET", f"/api/footage-clips/{clip_id}", headers=headers)

    def upload_begin_clip(self, clip_id, headers):
        return self._request("POST", f"/api/footage-clips/{clip_id}/upload-begin", {}, headers)

    def upload_complete_clip(self, clip_id, headers):
        return self._request("POST", f"/api/footage-clips/{clip_id}/upload-complete", {}, headers)

    def purge_clip(self, clip_id, headers):
        return self._request("POST", f"/api/footage-clips/{clip_id}/purge", {}, headers)

    # --- Coaching sessions ---
    def get_coaching_session(self, session_id, headers):
        return self._request("GET", f"/api/coaching-sessions/{session_id}", headers=headers)

    def acknowledge_coaching_session(self, session_id, headers):
        return self._request("POST", f"/api/coaching-sessions/{session_id}/acknowledge", {}, headers)

    def complete_coaching_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/coaching-sessions/{session_id}/complete", payload, headers)

    def reassign_coaching_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/coaching-sessions/{session_id}/reassign", payload, headers)

    def cancel_coaching_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/coaching-sessions/{session_id}/cancel", payload, headers)

    # --- Escalation cases ---
    def get_escalation_case(self, case_id, headers):
        return self._request("GET", f"/api/escalation-cases/{case_id}", headers=headers)

    def review_escalation_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/escalation-cases/{case_id}/review", payload, headers)

    def send_back_escalation_case(self, case_id, headers):
        return self._request("POST", f"/api/escalation-cases/{case_id}/send-back", {}, headers)

    def resolve_escalation_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/escalation-cases/{case_id}/resolve", payload, headers)

    # --- Exoneration claims ---
    def get_exoneration_claim(self, claim_id, headers):
        return self._request("GET", f"/api/exoneration-claims/{claim_id}", headers=headers)

    def begin_review_exoneration_claim(self, claim_id, headers):
        return self._request("POST", f"/api/exoneration-claims/{claim_id}/begin-review", {}, headers)

    def decide_exoneration_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/exoneration-claims/{claim_id}/decide", payload, headers)

    # --- Litigation holds ---
    def create_litigation_hold(self, payload, headers):
        return self._request("POST", "/api/litigation-holds", payload, headers)

    def get_litigation_hold(self, hold_id, headers):
        return self._request("GET", f"/api/litigation-holds/{hold_id}", headers=headers)

    def release_litigation_hold(self, hold_id, headers):
        return self._request("POST", f"/api/litigation-holds/{hold_id}/release", {}, headers)

    # --- Score snapshots ---
    def get_score_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/api/score-snapshots/{snapshot_id}", headers=headers)

    def list_snapshot_incentive_awards(self, snapshot_id, headers, params=None):
        return self._request("GET", f"/api/score-snapshots/{snapshot_id}/incentive-awards", headers=headers, params=params)

    # --- Incentive awards ---
    def get_incentive_award(self, award_id, headers):
        return self._request("GET", f"/api/incentive-awards/{award_id}", headers=headers)

    def approve_incentive_award(self, award_id, headers):
        return self._request("POST", f"/api/incentive-awards/{award_id}/approve", {}, headers)

    def pay_incentive_award(self, award_id, headers):
        return self._request("POST", f"/api/incentive-awards/{award_id}/pay", {}, headers)


api_client = ApiClient()
