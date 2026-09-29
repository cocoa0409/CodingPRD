"""API client: one method per endpoint defined in the PRD.

All franchise resources are mounted under the /franchise prefix. The logical
clock action is the sole endpoint served at the server root.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/franchise"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_current_utc(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ----------------------------------------------------------- franchisees
    def create_franchisee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/franchisees", payload, headers)

    def reinstate_franchisee(self, franchisee_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/franchisees/{franchisee_id}/reinstate", payload, headers
        )

    def get_franchisee(self, franchisee_id, headers):
        return self._request(
            "GET", f"{PREFIX}/franchisees/{franchisee_id}", headers=headers
        )

    def list_franchisees(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/franchisees", headers=headers, params=params)

    # ----------------------------------------------------------- territories
    def create_territory(self, payload, headers):
        return self._request("POST", f"{PREFIX}/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request(
            "GET", f"{PREFIX}/territories/{territory_id}", headers=headers
        )

    def list_territories(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/territories", headers=headers, params=params)

    # ----------------------------------------------------------------- clubs
    def create_club(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clubs", payload, headers)

    def open_club(self, club_id, payload, headers):
        return self._request("POST", f"{PREFIX}/clubs/{club_id}/open", payload, headers)

    def get_club(self, club_id, headers):
        return self._request("GET", f"{PREFIX}/clubs/{club_id}", headers=headers)

    def list_clubs(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/clubs", headers=headers, params=params)

    # ---------------------------------------------------- relocation requests
    def create_relocation_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/relocation-requests", payload, headers)

    def submit_relocation_request(self, relocation_request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/relocation-requests/{relocation_request_id}/submit",
            payload,
            headers,
        )

    def request_changes_relocation_request(self, relocation_request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/relocation-requests/{relocation_request_id}/request-changes",
            payload,
            headers,
        )

    def decide_relocation_request(self, relocation_request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/relocation-requests/{relocation_request_id}/decide",
            payload,
            headers,
        )

    def withdraw_relocation_request(self, relocation_request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/relocation-requests/{relocation_request_id}/withdraw",
            payload,
            headers,
        )

    def get_relocation_request(self, relocation_request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/relocation-requests/{relocation_request_id}", headers=headers
        )

    def list_relocation_requests(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/relocation-requests", headers=headers, params=params
        )

    # ------------------------------------------------------- plan templates
    def create_plan_template(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plan-templates", payload, headers)

    def publish_plan_template(self, plan_template_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/plan-templates/{plan_template_id}/publish", payload, headers
        )

    def get_plan_template(self, plan_template_id, headers):
        return self._request(
            "GET", f"{PREFIX}/plan-templates/{plan_template_id}", headers=headers
        )

    def list_plan_templates(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/plan-templates", headers=headers, params=params
        )

    # ------------------------------------------------------------ promotions
    def create_promotion(self, payload, headers):
        return self._request("POST", f"{PREFIX}/promotions", payload, headers)

    def review_promotion(self, promotion_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/promotions/{promotion_id}/review", payload, headers
        )

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"{PREFIX}/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/promotions", headers=headers, params=params)

    # --------------------------------------------------------------- members
    def create_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/members/{member_id}", headers=headers)

    def list_members(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/members", headers=headers, params=params)

    # ---------------------------------------------------- corporate accounts
    def create_corporate_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/corporate-accounts", payload, headers)

    def fund_corporate_account(self, corporate_account_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/corporate-accounts/{corporate_account_id}/fund",
            payload,
            headers,
        )

    def allocate_corporate_account(self, corporate_account_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/corporate-accounts/{corporate_account_id}/allocate",
            payload,
            headers,
        )

    def recall_corporate_allocation(self, corporate_account_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/corporate-accounts/{corporate_account_id}/recall-allocation",
            payload,
            headers,
        )

    def suspend_corporate_account(self, corporate_account_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/corporate-accounts/{corporate_account_id}/suspend",
            payload,
            headers,
        )

    def get_corporate_account(self, corporate_account_id, headers):
        return self._request(
            "GET", f"{PREFIX}/corporate-accounts/{corporate_account_id}", headers=headers
        )

    def list_corporate_accounts(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/corporate-accounts", headers=headers, params=params
        )

    # ------------------------------------------------------------ agreements
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements", payload, headers)

    def freeze_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/freeze", payload, headers
        )

    def unfreeze_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/unfreeze", payload, headers
        )

    def request_cancellation(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/agreements/{agreement_id}/request-cancellation",
            payload,
            headers,
        )

    def finalize_cancellation(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/agreements/{agreement_id}/finalize-cancellation",
            payload,
            headers,
        )

    def place_in_collections(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/agreements/{agreement_id}/place-in-collections",
            payload,
            headers,
        )

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/agreements", headers=headers, params=params)

    # -------------------------------------------------------- billing events
    def create_billing_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/billing-events", payload, headers)

    def get_billing_event(self, billing_event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/billing-events/{billing_event_id}", headers=headers
        )

    def list_agreement_billing_events(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/agreements/{agreement_id}/billing-events",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------ transfer requests
    def create_transfer_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transfer-requests", payload, headers)

    def decide_transfer_request(self, transfer_request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-requests/{transfer_request_id}/decide",
            payload,
            headers,
        )

    def complete_transfer_request(self, transfer_request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/transfer-requests/{transfer_request_id}/complete",
            payload,
            headers,
        )

    def get_transfer_request(self, transfer_request_id, headers):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests/{transfer_request_id}", headers=headers
        )

    def list_transfer_requests(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/transfer-requests", headers=headers, params=params
        )

    # ---------------------------------------------------- guest usage events
    def create_guest_usage_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/guest-usage-events", payload, headers)

    def get_guest_usage_event(self, guest_usage_event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/guest-usage-events/{guest_usage_event_id}", headers=headers
        )

    def list_guest_usage_events(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/guest-usage-events", headers=headers, params=params
        )

    # ----------------------------------------------------- usage settlements
    def create_usage_settlement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/usage-settlements", payload, headers)

    def post_usage_settlement(self, usage_settlement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/usage-settlements/{usage_settlement_id}/post",
            payload,
            headers,
        )

    def reverse_usage_settlement(self, usage_settlement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/usage-settlements/{usage_settlement_id}/reverse",
            payload,
            headers,
        )

    def get_usage_settlement(self, usage_settlement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/usage-settlements/{usage_settlement_id}", headers=headers
        )

    def list_usage_settlements(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/usage-settlements", headers=headers, params=params
        )

    # -------------------------------------------------------- royalty reports
    def create_royalty_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/royalty-reports", payload, headers)

    def adjudicate_royalty_report(self, royalty_report_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/royalty-reports/{royalty_report_id}/adjudicate",
            payload,
            headers,
        )

    def get_royalty_report(self, royalty_report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/royalty-reports/{royalty_report_id}", headers=headers
        )

    def list_royalty_reports(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/royalty-reports", headers=headers, params=params
        )

    # ----------------------------------------------------------- inspections
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inspections", payload, headers)

    def score_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/score", payload, headers
        )

    def waive_inspection_remediation(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/inspections/{inspection_id}/waive-remediation",
            payload,
            headers,
        )

    def close_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/close", payload, headers
        )

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/inspections", headers=headers, params=params)


api_client = ApiClient()
