"""API client: one method per endpoint defined in the PRD (§4 table).

The base URL comes from the ``API_BASE_URL`` environment variable via the
framework's ``GenericApiClient`` — never hardcode a port here. Every method
accepts ``headers=None``; a call made with no headers arrives at the server
with neither ``X-User-ID`` nor ``X-User-Role``, which is exactly what the
authentication tests need.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/jbp/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Reference data (PRD §3.1)
    # ------------------------------------------------------------------
    def create_retailer(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/jbp/retailers", payload, headers)

    def create_category(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/jbp/categories", payload, headers)

    # ------------------------------------------------------------------
    # Joint business plans (PRD §3.1)
    # ------------------------------------------------------------------
    def create_plan(self, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", "/jbp/plans", payload, headers)

    def get_plan(self, plan_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/jbp/plans/{plan_id}", headers=headers)

    def list_plans(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/jbp/plans", headers=headers, params=params)

    def negotiate_plan(self, plan_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/plans/{plan_id}/negotiate", payload, headers)

    def decide_plan(self, plan_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/plans/{plan_id}/decide", payload, headers)

    def activate_plan(self, plan_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/plans/{plan_id}/activate", payload, headers)

    # ------------------------------------------------------------------
    # Promotional events (PRD §3.2)
    # ------------------------------------------------------------------
    def create_event(self, plan_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/plans/{plan_id}/events", payload, headers)

    def list_events(self, plan_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"/jbp/plans/{plan_id}/events", headers=headers, params=params)

    def lock_event(self, event_id: str, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/events/{event_id}/lock", headers=headers)

    def cancel_event(self, event_id: str, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/events/{event_id}/cancel", headers=headers)

    # ------------------------------------------------------------------
    # Category analyses (PRD §3.3)
    # ------------------------------------------------------------------
    def create_category_analysis(self, plan_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/plans/{plan_id}/category-analyses", payload, headers)

    def list_category_analyses(self, plan_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"/jbp/plans/{plan_id}/category-analyses", headers=headers, params=params)

    def decide_category_analysis(self, analysis_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/category-analyses/{analysis_id}/decide", payload, headers)

    # ------------------------------------------------------------------
    # Shelf recommendations (PRD §3.4)
    # ------------------------------------------------------------------
    def create_shelf_recommendation(self, plan_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/plans/{plan_id}/shelf-recommendations", payload, headers)

    def list_shelf_recommendations(self, plan_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"/jbp/plans/{plan_id}/shelf-recommendations", headers=headers, params=params)

    def decide_shelf_recommendation(self, rec_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/shelf-recommendations/{rec_id}/decide", payload, headers)

    def verify_shelf_recommendation(self, rec_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/shelf-recommendations/{rec_id}/verify", payload, headers)

    # ------------------------------------------------------------------
    # Innovation launches and phases (PRD §3.5)
    # ------------------------------------------------------------------
    def create_launch(self, plan_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/plans/{plan_id}/launches", payload, headers)

    def list_launches(self, plan_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"/jbp/plans/{plan_id}/launches", headers=headers, params=params)

    def get_launch(self, launch_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/jbp/launches/{launch_id}", headers=headers)

    def execute_launch(self, launch_id: str, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/launches/{launch_id}/launch", headers=headers)

    def list_launch_phases(self, launch_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"/jbp/launches/{launch_id}/phases", headers=headers, params=params)

    def patch_launch_phase(self, launch_id: str, phase_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("PATCH", f"/jbp/launches/{launch_id}/phases/{phase_id}", payload, headers)

    def evaluate_launch_phase(self, launch_id: str, phase_id: str, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/launches/{launch_id}/phases/{phase_id}/evaluate", headers=headers)

    # ------------------------------------------------------------------
    # Trade funds, accruals, deductions (PRD §3.6)
    # ------------------------------------------------------------------
    def get_fund(self, fund_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/jbp/funds/{fund_id}", headers=headers)

    def list_funds(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/jbp/funds", headers=headers, params=params)

    def post_fund_accrual(self, fund_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/funds/{fund_id}/accruals", payload, headers)

    def create_deduction(self, fund_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/funds/{fund_id}/deductions", payload, headers)

    def list_deductions(self, fund_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"/jbp/funds/{fund_id}/deductions", headers=headers, params=params)

    def resolve_deduction(self, deduction_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/deductions/{deduction_id}/resolve", payload, headers)

    # ------------------------------------------------------------------
    # Forecasts (PRD §3.7)
    # ------------------------------------------------------------------
    def create_forecast(self, plan_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/plans/{plan_id}/forecasts", payload, headers)

    def list_forecasts(self, plan_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"/jbp/plans/{plan_id}/forecasts", headers=headers, params=params)

    def commit_forecast(self, forecast_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/forecasts/{forecast_id}/commit", payload, headers)

    # ------------------------------------------------------------------
    # Price-pack decisions (PRD §3.8)
    # ------------------------------------------------------------------
    def create_price_pack_decision(self, plan_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/plans/{plan_id}/price-pack-decisions", payload, headers)

    def list_price_pack_decisions(self, plan_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"/jbp/plans/{plan_id}/price-pack-decisions", headers=headers, params=params)

    def decide_price_pack_decision(self, ppd_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/price-pack-decisions/{ppd_id}/decide", payload, headers)

    # ------------------------------------------------------------------
    # Performance reviews (PRD §3.9)
    # ------------------------------------------------------------------
    def create_performance_review(self, launch_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/launches/{launch_id}/performance-reviews", payload, headers)

    def list_performance_reviews(self, launch_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", f"/jbp/launches/{launch_id}/performance-reviews", headers=headers, params=params)

    def finalize_performance_review(self, review_id: str, payload: Dict, headers: Optional[Dict] = None):
        return self._request("POST", f"/jbp/performance-reviews/{review_id}/finalize", payload, headers)


api_client = ApiClient()
