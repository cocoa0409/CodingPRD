"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/decking/_clock/set_current_utc", payload, headers)

    # --- plants ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/decking/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/decking/plants/{plant_id}", headers=headers)

    def run_capacity_review(self, plant_id, headers):
        return self._request("POST", f"/decking/plants/{plant_id}/run-capacity-review", {}, headers)

    # --- suppliers / collection programs ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/decking/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/decking/suppliers/{supplier_id}", headers=headers)

    def list_supplier_collection_programs(self, supplier_id, headers, params=None):
        return self._request("GET", f"/decking/suppliers/{supplier_id}/collection-programs", headers=headers, params=params)

    def list_supplier_feedstock_lots(self, supplier_id, headers, params=None):
        return self._request("GET", f"/decking/suppliers/{supplier_id}/feedstock-lots", headers=headers, params=params)

    def create_collection_program(self, payload, headers):
        return self._request("POST", "/decking/collection-programs", payload, headers)

    def get_collection_program(self, program_id, headers):
        return self._request("GET", f"/decking/collection-programs/{program_id}", headers=headers)

    def suspend_collection_program(self, program_id, headers):
        return self._request("POST", f"/decking/collection-programs/{program_id}/suspend", {}, headers)

    def reactivate_collection_program(self, program_id, headers):
        return self._request("POST", f"/decking/collection-programs/{program_id}/reactivate", {}, headers)

    def terminate_collection_program(self, program_id, headers):
        return self._request("POST", f"/decking/collection-programs/{program_id}/terminate", {}, headers)

    # --- feedstock lots ---
    def create_feedstock_lot(self, payload, headers):
        return self._request("POST", "/decking/feedstock-lots", payload, headers)

    def get_feedstock_lot(self, lot_id, headers):
        return self._request("GET", f"/decking/feedstock-lots/{lot_id}", headers=headers)

    def release_feedstock_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/decking/feedstock-lots/{lot_id}/release", payload, headers)

    def reject_feedstock_lot(self, lot_id, headers):
        return self._request("POST", f"/decking/feedstock-lots/{lot_id}/reject", {}, headers)

    # --- formulations ---
    def create_formulation(self, payload, headers):
        return self._request("POST", "/decking/formulations", payload, headers)

    def get_formulation(self, formulation_id, headers):
        return self._request("GET", f"/decking/formulations/{formulation_id}", headers=headers)

    def activate_formulation(self, formulation_id, headers):
        return self._request("POST", f"/decking/formulations/{formulation_id}/activate", {}, headers)

    def revise_formulation(self, formulation_id, payload, headers):
        return self._request("POST", f"/decking/formulations/{formulation_id}/revisions", payload, headers)

    def retire_formulation(self, formulation_id, headers):
        return self._request("POST", f"/decking/formulations/{formulation_id}/retire", {}, headers)

    def list_formulation_product_lines(self, formulation_id, headers, params=None):
        return self._request("GET", f"/decking/formulations/{formulation_id}/product-lines", headers=headers, params=params)

    # --- product lines ---
    def create_product_line(self, payload, headers):
        return self._request("POST", "/decking/product-lines", payload, headers)

    def get_product_line(self, line_id, headers):
        return self._request("GET", f"/decking/product-lines/{line_id}", headers=headers)

    def discontinue_product_line(self, line_id, headers):
        return self._request("POST", f"/decking/product-lines/{line_id}/discontinue", {}, headers)

    def set_repair_support(self, line_id, payload, headers):
        return self._request("POST", f"/decking/product-lines/{line_id}/set-repair-support", payload, headers)

    def sunset_product_line(self, line_id, headers):
        return self._request("POST", f"/decking/product-lines/{line_id}/sunset", {}, headers)

    # --- production runs ---
    def create_production_run(self, plant_id, payload, headers):
        return self._request("POST", f"/decking/plants/{plant_id}/production-runs", payload, headers)

    def get_production_run(self, plant_id, run_id, headers):
        return self._request("GET", f"/decking/plants/{plant_id}/production-runs/{run_id}", headers=headers)

    def get_production_run_by_id(self, run_id, headers):
        return self._request("GET", f"/decking/production-runs/{run_id}", headers=headers)

    def list_production_runs(self, plant_id, headers, params=None):
        return self._request("GET", f"/decking/plants/{plant_id}/production-runs", headers=headers, params=params)

    def list_all_production_runs(self, headers, params=None):
        return self._request("GET", "/decking/production-runs", headers=headers, params=params)

    def start_production_run(self, plant_id, run_id, headers):
        return self._request("POST", f"/decking/plants/{plant_id}/production-runs/{run_id}/start", {}, headers)

    def complete_production_run(self, plant_id, run_id, payload, headers):
        return self._request("POST", f"/decking/plants/{plant_id}/production-runs/{run_id}/complete", payload, headers)

    def cancel_production_run(self, plant_id, run_id, headers):
        return self._request("POST", f"/decking/plants/{plant_id}/production-runs/{run_id}/cancel", {}, headers)

    def list_run_board_lots(self, run_id, headers, params=None):
        return self._request("GET", f"/decking/production-runs/{run_id}/board-lots", headers=headers, params=params)

    # --- board lots ---
    def get_board_lot(self, lot_id, headers):
        return self._request("GET", f"/decking/board-lots/{lot_id}", headers=headers)

    def list_board_lots(self, headers, params=None):
        return self._request("GET", "/decking/board-lots", headers=headers, params=params)

    def list_plant_board_lots(self, plant_id, headers, params=None):
        return self._request("GET", f"/decking/plants/{plant_id}/board-lots", headers=headers, params=params)

    # --- dealers / orders / commitments / allocations ---
    def create_dealer(self, payload, headers):
        return self._request("POST", "/decking/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/decking/dealers/{dealer_id}", headers=headers)

    def list_dealer_shipment_orders(self, dealer_id, headers, params=None):
        return self._request("GET", f"/decking/dealers/{dealer_id}/shipment-orders", headers=headers, params=params)

    def list_dealer_stocking_commitments(self, dealer_id, headers, params=None):
        return self._request("GET", f"/decking/dealers/{dealer_id}/stocking-commitments", headers=headers, params=params)

    def create_shipment_order(self, payload, headers):
        return self._request("POST", "/decking/shipment-orders", payload, headers)

    def get_shipment_order(self, order_id, headers):
        return self._request("GET", f"/decking/shipment-orders/{order_id}", headers=headers)

    def list_shipment_orders(self, headers, params=None):
        return self._request("GET", "/decking/shipment-orders", headers=headers, params=params)

    def confirm_shipment_order(self, order_id, headers):
        return self._request("POST", f"/decking/shipment-orders/{order_id}/confirm", {}, headers)

    def ship_shipment_order(self, order_id, headers):
        return self._request("POST", f"/decking/shipment-orders/{order_id}/ship", {}, headers)

    def deliver_shipment_order(self, order_id, headers):
        return self._request("POST", f"/decking/shipment-orders/{order_id}/deliver", {}, headers)

    def cancel_shipment_order(self, order_id, headers):
        return self._request("POST", f"/decking/shipment-orders/{order_id}/cancel", {}, headers)

    def create_stocking_commitment(self, payload, headers):
        return self._request("POST", "/decking/stocking-commitments", payload, headers)

    def get_stocking_commitment(self, commitment_id, headers):
        return self._request("GET", f"/decking/stocking-commitments/{commitment_id}", headers=headers)

    def list_stocking_commitments(self, headers, params=None):
        return self._request("GET", "/decking/stocking-commitments", headers=headers, params=params)

    def close_stocking_commitment_season(self, commitment_id, payload, headers):
        return self._request("POST", f"/decking/stocking-commitments/{commitment_id}/close-season", payload, headers)

    def create_allocation_commitment(self, plant_id, payload, headers):
        return self._request("POST", f"/decking/plants/{plant_id}/allocation-commitments", payload, headers)

    def get_allocation_commitment(self, allocation_id, headers):
        return self._request("GET", f"/decking/allocation-commitments/{allocation_id}", headers=headers)

    def list_plant_allocation_commitments(self, plant_id, headers, params=None):
        return self._request("GET", f"/decking/plants/{plant_id}/allocation-commitments", headers=headers, params=params)

    def list_allocation_commitments(self, headers, params=None):
        return self._request("GET", "/decking/allocation-commitments", headers=headers, params=params)

    def release_allocation_commitment(self, allocation_id, headers):
        return self._request("POST", f"/decking/allocation-commitments/{allocation_id}/release", {}, headers)

    # --- contractor program ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/decking/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/decking/contractors/{contractor_id}", headers=headers)

    def certify_contractor(self, contractor_id, headers):
        return self._request("POST", f"/decking/contractors/{contractor_id}/certify", {}, headers)

    def suspend_contractor(self, contractor_id, headers):
        return self._request("POST", f"/decking/contractors/{contractor_id}/suspend", {}, headers)

    def reinstate_contractor(self, contractor_id, headers):
        return self._request("POST", f"/decking/contractors/{contractor_id}/reinstate", {}, headers)

    def list_contractor_training_records(self, contractor_id, headers, params=None):
        return self._request("GET", f"/decking/contractors/{contractor_id}/training-records", headers=headers, params=params)

    def list_contractor_install_registrations(self, contractor_id, headers, params=None):
        return self._request("GET", f"/decking/contractors/{contractor_id}/install-registrations", headers=headers, params=params)

    def create_training_module(self, payload, headers):
        return self._request("POST", "/decking/training-modules", payload, headers)

    def get_training_module(self, module_id, headers):
        return self._request("GET", f"/decking/training-modules/{module_id}", headers=headers)

    def reversion_training_module(self, module_id, payload, headers):
        return self._request("POST", f"/decking/training-modules/{module_id}/re-version", payload, headers)

    def retire_training_module(self, module_id, headers):
        return self._request("POST", f"/decking/training-modules/{module_id}/retire", {}, headers)

    def create_training_record(self, payload, headers):
        return self._request("POST", "/decking/training-records", payload, headers)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/decking/training-records/{record_id}", headers=headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/decking/training-records", headers=headers, params=params)

    def pass_training_record(self, record_id, headers):
        return self._request("POST", f"/decking/training-records/{record_id}/pass", {}, headers)

    def fail_training_record(self, record_id, headers):
        return self._request("POST", f"/decking/training-records/{record_id}/fail", {}, headers)

    # --- lead referrals ---
    def create_lead_referral(self, payload, headers):
        return self._request("POST", "/decking/lead-referrals", payload, headers)

    def get_lead_referral(self, lead_id, headers):
        return self._request("GET", f"/decking/lead-referrals/{lead_id}", headers=headers)

    def list_lead_referrals(self, headers, params=None):
        return self._request("GET", "/decking/lead-referrals", headers=headers, params=params)

    def assign_lead_referral(self, lead_id, headers):
        return self._request("POST", f"/decking/lead-referrals/{lead_id}/assign", {}, headers)

    def decline_lead_referral(self, lead_id, headers):
        return self._request("POST", f"/decking/lead-referrals/{lead_id}/decline", {}, headers)

    # --- install registrations ---
    def create_install_registration(self, payload, headers):
        return self._request("POST", "/decking/install-registrations", payload, headers)

    def get_install_registration(self, registration_id, headers):
        return self._request("GET", f"/decking/install-registrations/{registration_id}", headers=headers)

    def list_install_registrations(self, headers, params=None):
        return self._request("GET", "/decking/install-registrations", headers=headers, params=params)

    def mark_registration_installed(self, registration_id, headers):
        return self._request("POST", f"/decking/install-registrations/{registration_id}/mark-installed", {}, headers)

    def activate_warranty(self, registration_id, headers):
        return self._request("POST", f"/decking/install-registrations/{registration_id}/activate-warranty", {}, headers)

    def cancel_install_registration(self, registration_id, headers):
        return self._request("POST", f"/decking/install-registrations/{registration_id}/cancel", {}, headers)

    def list_registration_warranty_claims(self, registration_id, headers, params=None):
        return self._request("GET", f"/decking/install-registrations/{registration_id}/warranty-claims", headers=headers, params=params)

    # --- warranty claims / samples ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/decking/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/decking/warranty-claims/{claim_id}", headers=headers)

    def request_claim_sample(self, claim_id, headers):
        return self._request("POST", f"/decking/warranty-claims/{claim_id}/request-sample", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/decking/warranty-claims/{claim_id}/adjudicate", payload, headers)

    def list_claim_samples(self, claim_id, headers, params=None):
        return self._request("GET", f"/decking/warranty-claims/{claim_id}/samples", headers=headers, params=params)

    def get_claim_sample(self, sample_id, headers):
        return self._request("GET", f"/decking/claim-samples/{sample_id}", headers=headers)

    def receive_claim_sample(self, sample_id, headers):
        return self._request("POST", f"/decking/claim-samples/{sample_id}/receive", {}, headers)

    def review_claim_sample(self, sample_id, payload, headers):
        return self._request("POST", f"/decking/claim-samples/{sample_id}/review", payload, headers)

    # --- merchandising ---
    def create_sample_kit(self, payload, headers):
        return self._request("POST", "/decking/sample-kits", payload, headers)

    def get_sample_kit(self, kit_id, headers):
        return self._request("GET", f"/decking/sample-kits/{kit_id}", headers=headers)

    def list_sample_kits(self, headers, params=None):
        return self._request("GET", "/decking/sample-kits", headers=headers, params=params)

    def list_dealer_sample_kits(self, dealer_id, headers, params=None):
        return self._request("GET", f"/decking/dealers/{dealer_id}/sample-kits", headers=headers, params=params)

    def deliver_sample_kit(self, kit_id, headers):
        return self._request("POST", f"/decking/sample-kits/{kit_id}/deliver", {}, headers)

    def retire_sample_kit(self, kit_id, headers):
        return self._request("POST", f"/decking/sample-kits/{kit_id}/retire", {}, headers)

    def create_color_chip_request(self, payload, headers):
        return self._request("POST", "/decking/color-chip-requests", payload, headers)

    def get_color_chip_request(self, chip_id, headers):
        return self._request("GET", f"/decking/color-chip-requests/{chip_id}", headers=headers)

    def list_color_chip_requests(self, headers, params=None):
        return self._request("GET", "/decking/color-chip-requests", headers=headers, params=params)

    def list_dealer_color_chip_requests(self, dealer_id, headers, params=None):
        return self._request("GET", f"/decking/dealers/{dealer_id}/color-chip-requests", headers=headers, params=params)

    def fulfill_color_chip_request(self, chip_id, headers):
        return self._request("POST", f"/decking/color-chip-requests/{chip_id}/fulfill", {}, headers)

    def cancel_color_chip_request(self, chip_id, headers):
        return self._request("POST", f"/decking/color-chip-requests/{chip_id}/cancel", {}, headers)

    # --- price books ---
    def create_price_book(self, payload, headers):
        return self._request("POST", "/decking/price-books", payload, headers)

    def get_price_book(self, price_book_id, headers):
        return self._request("GET", f"/decking/price-books/{price_book_id}", headers=headers)


api_client = ApiClient()
