"""API client: one method per endpoint in the public surface."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin wrapper over GenericApiClient._request, one method per endpoint."""

    # ─── Clock / health ───────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def health(self, headers):
        return self._request("GET", "/_health", headers=headers)

    # ─── Manufacturers ────────────────────────────────
    def create_manufacturer(self, payload, headers):
        return self._request("POST", "/manufacturers", payload, headers)

    def get_manufacturer(self, manufacturer_id, headers):
        return self._request("GET", f"/manufacturers/{manufacturer_id}", headers=headers)

    def list_manufacturers(self, headers, params=None):
        return self._request("GET", "/manufacturers", headers=headers, params=params)

    def set_manufacturer_state(self, manufacturer_id, to_status, headers):
        return self._request("POST", f"/manufacturers/{manufacturer_id}/state",
                             {"to_status": to_status}, headers)

    def list_manufacturer_drug_prices_of_manufacturer(self, manufacturer_id, headers):
        return self._request("GET", f"/manufacturers/{manufacturer_id}/drug-prices",
                             headers=headers)

    # ─── Drugs ────────────────────────────────────────
    def create_drug(self, payload, headers):
        return self._request("POST", "/drugs", payload, headers)

    def get_drug(self, drug_id, headers):
        return self._request("GET", f"/drugs/{drug_id}", headers=headers)

    def list_drugs(self, headers, params=None):
        return self._request("GET", "/drugs", headers=headers, params=params)

    def stock_check(self, drug_id, headers):
        return self._request("GET", f"/formularies/{drug_id}/stock-check", headers=headers)

    def supply_summary(self, drug_id, headers):
        return self._request("GET", f"/formularies/{drug_id}/supply-summary", headers=headers)

    def expansion_score(self, drug_id, headers):
        return self._request("GET", f"/formularies/{drug_id}/expansion-score", headers=headers)

    def expand_formulary(self, drug_id, headers):
        return self._request("POST", f"/formularies/{drug_id}/expansion", {}, headers)

    def delist_formulary(self, drug_id, headers):
        return self._request("POST", f"/formularies/{drug_id}/delist", {}, headers)

    # ─── Manufacturer drug prices ─────────────────────
    def create_price(self, payload, headers):
        return self._request("POST", "/manufacturer-drug-prices", payload, headers)

    def get_price(self, price_id, headers):
        return self._request("GET", f"/manufacturer-drug-prices/{price_id}", headers=headers)

    def list_prices(self, headers, params=None):
        return self._request("GET", "/manufacturer-drug-prices", headers=headers, params=params)

    def list_drug_prices_of_drug(self, drug_id, headers):
        return self._request("GET", f"/drugs/{drug_id}/manufacturer-drug-prices", headers=headers)

    def activate_price(self, price_id, headers):
        return self._request("POST", f"/manufacturer-drug-prices/{price_id}/activation", {}, headers)

    def move_price_sourcing(self, price_id, to_sourcing_status, headers):
        return self._request("POST", f"/manufacturer-drug-prices/{price_id}/sourcing",
                             {"to_sourcing_status": to_sourcing_status}, headers)

    def revoke_price(self, price_id, headers):
        return self._request("POST", f"/manufacturer-drug-prices/{price_id}/revocation", {}, headers)

    def list_orders_of_price(self, price_id, headers):
        return self._request("GET", f"/manufacturer-drug-prices/{price_id}/orders", headers=headers)

    # ─── Pharmacies and licences ──────────────────────
    def create_pharmacy(self, payload, headers):
        return self._request("POST", "/pharmacies", payload, headers)

    def get_pharmacy(self, pharmacy_id, headers):
        return self._request("GET", f"/pharmacies/{pharmacy_id}", headers=headers)

    def list_pharmacies(self, headers, params=None):
        return self._request("GET", "/pharmacies", headers=headers, params=params)

    def file_license(self, pharmacy_id, payload, headers):
        return self._request("POST", f"/pharmacies/{pharmacy_id}/licenses", payload, headers)

    def list_licenses(self, pharmacy_id, headers, params=None):
        return self._request("GET", f"/pharmacies/{pharmacy_id}/licenses",
                             headers=headers, params=params)

    def get_license(self, pharmacy_id, license_id, headers):
        return self._request("GET", f"/pharmacies/{pharmacy_id}/licenses/{license_id}",
                             headers=headers)

    def set_license_state(self, pharmacy_id, license_id, to_status, headers):
        return self._request("POST",
                             f"/pharmacies/{pharmacy_id}/licenses/{license_id}/state",
                             {"to_status": to_status}, headers)

    def verify_license(self, pharmacy_id, license_id, headers):
        return self._request("POST",
                             f"/pharmacies/{pharmacy_id}/licenses/{license_id}/verification",
                             {}, headers)

    def list_orders_of_pharmacy(self, pharmacy_id, headers):
        return self._request("GET", f"/pharmacies/{pharmacy_id}/orders", headers=headers)

    # ─── Patients and prescribers ─────────────────────
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def create_prescriber(self, payload, headers):
        return self._request("POST", "/prescribers", payload, headers)

    def get_prescriber(self, prescriber_id, headers):
        return self._request("GET", f"/prescribers/{prescriber_id}", headers=headers)

    def set_prescriber_state(self, prescriber_id, to_status, headers):
        return self._request("POST", f"/prescribers/{prescriber_id}/state",
                             {"to_status": to_status}, headers)

    # ─── Prescriptions ────────────────────────────────
    def create_prescription(self, payload, headers):
        return self._request("POST", "/prescriptions", payload, headers)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/prescriptions/{prescription_id}", headers=headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/prescriptions", headers=headers, params=params)

    def list_prescriptions_of_drug(self, drug_id, headers):
        return self._request("GET", f"/drugs/{drug_id}/prescriptions", headers=headers)

    def list_prescriptions_of_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}/prescriptions", headers=headers)

    def list_prescriptions_of_prescriber(self, prescriber_id, headers):
        return self._request("GET", f"/prescribers/{prescriber_id}/prescriptions", headers=headers)

    def create_intake_request(self, prescription_id, packaged_quantity, headers):
        return self._request("POST", f"/prescriptions/{prescription_id}/intake-requests",
                             {"packaged_quantity": packaged_quantity}, headers)

    def list_intake_requests_of_prescription(self, prescription_id, headers, params=None):
        return self._request("GET", f"/prescriptions/{prescription_id}/intake-requests",
                             headers=headers, params=params)

    def terminate_prescription(self, prescription_id, headers):
        return self._request("POST", f"/prescriptions/{prescription_id}/termination", {}, headers)

    def substitute_prescription(self, prescription_id, payload, headers):
        return self._request("POST", f"/prescriptions/{prescription_id}/substitution",
                             payload, headers)

    # ─── Prescription requests ────────────────────────
    def get_intake_request(self, request_id, headers):
        return self._request("GET", f"/prescription-requests/{request_id}", headers=headers)

    def list_intake_requests(self, headers, params=None):
        return self._request("GET", "/prescription-requests", headers=headers, params=params)

    def review_intake_request(self, request_id, headers):
        return self._request("POST", f"/prescription-requests/{request_id}/review", {}, headers)

    def accept_intake_request(self, request_id, headers):
        return self._request("POST", f"/prescription-requests/{request_id}/acceptance", {}, headers)

    def reject_intake_request(self, request_id, reason_code, headers):
        return self._request("POST", f"/prescription-requests/{request_id}/rejection",
                             {"reason_code": reason_code}, headers)

    def list_orders_of_intake_request(self, request_id, headers):
        return self._request("GET", f"/prescription-requests/{request_id}/orders",
                             headers=headers)

    def list_shipments_of_intake_request(self, request_id, headers):
        return self._request("GET", f"/prescription-requests/{request_id}/shipments",
                             headers=headers)

    # ─── Orders ───────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def list_orders_of_prescription(self, prescription_id, headers):
        return self._request("GET", f"/prescriptions/{prescription_id}/orders",
                             headers=headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/payment", {}, headers)

    def fulfill_order(self, order_id, expected_order_version, headers):
        return self._request("POST", f"/orders/{order_id}/fulfillment",
                             {"expected_order_version": expected_order_version}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/shipping", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/delivery", {}, headers)

    def cancel_order(self, order_id, reason_code, headers):
        return self._request("POST", f"/orders/{order_id}/cancellation",
                             {"reason_code": reason_code}, headers)

    def cancel_order_no_reason(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancellation", {}, headers)

    def list_comparisons_of_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/comparisons", headers=headers)

    def get_order_comparison(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/comparison", headers=headers)

    def refresh_comparison(self, order_id, comparison_id, headers):
        return self._request("POST",
                             f"/orders/{order_id}/comparisons/{comparison_id}/refresh",
                             {}, headers)

    def enable_substantiation(self, order_id, substantiation_id, expected_order_version, headers):
        return self._request("POST", f"/orders/{order_id}/substantiation-enablement",
                             {"substantiation_id": substantiation_id,
                              "expected_order_version": expected_order_version}, headers)

    def disable_substantiation(self, order_id, substantiation_id, headers):
        return self._request("POST", f"/orders/{order_id}/substantiation-disablement",
                             {"substantiation_id": substantiation_id}, headers)

    def list_substantiations_of_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/substantiation-records",
                             headers=headers)

    # ─── Refill authorisations ────────────────────────
    def authorize_refill(self, claim_id, quantity, headers):
        return self._request("POST", f"/claims/{claim_id}/refill-authorizations",
                             {"quantity": quantity}, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim_summary(self, claim_id, headers):
        return self._request("GET", f"/claim-summaries/{claim_id}", headers=headers)

    def list_claims_of_prescription(self, prescription_id, headers):
        return self._request("GET", f"/prescriptions/{prescription_id}/claims", headers=headers)

    # ─── Shipments ────────────────────────────────────
    def list_shipments_of_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/shipments", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment_summary(self, shipment_id, headers):
        return self._request("GET", f"/shipment-summaries/{shipment_id}", headers=headers)

    # ─── Comparison listing ───────────────────────────
    def list_comparisons(self, headers, params=None):
        return self._request("GET", "/comparisons", headers=headers, params=params)

    # ─── Substantiation intake ────────────────────────
    def create_substantiation(self, payload, headers):
        return self._request("POST", "/price-substantiations", payload, headers)

    def get_substantiation(self, substantiation_id, headers):
        return self._request("GET", f"/price-substantiations/{substantiation_id}",
                             headers=headers)

    def list_substantiations(self, headers, params=None):
        return self._request("GET", "/price-substantiations", headers=headers, params=params)


api_client = ApiClient()