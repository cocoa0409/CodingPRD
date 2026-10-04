"""API client: one method per endpoint defined in PRD §4.

Subclass of the framework's GenericApiClient; methods return raw
requests.Response objects so tests can assert status codes and envelopes.
Action endpoints that take no input fields send an empty JSON object body.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_EMPTY: Dict[str, Any] = {}


class ApiClient(GenericApiClient):
    # -- Logical clock (PRD §2.4) -------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- Launch seasons (PRD §3.1, §3.9) -------------------------------------
    def create_season(self, payload, headers):
        return self._request("POST", "/launch-seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/launch-seasons/{season_id}", headers=headers)

    def list_season_categories(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/launch-seasons/{season_id}/categories", headers=headers, params=params
        )

    def freeze_season(self, season_id, headers, payload=None):
        return self._request(
            "POST", f"/launch-seasons/{season_id}/freeze",
            _EMPTY if payload is None else payload, headers,
        )

    def unfreeze_season(self, season_id, headers, payload=None):
        return self._request(
            "POST", f"/launch-seasons/{season_id}/unfreeze",
            _EMPTY if payload is None else payload, headers,
        )

    def close_season(self, season_id, headers, payload=None):
        return self._request(
            "POST", f"/launch-seasons/{season_id}/close",
            _EMPTY if payload is None else payload, headers,
        )

    def run_review(self, season_id, headers, payload=None):
        return self._request(
            "POST", f"/launch-seasons/{season_id}/run-review",
            _EMPTY if payload is None else payload, headers,
        )

    # -- Categories (PRD §3.1) ------------------------------------------------
    def create_category(self, payload, headers):
        return self._request("POST", "/categories", payload, headers)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/categories/{category_id}", headers=headers)

    def list_category_agreements(self, category_id, headers, params=None):
        return self._request(
            "GET", f"/categories/{category_id}/retail-agreements", headers=headers, params=params
        )

    def list_category_patent_cases(self, category_id, headers, params=None):
        return self._request(
            "GET", f"/categories/{category_id}/patent-cases", headers=headers, params=params
        )

    # -- Concepts, insights, prototype rounds (PRD §3.2) ----------------------
    def create_concept(self, payload, headers):
        return self._request("POST", "/concepts", payload, headers)

    def get_concept(self, concept_id, headers):
        return self._request("GET", f"/concepts/{concept_id}", headers=headers)

    def list_concepts(self, headers, params=None):
        return self._request("GET", "/concepts", headers=headers, params=params)

    def add_insight(self, concept_id, payload, headers):
        return self._request("POST", f"/concepts/{concept_id}/insights", payload, headers)

    def advance_concept(self, concept_id, headers, payload=None):
        return self._request(
            "POST", f"/concepts/{concept_id}/advance",
            _EMPTY if payload is None else payload, headers,
        )

    def create_round(self, concept_id, headers, payload=None):
        return self._request(
            "POST", f"/concepts/{concept_id}/rounds",
            _EMPTY if payload is None else payload, headers,
        )

    def list_rounds(self, concept_id, headers, params=None):
        return self._request(
            "GET", f"/concepts/{concept_id}/rounds", headers=headers, params=params
        )

    def complete_round(self, round_id, payload, headers):
        return self._request(
            "POST", f"/prototype-rounds/{round_id}/complete", payload, headers
        )

    # -- Factory partners (PRD §3.3) ------------------------------------------
    def create_partner(self, payload, headers):
        return self._request("POST", "/factory-partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/factory-partners/{partner_id}", headers=headers)

    def suspend_partner(self, partner_id, headers, payload=None):
        return self._request(
            "POST", f"/factory-partners/{partner_id}/suspend",
            _EMPTY if payload is None else payload, headers,
        )

    # -- Model variants (PRD §3.3) --------------------------------------------
    def create_variant(self, payload, headers):
        return self._request("POST", "/model-variants", payload, headers)

    def get_variant(self, variant_id, headers):
        return self._request("GET", f"/model-variants/{variant_id}", headers=headers)

    def list_variants(self, headers, params=None):
        return self._request("GET", "/model-variants", headers=headers, params=params)

    def tool_variant(self, variant_id, payload, headers):
        return self._request("POST", f"/model-variants/{variant_id}/tool", payload, headers)

    def list_variant_claim_studies(self, variant_id, headers, params=None):
        return self._request(
            "GET", f"/model-variants/{variant_id}/claim-studies", headers=headers, params=params
        )

    def list_variant_media_tests(self, variant_id, headers, params=None):
        return self._request(
            "GET", f"/model-variants/{variant_id}/media-tests", headers=headers, params=params
        )

    def list_variant_replenishments(self, variant_id, headers, params=None):
        return self._request(
            "GET", f"/model-variants/{variant_id}/replenishments", headers=headers, params=params
        )

    # -- Claim studies (PRD §3.4) ---------------------------------------------
    def create_claim_study(self, payload, headers):
        return self._request("POST", "/claim-studies", payload, headers)

    def complete_claim_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/claim-studies/{study_id}/complete", payload, headers
        )

    def substantiate_claim_study(self, study_id, headers, payload=None):
        return self._request(
            "POST", f"/claim-studies/{study_id}/substantiate",
            _EMPTY if payload is None else payload, headers,
        )

    def challenge_claim_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/claim-studies/{study_id}/challenge", payload, headers
        )

    def retest_claim_study(self, study_id, headers, payload=None):
        return self._request(
            "POST", f"/claim-studies/{study_id}/retest",
            _EMPTY if payload is None else payload, headers,
        )

    # -- Media tests (PRD §3.5) -----------------------------------------------
    def create_media_test(self, payload, headers):
        return self._request("POST", "/media-tests", payload, headers)

    def air_media_test(self, media_id, payload, headers):
        return self._request("POST", f"/media-tests/{media_id}/air", payload, headers)

    def decide_media_test(self, media_id, payload, headers):
        return self._request("POST", f"/media-tests/{media_id}/decide", payload, headers)

    # -- Retail agreements (PRD §3.6) -----------------------------------------
    def create_retail_agreement(self, payload, headers):
        return self._request("POST", "/retail-agreements", payload, headers)

    def get_retail_agreement(self, agreement_id, headers):
        return self._request("GET", f"/retail-agreements/{agreement_id}", headers=headers)

    def sign_retail_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/retail-agreements/{agreement_id}/sign",
            _EMPTY if payload is None else payload, headers,
        )

    # -- Launch commitments (PRD §3.6) ----------------------------------------
    def create_launch_commitment(self, payload, headers):
        return self._request("POST", "/launch-commitments", payload, headers)

    def get_launch_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"/launch-commitments/{commitment_id}", headers=headers
        )

    def list_launch_commitments(self, headers, params=None):
        return self._request("GET", "/launch-commitments", headers=headers, params=params)

    def cancel_launch_commitment(self, commitment_id, headers, payload=None):
        return self._request(
            "POST", f"/launch-commitments/{commitment_id}/cancel",
            _EMPTY if payload is None else payload, headers,
        )

    # -- Replenishment orders (PRD §3.7) --------------------------------------
    def create_replenishment_order(self, payload, headers):
        return self._request("POST", "/replenishment-orders", payload, headers)

    # -- Patent cases (PRD §3.8) ----------------------------------------------
    def create_patent_case(self, payload, headers):
        return self._request("POST", "/patent-cases", payload, headers)

    def settle_patent_case(self, case_id, payload, headers):
        return self._request("POST", f"/patent-cases/{case_id}/settle", payload, headers)

    def record_judgment(self, case_id, payload, headers):
        return self._request(
            "POST", f"/patent-cases/{case_id}/record-judgment", payload, headers
        )


api_client = ApiClient()
