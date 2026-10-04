"""API client: one method per PRD section 4 endpoint."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -- Logical clock ---------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- Restaurants ------------------------------------------------------
    def create_restaurant(self, payload, headers):
        return self._request("POST", "/api/restaurants", payload, headers)

    def list_restaurants(self, headers, params=None):
        return self._request("GET", "/api/restaurants", headers=headers, params=params)

    def get_restaurant(self, restaurant_id, headers):
        return self._request("GET", f"/api/restaurants/{restaurant_id}", headers=headers)

    def update_waitlist(self, restaurant_id, payload, headers):
        return self._request(
            "POST", f"/api/restaurants/{restaurant_id}/update-waitlist",
            payload, headers)

    # -- Menu revisions ---------------------------------------------------
    def create_menu_revision(self, payload, headers):
        return self._request("POST", "/api/menu-revisions", payload, headers)

    def list_menu_revisions(self, headers, params=None):
        return self._request("GET", "/api/menu-revisions", headers=headers, params=params)

    def get_menu_revision(self, revision_id, headers):
        return self._request(
            "GET", f"/api/menu-revisions/{revision_id}", headers=headers)

    def submit_review(self, revision_id, headers):
        return self._request(
            "POST", f"/api/menu-revisions/{revision_id}/submit-review", {}, headers)

    def request_changes(self, revision_id, headers):
        return self._request(
            "POST", f"/api/menu-revisions/{revision_id}/request-changes", {}, headers)

    def approve_revision(self, revision_id, headers):
        return self._request(
            "POST", f"/api/menu-revisions/{revision_id}/approve", {}, headers)

    def publish_revision(self, revision_id, headers):
        return self._request(
            "POST", f"/api/menu-revisions/{revision_id}/publish", {}, headers)

    # -- Recipes ----------------------------------------------------------
    def create_recipe(self, payload, headers):
        return self._request("POST", "/api/recipes", payload, headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/api/recipes", headers=headers, params=params)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/api/recipes/{recipe_id}", headers=headers)

    # -- Prep items -------------------------------------------------------
    def create_prep_item(self, payload, headers):
        return self._request("POST", "/api/prep-items", payload, headers)

    def list_prep_items(self, headers, params=None):
        return self._request("GET", "/api/prep-items", headers=headers, params=params)

    def get_prep_item(self, prep_item_id, headers):
        return self._request("GET", f"/api/prep-items/{prep_item_id}", headers=headers)

    def retire_prep_item(self, prep_item_id, headers):
        return self._request(
            "POST", f"/api/prep-items/{prep_item_id}/retire", {}, headers)

    # -- Stations ---------------------------------------------------------
    def create_station(self, payload, headers):
        return self._request("POST", "/api/stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/api/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/api/stations/{station_id}", headers=headers)

    def get_throughput_summary(self, station_id, headers):
        return self._request(
            "GET", f"/api/stations/{station_id}/throughput-summary", headers=headers)

    # -- Station pars -----------------------------------------------------
    def create_station_par(self, payload, headers):
        return self._request("POST", "/api/station-pars", payload, headers)

    def list_station_pars(self, headers, params=None):
        return self._request("GET", "/api/station-pars", headers=headers, params=params)

    def get_station_par(self, par_id, headers):
        return self._request("GET", f"/api/station-pars/{par_id}", headers=headers)

    def propose_adjustment(self, par_id, payload, headers):
        return self._request(
            "POST", f"/api/station-pars/{par_id}/propose-adjustment", payload, headers)

    def approve_adjustment(self, par_id, headers):
        return self._request(
            "POST", f"/api/station-pars/{par_id}/approve-adjustment", {}, headers)

    def reject_adjustment(self, par_id, headers):
        return self._request(
            "POST", f"/api/station-pars/{par_id}/reject-adjustment", {}, headers)

    # -- Cooks ------------------------------------------------------------
    def create_cook(self, payload, headers):
        return self._request("POST", "/api/cooks", payload, headers)

    def list_cooks(self, headers, params=None):
        return self._request("GET", "/api/cooks", headers=headers, params=params)

    def get_cook(self, cook_id, headers):
        return self._request("GET", f"/api/cooks/{cook_id}", headers=headers)

    def complete_retraining(self, cook_id, payload, headers):
        return self._request(
            "POST", f"/api/cooks/{cook_id}/complete-retraining", payload, headers)

    # -- Demand forecasts -------------------------------------------------
    def create_demand_forecast(self, payload, headers):
        return self._request("POST", "/api/demand-forecasts", payload, headers)

    def list_demand_forecasts(self, headers, params=None):
        return self._request("GET", "/api/demand-forecasts", headers=headers, params=params)

    def get_demand_forecast(self, forecast_id, headers):
        return self._request(
            "GET", f"/api/demand-forecasts/{forecast_id}", headers=headers)

    def submit_forecast(self, forecast_id, headers):
        return self._request(
            "POST", f"/api/demand-forecasts/{forecast_id}/submit", {}, headers)

    def finalize_forecast(self, forecast_id, headers):
        return self._request(
            "POST", f"/api/demand-forecasts/{forecast_id}/finalize", {}, headers)

    def amend_forecast(self, forecast_id, headers):
        return self._request(
            "POST", f"/api/demand-forecasts/{forecast_id}/amend", {}, headers)

    # -- Prep lists -------------------------------------------------------
    def create_prep_list(self, payload, headers):
        return self._request("POST", "/api/prep-lists", payload, headers)

    def list_prep_lists(self, headers, params=None):
        return self._request("GET", "/api/prep-lists", headers=headers, params=params)

    def get_prep_list(self, prep_list_id, headers):
        return self._request("GET", f"/api/prep-lists/{prep_list_id}", headers=headers)

    def generate_prep_list(self, prep_list_id, payload, headers):
        return self._request(
            "POST", f"/api/prep-lists/{prep_list_id}/generate", payload, headers)

    def regenerate_prep_list(self, prep_list_id, payload, headers):
        return self._request(
            "POST", f"/api/prep-lists/{prep_list_id}/regenerate", payload, headers)

    def lock_prep_list(self, prep_list_id, headers):
        return self._request(
            "POST", f"/api/prep-lists/{prep_list_id}/lock", {}, headers)

    # -- Prep batches -----------------------------------------------------
    def create_prep_batch(self, payload, headers):
        return self._request("POST", "/api/prep-batches", payload, headers)

    def list_prep_batches(self, headers, params=None):
        return self._request("GET", "/api/prep-batches", headers=headers, params=params)

    def get_prep_batch(self, batch_id, headers):
        return self._request("GET", f"/api/prep-batches/{batch_id}", headers=headers)

    def mark_prepped(self, batch_id, headers):
        return self._request(
            "POST", f"/api/prep-batches/{batch_id}/mark-prepped", {}, headers)

    def record_consumption(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/prep-batches/{batch_id}/record-consumption", payload, headers)

    def expire_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/api/prep-batches/{batch_id}/expire", {}, headers)

    # -- Shift assignments ------------------------------------------------
    def create_shift_assignment(self, payload, headers):
        return self._request("POST", "/api/shift-assignments", payload, headers)

    def list_shift_assignments(self, headers, params=None):
        return self._request(
            "GET", "/api/shift-assignments", headers=headers, params=params)

    def get_shift_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/api/shift-assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/api/shift-assignments/{assignment_id}/confirm", {}, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/api/shift-assignments/{assignment_id}/complete", {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/api/shift-assignments/{assignment_id}/cancel", {}, headers)

    def mark_no_show(self, assignment_id, headers):
        return self._request(
            "POST", f"/api/shift-assignments/{assignment_id}/mark-no-show", {}, headers)

    # -- Bakery orders ----------------------------------------------------
    def create_bakery_order(self, payload, headers):
        return self._request("POST", "/api/bakery-orders", payload, headers)

    def list_bakery_orders(self, headers, params=None):
        return self._request("GET", "/api/bakery-orders", headers=headers, params=params)

    def get_bakery_order(self, order_id, headers):
        return self._request("GET", f"/api/bakery-orders/{order_id}", headers=headers)

    def submit_bakery_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/bakery-orders/{order_id}/submit", {}, headers)

    def confirm_bakery_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/bakery-orders/{order_id}/confirm", {}, headers)

    def receive_bakery_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/bakery-orders/{order_id}/receive", payload, headers)

    def reconcile_yield(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/bakery-orders/{order_id}/reconcile-yield", payload, headers)

    def cancel_bakery_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/bakery-orders/{order_id}/cancel", {}, headers)

    # -- Waste entries ----------------------------------------------------
    def create_waste_entry(self, payload, headers):
        return self._request("POST", "/api/waste-entries", payload, headers)

    def list_waste_entries(self, headers, params=None):
        return self._request("GET", "/api/waste-entries", headers=headers, params=params)

    def get_waste_entry(self, waste_entry_id, headers):
        return self._request(
            "GET", f"/api/waste-entries/{waste_entry_id}", headers=headers)

    # -- Service tickets --------------------------------------------------
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/api/service-tickets", payload, headers)

    def list_service_tickets(self, headers, params=None):
        return self._request(
            "GET", "/api/service-tickets", headers=headers, params=params)

    def get_service_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/api/service-tickets/{ticket_id}", headers=headers)

    def fire_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/api/service-tickets/{ticket_id}/fire", {}, headers)

    def mark_ticket_ready(self, ticket_id, headers):
        return self._request(
            "POST", f"/api/service-tickets/{ticket_id}/mark-ready", {}, headers)

    def serve_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/api/service-tickets/{ticket_id}/serve", {}, headers)

    def void_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/api/service-tickets/{ticket_id}/void", {}, headers)

    def recall_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/api/service-tickets/{ticket_id}/recall", {}, headers)

    def clear_allergen_review(self, ticket_id, headers):
        return self._request(
            "POST", f"/api/service-tickets/{ticket_id}/clear-allergen-review",
            {}, headers)


api_client = ApiClient()
