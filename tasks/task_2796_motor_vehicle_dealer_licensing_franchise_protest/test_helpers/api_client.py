"""API client: one method per endpoint of the Motor Vehicle Dealer Board API.

Every path is mounted under the /dealer-board prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/dealer-board"


class ApiClient(GenericApiClient):
    # ── Logical clock ────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    def advance_clock(self, to_iso8601, headers):
        return self.set_clock({"to_iso8601": to_iso8601}, headers)

    # ── Franchisors (manufacturers) ──────────────────────────────────
    def create_manufacturer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/manufacturers", payload, headers)

    def get_manufacturer(self, manufacturer_id, headers):
        return self._request("GET", f"{PREFIX}/manufacturers/{manufacturer_id}", headers=headers)

    def list_manufacturers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/manufacturers", headers=headers, params=params)

    # ── Hearing rooms ────────────────────────────────────────────────
    def create_hearing_room(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hearing-rooms", payload, headers)

    def get_hearing_room(self, room_id, headers):
        return self._request("GET", f"{PREFIX}/hearing-rooms/{room_id}", headers=headers)

    def list_hearing_rooms(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/hearing-rooms", headers=headers, params=params)

    # ── Dealerships ──────────────────────────────────────────────────
    def create_dealer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"{PREFIX}/dealers/{dealer_id}", headers=headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dealers", headers=headers, params=params)

    # ── Dealer licence applications ──────────────────────────────────
    def create_license_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/license-applications", payload, headers)

    def submit_license_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/license-applications/{application_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def issue_deficiency_notice(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/license-applications/{application_id}/deficiency-notice",
            payload, headers,
        )

    def resubmit_license_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/license-applications/{application_id}/resubmit",
            payload if payload is not None else {}, headers,
        )

    def decide_license_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/license-applications/{application_id}/decision",
            payload, headers,
        )

    def get_license_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/license-applications/{application_id}", headers=headers)

    def list_license_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/license-applications", headers=headers, params=params)

    # ── Salespersons ─────────────────────────────────────────────────
    def create_salesperson(self, payload, headers):
        return self._request("POST", f"{PREFIX}/salespersons", payload, headers)

    def decide_salesperson_license(self, salesperson_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/salespersons/{salesperson_id}/license-decision",
            payload, headers,
        )

    def renew_salesperson(self, salesperson_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/salespersons/{salesperson_id}/renewal",
            payload if payload is not None else {}, headers,
        )

    def get_salesperson(self, salesperson_id, headers):
        return self._request("GET", f"{PREFIX}/salespersons/{salesperson_id}", headers=headers)

    def list_salespersons(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/salespersons", headers=headers, params=params)

    # ── Franchise filings ────────────────────────────────────────────
    def create_franchise_filing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/franchise-filings", payload, headers)

    def serve_filing_notice(self, filing_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/franchise-filings/{filing_id}/serve-notice",
            payload if payload is not None else {}, headers,
        )

    def amend_franchise_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/franchise-filings/{filing_id}/amend", payload, headers)

    def finalize_franchise_filing(self, filing_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/franchise-filings/{filing_id}/finalize",
            payload if payload is not None else {}, headers,
        )

    def get_franchise_filing(self, filing_id, headers):
        return self._request("GET", f"{PREFIX}/franchise-filings/{filing_id}", headers=headers)

    def list_franchise_filings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/franchise-filings", headers=headers, params=params)

    # ── Protests and the hearing docket ──────────────────────────────
    def create_protest(self, payload, headers):
        return self._request("POST", f"{PREFIX}/protests", payload, headers)

    def schedule_protest_hearing(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/schedule", payload, headers)

    def create_market_study(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/market-studies", payload, headers)

    def list_market_studies(self, protest_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/protests/{protest_id}/market-studies",
            headers=headers, params=params,
        )

    def create_evidence_submission(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/evidence-submissions", payload, headers)

    def list_evidence_submissions(self, protest_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/protests/{protest_id}/evidence-submissions",
            headers=headers, params=params,
        )

    def convene_protest_hearing(self, protest_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/convene",
            payload if payload is not None else {}, headers,
        )

    def decide_protest(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/decision", payload, headers)

    def appeal_protest(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/protests/{protest_id}/appeal", payload, headers)

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"{PREFIX}/protests/{protest_id}", headers=headers)

    def list_protests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/protests", headers=headers, params=params)

    def get_good_cause_analysis(self, protest_id, headers):
        return self._request(
            "GET", f"{PREFIX}/protests/{protest_id}/good-cause-analysis", headers=headers)

    # ── Warranty reimbursement rate disputes ─────────────────────────
    def create_warranty_rate_dispute(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-rate-disputes", payload, headers)

    def respond_to_warranty_rate_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-rate-disputes/{dispute_id}/response", payload, headers)

    def decide_warranty_rate_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/warranty-rate-disputes/{dispute_id}/decision", payload, headers)

    def get_warranty_rate_dispute(self, dispute_id, headers):
        return self._request(
            "GET", f"{PREFIX}/warranty-rate-disputes/{dispute_id}", headers=headers)

    def list_warranty_rate_disputes(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/warranty-rate-disputes", headers=headers, params=params)

    # ── Consumer complaints ──────────────────────────────────────────
    def create_consumer_complaint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consumer-complaints", payload, headers)

    def open_complaint_investigation(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consumer-complaints/{complaint_id}/investigation", payload, headers)

    def resolve_consumer_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consumer-complaints/{complaint_id}/resolution", payload, headers)

    def pay_restitution(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consumer-complaints/{complaint_id}/restitution-payment",
            payload, headers,
        )

    def get_consumer_complaint(self, complaint_id, headers):
        return self._request(
            "GET", f"{PREFIX}/consumer-complaints/{complaint_id}", headers=headers)

    def list_consumer_complaints(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/consumer-complaints", headers=headers, params=params)


api_client = ApiClient()
