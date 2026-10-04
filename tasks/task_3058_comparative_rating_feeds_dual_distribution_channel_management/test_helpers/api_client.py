"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- products -------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def activate_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/activate", {}, headers)

    def withdraw_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/withdraw", {}, headers)

    def list_product_feed_publications(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/products/{product_id}/rate-feed-publications",
            headers=headers, params=params,
        )

    # ---- raters ---------------------------------------------------------
    def create_rater(self, payload, headers):
        return self._request("POST", "/raters", payload, headers)

    def list_raters(self, headers, params=None):
        return self._request("GET", "/raters", headers=headers, params=params)

    def get_rater(self, rater_id, headers):
        return self._request("GET", f"/raters/{rater_id}", headers=headers)

    # ---- rate feed publications -----------------------------------------
    def create_feed_publication(self, rater_id, payload, headers):
        return self._request(
            "POST", f"/raters/{rater_id}/rate-feed-publications", payload, headers
        )

    def list_rater_feed_publications(self, rater_id, headers, params=None):
        return self._request(
            "GET", f"/raters/{rater_id}/rate-feed-publications",
            headers=headers, params=params,
        )

    def get_feed_publication(self, publication_id, headers):
        return self._request(
            "GET", f"/rate-feed-publications/{publication_id}", headers=headers
        )

    def publish_feed_publication(self, publication_id, headers):
        return self._request(
            "POST", f"/rate-feed-publications/{publication_id}/publish", {}, headers
        )

    def recall_feed_publication(self, publication_id, headers):
        return self._request(
            "POST", f"/rate-feed-publications/{publication_id}/recall", {}, headers
        )

    # ---- agents ---------------------------------------------------------
    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def appoint_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/appoint", {}, headers)

    def suspend_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/suspend", {}, headers)

    def reinstate_agent(self, agent_id, headers):
        return self._request("POST", f"/agents/{agent_id}/reinstate", {}, headers)

    def terminate_agent(self, agent_id, headers, payload=None):
        return self._request(
            "POST", f"/agents/{agent_id}/terminate", payload or {}, headers
        )

    # ---- appointments ---------------------------------------------------
    def create_appointment(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/agents/{agent_id}/appointments", payload, headers
        )

    def list_agent_appointments(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/appointments", headers=headers, params=params
        )

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def terminate_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/appointments/{appointment_id}/terminate", payload or {}, headers
        )

    # ---- commission schedules -------------------------------------------
    def create_commission_schedule(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/agents/{agent_id}/commission-schedules", payload, headers
        )

    def list_agent_commission_schedules(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/commission-schedules",
            headers=headers, params=params,
        )

    def get_commission_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/commission-schedules/{schedule_id}", headers=headers
        )

    # ---- consumers ------------------------------------------------------
    def create_consumer(self, payload, headers):
        return self._request("POST", "/consumers", payload, headers)

    def list_consumers(self, headers, params=None):
        return self._request("GET", "/consumers", headers=headers, params=params)

    def get_consumer(self, consumer_id, headers):
        return self._request("GET", f"/consumers/{consumer_id}", headers=headers)

    # ---- quotes ---------------------------------------------------------
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def submit_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/submit", {}, headers)

    def re_rate_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/re-rate", {}, headers)

    def refer_quote_to_agent(self, quote_id, payload, headers):
        return self._request(
            "POST", f"/quotes/{quote_id}/refer-to-agent", payload, headers
        )

    def agent_quote(self, quote_id, headers, payload=None):
        return self._request(
            "POST", f"/quotes/{quote_id}/agent-quote", payload or {}, headers
        )

    def bind_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/bind", {}, headers)

    def withdraw_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/withdraw", {}, headers)

    # ---- policies -------------------------------------------------------
    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def cancel_policy(self, policy_id, headers, payload=None):
        return self._request(
            "POST", f"/policies/{policy_id}/cancel", payload or {}, headers
        )

    # ---- claims ---------------------------------------------------------
    def create_claim(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/claims", payload, headers
        )

    def list_policy_claims(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/policies/{policy_id}/claims", headers=headers, params=params
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/close", {}, headers)

    # ---- telematics enrollments ------------------------------------------
    def list_policy_telematics_enrollments(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/policies/{policy_id}/telematics-enrollments",
            headers=headers, params=params,
        )

    def get_telematics_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/telematics-enrollments/{enrollment_id}", headers=headers
        )

    def activate_telematics_device(self, enrollment_id, headers):
        return self._request(
            "POST", f"/telematics-enrollments/{enrollment_id}/activate-device",
            {}, headers,
        )

    def score_telematics_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/telematics-enrollments/{enrollment_id}/score", payload, headers
        )

    def opt_out_telematics_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"/telematics-enrollments/{enrollment_id}/opt-out",
            payload or {}, headers,
        )

    # ---- commission statements ------------------------------------------
    def create_commission_statement(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/agents/{agent_id}/commission-statements", payload, headers
        )

    def list_agent_commission_statements(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/commission-statements",
            headers=headers, params=params,
        )

    def get_commission_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/commission-statements/{statement_id}", headers=headers
        )

    def finalize_commission_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/commission-statements/{statement_id}/finalize", {}, headers
        )

    def pay_commission_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/commission-statements/{statement_id}/pay", {}, headers
        )

    def claw_back_commission_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/commission-statements/{statement_id}/claw-back", payload, headers
        )

    # ---- contingent bonus pools / payouts --------------------------------
    def create_bonus_pool(self, payload, headers):
        return self._request("POST", "/contingent-bonus-pools", payload, headers)

    def list_bonus_pools(self, headers, params=None):
        return self._request(
            "GET", "/contingent-bonus-pools", headers=headers, params=params
        )

    def get_bonus_pool(self, pool_id, headers):
        return self._request(
            "GET", f"/contingent-bonus-pools/{pool_id}", headers=headers
        )

    def settle_bonus_pool(self, pool_id, headers):
        return self._request(
            "POST", f"/contingent-bonus-pools/{pool_id}/settle", {}, headers
        )

    def list_pool_bonus_payouts(self, pool_id, headers, params=None):
        return self._request(
            "GET", f"/contingent-bonus-pools/{pool_id}/bonus-payouts",
            headers=headers, params=params,
        )

    def list_agent_bonus_payouts(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/bonus-payouts", headers=headers, params=params
        )

    def get_bonus_payout(self, payout_id, headers):
        return self._request("GET", f"/bonus-payouts/{payout_id}", headers=headers)

    # ---- portfolio reviews ----------------------------------------------
    def create_portfolio_review(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/agents/{agent_id}/portfolio-reviews", payload, headers
        )

    def list_agent_portfolio_reviews(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/portfolio-reviews",
            headers=headers, params=params,
        )

    def get_portfolio_review(self, review_id, headers):
        return self._request(
            "GET", f"/portfolio-reviews/{review_id}", headers=headers
        )

    def issue_findings(self, review_id, payload, headers):
        return self._request(
            "POST", f"/portfolio-reviews/{review_id}/issue-findings", payload, headers
        )

    def take_review_action(self, review_id, payload, headers):
        return self._request(
            "POST", f"/portfolio-reviews/{review_id}/take-action", payload, headers
        )

    # ---- bundle placements -----------------------------------------------
    def create_bundle_placement(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/bundle-placements", payload, headers
        )

    def list_policy_bundle_placements(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/policies/{policy_id}/bundle-placements",
            headers=headers, params=params,
        )

    def list_bundle_placements(self, headers, params=None):
        return self._request(
            "GET", "/bundle-placements", headers=headers, params=params
        )

    def get_bundle_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/bundle-placements/{placement_id}", headers=headers
        )

    def place_bundle_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/bundle-placements/{placement_id}/place", {}, headers
        )

    def transfer_bundle_placement_aor(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/bundle-placements/{placement_id}/transfer-aor", payload, headers
        )

    def decline_bundle_placement(self, placement_id, headers, payload=None):
        return self._request(
            "POST", f"/bundle-placements/{placement_id}/decline", payload or {}, headers
        )

    # ---- leakage analytics ----------------------------------------------
    def get_leakage_report(self, headers, params=None):
        return self._request(
            "GET", "/leakage-reports/quote-to-bind", headers=headers, params=params
        )


api_client = ApiClient()
