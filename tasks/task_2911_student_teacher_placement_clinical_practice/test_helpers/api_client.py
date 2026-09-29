"""Typed client covering every endpoint of the contract.

One method per row of the endpoint table, plus the logical-clock endpoint.
Every method returns the raw response object so tests can assert on status and
on the error envelope; the ``*_data`` convenience wrappers unwrap the success
envelope.

Timestamps are rendered by the server with exactly three fractional digits.
Rather than have every test assert that width, ``canonical_instant`` and
``instants_equal`` normalise both sides to whole seconds so a test can compare
against the instant the contract's own prose names.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import GenericApiClient, get_success_data

_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?Z$")


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Strip the fractional-seconds part so instants compare by whole seconds."""
    if value is None:
        return None
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    return match.group(1) + "Z"


def instants_equal(actual: Optional[str], expected: Optional[str]) -> bool:
    """True when two ISO-8601 UTC instants denote the same second."""
    return canonical_instant(actual) == canonical_instant(expected)


class EppApiClient(GenericApiClient):
    """Client for the Student Teacher Placement & Clinical Practice API."""

    def patch(self, path: str, payload: Optional[Dict[str, Any]] = None,
              headers: Optional[Dict[str, str]] = None):
        """PATCH with a JSON body (the shared base client stops at PUT)."""
        return self._request("PATCH", path, payload, headers=headers)

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self.post("/_clock/set_current_utc",
                         {"current_utc": current_utc}, headers=headers)

    # ─── Districts ────────────────────────────────────

    def create_district(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/epp/districts", payload, headers=headers)

    def get_district(self, district_id: str, headers: Dict[str, str]):
        return self.get(f"/epp/districts/{district_id}", headers=headers)

    def list_districts(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self.get("/epp/districts", params=params, headers=headers)

    # ─── Candidates ───────────────────────────────────

    def create_candidate(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/epp/candidates", payload, headers=headers)

    def get_candidate(self, candidate_id: str, headers: Dict[str, str]):
        return self.get(f"/epp/candidates/{candidate_id}", headers=headers)

    def list_candidates(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self.get("/epp/candidates", params=params, headers=headers)

    def evaluate_readiness(self, candidate_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self.post(f"/epp/candidates/{candidate_id}/readiness-evaluate",
                         payload, headers=headers)

    def recommend_licensure(self, candidate_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self.post(f"/epp/candidates/{candidate_id}/licensure-recommendation",
                         payload, headers=headers)

    def file_state_report(self, candidate_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self.post(f"/epp/candidates/{candidate_id}/state-report",
                         payload, headers=headers)

    # ─── Readiness items ──────────────────────────────

    def create_readiness_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/epp/readiness-items", payload, headers=headers)

    def get_readiness_item(self, item_id: str, headers: Dict[str, str]):
        return self.get(f"/epp/readiness-items/{item_id}", headers=headers)

    def list_readiness_items(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self.get("/epp/readiness-items", params=params, headers=headers)

    def verify_readiness_item(self, item_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self.post(f"/epp/readiness-items/{item_id}/verify",
                         payload, headers=headers)

    # ─── Partnership agreements ───────────────────────

    def create_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/epp/partnership-agreements", payload, headers=headers)

    def get_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self.get(f"/epp/partnership-agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self.get("/epp/partnership-agreements", params=params, headers=headers)

    def activate_agreement(self, agreement_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self.post(f"/epp/partnership-agreements/{agreement_id}/activate",
                         payload if payload is not None else {}, headers=headers)

    def suspend_agreement(self, agreement_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self.post(f"/epp/partnership-agreements/{agreement_id}/suspend",
                         payload, headers=headers)

    def reactivate_agreement(self, agreement_id: str, headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self.post(f"/epp/partnership-agreements/{agreement_id}/reactivate",
                         payload if payload is not None else {}, headers=headers)

    def terminate_agreement(self, agreement_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self.post(f"/epp/partnership-agreements/{agreement_id}/terminate",
                         payload, headers=headers)

    # ─── Cooperating teachers ─────────────────────────

    def create_teacher(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/epp/cooperating-teachers", payload, headers=headers)

    def get_teacher(self, teacher_id: str, headers: Dict[str, str]):
        return self.get(f"/epp/cooperating-teachers/{teacher_id}", headers=headers)

    def list_teachers(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self.get("/epp/cooperating-teachers", params=params, headers=headers)

    def record_training_completion(self, teacher_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self.post(
            f"/epp/cooperating-teachers/{teacher_id}/training-completion",
            payload, headers=headers)

    def disqualify_teacher(self, teacher_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self.post(f"/epp/cooperating-teachers/{teacher_id}/disqualify",
                         payload, headers=headers)

    # ─── University supervisors ───────────────────────

    def create_supervisor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self.post("/epp/university-supervisors", payload, headers=headers)

    def get_supervisor(self, supervisor_id: str, headers: Dict[str, str]):
        return self.get(f"/epp/university-supervisors/{supervisor_id}",
                        headers=headers)

    def list_supervisors(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self.get("/epp/university-supervisors", params=params, headers=headers)

    def update_supervisor(self, supervisor_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self.patch(f"/epp/university-supervisors/{supervisor_id}",
                          payload, headers=headers)

    # ─── Placement requests ───────────────────────────

    def create_placement_request(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self.post("/epp/placement-requests", payload, headers=headers)

    def get_placement_request(self, request_id: str, headers: Dict[str, str]):
        return self.get(f"/epp/placement-requests/{request_id}", headers=headers)

    def list_placement_requests(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self.get("/epp/placement-requests", params=params, headers=headers)

    def route_request(self, request_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self.post(f"/epp/placement-requests/{request_id}/route",
                         payload if payload is not None else {}, headers=headers)

    def reroute_request(self, request_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self.post(f"/epp/placement-requests/{request_id}/reroute",
                         payload, headers=headers)

    # ─── Placements ───────────────────────────────────

    def get_placement(self, placement_id: str, headers: Dict[str, str]):
        return self.get(f"/epp/placements/{placement_id}", headers=headers)

    def list_placements(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self.get("/epp/placements", params=params, headers=headers)

    def confirm_placement(self, placement_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self.post(f"/epp/placements/{placement_id}/confirm",
                         payload if payload is not None else {}, headers=headers)

    def request_removal(self, placement_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self.post(f"/epp/placements/{placement_id}/removal-request",
                         payload, headers=headers)

    def decide_removal(self, placement_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self.post(f"/epp/placements/{placement_id}/removal-decision",
                         payload, headers=headers)

    def complete_placement(self, placement_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self.post(f"/epp/placements/{placement_id}/complete",
                         payload, headers=headers)

    def transition_stipend(self, placement_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self.post(f"/epp/placements/{placement_id}/stipend-transition",
                         payload, headers=headers)

    # ─── Observation cycles ───────────────────────────

    def create_observation_cycle(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self.post("/epp/observation-cycles", payload, headers=headers)

    def get_observation_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self.get(f"/epp/observation-cycles/{cycle_id}", headers=headers)

    def list_observation_cycles(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self.get("/epp/observation-cycles", params=params, headers=headers)

    def complete_observation_cycle(self, cycle_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self.post(f"/epp/observation-cycles/{cycle_id}/complete",
                         payload, headers=headers)

    def reschedule_observation_cycle(self, cycle_id: str, payload: Dict[str, Any],
                                     headers: Dict[str, str]):
        return self.post(f"/epp/observation-cycles/{cycle_id}/reschedule",
                         payload, headers=headers)

    # ─── Performance assessments ──────────────────────

    def create_performance_assessment(self, payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self.post("/epp/performance-assessments", payload, headers=headers)

    def get_performance_assessment(self, assessment_id: str,
                                   headers: Dict[str, str]):
        return self.get(f"/epp/performance-assessments/{assessment_id}",
                        headers=headers)

    def list_performance_assessments(self, headers: Dict[str, str],
                                     params: Optional[Dict[str, Any]] = None):
        return self.get("/epp/performance-assessments", params=params,
                        headers=headers)

    def submit_assessment(self, assessment_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self.post(f"/epp/performance-assessments/{assessment_id}/submit",
                         payload, headers=headers)

    def score_assessment(self, assessment_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self.post(f"/epp/performance-assessments/{assessment_id}/score",
                         payload, headers=headers)

    # ─── Envelope helpers ─────────────────────────────

    @staticmethod
    def data_of(response, expected_status: Optional[int] = None) -> Any:
        """Unwrap the success envelope's data member."""
        return get_success_data(response, expected_status)

    @staticmethod
    def page_of(response) -> Tuple[List[Any], Dict[str, Any]]:
        """Unwrap a list response into its rows and its page meta."""
        body = response.json()
        assert response.status_code == 200, (
            f"expected 200 for a list read, got {response.status_code}: {body}")
        assert "data" in body, f"list response has no data member: {body}"
        assert "meta" in body, f"list response has no meta member: {body}"
        return body["data"], body["meta"]
