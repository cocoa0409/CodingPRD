"""Typed client exposing one method per endpoint of the service under test."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

# The service publishes every route at the root of the host.
PREFIX = ""

Json = Dict[str, Any]
Headers = Optional[Dict[str, str]]


class ApiClient(GenericApiClient):
    """One method per documented endpoint, returning the raw response."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_current_utc(self, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Terminals
    # ------------------------------------------------------------------

    def create_terminal(self, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/terminals", payload, headers)

    def get_terminal(self, terminal_id: str, headers: Headers = None):
        return self._request("GET", f"{PREFIX}/terminals/{terminal_id}", None, headers)

    def list_terminals(self, headers: Headers = None, params: Optional[Json] = None):
        return self._request("GET", f"{PREFIX}/terminals", None, headers, params)

    def get_crash_analytics(
        self,
        terminal_id: str,
        headers: Headers = None,
        params: Optional[Json] = None,
    ):
        return self._request(
            "GET", f"{PREFIX}/terminals/{terminal_id}/crash-analytics", None, headers, params
        )

    # ------------------------------------------------------------------
    # Drivers
    # ------------------------------------------------------------------

    def create_driver(self, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/drivers", payload, headers)

    def get_driver(self, driver_id: str, headers: Headers = None):
        return self._request("GET", f"{PREFIX}/drivers/{driver_id}", None, headers)

    def list_drivers(self, headers: Headers = None, params: Optional[Json] = None):
        return self._request("GET", f"{PREFIX}/drivers", None, headers, params)

    def decide_employment(self, driver_id: str, payload: Json, headers: Headers = None):
        return self._request(
            "POST", f"{PREFIX}/drivers/{driver_id}/employment-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Crashes
    # ------------------------------------------------------------------

    def create_crash(self, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/crashes", payload, headers)

    def get_crash(self, crash_id: str, headers: Headers = None):
        return self._request("GET", f"{PREFIX}/crashes/{crash_id}", None, headers)

    def list_crashes(self, headers: Headers = None, params: Optional[Json] = None):
        return self._request("GET", f"{PREFIX}/crashes", None, headers, params)

    def create_driver_statement(self, crash_id: str, payload: Json, headers: Headers = None):
        return self._request(
            "POST", f"{PREFIX}/crashes/{crash_id}/driver-statements", payload, headers
        )

    def list_driver_statements(
        self, crash_id: str, headers: Headers = None, params: Optional[Json] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/crashes/{crash_id}/driver-statements", None, headers, params
        )

    def create_evidence_item(self, crash_id: str, payload: Json, headers: Headers = None):
        return self._request(
            "POST", f"{PREFIX}/crashes/{crash_id}/evidence-items", payload, headers
        )

    def list_crash_evidence_items(
        self, crash_id: str, headers: Headers = None, params: Optional[Json] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/crashes/{crash_id}/evidence-items", None, headers, params
        )

    def file_regulatory_report(self, crash_id: str, payload: Json, headers: Headers = None):
        return self._request(
            "POST", f"{PREFIX}/crashes/{crash_id}/regulatory-report", payload, headers
        )

    # ------------------------------------------------------------------
    # Evidence items
    # ------------------------------------------------------------------

    def get_evidence_item(self, evidence_item_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{PREFIX}/evidence-items/{evidence_item_id}", None, headers
        )

    def list_evidence_items(self, headers: Headers = None, params: Optional[Json] = None):
        return self._request("GET", f"{PREFIX}/evidence-items", None, headers, params)

    def preserve_evidence_item(
        self, evidence_item_id: str, payload: Json, headers: Headers = None
    ):
        return self._request(
            "POST", f"{PREFIX}/evidence-items/{evidence_item_id}/preserve", payload, headers
        )

    def purge_evidence_item(
        self, evidence_item_id: str, payload: Json, headers: Headers = None
    ):
        return self._request(
            "POST", f"{PREFIX}/evidence-items/{evidence_item_id}/purge", payload, headers
        )

    # ------------------------------------------------------------------
    # Review cases
    # ------------------------------------------------------------------

    def create_review_case(self, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/review-cases", payload, headers)

    def get_review_case(self, review_case_id: str, headers: Headers = None):
        return self._request("GET", f"{PREFIX}/review-cases/{review_case_id}", None, headers)

    def list_review_cases(self, headers: Headers = None, params: Optional[Json] = None):
        return self._request("GET", f"{PREFIX}/review-cases", None, headers, params)

    def open_deliberation(self, review_case_id: str, payload: Json = None, headers: Headers = None):
        return self._request(
            "POST",
            f"{PREFIX}/review-cases/{review_case_id}/open-deliberation",
            payload if payload is not None else {},
            headers,
        )

    def cast_vote(self, review_case_id: str, payload: Json, headers: Headers = None):
        return self._request(
            "POST", f"{PREFIX}/review-cases/{review_case_id}/votes", payload, headers
        )

    def list_votes(
        self, review_case_id: str, headers: Headers = None, params: Optional[Json] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/review-cases/{review_case_id}/votes", None, headers, params
        )

    def decide_review_case(
        self, review_case_id: str, payload: Json = None, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/review-cases/{review_case_id}/decide",
            payload if payload is not None else {},
            headers,
        )

    def appeal_review_case(self, review_case_id: str, payload: Json, headers: Headers = None):
        return self._request(
            "POST", f"{PREFIX}/review-cases/{review_case_id}/appeal", payload, headers
        )

    # ------------------------------------------------------------------
    # Policy layers
    # ------------------------------------------------------------------

    def create_policy_layer(self, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/policy-layers", payload, headers)

    def get_policy_layer(self, policy_layer_id: str, headers: Headers = None):
        return self._request("GET", f"{PREFIX}/policy-layers/{policy_layer_id}", None, headers)

    def list_policy_layers(self, headers: Headers = None, params: Optional[Json] = None):
        return self._request("GET", f"{PREFIX}/policy-layers", None, headers, params)

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    def create_claim(self, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def get_claim(self, claim_id: str, headers: Headers = None):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", None, headers)

    def list_claims(self, headers: Headers = None, params: Optional[Json] = None):
        return self._request("GET", f"{PREFIX}/claims", None, headers, params)

    def revise_reserve(self, claim_id: str, payload: Json, headers: Headers = None):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/reserve-revisions", payload, headers
        )

    def assign_counsel(self, claim_id: str, payload: Json, headers: Headers = None):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/counsel-assignment", payload, headers
        )

    def close_claim(self, claim_id: str, payload: Json = None, headers: Headers = None):
        return self._request(
            "POST",
            f"{PREFIX}/claims/{claim_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def create_demand(self, claim_id: str, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/demands", payload, headers)

    def list_claim_demands(
        self, claim_id: str, headers: Headers = None, params: Optional[Json] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/demands", None, headers, params
        )

    def create_subrogation_demand(self, claim_id: str, payload: Json, headers: Headers = None):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/subrogation-demands", payload, headers
        )

    def list_claim_subrogation_demands(
        self, claim_id: str, headers: Headers = None, params: Optional[Json] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/subrogation-demands", None, headers, params
        )

    # ------------------------------------------------------------------
    # Demands and negotiation
    # ------------------------------------------------------------------

    def get_demand(self, demand_id: str, headers: Headers = None):
        return self._request("GET", f"{PREFIX}/demands/{demand_id}", None, headers)

    def list_demands(self, headers: Headers = None, params: Optional[Json] = None):
        return self._request("GET", f"{PREFIX}/demands", None, headers, params)

    def create_offer(self, demand_id: str, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/demands/{demand_id}/offers", payload, headers)

    def create_counter(self, demand_id: str, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/demands/{demand_id}/counters", payload, headers)

    def list_negotiation_rounds(
        self, demand_id: str, headers: Headers = None, params: Optional[Json] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/demands/{demand_id}/negotiation-rounds", None, headers, params
        )

    def settle_demand(self, demand_id: str, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/demands/{demand_id}/settle", payload, headers)

    def rescind_settlement(self, demand_id: str, payload: Json, headers: Headers = None):
        return self._request(
            "POST", f"{PREFIX}/demands/{demand_id}/rescind-settlement", payload, headers
        )

    # ------------------------------------------------------------------
    # Disciplinary actions
    # ------------------------------------------------------------------

    def create_disciplinary_action(self, payload: Json, headers: Headers = None):
        return self._request("POST", f"{PREFIX}/disciplinary-actions", payload, headers)

    def get_disciplinary_action(self, action_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{PREFIX}/disciplinary-actions/{action_id}", None, headers
        )

    def list_disciplinary_actions(self, headers: Headers = None, params: Optional[Json] = None):
        return self._request("GET", f"{PREFIX}/disciplinary-actions", None, headers, params)

    def complete_retraining(self, action_id: str, payload: Json = None, headers: Headers = None):
        return self._request(
            "POST",
            f"{PREFIX}/disciplinary-actions/{action_id}/complete-retraining",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Subrogation demands
    # ------------------------------------------------------------------

    def get_subrogation_demand(self, subrogation_demand_id: str, headers: Headers = None):
        return self._request(
            "GET", f"{PREFIX}/subrogation-demands/{subrogation_demand_id}", None, headers
        )

    def list_subrogation_demands(self, headers: Headers = None, params: Optional[Json] = None):
        return self._request("GET", f"{PREFIX}/subrogation-demands", None, headers, params)

    def resolve_subrogation_demand(
        self, subrogation_demand_id: str, payload: Json, headers: Headers = None
    ):
        return self._request(
            "POST",
            f"{PREFIX}/subrogation-demands/{subrogation_demand_id}/resolve",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Verb probes used to confirm that no mutating verbs exist
    # ------------------------------------------------------------------

    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Json] = None,
        headers: Headers = None,
        params: Optional[Json] = None,
    ):
        return self._request(method, f"{PREFIX}{path}", payload, headers, params)
