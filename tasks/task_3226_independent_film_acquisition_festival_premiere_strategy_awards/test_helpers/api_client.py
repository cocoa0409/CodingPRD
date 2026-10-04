"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # --- Films ---
    def create_film(self, payload, headers):
        return self._request("POST", "/films", payload, headers)

    def get_film(self, film_id, headers):
        return self._request("GET", f"/films/{film_id}", headers=headers)

    def list_films(self, headers, params=None):
        return self._request("GET", "/films", headers=headers, params=params)

    def list_film_premiere_slots(self, film_id, headers, params=None):
        return self._request(
            "GET", f"/films/{film_id}/premiere-slots",
            headers=headers, params=params,
        )

    def pass_film(self, film_id, headers):
        return self._request("POST", f"/films/{film_id}/pass", {}, headers)

    def archive_film(self, film_id, headers):
        return self._request("POST", f"/films/{film_id}/archive", {}, headers)

    # --- Offers ---
    def create_offer(self, film_id, payload, headers):
        return self._request("POST", f"/films/{film_id}/offers", payload, headers)

    def list_offers(self, film_id, headers, params=None):
        return self._request(
            "GET", f"/films/{film_id}/offers", headers=headers, params=params,
        )

    def get_offer(self, film_id, offer_id, headers):
        return self._request(
            "GET", f"/films/{film_id}/offers/{offer_id}", headers=headers,
        )

    def get_offer_by_id(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers_reverse(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def counter_offer(self, film_id, offer_id, payload, headers):
        return self._request(
            "POST", f"/films/{film_id}/offers/{offer_id}/counter",
            payload, headers,
        )

    def accept_offer(self, film_id, offer_id, payload, headers):
        return self._request(
            "POST", f"/films/{film_id}/offers/{offer_id}/accept",
            payload, headers,
        )

    def reject_offer(self, film_id, offer_id, headers):
        return self._request(
            "POST", f"/films/{film_id}/offers/{offer_id}/reject", {}, headers,
        )

    def withdraw_offer(self, film_id, offer_id, headers):
        return self._request(
            "POST", f"/films/{film_id}/offers/{offer_id}/withdraw", {}, headers,
        )

    # --- Territories ---
    def create_territory(self, payload, headers):
        return self._request("POST", "/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request("GET", f"/territories/{territory_id}", headers=headers)

    def list_territories(self, headers, params=None):
        return self._request("GET", "/territories", headers=headers, params=params)

    # --- Festivals & premiere slots ---
    def create_festival(self, payload, headers):
        return self._request("POST", "/festivals", payload, headers)

    def get_festival(self, festival_id, headers):
        return self._request("GET", f"/festivals/{festival_id}", headers=headers)

    def create_premiere_slot(self, festival_id, payload, headers):
        return self._request(
            "POST", f"/festivals/{festival_id}/premiere-slots", payload, headers,
        )

    def list_premiere_slots(self, festival_id, headers, params=None):
        return self._request(
            "GET", f"/festivals/{festival_id}/premiere-slots",
            headers=headers, params=params,
        )

    def get_premiere_slot_nested(self, festival_id, slot_id, headers):
        return self._request(
            "GET", f"/festivals/{festival_id}/premiere-slots/{slot_id}",
            headers=headers,
        )

    def get_premiere_slot(self, slot_id, headers):
        return self._request("GET", f"/premiere-slots/{slot_id}", headers=headers)

    def list_premiere_slots_reverse(self, headers, params=None):
        return self._request("GET", "/premiere-slots", headers=headers, params=params)

    def hold_premiere_slot(self, festival_id, slot_id, payload, headers):
        return self._request(
            "POST", f"/festivals/{festival_id}/premiere-slots/{slot_id}/hold",
            payload, headers,
        )

    def book_premiere_slot(self, festival_id, slot_id, payload, headers):
        return self._request(
            "POST", f"/festivals/{festival_id}/premiere-slots/{slot_id}/book",
            payload, headers,
        )

    def release_hold_premiere_slot(self, festival_id, slot_id, headers):
        return self._request(
            "POST",
            f"/festivals/{festival_id}/premiere-slots/{slot_id}/release-hold",
            {}, headers,
        )

    def cancel_premiere_slot(self, festival_id, slot_id, headers):
        return self._request(
            "POST", f"/festivals/{festival_id}/premiere-slots/{slot_id}/cancel",
            {}, headers,
        )

    # --- Deals & rights grants ---
    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def list_film_deals(self, film_id, headers, params=None):
        return self._request(
            "GET", f"/films/{film_id}/deals", headers=headers, params=params,
        )

    def report_theatrical_spend(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/deals/{deal_id}/report-theatrical-spend",
            payload, headers,
        )

    def list_deal_rights_grants(self, deal_id, headers, params=None):
        return self._request(
            "GET", f"/deals/{deal_id}/rights-grants",
            headers=headers, params=params,
        )

    def get_rights_grant(self, grant_id, headers):
        return self._request("GET", f"/rights-grants/{grant_id}", headers=headers)

    def list_rights_grants_reverse(self, headers, params=None):
        return self._request("GET", "/rights-grants", headers=headers, params=params)

    # --- Release plans & market screenings ---
    def create_release_plan(self, film_id, payload, headers):
        return self._request(
            "POST", f"/films/{film_id}/release-plans", payload, headers,
        )

    def get_release_plan_nested(self, film_id, plan_id, headers):
        return self._request(
            "GET", f"/films/{film_id}/release-plans/{plan_id}", headers=headers,
        )

    def get_release_plan(self, plan_id, headers):
        return self._request("GET", f"/release-plans/{plan_id}", headers=headers)

    def list_release_plans(self, film_id, headers, params=None):
        return self._request(
            "GET", f"/films/{film_id}/release-plans",
            headers=headers, params=params,
        )

    def list_release_plans_reverse(self, headers, params=None):
        return self._request("GET", "/release-plans", headers=headers, params=params)

    def open_release_plan(self, film_id, plan_id, headers):
        return self._request(
            "POST", f"/films/{film_id}/release-plans/{plan_id}/open",
            {}, headers,
        )

    def pull_release_plan(self, film_id, plan_id, headers):
        return self._request(
            "POST", f"/films/{film_id}/release-plans/{plan_id}/pull",
            {}, headers,
        )

    def schedule_market_screening(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/release-plans/{plan_id}/market-screenings",
            payload, headers,
        )

    def list_market_screenings(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/release-plans/{plan_id}/market-screenings",
            headers=headers, params=params,
        )

    def get_market_screening(self, screening_id, headers):
        return self._request(
            "GET", f"/market-screenings/{screening_id}", headers=headers,
        )

    def list_market_screenings_reverse(self, headers, params=None):
        return self._request(
            "GET", "/market-screenings", headers=headers, params=params,
        )

    def report_market_screening(self, plan_id, screening_id, payload, headers):
        return self._request(
            "POST",
            f"/release-plans/{plan_id}/market-screenings/{screening_id}/report",
            payload, headers,
        )

    # --- Awards campaigns & spends ---
    def create_awards_campaign(self, film_id, payload, headers):
        return self._request(
            "POST", f"/films/{film_id}/awards-campaigns", payload, headers,
        )

    def list_awards_campaigns(self, film_id, headers, params=None):
        return self._request(
            "GET", f"/films/{film_id}/awards-campaigns",
            headers=headers, params=params,
        )

    def get_awards_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"/awards-campaigns/{campaign_id}", headers=headers,
        )

    def list_awards_campaigns_reverse(self, headers, params=None):
        return self._request(
            "GET", "/awards-campaigns", headers=headers, params=params,
        )

    def activate_awards_campaign(self, film_id, campaign_id, headers):
        return self._request(
            "POST",
            f"/films/{film_id}/awards-campaigns/{campaign_id}/activate",
            {}, headers,
        )

    def submit_awards_campaign(self, film_id, campaign_id, headers):
        return self._request(
            "POST",
            f"/films/{film_id}/awards-campaigns/{campaign_id}/submit",
            {}, headers,
        )

    def conclude_awards_campaign(self, film_id, campaign_id, headers):
        return self._request(
            "POST",
            f"/films/{film_id}/awards-campaigns/{campaign_id}/conclude",
            {}, headers,
        )

    def create_campaign_spend(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/awards-campaigns/{campaign_id}/spends", payload, headers,
        )

    def list_campaign_spends(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/awards-campaigns/{campaign_id}/spends",
            headers=headers, params=params,
        )

    def get_campaign_spend(self, spend_id, headers):
        return self._request(
            "GET", f"/campaign-spends/{spend_id}", headers=headers,
        )

    def list_campaign_spends_reverse(self, headers, params=None):
        return self._request(
            "GET", "/campaign-spends", headers=headers, params=params,
        )

    # --- Talent obligations ---
    def create_talent_obligation(self, film_id, payload, headers):
        return self._request(
            "POST", f"/films/{film_id}/talent-obligations", payload, headers,
        )

    def list_talent_obligations(self, film_id, headers, params=None):
        return self._request(
            "GET", f"/films/{film_id}/talent-obligations",
            headers=headers, params=params,
        )

    def get_talent_obligation(self, obligation_id, headers):
        return self._request(
            "GET", f"/talent-obligations/{obligation_id}", headers=headers,
        )

    def list_talent_obligations_reverse(self, headers, params=None):
        return self._request(
            "GET", "/talent-obligations", headers=headers, params=params,
        )

    def confirm_talent_obligation(self, film_id, obligation_id, headers):
        return self._request(
            "POST",
            f"/films/{film_id}/talent-obligations/{obligation_id}/confirm",
            {}, headers,
        )

    def fulfill_talent_obligation(self, film_id, obligation_id, headers):
        return self._request(
            "POST",
            f"/films/{film_id}/talent-obligations/{obligation_id}/fulfill",
            {}, headers,
        )

    def waive_talent_obligation(self, film_id, obligation_id, headers):
        return self._request(
            "POST",
            f"/films/{film_id}/talent-obligations/{obligation_id}/waive",
            {}, headers,
        )

    # --- Filmmaker statements ---
    def create_statement(self, film_id, payload, headers):
        return self._request(
            "POST", f"/films/{film_id}/statements", payload, headers,
        )

    def list_statements(self, film_id, headers, params=None):
        return self._request(
            "GET", f"/films/{film_id}/statements",
            headers=headers, params=params,
        )

    def get_statement_nested(self, film_id, statement_id, headers):
        return self._request(
            "GET", f"/films/{film_id}/statements/{statement_id}",
            headers=headers,
        )

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def list_statements_reverse(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    def finalize_statement(self, film_id, statement_id, headers):
        return self._request(
            "POST",
            f"/films/{film_id}/statements/{statement_id}/finalize",
            {}, headers,
        )


api_client = ApiClient()
