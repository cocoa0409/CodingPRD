"""
HTTP client for the Child Support Enforcement API.

One method per endpoint in the PRD's endpoint table. Every method returns the
raw ``requests.Response`` so that a test can assert on the status code as well
as on the envelope. Every collection lives directly under ``/child-support``.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_ROOT


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the child support service."""

    # ================================================================
    # Logical clock
    # ================================================================

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /child-support/_clock/set_current_utc"""
        return self._request("POST", f"{API_ROOT}/_clock/set_current_utc", payload, headers)

    # ================================================================
    # Participants
    # ================================================================

    def create_participant(self, payload, headers) -> requests.Response:
        """POST /child-support/participants"""
        return self._request("POST", f"{API_ROOT}/participants", payload, headers)

    def get_participant(self, participant_id: str, headers) -> requests.Response:
        """GET /child-support/participants/{participant_id}"""
        return self._request("GET", f"{API_ROOT}/participants/{participant_id}", None, headers)

    def list_participants(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/participants"""
        return self._request("GET", f"{API_ROOT}/participants", params, headers)

    def patch_participant_income(self, participant_id: str, payload, headers) -> requests.Response:
        """PATCH /child-support/participants/{participant_id}/income"""
        return self._request(
            "PATCH", f"{API_ROOT}/participants/{participant_id}/income", payload, headers
        )

    def record_locate_result(self, participant_id: str, payload, headers) -> requests.Response:
        """POST /child-support/participants/{participant_id}/locate-results"""
        return self._request(
            "POST", f"{API_ROOT}/participants/{participant_id}/locate-results", payload, headers
        )

    # ================================================================
    # Cases
    # ================================================================

    def create_case(self, payload, headers) -> requests.Response:
        """POST /child-support/cases"""
        return self._request("POST", f"{API_ROOT}/cases", payload, headers)

    def get_case(self, case_id: str, headers) -> requests.Response:
        """GET /child-support/cases/{case_id}"""
        return self._request("GET", f"{API_ROOT}/cases/{case_id}", None, headers)

    def list_cases(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/cases"""
        return self._request("GET", f"{API_ROOT}/cases", params, headers)

    def create_locate_referral(self, case_id: str, payload, headers) -> requests.Response:
        """POST /child-support/cases/{case_id}/locate-referrals"""
        return self._request(
            "POST", f"{API_ROOT}/cases/{case_id}/locate-referrals", payload, headers
        )

    def close_case(self, case_id: str, payload, headers) -> requests.Response:
        """POST /child-support/cases/{case_id}/closure"""
        return self._request("POST", f"{API_ROOT}/cases/{case_id}/closure", payload, headers)

    def get_case_ledger(self, case_id: str, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/cases/{case_id}/ledger"""
        return self._request("GET", f"{API_ROOT}/cases/{case_id}/ledger", params, headers)

    def create_accrual_run(self, case_id: str, payload, headers) -> requests.Response:
        """POST /child-support/cases/{case_id}/accrual-runs"""
        return self._request(
            "POST", f"{API_ROOT}/cases/{case_id}/accrual-runs", payload, headers
        )

    # ================================================================
    # Paternity actions
    # ================================================================

    def create_paternity_action(self, case_id: str, payload, headers) -> requests.Response:
        """POST /child-support/cases/{case_id}/paternity-actions"""
        return self._request(
            "POST", f"{API_ROOT}/cases/{case_id}/paternity-actions", payload, headers
        )

    def get_paternity_action(self, paternity_action_id: str, headers) -> requests.Response:
        """GET /child-support/paternity-actions/{paternity_action_id}"""
        return self._request(
            "GET", f"{API_ROOT}/paternity-actions/{paternity_action_id}", None, headers
        )

    def list_paternity_actions(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/paternity-actions"""
        return self._request("GET", f"{API_ROOT}/paternity-actions", params, headers)

    def record_acknowledgment(self, paternity_action_id: str, payload, headers) -> requests.Response:
        """POST /child-support/paternity-actions/{paternity_action_id}/acknowledgment"""
        return self._request(
            "POST",
            f"{API_ROOT}/paternity-actions/{paternity_action_id}/acknowledgment",
            payload,
            headers,
        )

    def rescind_acknowledgment(self, paternity_action_id: str, payload, headers) -> requests.Response:
        """POST /child-support/paternity-actions/{paternity_action_id}/rescission"""
        return self._request(
            "POST",
            f"{API_ROOT}/paternity-actions/{paternity_action_id}/rescission",
            payload,
            headers,
        )

    def order_genetic_test(self, paternity_action_id: str, payload, headers) -> requests.Response:
        """POST /child-support/paternity-actions/{paternity_action_id}/genetic-test-order"""
        return self._request(
            "POST",
            f"{API_ROOT}/paternity-actions/{paternity_action_id}/genetic-test-order",
            payload,
            headers,
        )

    def record_specimen_collection(self, paternity_action_id: str, payload, headers) -> requests.Response:
        """POST /child-support/paternity-actions/{paternity_action_id}/specimen-collection"""
        return self._request(
            "POST",
            f"{API_ROOT}/paternity-actions/{paternity_action_id}/specimen-collection",
            payload,
            headers,
        )

    def record_genetic_result(self, paternity_action_id: str, payload, headers) -> requests.Response:
        """POST /child-support/paternity-actions/{paternity_action_id}/genetic-result"""
        return self._request(
            "POST",
            f"{API_ROOT}/paternity-actions/{paternity_action_id}/genetic-result",
            payload,
            headers,
        )

    # ================================================================
    # Support orders
    # ================================================================

    def create_order(self, case_id: str, payload, headers) -> requests.Response:
        """POST /child-support/cases/{case_id}/orders"""
        return self._request("POST", f"{API_ROOT}/cases/{case_id}/orders", payload, headers)

    def get_order(self, order_id: str, headers) -> requests.Response:
        """GET /child-support/orders/{order_id}"""
        return self._request("GET", f"{API_ROOT}/orders/{order_id}", None, headers)

    def list_orders(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/orders"""
        return self._request("GET", f"{API_ROOT}/orders", params, headers)

    def run_guideline_calculation(self, order_id: str, payload, headers) -> requests.Response:
        """POST /child-support/orders/{order_id}/guideline-calculation"""
        return self._request(
            "POST", f"{API_ROOT}/orders/{order_id}/guideline-calculation", payload, headers
        )

    def request_deviation(self, order_id: str, payload, headers) -> requests.Response:
        """POST /child-support/orders/{order_id}/deviation-request"""
        return self._request(
            "POST", f"{API_ROOT}/orders/{order_id}/deviation-request", payload, headers
        )

    def decide_deviation_findings(self, order_id: str, payload, headers) -> requests.Response:
        """POST /child-support/orders/{order_id}/deviation-findings"""
        return self._request(
            "POST", f"{API_ROOT}/orders/{order_id}/deviation-findings", payload, headers
        )

    def enter_order(self, order_id: str, payload, headers) -> requests.Response:
        """POST /child-support/orders/{order_id}/entry"""
        return self._request("POST", f"{API_ROOT}/orders/{order_id}/entry", payload, headers)

    def vacate_order(self, order_id: str, payload, headers) -> requests.Response:
        """POST /child-support/orders/{order_id}/vacatur"""
        return self._request("POST", f"{API_ROOT}/orders/{order_id}/vacatur", payload, headers)

    # ================================================================
    # Employers
    # ================================================================

    def create_employer(self, payload, headers) -> requests.Response:
        """POST /child-support/employers"""
        return self._request("POST", f"{API_ROOT}/employers", payload, headers)

    def get_employer(self, employer_id: str, headers) -> requests.Response:
        """GET /child-support/employers/{employer_id}"""
        return self._request("GET", f"{API_ROOT}/employers/{employer_id}", None, headers)

    def list_employers(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/employers"""
        return self._request("GET", f"{API_ROOT}/employers", params, headers)

    # ================================================================
    # Income withholding orders
    # ================================================================

    def issue_withholding_order(self, order_id: str, payload, headers) -> requests.Response:
        """POST /child-support/orders/{order_id}/withholding-orders"""
        return self._request(
            "POST", f"{API_ROOT}/orders/{order_id}/withholding-orders", payload, headers
        )

    def get_withholding_order(self, iwo_id: str, headers) -> requests.Response:
        """GET /child-support/withholding-orders/{iwo_id}"""
        return self._request("GET", f"{API_ROOT}/withholding-orders/{iwo_id}", None, headers)

    def list_withholding_orders(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/withholding-orders"""
        return self._request("GET", f"{API_ROOT}/withholding-orders", params, headers)

    def serve_withholding_order(self, iwo_id: str, payload, headers) -> requests.Response:
        """POST /child-support/withholding-orders/{iwo_id}/service"""
        return self._request(
            "POST", f"{API_ROOT}/withholding-orders/{iwo_id}/service", payload, headers
        )

    def amend_withholding_order(self, iwo_id: str, payload, headers) -> requests.Response:
        """POST /child-support/withholding-orders/{iwo_id}/amendment"""
        return self._request(
            "POST", f"{API_ROOT}/withholding-orders/{iwo_id}/amendment", payload, headers
        )

    def post_remittance(self, iwo_id: str, payload, headers) -> requests.Response:
        """POST /child-support/withholding-orders/{iwo_id}/remittances"""
        return self._request(
            "POST", f"{API_ROOT}/withholding-orders/{iwo_id}/remittances", payload, headers
        )

    def declare_remittance_lapse(self, iwo_id: str, payload, headers) -> requests.Response:
        """POST /child-support/withholding-orders/{iwo_id}/lapse"""
        return self._request(
            "POST", f"{API_ROOT}/withholding-orders/{iwo_id}/lapse", payload, headers
        )

    def terminate_withholding_order(self, iwo_id: str, payload, headers) -> requests.Response:
        """POST /child-support/withholding-orders/{iwo_id}/termination"""
        return self._request(
            "POST", f"{API_ROOT}/withholding-orders/{iwo_id}/termination", payload, headers
        )

    # ================================================================
    # Charges
    # ================================================================

    def post_charge(self, order_id: str, payload, headers) -> requests.Response:
        """POST /child-support/orders/{order_id}/charges"""
        return self._request("POST", f"{API_ROOT}/orders/{order_id}/charges", payload, headers)

    def get_charge(self, charge_id: str, headers) -> requests.Response:
        """GET /child-support/charges/{charge_id}"""
        return self._request("GET", f"{API_ROOT}/charges/{charge_id}", None, headers)

    def list_charges(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/charges"""
        return self._request("GET", f"{API_ROOT}/charges", params, headers)

    def void_charge(self, charge_id: str, payload, headers) -> requests.Response:
        """POST /child-support/charges/{charge_id}/voidance"""
        return self._request("POST", f"{API_ROOT}/charges/{charge_id}/voidance", payload, headers)

    # ================================================================
    # Payments
    # ================================================================

    def post_payment(self, case_id: str, payload, headers) -> requests.Response:
        """POST /child-support/cases/{case_id}/payments"""
        return self._request("POST", f"{API_ROOT}/cases/{case_id}/payments", payload, headers)

    def get_payment(self, payment_id: str, headers) -> requests.Response:
        """GET /child-support/payments/{payment_id}"""
        return self._request("GET", f"{API_ROOT}/payments/{payment_id}", None, headers)

    def list_payments(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/payments"""
        return self._request("GET", f"{API_ROOT}/payments", params, headers)

    # ================================================================
    # Modification reviews
    # ================================================================

    def create_modification_review(self, order_id: str, payload, headers) -> requests.Response:
        """POST /child-support/orders/{order_id}/modification-reviews"""
        return self._request(
            "POST", f"{API_ROOT}/orders/{order_id}/modification-reviews", payload, headers
        )

    def get_modification_review(self, modification_review_id: str, headers) -> requests.Response:
        """GET /child-support/modification-reviews/{modification_review_id}"""
        return self._request(
            "GET", f"{API_ROOT}/modification-reviews/{modification_review_id}", None, headers
        )

    def list_modification_reviews(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/modification-reviews"""
        return self._request("GET", f"{API_ROOT}/modification-reviews", params, headers)

    def screen_modification_review(self, modification_review_id: str, payload, headers) -> requests.Response:
        """POST /child-support/modification-reviews/{modification_review_id}/screening"""
        return self._request(
            "POST",
            f"{API_ROOT}/modification-reviews/{modification_review_id}/screening",
            payload,
            headers,
        )

    def supply_review_information(self, modification_review_id: str, payload, headers) -> requests.Response:
        """POST /child-support/modification-reviews/{modification_review_id}/information"""
        return self._request(
            "POST",
            f"{API_ROOT}/modification-reviews/{modification_review_id}/information",
            payload,
            headers,
        )

    def create_proposed_order(self, modification_review_id: str, payload, headers) -> requests.Response:
        """POST /child-support/modification-reviews/{modification_review_id}/proposed-order"""
        return self._request(
            "POST",
            f"{API_ROOT}/modification-reviews/{modification_review_id}/proposed-order",
            payload,
            headers,
        )

    # ================================================================
    # Enforcement actions
    # ================================================================

    def propose_enforcement_action(self, case_id: str, payload, headers) -> requests.Response:
        """POST /child-support/cases/{case_id}/enforcement-actions"""
        return self._request(
            "POST", f"{API_ROOT}/cases/{case_id}/enforcement-actions", payload, headers
        )

    def get_enforcement_action(self, enforcement_action_id: str, headers) -> requests.Response:
        """GET /child-support/enforcement-actions/{enforcement_action_id}"""
        return self._request(
            "GET", f"{API_ROOT}/enforcement-actions/{enforcement_action_id}", None, headers
        )

    def list_enforcement_actions(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/enforcement-actions"""
        return self._request("GET", f"{API_ROOT}/enforcement-actions", params, headers)

    def send_enforcement_notice(self, enforcement_action_id: str, payload, headers) -> requests.Response:
        """POST /child-support/enforcement-actions/{enforcement_action_id}/notice"""
        return self._request(
            "POST",
            f"{API_ROOT}/enforcement-actions/{enforcement_action_id}/notice",
            payload,
            headers,
        )

    def contest_enforcement_action(self, enforcement_action_id: str, payload, headers) -> requests.Response:
        """POST /child-support/enforcement-actions/{enforcement_action_id}/contest"""
        return self._request(
            "POST",
            f"{API_ROOT}/enforcement-actions/{enforcement_action_id}/contest",
            payload,
            headers,
        )

    def decide_enforcement_review(self, enforcement_action_id: str, payload, headers) -> requests.Response:
        """POST /child-support/enforcement-actions/{enforcement_action_id}/review-decision"""
        return self._request(
            "POST",
            f"{API_ROOT}/enforcement-actions/{enforcement_action_id}/review-decision",
            payload,
            headers,
        )

    def activate_enforcement_action(self, enforcement_action_id: str, payload, headers) -> requests.Response:
        """POST /child-support/enforcement-actions/{enforcement_action_id}/activation"""
        return self._request(
            "POST",
            f"{API_ROOT}/enforcement-actions/{enforcement_action_id}/activation",
            payload,
            headers,
        )

    def release_enforcement_action(self, enforcement_action_id: str, payload, headers) -> requests.Response:
        """POST /child-support/enforcement-actions/{enforcement_action_id}/release"""
        return self._request(
            "POST",
            f"{API_ROOT}/enforcement-actions/{enforcement_action_id}/release",
            payload,
            headers,
        )

    # ================================================================
    # Interstate referrals
    # ================================================================

    def create_interstate_referral(self, case_id: str, payload, headers) -> requests.Response:
        """POST /child-support/cases/{case_id}/interstate-referrals"""
        return self._request(
            "POST", f"{API_ROOT}/cases/{case_id}/interstate-referrals", payload, headers
        )

    def get_interstate_referral(self, interstate_referral_id: str, headers) -> requests.Response:
        """GET /child-support/interstate-referrals/{interstate_referral_id}"""
        return self._request(
            "GET", f"{API_ROOT}/interstate-referrals/{interstate_referral_id}", None, headers
        )

    def list_interstate_referrals(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/interstate-referrals"""
        return self._request("GET", f"{API_ROOT}/interstate-referrals", params, headers)

    def transmit_referral(self, interstate_referral_id: str, payload, headers) -> requests.Response:
        """POST /child-support/interstate-referrals/{interstate_referral_id}/transmittal"""
        return self._request(
            "POST",
            f"{API_ROOT}/interstate-referrals/{interstate_referral_id}/transmittal",
            payload,
            headers,
        )

    def register_referral(self, interstate_referral_id: str, payload, headers) -> requests.Response:
        """POST /child-support/interstate-referrals/{interstate_referral_id}/registration"""
        return self._request(
            "POST",
            f"{API_ROOT}/interstate-referrals/{interstate_referral_id}/registration",
            payload,
            headers,
        )

    def return_referral(self, interstate_referral_id: str, payload, headers) -> requests.Response:
        """POST /child-support/interstate-referrals/{interstate_referral_id}/return"""
        return self._request(
            "POST",
            f"{API_ROOT}/interstate-referrals/{interstate_referral_id}/return",
            payload,
            headers,
        )

    # ================================================================
    # Compromise offers
    # ================================================================

    def create_compromise_offer(self, case_id: str, payload, headers) -> requests.Response:
        """POST /child-support/cases/{case_id}/compromise-offers"""
        return self._request(
            "POST", f"{API_ROOT}/cases/{case_id}/compromise-offers", payload, headers
        )

    def get_compromise_offer(self, compromise_offer_id: str, headers) -> requests.Response:
        """GET /child-support/compromise-offers/{compromise_offer_id}"""
        return self._request(
            "GET", f"{API_ROOT}/compromise-offers/{compromise_offer_id}", None, headers
        )

    def list_compromise_offers(self, headers, params: Optional[Dict] = None) -> requests.Response:
        """GET /child-support/compromise-offers"""
        return self._request("GET", f"{API_ROOT}/compromise-offers", params, headers)

    def accept_compromise_offer(self, compromise_offer_id: str, payload, headers) -> requests.Response:
        """POST /child-support/compromise-offers/{compromise_offer_id}/acceptance"""
        return self._request(
            "POST",
            f"{API_ROOT}/compromise-offers/{compromise_offer_id}/acceptance",
            payload,
            headers,
        )

    def declare_compromise_default(self, compromise_offer_id: str, payload, headers) -> requests.Response:
        """POST /child-support/compromise-offers/{compromise_offer_id}/default-declaration"""
        return self._request(
            "POST",
            f"{API_ROOT}/compromise-offers/{compromise_offer_id}/default-declaration",
            payload,
            headers,
        )

    # ================================================================
    # Raw request escape hatch
    # ================================================================

    def raw_request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """Send an arbitrary request, for auth-header cases that must omit headers."""
        return self._request(method, path, payload, headers, params)


#: Module-level singleton shared by the whole suite.
api_client = ApiClient()
