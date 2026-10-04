"""API client: one method per endpoint defined in the PRD (§4 routing table).

The business API is mounted under /supply; the logical-clock test-driving
endpoint lives outside that prefix (PRD §2.4), so its path is unprefixed here.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (outside the /supply prefix, PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/supply/facilities", payload, headers)

    # --- Products and registration ---
    def create_product(self, payload, headers):
        return self._request("POST", "/supply/products", payload, headers)

    def record_registration_event(self, product_id, payload, headers):
        return self._request(
            "POST", f"/supply/products/{product_id}/registration-events", payload, headers
        )

    # --- Manufacturing lots ---
    def create_manufacturing_lot(self, payload, headers):
        return self._request("POST", "/supply/manufacturing-lots", payload, headers)

    def list_manufacturing_lots(self, headers, params=None):
        return self._request("GET", "/supply/manufacturing-lots", headers=headers, params=params)

    def get_manufacturing_lot(self, lot_id, headers):
        return self._request("GET", f"/supply/manufacturing-lots/{lot_id}", headers=headers)

    def record_qa_disposition(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/supply/manufacturing-lots/{lot_id}/qa-disposition", payload, headers
        )

    # --- Sterilization batches ---
    def create_sterilization_batch(self, payload, headers):
        return self._request("POST", "/supply/sterilization-batches", payload, headers)

    def record_sterility_result(self, batch_id, payload, headers):
        return self._request(
            "POST",
            f"/supply/sterilization-batches/{batch_id}/record-sterility-result",
            payload,
            headers,
        )

    # --- Conversion programs ---
    def create_conversion_program(self, payload, headers):
        return self._request("POST", "/supply/conversion-programs", payload, headers)

    def list_conversion_programs(self, headers, params=None):
        return self._request("GET", "/supply/conversion-programs", headers=headers, params=params)

    def get_conversion_program(self, program_id, headers):
        return self._request("GET", f"/supply/conversion-programs/{program_id}", headers=headers)

    def record_review_decision(self, program_id, payload, headers):
        return self._request(
            "POST", f"/supply/conversion-programs/{program_id}/review-decision", payload, headers
        )

    def record_line_item_evaluation(self, program_id, payload, headers):
        return self._request(
            "POST",
            f"/supply/conversion-programs/{program_id}/line-item-evaluations",
            payload,
            headers,
        )

    # --- Tray templates ---
    def create_tray_template(self, payload, headers):
        return self._request("POST", "/supply/tray-templates", payload, headers)

    def list_tray_templates(self, headers, params=None):
        return self._request("GET", "/supply/tray-templates", headers=headers, params=params)

    def get_tray_template(self, tray_id, headers):
        return self._request("GET", f"/supply/tray-templates/{tray_id}", headers=headers)

    def propose_tray_change(self, tray_id, payload, headers):
        return self._request(
            "POST", f"/supply/tray-templates/{tray_id}/propose-change", payload, headers
        )

    def record_approval_decision(self, tray_id, payload, headers):
        return self._request(
            "POST", f"/supply/tray-templates/{tray_id}/approval-decision", payload, headers
        )

    # --- Prime vendor agreements ---
    def create_prime_vendor_agreement(self, payload, headers):
        return self._request("POST", "/supply/prime-vendor-agreements", payload, headers)

    def list_prime_vendor_agreements(self, headers, params=None):
        return self._request(
            "GET", "/supply/prime-vendor-agreements", headers=headers, params=params
        )

    def get_prime_vendor_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/supply/prime-vendor-agreements/{agreement_id}", headers=headers
        )

    # --- Distribution orders ---
    def create_distribution_order(self, payload, headers):
        return self._request("POST", "/supply/distribution-orders", payload, headers)

    def list_agreement_orders(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/supply/prime-vendor-agreements/{agreement_id}/distribution-orders",
            headers=headers,
            params=params,
        )

    def record_fulfillment_event(self, order_id, payload, headers):
        return self._request(
            "POST", f"/supply/distribution-orders/{order_id}/fulfillment-events", payload, headers
        )

    # --- Rebate claims ---
    def create_rebate_claim(self, payload, headers):
        return self._request("POST", "/supply/rebate-claims", payload, headers)

    def list_rebate_claims(self, headers, params=None):
        return self._request("GET", "/supply/rebate-claims", headers=headers, params=params)

    def get_rebate_claim(self, claim_id, headers):
        return self._request("GET", f"/supply/rebate-claims/{claim_id}", headers=headers)

    def record_lifecycle_event(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/supply/rebate-claims/{claim_id}/lifecycle-events", payload, headers
        )

    # --- Supply disruptions ---
    def create_supply_disruption(self, payload, headers):
        return self._request("POST", "/supply/supply-disruptions", payload, headers)

    def list_supply_disruptions(self, headers, params=None):
        return self._request("GET", "/supply/supply-disruptions", headers=headers, params=params)

    def get_supply_disruption(self, disruption_id, headers):
        return self._request("GET", f"/supply/supply-disruptions/{disruption_id}", headers=headers)

    def post_allocation(self, disruption_id, payload, headers):
        return self._request(
            "POST", f"/supply/supply-disruptions/{disruption_id}/allocations", payload, headers
        )

    def post_substitution_request(self, disruption_id, payload, headers):
        return self._request(
            "POST",
            f"/supply/supply-disruptions/{disruption_id}/substitution-requests",
            payload,
            headers,
        )

    # --- Inventory programs ---
    def create_inventory_program(self, payload, headers):
        return self._request("POST", "/supply/inventory-programs", payload, headers)

    def list_inventory_programs(self, headers, params=None):
        return self._request("GET", "/supply/inventory-programs", headers=headers, params=params)

    def get_inventory_program(self, program_id, headers):
        return self._request("GET", f"/supply/inventory-programs/{program_id}", headers=headers)

    def record_stock_event(self, program_id, payload, headers):
        return self._request(
            "POST", f"/supply/inventory-programs/{program_id}/stock-events", payload, headers
        )


api_client = ApiClient()
