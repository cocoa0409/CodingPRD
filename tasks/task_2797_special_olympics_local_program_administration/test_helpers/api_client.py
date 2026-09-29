"""API client: one method per endpoint declared in PRD §4.

All endpoints are mounted at the top level of the host; there is no common API
prefix (PRD §4).
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Any) -> Any:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    PRD §2.4 renders every timestamp "with exactly three fractional-second
    digits", but comparisons in tests must not fail merely because a server
    emitted ``...T10:00:00Z`` or ``...T10:00:00.000000Z``.  This canonicaliser
    is applied on both sides of an instant comparison so only the instant
    itself is under test.
    """
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if not raw:
        return value
    body = raw
    suffix = ""
    if body.endswith("Z"):
        body, suffix = body[:-1], "Z"
    elif "+" in body[10:]:
        idx = body.index("+", 10)
        body, suffix = body[:idx], "Z"
    if "." in body:
        head, frac = body.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit())
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    if "T" not in head:
        return raw
    return f"{head}.{frac}{suffix or 'Z'}"


class ApiClient(GenericApiClient):
    """One method per row of the PRD §4 endpoint table."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -------------------------------------------------------------- program
    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_program_athletes(self, program_id: str, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request("GET", f"/programs/{program_id}/athletes",
                             headers=headers, params=params)

    def list_program_volunteers(self, program_id: str, headers: Dict[str, str],
                                params: Optional[Dict] = None):
        return self._request("GET", f"/programs/{program_id}/volunteers",
                             headers=headers, params=params)

    def list_program_seasons(self, program_id: str, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request("GET", f"/programs/{program_id}/seasons",
                             headers=headers, params=params)

    def list_program_contributions(self, program_id: str, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request("GET", f"/programs/{program_id}/contributions",
                             headers=headers, params=params)

    def run_compliance_sweep(self, program_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/compliance-sweep",
                             payload, headers)

    # -------------------------------------------------------------- athlete
    def create_athlete(self, program_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/athletes",
                             payload, headers)

    def get_athlete(self, athlete_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/athletes/{athlete_id}", headers=headers)

    def withdraw_athlete(self, athlete_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/athletes/{athlete_id}/withdraw",
                             payload, headers)

    def list_athlete_medical_forms(self, athlete_id: str, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request("GET", f"/athletes/{athlete_id}/medical-forms",
                             headers=headers, params=params)

    def list_athlete_attendance_records(self, athlete_id: str,
                                        headers: Dict[str, str],
                                        params: Optional[Dict] = None):
        return self._request("GET", f"/athletes/{athlete_id}/attendance-records",
                             headers=headers, params=params)

    def list_athlete_health_screenings(self, athlete_id: str,
                                       headers: Dict[str, str],
                                       params: Optional[Dict] = None):
        return self._request("GET", f"/athletes/{athlete_id}/health-screenings",
                             headers=headers, params=params)

    # --------------------------------------------------------- medical form
    def create_medical_form(self, athlete_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/athletes/{athlete_id}/medical-forms",
                             payload, headers)

    def review_medical_form(self, form_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/medical-forms/{form_id}/review",
                             payload, headers)

    def resubmit_medical_form(self, form_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/medical-forms/{form_id}/resubmit",
                             payload, headers)

    # ------------------------------------------------------------ volunteer
    def create_volunteer(self, program_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/volunteers",
                             payload, headers)

    def get_volunteer(self, volunteer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def list_volunteer_credentials(self, volunteer_id: str, headers: Dict[str, str],
                                   params: Optional[Dict] = None):
        return self._request("GET", f"/volunteers/{volunteer_id}/credentials",
                             headers=headers, params=params)

    # ----------------------------------------------------------- credential
    def create_credential(self, volunteer_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/volunteers/{volunteer_id}/credentials",
                             payload, headers)

    def get_credential(self, credential_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/credentials/{credential_id}", headers=headers)

    def record_credential_screening(self, credential_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request("POST", f"/credentials/{credential_id}/screening",
                             payload, headers)

    def record_credential_training(self, credential_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request("POST", f"/credentials/{credential_id}/training",
                             payload, headers)

    def certify_credential(self, credential_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", f"/credentials/{credential_id}/certify",
                             payload, headers)

    # --------------------------------------------------------------- season
    def create_season(self, program_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/seasons",
                             payload, headers)

    def get_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def open_season_practice(self, season_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"/seasons/{season_id}/open-practice",
                             payload, headers)

    def run_divisioning(self, season_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", f"/seasons/{season_id}/divisioning",
                             payload, headers)

    def redivision_season(self, season_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/seasons/{season_id}/redivision",
                             payload, headers)

    def lock_season_entries(self, season_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/seasons/{season_id}/lock-entries",
                             payload, headers)

    # ----------------------------------------------------- practice session
    def create_practice_session(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", "/practice-sessions", payload, headers)

    def list_practice_sessions(self, headers: Dict[str, str],
                               params: Optional[Dict] = None):
        return self._request("GET", "/practice-sessions", headers=headers,
                             params=params)

    def get_practice_session(self, session_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/practice-sessions/{session_id}",
                             headers=headers)

    def cancel_practice_session(self, session_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/practice-sessions/{session_id}/cancel",
                             payload, headers)

    def create_attendance_record(self, session_id: str, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/practice-sessions/{session_id}/attendance-records",
            payload, headers)

    def list_session_attendance_records(self, session_id: str,
                                        headers: Dict[str, str],
                                        params: Optional[Dict] = None):
        return self._request(
            "GET", f"/practice-sessions/{session_id}/attendance-records",
            headers=headers, params=params)

    # ---------------------------------------------------------- unified team
    def create_unified_team(self, season_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/seasons/{season_id}/unified-teams",
                             payload, headers)

    def list_season_unified_teams(self, season_id: str, headers: Dict[str, str],
                                  params: Optional[Dict] = None):
        return self._request("GET", f"/seasons/{season_id}/unified-teams",
                             headers=headers, params=params)

    def get_unified_team(self, team_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/unified-teams/{team_id}", headers=headers)

    def add_unified_team_member(self, team_id: str, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", f"/unified-teams/{team_id}/members",
                             payload, headers)

    # ------------------------------------------------ entries and divisions
    def create_competition_entry(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request("POST", "/competition-entries", payload, headers)

    def list_competition_entries(self, headers: Dict[str, str],
                                 params: Optional[Dict] = None):
        return self._request("GET", "/competition-entries", headers=headers,
                             params=params)

    def get_competition_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/competition-entries/{entry_id}",
                             headers=headers)

    def post_entry_result(self, entry_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/competition-entries/{entry_id}/result",
                             payload, headers)

    def list_divisions(self, headers: Dict[str, str],
                       params: Optional[Dict] = None):
        return self._request("GET", "/divisions", headers=headers, params=params)

    def get_division(self, division_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/divisions/{division_id}", headers=headers)

    # ----------------------------------------------------- health screening
    def create_health_screening(self, payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request("POST", "/health-screenings", payload, headers)

    def log_referral_followup(self, screening_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/health-screenings/{screening_id}/referral-followup",
            payload, headers)

    # --------------------------------------------------------- contribution
    def create_contribution(self, program_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/contributions",
                             payload, headers)

    def fulfill_contribution(self, contribution_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request("POST", f"/contributions/{contribution_id}/fulfill",
                             payload, headers)

    def void_contribution(self, contribution_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/contributions/{contribution_id}/void",
                             payload, headers)


api_client = ApiClient()
