"""API client: one method per endpoint defined in the PRD.

Every collection is mounted at the root of the API — there is no shared URL
prefix — so each path below is absolute.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Counties ────────────────────────────────────────────────────────────

    def create_county(self, payload, headers):
        return self._request("POST", "/counties", payload, headers)

    def get_county(self, county_id, headers):
        return self._request("GET", f"/counties/{county_id}", headers=headers)

    # ─── Party profiles ──────────────────────────────────────────────────────

    def create_seller_profile(self, payload, headers):
        return self._request("POST", "/seller-profiles", payload, headers)

    def get_seller_profile(self, seller_id, headers):
        return self._request("GET", f"/seller-profiles/{seller_id}", headers=headers)

    def create_buyer_profile(self, payload, headers):
        return self._request("POST", "/buyer-profiles", payload, headers)

    def get_buyer_profile(self, buyer_id, headers):
        return self._request("GET", f"/buyer-profiles/{buyer_id}", headers=headers)

    def qualification_review(self, buyer_id, payload, headers):
        return self._request(
            "POST", f"/buyer-profiles/{buyer_id}/qualification-review", payload, headers
        )

    # ─── Brokerages ──────────────────────────────────────────────────────────

    def create_brokerage(self, payload, headers):
        return self._request("POST", "/brokerages", payload, headers)

    def get_brokerage(self, brokerage_id, headers):
        return self._request("GET", f"/brokerages/{brokerage_id}", headers=headers)

    # ─── Licenses ────────────────────────────────────────────────────────────

    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def list_license_safekeeping_filings(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/licenses/{license_id}/safekeeping-filings",
            headers=headers, params=params,
        )

    # ─── Premises ────────────────────────────────────────────────────────────

    def create_premises(self, payload, headers):
        return self._request("POST", "/premises", payload, headers)

    def get_premises(self, premises_id, headers):
        return self._request("GET", f"/premises/{premises_id}", headers=headers)

    def list_premises(self, headers, params=None):
        return self._request("GET", "/premises", headers=headers, params=params)

    def zoning_verification(self, premises_id, payload, headers):
        return self._request(
            "POST", f"/premises/{premises_id}/zoning-verification", payload, headers
        )

    def landlord_consent(self, premises_id, payload, headers):
        return self._request(
            "POST", f"/premises/{premises_id}/landlord-consent", payload, headers
        )

    # ─── Listings ────────────────────────────────────────────────────────────

    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def get_valuation_preview(self, listing_id, headers):
        return self._request(
            "GET", f"/listings/{listing_id}/valuation-preview", headers=headers
        )

    def activate_listing(self, listing_id, headers, payload=None):
        return self._request(
            "POST", f"/listings/{listing_id}/activate", payload or {}, headers
        )

    def withdraw_listing(self, listing_id, headers, payload=None):
        return self._request(
            "POST", f"/listings/{listing_id}/withdraw", payload or {}, headers
        )

    # ─── Purchase agreements ─────────────────────────────────────────────────

    def create_purchase_agreement(self, payload, headers):
        return self._request("POST", "/purchase-agreements", payload, headers)

    def get_purchase_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/purchase-agreements/{agreement_id}", headers=headers
        )

    def list_purchase_agreements(self, headers, params=None):
        return self._request(
            "GET", "/purchase-agreements", headers=headers, params=params
        )

    def get_agreement_escrow_ledger(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/purchase-agreements/{agreement_id}/escrow-ledger",
            headers=headers, params=params,
        )

    def get_escrow_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/escrow-ledger-entries/{entry_id}", headers=headers
        )

    def list_escrow_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/escrow-ledger-entries", headers=headers, params=params
        )

    def list_agreement_disclosures(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/purchase-agreements/{agreement_id}/dual-agency-disclosures",
            headers=headers, params=params,
        )

    def escrow_deposit(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/purchase-agreements/{agreement_id}/escrow-deposit",
            payload, headers,
        )

    def execute_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/purchase-agreements/{agreement_id}/execute",
            payload or {}, headers,
        )

    def terminate_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/purchase-agreements/{agreement_id}/terminate", payload, headers
        )

    def escrow_settlement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/purchase-agreements/{agreement_id}/escrow-settlement",
            payload, headers,
        )

    # ─── Dual agency disclosures ─────────────────────────────────────────────

    def create_disclosure(self, payload, headers):
        return self._request("POST", "/dual-agency-disclosures", payload, headers)

    def get_disclosure(self, disclosure_id, headers):
        return self._request(
            "GET", f"/dual-agency-disclosures/{disclosure_id}", headers=headers
        )

    def list_disclosures(self, headers, params=None):
        return self._request(
            "GET", "/dual-agency-disclosures", headers=headers, params=params
        )

    def acknowledge_disclosure(self, disclosure_id, payload, headers):
        return self._request(
            "POST", f"/dual-agency-disclosures/{disclosure_id}/acknowledge",
            payload, headers,
        )

    # ─── Transfer applications ───────────────────────────────────────────────

    def create_transfer_application(self, payload, headers):
        return self._request("POST", "/transfer-applications", payload, headers)

    def get_transfer_application(self, application_id, headers):
        return self._request(
            "GET", f"/transfer-applications/{application_id}", headers=headers
        )

    def list_transfer_applications(self, headers, params=None):
        return self._request(
            "GET", "/transfer-applications", headers=headers, params=params
        )

    def list_application_protests(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/transfer-applications/{application_id}/protests",
            headers=headers, params=params,
        )

    def accept_review(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/transfer-applications/{application_id}/accept-review",
            payload or {}, headers,
        )

    def issue_deficiency(self, application_id, payload, headers):
        return self._request(
            "POST", f"/transfer-applications/{application_id}/deficiency",
            payload, headers,
        )

    def resubmit_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/transfer-applications/{application_id}/resubmit",
            payload, headers,
        )

    def post_notice(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/transfer-applications/{application_id}/post-notice",
            payload or {}, headers,
        )

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/transfer-applications/{application_id}/decision",
            payload, headers,
        )

    # ─── Protests ────────────────────────────────────────────────────────────

    def create_protest(self, payload, headers):
        return self._request("POST", "/protests", payload, headers)

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"/protests/{protest_id}", headers=headers)

    def list_protests(self, headers, params=None):
        return self._request("GET", "/protests", headers=headers, params=params)

    def respond_to_protest(self, protest_id, payload, headers):
        return self._request(
            "POST", f"/protests/{protest_id}/response", payload, headers
        )

    # ─── Safekeeping filings ─────────────────────────────────────────────────

    def create_safekeeping_filing(self, payload, headers):
        return self._request("POST", "/safekeeping-filings", payload, headers)

    def get_safekeeping_filing(self, filing_id, headers):
        return self._request(
            "GET", f"/safekeeping-filings/{filing_id}", headers=headers
        )

    def list_safekeeping_filings(self, headers, params=None):
        return self._request(
            "GET", "/safekeeping-filings", headers=headers, params=params
        )

    def decide_safekeeping_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/safekeeping-filings/{filing_id}/decide", payload, headers
        )

    # ─── Logical clock ───────────────────────────────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
