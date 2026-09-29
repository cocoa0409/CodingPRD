"""HTTP client for the Newsroom Standards & Corrections API.

One method per endpoint of PRD §4, all mounted beneath ``/standards-desk``.
Every method returns the raw ``requests.Response`` so tests can assert on the
status code as well as on the envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import BASE

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the standards desk."""

    # ─── Newsrooms, people, reviewers (PRD §3.1) ──────

    def create_newsroom(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{BASE}/newsrooms", payload, headers)

    def get_newsroom(self, newsroom_id: str, headers: Headers = None):
        return self._request("GET", f"{BASE}/newsrooms/{newsroom_id}", None, headers)

    def get_standards_summary(self, newsroom_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{BASE}/newsrooms/{newsroom_id}/standards-summary", None, headers
        )

    def create_journalist(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{BASE}/journalists", payload, headers)

    def get_journalist(self, journalist_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{BASE}/journalists/{journalist_id}", None, headers
        )

    def list_journalists(
        self, newsroom_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"{BASE}/newsrooms/{newsroom_id}/journalists", params, headers
        )

    def create_reviewer(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{BASE}/reviewers", payload, headers)

    def get_reviewer(self, reviewer_id: str, headers: Headers = None):
        return self._request("GET", f"{BASE}/reviewers/{reviewer_id}", None, headers)

    def list_reviewers(
        self, newsroom_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"{BASE}/newsrooms/{newsroom_id}/reviewers", params, headers
        )

    def list_audit_events(
        self, newsroom_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"{BASE}/newsrooms/{newsroom_id}/audit-events", params, headers
        )

    # ─── Stories (PRD §3.2, §3.5) ─────────────────────

    def create_story(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{BASE}/stories", payload, headers)

    def get_story(self, story_id: str, headers: Headers = None):
        return self._request("GET", f"{BASE}/stories/{story_id}", None, headers)

    def list_stories(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{BASE}/stories", params, headers)

    def publish_story(
        self, story_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST", f"{BASE}/stories/{story_id}/publish", payload or {}, headers
        )

    def unpublish_story(self, story_id: str, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{BASE}/stories/{story_id}/unpublish", payload, headers
        )

    # ─── Anonymous-source approvals (PRD §3.2) ────────

    def create_source_approval(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{BASE}/anonymous-source-approvals", payload, headers
        )

    def get_source_approval(self, approval_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{BASE}/anonymous-source-approvals/{approval_id}", None, headers
        )

    def list_story_source_approvals(
        self, story_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET",
            f"{BASE}/stories/{story_id}/anonymous-source-approvals",
            params,
            headers,
        )

    def decide_source_approval(
        self, approval_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/anonymous-source-approvals/{approval_id}/decide",
            payload,
            headers,
        )

    def revoke_source_approval(
        self, approval_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/anonymous-source-approvals/{approval_id}/revoke",
            payload,
            headers,
        )

    # ─── Pre-publication reviews (PRD §3.3) ───────────

    def create_review(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{BASE}/pre-publication-reviews", payload, headers
        )

    def get_review(self, review_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{BASE}/pre-publication-reviews/{review_id}", None, headers
        )

    def list_story_reviews(
        self, story_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"{BASE}/stories/{story_id}/pre-publication-reviews", params, headers
        )

    def record_legal_verdict(
        self, review_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/pre-publication-reviews/{review_id}/legal-verdict",
            payload,
            headers,
        )

    def record_standards_verdict(
        self, review_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/pre-publication-reviews/{review_id}/standards-verdict",
            payload,
            headers,
        )

    def clear_review(
        self, review_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/pre-publication-reviews/{review_id}/clear",
            payload or {},
            headers,
        )

    def resubmit_review(
        self, review_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/pre-publication-reviews/{review_id}/resubmit",
            payload or {},
            headers,
        )

    # ─── Review assignments (PRD §3.4) ────────────────

    def create_assignment(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{BASE}/review-assignments", payload, headers)

    def get_assignment(self, assignment_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{BASE}/review-assignments/{assignment_id}", None, headers
        )

    def list_assignments(self, headers: Headers = None, params: Payload = None):
        return self._request("GET", f"{BASE}/review-assignments", params, headers)

    def cancel_assignment(
        self, assignment_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/review-assignments/{assignment_id}/cancel",
            payload,
            headers,
        )

    # ─── Correction requests (PRD §3.6) ───────────────

    def create_correction_request(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{BASE}/correction-requests", payload, headers)

    def get_correction_request(self, request_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{BASE}/correction-requests/{request_id}", None, headers
        )

    def list_story_correction_requests(
        self, story_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET", f"{BASE}/stories/{story_id}/correction-requests", params, headers
        )

    def start_correction_investigation(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/correction-requests/{request_id}/start-investigation",
            payload or {},
            headers,
        )

    def record_subject_outreach(
        self, request_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/correction-requests/{request_id}/subject-outreach",
            payload,
            headers,
        )

    def adjudicate_correction_request(
        self, request_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/correction-requests/{request_id}/adjudicate",
            payload,
            headers,
        )

    def resolve_correction_request(
        self, request_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/correction-requests/{request_id}/resolve",
            payload or {},
            headers,
        )

    # ─── Misconduct investigations (PRD §3.7) ─────────

    def create_investigation(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{BASE}/misconduct-investigations", payload, headers
        )

    def get_investigation(self, investigation_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{BASE}/misconduct-investigations/{investigation_id}", None, headers
        )

    def list_investigations(self, headers: Headers = None, params: Payload = None):
        return self._request(
            "GET", f"{BASE}/misconduct-investigations", params, headers
        )

    def advance_investigation(
        self, investigation_id: str, payload: Payload = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/misconduct-investigations/{investigation_id}/advance",
            payload or {},
            headers,
        )

    def decide_investigation(
        self, investigation_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/misconduct-investigations/{investigation_id}/decide",
            payload,
            headers,
        )

    def appeal_investigation(
        self, investigation_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/misconduct-investigations/{investigation_id}/appeal",
            payload,
            headers,
        )

    # ─── Conflicts, outside work, training (PRD §3.8) ─

    def create_disclosure(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{BASE}/conflict-disclosures", payload, headers)

    def get_disclosure(self, disclosure_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{BASE}/conflict-disclosures/{disclosure_id}", None, headers
        )

    def list_journalist_disclosures(
        self, journalist_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET",
            f"{BASE}/journalists/{journalist_id}/conflict-disclosures",
            params,
            headers,
        )

    def review_disclosure(
        self, disclosure_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/conflict-disclosures/{disclosure_id}/review",
            payload,
            headers,
        )

    def create_activity_request(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{BASE}/outside-activity-requests", payload, headers
        )

    def get_activity_request(self, request_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{BASE}/outside-activity-requests/{request_id}", None, headers
        )

    def list_journalist_activity_requests(
        self, journalist_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET",
            f"{BASE}/journalists/{journalist_id}/outside-activity-requests",
            params,
            headers,
        )

    def decide_activity_request(
        self, request_id: str, payload: Payload, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{BASE}/outside-activity-requests/{request_id}/decide",
            payload,
            headers,
        )

    def create_training_record(self, payload: Payload, headers: Headers = None):
        return self._request("POST", f"{BASE}/training-records", payload, headers)

    def list_journalist_training_records(
        self, journalist_id: str, headers: Headers = None, params: Payload = None
    ):
        return self._request(
            "GET",
            f"{BASE}/journalists/{journalist_id}/training-records",
            params,
            headers,
        )

    # ─── Logical clock (PRD §2.5) ─────────────────────

    def set_clock(self, payload: Payload, headers: Headers = None):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
