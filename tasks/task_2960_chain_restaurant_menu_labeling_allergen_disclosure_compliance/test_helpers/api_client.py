"""One method per endpoint of the PRD 4 endpoint table.

Every method returns the raw `requests.Response` so tests can assert on HTTP
status codes as well as on the envelope of PRD 2.2.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP client for the menu-labeling compliance API."""

    # ==================================================================
    # Reads (PRD 4: all five roles)
    # ==================================================================
    def get_brand(self, brand_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/brands/{brand_id}", headers=headers)

    def get_brand_compliance_summary(
        self, brand_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/brands/{brand_id}/compliance-summary", headers=headers
        )

    def list_brand_disclosure_packets(
        self,
        brand_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/brands/{brand_id}/disclosure-packets", headers=headers,
            params=params,
        )

    def list_brand_variance_requests(
        self,
        brand_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/brands/{brand_id}/variance-requests", headers=headers,
            params=params,
        )

    def get_jurisdiction(
        self, jurisdiction_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}", headers=headers
        )

    def list_jurisdiction_variance_requests(
        self,
        jurisdiction_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/jurisdictions/{jurisdiction_id}/variance-requests",
            headers=headers,
            params=params,
        )

    def list_jurisdiction_enforcement_actions(
        self,
        jurisdiction_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/jurisdictions/{jurisdiction_id}/enforcement-actions",
            headers=headers,
            params=params,
        )

    def get_establishment(
        self, establishment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/establishments/{establishment_id}", headers=headers
        )

    def list_establishments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/establishments", headers=headers, params=params)

    def list_establishment_enforcement_actions(
        self,
        establishment_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/establishments/{establishment_id}/enforcement-actions",
            headers=headers,
            params=params,
        )

    def get_menu_item(
        self, menu_item_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/menu-items/{menu_item_id}", headers=headers)

    def list_menu_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/menu-items", headers=headers, params=params)

    def list_menu_item_listings(
        self,
        menu_item_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/menu-items/{menu_item_id}/listings", headers=headers,
            params=params,
        )

    def get_recipe(self, recipe_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/recipes/{recipe_id}", headers=headers)

    def list_recipes(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/recipes", headers=headers, params=params)

    def list_recipe_components(
        self,
        recipe_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/recipes/{recipe_id}/components", headers=headers, params=params
        )

    def list_recipe_nutrition_analyses(
        self,
        recipe_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/recipes/{recipe_id}/nutrition-analyses",
            headers=headers,
            params=params,
        )

    def get_nutrition_analysis(
        self, analysis_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/nutrition-analyses/{analysis_id}", headers=headers
        )

    def get_menu_board(
        self, board_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/menu-boards/{board_id}", headers=headers)

    def list_menu_boards(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/menu-boards", headers=headers, params=params)

    def list_menu_board_listings(
        self,
        board_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/menu-boards/{board_id}/listings", headers=headers, params=params
        )

    def get_disclosure_packet(
        self, packet_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/disclosure-packets/{packet_id}", headers=headers
        )

    def get_variance_request(
        self, variance_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/variance-requests/{variance_id}", headers=headers
        )

    def get_enforcement_action(
        self, action_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/enforcement-actions/{action_id}", headers=headers
        )

    # ==================================================================
    # Registry writes (PRD 3.1)
    # ==================================================================
    def create_brand(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/brands", payload, headers)

    def create_jurisdiction(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/jurisdictions", payload, headers)

    def create_establishment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/establishments", payload, headers)

    def create_establishment_batch(
        self, brand_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/brands/{brand_id}/establishment-batches", payload, headers
        )

    def change_establishment_status(
        self, establishment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/establishments/{establishment_id}/status-changes", payload,
            headers,
        )

    def determine_coverage(
        self, brand_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/brands/{brand_id}/coverage-determinations", payload, headers
        )

    # ==================================================================
    # Menu writes (PRD 3.2)
    # ==================================================================
    def create_menu_item(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/menu-items", payload, headers)

    def append_offer_window(
        self, menu_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/menu-items/{menu_item_id}/offer-windows", payload, headers
        )

    def review_exemption(
        self, menu_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/menu-items/{menu_item_id}/exemption-reviews", payload, headers
        )

    # ==================================================================
    # Recipe and analysis writes (PRD 3.3, 3.4)
    # ==================================================================
    def create_recipe(
        self, menu_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/menu-items/{menu_item_id}/recipes", payload, headers
        )

    def add_recipe_component(
        self, recipe_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/recipes/{recipe_id}/components", payload, headers
        )

    def submit_for_analysis(
        self, recipe_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/recipes/{recipe_id}/submit-for-analysis", payload, headers
        )

    def decide_analysis(
        self, analysis_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/nutrition-analyses/{analysis_id}/decision", payload, headers
        )

    def withdraw_certification(
        self, recipe_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/recipes/{recipe_id}/withdraw-certification", payload, headers
        )

    # ==================================================================
    # Disclosure packet writes (PRD 3.5)
    # ==================================================================
    def create_disclosure_packet(
        self, brand_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/brands/{brand_id}/disclosure-packets", payload, headers
        )

    def publish_disclosure_packet(
        self, packet_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """PRD 3.5: packet publication carries no request body."""
        return self._request(
            "POST", f"/disclosure-packets/{packet_id}/publish", payload or {}, headers
        )

    # ==================================================================
    # Menu board writes (PRD 3.6, 3.7)
    # ==================================================================
    def create_menu_board(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/menu-boards", payload, headers)

    def create_listing(
        self, board_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/menu-boards/{board_id}/listings", payload, headers
        )

    def publish_menu_board(
        self, board_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/menu-boards/{board_id}/publish", payload, headers
        )

    def reprint_menu_board(
        self, board_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/menu-boards/{board_id}/reprint", payload, headers
        )

    # ==================================================================
    # Variance writes (PRD 3.8)
    # ==================================================================
    def create_variance_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/variance-requests", payload, headers)

    def decide_variance_request(
        self, variance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/variance-requests/{variance_id}/decision", payload, headers
        )

    # ==================================================================
    # Enforcement writes (PRD 3.9)
    # ==================================================================
    def create_enforcement_action(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/enforcement-actions", payload, headers)

    def create_enforcement_response(
        self, action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/enforcement-actions/{action_id}/responses", payload, headers
        )

    def create_regulator_action(
        self, action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enforcement-actions/{action_id}/regulator-actions",
            payload,
            headers,
        )

    # ==================================================================
    # Logical clock (PRD 2.4, 3.7)
    # ==================================================================
    def set_clock(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
