"""One method per endpoint of the Cement Plant & Kiln Operations API."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX
from .types import Headers, Payload


class ApiClient(GenericApiClient):
    """Thin endpoint wrapper: every method returns the raw response."""

    # -- plants -------------------------------------------------------------
    def create_plant(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/plants", payload, headers)

    def get_plant(self, plant_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/plants/{plant_id}", None, headers)

    def list_plants(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/plants", None, headers, params=params)

    def get_distribution_plan(
        self, plant_id: str, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/plants/{plant_id}/distribution-plan",
            None,
            headers,
            params=params,
        )

    # -- raw materials ------------------------------------------------------
    def create_raw_material(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/raw-materials", payload, headers)

    def get_raw_material(self, raw_material_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/raw-materials/{raw_material_id}", None, headers
        )

    def list_raw_materials(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/raw-materials", None, headers, params=params
        )

    # -- fuels --------------------------------------------------------------
    def create_fuel(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fuels", payload, headers)

    def get_fuel(self, fuel_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fuels/{fuel_id}", None, headers)

    def list_fuels(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fuels", None, headers, params=params)

    # -- customers ----------------------------------------------------------
    def create_customer(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/customers", payload, headers)

    def patch_customer(
        self, customer_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/customers/{customer_id}", payload, headers
        )

    def get_customer(self, customer_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/customers/{customer_id}", None, headers)

    def list_customers(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/customers", None, headers, params=params)

    # -- raw mix designs ----------------------------------------------------
    def create_design(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/raw-mix-designs", payload, headers)

    def patch_design(
        self, design_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/raw-mix-designs/{design_id}", payload, headers
        )

    def submit_design(
        self, design_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/raw-mix-designs/{design_id}/submit", payload or {}, headers
        )

    def request_design_revision(
        self, design_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/raw-mix-designs/{design_id}/request-revision",
            payload,
            headers,
        )

    def approve_design(
        self, design_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/raw-mix-designs/{design_id}/approve", payload or {}, headers
        )

    def get_design(self, design_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/raw-mix-designs/{design_id}", None, headers
        )

    def list_designs(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/raw-mix-designs", None, headers, params=params
        )

    # -- blended piles ------------------------------------------------------
    def create_pile(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/blended-piles", payload, headers)

    def add_pile_addition(
        self, pile_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/blended-piles/{pile_id}/additions", payload, headers
        )

    def seal_pile(
        self, pile_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/blended-piles/{pile_id}/seal", payload or {}, headers
        )

    def get_pile(self, pile_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/blended-piles/{pile_id}", None, headers)

    def list_piles(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/blended-piles", None, headers, params=params
        )

    # -- burn tests ---------------------------------------------------------
    def create_burn_test(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/burn-tests", payload, headers)

    def start_burn_test(
        self, burn_test_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/burn-tests/{burn_test_id}/start", payload or {}, headers
        )

    def record_burn_test_result(
        self, burn_test_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/burn-tests/{burn_test_id}/record-result", payload, headers
        )

    def adjudicate_burn_test(
        self, burn_test_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/burn-tests/{burn_test_id}/adjudicate", payload, headers
        )

    def get_burn_test(self, burn_test_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/burn-tests/{burn_test_id}", None, headers)

    def list_burn_tests(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/burn-tests", None, headers, params=params)

    # -- kilns --------------------------------------------------------------
    def create_kiln(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/kilns", payload, headers)

    def get_kiln(self, kiln_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/kilns/{kiln_id}", None, headers)

    def list_kilns(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/kilns", None, headers, params=params)

    # -- kiln runs ----------------------------------------------------------
    def create_kiln_run(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/kiln-runs", payload, headers)

    def light_kiln_run(
        self, kiln_run_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/kiln-runs/{kiln_run_id}/light", payload or {}, headers
        )

    def charge_fuel(
        self, kiln_run_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/kiln-runs/{kiln_run_id}/fuel-charges", payload, headers
        )

    def complete_kiln_run(
        self, kiln_run_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/kiln-runs/{kiln_run_id}/complete", payload or {}, headers
        )

    def abort_kiln_run(
        self, kiln_run_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/kiln-runs/{kiln_run_id}/abort", payload, headers
        )

    def release_clinker(
        self, kiln_run_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/kiln-runs/{kiln_run_id}/release-clinker",
            payload or {},
            headers,
        )

    def get_kiln_run(self, kiln_run_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/kiln-runs/{kiln_run_id}", None, headers)

    def list_kiln_runs(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/kiln-runs", None, headers, params=params)

    # -- kiln outages -------------------------------------------------------
    def create_outage(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/kiln-outages", payload, headers)

    def approve_outage(
        self, outage_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/kiln-outages/{outage_id}/approve", payload or {}, headers
        )

    def start_outage(
        self, outage_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/kiln-outages/{outage_id}/start", payload or {}, headers
        )

    def complete_outage(
        self, outage_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/kiln-outages/{outage_id}/complete", payload, headers
        )

    def get_outage(self, outage_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/kiln-outages/{outage_id}", None, headers)

    def list_outages(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/kiln-outages", None, headers, params=params
        )

    # -- silos --------------------------------------------------------------
    def create_silo(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/silos", payload, headers)

    def patch_silo(
        self, silo_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("PATCH", f"{API_PREFIX}/silos/{silo_id}", payload, headers)

    def get_silo(self, silo_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/silos/{silo_id}", None, headers)

    def list_silos(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/silos", None, headers, params=params)

    # -- cement batches -----------------------------------------------------
    def create_cement_batch(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/cement-batches", payload, headers)

    def start_grinding(
        self, cement_batch_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/cement-batches/{cement_batch_id}/start-grinding",
            payload or {},
            headers,
        )

    def finish_grinding(
        self, cement_batch_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/cement-batches/{cement_batch_id}/finish-grinding",
            payload or {},
            headers,
        )

    def get_cement_batch(self, cement_batch_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/cement-batches/{cement_batch_id}", None, headers
        )

    def list_cement_batches(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/cement-batches", None, headers, params=params
        )

    # -- laboratory tests ---------------------------------------------------
    def create_lab_test(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/lab-tests", payload, headers)

    def get_lab_test(self, lab_test_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/lab-tests/{lab_test_id}", None, headers)

    def list_lab_tests(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/lab-tests", None, headers, params=params)

    # -- mill certificates --------------------------------------------------
    def create_mill_certificate(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/mill-certificates", payload, headers)

    def issue_mill_certificate(
        self, mill_certificate_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/mill-certificates/{mill_certificate_id}/issue",
            payload or {},
            headers,
        )

    def revoke_mill_certificate(
        self, mill_certificate_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/mill-certificates/{mill_certificate_id}/revoke",
            payload,
            headers,
        )

    def get_mill_certificate(
        self, mill_certificate_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/mill-certificates/{mill_certificate_id}", None, headers
        )

    def list_mill_certificates(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/mill-certificates", None, headers, params=params
        )

    # -- loadout orders -----------------------------------------------------
    def create_loadout_order(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/loadout-orders", payload, headers)

    def start_loading(
        self, loadout_order_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/loadout-orders/{loadout_order_id}/start-loading",
            payload or {},
            headers,
        )

    def complete_loadout_order(
        self, loadout_order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/loadout-orders/{loadout_order_id}/complete",
            payload,
            headers,
        )

    def void_loadout_order(
        self, loadout_order_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/loadout-orders/{loadout_order_id}/void", payload, headers
        )

    def get_loadout_order(
        self, loadout_order_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/loadout-orders/{loadout_order_id}", None, headers
        )

    def list_loadout_orders(
        self, headers: Headers, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/loadout-orders", None, headers, params=params
        )

    # -- logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )


api_client = ApiClient()
