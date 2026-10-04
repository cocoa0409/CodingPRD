"""One method per endpoint in the merchandise API catalogue."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the generic HTTP client."""

    # ─── logical clock ──────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── price points ───────────────────────────────────────────────────────
    def create_price_point(self, payload, headers):
        return self._request("POST", "/merchandise/price-points", payload, headers)

    def list_price_points(self, headers, params=None):
        return self._request("GET", "/merchandise/price-points", headers=headers, params=params)

    def get_price_point(self, price_point_id, headers):
        return self._request("GET", f"/merchandise/price-points/{price_point_id}", headers=headers)

    def activate_price_point(self, price_point_id, headers):
        return self._request("POST", f"/merchandise/price-points/{price_point_id}/activate", {}, headers)

    def list_price_point_aisle_resets(self, price_point_id, headers, params=None):
        return self._request("GET", f"/merchandise/price-points/{price_point_id}/aisle-resets",
                             headers=headers, params=params)

    def list_price_point_conversion_projects(self, price_point_id, headers, params=None):
        return self._request("GET", f"/merchandise/price-points/{price_point_id}/conversion-projects",
                             headers=headers, params=params)

    # ─── vendors ────────────────────────────────────────────────────────────
    def create_vendor(self, payload, headers):
        return self._request("POST", "/merchandise/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/merchandise/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/merchandise/vendors/{vendor_id}", headers=headers)

    def list_vendor_pack_programs(self, vendor_id, headers, params=None):
        return self._request("GET", f"/merchandise/vendors/{vendor_id}/exclusive-pack-programs",
                             headers=headers, params=params)

    # ─── exclusive pack programs ────────────────────────────────────────────
    def create_pack_program(self, payload, headers):
        return self._request("POST", "/merchandise/exclusive-pack-programs", payload, headers)

    def list_pack_programs(self, headers, params=None):
        return self._request("GET", "/merchandise/exclusive-pack-programs", headers=headers, params=params)

    def get_pack_program(self, program_id, headers):
        return self._request("GET", f"/merchandise/exclusive-pack-programs/{program_id}", headers=headers)

    def patch_pack_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/merchandise/exclusive-pack-programs/{program_id}", payload, headers)

    # ─── items ──────────────────────────────────────────────────────────────
    def create_item(self, payload, headers):
        return self._request("POST", "/merchandise/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/merchandise/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/merchandise/items/{item_id}", headers=headers)

    def assign_item_price_point(self, item_id, price_point_id, headers):
        return self._request("POST", f"/merchandise/items/{item_id}/price-assignments",
                             {"price_point_id": price_point_id}, headers)

    def release_item_price_assignment(self, item_id, headers):
        return self._request("POST", f"/merchandise/items/{item_id}/price-assignment-release", {}, headers)

    def apply_landed_cost(self, item_id, payload, headers):
        return self._request("POST", f"/merchandise/items/{item_id}/landed-costs", payload, headers)

    def list_item_landed_costs(self, item_id, headers, params=None):
        return self._request("GET", f"/merchandise/items/{item_id}/landed-costs", headers=headers, params=params)

    def list_landed_cost_history(self, headers, params=None):
        return self._request("GET", "/merchandise/landed-cost-history", headers=headers, params=params)

    def get_break_even(self, item_id, headers):
        return self._request("GET", f"/merchandise/items/{item_id}/break-even", headers=headers)

    def activate_item(self, item_id, headers):
        return self._request("POST", f"/merchandise/items/{item_id}/activations", {}, headers)

    # ─── item deletion ──────────────────────────────────────────────────────
    def decide_item_deletion(self, item_id, decision, headers):
        return self._request("POST", f"/merchandise/item-deletions/{item_id}/decision",
                             {"decision": decision}, headers)

    # ─── containers ─────────────────────────────────────────────────────────
    def create_container(self, payload, headers):
        return self._request("POST", "/merchandise/containers", payload, headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/merchandise/containers", headers=headers, params=params)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/merchandise/containers/{container_id}", headers=headers)

    def container_depart(self, container_id, headers):
        return self._request("POST", f"/merchandise/containers/{container_id}/depart", {}, headers)

    def container_arrive(self, container_id, headers):
        return self._request("POST", f"/merchandise/containers/{container_id}/arrive", {}, headers)

    def container_customs_hold(self, container_id, headers):
        return self._request("POST", f"/merchandise/containers/{container_id}/customs-hold", {}, headers)

    def container_customs_release(self, container_id, headers):
        return self._request("POST", f"/merchandise/containers/{container_id}/customs-release", {}, headers)

    def container_receive(self, container_id, headers):
        return self._request("POST", f"/merchandise/containers/{container_id}/receive", {}, headers)

    def list_container_landed_costs(self, container_id, headers, params=None):
        return self._request("GET", f"/merchandise/containers/{container_id}/landed-cost-history",
                             headers=headers, params=params)

    # ─── allocation lines ───────────────────────────────────────────────────
    def create_allocation_line(self, payload, headers):
        return self._request("POST", "/merchandise/allocation-lines", payload, headers)

    def list_allocation_lines(self, headers, params=None):
        return self._request("GET", "/merchandise/allocation-lines", headers=headers, params=params)

    def get_allocation_line(self, line_id, headers):
        return self._request("GET", f"/merchandise/allocation-lines/{line_id}", headers=headers)

    def list_container_allocation_lines(self, container_id, headers, params=None):
        return self._request("GET", f"/merchandise/containers/{container_id}/allocation-lines",
                             headers=headers, params=params)

    def release_allocation_line(self, line_id, release_units, headers):
        return self._request("POST", f"/merchandise/allocation-lines/{line_id}/release",
                             {"release_units": release_units}, headers)

    def short_allocation_line(self, line_id, headers):
        return self._request("POST", f"/merchandise/allocation-lines/{line_id}/short", {}, headers)

    # ─── stores ─────────────────────────────────────────────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", "/merchandise/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/merchandise/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/merchandise/stores/{store_id}", headers=headers)

    def begin_conversion(self, store_id, to_price_point_id, headers):
        return self._request("POST", f"/merchandise/stores/{store_id}/conversions",
                             {"to_price_point_id": to_price_point_id}, headers)

    def file_conversion_artifact(self, store_id, conversion_id, artifact, headers):
        return self._request("POST", f"/merchandise/stores/{store_id}/conversions/{conversion_id}/filing",
                             {"artifact": artifact}, headers)

    def complete_conversion(self, store_id, conversion_id, headers):
        return self._request("POST", f"/merchandise/stores/{store_id}/conversions/{conversion_id}/complete",
                             {}, headers)

    def rollback_conversion(self, store_id, conversion_id, headers):
        return self._request("POST", f"/merchandise/stores/{store_id}/conversions/{conversion_id}/rollback",
                             {}, headers)

    def begin_reversion(self, store_id, to_price_point_id, headers):
        return self._request("POST", f"/merchandise/stores/{store_id}/reversions",
                             {"to_price_point_id": to_price_point_id}, headers)

    def list_store_audits(self, store_id, headers, params=None):
        return self._request("GET", f"/merchandise/stores/{store_id}/price-integrity-audits",
                             headers=headers, params=params)

    def list_store_aisle_resets(self, store_id, headers, params=None):
        return self._request("GET", f"/merchandise/stores/{store_id}/aisle-resets",
                             headers=headers, params=params)

    def list_store_conversion_projects(self, store_id, headers, params=None):
        return self._request("GET", f"/merchandise/stores/{store_id}/conversion-projects",
                             headers=headers, params=params)

    # ─── conversion projects ────────────────────────────────────────────────
    def create_conversion_project(self, payload, headers):
        return self._request("POST", "/merchandise/conversion-projects", payload, headers)

    def list_conversion_projects(self, headers, params=None):
        return self._request("GET", "/merchandise/conversion-projects", headers=headers, params=params)

    def get_conversion_project(self, project_id, headers):
        return self._request("GET", f"/merchandise/conversion-projects/{project_id}", headers=headers)

    def get_project_coverage(self, project_id, headers):
        return self._request("GET", f"/merchandise/conversion-projects/{project_id}/coverage", headers=headers)

    def start_conversion_project(self, project_id, headers):
        return self._request("POST", f"/merchandise/conversion-projects/{project_id}/start", {}, headers)

    def patch_conversion_project(self, project_id, payload, headers):
        return self._request("PATCH", f"/merchandise/conversion-projects/{project_id}", payload, headers)

    def create_multi_price_issue(self, payload, headers):
        return self._request("POST", "/merchandise/multi-price-issues", payload, headers)

    # ─── season windows ─────────────────────────────────────────────────────
    def create_season_window(self, payload, headers):
        return self._request("POST", "/merchandise/season-windows", payload, headers)

    def list_season_windows(self, headers, params=None):
        return self._request("GET", "/merchandise/season-windows", headers=headers, params=params)

    def get_season_window(self, window_id, headers):
        return self._request("GET", f"/merchandise/season-windows/{window_id}", headers=headers)

    def list_season_window_aisle_resets(self, window_id, headers, params=None):
        return self._request("GET", f"/merchandise/season-windows/{window_id}/aisle-resets",
                             headers=headers, params=params)

    def schedule_season_window(self, window_id, headers):
        return self._request("POST", f"/merchandise/season-windows/{window_id}/schedule", {}, headers)

    def unschedule_season_window(self, window_id, headers):
        return self._request("POST", f"/merchandise/season-windows/{window_id}/unschedule", {}, headers)

    # ─── aisle resets ───────────────────────────────────────────────────────
    def create_aisle_reset(self, payload, headers):
        return self._request("POST", "/merchandise/aisle-resets", payload, headers)

    def list_aisle_resets(self, headers, params=None):
        return self._request("GET", "/merchandise/aisle-resets", headers=headers, params=params)

    def get_aisle_reset(self, reset_id, headers):
        return self._request("GET", f"/merchandise/aisle-resets/{reset_id}", headers=headers)

    def begin_aisle_reset(self, reset_id, headers):
        return self._request("POST", f"/merchandise/aisle-resets/{reset_id}/begin", {}, headers)

    def execute_aisle_reset(self, reset_id, headers):
        return self._request("POST", f"/merchandise/aisle-resets/{reset_id}/execute", {}, headers)

    def abandon_aisle_reset(self, reset_id, headers):
        return self._request("POST", f"/merchandise/aisle-resets/{reset_id}/abandon", {}, headers)

    # ─── price integrity audits ─────────────────────────────────────────────
    def create_audit(self, payload, headers):
        return self._request("POST", "/merchandise/price-integrity-audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/merchandise/price-integrity-audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/merchandise/price-integrity-audits/{audit_id}", headers=headers)

    def resolve_audit(self, audit_id, headers):
        return self._request("POST", f"/merchandise/price-integrity-audits/{audit_id}/resolve", {}, headers)


api_client = ApiClient()