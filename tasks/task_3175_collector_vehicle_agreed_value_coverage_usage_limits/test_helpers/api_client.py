"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def update_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/members/{member_id}", payload, headers)

    def list_member_event_registrations(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/event-registrations", headers=headers, params=params
        )

    # --- vehicles ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def evaluate_eligibility(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/evaluate-eligibility", {}, headers)

    # --- photos ---
    def submit_photo(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/photos", payload, headers)

    def list_photos(self, vehicle_id, headers, params=None):
        return self._request("GET", f"/vehicles/{vehicle_id}/photos", headers=headers, params=params)

    def review_photo(self, vehicle_id, photo_id, payload, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/photos/{photo_id}/review", payload, headers
        )

    # --- valuation guides ---
    def create_valuation_guide(self, payload, headers):
        return self._request("POST", "/valuation-guides", payload, headers)

    def get_valuation_guide(self, guide_id, headers):
        return self._request("GET", f"/valuation-guides/{guide_id}", headers=headers)

    def add_guide_entry(self, guide_id, payload, headers):
        return self._request("POST", f"/valuation-guides/{guide_id}/entries", payload, headers)

    def list_guide_entries(self, guide_id, headers, params=None):
        return self._request(
            "GET", f"/valuation-guides/{guide_id}/entries", headers=headers, params=params
        )

    def publish_guide(self, guide_id, headers):
        return self._request("POST", f"/valuation-guides/{guide_id}/publish", {}, headers)

    # --- appraisals ---
    def submit_appraisal(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/appraisals", payload, headers)

    def list_appraisals(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/appraisals", headers=headers, params=params
        )

    def certify_appraisal(self, appraisal_id, payload, headers):
        return self._request("POST", f"/appraisals/{appraisal_id}/certify", payload, headers)

    # --- auction results ---
    def create_auction_result(self, payload, headers):
        return self._request("POST", "/auction-results", payload, headers)

    def list_auction_results(self, headers, params=None):
        return self._request("GET", "/auction-results", headers=headers, params=params)

    # --- valuations ---
    def create_valuation(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/valuations", payload, headers)

    def list_vehicle_valuations(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/valuations", headers=headers, params=params
        )

    def get_valuation(self, valuation_id, headers):
        return self._request("GET", f"/valuations/{valuation_id}", headers=headers)

    def list_valuations(self, headers, params=None):
        return self._request("GET", "/valuations", headers=headers, params=params)

    def propose_valuation(self, valuation_id, headers):
        return self._request("POST", f"/valuations/{valuation_id}/propose", {}, headers)

    def revise_valuation(self, valuation_id, payload, headers):
        return self._request("POST", f"/valuations/{valuation_id}/revise", payload, headers)

    def approve_valuation(self, valuation_id, payload, headers):
        return self._request("POST", f"/valuations/{valuation_id}/approve", payload, headers)

    def reject_valuation(self, valuation_id, headers):
        return self._request("POST", f"/valuations/{valuation_id}/reject", {}, headers)

    # --- policies ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def repin_policy_valuation(self, policy_id, payload, headers):
        return self._request("PATCH", f"/policies/{policy_id}", payload, headers)

    def activate_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/activate", {}, headers)

    def begin_review(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/begin-review", {}, headers)

    def resolve_review(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/resolve-review", {}, headers)

    def suspend_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/suspend", {}, headers)

    def resume_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/resume", {}, headers)

    def lapse_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/lapse", {}, headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", {}, headers)

    # --- drivers ---
    def add_driver(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/drivers", payload, headers)

    def list_drivers(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/drivers", headers=headers, params=params)

    def remove_driver(self, policy_id, driver_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/drivers/{driver_id}/remove", {}, headers
        )

    # --- usage events ---
    def record_usage_event(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/usage-events", payload, headers)

    def list_usage_events(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/policies/{policy_id}/usage-events", headers=headers, params=params
        )

    def reverse_usage_event(self, usage_event_id, headers):
        return self._request("POST", f"/usage-events/{usage_event_id}/reverse", {}, headers)

    # --- repair shops ---
    def create_repair_shop(self, payload, headers):
        return self._request("POST", "/repair-shops", payload, headers)

    def list_repair_shops(self, headers, params=None):
        return self._request("GET", "/repair-shops", headers=headers, params=params)

    def certify_repair_shop(self, shop_id, headers):
        return self._request("POST", f"/repair-shops/{shop_id}/certify", {}, headers)

    def suspend_repair_shop(self, shop_id, headers):
        return self._request("POST", f"/repair-shops/{shop_id}/suspend", {}, headers)

    # --- claims ---
    def open_claim(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/claims", payload, headers)

    def list_policy_claims(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/claims", headers=headers, params=params)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def assign_shop(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/assign-shop", payload, headers)

    def submit_estimate(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/submit-estimate", payload, headers)

    def authorize_repair(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/authorize-repair", {}, headers)

    def declare_total_loss(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/declare-total-loss", payload, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/settle", {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/reopen", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/close", {}, headers)

    # --- restoration projects ---
    def create_restoration_project(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/restoration-projects", payload, headers
        )

    def list_vehicle_restoration_projects(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/restoration-projects", headers=headers, params=params
        )

    def list_restoration_projects(self, headers, params=None):
        return self._request("GET", "/restoration-projects", headers=headers, params=params)

    def get_restoration_project(self, project_id, headers):
        return self._request("GET", f"/restoration-projects/{project_id}", headers=headers)

    def submit_receipt(self, project_id, payload, headers):
        return self._request(
            "POST", f"/restoration-projects/{project_id}/receipts", payload, headers
        )

    def advance_stage(self, project_id, headers):
        return self._request(
            "POST", f"/restoration-projects/{project_id}/advance-stage", {}, headers
        )

    def suspend_restoration(self, project_id, headers):
        return self._request("POST", f"/restoration-projects/{project_id}/suspend", {}, headers)

    def resume_restoration(self, project_id, headers):
        return self._request("POST", f"/restoration-projects/{project_id}/resume", {}, headers)

    def complete_restoration(self, project_id, headers):
        return self._request("POST", f"/restoration-projects/{project_id}/complete", {}, headers)

    # --- club memberships ---
    def create_club_membership(self, payload, headers):
        return self._request("POST", "/club-memberships", payload, headers)

    def list_club_memberships(self, headers, params=None):
        return self._request("GET", "/club-memberships", headers=headers, params=params)

    def get_club_membership(self, membership_id, headers):
        return self._request("GET", f"/club-memberships/{membership_id}", headers=headers)

    def lapse_club_membership(self, membership_id, headers):
        return self._request("POST", f"/club-memberships/{membership_id}/lapse", {}, headers)

    def reactivate_club_membership(self, membership_id, headers):
        return self._request("POST", f"/club-memberships/{membership_id}/reactivate", {}, headers)

    # --- roadside events ---
    def dispatch_roadside_event(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/club-memberships/{membership_id}/roadside-events", payload, headers
        )

    def list_membership_roadside_events(self, membership_id, headers, params=None):
        return self._request(
            "GET",
            f"/club-memberships/{membership_id}/roadside-events",
            headers=headers,
            params=params,
        )

    def get_roadside_event(self, event_id, headers):
        return self._request("GET", f"/roadside-events/{event_id}", headers=headers)

    def list_roadside_events(self, headers, params=None):
        return self._request("GET", "/roadside-events", headers=headers, params=params)

    def complete_roadside_event(self, event_id, headers):
        return self._request("POST", f"/roadside-events/{event_id}/complete", {}, headers)

    def cancel_roadside_event(self, event_id, headers):
        return self._request("POST", f"/roadside-events/{event_id}/cancel", {}, headers)

    # --- club events & registrations ---
    def create_club_event(self, payload, headers):
        return self._request("POST", "/club-events", payload, headers)

    def get_club_event(self, event_id, headers):
        return self._request("GET", f"/club-events/{event_id}", headers=headers)

    def cancel_club_event(self, event_id, headers):
        return self._request("POST", f"/club-events/{event_id}/cancel", {}, headers)

    def register_for_event(self, event_id, payload, headers):
        return self._request("POST", f"/club-events/{event_id}/register", payload, headers)

    def list_event_registrations(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/club-events/{event_id}/registrations", headers=headers, params=params
        )

    def cancel_registration(self, event_id, registration_id, headers):
        return self._request(
            "POST",
            f"/club-events/{event_id}/registrations/{registration_id}/cancel",
            {},
            headers,
        )


api_client = ApiClient()
