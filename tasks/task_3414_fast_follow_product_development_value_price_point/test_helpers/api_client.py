"""API client: one method per endpoint defined in the PRD.

Every method delegates to the framework's _request() and returns the raw
requests.Response so tests can assert status codes. `headers` is optional:
passing None (or omitting it) sends no X-User-ID / X-User-Role headers,
which is how unauthenticated-request tests are written.
"""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

__all__ = ["ApiClient", "api_client"]


class ApiClient(GenericApiClient):
    # --- Logical clock (PlatformAdmin) --------------------------------------
    def set_clock(self, current_utc: str, headers: Optional[dict] = None):
        """POST /_clock/set_current_utc — advance the server's logical clock."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- Trend signals (TrendScout) ------------------------------------------
    def create_trend_signal(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/trend-signals", payload, headers)

    def list_trend_signals(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", "/trend-signals", headers=headers, params=params)

    def patch_trend_signal(self, trend_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/trend-signals/{trend_id}", payload, headers)

    # --- Concepts (TrendScout) ------------------------------------------------
    def create_concept(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/concepts", payload, headers)

    def list_concepts(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", "/concepts", headers=headers, params=params)

    def get_concept(self, concept_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/concepts/{concept_id}", headers=headers)

    def patch_concept(self, concept_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/concepts/{concept_id}", payload, headers)

    # --- Products (ProductManager) --------------------------------------------
    def create_product(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def patch_product(self, product_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/products/{product_id}", payload, headers)

    # --- Contract manufacturers (SourcingLead) --------------------------------
    def create_manufacturer(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/manufacturers", payload, headers)

    def get_manufacturer(self, manufacturer_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/manufacturers/{manufacturer_id}", headers=headers)

    def patch_manufacturer(self, manufacturer_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/manufacturers/{manufacturer_id}", payload, headers)

    # --- Formula projects (SourcingLead / ManufacturerRep) --------------------
    def create_formula_project(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/formula-projects", payload, headers)

    def list_formula_projects(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", "/formula-projects", headers=headers, params=params)

    def get_formula_project(self, project_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/formula-projects/{project_id}", headers=headers)

    def patch_formula_project(self, project_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/formula-projects/{project_id}", payload, headers)

    # --- Cost quotes (ManufacturerRep submit; SourcingLead lifecycle) ---------
    def create_cost_quote(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/cost-quotes", payload, headers)

    def list_cost_quotes(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", "/cost-quotes", headers=headers, params=params)

    def get_cost_quote(self, quote_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/cost-quotes/{quote_id}", headers=headers)

    def patch_cost_quote(self, quote_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/cost-quotes/{quote_id}", payload, headers)

    # --- Compliance dossiers (ComplianceOfficer) ------------------------------
    def create_compliance_dossier(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/compliance-dossiers", payload, headers)

    def list_compliance_dossiers(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", "/compliance-dossiers", headers=headers, params=params)

    def get_compliance_dossier(self, dossier_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/compliance-dossiers/{dossier_id}", headers=headers)

    def submit_dossier_review(self, dossier_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"/compliance-dossiers/{dossier_id}/reviews", payload, headers
        )

    # --- Retail partners (RetailPlanner) --------------------------------------
    def create_retail_partner(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/retail-partners", payload, headers)

    def get_retail_partner(self, partner_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/retail-partners/{partner_id}", headers=headers)

    def patch_retail_partner(self, partner_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/retail-partners/{partner_id}", payload, headers)

    # --- Line reviews (RetailPlanner) ------------------------------------------
    def create_line_review(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/line-reviews", payload, headers)

    def list_line_reviews(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", "/line-reviews", headers=headers, params=params)

    def get_line_review(self, review_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/line-reviews/{review_id}", headers=headers)

    def patch_line_review(self, review_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/line-reviews/{review_id}", payload, headers)

    # --- Planogram slots (RetailPlanner) ---------------------------------------
    def create_planogram_slot(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/planogram-slots", payload, headers)

    def list_planogram_slots(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", "/planogram-slots", headers=headers, params=params)

    def get_planogram_slot(self, slot_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/planogram-slots/{slot_id}", headers=headers)

    def patch_planogram_slot(self, slot_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/planogram-slots/{slot_id}", payload, headers)

    # --- Launch plans (ProductManager; sampling fields MarketingLead) ----------
    def create_launch_plan(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/launch-plans", payload, headers)

    def list_launch_plans(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", "/launch-plans", headers=headers, params=params)

    def get_launch_plan(self, plan_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/launch-plans/{plan_id}", headers=headers)

    def patch_launch_plan(self, plan_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/launch-plans/{plan_id}", payload, headers)

    def create_sample_distribution(self, plan_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request(
            "POST", f"/launch-plans/{plan_id}/sample-distributions", payload, headers
        )

    # --- Discontinuation reviews (ProductManager propose; RetailPlanner decide)
    def create_discontinuation_review(self, payload: dict, headers: Optional[dict] = None):
        return self._request("POST", "/discontinuation-reviews", payload, headers)

    def list_discontinuation_reviews(self, headers: Optional[dict] = None, params: Optional[dict] = None):
        return self._request("GET", "/discontinuation-reviews", headers=headers, params=params)

    def get_discontinuation_review(self, review_id: str, headers: Optional[dict] = None):
        return self._request("GET", f"/discontinuation-reviews/{review_id}", headers=headers)

    def patch_discontinuation_review(self, review_id: str, payload: dict, headers: Optional[dict] = None):
        return self._request("PATCH", f"/discontinuation-reviews/{review_id}", payload, headers)


api_client = ApiClient()
