"""API client: one method per endpoint defined in the PRD (section 4)."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Parties ----
    def create_party(self, payload, headers):
        return self._request("POST", "/intake/parties", payload, headers)

    def get_party(self, party_id, headers):
        return self._request("GET", f"/intake/parties/{party_id}", headers=headers)

    def list_parties(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/intake/parties", headers=headers, params=params)

    def list_party_matter_parties(self, party_id, headers):
        return self._request(
            "GET", f"/intake/parties/{party_id}/matter-parties", headers=headers
        )

    # ---- Attorneys ----
    def create_attorney(self, payload, headers):
        return self._request("POST", "/intake/attorneys", payload, headers)

    def get_attorney(self, attorney_id, headers):
        return self._request(
            "GET", f"/intake/attorneys/{attorney_id}", headers=headers
        )

    # ---- Matters ----
    def create_matter(self, payload, headers):
        return self._request("POST", "/intake/matters", payload, headers)

    def list_matters(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/intake/matters", headers=headers, params=params)

    def get_matter(self, matter_id, headers):
        return self._request("GET", f"/intake/matters/{matter_id}", headers=headers)

    def patch_matter(self, matter_id, payload, headers):
        return self._request(
            "PATCH", f"/intake/matters/{matter_id}", payload, headers
        )

    def add_matter_party(self, matter_id, payload, headers):
        return self._request(
            "POST", f"/intake/matters/{matter_id}/parties", payload, headers
        )

    def list_matter_parties(self, matter_id, headers):
        return self._request(
            "GET", f"/intake/matters/{matter_id}/parties", headers=headers
        )

    def transition_matter(self, matter_id, payload, headers):
        return self._request(
            "POST", f"/intake/matters/{matter_id}/transition", payload, headers
        )

    # ---- Conflict checks / hits ----
    def list_matter_conflict_checks(self, matter_id, headers):
        return self._request(
            "GET", f"/intake/matters/{matter_id}/conflict-checks", headers=headers
        )

    def create_conflict_check(self, matter_id, payload, headers):
        return self._request(
            "POST", f"/intake/matters/{matter_id}/conflict-checks", payload, headers
        )

    def list_conflict_hits(self, headers, params: Optional[dict] = None):
        return self._request(
            "GET", "/intake/conflict-hits", headers=headers, params=params
        )

    def get_conflict_hit(self, hit_id, headers):
        return self._request(
            "GET", f"/intake/conflict-hits/{hit_id}", headers=headers
        )

    def list_hit_waiver_requests(self, hit_id, headers):
        return self._request(
            "GET", f"/intake/conflict-hits/{hit_id}/waiver-requests", headers=headers
        )

    def review_conflict_hit(self, hit_id, payload, headers):
        return self._request(
            "POST", f"/intake/conflict-hits/{hit_id}/review", payload, headers
        )

    # ---- Ethical walls ----
    def create_ethical_wall(self, matter_id, payload, headers):
        return self._request(
            "POST", f"/intake/matters/{matter_id}/ethical-walls", payload, headers
        )

    def list_matter_ethical_walls(self, matter_id, headers):
        return self._request(
            "GET", f"/intake/matters/{matter_id}/ethical-walls", headers=headers
        )

    def transition_ethical_wall(self, wall_id, payload, headers):
        return self._request(
            "POST", f"/intake/ethical-walls/{wall_id}/transition", payload, headers
        )

    # ---- Waivers ----
    def create_waiver_request(self, matter_id, payload, headers):
        return self._request(
            "POST", f"/intake/matters/{matter_id}/waiver-requests", payload, headers
        )

    def list_matter_waiver_requests(self, matter_id, headers):
        return self._request(
            "GET", f"/intake/matters/{matter_id}/waiver-requests", headers=headers
        )

    def transition_waiver_request(self, waiver_id, payload, headers):
        return self._request(
            "POST", f"/intake/waiver-requests/{waiver_id}/transition", payload, headers
        )

    # ---- Engagement letters ----
    def create_engagement_letter(self, matter_id, payload, headers):
        return self._request(
            "POST",
            f"/intake/matters/{matter_id}/engagement-letters",
            payload,
            headers,
        )

    def list_matter_engagement_letters(self, matter_id, headers):
        return self._request(
            "GET", f"/intake/matters/{matter_id}/engagement-letters", headers=headers
        )

    def transition_engagement_letter(self, letter_id, payload, headers):
        return self._request(
            "POST",
            f"/intake/engagement-letters/{letter_id}/transition",
            payload,
            headers,
        )

    # ---- Credit ----
    def create_credit_assessment(self, matter_id, payload, headers):
        return self._request(
            "POST", f"/intake/matters/{matter_id}/credit-assessments", payload, headers
        )

    def list_matter_credit_assessments(self, matter_id, headers):
        return self._request(
            "GET", f"/intake/matters/{matter_id}/credit-assessments", headers=headers
        )

    # ---- Retainer ----
    def list_matter_retainer_deposits(self, matter_id, headers):
        return self._request(
            "GET", f"/intake/matters/{matter_id}/retainer-deposits", headers=headers
        )

    def transition_retainer_deposit(self, deposit_id, payload, headers):
        return self._request(
            "POST",
            f"/intake/retainer-deposits/{deposit_id}/transition",
            payload,
            headers,
        )

    # ---- Logical clock ----
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
