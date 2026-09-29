"""API client: one method per endpoint the PRD defines."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Officiating Development & Grading API."""

    # ─── The logical clock ────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Optional[dict], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Season programs ──────────────────────────────

    def create_season_program(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/season-programs", payload, headers)

    def open_season_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/season-programs/{program_id}/open", headers=headers
        )

    def lock_postseason(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/season-programs/{program_id}/lock-postseason", headers=headers
        )

    def get_season_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/season-programs/{program_id}", headers=headers)

    # ─── Officials ────────────────────────────────────

    def create_official(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/officials", payload, headers)

    def get_official(self, official_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/officials/{official_id}", headers=headers)

    def list_officials(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/officials", headers=headers, params=params)

    # ─── Training records (append-only, beneath their official) ────

    def create_training_record(
        self, official_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/officials/{official_id}/training-records", payload, headers
        )

    def list_training_records(
        self, official_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/officials/{official_id}/training-records",
            headers=headers,
            params=params,
        )

    # ─── Advancement applications ─────────────────────

    def create_advancement_application(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/advancement-applications", payload, headers)

    def screen_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/advancement-applications/{application_id}/screen", headers=headers
        )

    def create_field_evaluation(
        self, application_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/advancement-applications/{application_id}/field-evaluations",
            payload,
            headers,
        )

    def list_field_evaluations(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[dict] = None,
    ):
        return self._request(
            "GET",
            f"/advancement-applications/{application_id}/field-evaluations",
            headers=headers,
            params=params,
        )

    def submit_application_to_committee(
        self, application_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/advancement-applications/{application_id}/submit-to-committee",
            headers=headers,
        )

    def return_application_for_tape(
        self, application_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/advancement-applications/{application_id}/return-for-tape",
            payload,
            headers,
        )

    def decide_application(
        self, application_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/advancement-applications/{application_id}/decide",
            payload,
            headers,
        )

    def get_advancement_application(
        self, application_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/advancement-applications/{application_id}", headers=headers
        )

    def list_advancement_applications(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", "/advancement-applications", headers=headers, params=params
        )

    # ─── Games ────────────────────────────────────────

    def create_game(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/games", payload, headers)

    def kickoff_game(self, game_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/games/{game_id}/kickoff", headers=headers)

    def mark_game_played(self, game_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/games/{game_id}/mark-played", headers=headers)

    def finalize_game(self, game_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/games/{game_id}/finalize", headers=headers)

    def get_game(self, game_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/games/{game_id}", headers=headers)

    def list_games(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/games", headers=headers, params=params)

    # ─── Crew assignments ─────────────────────────────

    def create_crew_assignment(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/crew-assignments", payload, headers)

    def confirm_crew_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/crew-assignments/{assignment_id}/confirm", headers=headers
        )

    def withdraw_crew_assignment(
        self,
        assignment_id: str,
        headers: Dict[str, str],
        payload: Optional[dict] = None,
    ):
        return self._request(
            "POST", f"/crew-assignments/{assignment_id}/withdraw", payload, headers
        )

    def get_crew_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/crew-assignments/{assignment_id}", headers=headers
        )

    def list_crew_assignments(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/crew-assignments", headers=headers, params=params)

    # ─── Play grades ──────────────────────────────────

    def create_play_grade(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/play-grades", payload, headers)

    def post_play_grade(self, grade_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/play-grades/{grade_id}/post", headers=headers)

    def get_play_grade(self, grade_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/play-grades/{grade_id}", headers=headers)

    def list_play_grades(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/play-grades", headers=headers, params=params)

    # ─── Grade appeals ────────────────────────────────

    def create_grade_appeal(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/grade-appeals", payload, headers)

    def start_appeal_review(self, appeal_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/grade-appeals/{appeal_id}/start-review", headers=headers
        )

    def decide_grade_appeal(
        self, appeal_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/grade-appeals/{appeal_id}/decide", payload, headers
        )

    def withdraw_grade_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/grade-appeals/{appeal_id}/withdraw", headers=headers
        )

    def get_grade_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/grade-appeals/{appeal_id}", headers=headers)

    def list_grade_appeals(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/grade-appeals", headers=headers, params=params)

    # ─── Replay stations and reviews ──────────────────

    def create_replay_station(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/replay-stations", payload, headers)

    def get_replay_station(self, station_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/replay-stations/{station_id}", headers=headers)

    def create_replay_review(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/replay-reviews", payload, headers)

    def decide_replay_review(
        self, review_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/replay-reviews/{review_id}/decide", payload, headers
        )

    def get_replay_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/replay-reviews/{review_id}", headers=headers)

    def list_replay_reviews(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/replay-reviews", headers=headers, params=params)

    # ─── Pool reports ─────────────────────────────────

    def create_pool_report(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/pool-reports", payload, headers)

    def publish_pool_report(self, report_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/pool-reports/{report_id}/publish", headers=headers
        )

    def get_pool_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/pool-reports/{report_id}", headers=headers)

    def list_pool_reports(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/pool-reports", headers=headers, params=params)

    # ─── Discipline actions ───────────────────────────

    def create_discipline_action(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/discipline-actions", payload, headers)

    def assign_remediation(self, action_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/discipline-actions/{action_id}/assign-remediation", payload, headers
        )

    def resolve_discipline_action(
        self, action_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/discipline-actions/{action_id}/resolve", payload, headers
        )

    def get_discipline_action(self, action_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/discipline-actions/{action_id}", headers=headers
        )

    def list_discipline_actions(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", "/discipline-actions", headers=headers, params=params
        )

    # ─── Official season records ──────────────────────

    def get_season_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/season-records/{record_id}", headers=headers)

    def list_season_records(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/season-records", headers=headers, params=params)


api_client = ApiClient()
