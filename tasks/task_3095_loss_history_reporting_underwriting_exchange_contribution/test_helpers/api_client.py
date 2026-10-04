"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- exchange rules ---
    def create_exchange_rules(self, payload, headers):
        return self._request("POST", "/exchange-rules", payload, headers)

    def get_exchange_rules(self, headers):
        return self._request("GET", "/exchange-rules", headers=headers)

    def patch_exchange_rules(self, payload, headers):
        return self._request("PATCH", "/exchange-rules", payload, headers)

    # --- carriers ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    def withdraw_carrier(self, carrier_id, headers):
        return self._request("POST", f"/carriers/{carrier_id}/withdraw", None, headers)

    # --- contribution batches ---
    def create_batch(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/batches", payload, headers)

    def list_carrier_batches(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def void_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/void", None, headers)

    def list_batch_claims(self, batch_id, headers, params=None):
        return self._request("GET", f"/batches/{batch_id}/claims", headers=headers, params=params)

    # --- loss claims ---
    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def list_carrier_claims(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/claims", headers=headers, params=params)

    def list_consumer_claims(self, consumer_id, headers, params=None):
        return self._request("GET", f"/consumers/{consumer_id}/claims", headers=headers, params=params)

    def create_claim_amendment(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/amendments", payload, headers)

    def list_claim_amendments(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}/amendments", headers=headers)

    def list_claim_disputes(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/disputes", headers=headers, params=params)

    def list_claim_report_entries(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/report-entries", headers=headers, params=params)

    # --- consumers ---
    def create_consumer(self, payload, headers):
        return self._request("POST", "/consumers", payload, headers)

    def get_consumer(self, consumer_id, headers):
        return self._request("GET", f"/consumers/{consumer_id}", headers=headers)

    def list_consumers(self, headers, params=None):
        return self._request("GET", "/consumers", headers=headers, params=params)

    def get_consumer_file(self, consumer_id, headers):
        return self._request("GET", f"/consumers/{consumer_id}/file", headers=headers)

    def freeze_consumer(self, consumer_id, headers):
        return self._request("POST", f"/consumers/{consumer_id}/freeze", None, headers)

    def list_consumer_reports(self, consumer_id, headers, params=None):
        return self._request("GET", f"/consumers/{consumer_id}/reports", headers=headers, params=params)

    def list_consumer_report_entries(self, consumer_id, headers, params=None):
        return self._request("GET", f"/consumers/{consumer_id}/report-entries", headers=headers, params=params)

    def list_consumer_inquiries(self, consumer_id, headers, params=None):
        return self._request("GET", f"/consumers/{consumer_id}/inquiries", headers=headers, params=params)

    def list_consumer_disputes(self, consumer_id, headers, params=None):
        return self._request("GET", f"/consumers/{consumer_id}/disputes", headers=headers, params=params)

    def create_dispute(self, consumer_id, payload, headers):
        return self._request("POST", f"/consumers/{consumer_id}/disputes", payload, headers)

    def list_consumer_notices(self, consumer_id, headers, params=None):
        return self._request("GET", f"/consumers/{consumer_id}/adverse-action-notices", headers=headers, params=params)

    def list_consumer_audit_events(self, consumer_id, headers, params=None):
        return self._request("GET", f"/consumers/{consumer_id}/audit-events", headers=headers, params=params)

    # --- inquiries / reports ---
    def create_inquiry(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/inquiries", payload, headers)

    def list_carrier_inquiries(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/inquiries", headers=headers, params=params)

    def get_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/inquiries/{inquiry_id}", headers=headers)

    def list_inquiries(self, headers, params=None):
        return self._request("GET", "/inquiries", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/reports", headers=headers, params=params)

    def list_carrier_reports(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/reports", headers=headers, params=params)

    def list_report_entries(self, headers, params=None):
        return self._request("GET", "/report-entries", headers=headers, params=params)

    def get_report_entry(self, entry_id, headers):
        return self._request("GET", f"/report-entries/{entry_id}", headers=headers)

    def list_report_entries_for_report(self, report_id, headers, params=None):
        return self._request("GET", f"/reports/{report_id}/entries", headers=headers, params=params)

    def list_report_notices(self, report_id, headers, params=None):
        return self._request("GET", f"/reports/{report_id}/adverse-action-notices", headers=headers, params=params)

    def list_carrier_report_entries(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/report-entries", headers=headers, params=params)

    # --- disputes ---
    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def begin_reinvestigation(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/begin-reinvestigation", None, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    # --- adverse action notices ---
    def create_notice(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/adverse-action-notices", payload, headers)

    def list_carrier_notices(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/adverse-action-notices", headers=headers, params=params)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/adverse-action-notices", headers=headers, params=params)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/adverse-action-notices/{notice_id}", headers=headers)

    def send_notice(self, notice_id, headers):
        return self._request("POST", f"/adverse-action-notices/{notice_id}/send", None, headers)

    def acknowledge_notice(self, notice_id, headers):
        return self._request("POST", f"/adverse-action-notices/{notice_id}/acknowledge", None, headers)

    def cancel_notice(self, notice_id, headers):
        return self._request("POST", f"/adverse-action-notices/{notice_id}/cancel", None, headers)

    # --- audit ---
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    def get_audit_event(self, event_id, headers):
        return self._request("GET", f"/audit-events/{event_id}", headers=headers)

    def list_carrier_audit_events(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/audit-events", headers=headers, params=params)


api_client = ApiClient()
