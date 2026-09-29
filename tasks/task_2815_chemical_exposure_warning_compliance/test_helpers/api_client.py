"""One method per endpoint of the chemical exposure warning compliance API.

Every method returns the raw ``requests.Response`` so tests can assert on the
status code themselves.  Paths mirror the PRD endpoint table exactly.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Payload, QueryParams


class ChemicalComplianceApiClient(GenericApiClient):
    """HTTP surface of the compliance API under test."""

    # ─── Logical clock ────────────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Listed chemical registry ─────────────────────────────────────────────

    def create_listed_chemical(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/listed-chemicals", payload, headers)

    def get_listed_chemical(
        self, chemical_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/listed-chemicals/{chemical_id}", None, headers
        )

    def list_listed_chemicals(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/listed-chemicals", params or {}, headers)

    def listed_chemical_transition(
        self, chemical_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/listed-chemicals/{chemical_id}/transitions", payload, headers
        )

    # ─── Suppliers and warranties ─────────────────────────────────────────────

    def create_supplier(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/suppliers/{supplier_id}", None, headers)

    def supplier_transition(
        self, supplier_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/suppliers/{supplier_id}/transitions", payload, headers
        )

    # ─── Materials and the bill of materials ──────────────────────────────────

    def create_material(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/materials", payload, headers)

    def get_material(self, material_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/materials/{material_id}", None, headers)

    def list_materials(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/materials", params or {}, headers)

    def patch_material(
        self, material_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("PATCH", f"/materials/{material_id}", payload, headers)

    def material_disclosure(
        self, material_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/materials/{material_id}/disclosure", payload, headers
        )

    def create_material_chemical(
        self, material_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/materials/{material_id}/chemicals", payload, headers
        )

    # ─── Material/chemical links and laboratory testing ───────────────────────

    def get_material_chemical(
        self, material_chemical_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/material-chemicals/{material_chemical_id}", None, headers
        )

    def list_material_chemicals(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/material-chemicals", params or {}, headers)

    def material_chemical_transition(
        self, material_chemical_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/material-chemicals/{material_chemical_id}/transitions",
            payload,
            headers,
        )

    # ─── Products ─────────────────────────────────────────────────────────────

    def create_product(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/products/{product_id}", None, headers)

    def list_products(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/products", params or {}, headers)

    def patch_product(
        self, product_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("PATCH", f"/products/{product_id}", payload, headers)

    def product_transition(
        self, product_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/products/{product_id}/transitions", payload, headers
        )

    def product_version(self, product_id: str, headers: Headers) -> int:
        """Read the product's current ``version`` for optimistic concurrency."""
        response = self.get_product(product_id, headers)
        assert response.status_code == 200, (
            f"Could not read product version: HTTP {response.status_code} "
            f"{response.text}"
        )
        return response.json()["data"]["version"]

    def compliance_summary(
        self,
        product_id: str,
        headers: Headers,
        params: Optional[QueryParams] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/products/{product_id}/compliance-summary", params or {}, headers
        )

    # ─── Bill-of-materials components ─────────────────────────────────────────

    def create_component(
        self, product_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/products/{product_id}/components", payload, headers
        )

    def get_component(self, component_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/product-components/{component_id}", None, headers
        )

    def list_components(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/product-components", params or {}, headers)

    def patch_component(
        self, component_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/product-components/{component_id}", payload, headers
        )

    def component_transition(
        self, component_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/product-components/{component_id}/transitions", payload, headers
        )

    # ─── Exposure assessments ─────────────────────────────────────────────────

    def create_assessment(
        self, product_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/products/{product_id}/exposure-assessments", payload, headers
        )

    def get_assessment(self, assessment_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/exposure-assessments/{assessment_id}", None, headers
        )

    def list_assessments(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/exposure-assessments", params or {}, headers)

    def assessment_transition(
        self, assessment_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/exposure-assessments/{assessment_id}/transitions",
            payload,
            headers,
        )

    # ─── Warning determinations ───────────────────────────────────────────────

    def create_determination(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/warning-determinations", payload, headers)

    def get_determination(
        self, determination_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/warning-determinations/{determination_id}", None, headers
        )

    def list_determinations(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/warning-determinations", params or {}, headers)

    def determination_transition(
        self, determination_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/warning-determinations/{determination_id}/transitions",
            payload,
            headers,
        )

    # ─── Warning placements ───────────────────────────────────────────────────

    def create_placement(
        self, determination_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/warning-determinations/{determination_id}/placements",
            payload,
            headers,
        )

    def get_placement(self, placement_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/warning-placements/{placement_id}", None, headers
        )

    def list_placements(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/warning-placements", params or {}, headers)

    def placement_transition(
        self, placement_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/warning-placements/{placement_id}/transitions", payload, headers
        )

    # ─── Notices of violation ─────────────────────────────────────────────────

    def create_notice(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/notices", payload, headers)

    def get_notice(self, notice_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/notices/{notice_id}", None, headers)

    def list_notices(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/notices", params or {}, headers)

    def notice_transition(
        self, notice_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/notices/{notice_id}/transitions", payload, headers
        )

    def notice_version(self, notice_id: str, headers: Headers) -> int:
        """Read the notice's current ``version`` for optimistic concurrency."""
        response = self.get_notice(notice_id, headers)
        assert response.status_code == 200, (
            f"Could not read notice version: HTTP {response.status_code} "
            f"{response.text}"
        )
        return response.json()["data"]["version"]

    # ─── Settlements ──────────────────────────────────────────────────────────

    def create_settlement(
        self, notice_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/notices/{notice_id}/settlements", payload, headers
        )

    def get_settlement(self, settlement_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/settlements/{settlement_id}", None, headers)

    def list_settlements(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/settlements", params or {}, headers)

    def settlement_transition(
        self, settlement_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/settlements/{settlement_id}/transitions", payload, headers
        )

    # ─── Reformulation projects ───────────────────────────────────────────────

    def create_reformulation_project(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/reformulation-projects", payload, headers)

    def get_reformulation_project(
        self, project_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/reformulation-projects/{project_id}", None, headers
        )

    def list_reformulation_projects(
        self, headers: Headers, params: Optional[QueryParams] = None
    ) -> requests.Response:
        return self._request("GET", "/reformulation-projects", params or {}, headers)

    def reformulation_transition(
        self, project_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/reformulation-projects/{project_id}/transitions",
            payload,
            headers,
        )

    # ─── Raw escape hatches ───────────────────────────────────────────────────

    def raw_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[QueryParams] = None,
    ) -> requests.Response:
        """GET an arbitrary path, e.g. to send deliberately malformed headers."""
        return self._request("GET", path, params or {}, headers)

    def raw_post(
        self,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """POST to an arbitrary path with arbitrary headers."""
        return self._request("POST", path, payload, headers)
