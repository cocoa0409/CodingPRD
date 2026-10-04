"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- tours ----------------------------------------------------------
    def create_tour(self, payload, headers):
        return self._request("POST", "/tours", payload, headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/tours", headers=headers, params=params)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}", headers=headers)

    def open_routing(self, tour_id, headers, payload=None):
        return self._request(
            "POST", f"/tours/{tour_id}/open-routing", payload or {}, headers
        )

    def close_tour(self, tour_id, headers, payload=None):
        return self._request("POST", f"/tours/{tour_id}/close", payload or {}, headers)

    # ---- venues ---------------------------------------------------------
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def deactivate_venue(self, venue_id, headers, payload=None):
        return self._request(
            "POST", f"/venues/{venue_id}/deactivate", payload or {}, headers
        )

    # ---- rigging points -------------------------------------------------
    def create_rigging_point(self, venue_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/rigging-points", payload, headers
        )

    def list_rigging_points(self, venue_id, headers, params=None):
        return self._request(
            "GET", f"/venues/{venue_id}/rigging-points", headers=headers, params=params
        )

    def get_rigging_point(self, venue_id, point_id, headers):
        return self._request(
            "GET", f"/venues/{venue_id}/rigging-points/{point_id}", headers=headers
        )

    def mark_point_out_of_service(self, venue_id, point_id, headers, payload=None):
        return self._request(
            "POST",
            f"/venues/{venue_id}/rigging-points/{point_id}/mark-out-of-service",
            payload or {},
            headers,
        )

    # ---- date avails ----------------------------------------------------
    def create_date_avail(self, venue_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/date-avails", payload, headers
        )

    def list_date_avails(self, venue_id, headers, params=None):
        return self._request(
            "GET", f"/venues/{venue_id}/date-avails", headers=headers, params=params
        )

    def get_date_avail(self, venue_id, avail_id, headers):
        return self._request(
            "GET", f"/venues/{venue_id}/date-avails/{avail_id}", headers=headers
        )

    def release_date_avail(self, venue_id, avail_id, headers, payload=None):
        return self._request(
            "POST",
            f"/venues/{venue_id}/date-avails/{avail_id}/release",
            payload or {},
            headers,
        )

    # ---- engagements ----------------------------------------------------
    def create_engagement(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/engagements", payload, headers)

    def list_engagements(self, tour_id, headers, params=None):
        return self._request(
            "GET", f"/tours/{tour_id}/engagements", headers=headers, params=params
        )

    def get_engagement(self, tour_id, engagement_id, headers):
        return self._request(
            "GET", f"/tours/{tour_id}/engagements/{engagement_id}", headers=headers
        )

    def confirm_engagement(self, tour_id, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/confirm",
            payload or {},
            headers,
        )

    def cancel_engagement(self, tour_id, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/cancel",
            payload or {},
            headers,
        )

    def mark_show_ready(self, tour_id, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/mark-show-ready",
            payload or {},
            headers,
        )

    # ---- rigging plans --------------------------------------------------
    def create_rigging_plan(self, tour_id, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/rigging-plans",
            payload or {},
            headers,
        )

    def list_rigging_plans(self, tour_id, engagement_id, headers, params=None):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/rigging-plans",
            headers=headers,
            params=params,
        )

    def get_rigging_plan(self, tour_id, engagement_id, plan_id, headers):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/rigging-plans/{plan_id}",
            headers=headers,
        )

    def submit_rigging_plan(self, tour_id, engagement_id, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/rigging-plans/{plan_id}/submit",
            payload or {},
            headers,
        )

    def approve_rigging_plan(self, tour_id, engagement_id, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/rigging-plans/{plan_id}/approve",
            payload or {},
            headers,
        )

    def reject_rigging_plan(self, tour_id, engagement_id, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/rigging-plans/{plan_id}/reject",
            payload or {},
            headers,
        )

    def revise_rigging_plan(self, tour_id, engagement_id, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/rigging-plans/{plan_id}/revise",
            payload or {},
            headers,
        )

    # ---- rigging allocations --------------------------------------------
    def create_rigging_allocation(self, tour_id, engagement_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/rigging-plans/{plan_id}/allocations",
            payload,
            headers,
        )

    def list_rigging_allocations(self, tour_id, engagement_id, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/rigging-plans/{plan_id}/allocations",
            headers=headers,
            params=params,
        )

    # ---- labor calls ----------------------------------------------------
    def create_labor_call(self, tour_id, engagement_id, payload, headers):
        return self._request(
            "POST", f"/tours/{tour_id}/engagements/{engagement_id}/labor-calls", payload, headers
        )

    def list_labor_calls(self, tour_id, engagement_id, headers, params=None):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/labor-calls",
            headers=headers,
            params=params,
        )

    def get_labor_call(self, tour_id, engagement_id, call_id, headers):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/labor-calls/{call_id}",
            headers=headers,
        )

    def post_labor_call(self, tour_id, engagement_id, call_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/labor-calls/{call_id}/post",
            payload or {},
            headers,
        )

    def fill_labor_call(self, tour_id, engagement_id, call_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/labor-calls/{call_id}/fill",
            payload or {},
            headers,
        )

    def settle_labor_call(self, tour_id, engagement_id, call_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/labor-calls/{call_id}/settle",
            payload,
            headers,
        )

    def cancel_labor_call(self, tour_id, engagement_id, call_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/labor-calls/{call_id}/cancel",
            payload or {},
            headers,
        )

    # ---- truck moves ----------------------------------------------------
    def create_truck_move(self, tour_id, engagement_id, payload, headers):
        return self._request(
            "POST", f"/tours/{tour_id}/engagements/{engagement_id}/truck-moves", payload, headers
        )

    def list_truck_moves(self, tour_id, engagement_id, headers, params=None):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/truck-moves",
            headers=headers,
            params=params,
        )

    def get_truck_move(self, tour_id, engagement_id, move_id, headers):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/truck-moves/{move_id}",
            headers=headers,
        )

    def dispatch_truck_move(self, tour_id, engagement_id, move_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/truck-moves/{move_id}/dispatch",
            payload or {},
            headers,
        )

    def mark_truck_arrived(self, tour_id, engagement_id, move_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/truck-moves/{move_id}/mark-arrived",
            payload or {},
            headers,
        )

    def cancel_truck_move(self, tour_id, engagement_id, move_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/truck-moves/{move_id}/cancel",
            payload or {},
            headers,
        )

    # ---- ticket scales / sales ------------------------------------------
    def create_ticket_scale(self, tour_id, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/ticket-scales",
            payload,
            headers,
        )

    def list_ticket_scales(self, tour_id, engagement_id, headers, params=None):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/ticket-scales",
            headers=headers,
            params=params,
        )

    def get_ticket_scale(self, tour_id, engagement_id, scale_id, headers):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/ticket-scales/{scale_id}",
            headers=headers,
        )

    def create_ticket_sale(self, tour_id, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/ticket-sales",
            payload,
            headers,
        )

    # ---- settlement -----------------------------------------------------
    def get_settlement(self, tour_id, engagement_id, headers):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/settlement",
            headers=headers,
        )

    def reconcile_settlement(self, tour_id, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/settlement/reconcile",
            payload or {},
            headers,
        )

    def mark_settlement_paid(self, tour_id, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/settlement/mark-paid",
            payload,
            headers,
        )

    def dispute_settlement(self, tour_id, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/settlement/dispute",
            payload or {},
            headers,
        )

    def resolve_dispute(self, tour_id, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/settlement/resolve-dispute",
            payload or {},
            headers,
        )

    # ---- license agreements ---------------------------------------------
    def create_license_agreement(self, tour_id, payload, headers):
        return self._request(
            "POST", f"/tours/{tour_id}/license-agreements", payload, headers
        )

    def list_license_agreements(self, tour_id, headers, params=None):
        return self._request(
            "GET", f"/tours/{tour_id}/license-agreements", headers=headers, params=params
        )

    def get_license_agreement(self, tour_id, lic_id, headers):
        return self._request(
            "GET", f"/tours/{tour_id}/license-agreements/{lic_id}", headers=headers
        )

    def activate_license_agreement(self, tour_id, lic_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/license-agreements/{lic_id}/activate",
            payload or {},
            headers,
        )

    def terminate_license_agreement(self, tour_id, lic_id, headers, payload=None):
        return self._request(
            "POST",
            f"/tours/{tour_id}/license-agreements/{lic_id}/terminate",
            payload or {},
            headers,
        )

    # ---- safety inspections ---------------------------------------------
    def create_safety_inspection(self, tour_id, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/safety-inspections",
            payload,
            headers,
        )

    def list_safety_inspections(self, tour_id, engagement_id, headers, params=None):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/safety-inspections",
            headers=headers,
            params=params,
        )

    def get_safety_inspection(self, tour_id, engagement_id, insp_id, headers):
        return self._request(
            "GET",
            f"/tours/{tour_id}/engagements/{engagement_id}/safety-inspections/{insp_id}",
            headers=headers,
        )

    def pass_safety_inspection(self, tour_id, engagement_id, insp_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/safety-inspections/{insp_id}/pass",
            payload,
            headers,
        )

    def fail_safety_inspection(self, tour_id, engagement_id, insp_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/safety-inspections/{insp_id}/fail",
            payload,
            headers,
        )

    def waive_safety_inspection(self, tour_id, engagement_id, insp_id, payload, headers):
        return self._request(
            "POST",
            f"/tours/{tour_id}/engagements/{engagement_id}/safety-inspections/{insp_id}/waive",
            payload,
            headers,
        )

    # ---- flat read aliases ----------------------------------------------
    def get_engagement_flat(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def list_engagements_flat(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def get_date_avail_flat(self, avail_id, headers):
        return self._request("GET", f"/date-avails/{avail_id}", headers=headers)

    def list_date_avails_flat(self, headers, params=None):
        return self._request("GET", "/date-avails", headers=headers, params=params)

    def get_rigging_point_flat(self, point_id, headers):
        return self._request("GET", f"/rigging-points/{point_id}", headers=headers)

    def list_rigging_points_flat(self, headers, params=None):
        return self._request("GET", "/rigging-points", headers=headers, params=params)

    def get_rigging_plan_flat(self, plan_id, headers):
        return self._request("GET", f"/rigging-plans/{plan_id}", headers=headers)

    def list_rigging_plans_flat(self, headers, params=None):
        return self._request("GET", "/rigging-plans", headers=headers, params=params)

    def get_rigging_allocation_flat(self, alloc_id, headers):
        return self._request("GET", f"/rigging-allocations/{alloc_id}", headers=headers)

    def list_rigging_allocations_flat(self, headers, params=None):
        return self._request("GET", "/rigging-allocations", headers=headers, params=params)

    def get_labor_call_flat(self, call_id, headers):
        return self._request("GET", f"/labor-calls/{call_id}", headers=headers)

    def list_labor_calls_flat(self, headers, params=None):
        return self._request("GET", "/labor-calls", headers=headers, params=params)

    def get_truck_move_flat(self, move_id, headers):
        return self._request("GET", f"/truck-moves/{move_id}", headers=headers)

    def list_truck_moves_flat(self, headers, params=None):
        return self._request("GET", "/truck-moves", headers=headers, params=params)

    def get_ticket_scale_flat(self, scale_id, headers):
        return self._request("GET", f"/ticket-scales/{scale_id}", headers=headers)

    def list_ticket_scales_flat(self, headers, params=None):
        return self._request("GET", "/ticket-scales", headers=headers, params=params)

    def get_settlement_flat(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements_flat(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_license_agreement_flat(self, lic_id, headers):
        return self._request("GET", f"/license-agreements/{lic_id}", headers=headers)

    def list_license_agreements_flat(self, headers, params=None):
        return self._request("GET", "/license-agreements", headers=headers, params=params)

    def get_safety_inspection_flat(self, insp_id, headers):
        return self._request("GET", f"/safety-inspections/{insp_id}", headers=headers)

    def list_safety_inspections_flat(self, headers, params=None):
        return self._request("GET", "/safety-inspections", headers=headers, params=params)


api_client = ApiClient()
