"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/mls/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def advance_day(self, headers, days=None):
        payload = {} if days is None else {"days": days}
        return self._request("POST", "/mls/_clock/advance_day", payload, headers)

    # --- associations ---
    def create_association(self, payload, headers):
        return self._request("POST", "/mls/associations", payload, headers)

    def get_association(self, association_id, headers):
        return self._request("GET", f"/mls/associations/{association_id}", headers=headers)

    def list_associations(self, headers, params=None):
        return self._request("GET", "/mls/associations", headers=headers, params=params)

    # --- members ---
    def create_member(self, association_id, payload, headers):
        return self._request("POST", f"/mls/associations/{association_id}/members",
                             payload, headers)

    def get_member(self, association_id, member_id, headers):
        return self._request(
            "GET", f"/mls/associations/{association_id}/members/{member_id}", headers=headers)

    def list_members(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/members",
                             headers=headers, params=params)

    def terminate_member(self, association_id, member_id, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/members/{member_id}/terminate",
            {}, headers)

    def create_credit_adjustment(self, association_id, member_id, payload, headers):
        return self._request(
            "POST",
            f"/mls/associations/{association_id}/members/{member_id}/credit-adjustments",
            payload, headers)

    # --- offices ---
    def create_office(self, association_id, payload, headers):
        return self._request("POST", f"/mls/associations/{association_id}/offices",
                             payload, headers)

    def get_office(self, association_id, office_id, headers):
        return self._request(
            "GET", f"/mls/associations/{association_id}/offices/{office_id}", headers=headers)

    def list_offices(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/offices",
                             headers=headers, params=params)

    def close_office(self, association_id, office_id, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/offices/{office_id}/close",
            {}, headers)

    # --- listings ---
    def create_listing(self, association_id, office_id, payload, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/offices/{office_id}/listings",
            payload, headers)

    def get_listing(self, association_id, office_id, listing_id, headers):
        return self._request(
            "GET",
            f"/mls/associations/{association_id}/offices/{office_id}/listings/{listing_id}",
            headers=headers)

    def list_listings(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/listings",
                             headers=headers, params=params)

    def activate_listing(self, association_id, office_id, listing_id, headers):
        return self._request(
            "POST",
            f"/mls/associations/{association_id}/offices/{office_id}/listings/{listing_id}/activate",
            {}, headers)

    def change_listing_status(self, association_id, office_id, listing_id, payload, headers):
        return self._request(
            "POST",
            f"/mls/associations/{association_id}/offices/{office_id}/listings/{listing_id}/status",
            payload, headers)

    def list_listing_status_changes(self, association_id, office_id, listing_id, headers):
        return self._request(
            "GET",
            f"/mls/associations/{association_id}/offices/{office_id}/listings/{listing_id}/status-changes",
            headers=headers)

    # --- dues periods ---
    def create_dues_period(self, association_id, payload, headers):
        return self._request("POST", f"/mls/associations/{association_id}/dues-periods",
                             payload, headers)

    def get_dues_period(self, association_id, period_id, headers):
        return self._request(
            "GET", f"/mls/associations/{association_id}/dues-periods/{period_id}",
            headers=headers)

    def list_dues_periods(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/dues-periods",
                             headers=headers, params=params)

    def bill_dues_period(self, association_id, period_id, expected_version, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/dues-periods/{period_id}/bill",
            {"expected_dues_period_version": expected_version}, headers)

    def reconcile_dues_period(self, association_id, period_id, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/dues-periods/{period_id}/reconcile",
            {}, headers)

    # --- dues invoices ---
    def get_dues_invoice(self, association_id, invoice_id, headers):
        return self._request(
            "GET", f"/mls/associations/{association_id}/dues-invoices/{invoice_id}",
            headers=headers)

    def list_dues_invoices(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/dues-invoices",
                             headers=headers, params=params)

    def list_dues_invoices_flat(self, headers, params=None):
        return self._request("GET", "/mls/dues-invoices", headers=headers, params=params)

    def pay_dues_invoice(self, association_id, invoice_id, tender_cents, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/dues-invoices/{invoice_id}/pay",
            {"tender_cents": tender_cents}, headers)

    def waive_dues_invoice(self, association_id, invoice_id, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/dues-invoices/{invoice_id}/waive",
            {}, headers)

    # --- citations ---
    def create_citation(self, association_id, payload, headers):
        return self._request("POST", f"/mls/associations/{association_id}/citations",
                             payload, headers)

    def get_citation(self, association_id, citation_id, headers):
        return self._request(
            "GET", f"/mls/associations/{association_id}/citations/{citation_id}",
            headers=headers)

    def list_citations(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/citations",
                             headers=headers, params=params)

    def pay_citation(self, association_id, citation_id, tender_cents, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/citations/{citation_id}/pay",
            {"tender_cents": tender_cents}, headers)

    def request_hearing(self, association_id, citation_id, headers):
        return self._request(
            "POST",
            f"/mls/associations/{association_id}/citations/{citation_id}/request-hearing",
            {}, headers)

    def donate_credit(self, association_id, citation_id, amount_cents, headers):
        return self._request(
            "POST",
            f"/mls/associations/{association_id}/citations/{citation_id}/donate-credit",
            {"amount_cents": amount_cents}, headers)

    # --- fine schedules ---
    def create_fine_schedule(self, association_id, payload, headers):
        return self._request("POST", f"/mls/associations/{association_id}/fine-schedules",
                             payload, headers)

    def list_fine_schedules(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/fine-schedules",
                             headers=headers, params=params)

    def retire_fine_schedule(self, association_id, schedule_id, headers):
        return self._request(
            "POST",
            f"/mls/associations/{association_id}/fine-schedules/{schedule_id}/retire",
            {}, headers)

    # --- ethics cases ---
    def create_ethics_case(self, association_id, payload, headers):
        return self._request("POST", f"/mls/associations/{association_id}/ethics-cases",
                             payload, headers)

    def get_ethics_case(self, association_id, case_id, headers):
        return self._request(
            "GET", f"/mls/associations/{association_id}/ethics-cases/{case_id}",
            headers=headers)

    def list_ethics_cases(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/ethics-cases",
                             headers=headers, params=params)

    def screen_ethics_case(self, association_id, case_id, outcome, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/ethics-cases/{case_id}/screen",
            {"outcome": outcome}, headers)

    def appeal_ethics_case(self, association_id, case_id, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/ethics-cases/{case_id}/appeal",
            {}, headers)

    def appeal_ruling_ethics_case(self, association_id, case_id, headers):
        return self._request(
            "POST",
            f"/mls/associations/{association_id}/ethics-cases/{case_id}/appeal-ruling",
            {}, headers)

    # --- arbitration cases ---
    def create_arbitration_case(self, association_id, payload, headers):
        return self._request("POST", f"/mls/associations/{association_id}/arbitration-cases",
                             payload, headers)

    def get_arbitration_case(self, association_id, case_id, headers):
        return self._request(
            "GET", f"/mls/associations/{association_id}/arbitration-cases/{case_id}",
            headers=headers)

    def list_arbitration_cases(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/arbitration-cases",
                             headers=headers, params=params)

    def record_mediation_outcome(self, association_id, case_id, outcome, headers):
        return self._request(
            "POST",
            f"/mls/associations/{association_id}/arbitration-cases/{case_id}/mediation-outcome",
            {"outcome": outcome}, headers)

    # --- hearing panels ---
    def convene_hearing_panel(self, association_id, case_type, case_id, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/hearing-panels",
            {"case_type": case_type, "case_id": case_id}, headers)

    def get_hearing_panel(self, association_id, panel_id, headers):
        return self._request(
            "GET", f"/mls/associations/{association_id}/hearing-panels/{panel_id}",
            headers=headers)

    def list_hearing_panels(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/hearing-panels",
                             headers=headers, params=params)

    def hold_hearing(self, association_id, panel_id, headers, factor_scores=None):
        payload = {} if factor_scores is None else {"factor_scores": factor_scores}
        return self._request(
            "POST", f"/mls/associations/{association_id}/hearing-panels/{panel_id}/hold-hearing",
            payload, headers)

    def rule_panel(self, association_id, panel_id, decision, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/hearing-panels/{panel_id}/rule",
            {"decision": decision}, headers)

    # --- data licenses ---
    def create_data_license(self, association_id, payload, headers):
        return self._request("POST", f"/mls/associations/{association_id}/data-licenses",
                             payload, headers)

    def get_data_license(self, association_id, license_id, headers):
        return self._request(
            "GET", f"/mls/associations/{association_id}/data-licenses/{license_id}",
            headers=headers)

    def list_data_licenses(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/data-licenses",
                             headers=headers, params=params)

    def activate_data_license(self, association_id, license_id, headers):
        return self._request(
            "POST",
            f"/mls/associations/{association_id}/data-licenses/{license_id}/activate",
            {}, headers)

    def sync_feed(self, association_id, license_id, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/data-licenses/{license_id}/sync-feed",
            {}, headers)

    def audit_feed(self, association_id, license_id, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/data-licenses/{license_id}/audit-feed",
            {}, headers)

    def cure_data_license(self, association_id, license_id, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/data-licenses/{license_id}/cure",
            {}, headers)

    def terminate_data_license(self, association_id, license_id, headers):
        return self._request(
            "POST",
            f"/mls/associations/{association_id}/data-licenses/{license_id}/terminate",
            {}, headers)

    # --- policy revisions ---
    def create_policy_revision(self, association_id, payload, headers):
        return self._request("POST", f"/mls/associations/{association_id}/policy-revisions",
                             payload, headers)

    def get_policy_revision(self, association_id, revision_id, headers):
        return self._request(
            "GET", f"/mls/associations/{association_id}/policy-revisions/{revision_id}",
            headers=headers)

    def list_policy_revisions(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/policy-revisions",
                             headers=headers, params=params)

    # --- consolidations ---
    def create_consolidation(self, survivor_id, payload, headers):
        return self._request("POST", f"/mls/associations/{survivor_id}/consolidations",
                             payload, headers)

    def get_consolidation(self, survivor_id, event_id, headers):
        return self._request(
            "GET", f"/mls/associations/{survivor_id}/consolidations/{event_id}",
            headers=headers)

    def execute_consolidation(self, survivor_id, event_id, headers):
        return self._request(
            "POST", f"/mls/associations/{survivor_id}/consolidations/{event_id}/execute",
            {}, headers)

    def cancel_consolidation(self, survivor_id, event_id, headers):
        return self._request(
            "POST", f"/mls/associations/{survivor_id}/consolidations/{event_id}/cancel",
            {}, headers)

    def list_consolidations(self, association_id, headers, params=None):
        return self._request("GET", f"/mls/associations/{association_id}/consolidations",
                             headers=headers, params=params)

    # --- compliance checkpoint ---
    def run_compliance_checkpoint(self, association_id, headers):
        return self._request(
            "POST", f"/mls/associations/{association_id}/run-compliance-checkpoint",
            {}, headers)


api_client = ApiClient()
