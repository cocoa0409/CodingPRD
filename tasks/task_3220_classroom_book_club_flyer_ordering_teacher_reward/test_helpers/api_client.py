"""HTTP client for the Classroom Book Club API.

One method per declared endpoint. Every method returns the raw response so a
test can assert on the status code as well as the body. Query filters and
pagination are passed as ``params``; request bodies as ``payload``. All paths
are mounted under the ``/club`` prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the contract declares."""

    # -- Logical clock and operational sweeps -------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/_clock/set_current_utc", payload, headers)

    def run_ops(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/_ops/run-ops", None, headers)

    def run_shipping(self, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/_ops/run-shipping", None, headers)

    # -- Schools ------------------------------------------------------------

    def create_school(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/schools", payload, headers)

    def list_schools(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/club/schools", None, headers, params=params)

    def get_school(self, school_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/club/schools/{school_id}", None, headers)

    def list_school_teachers(self, school_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/schools/{school_id}/teachers", None, headers, params=params)

    def list_school_flyer_cycles(self, school_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/schools/{school_id}/flyer-cycles", None, headers, params=params)

    def list_school_book_fairs(self, school_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/schools/{school_id}/book-fairs", None, headers, params=params)

    def list_school_donation_requests(self, school_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/schools/{school_id}/donation-requests", None, headers, params=params)

    def list_school_enrollments(self, school_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/schools/{school_id}/enrollments", None, headers, params=params)

    def enroll_program(self, school_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/schools/{school_id}/enroll-program", payload, headers)

    def suspend_program(self, school_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/schools/{school_id}/suspend-program", None, headers)

    def reinstate_program(self, school_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/schools/{school_id}/reinstate-program", None, headers)

    # -- Teachers -----------------------------------------------------------

    def create_teacher(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/teachers", payload, headers)

    def list_teachers(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/club/teachers", None, headers, params=params)

    def get_teacher(self, teacher_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/club/teachers/{teacher_id}", None, headers)

    def list_teacher_points_ledger(self, teacher_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/teachers/{teacher_id}/points-ledger", None, headers, params=params)

    def list_teacher_class_orders(self, teacher_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/teachers/{teacher_id}/class-orders", None, headers, params=params)

    def list_teacher_redemptions(self, teacher_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/teachers/{teacher_id}/redemptions", None, headers, params=params)

    def list_teacher_donation_requests(self, teacher_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/teachers/{teacher_id}/donation-requests", None, headers, params=params)

    # -- Titles -------------------------------------------------------------

    def create_title(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/titles", payload, headers)

    def acquire_title(self, title_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/titles/{title_id}/acquire", payload, headers)

    def list_titles(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/club/titles", None, headers, params=params)

    def get_title(self, title_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/club/titles/{title_id}", None, headers)

    def list_title_promotions(self, title_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/titles/{title_id}/promotions", None, headers, params=params)

    def list_title_offerings(self, title_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/titles/{title_id}/offerings", None, headers, params=params)

    def list_title_fair_titles(self, title_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/titles/{title_id}/fair-titles", None, headers, params=params)

    def list_title_donation_requests(self, title_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/titles/{title_id}/donation-requests", None, headers, params=params)

    def list_title_redemptions(self, title_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/titles/{title_id}/redemptions", None, headers, params=params)

    # -- Promotions ---------------------------------------------------------

    def create_promotion(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/promotions", payload, headers)

    def list_promotions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/club/promotions", None, headers, params=params)

    def get_promotion(self, promotion_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/club/promotions/{promotion_id}", None, headers)

    # -- Flyer cycles and offerings -----------------------------------------

    def create_flyer_cycle(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/flyer-cycles", payload, headers)

    def get_flyer_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/club/flyer-cycles/{cycle_id}", None, headers)

    def add_offering(self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/flyer-cycles/{cycle_id}/offerings", payload, headers)

    def list_cycle_offerings(self, cycle_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/flyer-cycles/{cycle_id}/offerings", None, headers, params=params)

    def get_offering(self, offering_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/club/offerings/{offering_id}", None, headers)

    def list_cycle_class_orders(self, cycle_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/flyer-cycles/{cycle_id}/class-orders", None, headers, params=params)

    def publish_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/flyer-cycles/{cycle_id}/publish", None, headers)

    def close_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/flyer-cycles/{cycle_id}/close", None, headers)

    def list_offering_lines(self, offering_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/offerings/{offering_id}/lines", None, headers, params=params)

    # -- Class orders and order lines ---------------------------------------

    def create_class_order(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/class-orders", payload, headers)

    def get_class_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/club/class-orders/{order_id}", None, headers)

    def list_order_lines(self, order_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/class-orders/{order_id}/lines", None, headers, params=params)

    def add_order_line(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/class-orders/{order_id}/lines", payload, headers)

    def update_order_line(self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("PATCH", f"/club/order-lines/{line_id}", payload, headers)

    def delete_order_line(self, line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("DELETE", f"/club/order-lines/{line_id}", None, headers)

    def submit_class_order(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/class-orders/{order_id}/submit", payload, headers)

    def cancel_class_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/class-orders/{order_id}/cancel", None, headers)

    # -- Book fairs ---------------------------------------------------------

    def create_book_fair(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/book-fairs", payload, headers)

    def get_book_fair(self, fair_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/club/book-fairs/{fair_id}", None, headers)

    def list_fair_titles(self, fair_id: str, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"/club/book-fairs/{fair_id}/titles", None, headers, params=params)

    def add_fair_title(self, fair_id: str, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/book-fairs/{fair_id}/titles", payload, headers)

    def cancel_book_fair(self, fair_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/book-fairs/{fair_id}/cancel", None, headers)

    # -- Donation requests --------------------------------------------------

    def create_donation_request(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/donation-requests", payload, headers)

    def get_donation_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/club/donation-requests/{request_id}", None, headers)

    def match_donation_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/donation-requests/{request_id}/match", None, headers)

    def fulfill_donation_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/donation-requests/{request_id}/fulfill", None, headers)

    def cancel_donation_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/donation-requests/{request_id}/cancel", None, headers)

    # -- Redemptions --------------------------------------------------------

    def create_redemption(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/club/redemptions", payload, headers)

    def get_redemption(self, redemption_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/club/redemptions/{redemption_id}", None, headers)

    def confirm_redemption(self, redemption_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/redemptions/{redemption_id}/confirm", None, headers)

    def cancel_redemption(self, redemption_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/club/redemptions/{redemption_id}/cancel", None, headers)


api_client = ApiClient()
