"""API client: one method per endpoint the PRD declares."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock and operator sweeps ────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_transition_sweep(self, headers, payload=None):
        return self._request("POST", "/ops/transition-sweep", payload or {}, headers)

    # ── Organizations ───────────────────────────────────────────────────

    def create_organization(self, payload, headers):
        return self._request("POST", "/organizations", payload, headers)

    def list_organizations(self, headers, params=None):
        return self._request("GET", "/organizations", headers=headers, params=params)

    def get_organization(self, organization_id, headers):
        return self._request(
            "GET", f"/organizations/{organization_id}", headers=headers
        )

    def get_rating_trend(self, organization_id, headers, params=None):
        return self._request(
            "GET",
            f"/organizations/{organization_id}/rating-trend",
            headers=headers,
            params=params,
        )

    def list_organization_filing_records(self, organization_id, headers, params=None):
        return self._request(
            "GET",
            f"/organizations/{organization_id}/filing-records",
            headers=headers,
            params=params,
        )

    # ── Methodology versions ────────────────────────────────────────────

    def create_methodology_version(self, payload, headers):
        return self._request("POST", "/methodology-versions", payload, headers)

    def list_methodology_versions(self, headers, params=None):
        return self._request(
            "GET", "/methodology-versions", headers=headers, params=params
        )

    def get_methodology_version(self, methodology_version_id, headers):
        return self._request(
            "GET", f"/methodology-versions/{methodology_version_id}", headers=headers
        )

    def open_comment(self, methodology_version_id, headers, payload=None):
        return self._request(
            "POST",
            f"/methodology-versions/{methodology_version_id}/open-comment",
            payload or {},
            headers,
        )

    def close_comment(self, methodology_version_id, headers, payload=None):
        return self._request(
            "POST",
            f"/methodology-versions/{methodology_version_id}/close-comment",
            payload or {},
            headers,
        )

    def return_to_draft(self, methodology_version_id, payload, headers):
        return self._request(
            "POST",
            f"/methodology-versions/{methodology_version_id}/return-to-draft",
            payload,
            headers,
        )

    def adopt_methodology_version(self, methodology_version_id, payload, headers):
        return self._request(
            "POST",
            f"/methodology-versions/{methodology_version_id}/adopt",
            payload,
            headers,
        )

    def list_methodology_public_comments(
        self, methodology_version_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/methodology-versions/{methodology_version_id}/public-comments",
            headers=headers,
            params=params,
        )

    # ── Public comments ─────────────────────────────────────────────────

    def create_public_comment(self, payload, headers):
        return self._request("POST", "/public-comments", payload, headers)

    def dispose_public_comment(self, public_comment_id, payload, headers):
        return self._request(
            "POST", f"/public-comments/{public_comment_id}/dispose", payload, headers
        )

    # ── Transition grants ───────────────────────────────────────────────

    def list_transition_grants(self, headers, params=None):
        return self._request(
            "GET", "/transition-grants", headers=headers, params=params
        )

    def get_transition_grant(self, transition_grant_id, headers):
        return self._request(
            "GET", f"/transition-grants/{transition_grant_id}", headers=headers
        )

    # ── Filing records ──────────────────────────────────────────────────

    def create_filing_record(self, payload, headers):
        return self._request("POST", "/filing-records", payload, headers)

    def get_filing_record(self, filing_record_id, headers):
        return self._request(
            "GET", f"/filing-records/{filing_record_id}", headers=headers
        )

    def validate_filing_record(self, filing_record_id, payload, headers):
        return self._request(
            "POST", f"/filing-records/{filing_record_id}/validate", payload, headers
        )

    # ── Governance profiles and standard evaluations ─────────────────────

    def create_governance_profile(self, payload, headers):
        return self._request("POST", "/governance-profiles", payload, headers)

    def list_governance_profiles(self, headers, params=None):
        return self._request(
            "GET", "/governance-profiles", headers=headers, params=params
        )

    def get_governance_profile(self, governance_profile_id, headers):
        return self._request(
            "GET", f"/governance-profiles/{governance_profile_id}", headers=headers
        )

    def evaluate_governance_profile(self, governance_profile_id, headers, payload=None):
        return self._request(
            "POST",
            f"/governance-profiles/{governance_profile_id}/evaluate",
            payload or {},
            headers,
        )

    def list_standard_evaluations(self, governance_profile_id, headers, params=None):
        return self._request(
            "GET",
            f"/governance-profiles/{governance_profile_id}/standard-evaluations",
            headers=headers,
            params=params,
        )

    def get_standard_evaluation(self, standard_evaluation_id, headers):
        return self._request(
            "GET", f"/standard-evaluations/{standard_evaluation_id}", headers=headers
        )

    def waive_standard_evaluation(self, standard_evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"/standard-evaluations/{standard_evaluation_id}/waive",
            payload,
            headers,
        )

    def revoke_standard_waiver(self, standard_evaluation_id, payload, headers):
        return self._request(
            "POST",
            f"/standard-evaluations/{standard_evaluation_id}/revoke-waiver",
            payload or {},
            headers,
        )

    # ── Rating cycles ───────────────────────────────────────────────────

    def create_rating_cycle(self, payload, headers):
        return self._request("POST", "/rating-cycles", payload, headers)

    def list_rating_cycles(self, headers, params=None):
        return self._request("GET", "/rating-cycles", headers=headers, params=params)

    def get_rating_cycle(self, rating_cycle_id, headers):
        return self._request(
            "GET", f"/rating-cycles/{rating_cycle_id}", headers=headers
        )

    def score_rating_cycle(self, rating_cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/rating-cycles/{rating_cycle_id}/score", payload or {}, headers
        )

    def open_org_review(self, rating_cycle_id, headers, payload=None):
        return self._request(
            "POST",
            f"/rating-cycles/{rating_cycle_id}/open-org-review",
            payload or {},
            headers,
        )

    def publish_rating_cycle(self, rating_cycle_id, payload, headers):
        return self._request(
            "POST", f"/rating-cycles/{rating_cycle_id}/publish", payload or {}, headers
        )

    def withdraw_rating_cycle(self, rating_cycle_id, payload, headers):
        return self._request(
            "POST", f"/rating-cycles/{rating_cycle_id}/withdraw", payload, headers
        )

    def get_score_breakdown(self, rating_cycle_id, headers):
        return self._request(
            "GET", f"/rating-cycles/{rating_cycle_id}/score-breakdown", headers=headers
        )

    def list_dimension_scores(self, rating_cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/rating-cycles/{rating_cycle_id}/dimension-scores",
            headers=headers,
            params=params,
        )

    def create_dimension_overrides(self, rating_cycle_id, payload, headers):
        return self._request(
            "POST",
            f"/rating-cycles/{rating_cycle_id}/dimension-overrides",
            payload,
            headers,
        )

    # ── Correction requests ─────────────────────────────────────────────

    def create_correction_request(self, payload, headers):
        return self._request("POST", "/correction-requests", payload, headers)

    def list_correction_requests(self, headers, params=None):
        return self._request(
            "GET", "/correction-requests", headers=headers, params=params
        )

    def get_correction_request(self, correction_request_id, headers):
        return self._request(
            "GET", f"/correction-requests/{correction_request_id}", headers=headers
        )

    def claim_correction_request(self, correction_request_id, headers, payload=None):
        return self._request(
            "POST",
            f"/correction-requests/{correction_request_id}/claim",
            payload or {},
            headers,
        )

    def decide_correction_request(self, correction_request_id, payload, headers):
        return self._request(
            "POST",
            f"/correction-requests/{correction_request_id}/decide",
            payload,
            headers,
        )

    # ── Appeals ─────────────────────────────────────────────────────────

    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def assign_appeal_panel(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/assign-panel", payload, headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # ── Complaints ──────────────────────────────────────────────────────

    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def triage_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/triage", payload, headers
        )

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/resolve", payload, headers
        )

    def reverse_complaint_finding(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/complaints/{complaint_id}/reverse-finding", payload, headers
        )

    # ── Publication ledger ──────────────────────────────────────────────

    def list_publication_records(self, headers, params=None):
        return self._request(
            "GET", "/publication-records", headers=headers, params=params
        )

    def get_publication_record(self, publication_record_id, headers):
        return self._request(
            "GET", f"/publication-records/{publication_record_id}", headers=headers
        )


api_client = ApiClient()
