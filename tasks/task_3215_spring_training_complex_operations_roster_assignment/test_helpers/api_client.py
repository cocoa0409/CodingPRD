"""API client: one method per endpoint declared in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/camp-ops/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- Complex ---
    def create_complex(self, payload, headers):
        return self._request("POST", "/camp-ops/complexes", payload, headers)

    def get_complex(self, complex_id, headers):
        return self._request("GET", f"/camp-ops/complexes/{complex_id}", headers=headers)

    def list_complexes(self, headers, params=None):
        return self._request("GET", "/camp-ops/complexes", headers=headers, params=params)

    def field_maintenance(self, complex_id, maintenance_action, headers):
        return self._request("POST", f"/camp-ops/complexes/{complex_id}/field-maintenance",
                             {"maintenance_action": maintenance_action}, headers)

    def posture_sweep(self, complex_id, headers):
        return self._request("POST", f"/camp-ops/complexes/{complex_id}/posture-sweeps",
                             {}, headers)

    # --- CommunityAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/camp-ops/community-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/camp-ops/community-agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/camp-ops/community-agreements/{agreement_id}/activate",
                             {}, headers)

    def revert_agreement_to_draft(self, agreement_id, headers):
        return self._request("POST", f"/camp-ops/community-agreements/{agreement_id}/revert-to-draft",
                             {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/camp-ops/community-agreements/{agreement_id}/terminate",
                             {}, headers)

    # --- Player ---
    def create_player(self, payload, headers):
        return self._request("POST", "/camp-ops/players", payload, headers)

    def get_player(self, player_id, headers):
        return self._request("GET", f"/camp-ops/players/{player_id}", headers=headers)

    def list_players(self, headers, params=None):
        return self._request("GET", "/camp-ops/players", headers=headers, params=params)

    def pend_clearance(self, player_id, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/clearance/pend", {}, headers)

    # --- PlayerRosterRecord ---
    def open_roster_record(self, player_id, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/roster-record",
                             {"player_id": player_id}, headers)

    def get_roster_record(self, record_id, headers):
        return self._request("GET", f"/camp-ops/roster-records/{record_id}", headers=headers)

    def list_roster_records(self, headers, params=None):
        return self._request("GET", "/camp-ops/roster-records", headers=headers, params=params)

    def list_player_roster_records(self, player_id, headers):
        return self._request("GET", f"/camp-ops/players/{player_id}/roster-records", headers=headers)

    def select_active_roster(self, player_id, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/roster-record/select-active-roster",
                             {}, headers)

    def decide(self, player_id, decision_type, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/roster-record/decide",
                             {"decision_type": decision_type}, headers)

    def request_waivers(self, player_id, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/roster-record/request-waivers",
                             {}, headers)

    def record_waiver_outcome(self, player_id, outcome, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/roster-record/record-waiver-outcome",
                             {"outcome": outcome}, headers)

    def finalize_decision(self, player_id, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/roster-record/finalize-decision",
                             {}, headers)

    def void_decision(self, player_id, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/roster-record/void-decision",
                             {}, headers)

    def break_out_camp(self, record_id, level, headers):
        return self._request("POST", f"/camp-ops/roster-records/{record_id}/break-out-camp",
                             {"level": level}, headers)

    # --- PlayerProgramProfile ---
    def open_program_profile(self, player_id, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/program-profile",
                             {"player_id": player_id}, headers)

    def get_program_profile(self, profile_id, headers):
        return self._request("GET", f"/camp-ops/program-profiles/{profile_id}", headers=headers)

    def list_player_program_profiles(self, player_id, headers):
        return self._request("GET", f"/camp-ops/players/{player_id}/program-profiles", headers=headers)

    def reinstate_profile(self, player_id, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/program-profile/reinstate",
                             {}, headers)

    # --- HostCommunityRecord ---
    def open_host_community_record(self, agreement_id, headers):
        return self._request("POST", f"/camp-ops/community-agreements/{agreement_id}/host-community-record",
                             {"agreement_id": agreement_id}, headers)

    def get_host_community_record(self, record_id, headers):
        return self._request("GET", f"/camp-ops/host-community-records/{record_id}", headers=headers)

    def get_ledger(self, record_id, headers):
        return self._request("GET", f"/camp-ops/host-community-records/{record_id}/ledger",
                             headers=headers)

    def open_ticketing(self, record_id, headers):
        return self._request("POST", f"/camp-ops/host-community-records/{record_id}/open-ticketing",
                             {}, headers)

    def close_ticketing(self, record_id, headers):
        return self._request("POST", f"/camp-ops/host-community-records/{record_id}/close-ticketing",
                             {}, headers)

    def sell_tickets(self, record_id, quantity, headers):
        return self._request("POST", f"/camp-ops/host-community-records/{record_id}/sell-tickets",
                             {"quantity": quantity}, headers)

    # --- Sponsorship ---
    def create_sponsorship(self, record_id, payload, headers):
        return self._request("POST", f"/camp-ops/host-community-records/{record_id}/sponsorships",
                             payload, headers)

    def get_sponsorship(self, sponsorship_id, headers):
        return self._request("GET", f"/camp-ops/sponsorships/{sponsorship_id}", headers=headers)

    def contribute(self, sponsorship_id, amount_cents, direction, headers):
        return self._request("POST", f"/camp-ops/sponsorships/{sponsorship_id}/contribute",
                             {"amount_cents": amount_cents, "direction": direction}, headers)

    def settle_sponsorship(self, sponsorship_id, headers):
        return self._request("POST", f"/camp-ops/sponsorships/{sponsorship_id}/settle", {}, headers)

    def recognize_sponsorship(self, sponsorship_id, headers):
        return self._request("POST", f"/camp-ops/sponsorships/{sponsorship_id}/recognize", {}, headers)

    def void_settlement(self, sponsorship_id, headers):
        return self._request("POST", f"/camp-ops/sponsorships/{sponsorship_id}/void-settlement",
                             {}, headers)

    # --- WorkoutGroup ---
    def create_workout_group(self, complex_id, payload, headers):
        return self._request("POST", f"/camp-ops/complexes/{complex_id}/workout-groups",
                             payload, headers)

    def get_workout_group(self, group_id, headers):
        return self._request("GET", f"/camp-ops/workout-groups/{group_id}", headers=headers)

    def list_workout_groups(self, headers, params=None):
        return self._request("GET", "/camp-ops/workout-groups", headers=headers, params=params)

    def publish_group(self, group_id, expected_group_version, headers):
        return self._request("POST", f"/camp-ops/workout-groups/{group_id}/publish",
                             {"expected_group_version": expected_group_version}, headers)

    def disband_group(self, group_id, headers):
        return self._request("POST", f"/camp-ops/workout-groups/{group_id}/disband", {}, headers)

    def create_workout_session(self, group_id, payload, headers):
        return self._request("POST", f"/camp-ops/workout-groups/{group_id}/sessions", payload, headers)

    def publish_session(self, group_id, session_id, headers):
        return self._request("POST",
                             f"/camp-ops/workout-groups/{group_id}/sessions/{session_id}/publish-session",
                             {}, headers)

    # --- GroupAssignment ---
    def create_assignment(self, group_id, payload, headers):
        return self._request("POST", f"/camp-ops/workout-groups/{group_id}/assignments",
                             payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/camp-ops/group-assignments/{assignment_id}", headers=headers)

    def list_group_assignments(self, headers, params=None):
        return self._request("GET", "/camp-ops/group-assignments", headers=headers, params=params)

    def call_up(self, assignment_id, headers):
        return self._request("POST", f"/camp-ops/group-assignments/{assignment_id}/call-up",
                             {}, headers)

    def withdraw_assignment(self, assignment_id, withdrawal_reason, headers):
        return self._request("POST", f"/camp-ops/group-assignments/{assignment_id}/withdraw",
                             {"withdrawal_reason": withdrawal_reason}, headers)

    # --- ThrowProgram ---
    def create_throw_program(self, assignment_id, payload, headers):
        return self._request("POST", f"/camp-ops/group-assignments/{assignment_id}/throw-programs",
                             payload, headers)

    def get_throw_program(self, program_id, headers):
        return self._request("GET", f"/camp-ops/throw-programs/{program_id}", headers=headers)

    def log_throw_session(self, program_id, payload, headers):
        return self._request("POST", f"/camp-ops/throw-programs/{program_id}/sessions",
                             payload, headers)

    def list_throw_program_sessions(self, program_id, headers):
        return self._request("GET", f"/camp-ops/throw-programs/{program_id}/sessions", headers=headers)

    def advance_phase(self, program_id, direction, headers):
        return self._request("POST", f"/camp-ops/throw-programs/{program_id}/advance-phase",
                             {"direction": direction}, headers)

    def shutdown_program(self, program_id, headers):
        return self._request("POST", f"/camp-ops/throw-programs/{program_id}/shutdown", {}, headers)

    def reinstate_program(self, program_id, headers):
        return self._request("POST", f"/camp-ops/throw-programs/{program_id}/reinstate", {}, headers)

    # --- CampInvitation ---
    def create_invitation(self, player_id, payload, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/camp-invitations",
                             payload, headers)

    def get_invitation(self, invitation_id, headers):
        return self._request("GET", f"/camp-ops/camp-invitations/{invitation_id}", headers=headers)

    def list_invitations(self, headers, params=None):
        return self._request("GET", "/camp-ops/camp-invitations", headers=headers, params=params)

    def send_letter(self, invitation_id, headers):
        return self._request("POST", f"/camp-ops/camp-invitations/{invitation_id}/send-letter",
                             {}, headers)

    def acknowledge(self, invitation_id, headers):
        return self._request("POST", f"/camp-ops/camp-invitations/{invitation_id}/acknowledge",
                             {}, headers)

    def arrive(self, invitation_id, headers):
        return self._request("POST", f"/camp-ops/camp-invitations/{invitation_id}/arrive",
                             {}, headers)

    def mark_visa_blocked(self, invitation_id, headers):
        return self._request("POST", f"/camp-ops/camp-invitations/{invitation_id}/mark-visa-blocked",
                             {}, headers)

    # --- TravelArrangement ---
    def create_travel_arrangement(self, invitation_id, payload, headers):
        return self._request("POST", f"/camp-ops/camp-invitations/{invitation_id}/travel-arrangement",
                             payload, headers)

    def get_travel_arrangement(self, arrangement_id, headers):
        return self._request("GET", f"/camp-ops/travel-arrangements/{arrangement_id}", headers=headers)

    def revert_arrangement(self, arrangement_id, headers):
        return self._request("POST", f"/camp-ops/travel-arrangements/{arrangement_id}/revert",
                             {}, headers)

    def cancel_arrangement(self, arrangement_id, headers):
        return self._request("POST", f"/camp-ops/travel-arrangements/{arrangement_id}/cancel",
                             {}, headers)

    # --- Physical ---
    def create_physical(self, player_id, scheduled_visit_date, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/physicals",
                             {"player_id": player_id, "scheduled_visit_date": scheduled_visit_date},
                             headers)

    def get_physical(self, physical_id, headers):
        return self._request("GET", f"/camp-ops/physicals/{physical_id}", headers=headers)

    def perform_physical(self, physical_id, physical_result, headers):
        return self._request("POST", f"/camp-ops/physicals/{physical_id}/perform",
                             {"physical_result": physical_result}, headers)

    def void_physical(self, physical_id, headers):
        return self._request("POST", f"/camp-ops/physicals/{physical_id}/void", {}, headers)

    # --- GameSchedule ---
    def create_game(self, complex_id, payload, headers):
        return self._request("POST", f"/camp-ops/complexes/{complex_id}/games", payload, headers)

    def get_game(self, game_id, headers):
        return self._request("GET", f"/camp-ops/games/{game_id}", headers=headers)

    def publish_game(self, game_id, expected_game_version, headers):
        return self._request("POST", f"/camp-ops/games/{game_id}/publish",
                             {"expected_game_version": expected_game_version}, headers)

    def revert_game_to_draft(self, game_id, headers):
        return self._request("POST", f"/camp-ops/games/{game_id}/revert-to-draft", {}, headers)

    def record_result(self, game_id, headers):
        return self._request("POST", f"/camp-ops/games/{game_id}/record-result", {}, headers)

    def cancel_game(self, game_id, headers):
        return self._request("POST", f"/camp-ops/games/{game_id}/cancel", {}, headers)

    # --- GameParticipation ---
    def create_participation(self, game_id, payload, headers):
        return self._request("POST", f"/camp-ops/games/{game_id}/participations", payload, headers)

    def get_participation(self, participation_id, headers):
        return self._request("GET", f"/camp-ops/game-participations/{participation_id}", headers=headers)

    def list_participations(self, headers, params=None):
        return self._request("GET", "/camp-ops/game-participations", headers=headers, params=params)

    def confirm_participation(self, game_id, participation_id, expected_game_version, headers):
        return self._request("POST",
                             f"/camp-ops/games/{game_id}/participations/{participation_id}/confirm",
                             {"expected_game_version": expected_game_version}, headers)

    def withdraw_participation(self, game_id, participation_id, headers):
        return self._request("POST",
                             f"/camp-ops/games/{game_id}/participations/{participation_id}/withdraw",
                             {}, headers)

    def package_roster(self, game_id, headers):
        return self._request("POST", f"/camp-ops/games/{game_id}/package-roster", {}, headers)

    # --- SpringTrail / MinorLeagueAssignment ---
    def create_spring_trail(self, player_id, trail_level, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/spring-trails",
                             {"player_id": player_id, "trail_level": trail_level}, headers)

    def end_spring_trail(self, trail_id, headers):
        return self._request("POST", f"/camp-ops/spring-trails/{trail_id}/end", {}, headers)

    def create_minor_league_assignment(self, player_id, payload, headers):
        return self._request("POST", f"/camp-ops/players/{player_id}/minor-league-assignments",
                             payload, headers)

    def get_minor_league_assignment(self, assignment_id, headers):
        return self._request("GET", f"/camp-ops/minor-league-assignments/{assignment_id}",
                             headers=headers)

    def list_minor_league_assignments(self, headers, params=None):
        return self._request("GET", "/camp-ops/minor-league-assignments",
                             headers=headers, params=params)

    def settle_minor_league_assignment(self, assignment_id, headers):
        return self._request("POST", f"/camp-ops/minor-league-assignments/{assignment_id}/settle",
                             {}, headers)

    def void_breakout(self, assignment_id, headers):
        return self._request("POST", f"/camp-ops/minor-league-assignments/{assignment_id}/void-breakout",
                             {}, headers)

    # --- ops runs ---
    def run_ops(self, run_type, headers):
        return self._request("POST", "/camp-ops/ops-runs", {"run_type": run_type}, headers)


api_client = ApiClient()