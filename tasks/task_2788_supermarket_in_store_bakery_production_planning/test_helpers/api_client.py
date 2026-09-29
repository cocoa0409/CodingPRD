"""API client: one method per endpoint the PRD defines under ``/bakery``.

Also carries :func:`canonical_instant`, which normalises every ISO 8601 UTC
instant this suite compares to a fixed three-fractional-digit width so that a
server writing ``2026-08-12T04:20:00Z`` and one writing
``2026-08-12T04:20:00.000Z`` are both accepted.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/bakery"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Canonicalise an ISO 8601 UTC instant to exactly three fractional digits.

    ``None`` passes through untouched so null timestamp fields stay null.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[: -len("+00:00")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit())
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two instants denote the same moment at millisecond width."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    # ----- logical clock ---------------------------------------------------

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ----- departments -----------------------------------------------------

    def create_department(self, payload, headers):
        return self._request("POST", f"{BASE}/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request(
            "GET", f"{BASE}/departments/{department_id}", headers=headers
        )

    def list_departments(self, headers, params=None):
        return self._request("GET", f"{BASE}/departments", headers=headers, params=params)

    # ----- products --------------------------------------------------------

    def create_product(self, payload, headers):
        return self._request("POST", f"{BASE}/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{BASE}/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{BASE}/products", headers=headers, params=params)

    # ----- ingredients -----------------------------------------------------

    def create_ingredient(self, payload, headers):
        return self._request("POST", f"{BASE}/ingredients", payload, headers)

    def get_ingredient(self, ingredient_id, headers):
        return self._request(
            "GET", f"{BASE}/ingredients/{ingredient_id}", headers=headers
        )

    def list_ingredients(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/ingredients", headers=headers, params=params
        )

    # ----- ovens -----------------------------------------------------------

    def create_oven(self, payload, headers):
        return self._request("POST", f"{BASE}/ovens", payload, headers)

    def get_oven(self, oven_id, headers):
        return self._request("GET", f"{BASE}/ovens/{oven_id}", headers=headers)

    def list_ovens(self, headers, params=None):
        return self._request("GET", f"{BASE}/ovens", headers=headers, params=params)

    def set_oven_status(self, oven_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/ovens/{oven_id}/status", payload, headers
        )

    # ----- bake days -------------------------------------------------------

    def create_bake_day(self, payload, headers):
        return self._request("POST", f"{BASE}/bake-days", payload, headers)

    def get_bake_day(self, bake_day_id, headers):
        return self._request("GET", f"{BASE}/bake-days/{bake_day_id}", headers=headers)

    def list_bake_days(self, headers, params=None):
        return self._request("GET", f"{BASE}/bake-days", headers=headers, params=params)

    def append_forecast_line(self, bake_day_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/bake-days/{bake_day_id}/forecast-lines", payload, headers
        )

    def generate_plan(self, bake_day_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/bake-days/{bake_day_id}/generate-plan", payload, headers
        )

    def lock_plan(self, bake_day_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/bake-days/{bake_day_id}/lock-plan", payload or {}, headers
        )

    def close_bake_day(self, bake_day_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/bake-days/{bake_day_id}/close", payload or {}, headers
        )

    # ----- production runs -------------------------------------------------

    def create_production_run(self, payload, headers):
        return self._request("POST", f"{BASE}/production-runs", payload, headers)

    def get_production_run(self, run_id, headers):
        return self._request(
            "GET", f"{BASE}/production-runs/{run_id}", headers=headers
        )

    def list_production_runs(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/production-runs", headers=headers, params=params
        )

    def start_proof(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/production-runs/{run_id}/start-proof", payload or {}, headers
        )

    def start_bake(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/production-runs/{run_id}/start-bake", payload or {}, headers
        )

    def complete_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/production-runs/{run_id}/complete", payload, headers
        )

    def markdown_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/production-runs/{run_id}/markdown", payload or {}, headers
        )

    # ----- waste records ---------------------------------------------------

    def create_waste_record(self, payload, headers):
        return self._request("POST", f"{BASE}/waste-records", payload, headers)

    def get_waste_record(self, waste_record_id, headers):
        return self._request(
            "GET", f"{BASE}/waste-records/{waste_record_id}", headers=headers
        )

    def list_waste_records(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/waste-records", headers=headers, params=params
        )

    def void_waste_record(self, waste_record_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/waste-records/{waste_record_id}/void", payload, headers
        )

    # ----- pickup slots ----------------------------------------------------

    def create_pickup_slot(self, payload, headers):
        return self._request("POST", f"{BASE}/pickup-slots", payload, headers)

    def get_pickup_slot(self, pickup_slot_id, headers):
        return self._request(
            "GET", f"{BASE}/pickup-slots/{pickup_slot_id}", headers=headers
        )

    def list_pickup_slots(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/pickup-slots", headers=headers, params=params
        )

    def close_pickup_slot(self, pickup_slot_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/pickup-slots/{pickup_slot_id}/close", payload or {}, headers
        )

    # ----- custom cake orders ---------------------------------------------

    def create_cake_order(self, payload, headers):
        return self._request("POST", f"{BASE}/custom-cake-orders", payload, headers)

    def get_cake_order(self, order_id, headers):
        return self._request(
            "GET", f"{BASE}/custom-cake-orders/{order_id}", headers=headers
        )

    def list_cake_orders(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/custom-cake-orders", headers=headers, params=params
        )

    def confirm_cake_order(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/custom-cake-orders/{order_id}/confirm",
            payload or {},
            headers,
        )

    def start_decoration(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/custom-cake-orders/{order_id}/start-decoration",
            payload or {},
            headers,
        )

    def request_cake_revision(self, order_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/custom-cake-orders/{order_id}/request-revision",
            payload,
            headers,
        )

    def cake_order_ready(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/custom-cake-orders/{order_id}/ready", payload or {}, headers
        )

    def pickup_cake_order(self, order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/custom-cake-orders/{order_id}/pickup",
            payload or {},
            headers,
        )

    # ----- ingredient orders ----------------------------------------------

    def create_ingredient_order(self, payload, headers):
        return self._request("POST", f"{BASE}/ingredient-orders", payload, headers)

    def get_ingredient_order(self, ingredient_order_id, headers):
        return self._request(
            "GET", f"{BASE}/ingredient-orders/{ingredient_order_id}", headers=headers
        )

    def list_ingredient_orders(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/ingredient-orders", headers=headers, params=params
        )

    def submit_ingredient_order(self, ingredient_order_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/ingredient-orders/{ingredient_order_id}/submit",
            payload or {},
            headers,
        )

    def receive_ingredient_order(self, ingredient_order_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/ingredient-orders/{ingredient_order_id}/receive",
            payload,
            headers,
        )

    def cancel_ingredient_order(self, ingredient_order_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/ingredient-orders/{ingredient_order_id}/cancel",
            payload,
            headers,
        )


api_client = ApiClient()
