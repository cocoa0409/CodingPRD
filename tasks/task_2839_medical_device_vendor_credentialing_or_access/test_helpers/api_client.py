"""One method per endpoint in the PRD's endpoint table.

Every method returns the raw ``requests.Response`` so a test can assert the
status code itself, and every path is mounted under the ``/vendor-access``
prefix of section 2.2. Query parameters are passed through untouched so that a
test can send an out-of-range ``limit`` and see the malformed-request refusal of
section 2.3.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class VendorAccessApiClient(GenericApiClient):
    """HTTP surface of the Medical Device Vendor Credentialing & OR Access API."""

    # ── Facilities ────────────────────────────────────────────────────────────
    def create_facility(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/facilities/{facility_id}", None, headers
        )

    # ── Vendors ───────────────────────────────────────────────────────────────
    def create_vendor(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/vendors/{vendor_id}", None, headers)

    def get_vendor_scorecard(
        self, vendor_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/vendors/{vendor_id}/scorecard", None, headers
        )

    # ── Vendor representatives ────────────────────────────────────────────────
    def create_vendor_rep(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/vendor-reps", payload, headers)

    def get_vendor_rep(self, rep_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/vendor-reps/{rep_id}", None, headers)

    def list_vendor_reps(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/vendor-reps", params, headers)

    def revoke_rep_access(
        self, rep_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/vendor-reps/{rep_id}/revoke-access", payload, headers
        )

    def list_rep_credentials(
        self, rep_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/vendor-reps/{rep_id}/credentials", params, headers
        )

    def list_rep_access_appeals(
        self, rep_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/vendor-reps/{rep_id}/access-appeals", params, headers
        )

    # ── Credentials ───────────────────────────────────────────────────────────
    def create_credential(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/credentials", payload, headers)

    def decide_credential(
        self, credential_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/credentials/{credential_id}/decide", payload, headers
        )

    # ── Surgical cases ────────────────────────────────────────────────────────
    def create_surgical_case(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/surgical-cases", payload, headers)

    def get_surgical_case(self, case_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/surgical-cases/{case_id}", None, headers
        )

    def list_surgical_cases(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/surgical-cases", params, headers)

    def reschedule_surgical_case(
        self, case_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/surgical-cases/{case_id}/reschedule", payload, headers
        )

    def cancel_surgical_case(
        self, case_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/surgical-cases/{case_id}/cancel", payload, headers
        )

    # ── Case representative authorizations ────────────────────────────────────
    def create_authorization(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/case-rep-authorizations", payload, headers
        )

    def get_authorization(self, auth_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/case-rep-authorizations/{auth_id}", None, headers
        )

    def list_authorizations(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/case-rep-authorizations", params, headers
        )

    def decide_authorization(
        self, auth_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/case-rep-authorizations/{auth_id}/decide",
            payload,
            headers,
        )

    def revoke_authorization(
        self, auth_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/case-rep-authorizations/{auth_id}/revoke",
            payload,
            headers,
        )

    def list_authorization_check_ins(
        self, auth_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/case-rep-authorizations/{auth_id}/check-ins",
            params,
            headers,
        )

    # ── Product introduction requests ─────────────────────────────────────────
    def create_pir(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/product-introduction-requests", payload, headers
        )

    def get_pir(self, pir_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/product-introduction-requests/{pir_id}", None, headers
        )

    def list_pirs(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/product-introduction-requests", params, headers
        )

    def submit_pir(
        self, pir_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/product-introduction-requests/{pir_id}/submit",
            payload,
            headers,
        )

    def clinical_review_pir(
        self, pir_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/product-introduction-requests/{pir_id}/clinical-review",
            payload,
            headers,
        )

    def value_analysis_decision(
        self, pir_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/product-introduction-requests/{pir_id}/value-analysis-decision",
            payload,
            headers,
        )

    # ── Approved products ─────────────────────────────────────────────────────
    def get_approved_product(self, product_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/approved-products/{product_id}", None, headers
        )

    def list_approved_products(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/approved-products", params, headers)

    # ── Loaner sets ───────────────────────────────────────────────────────────
    def create_loaner_set(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/loaner-sets", payload, headers)

    def get_loaner_set(self, set_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/loaner-sets/{set_id}", None, headers)

    def list_loaner_sets(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/loaner-sets", params, headers)

    def receive_loaner_set(
        self, set_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/loaner-sets/{set_id}/receive", payload, headers
        )

    def release_loaner_set(
        self, set_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/loaner-sets/{set_id}/release", payload, headers
        )

    # ── Kiosk check-ins ───────────────────────────────────────────────────────
    def create_check_in(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/kiosk-check-ins", payload, headers)

    def get_check_in(self, check_in_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/kiosk-check-ins/{check_in_id}", None, headers
        )

    def attach_escort(
        self, check_in_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/kiosk-check-ins/{check_in_id}/attach-escort",
            payload,
            headers,
        )

    def check_out(
        self, check_in_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/kiosk-check-ins/{check_in_id}/check-out",
            payload,
            headers,
        )

    # ── Incidents ─────────────────────────────────────────────────────────────
    def create_incident(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/incidents", payload, headers)

    def get_incident(self, incident_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/incidents/{incident_id}", None, headers
        )

    def list_incidents(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/incidents", params, headers)

    def investigate_incident(
        self, incident_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/incidents/{incident_id}/investigate", payload, headers
        )

    def adjudicate_incident(
        self, incident_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/incidents/{incident_id}/adjudicate", payload, headers
        )

    # ── Access appeals ────────────────────────────────────────────────────────
    def create_access_appeal(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/access-appeals", payload, headers)

    def get_access_appeal(self, appeal_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/access-appeals/{appeal_id}", None, headers
        )

    def decide_access_appeal(
        self, appeal_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/access-appeals/{appeal_id}/decide", payload, headers
        )

    # ── Compliance sweeps and the logical clock ───────────────────────────────
    def create_compliance_sweep(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/compliance-sweeps", payload, headers)

    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    # ── Escape hatch for path-shape probes ────────────────────────────────────
    def raw_get(
        self, path: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        """GET an arbitrary path under test, used for the 404 sweep over every entity."""
        return self._request("GET", path, params, headers)

    def raw_post(
        self, path: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """POST an arbitrary path under test."""
        return self._request("POST", path, payload, headers)
