"""API client: one method per endpoint of the regional news operations API."""
from prd_bench_local_runner.testing import GenericApiClient

P = "/regional-news-ops"


class ApiClient(GenericApiClient):
    # ─── Clock and print-volume feed ────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def record_print_volume(self, payload, headers):
        return self._request("POST", f"{P}/_print-volume/records", payload, headers)

    # ─── RegionHub ───────────────────────────────────────────────────
    def create_hub(self, payload, headers):
        return self._request("POST", f"{P}/region-hubs", payload, headers)

    def list_hubs(self, headers, params=None):
        return self._request("GET", f"{P}/region-hubs", None, headers, params)

    def get_hub(self, hub_id, headers):
        return self._request("GET", f"{P}/region-hubs/{hub_id}", None, headers)

    def get_hub_compliance(self, hub_id, headers):
        return self._request("GET", f"{P}/region-hubs/{hub_id}/compliance", None, headers)

    # ─── Region ──────────────────────────────────────────────────────
    def create_region(self, hub_id, payload, headers):
        return self._request("POST", f"{P}/region-hubs/{hub_id}/regions", payload, headers)

    def list_regions(self, hub_id, headers, params=None):
        return self._request("GET", f"{P}/region-hubs/{hub_id}/regions", None, headers, params)

    def get_region(self, region_id, headers):
        return self._request("GET", f"{P}/regions/{region_id}", None, headers)

    # ─── PrintSite ───────────────────────────────────────────────────
    def create_print_site(self, hub_id, payload, headers):
        return self._request("POST", f"{P}/region-hubs/{hub_id}/print-sites", payload, headers)

    def list_print_sites(self, hub_id, headers, params=None):
        return self._request("GET", f"{P}/region-hubs/{hub_id}/print-sites", None, headers, params)

    def get_print_site(self, site_id, headers):
        return self._request("GET", f"{P}/print-sites/{site_id}", None, headers)

    def plan_site_closure(self, site_id, headers, payload=None):
        return self._request("POST", f"{P}/print-sites/{site_id}/plan-closure", payload or {}, headers)

    def begin_consolidating(self, site_id, headers):
        return self._request("POST", f"{P}/print-sites/{site_id}/begin-consolidating", {}, headers)

    def close_print_site(self, site_id, headers):
        return self._request("POST", f"{P}/print-sites/{site_id}/close", {}, headers)

    # ─── PrintRoute ──────────────────────────────────────────────────
    def create_print_route(self, site_id, payload, headers):
        return self._request("POST", f"{P}/print-sites/{site_id}/routes", payload, headers)

    def list_site_routes(self, site_id, headers, params=None):
        return self._request("GET", f"{P}/print-sites/{site_id}/routes", None, headers, params)

    def get_print_route(self, route_id, headers):
        return self._request("GET", f"{P}/print-routes/{route_id}", None, headers)

    def list_print_routes(self, headers, params=None):
        return self._request("GET", f"{P}/print-routes", None, headers, params)

    def list_route_markets(self, route_id, headers):
        return self._request("GET", f"{P}/print-routes/{route_id}/print-markets", None, headers)

    def list_site_editions(self, site_id, headers, params=None):
        return self._request("GET", f"{P}/print-sites/{site_id}/editions", None, headers, params)

    # ─── PrintMarket ─────────────────────────────────────────────────
    def create_print_market(self, region_id, payload, headers):
        return self._request("POST", f"{P}/regions/{region_id}/print-markets", payload, headers)

    def list_region_markets(self, region_id, headers, params=None):
        return self._request("GET", f"{P}/regions/{region_id}/print-markets", None, headers, params)

    def get_print_market(self, market_id, headers):
        return self._request("GET", f"{P}/print-markets/{market_id}", None, headers)

    def list_print_markets(self, headers, params=None):
        return self._request("GET", f"{P}/print-markets", None, headers, params)

    def plan_market_transfer(self, market_id, payload, headers):
        return self._request("POST", f"{P}/print-markets/{market_id}/plan-transfer", payload, headers)

    def redispatch_market(self, market_id, payload, headers):
        return self._request("POST", f"{P}/print-markets/{market_id}/redispatch", payload, headers)

    def withdraw_market(self, market_id, headers):
        return self._request("POST", f"{P}/print-markets/{market_id}/withdraw", {}, headers)

    def open_frequency_change(self, market_id, payload, headers):
        return self._request("POST", f"{P}/print-markets/{market_id}/frequency-change", payload, headers)

    def dispatch_frequency_notices(self, market_id, headers):
        return self._request("POST", f"{P}/print-markets/{market_id}/frequency-notices", {}, headers)

    def apply_frequency_change(self, market_id, headers):
        return self._request("POST", f"{P}/print-markets/{market_id}/frequency-apply", {}, headers)

    def reject_frequency_change(self, market_id, headers):
        return self._request("POST", f"{P}/print-markets/{market_id}/frequency-reject", {}, headers)

    def create_edition(self, market_id, payload, headers):
        return self._request("POST", f"{P}/print-markets/{market_id}/editions", payload, headers)

    def list_market_editions(self, market_id, headers, params=None):
        return self._request("GET", f"{P}/print-markets/{market_id}/editions", None, headers, params)

    def list_market_delivery_routes(self, market_id, headers, params=None):
        return self._request("GET", f"{P}/print-markets/{market_id}/delivery-routes", None, headers, params)

    def list_market_delivery_stops(self, market_id, headers, params=None):
        return self._request("GET", f"{P}/print-markets/{market_id}/delivery-stops", None, headers, params)

    def list_market_subscribers(self, market_id, headers, params=None):
        return self._request("GET", f"{P}/print-markets/{market_id}/subscribers", None, headers, params)

    # ─── LatestEdition ───────────────────────────────────────────────
    def get_edition(self, edition_id, headers):
        return self._request("GET", f"{P}/editions/{edition_id}", None, headers)

    def dispatch_edition(self, edition_id, headers):
        return self._request("POST", f"{P}/editions/{edition_id}/dispatch", {}, headers)

    def revert_edition_to_digital(self, edition_id, headers):
        return self._request("POST", f"{P}/editions/{edition_id}/revert-to-digital", {}, headers)

    def deliver_edition(self, edition_id, headers):
        return self._request("POST", f"{P}/editions/{edition_id}/deliver", {}, headers)

    def correct_edition(self, edition_id, headers):
        return self._request("POST", f"{P}/editions/{edition_id}/correct", {}, headers)

    # ─── DeliveryContractor ──────────────────────────────────────────
    def create_contractor(self, hub_id, payload, headers):
        return self._request("POST", f"{P}/region-hubs/{hub_id}/delivery-contractors", payload, headers)

    def list_contractors(self, hub_id, headers, params=None):
        return self._request("GET", f"{P}/region-hubs/{hub_id}/delivery-contractors", None, headers, params)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"{P}/delivery-contractors/{contractor_id}", None, headers)

    def suspend_contractor(self, contractor_id, payload, headers):
        return self._request("POST", f"{P}/delivery-contractors/{contractor_id}/suspend", payload, headers)

    def terminate_contractor(self, contractor_id, headers):
        return self._request("POST", f"{P}/delivery-contractors/{contractor_id}/terminate", {}, headers)

    def reinstate_contractor(self, contractor_id, headers):
        return self._request("POST", f"{P}/delivery-contractors/{contractor_id}/reinstate", {}, headers)

    # ─── DeliveryRoute ───────────────────────────────────────────────
    def create_delivery_route(self, contractor_id, payload, headers):
        return self._request("POST", f"{P}/delivery-contractors/{contractor_id}/routes", payload, headers)

    def list_contractor_routes(self, contractor_id, headers, params=None):
        return self._request("GET", f"{P}/delivery-contractors/{contractor_id}/routes", None, headers, params)

    def get_delivery_route(self, route_id, headers):
        return self._request("GET", f"{P}/delivery-routes/{route_id}", None, headers)

    def cost_run(self, route_id, payload, headers):
        return self._request("POST", f"{P}/delivery-routes/{route_id}/cost-run", payload, headers)

    def list_delivery_routes(self, headers, params=None):
        return self._request("GET", f"{P}/delivery-routes", None, headers, params)

    # ─── DeliveryStop ────────────────────────────────────────────────
    def create_delivery_stop(self, route_id, payload, headers):
        return self._request("POST", f"{P}/delivery-routes/{route_id}/stops", payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"{P}/delivery-routes/{route_id}/stops", None, headers, params)

    def get_delivery_stop(self, stop_id, headers):
        return self._request("GET", f"{P}/delivery-stops/{stop_id}", None, headers)

    def pause_stop(self, stop_id, headers):
        return self._request("POST", f"{P}/delivery-stops/{stop_id}/pause", {}, headers)

    def resume_stop(self, stop_id, headers):
        return self._request("POST", f"{P}/delivery-stops/{stop_id}/resume", {}, headers)

    def terminate_stop(self, stop_id, headers):
        return self._request("POST", f"{P}/delivery-stops/{stop_id}/terminate", {}, headers)

    # ─── SubscriberContract ──────────────────────────────────────────
    def create_subscriber(self, stop_id, payload, headers):
        return self._request("POST", f"{P}/delivery-stops/{stop_id}/subscribers", payload, headers)

    def list_stop_subscribers(self, stop_id, headers, params=None):
        return self._request("GET", f"{P}/delivery-stops/{stop_id}/subscribers", None, headers, params)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"{P}/subscribers/{subscriber_id}", None, headers)

    def list_subscribers(self, headers, params=None):
        return self._request("GET", f"{P}/subscribers", None, headers, params)

    def migrate_subscriber(self, subscriber_id, headers):
        return self._request("POST", f"{P}/subscribers/{subscriber_id}/migrate-digital", {}, headers)

    def accept_retention_offer(self, subscriber_id, headers):
        return self._request("POST", f"{P}/subscribers/{subscriber_id}/accept-retention-offer", {}, headers)

    def cancel_subscriber(self, subscriber_id, headers):
        return self._request("POST", f"{P}/subscribers/{subscriber_id}/cancel", {}, headers)

    def refund_subscriber(self, subscriber_id, headers):
        return self._request("POST", f"{P}/subscribers/{subscriber_id}/refund", {}, headers)

    def list_subscriber_retention_actions(self, subscriber_id, headers, params=None):
        return self._request("GET", f"{P}/subscribers/{subscriber_id}/retention-actions", None, headers, params)

    # ─── RetentionAction ─────────────────────────────────────────────
    def offer_retention_action(self, subscriber_id, payload, headers):
        return self._request("POST", f"{P}/subscribers/{subscriber_id}/retention-actions", payload, headers)

    def get_retention_action(self, action_id, headers):
        return self._request("GET", f"{P}/retention-actions/{action_id}", None, headers)

    def accept_retention_action(self, action_id, headers):
        return self._request("POST", f"{P}/retention-actions/{action_id}/accept", {}, headers)

    # ─── NewsroomPosition ────────────────────────────────────────────
    def create_newsroom_position(self, region_id, payload, headers):
        return self._request("POST", f"{P}/regions/{region_id}/newsroom-positions", payload, headers)

    def list_region_positions(self, region_id, headers, params=None):
        return self._request("GET", f"{P}/regions/{region_id}/newsroom-positions", None, headers, params)

    def get_newsroom_position(self, position_id, headers):
        return self._request("GET", f"{P}/newsroom-positions/{position_id}", None, headers)

    # ─── NewsroomChange ──────────────────────────────────────────────
    def create_newsroom_change(self, payload, headers):
        return self._request("POST", f"{P}/newsroom-changes", payload, headers)

    def list_newsroom_changes(self, headers, params=None):
        return self._request("GET", f"{P}/newsroom-changes", None, headers, params)

    def get_newsroom_change(self, change_id, headers):
        return self._request("GET", f"{P}/newsroom-changes/{change_id}", None, headers)

    def list_position_changes(self, position_id, headers, params=None):
        return self._request("GET", f"{P}/newsroom-positions/{position_id}/newsroom-changes", None, headers, params)

    def approve_newsroom_change(self, change_id, headers):
        return self._request("POST", f"{P}/newsroom-changes/{change_id}/approve", {}, headers)

    def apply_newsroom_change(self, change_id, headers):
        return self._request("POST", f"{P}/newsroom-changes/{change_id}/apply", {}, headers)

    def reject_newsroom_change(self, change_id, headers):
        return self._request("POST", f"{P}/newsroom-changes/{change_id}/reject", {}, headers)

    def reopen_newsroom_change(self, change_id, headers):
        return self._request("POST", f"{P}/newsroom-changes/{change_id}/reopen", {}, headers)

    # ─── TitleClosure ────────────────────────────────────────────────
    def create_title_closure(self, hub_id, payload, headers):
        return self._request("POST", f"{P}/region-hubs/{hub_id}/title-closures", payload, headers)

    def list_title_closures(self, hub_id, headers, params=None):
        return self._request("GET", f"{P}/region-hubs/{hub_id}/title-closures", None, headers, params)

    def get_title_closure(self, title_id, headers):
        return self._request("GET", f"{P}/title-closures/{title_id}", None, headers)

    def publish_title_notice(self, title_id, headers):
        return self._request("POST", f"{P}/title-closures/{title_id}/publish-notice", {}, headers)

    def suspend_title_closure(self, title_id, headers):
        return self._request("POST", f"{P}/title-closures/{title_id}/suspend", {}, headers)

    def resume_title_closure(self, title_id, headers):
        return self._request("POST", f"{P}/title-closures/{title_id}/resume", {}, headers)

    def merge_title_closure(self, title_id, payload, headers):
        return self._request("POST", f"{P}/title-closures/{title_id}/merge", payload, headers)

    def archive_title_closure(self, title_id, headers):
        return self._request("POST", f"{P}/title-closures/{title_id}/archive", {}, headers)


api_client = ApiClient()