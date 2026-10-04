"""API client: one method per endpoint on the /toastmasters surface (PRD §4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/toastmasters"


class ApiClient(GenericApiClient):
    """Thin endpoint-per-method wrapper. All methods return the raw response."""

    # ------------------------------------------------------------------
    # Club reads
    # ------------------------------------------------------------------
    def list_clubs(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/clubs", headers=headers, params=params)

    def get_coaching_queue(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/clubs/coaching-queue", headers=headers, params=params
        )

    def get_club(self, club_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/clubs/{club_id}", headers=headers)

    def get_member(self, member_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/members/{member_id}", headers=headers)

    # ------------------------------------------------------------------
    # Membership / education / completion reads
    # ------------------------------------------------------------------
    def list_memberships(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/memberships", headers=headers, params=params)

    def get_membership(self, membership_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/memberships/{membership_id}", headers=headers)

    def list_education_paths(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/education-paths", headers=headers, params=params
        )

    def get_education_path(self, path_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/education-paths/{path_id}", headers=headers)

    def list_project_completions(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/project-completions", headers=headers, params=params
        )

    def get_project_completion(self, completion_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/project-completions/{completion_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Meeting / role reads
    # ------------------------------------------------------------------
    def list_meetings(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/meetings", headers=headers, params=params)

    def get_meeting(self, meeting_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/meetings/{meeting_id}", headers=headers)

    def list_role_assignments(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/role-assignments", headers=headers, params=params
        )

    def get_role_assignment(self, assignment_id: str, headers):
        return self._request(
            "GET", f"{API_PREFIX}/role-assignments/{assignment_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Officer / contest / visit reads
    # ------------------------------------------------------------------
    def list_officer_terms(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/officer-terms", headers=headers, params=params)

    def get_officer_term(self, term_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/officer-terms/{term_id}", headers=headers)

    def list_contests(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/contests", headers=headers, params=params)

    def get_contest(self, contest_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/contests/{contest_id}", headers=headers)

    def list_contest_entries(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{API_PREFIX}/contest-entries", headers=headers, params=params
        )

    def get_contest_entry(self, entry_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/contest-entries/{entry_id}", headers=headers)

    def list_area_visits(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"{API_PREFIX}/area-visits", headers=headers, params=params)

    def get_area_visit(self, visit_id: str, headers):
        return self._request("GET", f"{API_PREFIX}/area-visits/{visit_id}", headers=headers)

    # ------------------------------------------------------------------
    # Club writes
    # ------------------------------------------------------------------
    def create_club(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/clubs", payload, headers)

    def charter_club(self, club_id: str, headers, payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/clubs/{club_id}/charter", payload or {}, headers
        )

    def close_cycle(self, club_id: str, headers, payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/clubs/{club_id}/close-cycle", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Membership writes
    # ------------------------------------------------------------------
    def create_membership(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/memberships", payload, headers)

    def bulk_create_memberships(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/memberships/bulk", payload, headers)

    def renew_dues(self, membership_id: str, headers, payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/memberships/{membership_id}/renew", payload or {}, headers
        )

    def refund_dues(self, membership_id: str, headers, payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/memberships/{membership_id}/refund-dues", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Education path / completion writes
    # ------------------------------------------------------------------
    def create_education_path(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/education-paths", payload, headers)

    def advance_level(self, path_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/education-paths/{path_id}/advance-level", payload, headers
        )

    def create_project_completion(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/project-completions", payload, headers)

    def record_evaluation(self, completion_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/project-completions/{completion_id}/evaluation", payload, headers
        )

    def review_completion(self, completion_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/project-completions/{completion_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Meeting / role writes
    # ------------------------------------------------------------------
    def create_meeting(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/meetings", payload, headers)

    def close_meeting(self, meeting_id: str, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/meetings/{meeting_id}/close", payload, headers)

    def create_role_assignment(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/role-assignments", payload, headers)

    def release_role_assignment(self, assignment_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/role-assignments/{assignment_id}/release", payload, headers
        )

    # ------------------------------------------------------------------
    # Officer term writes
    # ------------------------------------------------------------------
    def create_officer_term(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/officer-terms", payload, headers)

    def elect_officer(self, term_id: str, headers, payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/officer-terms/{term_id}/elect", payload or {}, headers
        )

    def record_officer_training(self, term_id: str, headers, payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/officer-terms/{term_id}/training", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Contest writes
    # ------------------------------------------------------------------
    def create_contest(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/contests", payload, headers)

    def complete_contest(self, contest_id: str, headers, payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"{API_PREFIX}/contests/{contest_id}/complete", payload or {}, headers
        )

    def create_contest_entry(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/contest-entries", payload, headers)

    def record_ballot(self, entry_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"{API_PREFIX}/contest-entries/{entry_id}/ballots", payload, headers
        )

    # ------------------------------------------------------------------
    # Governance visit writes
    # ------------------------------------------------------------------
    def create_area_visit(self, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/area-visits", payload, headers)

    def complete_area_visit(self, visit_id: str, payload: Dict[str, Any], headers):
        return self._request("POST", f"{API_PREFIX}/area-visits/{visit_id}/complete", payload, headers)


api_client = ApiClient()
