"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the `/ocs` path prefix.
"""

import json
import re

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/ocs"

# PRD 2.4 pins "exactly three fractional-second digits and a trailing `Z`" on
# `created_at` and `updated_at` (and 2.2 on `api_request_timestamp`) and on
# nothing else. Every other instant the API renders — window_start,
# last_service_at, price_protection_until, parts_eta, reconditioning_until and
# the rest — is left unspecified, so "...T09:00:00.000Z" and "...T09:00:00Z"
# are the same instant rendered two equally faithful ways. The suite quotes the
# minute-granularity instants the PRD prose itself uses, so a zero-millisecond
# suffix is normalised away here — on the unpinned fields only — leaving every
# assertion to compare the instant rather than its width.
_ZERO_MILLIS_INSTANT = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.000Z$")
_WIDTH_PINNED_KEYS = frozenset({"created_at", "updated_at", "api_request_timestamp"})


def _canonical_instants(node, key=None):
    if isinstance(node, dict):
        return {k: _canonical_instants(v, k) for k, v in node.items()}
    if isinstance(node, list):
        return [_canonical_instants(v, key) for v in node]
    if isinstance(node, str) and key not in _WIDTH_PINNED_KEYS:
        match = _ZERO_MILLIS_INSTANT.match(node)
        if match:
            return match.group(1) + "Z"
    return node


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        response = super()._request(method, path, payload, headers, params)
        try:
            body = response.json()
        except ValueError:
            return response
        canonical = _canonical_instants(body)
        if canonical != body:
            response._content = json.dumps(canonical).encode("utf-8")
        return response

    # --- Test-driving capabilities -------------------------------------------

    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    def set_green_index(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_market/set_green_index", payload, headers)

    # --- Routes --------------------------------------------------------------

    def create_route(self, payload, headers):
        return self._request("POST", f"{PREFIX}/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"{PREFIX}/routes/{route_id}", headers=headers)

    def get_route_day_load(self, route_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/routes/{route_id}/day-load", headers=headers, params=params
        )

    # --- Equipment models ----------------------------------------------------

    def create_equipment_model(self, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment-models", payload, headers)

    def list_equipment_models(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/equipment-models", headers=headers, params=params
        )

    def get_equipment_model(self, model_id, headers):
        return self._request(
            "GET", f"{PREFIX}/equipment-models/{model_id}", headers=headers
        )

    # --- Equipment assets ----------------------------------------------------

    def create_equipment_asset(self, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment-assets", payload, headers)

    def list_equipment_assets(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/equipment-assets", headers=headers, params=params
        )

    def get_equipment_asset(self, asset_id, headers):
        return self._request(
            "GET", f"{PREFIX}/equipment-assets/{asset_id}", headers=headers
        )

    # --- Product items -------------------------------------------------------

    def create_product_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/product-items", payload, headers)

    def list_product_items(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/product-items", headers=headers, params=params
        )

    def get_product_item(self, product_id, headers):
        return self._request(
            "GET", f"{PREFIX}/product-items/{product_id}", headers=headers
        )

    # --- Accounts ------------------------------------------------------------

    def create_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    def cancel_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/cancel", payload, headers
        )

    def recompute_allied_attachment(self, account_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/accounts/{account_id}/recompute-allied-attachment",
            payload,
            headers,
        )

    # --- Sites ---------------------------------------------------------------

    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    def update_site(self, site_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/sites/{site_id}", payload, headers)

    def size_and_plan_site(self, site_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sites/{site_id}/size-and-plan", payload, headers
        )

    def evaluate_service_posture(self, site_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sites/{site_id}/evaluate-service-posture", payload, headers
        )

    # --- Par levels ----------------------------------------------------------

    def create_par_level(self, payload, headers):
        return self._request("POST", f"{PREFIX}/par-levels", payload, headers)

    def list_par_levels(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/par-levels", headers=headers, params=params)

    def get_par_level(self, par_level_id, headers):
        return self._request("GET", f"{PREFIX}/par-levels/{par_level_id}", headers=headers)

    def update_par_level(self, par_level_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/par-levels/{par_level_id}", payload, headers
        )

    # --- Equipment placements ------------------------------------------------

    def create_placement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment-placements", payload, headers)

    def list_placements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/equipment-placements", headers=headers, params=params
        )

    def get_placement(self, placement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/equipment-placements/{placement_id}", headers=headers
        )

    def evaluate_placement_compliance(self, placement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/equipment-placements/{placement_id}/evaluate-compliance",
            payload,
            headers,
        )

    def retrieve_placement(self, placement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/equipment-placements/{placement_id}/retrieve",
            payload,
            headers,
        )

    # --- Service visits ------------------------------------------------------

    def create_visit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-visits", payload, headers)

    def list_visits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-visits", headers=headers, params=params
        )

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"{PREFIX}/service-visits/{visit_id}", headers=headers)

    def append_visit_line(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-visits/{visit_id}/lines", payload, headers
        )

    def reschedule_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-visits/{visit_id}/reschedule", payload, headers
        )

    def complete_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-visits/{visit_id}/complete", payload, headers
        )

    def void_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/service-visits/{visit_id}/void", payload, headers
        )

    # --- Maintenance work orders --------------------------------------------

    def create_work_order(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/maintenance-work-orders", payload, headers
        )

    def list_work_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/maintenance-work-orders", headers=headers, params=params
        )

    def get_work_order(self, work_order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/maintenance-work-orders/{work_order_id}", headers=headers
        )

    def advance_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/maintenance-work-orders/{work_order_id}/advance",
            payload,
            headers,
        )

    def loaner_swap(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/maintenance-work-orders/{work_order_id}/loaner-swap",
            payload,
            headers,
        )

    def loaner_return(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/maintenance-work-orders/{work_order_id}/loaner-return",
            payload,
            headers,
        )

    # --- Consolidated invoices ----------------------------------------------

    def create_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consolidated-invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/consolidated-invoices", headers=headers, params=params
        )

    def get_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"{PREFIX}/consolidated-invoices/{invoice_id}", headers=headers
        )

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consolidated-invoices/{invoice_id}/issue", payload, headers
        )

    def credit_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consolidated-invoices/{invoice_id}/credit", payload, headers
        )

    # --- Invoice lines -------------------------------------------------------

    def list_invoice_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/invoice-lines", headers=headers, params=params
        )

    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/invoice-lines/{line_id}", headers=headers)

    # --- Price adjustments ---------------------------------------------------

    def create_price_adjustment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/price-adjustments", payload, headers)

    def list_price_adjustments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/price-adjustments", headers=headers, params=params
        )

    def get_price_adjustment(self, adjustment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/price-adjustments/{adjustment_id}", headers=headers
        )

    def respond_price_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/price-adjustments/{adjustment_id}/respond", payload, headers
        )

    def revise_price_adjustment(self, adjustment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/price-adjustments/{adjustment_id}/revise", payload, headers
        )


api_client = ApiClient()
