"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- stations ---
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    # --- union agreements ---
    def create_union_agreement(self, payload, headers):
        return self._request("POST", "/union-agreements", payload, headers)

    def list_union_agreements(self, headers, params=None):
        return self._request("GET", "/union-agreements", headers=headers, params=params)

    def get_union_agreement(self, agreement_id, headers):
        return self._request("GET", f"/union-agreements/{agreement_id}", headers=headers)

    # --- hotel vendors ---
    def create_hotel_vendor(self, payload, headers):
        return self._request("POST", "/hotel-vendors", payload, headers)

    def list_hotel_vendors(self, headers, params=None):
        return self._request("GET", "/hotel-vendors", headers=headers, params=params)

    def get_hotel_vendor(self, vendor_id, headers):
        return self._request("GET", f"/hotel-vendors/{vendor_id}", headers=headers)

    # --- RFP cycles ---
    def create_rfp_cycle(self, payload, headers):
        return self._request("POST", "/rfp-cycles", payload, headers)

    def list_rfp_cycles(self, headers, params=None):
        return self._request("GET", "/rfp-cycles", headers=headers, params=params)

    def get_rfp_cycle(self, cycle_id, headers):
        return self._request("GET", f"/rfp-cycles/{cycle_id}", headers=headers)

    def open_rfp_cycle(self, cycle_id, headers):
        return self._request("POST", f"/rfp-cycles/{cycle_id}/open", headers=headers)

    def close_rfp_cycle(self, cycle_id, headers):
        return self._request("POST", f"/rfp-cycles/{cycle_id}/close", headers=headers)

    def open_negotiation(self, cycle_id, headers):
        return self._request("POST", f"/rfp-cycles/{cycle_id}/open-negotiation", headers=headers)

    def award_rfp_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/rfp-cycles/{cycle_id}/award", payload, headers)

    def cancel_rfp_cycle(self, cycle_id, headers):
        return self._request("POST", f"/rfp-cycles/{cycle_id}/cancel", headers=headers)

    # --- proposals ---
    def submit_proposal(self, cycle_id, payload, headers):
        return self._request("POST", f"/rfp-cycles/{cycle_id}/proposals", payload, headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/rfp-proposals", headers=headers, params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/rfp-proposals/{proposal_id}", headers=headers)

    def shortlist_proposal(self, proposal_id, headers):
        return self._request("POST", f"/rfp-proposals/{proposal_id}/shortlist", headers=headers)

    def reject_proposal(self, proposal_id, headers):
        return self._request("POST", f"/rfp-proposals/{proposal_id}/reject", headers=headers)

    def withdraw_proposal(self, proposal_id, headers):
        return self._request("POST", f"/rfp-proposals/{proposal_id}/withdraw", headers=headers)

    def counter_offer_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/rfp-proposals/{proposal_id}/counter-offer", payload, headers)

    # --- contracts ---
    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", headers=headers)

    def remediate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/remediate", headers=headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", headers=headers)

    # --- layover requirements ---
    def create_layover_requirement(self, payload, headers):
        return self._request("POST", "/layover-requirements", payload, headers)

    def list_layover_requirements(self, headers, params=None):
        return self._request("GET", "/layover-requirements", headers=headers, params=params)

    def get_layover_requirement(self, layover_id, headers):
        return self._request("GET", f"/layover-requirements/{layover_id}", headers=headers)

    def book_layover(self, layover_id, payload, headers):
        return self._request("POST", f"/layover-requirements/{layover_id}/book", payload, headers)

    def distressed_book_layover(self, layover_id, payload, headers):
        return self._request("POST", f"/layover-requirements/{layover_id}/distressed-book", payload, headers)

    def cancel_layover(self, layover_id, headers):
        return self._request("POST", f"/layover-requirements/{layover_id}/cancel", headers=headers)

    def create_transport_trip(self, layover_id, payload, headers):
        return self._request("POST", f"/layover-requirements/{layover_id}/transport-trips", payload, headers)

    # --- allocations ---
    def list_allocations(self, headers, params=None):
        return self._request("GET", "/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    def confirm_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/confirm", headers=headers)

    def check_in_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/check-in", headers=headers)

    def no_show_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/no-show", headers=headers)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/release", headers=headers)

    # --- transport trips ---
    def list_transport_trips(self, headers, params=None):
        return self._request("GET", "/transport-trips", headers=headers, params=params)

    def get_transport_trip(self, trip_id, headers):
        return self._request("GET", f"/transport-trips/{trip_id}", headers=headers)

    def dispatch_trip(self, trip_id, headers):
        return self._request("POST", f"/transport-trips/{trip_id}/dispatch", headers=headers)

    def complete_trip(self, trip_id, headers):
        return self._request("POST", f"/transport-trips/{trip_id}/complete", headers=headers)

    # --- crew feedback ---
    def create_crew_feedback(self, payload, headers):
        return self._request("POST", "/crew-feedback", payload, headers)

    def list_crew_feedback(self, headers, params=None):
        return self._request("GET", "/crew-feedback", headers=headers, params=params)

    def get_crew_feedback(self, feedback_id, headers):
        return self._request("GET", f"/crew-feedback/{feedback_id}", headers=headers)

    # --- audits ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def start_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/start", headers=headers)

    def close_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/close", payload, headers)

    # --- invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def reconcile_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/reconcile", headers=headers)

    def approve_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/approve", headers=headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", headers=headers)

    def re_reconcile_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/re-reconcile", headers=headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/mark-paid", headers=headers)

    def reject_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/reject", headers=headers)


api_client = ApiClient()
