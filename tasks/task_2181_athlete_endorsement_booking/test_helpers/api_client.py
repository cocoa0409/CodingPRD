"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock ────────────────────────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Athletes ─────────────────────────────────────────────────────────
    def create_athlete(self, payload, headers):
        return self._request("POST", "/athletes", payload, headers)

    def get_athlete(self, athlete_id, headers):
        return self._request("GET", f"/athletes/{athlete_id}", headers=headers)

    def set_athlete_status(self, athlete_id, payload, headers):
        return self._request("POST", f"/athletes/{athlete_id}/status", payload, headers)

    def get_exposure_summary(self, athlete_id, headers, params=None):
        return self._request(
            "GET", f"/athletes/{athlete_id}/exposure-summary", headers=headers, params=params
        )

    def list_athlete_exclusivity_grants(self, athlete_id, headers, params=None):
        return self._request(
            "GET", f"/athletes/{athlete_id}/exclusivity-grants", headers=headers, params=params
        )

    # ── Brands ───────────────────────────────────────────────────────────
    def create_brand(self, payload, headers):
        return self._request("POST", "/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/brands/{brand_id}", headers=headers)

    def sanction_brand(self, brand_id, payload, headers):
        return self._request("POST", f"/brands/{brand_id}/sanction", payload, headers)

    # ── Opportunities ────────────────────────────────────────────────────
    def create_opportunity(self, payload, headers):
        return self._request("POST", "/opportunities", payload, headers)

    def get_opportunity(self, opportunity_id, headers):
        return self._request("GET", f"/opportunities/{opportunity_id}", headers=headers)

    def list_opportunities(self, headers, params=None):
        return self._request("GET", "/opportunities", headers=headers, params=params)

    def screen_opportunity(self, opportunity_id, headers):
        return self._request(
            "POST", f"/opportunities/{opportunity_id}/screen", {}, headers
        )

    # ── Term sheets ──────────────────────────────────────────────────────
    def create_term_sheet(self, payload, headers):
        return self._request("POST", "/term-sheets", payload, headers)

    def get_term_sheet(self, term_sheet_id, headers):
        return self._request("GET", f"/term-sheets/{term_sheet_id}", headers=headers)

    def list_term_sheets(self, headers, params=None):
        return self._request("GET", "/term-sheets", headers=headers, params=params)

    def submit_term_sheet(self, term_sheet_id, headers):
        return self._request("POST", f"/term-sheets/{term_sheet_id}/submit", {}, headers)

    def counter_term_sheet(self, term_sheet_id, payload, headers):
        return self._request(
            "POST", f"/term-sheets/{term_sheet_id}/counter", payload, headers
        )

    def revise_term_sheet(self, term_sheet_id, payload, headers):
        return self._request(
            "POST", f"/term-sheets/{term_sheet_id}/revise", payload, headers
        )

    def accept_term_sheet(self, term_sheet_id, headers):
        return self._request("POST", f"/term-sheets/{term_sheet_id}/accept", {}, headers)

    def withdraw_term_sheet(self, term_sheet_id, payload, headers):
        return self._request(
            "POST", f"/term-sheets/{term_sheet_id}/withdraw", payload, headers
        )

    # ── Engagements ──────────────────────────────────────────────────────
    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def countersign_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/countersign", payload, headers
        )

    def terminate_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/terminate", payload, headers
        )

    def list_ledger_entries(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/engagements/{engagement_id}/ledger-entries", headers=headers, params=params
        )

    def list_engagement_exclusivity_grants(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/engagements/{engagement_id}/exclusivity-grants", headers=headers, params=params
        )

    def list_engagement_payout_statements(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/engagements/{engagement_id}/payout-statements", headers=headers, params=params
        )

    def list_engagement_renewal_options(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/engagements/{engagement_id}/renewal-options", headers=headers, params=params
        )

    # ── Appearance bookings ──────────────────────────────────────────────
    def create_appearance_booking(self, payload, headers):
        return self._request("POST", "/appearance-bookings", payload, headers)

    def get_appearance_booking(self, booking_id, headers):
        return self._request("GET", f"/appearance-bookings/{booking_id}", headers=headers)

    def list_appearance_bookings(self, headers, params=None):
        return self._request("GET", "/appearance-bookings", headers=headers, params=params)

    def confirm_appearance_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/appearance-bookings/{booking_id}/confirm", payload, headers
        )

    def close_appearance_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/appearance-bookings/{booking_id}/close", payload, headers
        )

    def cancel_appearance_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/appearance-bookings/{booking_id}/cancel", payload, headers
        )

    # ── Production slots ─────────────────────────────────────────────────
    def create_production_slot(self, payload, headers):
        return self._request("POST", "/production-slots", payload, headers)

    def get_production_slot(self, slot_id, headers):
        return self._request("GET", f"/production-slots/{slot_id}", headers=headers)

    # ── Deliverables ─────────────────────────────────────────────────────
    def create_deliverable(self, payload, headers):
        return self._request("POST", "/deliverables", payload, headers)

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/deliverables/{deliverable_id}", headers=headers)

    def list_deliverables(self, headers, params=None):
        return self._request("GET", "/deliverables", headers=headers, params=params)

    def submit_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/submit", payload, headers
        )

    def review_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/review", payload, headers
        )

    def list_disclosure_records(self, deliverable_id, headers, params=None):
        return self._request(
            "GET", f"/deliverables/{deliverable_id}/disclosure-records", headers=headers, params=params
        )

    # ── Disclosure records ───────────────────────────────────────────────
    def create_disclosure_record(self, payload, headers):
        return self._request("POST", "/disclosure-records", payload, headers)

    def rule_disclosure_record(self, disclosure_id, payload, headers):
        return self._request(
            "POST", f"/disclosure-records/{disclosure_id}/rule", payload, headers
        )

    def remediate_disclosure_record(self, disclosure_id, payload, headers):
        return self._request(
            "POST", f"/disclosure-records/{disclosure_id}/remediate", payload, headers
        )

    # ── Payout statements ────────────────────────────────────────────────
    def create_payout_statement(self, payload, headers):
        return self._request("POST", "/payout-statements", payload, headers)

    def disburse_payout_statement(self, payout_id, headers):
        return self._request(
            "POST", f"/payout-statements/{payout_id}/disburse", {}, headers
        )

    # ── Renewal options ──────────────────────────────────────────────────
    def create_renewal_option(self, payload, headers):
        return self._request("POST", "/renewal-options", payload, headers)

    def decide_renewal_option(self, renewal_id, payload, headers):
        return self._request(
            "POST", f"/renewal-options/{renewal_id}/decide", payload, headers
        )


api_client = ApiClient()
