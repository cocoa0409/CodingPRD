"""Endpoint mixin: property risk profiles, premium quotes, reevaluation requests, appeals.

These are the rating-side and dispute-side endpoints. Every method returns
the raw ``requests.Response``; OCC-bearing writes take the expected parent
version inside ``payload``.
"""
from typing import Any, Dict, Optional

import requests


class InsuranceEndpoints:
    # ── Property risk profiles ───────────────────────────────────────────
    def create_property_risk_profile(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/ppc/property-risk-profiles", payload, headers)

    def list_property_risk_profiles(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/property-risk-profiles", headers=headers, params=params)

    def get_property_risk_profile(self, property_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/property-risk-profiles/{property_id}", headers=headers)

    # ── Premium quotes ───────────────────────────────────────────────────
    def create_premium_quote(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/ppc/premium-quotes", payload, headers)

    def list_premium_quotes(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/premium-quotes", headers=headers, params=params)

    def get_premium_quote(self, quote_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/premium-quotes/{quote_id}", headers=headers)

    def bind_premium_quote(self, quote_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/ppc/premium-quotes/{quote_id}/bind", payload, headers)

    def void_premium_quote(self, quote_id: str, headers: Optional[Dict[str, str]], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", f"/ppc/premium-quotes/{quote_id}/void", payload if payload is not None else {}, headers)

    # ── Reevaluation requests ────────────────────────────────────────────
    def create_reevaluation_request(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/ppc/reevaluation-requests", payload, headers)

    def list_reevaluation_requests(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/reevaluation-requests", headers=headers, params=params)

    def get_reevaluation_request(self, request_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/reevaluation-requests/{request_id}", headers=headers)

    def patch_reevaluation_request(self, request_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("PATCH", f"/ppc/reevaluation-requests/{request_id}", payload, headers)

    def transition_reevaluation_request(self, request_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/ppc/reevaluation-requests/{request_id}/transition", payload, headers)

    def approve_reevaluation_request(self, request_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/ppc/reevaluation-requests/{request_id}/approve", payload, headers)

    # ── Appeals ──────────────────────────────────────────────────────────
    def create_appeal(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", "/ppc/appeals", payload, headers)

    def list_appeals(self, headers: Optional[Dict[str, str]], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ppc/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id: str, headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("GET", f"/ppc/appeals/{appeal_id}", headers=headers)

    def transition_appeal(self, appeal_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]]) -> requests.Response:
        return self._request("POST", f"/ppc/appeals/{appeal_id}/transition", payload, headers)
