"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Consumers ---
    def create_consumer(self, payload, headers):
        return self._request("POST", "/credit/consumers", payload, headers)

    def list_consumers(self, headers, params=None):
        return self._request("GET", "/credit/consumers", headers=headers, params=params)

    def get_consumer(self, consumer_id, headers):
        return self._request("GET", f"/credit/consumers/{consumer_id}", headers=headers)

    def get_adverse_action_summary(self, consumer_id, headers):
        return self._request(
            "GET", f"/credit/consumers/{consumer_id}/adverse-action-summary", headers=headers
        )

    def grant_monitoring_consent(self, consumer_id, headers):
        return self._request(
            "POST", f"/credit/consumers/{consumer_id}/monitoring-consent", {}, headers
        )

    def close_consumer(self, consumer_id, headers):
        return self._request("POST", f"/credit/consumers/{consumer_id}/close", {}, headers)

    # --- Bureau pulls and snapshots ---
    def create_bureau_snapshot(self, consumer_id, payload, headers):
        return self._request(
            "POST", f"/credit/consumers/{consumer_id}/bureau-snapshots", payload, headers
        )

    def list_bureau_snapshots(self, headers, params=None):
        return self._request("GET", "/credit/bureau-snapshots", headers=headers, params=params)

    def get_bureau_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/credit/bureau-snapshots/{snapshot_id}", headers=headers)

    def list_consumer_bureau_snapshots(self, consumer_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit/consumers/{consumer_id}/bureau-snapshots",
            headers=headers,
            params=params,
        )

    def replay_bureau_snapshot(self, snapshot_id, headers):
        return self._request(
            "POST", f"/credit/bureau-snapshots/{snapshot_id}/replay", {}, headers
        )

    # --- Score factor explanations ---
    def list_snapshot_factor_explanations(self, snapshot_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit/bureau-snapshots/{snapshot_id}/score-factor-explanations",
            headers=headers,
            params=params,
        )

    def list_factor_explanations(self, headers, params=None):
        return self._request(
            "GET", "/credit/score-factor-explanations", headers=headers, params=params
        )

    def get_factor_explanation(self, explanation_id, headers):
        return self._request(
            "GET", f"/credit/score-factor-explanations/{explanation_id}", headers=headers
        )

    # --- Score alerts ---
    def list_score_alerts(self, headers, params=None):
        return self._request("GET", "/credit/score-alerts", headers=headers, params=params)

    def list_consumer_score_alerts(self, consumer_id, headers, params=None):
        return self._request(
            "GET", f"/credit/consumers/{consumer_id}/score-alerts", headers=headers, params=params
        )

    def get_score_alert(self, alert_id, headers):
        return self._request("GET", f"/credit/score-alerts/{alert_id}", headers=headers)

    def acknowledge_score_alert(self, alert_id, headers):
        return self._request("POST", f"/credit/score-alerts/{alert_id}/acknowledge", {}, headers)

    def suppress_score_alert(self, alert_id, headers):
        return self._request("POST", f"/credit/score-alerts/{alert_id}/suppress", {}, headers)

    def set_score_alert_threshold(self, consumer_id, payload, headers):
        return self._request(
            "PUT", f"/credit/consumers/{consumer_id}/score-alert-threshold", payload, headers
        )

    def list_score_alert_thresholds(self, headers, params=None):
        return self._request(
            "GET", "/credit/score-alert-thresholds", headers=headers, params=params
        )

    def get_score_alert_threshold(self, threshold_id, headers):
        return self._request(
            "GET", f"/credit/score-alert-thresholds/{threshold_id}", headers=headers
        )

    # --- Simulations ---
    def create_simulation(self, consumer_id, payload, headers):
        return self._request(
            "POST", f"/credit/consumers/{consumer_id}/simulations", payload, headers
        )

    def list_consumer_simulations(self, consumer_id, headers, params=None):
        return self._request(
            "GET", f"/credit/consumers/{consumer_id}/simulations", headers=headers, params=params
        )

    def list_simulations(self, headers, params=None):
        return self._request("GET", "/credit/score-simulations", headers=headers, params=params)

    def get_simulation(self, simulation_id, headers):
        return self._request("GET", f"/credit/score-simulations/{simulation_id}", headers=headers)

    def settle_simulation(self, simulation_id, headers):
        return self._request(
            "POST", f"/credit/score-simulations/{simulation_id}/settle", {}, headers
        )

    # --- Catalog items ---
    def create_catalog_item(self, payload, headers):
        return self._request("POST", "/credit/catalog/items", payload, headers)

    def list_catalog_items(self, headers, params=None):
        return self._request("GET", "/credit/catalog/items", headers=headers, params=params)

    def get_catalog_item(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/credit/catalog/items/{item_id}", headers=headers, params=params
        )

    def get_catalog_item_settled_index(self, item_id, headers):
        return self._request(
            "GET", f"/credit/catalog/items/{item_id}/settled-index", headers=headers
        )

    def activate_catalog_item(self, item_id, headers):
        return self._request("POST", f"/credit/catalog/items/{item_id}/activate", {}, headers)

    def retire_catalog_item(self, item_id, headers):
        return self._request("POST", f"/credit/catalog/items/{item_id}/retire", {}, headers)

    def list_catalog_item_programs(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/credit/catalog/items/{item_id}/lender-programs", headers=headers, params=params
        )

    # --- Lenders ---
    def create_lender(self, payload, headers):
        return self._request("POST", "/credit/lenders", payload, headers)

    def list_lenders(self, headers, params=None):
        return self._request("GET", "/credit/lenders", headers=headers, params=params)

    def get_lender(self, lender_id, headers):
        return self._request("GET", f"/credit/lenders/{lender_id}", headers=headers)

    def set_lender_compliance_status(self, lender_id, payload, headers):
        return self._request(
            "POST", f"/credit/lenders/{lender_id}/compliance-status", payload, headers
        )

    def activate_lender(self, lender_id, headers):
        return self._request("POST", f"/credit/lenders/{lender_id}/activate", {}, headers)

    def offboard_lender(self, lender_id, headers):
        return self._request("POST", f"/credit/lenders/{lender_id}/offboard", {}, headers)

    # --- Lender programs ---
    def create_lender_program(self, payload, headers):
        return self._request("POST", "/credit/lender-programs", payload, headers)

    def list_lender_programs(self, headers, params=None):
        return self._request("GET", "/credit/lender-programs", headers=headers, params=params)

    def get_lender_program(self, program_id, headers):
        return self._request("GET", f"/credit/lender-programs/{program_id}", headers=headers)

    def list_lender_programs_of_lender(self, lender_id, headers, params=None):
        return self._request(
            "GET", f"/credit/lenders/{lender_id}/lender-programs", headers=headers, params=params
        )

    def activate_lender_program(self, program_id, headers):
        return self._request("POST", f"/credit/lender-programs/{program_id}/activate", {}, headers)

    def pause_lender_program(self, program_id, headers):
        return self._request("POST", f"/credit/lender-programs/{program_id}/pause", {}, headers)

    def resume_lender_program(self, program_id, headers):
        return self._request("POST", f"/credit/lender-programs/{program_id}/resume", {}, headers)

    def create_targeting_criterion(self, program_id, payload, headers):
        return self._request(
            "POST", f"/credit/lender-programs/{program_id}/targeting-criteria", payload, headers
        )

    def list_targeting_criteria(self, headers, params=None):
        return self._request("GET", "/credit/targeting-criteria", headers=headers, params=params)

    def get_targeting_criterion(self, criterion_id, headers):
        return self._request("GET", f"/credit/targeting-criteria/{criterion_id}", headers=headers)

    def list_program_targeting_criteria(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit/lender-programs/{program_id}/targeting-criteria",
            headers=headers,
            params=params,
        )

    # --- Pre-qualification decisions ---
    def create_prequalification(self, consumer_id, payload, headers):
        return self._request(
            "POST", f"/credit/consumers/{consumer_id}/pre-qualifications", payload, headers
        )

    def list_prequalification_decisions(self, headers, params=None):
        return self._request(
            "GET", "/credit/pre-qualification-decisions", headers=headers, params=params
        )

    def get_prequalification_decision(self, decision_id, headers):
        return self._request(
            "GET", f"/credit/pre-qualification-decisions/{decision_id}", headers=headers
        )

    def list_consumer_decisions(self, consumer_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit/consumers/{consumer_id}/pre-qualification-decisions",
            headers=headers,
            params=params,
        )

    def list_program_decisions(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit/lender-programs/{program_id}/pre-qualification-decisions",
            headers=headers,
            params=params,
        )

    def list_snapshot_decisions(self, snapshot_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit/bureau-snapshots/{snapshot_id}/pre-qualification-decisions",
            headers=headers,
            params=params,
        )

    def qualify_decision(self, decision_id, headers):
        return self._request(
            "POST", f"/credit/pre-qualification-decisions/{decision_id}/qualify", {}, headers
        )

    # --- Offers ---
    def list_decision_offers(self, decision_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit/pre-qualification-decisions/{decision_id}/pre-qualified-offers",
            headers=headers,
            params=params,
        )

    def present_decision(self, decision_id, payload, headers):
        return self._request(
            "POST", f"/credit/pre-qualification-decisions/{decision_id}/present", payload, headers
        )

    def list_offers(self, headers, params=None):
        return self._request("GET", "/credit/pre-qualified-offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/credit/pre-qualified-offers/{offer_id}", headers=headers)

    def render_offer(self, offer_id, headers):
        return self._request("POST", f"/credit/offers/{offer_id}/render", {}, headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/credit/offers/{offer_id}/withdraw", {}, headers)

    def list_consumer_offers(self, consumer_id, headers, params=None):
        return self._request(
            "GET", f"/credit/consumers/{consumer_id}/pre-qualified-offers", headers=headers,
            params=params,
        )

    def list_program_offers(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/credit/lender-programs/{program_id}/pre-qualified-offers", headers=headers,
            params=params,
        )

    # --- Consent ---
    def complete_consent(self, consumer_id, decision_id, payload, headers):
        return self._request(
            "POST",
            f"/credit/consumers/{consumer_id}/consents/{decision_id}/complete",
            payload,
            headers,
        )

    def list_consent_records(self, headers, params=None):
        return self._request("GET", "/credit/consent-records", headers=headers, params=params)

    def get_consent_record(self, consent_id, headers):
        return self._request("GET", f"/credit/consent-records/{consent_id}", headers=headers)

    def list_consumer_consent_records(self, consumer_id, headers, params=None):
        return self._request(
            "GET", f"/credit/consumers/{consumer_id}/consent-records", headers=headers,
            params=params,
        )

    def list_decision_consent_records(self, decision_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit/pre-qualification-decisions/{decision_id}/consent-records",
            headers=headers,
            params=params,
        )

    # --- Referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/credit/referrals", payload, headers)

    def create_referral_attempt(self, payload, headers):
        return self._request("POST", "/credit/referral-attempts", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/credit/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/credit/referrals/{referral_id}", headers=headers)

    def fund_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/credit/referrals/{referral_id}/fund", payload, headers)

    def decline_referral(self, referral_id, headers):
        return self._request("POST", f"/credit/referrals/{referral_id}/decline", {}, headers)

    def reverse_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/credit/referrals/{referral_id}/reverse", payload, headers)

    def list_revenue_entries(self, headers, params=None):
        return self._request(
            "GET", "/credit/revenue-recognition-entries", headers=headers, params=params
        )

    def get_revenue_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/credit/revenue-recognition-entries/{entry_id}", headers=headers
        )

    def list_referral_revenue_entries(self, referral_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit/referrals/{referral_id}/revenue-recognition-entries",
            headers=headers,
            params=params,
        )

    def list_consumer_revenue_entries(self, consumer_id, headers, params=None):
        return self._request(
            "GET",
            f"/credit/consumers/{consumer_id}/revenue-recognition-entries",
            headers=headers,
            params=params,
        )

    # --- Dispute referrals ---
    def create_dispute_referral(self, payload, headers):
        return self._request("POST", "/credit/dispute-referrals", payload, headers)

    def list_dispute_referrals(self, headers, params=None):
        return self._request("GET", "/credit/dispute-referrals", headers=headers, params=params)

    def get_dispute_referral(self, dispute_id, headers):
        return self._request("GET", f"/credit/dispute-referrals/{dispute_id}", headers=headers)

    def list_consumer_dispute_referrals(self, consumer_id, headers, params=None):
        return self._request(
            "GET", f"/credit/consumers/{consumer_id}/dispute-referrals", headers=headers,
            params=params,
        )

    def list_snapshot_dispute_referrals(self, snapshot_id, headers, params=None):
        return self._request(
            "GET", f"/credit/bureau-snapshots/{snapshot_id}/dispute-referrals", headers=headers,
            params=params,
        )

    def list_referral_dispute_referrals(self, referral_id, headers, params=None):
        return self._request(
            "GET", f"/credit/referrals/{referral_id}/dispute-referrals", headers=headers,
            params=params,
        )

    def submit_dispute_referral(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/credit/dispute-referrals/{dispute_id}/submit", payload, headers
        )

    def acknowledge_dispute_referral(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/credit/dispute-referrals/{dispute_id}/acknowledge", payload, headers
        )

    def withdraw_dispute_referral(self, dispute_id, headers):
        return self._request(
            "POST", f"/credit/dispute-referrals/{dispute_id}/withdraw", {}, headers
        )

    # --- Score tiers ---
    def create_score_tier(self, payload, headers):
        return self._request("POST", "/credit/score-tiers", payload, headers)

    def list_score_tiers(self, headers, params=None):
        return self._request("GET", "/credit/score-tiers", headers=headers, params=params)

    def activate_score_tier(self, tier_id, headers):
        return self._request("POST", f"/credit/score-tiers/{tier_id}/activate", {}, headers)

    def retire_score_tier(self, tier_id, headers):
        return self._request("POST", f"/credit/score-tiers/{tier_id}/retire", {}, headers)

    # --- Render policy, content quality, presentation caps ---
    def set_render_policy(self, consumer_id, payload, headers):
        return self._request(
            "PUT", f"/credit/consumers/{consumer_id}/render-policy", payload, headers
        )

    def list_render_policies(self, headers, params=None):
        return self._request("GET", "/credit/render-policies", headers=headers, params=params)

    def list_consumer_render_policies(self, consumer_id, headers, params=None):
        return self._request(
            "GET", f"/credit/consumers/{consumer_id}/render-policies", headers=headers,
            params=params,
        )

    def create_content_quality_facet(self, consumer_id, payload, headers):
        return self._request(
            "POST", f"/credit/consumers/{consumer_id}/content-quality-facets", payload, headers
        )

    def list_content_quality_facets(self, headers, params=None):
        return self._request(
            "GET", "/credit/content-quality-facets", headers=headers, params=params
        )

    def list_consumer_content_quality_facets(self, consumer_id, headers, params=None):
        return self._request(
            "GET", f"/credit/consumers/{consumer_id}/content-quality-facets", headers=headers,
            params=params,
        )

    def score_content_quality_facet(self, facet_id, payload, headers):
        return self._request(
            "POST", f"/credit/content-quality-facets/{facet_id}/score", payload, headers
        )

    def list_offer_presentation_caps(self, headers, params=None):
        return self._request(
            "GET", "/credit/offer-presentation-caps", headers=headers, params=params
        )

    def list_consumer_offer_presentation_caps(self, consumer_id, headers, params=None):
        return self._request(
            "GET", f"/credit/consumers/{consumer_id}/offer-presentation-caps", headers=headers,
            params=params,
        )

    # --- Ops run and logical clock ---
    def run_ops(self, payload, headers):
        return self._request("POST", "/credit/_ops/runs", payload, headers)

    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/credit/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


api_client = ApiClient()