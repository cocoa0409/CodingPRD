"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/network"


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving capability) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- member stations ---
    def create_station(self, payload, headers):
        return self._request("POST", f"{PREFIX}/member-stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/member-stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"{PREFIX}/member-stations/{station_id}", headers=headers)

    def update_station(self, station_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/member-stations/{station_id}", payload, headers)

    def submit_eligibility(self, station_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/submit-eligibility",
                             payload or {}, headers)

    def record_deficiency(self, station_id, payload, headers):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/record-deficiency",
                             payload, headers)

    def remediation(self, station_id, payload, headers):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/remediation",
                             payload, headers)

    def approve_eligibility(self, station_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/approve-eligibility",
                             payload or {}, headers)

    def probation(self, station_id, payload, headers):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/probation",
                             payload, headers)

    def restore_eligibility(self, station_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/restore-eligibility",
                             payload or {}, headers)

    def suspend_station(self, station_id, payload, headers):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/suspend",
                             payload, headers)

    def reinstate_station(self, station_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/reinstate",
                             payload or {}, headers)

    def withdraw_station(self, station_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/withdraw",
                             payload or {}, headers)

    def apply_contribution_credit(self, station_id, payload, headers):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/apply-contribution-credit",
                             payload, headers)

    def cost_efficiency_match(self, station_id, payload, headers):
        return self._request("POST", f"{PREFIX}/member-stations/{station_id}/cost-efficiency-match",
                             payload, headers)

    def list_standings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/member-station-standings", headers=headers, params=params)

    def list_station_assessments(self, station_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/member-stations/{station_id}/assessments",
                             headers=headers, params=params)

    def list_eligibility_projections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dues-vote-eligibility-projections",
                             headers=headers, params=params)

    def get_eligibility_projection(self, projection_id, headers):
        return self._request("GET", f"{PREFIX}/dues-vote-eligibility-projections/{projection_id}",
                             headers=headers)

    # --- programming fee schedules ---
    def create_schedule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/programming-fee-schedules", payload, headers)

    def list_schedules(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/programming-fee-schedules", headers=headers, params=params)

    def get_schedule(self, schedule_id, headers):
        return self._request("GET", f"{PREFIX}/programming-fee-schedules/{schedule_id}", headers=headers)

    def preview_schedule(self, schedule_id, station_id, headers):
        return self._request("GET", f"{PREFIX}/programming-fee-schedules/{schedule_id}/preview",
                             headers=headers, params={"station_id": station_id})

    # --- programming fee assessments ---
    def list_assessments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/programming-fee-assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"{PREFIX}/programming-fee-assessments/{assessment_id}", headers=headers)

    def finalize_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/programming-fee-assessments/{assessment_id}/finalize",
                             payload, headers)

    def allocate_pool(self, assessment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/programming-fee-assessments/{assessment_id}/allocate-pool",
                             payload, headers)

    # --- carriage agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/carriage-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/carriage-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/carriage-agreements/{agreement_id}", headers=headers)

    def list_agreement_windows(self, agreement_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/carriage-agreements/{agreement_id}/windows",
                             headers=headers, params=params)

    def submit_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/carriage-agreements/{agreement_id}/submit",
                             payload or {}, headers)

    def review_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/carriage-agreements/{agreement_id}/review",
                             payload or {}, headers)

    def clear_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/carriage-agreements/{agreement_id}/clear",
                             payload or {}, headers)

    def publish_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/carriage-agreements/{agreement_id}/publish",
                             payload or {}, headers)

    def republish_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/carriage-agreements/{agreement_id}/republish",
                             payload or {}, headers)

    def lift_publish_embargo(self, agreement_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/carriage-agreements/{agreement_id}/lift-publish-embargo",
                             payload or {}, headers)

    def expire_agreement(self, agreement_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/carriage-agreements/{agreement_id}/expire",
                             payload or {}, headers)

    def terminate_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/carriage-agreements/{agreement_id}/terminate",
                             payload, headers)

    # --- broadcast windows ---
    def create_window(self, payload, headers):
        return self._request("POST", f"{PREFIX}/broadcast-windows", payload, headers)

    def list_windows(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/broadcast-windows", headers=headers, params=params)

    def get_window(self, window_id, headers):
        return self._request("GET", f"{PREFIX}/broadcast-windows/{window_id}", headers=headers)

    def request_clearance(self, window_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/broadcast-windows/{window_id}/request-clearance",
                             payload or {}, headers)

    def clear_window(self, window_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/broadcast-windows/{window_id}/clear",
                             payload or {}, headers)

    def reject_window(self, window_id, payload, headers):
        return self._request("POST", f"{PREFIX}/broadcast-windows/{window_id}/reject", payload, headers)

    def remediating_window(self, window_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/broadcast-windows/{window_id}/remediating",
                             payload or {}, headers)

    def expire_window(self, window_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/broadcast-windows/{window_id}/expire",
                             payload or {}, headers)

    def series_embargo_check(self, headers, payload=None):
        return self._request("POST", f"{PREFIX}/series/embargo-check", payload or {}, headers)

    # --- distribution feeds ---
    def create_feed(self, payload, headers):
        return self._request("POST", f"{PREFIX}/distribution-feeds", payload, headers)

    def list_feeds(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/distribution-feeds", headers=headers, params=params)

    def get_feed(self, feed_id, headers):
        return self._request("GET", f"{PREFIX}/distribution-feeds/{feed_id}", headers=headers)

    def list_feed_slots(self, feed_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/distribution-feeds/{feed_id}/uplink-slots",
                             headers=headers, params=params)

    def bring_feed_online(self, feed_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/distribution-feeds/{feed_id}/bring-online",
                             payload or {}, headers)

    def feed_maintenance(self, feed_id, payload, headers):
        return self._request("POST", f"{PREFIX}/distribution-feeds/{feed_id}/maintenance",
                             payload, headers)

    def restore_feed(self, feed_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/distribution-feeds/{feed_id}/restore",
                             payload or {}, headers)

    def take_feed_offline(self, feed_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/distribution-feeds/{feed_id}/take-offline",
                             payload or {}, headers)

    def replan_feed(self, feed_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/distribution-feeds/{feed_id}/replan",
                             payload or {}, headers)

    def suspend_feed(self, feed_id, payload, headers):
        return self._request("POST", f"{PREFIX}/distribution-feeds/{feed_id}/suspend", payload, headers)

    # --- uplink slots ---
    def create_slot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/uplink-slots", payload, headers)

    def block_slots(self, payload, headers):
        return self._request("POST", f"{PREFIX}/uplink-slots/block", payload, headers)

    def list_slots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/uplink-slots", headers=headers, params=params)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"{PREFIX}/uplink-slots/{slot_id}", headers=headers)

    def air_slot(self, slot_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/uplink-slots/{slot_id}/air", payload or {}, headers)

    def release_slot(self, slot_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/uplink-slots/{slot_id}/release", payload or {}, headers)

    def preemption_review(self, slot_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/uplink-slots/{slot_id}/preemption-review",
                             payload or {}, headers)

    # --- underwriting agreements ---
    def create_underwriting(self, payload, headers):
        return self._request("POST", f"{PREFIX}/underwriting-agreements", payload, headers)

    def list_underwriting(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/underwriting-agreements", headers=headers, params=params)

    def get_underwriting(self, underwriting_id, headers):
        return self._request("GET", f"{PREFIX}/underwriting-agreements/{underwriting_id}", headers=headers)

    def submit_underwriting_review(self, underwriting_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/underwriting-agreements/{underwriting_id}/submit-for-review",
                             payload or {}, headers)

    def approve_underwriting(self, underwriting_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/underwriting-agreements/{underwriting_id}/approve",
                             payload or {}, headers)

    def reject_underwriting(self, underwriting_id, payload, headers):
        return self._request("POST", f"{PREFIX}/underwriting-agreements/{underwriting_id}/reject",
                             payload, headers)

    def schedule_underwriting(self, underwriting_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/underwriting-agreements/{underwriting_id}/schedule",
                             payload or {}, headers)

    def air_segment(self, underwriting_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/underwriting-agreements/{underwriting_id}/air-segment",
                             payload or {}, headers)

    # --- content contributions ---
    def create_contribution(self, payload, headers):
        return self._request("POST", f"{PREFIX}/content-contributions", payload, headers)

    def list_contributions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/content-contributions", headers=headers, params=params)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"{PREFIX}/content-contributions/{contribution_id}", headers=headers)

    def submit_contribution(self, contribution_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/content-contributions/{contribution_id}/submit",
                             payload or {}, headers)

    def shortlist_contribution(self, contribution_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/content-contributions/{contribution_id}/shortlist",
                             payload or {}, headers)

    def request_resubmission(self, contribution_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/content-contributions/{contribution_id}/request-resubmission",
                             payload or {}, headers)

    def license_contribution(self, contribution_id, payload, headers):
        return self._request("POST", f"{PREFIX}/content-contributions/{contribution_id}/license",
                             payload, headers)

    def mark_contribution_used(self, contribution_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/content-contributions/{contribution_id}/mark-used",
                             payload or {}, headers)

    def reject_contribution(self, contribution_id, payload, headers):
        return self._request("POST", f"{PREFIX}/content-contributions/{contribution_id}/reject",
                             payload, headers)

    def withdraw_contribution(self, contribution_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/content-contributions/{contribution_id}/withdraw",
                             payload or {}, headers)

    # --- national programs ---
    def create_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/national-programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/national-programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/national-programs/{program_id}", headers=headers)

    def list_program_contributions(self, program_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/national-programs/{program_id}/contributions",
                             headers=headers, params=params)

    def list_program_agreements(self, program_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/national-programs/{program_id}/carriage-agreements",
                             headers=headers, params=params)

    def program_move_to_production(self, program_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/national-programs/{program_id}/move-to-production",
                             payload or {}, headers)

    def program_schedule(self, program_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/national-programs/{program_id}/schedule",
                             payload or {}, headers)

    def program_premiere(self, program_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/national-programs/{program_id}/premiere",
                             payload or {}, headers)

    def program_publish(self, program_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/national-programs/{program_id}/publish",
                             payload or {}, headers)

    def program_premiere_embargo(self, program_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/national-programs/{program_id}/premiere-embargo",
                             payload or {}, headers)

    def program_reschedule_airings(self, program_id, payload, headers):
        return self._request("POST", f"{PREFIX}/national-programs/{program_id}/reschedule-airings",
                             payload, headers)

    def program_return_to_development(self, program_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/national-programs/{program_id}/return-to-development",
                             payload or {}, headers)

    def program_retire(self, program_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/national-programs/{program_id}/retire",
                             payload or {}, headers)

    # --- membership drives ---
    def create_drive(self, payload, headers):
        return self._request("POST", f"{PREFIX}/membership-drives", payload, headers)

    def list_drives(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/membership-drives", headers=headers, params=params)

    def get_drive(self, drive_id, headers):
        return self._request("GET", f"{PREFIX}/membership-drives/{drive_id}", headers=headers)

    def open_drive(self, drive_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/membership-drives/{drive_id}/open",
                             payload or {}, headers)

    def pledge_drive(self, drive_id, payload, headers):
        return self._request("POST", f"{PREFIX}/membership-drives/{drive_id}/pledge", payload, headers)

    def close_drive(self, drive_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/membership-drives/{drive_id}/close",
                             payload or {}, headers)

    def report_drive(self, drive_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/membership-drives/{drive_id}/report",
                             payload or {}, headers)

    def settle_drive(self, drive_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/membership-drives/{drive_id}/settle",
                             payload or {}, headers)

    def cancel_drive(self, drive_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/membership-drives/{drive_id}/cancel",
                             payload or {}, headers)

    # --- audience reports ---
    def create_audience_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/audience-reports", payload, headers)

    def list_audience_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/audience-reports", headers=headers, params=params)

    def get_audience_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/audience-reports/{report_id}", headers=headers)

    # --- dues proposals and votes ---
    def create_proposal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dues-proposals", payload, headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dues-proposals", headers=headers, params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"{PREFIX}/dues-proposals/{proposal_id}", headers=headers)

    def list_proposal_votes(self, proposal_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/dues-proposals/{proposal_id}/votes",
                             headers=headers, params=params)

    def open_proposal(self, proposal_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/dues-proposals/{proposal_id}/open",
                             payload or {}, headers)

    def cast_vote(self, proposal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dues-proposals/{proposal_id}/votes", payload, headers)

    def tally_proposal(self, proposal_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/dues-proposals/{proposal_id}/tally",
                             payload or {}, headers)

    def table_proposal(self, proposal_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/dues-proposals/{proposal_id}/table",
                             payload or {}, headers)

    def enact_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dues-proposals/{proposal_id}/enact", payload, headers)

    def close_enactment(self, proposal_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/dues-proposals/{proposal_id}/close-enactment",
                             payload or {}, headers)

    def list_station_votes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/station-votes", headers=headers, params=params)

    def get_station_vote(self, vote_id, headers):
        return self._request("GET", f"{PREFIX}/station-votes/{vote_id}", headers=headers)

    def supersede_vote(self, vote_id, payload, headers):
        return self._request("POST", f"{PREFIX}/station-votes/{vote_id}/supersede", payload, headers)

    def restore_vote(self, vote_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/station-votes/{vote_id}/restore",
                             payload or {}, headers)

    # --- board elections, candidacies and seats ---
    def create_election(self, payload, headers):
        return self._request("POST", f"{PREFIX}/board-elections", payload, headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/board-elections", headers=headers, params=params)

    def get_election(self, election_id, headers):
        return self._request("GET", f"{PREFIX}/board-elections/{election_id}", headers=headers)

    def list_election_candidates(self, election_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/board-elections/{election_id}/candidates",
                             headers=headers, params=params)

    def close_election(self, election_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/board-elections/{election_id}/close",
                             payload or {}, headers)

    def certify_election(self, election_id, payload, headers):
        return self._request("POST", f"{PREFIX}/board-elections/{election_id}/certify", payload, headers)

    def contest_election(self, election_id, payload, headers):
        return self._request("POST", f"{PREFIX}/board-elections/{election_id}/contest", payload, headers)

    def reopen_election(self, election_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/board-elections/{election_id}/reopen",
                             payload or {}, headers)

    def hold_over_seat(self, election_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/board-elections/{election_id}/hold-over",
                             payload or {}, headers)

    def vacate_seat(self, election_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/board-elections/{election_id}/vacate-seat",
                             payload or {}, headers)

    def finalize_election(self, election_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/board-elections/{election_id}/finalize",
                             payload or {}, headers)

    def create_candidate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/board-candidates", payload, headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/board-candidates", headers=headers, params=params)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"{PREFIX}/board-candidates/{candidate_id}", headers=headers)

    def qualify_candidate(self, candidate_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/board-candidates/{candidate_id}/qualify",
                             payload or {}, headers)

    def lapse_candidate(self, candidate_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/board-candidates/{candidate_id}/lapse",
                             payload or {}, headers)

    def record_candidate_votes(self, candidate_id, payload, headers):
        return self._request("POST", f"{PREFIX}/board-candidates/{candidate_id}/record-votes",
                             payload, headers)

    def withdraw_candidate(self, candidate_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/board-candidates/{candidate_id}/withdraw",
                             payload or {}, headers)

    def create_seat(self, payload, headers):
        return self._request("POST", f"{PREFIX}/board-seats", payload, headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/board-seats", headers=headers, params=params)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"{PREFIX}/board-seats/{seat_id}", headers=headers)

    def deallocate_seat(self, seat_id, payload, headers):
        return self._request("POST", f"{PREFIX}/board-seats/{seat_id}/deallocate", payload, headers)

    def recall_seat(self, seat_id, payload, headers):
        return self._request("POST", f"{PREFIX}/board-seats/{seat_id}/recall", payload, headers)


api_client = ApiClient()