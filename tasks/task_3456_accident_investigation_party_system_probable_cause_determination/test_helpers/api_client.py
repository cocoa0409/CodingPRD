"""API client: one method per endpoint defined in the PRD (PRD §4).

The API is mounted at the server root: collections live directly under
/accident-cases, /investigations, /party-organizations, /party-designations,
/groups, /recorders, /safety-recommendations, /board-meetings, plus the
platform clock capability at /_clock/set_current_utc.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- platform: logical clock (PRD §2.4) ---------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- accident cases -----------------------------------------------------
    def create_accident_case(self, payload, headers):
        return self._request("POST", "/accident-cases", payload, headers)

    def list_accident_cases(self, headers, params=None):
        return self._request("GET", "/accident-cases", headers=headers, params=params)

    def get_accident_case(self, case_id, headers):
        return self._request("GET", f"/accident-cases/{case_id}", headers=headers)

    def propose_launch_decision(self, case_id, payload, headers):
        return self._request(
            "POST", f"/accident-cases/{case_id}/launch-decisions", payload, headers
        )

    def adopt_launch_decision(self, case_id, decision_id, payload, headers):
        return self._request(
            "POST",
            f"/accident-cases/{case_id}/launch-decisions/{decision_id}/adopt",
            payload or {},
            headers,
        )

    def reconsider_launch_decision(self, case_id, decision_id, payload, headers):
        return self._request(
            "POST",
            f"/accident-cases/{case_id}/launch-decisions/{decision_id}/reconsider",
            payload or {},
            headers,
        )

    # ---- investigations -----------------------------------------------------
    def list_investigations(self, headers, params=None):
        return self._request("GET", "/investigations", headers=headers, params=params)

    def get_investigation(self, investigation_id, headers):
        return self._request(
            "GET", f"/investigations/{investigation_id}", headers=headers
        )

    def advance_phase(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"/investigations/{investigation_id}/advance-phase", payload, headers
        )

    def reopen_factual(self, investigation_id, headers):
        return self._request(
            "POST", f"/investigations/{investigation_id}/reopen-factual", {}, headers
        )

    def release_docket(self, investigation_id, headers):
        return self._request(
            "POST", f"/investigations/{investigation_id}/release-docket", {}, headers
        )

    # ---- party organizations ------------------------------------------------
    def create_party_organization(self, payload, headers):
        return self._request("POST", "/party-organizations", payload, headers)

    def get_party_organization(self, organization_id, headers):
        return self._request(
            "GET", f"/party-organizations/{organization_id}", headers=headers
        )

    # ---- party designations -------------------------------------------------
    def create_party_designation(self, payload, headers):
        return self._request("POST", "/party-designations", payload, headers)

    def list_party_designations(self, headers, params=None):
        return self._request("GET", "/party-designations", headers=headers, params=params)

    def get_party_designation(self, designation_id, headers):
        return self._request(
            "GET", f"/party-designations/{designation_id}", headers=headers
        )

    def expel_party_designation(self, designation_id, payload, headers):
        return self._request(
            "POST", f"/party-designations/{designation_id}/expel", payload or {}, headers
        )

    def create_seat(self, designation_id, payload, headers):
        return self._request(
            "POST", f"/party-designations/{designation_id}/seats", payload, headers
        )

    def record_conduct_violation(self, designation_id, seat_id, payload, headers):
        return self._request(
            "POST",
            f"/party-designations/{designation_id}/seats/{seat_id}/conduct-violations",
            payload,
            headers,
        )

    # ---- investigative groups -----------------------------------------------
    def create_group(self, payload, headers):
        return self._request("POST", "/groups", payload, headers)

    def list_groups(self, headers, params=None):
        return self._request("GET", "/groups", headers=headers, params=params)

    def get_group(self, group_id, headers):
        return self._request("GET", f"/groups/{group_id}", headers=headers)

    def complete_group(self, group_id, headers):
        return self._request("POST", f"/groups/{group_id}/complete", {}, headers)

    def create_factual_report(self, group_id, payload, headers):
        return self._request(
            "POST", f"/groups/{group_id}/factual-reports", payload, headers
        )

    def verify_factual_report(self, group_id, report_id, headers):
        return self._request(
            "POST",
            f"/groups/{group_id}/factual-reports/{report_id}/verify",
            {},
            headers,
        )

    # ---- recorder packages ----------------------------------------------------
    def create_recorder(self, payload, headers):
        return self._request("POST", "/recorders", payload, headers)

    def list_recorders(self, headers, params=None):
        return self._request("GET", "/recorders", headers=headers, params=params)

    def get_recorder(self, recorder_id, headers):
        return self._request("GET", f"/recorders/{recorder_id}", headers=headers)

    def create_readout_session(self, recorder_id, payload, headers):
        return self._request(
            "POST", f"/recorders/{recorder_id}/readout-sessions", payload, headers
        )

    # ---- safety recommendations -----------------------------------------------
    def create_safety_recommendation(self, payload, headers):
        return self._request("POST", "/safety-recommendations", payload, headers)

    def list_safety_recommendations(self, headers, params=None):
        return self._request(
            "GET", "/safety-recommendations", headers=headers, params=params
        )

    def get_safety_recommendation(self, recommendation_id, headers):
        return self._request(
            "GET", f"/safety-recommendations/{recommendation_id}", headers=headers
        )

    def submit_response(self, recommendation_id, payload, headers):
        return self._request(
            "POST", f"/safety-recommendations/{recommendation_id}/responses", payload, headers
        )

    def classify_response(self, recommendation_id, payload, headers):
        return self._request(
            "POST", f"/safety-recommendations/{recommendation_id}/classify", payload, headers
        )

    def close_recommendation(self, recommendation_id, payload, headers):
        return self._request(
            "POST", f"/safety-recommendations/{recommendation_id}/close", payload, headers
        )

    # ---- board meetings ---------------------------------------------------------
    def create_board_meeting(self, payload, headers):
        return self._request("POST", "/board-meetings", payload, headers)

    def list_board_meetings(self, headers, params=None):
        return self._request("GET", "/board-meetings", headers=headers, params=params)

    def get_board_meeting(self, meeting_id, headers):
        return self._request("GET", f"/board-meetings/{meeting_id}", headers=headers)

    def cast_vote(self, meeting_id, payload, headers):
        return self._request(
            "POST", f"/board-meetings/{meeting_id}/votes", payload, headers
        )

    def close_board_meeting(self, meeting_id, headers):
        return self._request(
            "POST", f"/board-meetings/{meeting_id}/close", {}, headers
        )


api_client = ApiClient()
