"""API client: one method per endpoint declared in the API contract."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Store and logical clock ──────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def run_epoch(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/run_epoch", {}, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Member ───────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/stores/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/stores/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/stores/members", headers=headers, params=params)

    def patch_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/stores/members/{member_id}", payload, headers)

    def suspend_member(self, member_id, payload, headers):
        return self._request(
            "POST", f"/stores/members/{member_id}/suspend", payload, headers
        )

    def reinstate_member(self, member_id, headers, payload=None):
        return self._request(
            "POST", f"/stores/members/{member_id}/reinstate", payload or {}, headers
        )

    def list_member_ledger(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/stores/members/{member_id}/loyalty-ledger",
            headers=headers, params=params,
        )

    # ─── Element ──────────────────────────────────────
    def create_element(self, payload, headers):
        return self._request("POST", "/stores/elements", payload, headers)

    def get_element(self, element_id, headers):
        return self._request("GET", f"/stores/elements/{element_id}", headers=headers)

    def list_elements(self, headers, params=None):
        return self._request("GET", "/stores/elements", headers=headers, params=params)

    def retire_element(self, element_id, payload, headers):
        return self._request(
            "POST", f"/stores/elements/{element_id}/retire", payload, headers
        )

    def reissue_element(self, element_id, headers, payload=None):
        return self._request(
            "POST", f"/stores/elements/{element_id}/reissue", payload or {}, headers
        )

    # ─── WallBin ──────────────────────────────────────
    def create_wall_bin(self, payload, headers):
        return self._request("POST", "/stores/wall-bins", payload, headers)

    def get_wall_bin(self, bin_id, headers):
        return self._request("GET", f"/stores/wall-bins/{bin_id}", headers=headers)

    def list_wall_bins(self, headers, params=None):
        return self._request("GET", "/stores/wall-bins", headers=headers, params=params)

    def list_bin_allocations(self, bin_id, headers, params=None):
        return self._request(
            "GET", f"/stores/wall-bins/{bin_id}/allocations",
            headers=headers, params=params,
        )

    def restock_wall_bin(self, bin_id, payload, headers):
        return self._request(
            "POST", f"/stores/wall-bins/{bin_id}/restock", payload, headers
        )

    def rotate_wall_bins(self, payload, headers):
        return self._request("POST", "/stores/wall-bins/rotate", payload, headers)

    # ─── FusionOrder ──────────────────────────────────
    def create_fusion_order(self, payload, headers):
        return self._request("POST", "/stores/fusion-orders", payload, headers)

    def get_fusion_order(self, order_id, headers):
        return self._request("GET", f"/stores/fusion-orders/{order_id}", headers=headers)

    def list_fusion_orders(self, headers, params=None):
        return self._request(
            "GET", "/stores/fusion-orders", headers=headers, params=params
        )

    def create_allocation(self, order_id, payload, headers):
        return self._request(
            "POST", f"/stores/fusion-orders/{order_id}/allocations", payload, headers
        )

    def list_order_allocations(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/stores/fusion-orders/{order_id}/allocations",
            headers=headers, params=params,
        )

    def checkout_fusion_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/stores/fusion-orders/{order_id}/checkout", payload, headers
        )

    def void_fusion_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/stores/fusion-orders/{order_id}/void", payload, headers
        )

    # ─── ExitInspection ───────────────────────────────
    def create_exit_inspection(self, payload, headers):
        return self._request("POST", "/stores/exit-inspections", payload, headers)

    def get_exit_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/stores/exit-inspections/{inspection_id}", headers=headers
        )

    def list_exit_inspections(self, headers, params=None):
        return self._request(
            "GET", "/stores/exit-inspections", headers=headers, params=params
        )

    # ─── MinifigureBuild ──────────────────────────────
    def create_minifigure_build(self, payload, headers):
        return self._request("POST", "/stores/minifigure-builds", payload, headers)

    def get_minifigure_build(self, build_id, headers):
        return self._request(
            "GET", f"/stores/minifigure-builds/{build_id}", headers=headers
        )

    def list_minifigure_builds(self, headers, params=None):
        return self._request(
            "GET", "/stores/minifigure-builds", headers=headers, params=params
        )

    def set_build_components(self, build_id, payload, headers):
        return self._request(
            "POST", f"/stores/minifigure-builds/{build_id}/components",
            payload, headers,
        )

    def seal_build(self, build_id, payload, headers):
        return self._request(
            "POST", f"/stores/minifigure-builds/{build_id}/seal", payload, headers
        )

    # ─── ThemeLaunch ──────────────────────────────────
    def create_theme_launch(self, payload, headers):
        return self._request("POST", "/stores/theme-launches", payload, headers)

    def get_theme_launch(self, launch_id, headers):
        return self._request(
            "GET", f"/stores/theme-launches/{launch_id}", headers=headers
        )

    def list_theme_launches(self, headers, params=None):
        return self._request(
            "GET", "/stores/theme-launches", headers=headers, params=params
        )

    def reschedule_theme_launch(self, launch_id, payload, headers):
        return self._request(
            "POST", f"/stores/theme-launches/{launch_id}/reschedule", payload, headers
        )

    # ─── LaunchQueue ──────────────────────────────────
    def create_launch_queue(self, payload, headers):
        return self._request("POST", "/stores/launch-queues", payload, headers)

    def get_launch_queue(self, queue_id, headers):
        return self._request("GET", f"/stores/launch-queues/{queue_id}", headers=headers)

    def list_launch_queues(self, headers, params=None):
        return self._request(
            "GET", "/stores/launch-queues", headers=headers, params=params
        )

    def verify_identity(self, queue_id, payload, headers):
        return self._request(
            "POST", f"/stores/launch-queues/{queue_id}/verify-identity",
            payload, headers,
        )

    def grant_launch_queues(self, payload, headers):
        return self._request("POST", "/stores/launch-queues/grant", payload, headers)

    def purchase_launch_queue(self, queue_id, payload, headers):
        return self._request(
            "POST", f"/stores/launch-queues/{queue_id}/purchase", payload, headers
        )

    # ─── StoreEvent ───────────────────────────────────
    def create_store_event(self, payload, headers):
        return self._request("POST", "/stores/store-events", payload, headers)

    def get_store_event(self, event_id, headers):
        return self._request("GET", f"/stores/store-events/{event_id}", headers=headers)

    def list_store_events(self, headers, params=None):
        return self._request(
            "GET", "/stores/store-events", headers=headers, params=params
        )

    # ─── MiniBuildReservation ─────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/stores/mini-build-reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/stores/mini-build-reservations/{reservation_id}", headers=headers
        )

    def list_reservations(self, headers, params=None):
        return self._request(
            "GET", "/stores/mini-build-reservations", headers=headers, params=params
        )

    def check_in_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/stores/mini-build-reservations/{reservation_id}/check-in",
            payload or {}, headers,
        )

    def cancel_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/stores/mini-build-reservations/{reservation_id}/cancel",
            payload or {}, headers,
        )

    # ─── ReplacementRequest ───────────────────────────
    def create_replacement_request(self, payload, headers):
        return self._request("POST", "/stores/replacement-requests", payload, headers)

    def get_replacement_request(self, request_id, headers):
        return self._request(
            "GET", f"/stores/replacement-requests/{request_id}", headers=headers
        )

    def list_replacement_requests(self, headers, params=None):
        return self._request(
            "GET", "/stores/replacement-requests", headers=headers, params=params
        )

    def claim_replacement_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/stores/replacement-requests/{request_id}/claim",
            payload or {}, headers,
        )

    def complete_replacement_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/stores/replacement-requests/{request_id}/complete",
            payload or {}, headers,
        )

    # ─── LoyaltyLedger ────────────────────────────────
    def create_ledger_entry(self, payload, headers):
        return self._request("POST", "/stores/loyalty-ledger", payload, headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/stores/loyalty-ledger", headers=headers, params=params
        )


api_client = ApiClient()