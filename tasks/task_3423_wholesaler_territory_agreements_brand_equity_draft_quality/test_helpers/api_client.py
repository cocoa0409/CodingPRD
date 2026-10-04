"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Territories ---
    def create_territory(self, payload, headers):
        return self._request("POST", "/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request("GET", f"/territories/{territory_id}", headers=headers)

    def list_territory_agreements(self, territory_id, headers, params=None):
        return self._request(
            "GET", f"/territories/{territory_id}/agreements", headers=headers, params=params
        )

    # --- Agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/agreements/{agreement_id}/amendments", payload, headers
        )

    def get_equity_index(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/agreements/{agreement_id}/equity-index", headers=headers, params=params
        )

    def list_agreement_transfers(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/agreements/{agreement_id}/transfer-applications",
            headers=headers,
            params=params,
        )

    # --- Wholesalers ---
    def create_wholesaler(self, payload, headers):
        return self._request("POST", "/wholesalers", payload, headers)

    def get_wholesaler(self, wholesaler_id, headers):
        return self._request("GET", f"/wholesalers/{wholesaler_id}", headers=headers)

    def list_wholesaler_agreements(self, wholesaler_id, headers, params=None):
        return self._request(
            "GET", f"/wholesalers/{wholesaler_id}/agreements", headers=headers, params=params
        )

    def list_wholesaler_retail_accounts(self, wholesaler_id, headers, params=None):
        return self._request(
            "GET",
            f"/wholesalers/{wholesaler_id}/retail-accounts",
            headers=headers,
            params=params,
        )

    def list_wholesaler_reviews(self, wholesaler_id, headers, params=None):
        return self._request(
            "GET",
            f"/wholesalers/{wholesaler_id}/performance-reviews",
            headers=headers,
            params=params,
        )

    # --- Transfer applications ---
    def create_transfer(self, payload, headers):
        return self._request("POST", "/transfer-applications", payload, headers)

    def qualification_review(self, transfer_id, headers):
        return self._request(
            "POST", f"/transfer-applications/{transfer_id}/qualification-review", {}, headers
        )

    def rofr_response(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/transfer-applications/{transfer_id}/rofr-response", payload, headers
        )

    def transfer_decision(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/transfer-applications/{transfer_id}/decision", payload, headers
        )

    def consummate_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/transfer-applications/{transfer_id}/consummate", {}, headers
        )

    # --- Performance reviews & corrective plans ---
    def create_review(self, payload, headers):
        return self._request("POST", "/performance-reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/performance-reviews/{review_id}", headers=headers)

    def review_response(self, review_id, payload, headers):
        return self._request(
            "POST", f"/performance-reviews/{review_id}/response", payload, headers
        )

    def list_review_plans(self, review_id, headers, params=None):
        return self._request(
            "GET",
            f"/performance-reviews/{review_id}/corrective-plans",
            headers=headers,
            params=params,
        )

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/corrective-plans/{plan_id}/activate", {}, headers)

    def resolve_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/corrective-plans/{plan_id}/resolve", payload, headers)

    def revise_plan(self, plan_id, headers):
        return self._request("POST", f"/corrective-plans/{plan_id}/revise", {}, headers)

    # --- Allocation events ---
    def create_allocation_event(self, payload, headers):
        return self._request("POST", "/allocation-events", payload, headers)

    def get_allocation_event(self, event_id, headers):
        return self._request("GET", f"/allocation-events/{event_id}", headers=headers)

    def request_allocation(self, event_id, payload, headers):
        return self._request(
            "POST", f"/allocation-events/{event_id}/requests", payload, headers
        )

    def lock_event(self, event_id, headers):
        return self._request("POST", f"/allocation-events/{event_id}/lock", {}, headers)

    def assignment_decision(self, event_id, wholesaler_id, payload, headers):
        return self._request(
            "POST",
            f"/allocation-events/{event_id}/assignments/{wholesaler_id}/decision",
            payload,
            headers,
        )

    # --- Retail accounts & draft audits ---
    def create_retail_account(self, payload, headers):
        return self._request("POST", "/retail-accounts", payload, headers)

    def get_retail_account(self, account_id, headers):
        return self._request("GET", f"/retail-accounts/{account_id}", headers=headers)

    def list_account_audits(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/retail-accounts/{account_id}/draft-audits", headers=headers, params=params
        )

    def create_draft_audit(self, payload, headers):
        return self._request("POST", "/draft-audits", payload, headers)

    # --- POS grants ---
    def list_account_pos_grants(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/retail-accounts/{account_id}/pos-grants", headers=headers, params=params
        )

    def create_pos_grant(self, payload, headers):
        return self._request("POST", "/pos-grants", payload, headers)

    def void_pos_grant(self, grant_id, headers):
        return self._request("POST", f"/pos-grants/{grant_id}/void", {}, headers)

    # --- Promotion programs ---
    def create_promotion(self, payload, headers):
        return self._request("POST", "/promotion-programs", payload, headers)

    def opt_in(self, program_id, headers):
        return self._request(
            "POST", f"/promotion-programs/{program_id}/opt-ins", {}, headers
        )


api_client = ApiClient()
