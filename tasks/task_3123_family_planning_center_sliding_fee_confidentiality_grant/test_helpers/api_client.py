"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/family-planning/_clock/set_current_utc", payload, headers)

    # --- affiliates ---
    def create_affiliate(self, payload, headers):
        return self._request("POST", "/family-planning/affiliates", payload, headers)

    def list_affiliates(self, headers, params=None):
        return self._request("GET", "/family-planning/affiliates", headers=headers, params=params)

    def get_affiliate(self, affiliate_id, headers):
        return self._request("GET", f"/family-planning/affiliates/{affiliate_id}", headers=headers)

    def suspend_affiliate(self, affiliate_id, headers):
        return self._request("POST", f"/family-planning/affiliates/{affiliate_id}/suspend", {}, headers)

    def reinstate_affiliate(self, affiliate_id, headers):
        return self._request("POST", f"/family-planning/affiliates/{affiliate_id}/reinstate", {}, headers)

    def close_affiliate(self, affiliate_id, headers):
        return self._request("POST", f"/family-planning/affiliates/{affiliate_id}/close", {}, headers)

    # --- service catalog ---
    def create_catalog_entry(self, affiliate_id, payload, headers):
        return self._request("POST", f"/family-planning/affiliates/{affiliate_id}/service-catalog", payload, headers)

    def list_catalog_entries(self, affiliate_id, headers, params=None):
        return self._request("GET", f"/family-planning/affiliates/{affiliate_id}/service-catalog", headers=headers, params=params)

    def get_catalog_entry(self, entry_id, headers):
        return self._request("GET", f"/family-planning/service-catalog/{entry_id}", headers=headers)

    # --- fee tiers ---
    def create_fee_tier(self, affiliate_id, payload, headers):
        return self._request("POST", f"/family-planning/affiliates/{affiliate_id}/fee-tiers", payload, headers)

    def list_fee_tiers(self, affiliate_id, headers, params=None):
        return self._request("GET", f"/family-planning/affiliates/{affiliate_id}/fee-tiers", headers=headers, params=params)

    def get_fee_tier(self, tier_id, headers):
        return self._request("GET", f"/family-planning/fee-tiers/{tier_id}", headers=headers)

    # --- patients ---
    def create_patient(self, affiliate_id, payload, headers):
        return self._request("POST", f"/family-planning/affiliates/{affiliate_id}/patients", payload, headers)

    def list_patients(self, affiliate_id, headers, params=None):
        return self._request("GET", f"/family-planning/affiliates/{affiliate_id}/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/family-planning/patients/{patient_id}", headers=headers)

    # --- household assessments ---
    def create_assessment(self, patient_id, payload, headers):
        return self._request("POST", f"/family-planning/patients/{patient_id}/household-assessments", payload, headers)

    def list_assessments(self, patient_id, headers, params=None):
        return self._request("GET", f"/family-planning/patients/{patient_id}/household-assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/family-planning/household-assessments/{assessment_id}", headers=headers)

    def list_assessment_encounters(self, assessment_id, headers, params=None):
        return self._request("GET", f"/family-planning/household-assessments/{assessment_id}/encounters", headers=headers, params=params)

    # --- providers / licenses ---
    def create_provider(self, affiliate_id, payload, headers):
        return self._request("POST", f"/family-planning/affiliates/{affiliate_id}/providers", payload, headers)

    def list_providers(self, affiliate_id, headers, params=None):
        return self._request("GET", f"/family-planning/affiliates/{affiliate_id}/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/family-planning/providers/{provider_id}", headers=headers)

    def create_license(self, provider_id, payload, headers):
        return self._request("POST", f"/family-planning/providers/{provider_id}/licenses", payload, headers)

    def list_licenses(self, provider_id, headers, params=None):
        return self._request("GET", f"/family-planning/providers/{provider_id}/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/family-planning/licenses/{license_id}", headers=headers)

    # --- encounters ---
    def create_encounter(self, patient_id, payload, headers):
        return self._request("POST", f"/family-planning/patients/{patient_id}/encounters", payload, headers)

    def list_patient_encounters(self, patient_id, headers, params=None):
        return self._request("GET", f"/family-planning/patients/{patient_id}/encounters", headers=headers, params=params)

    def list_affiliate_encounters(self, affiliate_id, headers, params=None):
        return self._request("GET", f"/family-planning/affiliates/{affiliate_id}/encounters", headers=headers, params=params)

    def list_provider_encounters(self, provider_id, headers, params=None):
        return self._request("GET", f"/family-planning/providers/{provider_id}/encounters", headers=headers, params=params)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/family-planning/encounters/{encounter_id}", headers=headers)

    def start_encounter(self, encounter_id, headers):
        return self._request("POST", f"/family-planning/encounters/{encounter_id}/start", {}, headers)

    def complete_encounter(self, encounter_id, headers):
        return self._request("POST", f"/family-planning/encounters/{encounter_id}/complete", {}, headers)

    def cancel_encounter(self, encounter_id, headers):
        return self._request("POST", f"/family-planning/encounters/{encounter_id}/cancel", {}, headers)

    def waive_billing(self, encounter_id, headers):
        return self._request("POST", f"/family-planning/encounters/{encounter_id}/waive-billing", {}, headers)

    # --- claims ---
    def create_claim(self, encounter_id, headers):
        return self._request("POST", f"/family-planning/encounters/{encounter_id}/claims", {}, headers)

    def list_claims(self, encounter_id, headers, params=None):
        return self._request("GET", f"/family-planning/encounters/{encounter_id}/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/family-planning/claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/family-planning/claims/{claim_id}/submit", {}, headers)

    def return_claim(self, claim_id, headers):
        return self._request("POST", f"/family-planning/claims/{claim_id}/return", {}, headers)

    def resubmit_claim(self, claim_id, headers):
        return self._request("POST", f"/family-planning/claims/{claim_id}/resubmit", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/family-planning/claims/{claim_id}/adjudicate", payload, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/family-planning/claims/{claim_id}/deny", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/family-planning/claims/{claim_id}/void", {}, headers)

    def recoup_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/family-planning/claims/{claim_id}/recoup", payload, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/family-planning/claims/{claim_id}/settle", {}, headers)

    # --- stock lots / device reservations ---
    def create_stock_lot(self, affiliate_id, payload, headers):
        return self._request("POST", f"/family-planning/affiliates/{affiliate_id}/stock-lots", payload, headers)

    def list_stock_lots(self, affiliate_id, headers, params=None):
        return self._request("GET", f"/family-planning/affiliates/{affiliate_id}/stock-lots", headers=headers, params=params)

    def get_stock_lot(self, lot_id, headers):
        return self._request("GET", f"/family-planning/stock-lots/{lot_id}", headers=headers)

    def list_lot_reservations(self, lot_id, headers, params=None):
        return self._request("GET", f"/family-planning/stock-lots/{lot_id}/device-reservations", headers=headers, params=params)

    def create_device_reservation(self, encounter_id, payload, headers):
        return self._request("POST", f"/family-planning/encounters/{encounter_id}/device-reservations", payload, headers)

    def list_encounter_reservations(self, encounter_id, headers, params=None):
        return self._request("GET", f"/family-planning/encounters/{encounter_id}/device-reservations", headers=headers, params=params)

    def get_device_reservation(self, reservation_id, headers):
        return self._request("GET", f"/family-planning/device-reservations/{reservation_id}", headers=headers)

    def release_device_reservation(self, reservation_id, headers):
        return self._request("POST", f"/family-planning/device-reservations/{reservation_id}/release", {}, headers)

    # --- referral orders ---
    def create_referral(self, encounter_id, payload, headers):
        return self._request("POST", f"/family-planning/encounters/{encounter_id}/referral-orders", payload, headers)

    def list_referrals(self, encounter_id, headers, params=None):
        return self._request("GET", f"/family-planning/encounters/{encounter_id}/referral-orders", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/family-planning/referral-orders/{referral_id}", headers=headers)

    def acknowledge_referral(self, referral_id, headers):
        return self._request("POST", f"/family-planning/referral-orders/{referral_id}/acknowledge", {}, headers)

    def complete_referral(self, referral_id, headers):
        return self._request("POST", f"/family-planning/referral-orders/{referral_id}/complete", {}, headers)

    def withdraw_referral(self, referral_id, headers):
        return self._request("POST", f"/family-planning/referral-orders/{referral_id}/withdraw", {}, headers)

    # --- grant reports ---
    def create_grant_report(self, affiliate_id, payload, headers):
        return self._request("POST", f"/family-planning/affiliates/{affiliate_id}/grant-reports", payload, headers)

    def list_grant_reports(self, affiliate_id, headers, params=None):
        return self._request("GET", f"/family-planning/affiliates/{affiliate_id}/grant-reports", headers=headers, params=params)

    def get_grant_report(self, report_id, headers):
        return self._request("GET", f"/family-planning/grant-reports/{report_id}", headers=headers)

    def list_report_amendments(self, report_id, headers, params=None):
        return self._request("GET", f"/family-planning/grant-reports/{report_id}/amendments", headers=headers, params=params)

    def finalize_grant_report(self, report_id, headers):
        return self._request("POST", f"/family-planning/grant-reports/{report_id}/finalize", {}, headers)

    # --- privacy holds ---
    def create_privacy_hold(self, patient_id, payload, headers):
        return self._request("POST", f"/family-planning/patients/{patient_id}/privacy-holds", payload, headers)

    def list_privacy_holds(self, patient_id, headers, params=None):
        return self._request("GET", f"/family-planning/patients/{patient_id}/privacy-holds", headers=headers, params=params)

    def get_privacy_hold(self, hold_id, headers):
        return self._request("GET", f"/family-planning/privacy-holds/{hold_id}", headers=headers)

    def release_privacy_hold(self, hold_id, headers):
        return self._request("POST", f"/family-planning/privacy-holds/{hold_id}/release", {}, headers)


api_client = ApiClient()
