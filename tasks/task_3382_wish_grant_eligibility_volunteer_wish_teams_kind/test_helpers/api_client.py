"""API client: one method per endpoint defined in the PRD (mounted at /wish-grant)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/wish-grant"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving)
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        """POST /wish-grant/_clock/set_current_utc — payload {to_iso8601}."""
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Chapters
    # ------------------------------------------------------------------
    def create_chapter(self, payload, headers):
        return self._request("POST", f"{PREFIX}/chapters", payload, headers)

    def get_chapter(self, chapter_id, headers):
        return self._request("GET", f"{PREFIX}/chapters/{chapter_id}", headers=headers)

    # ------------------------------------------------------------------
    # Volunteers
    # ------------------------------------------------------------------
    def create_volunteer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"{PREFIX}/volunteers/{volunteer_id}", headers=headers)

    def transition_volunteer(self, volunteer_id, payload, headers):
        """POST /volunteers/{id}/transition — payload {target_state}."""
        return self._request("POST", f"{PREFIX}/volunteers/{volunteer_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Referrals
    # ------------------------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def certify_referral(self, referral_id, payload, headers):
        """POST /referrals/{id}/certify — payload {qualifying_condition, certification_note?}."""
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/certify",
                             payload, headers)

    def determine_referral(self, referral_id, payload, headers):
        """POST /referrals/{id}/determine — payload {decision, denial_reason?}."""
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/determine",
                             payload, headers)

    # ------------------------------------------------------------------
    # Children
    # ------------------------------------------------------------------
    def list_children(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/children", headers=headers, params=params)

    def get_child(self, child_id, headers):
        return self._request("GET", f"{PREFIX}/children/{child_id}", headers=headers)

    def patch_child(self, child_id, payload, headers):
        """PATCH /children/{id} — payload {treatment_windows: [...]} (wholesale replace)."""
        return self._request("PATCH", f"{PREFIX}/children/{child_id}", payload, headers)

    # ------------------------------------------------------------------
    # Wish teams
    # ------------------------------------------------------------------
    def create_wish_team(self, payload, headers):
        """POST /wish-teams — payload {wish_id, lead_volunteer_id,
        second_volunteer_id, expected_wish_version} (OCC-guarded)."""
        return self._request("POST", f"{PREFIX}/wish-teams", payload, headers)

    def list_wish_teams(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/wish-teams", headers=headers, params=params)

    def get_wish_team(self, team_id, headers):
        return self._request("GET", f"{PREFIX}/wish-teams/{team_id}", headers=headers)

    # ------------------------------------------------------------------
    # Wish visits
    # ------------------------------------------------------------------
    def create_wish_visit(self, payload, headers):
        """POST /wish-visits — payload {wish_team_id, scheduled_start,
        scheduled_end, visit_method}. Acting volunteer must be a team member."""
        return self._request("POST", f"{PREFIX}/wish-visits", payload, headers)

    def list_team_visits(self, team_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/wish-teams/{team_id}/visits",
                             headers=headers, params=params)

    def conclude_wish_visit(self, visit_id, payload, headers):
        """POST /wish-visits/{id}/conclude — payload {outcome, captured_true_wish?,
        captured_wish_type?}."""
        return self._request("POST", f"{PREFIX}/wish-visits/{visit_id}/conclude",
                             payload, headers)

    # ------------------------------------------------------------------
    # Wishes
    # ------------------------------------------------------------------
    def list_wishes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/wishes", headers=headers, params=params)

    def get_wish(self, wish_id, headers):
        return self._request("GET", f"{PREFIX}/wishes/{wish_id}", headers=headers)

    # ------------------------------------------------------------------
    # Donation offers
    # ------------------------------------------------------------------
    def create_donation_offer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/donation-offers", payload, headers)

    def get_donation_offer(self, offer_id, headers):
        return self._request("GET", f"{PREFIX}/donation-offers/{offer_id}", headers=headers)

    def list_offer_line_items(self, offer_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/donation-offers/{offer_id}/line-items",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Fulfillment plans
    # ------------------------------------------------------------------
    def create_fulfillment_plan(self, payload, headers):
        """POST /fulfillment-plans — payload {wish_id, cash_cost_cents,
        expected_wish_version, notes?} (OCC-guarded)."""
        return self._request("POST", f"{PREFIX}/fulfillment-plans", payload, headers)

    def list_wish_plans(self, wish_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/wishes/{wish_id}/fulfillment-plans",
                             headers=headers, params=params)

    def get_fulfillment_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/fulfillment-plans/{plan_id}",
                             headers=headers)

    def create_plan_line_item(self, plan_id, payload, headers):
        """POST /fulfillment-plans/{id}/line-items — payload {donation_offer_id, quantity}."""
        return self._request("POST", f"{PREFIX}/fulfillment-plans/{plan_id}/line-items",
                             payload, headers)

    def list_plan_line_items(self, plan_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/fulfillment-plans/{plan_id}/line-items",
                             headers=headers, params=params)

    def submit_plan(self, plan_id, headers):
        """POST /fulfillment-plans/{id}/submit — no body fields."""
        return self._request("POST", f"{PREFIX}/fulfillment-plans/{plan_id}/submit",
                             {}, headers)

    def approve_plan(self, plan_id, headers):
        """POST /fulfillment-plans/{id}/approve — no body fields."""
        return self._request("POST", f"{PREFIX}/fulfillment-plans/{plan_id}/approve",
                             {}, headers)

    def abort_plan(self, plan_id, payload, headers):
        """POST /fulfillment-plans/{id}/abort — payload {reason?}."""
        return self._request("POST", f"{PREFIX}/fulfillment-plans/{plan_id}/abort",
                             payload, headers)

    # ------------------------------------------------------------------
    # Medical clearances
    # ------------------------------------------------------------------
    def create_medical_clearance(self, payload, headers):
        """POST /medical-clearances — payload {wish_id} (TRAVEL wishes only)."""
        return self._request("POST", f"{PREFIX}/medical-clearances", payload, headers)

    def list_wish_clearances(self, wish_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/wishes/{wish_id}/medical-clearances",
                             headers=headers, params=params)

    def decide_clearance(self, clearance_id, payload, headers):
        """POST /medical-clearances/{id}/decide — payload {decision, accommodations?,
        valid_until?, decision_note?}."""
        return self._request("POST",
                             f"{PREFIX}/medical-clearances/{clearance_id}/decide",
                             payload, headers)

    # ------------------------------------------------------------------
    # Wish events
    # ------------------------------------------------------------------
    def create_wish_event(self, payload, headers):
        """POST /wish-events — payload {wish_id, event_start_date, event_end_date}."""
        return self._request("POST", f"{PREFIX}/wish-events", payload, headers)

    def list_wish_events(self, wish_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/wishes/{wish_id}/wish-events",
                             headers=headers, params=params)

    def complete_wish_event(self, event_id, headers):
        """POST /wish-events/{id}/complete — no body fields."""
        return self._request("POST", f"{PREFIX}/wish-events/{event_id}/complete",
                             {}, headers)


api_client = ApiClient()
