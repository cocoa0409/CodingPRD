"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Shippers
    # ------------------------------------------------------------------
    def create_shipper(self, payload, headers):
        return self._request("POST", "/shippers", payload, headers)

    def get_shipper(self, shipper_id, headers):
        return self._request("GET", f"/shippers/{shipper_id}", headers=headers)

    def list_shippers(self, headers, params=None):
        return self._request("GET", "/shippers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Commodities
    # ------------------------------------------------------------------
    def create_commodity(self, payload, headers):
        return self._request("POST", "/commodities", payload, headers)

    def get_commodity(self, commodity_id, headers):
        return self._request("GET", f"/commodities/{commodity_id}", headers=headers)

    def list_commodities(self, headers, params=None):
        return self._request("GET", "/commodities", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Prior-cargo compatibility matrix
    # ------------------------------------------------------------------
    def create_compatibility_rule(self, payload, headers):
        return self._request("POST", "/compatibility-rules", payload, headers)

    def list_compatibility_rules(self, headers, params=None):
        return self._request("GET", "/compatibility-rules", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Tariff filings
    # ------------------------------------------------------------------
    def create_tariff_filing(self, payload, headers):
        return self._request("POST", "/tariff-filings", payload, headers)

    def file_tariff_filing(self, tariff_filing_id, headers):
        return self._request(
            "POST", f"/tariff-filings/{tariff_filing_id}/file", {}, headers)

    def effectuate_tariff_filing(self, tariff_filing_id, headers):
        return self._request(
            "POST", f"/tariff-filings/{tariff_filing_id}/effectuate", {}, headers)

    def get_tariff_filing(self, tariff_filing_id, headers):
        return self._request("GET", f"/tariff-filings/{tariff_filing_id}", headers=headers)

    def list_tariff_filings(self, headers, params=None):
        return self._request("GET", "/tariff-filings", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Fuel index
    # ------------------------------------------------------------------
    def create_fuel_index_posting(self, payload, headers):
        return self._request("POST", "/fuel-index-postings", payload, headers)

    def list_fuel_index_postings(self, headers, params=None):
        return self._request("GET", "/fuel-index-postings", headers=headers, params=params)

    # ------------------------------------------------------------------
    # River stage
    # ------------------------------------------------------------------
    def create_river_stage_reading(self, payload, headers):
        return self._request("POST", "/river-stage-readings", payload, headers)

    def list_river_stage_readings(self, headers, params=None):
        return self._request("GET", "/river-stage-readings", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Barges
    # ------------------------------------------------------------------
    def create_barge(self, payload, headers):
        return self._request("POST", "/barges", payload, headers)

    def get_barge(self, barge_id, headers):
        return self._request("GET", f"/barges/{barge_id}", headers=headers)

    def list_barges(self, headers, params=None):
        return self._request("GET", "/barges", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Cleaning orders
    # ------------------------------------------------------------------
    def create_cleaning_order(self, barge_id, payload, headers):
        return self._request(
            "POST", f"/barges/{barge_id}/cleaning-orders", payload, headers)

    def start_cleaning_order(self, cleaning_order_id, headers):
        return self._request(
            "POST", f"/cleaning-orders/{cleaning_order_id}/start", {}, headers)

    def complete_cleaning_order(self, cleaning_order_id, payload, headers):
        return self._request(
            "POST", f"/cleaning-orders/{cleaning_order_id}/complete", payload, headers)

    def get_cleaning_order(self, cleaning_order_id, headers):
        return self._request(
            "GET", f"/cleaning-orders/{cleaning_order_id}", headers=headers)

    def list_cleaning_orders(self, headers, params=None):
        return self._request("GET", "/cleaning-orders", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Fleeting berths and assignments
    # ------------------------------------------------------------------
    def create_fleeting_berth(self, payload, headers):
        return self._request("POST", "/fleeting-berths", payload, headers)

    def get_fleeting_berth(self, fleeting_berth_id, headers):
        return self._request(
            "GET", f"/fleeting-berths/{fleeting_berth_id}", headers=headers)

    def list_fleeting_berths(self, headers, params=None):
        return self._request("GET", "/fleeting-berths", headers=headers, params=params)

    def create_fleeting_assignment(self, payload, headers):
        return self._request("POST", "/fleeting-assignments", payload, headers)

    def release_fleeting_assignment(self, fleeting_assignment_id, payload, headers):
        return self._request(
            "POST", f"/fleeting-assignments/{fleeting_assignment_id}/release",
            payload, headers)

    def cancel_fleeting_assignment(self, fleeting_assignment_id, headers):
        return self._request(
            "POST", f"/fleeting-assignments/{fleeting_assignment_id}/cancel", {}, headers)

    def get_fleeting_assignment(self, fleeting_assignment_id, headers):
        return self._request(
            "GET", f"/fleeting-assignments/{fleeting_assignment_id}", headers=headers)

    def list_fleeting_assignments(self, headers, params=None):
        return self._request("GET", "/fleeting-assignments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Locks
    # ------------------------------------------------------------------
    def create_lock(self, payload, headers):
        return self._request("POST", "/locks", payload, headers)

    def set_lock_status(self, lock_id, payload, headers):
        return self._request("POST", f"/locks/{lock_id}/set-status", payload, headers)

    def get_lock(self, lock_id, headers):
        return self._request("GET", f"/locks/{lock_id}", headers=headers)

    def list_locks(self, headers, params=None):
        return self._request("GET", "/locks", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Lock reservations
    # ------------------------------------------------------------------
    def create_lock_reservation(self, payload, headers):
        return self._request("POST", "/lock-reservations", payload, headers)

    def grant_lock_reservation(self, lock_reservation_id, headers):
        return self._request(
            "POST", f"/lock-reservations/{lock_reservation_id}/grant", {}, headers)

    def deny_lock_reservation(self, lock_reservation_id, payload, headers):
        return self._request(
            "POST", f"/lock-reservations/{lock_reservation_id}/deny", payload, headers)

    def reschedule_lock_reservation(self, lock_reservation_id, payload, headers):
        return self._request(
            "POST", f"/lock-reservations/{lock_reservation_id}/reschedule",
            payload, headers)

    def enter_chamber(self, lock_reservation_id, payload, headers):
        return self._request(
            "POST", f"/lock-reservations/{lock_reservation_id}/enter-chamber",
            payload, headers)

    def clear_chamber(self, lock_reservation_id, payload, headers):
        return self._request(
            "POST", f"/lock-reservations/{lock_reservation_id}/clear", payload, headers)

    def cancel_lock_reservation(self, lock_reservation_id, headers):
        return self._request(
            "POST", f"/lock-reservations/{lock_reservation_id}/cancel", {}, headers)

    def get_lock_reservation(self, lock_reservation_id, headers):
        return self._request(
            "GET", f"/lock-reservations/{lock_reservation_id}", headers=headers)

    def list_lock_reservations(self, headers, params=None):
        return self._request("GET", "/lock-reservations", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Tows
    # ------------------------------------------------------------------
    def create_tow(self, payload, headers):
        return self._request("POST", "/tows", payload, headers)

    def create_barge_assignment(self, tow_id, payload, headers):
        return self._request(
            "POST", f"/tows/{tow_id}/barge-assignments", payload, headers)

    def seal_tow(self, tow_id, headers):
        return self._request("POST", f"/tows/{tow_id}/seal", {}, headers)

    def depart_tow(self, tow_id, payload, headers):
        return self._request("POST", f"/tows/{tow_id}/depart", payload, headers)

    def resume_tow(self, tow_id, headers):
        return self._request("POST", f"/tows/{tow_id}/resume", {}, headers)

    def arrive_tow(self, tow_id, payload, headers):
        return self._request("POST", f"/tows/{tow_id}/arrive", payload, headers)

    def break_up_tow(self, tow_id, headers):
        return self._request("POST", f"/tows/{tow_id}/break-up", {}, headers)

    def adjust_tow_load(self, tow_id, payload, headers):
        return self._request("POST", f"/tows/{tow_id}/adjust-load", payload, headers)

    def get_tow(self, tow_id, headers):
        return self._request("GET", f"/tows/{tow_id}", headers=headers)

    def list_tows(self, headers, params=None):
        return self._request("GET", "/tows", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Barge assignments
    # ------------------------------------------------------------------
    def drop_barge_assignment(self, barge_assignment_id, headers):
        return self._request(
            "POST", f"/barge-assignments/{barge_assignment_id}/drop", {}, headers)

    def record_barge_arrival(self, barge_assignment_id, payload, headers):
        return self._request(
            "POST", f"/barge-assignments/{barge_assignment_id}/record-arrival",
            payload, headers)

    def start_unload(self, barge_assignment_id, payload, headers):
        return self._request(
            "POST", f"/barge-assignments/{barge_assignment_id}/start-unload",
            payload, headers)

    def finish_unload(self, barge_assignment_id, payload, headers):
        return self._request(
            "POST", f"/barge-assignments/{barge_assignment_id}/finish-unload",
            payload, headers)

    def get_barge_assignment(self, barge_assignment_id, headers):
        return self._request(
            "GET", f"/barge-assignments/{barge_assignment_id}", headers=headers)

    def list_barge_assignments(self, headers, params=None):
        return self._request("GET", "/barge-assignments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Freight contracts
    # ------------------------------------------------------------------
    def create_freight_contract(self, payload, headers):
        return self._request("POST", "/freight-contracts", payload, headers)

    def book_freight_contract(self, freight_contract_id, headers):
        return self._request(
            "POST", f"/freight-contracts/{freight_contract_id}/book", {}, headers)

    def activate_freight_contract(self, freight_contract_id, headers):
        return self._request(
            "POST", f"/freight-contracts/{freight_contract_id}/activate", {}, headers)

    def cancel_freight_contract(self, freight_contract_id, payload, headers):
        return self._request(
            "POST", f"/freight-contracts/{freight_contract_id}/cancel", payload, headers)

    def issue_invoice(self, freight_contract_id, payload, headers):
        return self._request(
            "POST", f"/freight-contracts/{freight_contract_id}/issue-invoice",
            payload, headers)

    def mark_contract_paid(self, freight_contract_id, payload, headers):
        return self._request(
            "POST", f"/freight-contracts/{freight_contract_id}/mark-paid",
            payload, headers)

    def get_freight_contract(self, freight_contract_id, headers):
        return self._request(
            "GET", f"/freight-contracts/{freight_contract_id}", headers=headers)

    def get_charge_breakdown(self, freight_contract_id, headers, params=None):
        return self._request(
            "GET", f"/freight-contracts/{freight_contract_id}/charge-breakdown",
            headers=headers, params=params)

    def list_freight_contracts(self, headers, params=None):
        return self._request("GET", "/freight-contracts", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Cargo claims
    # ------------------------------------------------------------------
    def create_cargo_claim(self, payload, headers):
        return self._request("POST", "/cargo-claims", payload, headers)

    def begin_claim_review(self, cargo_claim_id, headers):
        return self._request(
            "POST", f"/cargo-claims/{cargo_claim_id}/begin-review", {}, headers)

    def request_claim_info(self, cargo_claim_id, payload, headers):
        return self._request(
            "POST", f"/cargo-claims/{cargo_claim_id}/request-info", payload, headers)

    def resume_claim_review(self, cargo_claim_id, payload, headers):
        return self._request(
            "POST", f"/cargo-claims/{cargo_claim_id}/resume-review", payload, headers)

    def assess_cargo_claim(self, cargo_claim_id, headers):
        return self._request(
            "POST", f"/cargo-claims/{cargo_claim_id}/assess", {}, headers)

    def approve_cargo_claim(self, cargo_claim_id, headers):
        return self._request(
            "POST", f"/cargo-claims/{cargo_claim_id}/approve", {}, headers)

    def deny_cargo_claim(self, cargo_claim_id, payload, headers):
        return self._request(
            "POST", f"/cargo-claims/{cargo_claim_id}/deny", payload, headers)

    def withdraw_cargo_claim(self, cargo_claim_id, headers):
        return self._request(
            "POST", f"/cargo-claims/{cargo_claim_id}/withdraw", {}, headers)

    def get_cargo_claim(self, cargo_claim_id, headers):
        return self._request("GET", f"/cargo-claims/{cargo_claim_id}", headers=headers)

    def list_cargo_claims(self, headers, params=None):
        return self._request("GET", "/cargo-claims", headers=headers, params=params)


api_client = ApiClient()
