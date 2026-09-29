"""API client: one method per endpoint defined in the PRD."""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the surplus-property disposal HTTP surface."""

    # ─── Logical clock (PRD §2.4) ─────────────────────────────────────────

    def set_current_utc(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ─── Agencies (PRD §3.1) ──────────────────────────────────────────────

    def create_agency(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def list_agencies(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/agencies", headers=headers, params=params)

    def set_agency_status(self, agency_id: str, status: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/agencies/{agency_id}/status", {"status": status}, headers
        )

    def set_agency_donee_certification(
        self, agency_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/agencies/{agency_id}/donee-certification", payload, headers
        )

    # ─── Turn-ins (PRD §3.2) ──────────────────────────────────────────────

    def create_turn_in(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/turn-ins", payload, headers)

    def get_turn_in(self, turn_in_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/turn-ins/{turn_in_id}", headers=headers)

    def list_turn_ins(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/turn-ins", headers=headers, params=params)

    def submit_turn_in(self, turn_in_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/turn-ins/{turn_in_id}/submit", {}, headers)

    def review_turn_in(self, turn_in_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/turn-ins/{turn_in_id}/review", payload, headers)

    # ─── Surplus assets (PRD §3.2) ────────────────────────────────────────

    def create_asset(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def release_asset(self, asset_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/assets/{asset_id}/release", payload, headers)

    # ─── Condition assessments (PRD §3.3) ─────────────────────────────────

    def create_condition_assessment(
        self, asset_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/assets/{asset_id}/condition-assessments", payload, headers
        )

    def list_condition_assessments(
        self, asset_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/assets/{asset_id}/condition-assessments",
            headers=headers, params=params,
        )

    # ─── Clearance certificates (PRD §3.8) ────────────────────────────────

    def create_clearance_certificate(
        self, asset_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/assets/{asset_id}/clearance-certificates", payload, headers
        )

    def list_clearance_certificates(
        self, asset_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/assets/{asset_id}/clearance-certificates",
            headers=headers, params=params,
        )

    # ─── Screening cycles (PRD §3.4) ──────────────────────────────────────

    def create_screening_cycle(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/screening-cycles", payload, headers)

    def get_screening_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/screening-cycles/{cycle_id}", headers=headers)

    def list_screening_cycles(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/screening-cycles", headers=headers, params=params)

    def advance_screening_tier(self, cycle_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/screening-cycles/{cycle_id}/advance-tier", {}, headers
        )

    def award_screening_cycle(
        self, cycle_id: str, screening_request_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/screening-cycles/{cycle_id}/award",
            {"screening_request_id": screening_request_id}, headers,
        )

    # ─── Screening requests (PRD §3.4) ────────────────────────────────────

    def create_screening_request(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/screening-requests", payload, headers)

    def get_screening_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/screening-requests/{request_id}", headers=headers)

    def list_screening_requests(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", "/screening-requests", headers=headers, params=params
        )

    def request_screening_info(
        self, request_id: str, information_request_note: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/screening-requests/{request_id}/request-info",
            {"information_request_note": information_request_note}, headers,
        )

    def resubmit_screening_request(
        self, request_id: str, justification: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/screening-requests/{request_id}/resubmit",
            {"justification": justification}, headers,
        )

    # ─── Transfer orders (PRD §3.5) ───────────────────────────────────────

    def create_transfer_order(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/transfer-orders", payload, headers)

    def get_transfer_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/transfer-orders/{order_id}", headers=headers)

    def list_transfer_orders(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/transfer-orders", headers=headers, params=params)

    def acknowledge_transfer_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-orders/{order_id}/acknowledge", {}, headers
        )

    def void_transfer_order(
        self, order_id: str, void_reason: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/transfer-orders/{order_id}/void",
            {"void_reason": void_reason}, headers,
        )

    # ─── Sale venues (PRD §3.1) ───────────────────────────────────────────

    def create_venue(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def list_venues(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def set_venue_status(self, venue_id: str, status: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/venues/{venue_id}/status", {"status": status}, headers
        )

    # ─── Auction lots and bids (PRD §3.6) ─────────────────────────────────

    def create_auction_lot(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/auction-lots", payload, headers)

    def get_auction_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/auction-lots/{lot_id}", headers=headers)

    def list_auction_lots(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/auction-lots", headers=headers, params=params)

    def open_auction_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/auction-lots/{lot_id}/open", {}, headers)

    def close_auction_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/auction-lots/{lot_id}/close", {}, headers)

    def place_bid(self, lot_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/auction-lots/{lot_id}/bids", payload, headers)

    def list_lot_bids(
        self, lot_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/auction-lots/{lot_id}/bids", headers=headers, params=params
        )

    # ─── Bidders (PRD §3.1) ───────────────────────────────────────────────

    def create_bidder(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/bidders", payload, headers)

    def get_bidder(self, bidder_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/bidders/{bidder_id}", headers=headers)

    def list_bidders(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/bidders", headers=headers, params=params)

    def set_bidder_status(self, bidder_id: str, status: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/bidders/{bidder_id}/status", {"status": status}, headers
        )

    def set_bidder_end_use_certificate(
        self, bidder_id: str, end_use_certificate_expires_on: str,
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/bidders/{bidder_id}/end-use-certificate",
            {"end_use_certificate_expires_on": end_use_certificate_expires_on},
            headers,
        )

    def record_deposit(self, bidder_id: str, amount_cents: int, headers: Dict[str, str]):
        return self._request(
            "POST", f"/bidders/{bidder_id}/deposits",
            {"amount_cents": amount_cents}, headers,
        )

    def list_bidder_bids(
        self, bidder_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/bidders/{bidder_id}/bids", headers=headers, params=params
        )

    # ─── Sale invoices (PRD §3.7) ─────────────────────────────────────────

    def get_sale_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sale-invoices/{invoice_id}", headers=headers)

    def list_sale_invoices(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/sale-invoices", headers=headers, params=params)

    def pay_sale_invoice(self, invoice_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/sale-invoices/{invoice_id}/payments", payload, headers
        )

    def default_sale_invoice(
        self, invoice_id: str, default_reason: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sale-invoices/{invoice_id}/default",
            {"default_reason": default_reason}, headers,
        )

    def void_sale_invoice(
        self, invoice_id: str, void_reason: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sale-invoices/{invoice_id}/void",
            {"void_reason": void_reason}, headers,
        )

    # ─── Proceeds distributions (PRD §3.9) ────────────────────────────────

    def create_proceeds_distribution(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/proceeds-distributions", payload, headers)

    def get_proceeds_distribution(
        self, distribution_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/proceeds-distributions/{distribution_id}", headers=headers
        )

    def list_proceeds_distributions(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", "/proceeds-distributions", headers=headers, params=params
        )

    def post_proceeds_distribution(
        self, distribution_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/proceeds-distributions/{distribution_id}/post", {}, headers
        )

    def reverse_proceeds_distribution(
        self, distribution_id: str, reversal_reason: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/proceeds-distributions/{distribution_id}/reverse",
            {"reversal_reason": reversal_reason}, headers,
        )


api_client = ApiClient()
