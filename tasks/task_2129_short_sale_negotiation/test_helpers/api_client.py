"""API client: one method per endpoint defined in the PRD.

Every route lives under the `/short-sale` prefix except the logical-clock
control endpoint, which lives under `/_clock`.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/short-sale"


class ApiClient(GenericApiClient):

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── BPO vendors ──────────────────────────────────
    def create_bpo_vendor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bpo-vendors", payload, headers)

    # ─── Cases ────────────────────────────────────────
    def create_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases", headers=headers, params=params)

    # ─── Hardship packages ────────────────────────────
    def create_hardship_package(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cases/{case_id}/hardship-packages", payload, headers
        )

    def get_hardship_package(self, package_id, headers):
        return self._request(
            "GET", f"{PREFIX}/hardship-packages/{package_id}", headers=headers
        )

    def list_case_hardship_packages(self, case_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cases/{case_id}/hardship-packages",
            headers=headers, params=params,
        )

    def submit_hardship_package(self, package_id, headers):
        return self._request(
            "POST", f"{PREFIX}/hardship-packages/{package_id}/submit", {}, headers
        )

    def decide_hardship_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hardship-packages/{package_id}/decision", payload, headers
        )

    # ─── Seller documents ─────────────────────────────
    def file_document(self, package_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hardship-packages/{package_id}/documents", payload, headers
        )

    def list_package_documents(self, package_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hardship-packages/{package_id}/documents",
            headers=headers, params=params,
        )

    def review_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/documents/{document_id}/review", payload, headers
        )

    # ─── Listings ─────────────────────────────────────
    def create_listing(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cases/{case_id}/listings", payload, headers
        )

    def list_case_listings(self, case_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cases/{case_id}/listings", headers=headers, params=params
        )

    def record_price_reduction(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/listings/{listing_id}/price-reduction", payload, headers
        )

    def withdraw_listing(self, listing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/listings/{listing_id}/withdraw", payload, headers
        )

    # ─── Offers ───────────────────────────────────────
    def create_offer(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/offers", payload, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"{PREFIX}/offers/{offer_id}", headers=headers)

    def list_case_offers(self, case_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cases/{case_id}/offers", headers=headers, params=params
        )

    def submit_offer(self, offer_id, headers):
        return self._request("POST", f"{PREFIX}/offers/{offer_id}/submit", {}, headers)

    def servicer_decision_on_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/servicer-decision", payload, headers
        )

    def revise_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/revise", payload, headers
        )

    # ─── Net sheets ───────────────────────────────────
    def create_net_sheet(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/net-sheets", payload, headers
        )

    def list_offer_net_sheets(self, offer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/offers/{offer_id}/net-sheets", headers=headers, params=params
        )

    # ─── Valuations ───────────────────────────────────
    def order_valuation(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cases/{case_id}/valuations", payload, headers
        )

    def get_valuation(self, valuation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/valuations/{valuation_id}", headers=headers
        )

    def list_valuations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/valuations", headers=headers, params=params
        )

    def record_valuation_value(self, valuation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/valuations/{valuation_id}/record-value", payload, headers
        )

    def file_dispute(self, valuation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/valuations/{valuation_id}/disputes", payload, headers
        )

    def list_valuation_disputes(self, valuation_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/valuations/{valuation_id}/disputes",
            headers=headers, params=params,
        )

    def adjudicate_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/disputes/{dispute_id}/adjudicate", payload, headers
        )

    # ─── Junior liens ─────────────────────────────────
    def create_junior_lien(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cases/{case_id}/junior-liens", payload, headers
        )

    def list_case_junior_liens(self, case_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cases/{case_id}/junior-liens", headers=headers, params=params
        )

    def send_lien_demand(self, lien_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/junior-liens/{lien_id}/demand", payload, headers
        )

    def respond_to_lien(self, lien_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/junior-liens/{lien_id}/response", payload, headers
        )

    # ─── Mortgage insurance ───────────────────────────
    def create_mi_claim(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cases/{case_id}/mi-claims", payload, headers
        )

    def list_case_mi_claims(self, case_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cases/{case_id}/mi-claims", headers=headers, params=params
        )

    def decide_mi_claim(self, mi_claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/mi-claims/{mi_claim_id}/decision", payload, headers
        )

    # ─── Approval letters ─────────────────────────────
    def issue_approval_letter(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cases/{case_id}/approval-letters", payload, headers
        )

    def get_approval_letter(self, letter_id, headers):
        return self._request(
            "GET", f"{PREFIX}/approval-letters/{letter_id}", headers=headers
        )

    def list_approval_letters(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/approval-letters", headers=headers, params=params
        )

    def close_approval_letter(self, letter_id, headers):
        return self._request(
            "POST", f"{PREFIX}/approval-letters/{letter_id}/close", {}, headers
        )

    def file_extension_request(self, letter_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/approval-letters/{letter_id}/extension-requests",
            payload, headers,
        )

    def list_letter_extension_requests(self, letter_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/approval-letters/{letter_id}/extension-requests",
            headers=headers, params=params,
        )

    def decide_extension_request(self, extension_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/extension-requests/{extension_id}/decision", payload, headers
        )


api_client = ApiClient()
