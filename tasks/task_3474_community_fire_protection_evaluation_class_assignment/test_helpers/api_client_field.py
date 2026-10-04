"""Endpoint mixin: departments, apparatus, water systems, hydrants, flow tests, credits.

These are the field-data endpoints: the data the community's owners submit
while the evaluation data window is open, and the analyst's verification
actions on it. Every method returns the raw ``requests.Response``.
"""
from typing import Any, Dict, Optional

import requests


class FieldDataEndpoints:
    # ── Fire departments ─────────────────────────────────────────────────
    def list_fire_departments(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/fire-departments", headers=headers, params=params)

    def get_fire_department(self, department_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/fire-departments/{department_id}", headers=headers)

    def patch_fire_department(self, department_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("PATCH", f"/ppc/fire-departments/{department_id}", payload, headers)

    # ── Apparatus ────────────────────────────────────────────────────────
    def create_apparatus(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/ppc/apparatus", payload, headers)

    def list_apparatus(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/apparatus", headers=headers, params=params)

    def get_apparatus(self, apparatus_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/apparatus/{apparatus_id}", headers=headers)

    def patch_apparatus(self, apparatus_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("PATCH", f"/ppc/apparatus/{apparatus_id}", payload, headers)

    # ── Water supply systems ─────────────────────────────────────────────
    def list_water_supply_systems(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/water-supply-systems", headers=headers, params=params)

    def get_water_supply_system(self, system_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/water-supply-systems/{system_id}", headers=headers)

    def patch_water_supply_system(self, system_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("PATCH", f"/ppc/water-supply-systems/{system_id}", payload, headers)

    def verify_alternate_supply(self, system_id: str, headers: Optional[Dict[str, str]], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/ppc/water-supply-systems/{system_id}/verify-alternate-supply", payload if payload is not None else {}, headers)

    # ── Hydrants ─────────────────────────────────────────────────────────
    def create_hydrant(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/ppc/hydrants", payload, headers)

    def list_hydrants(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/hydrants", headers=headers, params=params)

    def get_hydrant(self, hydrant_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/hydrants/{hydrant_id}", headers=headers)

    def patch_hydrant(self, hydrant_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("PATCH", f"/ppc/hydrants/{hydrant_id}", payload, headers)

    # ── Flow tests ───────────────────────────────────────────────────────
    def create_flow_test(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/ppc/flow-tests", payload, headers)

    def list_flow_tests(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/flow-tests", headers=headers, params=params)

    def get_flow_test(self, test_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/flow-tests/{test_id}", headers=headers)

    def transition_flow_test(self, test_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/ppc/flow-tests/{test_id}/transition", payload, headers)

    # ── Risk reduction credits ───────────────────────────────────────────
    def create_risk_reduction_credit(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/ppc/risk-reduction-credits", payload, headers)

    def list_risk_reduction_credits(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/risk-reduction-credits", headers=headers, params=params)

    def get_risk_reduction_credit(self, credit_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/risk-reduction-credits/{credit_id}", headers=headers)

    def transition_risk_reduction_credit(self, credit_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/ppc/risk-reduction-credits/{credit_id}/transition", payload, headers)
