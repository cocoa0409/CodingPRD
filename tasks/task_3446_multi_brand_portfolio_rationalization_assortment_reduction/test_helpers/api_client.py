"""API client: one typed method per endpoint defined in PRD §4.

All endpoints live under the /portfolio prefix EXCEPT the logical-clock
platform endpoint POST /_clock/set_current_utc, which is unprefixed (PRD §2.4).

The module-level `api_client` singleton is the canonical client instance;
tests and fixtures import it from the package barrel (test_helpers.api_client
the attribute) — the submodule of the same name is only ever accessed via
importlib or `from test_helpers.api_client import ApiClient`.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Platform clock (UNPREFIXED — do not add /portfolio) ──────────────────
    def set_clock(self, payload, headers):
        """POST /_clock/set_current_utc — body {"to_iso8601": ...}; HTTP 200."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Brands ───────────────────────────────────────────────────────────────
    def create_brand(self, payload, headers):
        return self._request("POST", "/portfolio/brands", payload, headers)

    def list_brands(self, headers, params=None):
        return self._request("GET", "/portfolio/brands", headers=headers, params=params)

    # ── Items ────────────────────────────────────────────────────────────────
    def create_item(self, payload, headers):
        return self._request("POST", "/portfolio/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/portfolio/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/portfolio/items/{item_id}", headers=headers)

    def sell_down_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/items/{item_id}/sell-down", payload, headers
        )

    # ── Plants ───────────────────────────────────────────────────────────────
    def create_plant(self, payload, headers):
        return self._request("POST", "/portfolio/plants", payload, headers)

    def list_plants(self, headers, params=None):
        return self._request("GET", "/portfolio/plants", headers=headers, params=params)

    def announce_plant_closure(self, plant_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/plants/{plant_id}/announce-closure", payload, headers
        )

    def complete_plant_closure(self, plant_id, headers):
        return self._request(
            "POST", f"/portfolio/plants/{plant_id}/complete-closure", {}, headers
        )

    # ── Retailers ────────────────────────────────────────────────────────────
    def create_retailer(self, payload, headers):
        return self._request("POST", "/portfolio/retailers", payload, headers)

    # ── Rationalization cases ────────────────────────────────────────────────
    def create_rationalization_case(self, payload, headers):
        return self._request("POST", "/portfolio/rationalization-cases", payload, headers)

    def list_rationalization_cases(self, headers, params=None):
        return self._request(
            "GET", "/portfolio/rationalization-cases", headers=headers, params=params
        )

    def get_rationalization_case(self, case_id, headers):
        return self._request(
            "GET", f"/portfolio/rationalization-cases/{case_id}", headers=headers
        )

    def decide_rationalization_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/rationalization-cases/{case_id}/decide", payload, headers
        )

    def finalize_rationalization_case(self, case_id, headers):
        return self._request(
            "POST", f"/portfolio/rationalization-cases/{case_id}/finalize", {}, headers
        )

    # ── Divestitures ─────────────────────────────────────────────────────────
    def create_divestiture(self, payload, headers):
        return self._request("POST", "/portfolio/divestitures", payload, headers)

    def list_divestitures(self, headers, params=None):
        return self._request(
            "GET", "/portfolio/divestitures", headers=headers, params=params
        )

    def get_divestiture(self, divestiture_id, headers):
        return self._request(
            "GET", f"/portfolio/divestitures/{divestiture_id}", headers=headers
        )

    def sign_divestiture_spa(self, divestiture_id, payload, headers):
        return self._request(
            "POST", f"/portfolio/divestitures/{divestiture_id}/sign-spa", payload, headers
        )

    def close_divestiture(self, divestiture_id, headers):
        return self._request(
            "POST", f"/portfolio/divestitures/{divestiture_id}/close", {}, headers
        )

    def separate_divestiture(self, divestiture_id, headers):
        return self._request(
            "POST", f"/portfolio/divestitures/{divestiture_id}/separate", {}, headers
        )

    # ── Transition service agreements ────────────────────────────────────────
    def list_tsas(self, headers, params=None):
        return self._request("GET", "/portfolio/tsas", headers=headers, params=params)

    def get_tsa(self, tsa_id, headers):
        return self._request("GET", f"/portfolio/tsas/{tsa_id}", headers=headers)

    def terminate_tsa(self, tsa_id, headers):
        return self._request("POST", f"/portfolio/tsas/{tsa_id}/terminate", {}, headers)

    # ── Product transfers & qualification runs ───────────────────────────────
    def create_product_transfer(self, payload, headers):
        return self._request("POST", "/portfolio/product-transfers", payload, headers)

    def list_product_transfers(self, headers, params=None):
        return self._request(
            "GET", "/portfolio/product-transfers", headers=headers, params=params
        )

    def get_product_transfer(self, transfer_id, headers):
        return self._request(
            "GET", f"/portfolio/product-transfers/{transfer_id}", headers=headers
        )

    def record_qualification_run(self, transfer_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/product-transfers/{transfer_id}/qualification-runs",
            payload,
            headers,
        )

    def list_qualification_runs(self, transfer_id, headers, params=None):
        return self._request(
            "GET",
            f"/portfolio/product-transfers/{transfer_id}/qualification-runs",
            headers=headers,
            params=params,
        )

    # ── Combined negotiations ────────────────────────────────────────────────
    def create_combined_negotiation(self, payload, headers):
        return self._request("POST", "/portfolio/combined-negotiations", payload, headers)

    def list_combined_negotiations(self, headers, params=None):
        return self._request(
            "GET", "/portfolio/combined-negotiations", headers=headers, params=params
        )

    def get_combined_negotiation(self, negotiation_id, headers):
        return self._request(
            "GET", f"/portfolio/combined-negotiations/{negotiation_id}", headers=headers
        )

    def respond_to_negotiation(self, negotiation_id, payload, headers):
        return self._request(
            "POST",
            f"/portfolio/combined-negotiations/{negotiation_id}/respond",
            payload,
            headers,
        )

    # ── Capital cycles & innovation projects ─────────────────────────────────
    def create_capital_cycle(self, payload, headers):
        return self._request("POST", "/portfolio/capital-cycles", payload, headers)

    def run_capital_cycle_selection(self, cycle_id, headers):
        return self._request(
            "POST", f"/portfolio/capital-cycles/{cycle_id}/run-selection", {}, headers
        )

    def create_innovation_project(self, payload, headers):
        return self._request("POST", "/portfolio/innovation-projects", payload, headers)

    def list_innovation_projects(self, headers, params=None):
        return self._request(
            "GET", "/portfolio/innovation-projects", headers=headers, params=params
        )

    def get_innovation_project(self, project_id, headers):
        return self._request(
            "GET", f"/portfolio/innovation-projects/{project_id}", headers=headers
        )


api_client = ApiClient()
