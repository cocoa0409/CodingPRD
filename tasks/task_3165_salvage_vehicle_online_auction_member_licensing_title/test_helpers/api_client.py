"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/salvage-auction"


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- yards ----------------------------------------------------------
    def create_yard(self, payload, headers):
        return self._request("POST", f"{PREFIX}/yards", payload, headers)

    def list_yards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/yards", headers=headers, params=params)

    def get_yard(self, yard_id, headers):
        return self._request("GET", f"{PREFIX}/yards/{yard_id}", headers=headers)

    # ---- sellers --------------------------------------------------------
    def create_seller(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sellers", payload, headers)

    def list_sellers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sellers", headers=headers, params=params)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"{PREFIX}/sellers/{seller_id}", headers=headers)

    # ---- members --------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/members/{member_id}", headers=headers)

    # ---- licenses -------------------------------------------------------
    def create_license(self, member_id, payload, headers):
        return self._request("POST", f"{PREFIX}/members/{member_id}/licenses", payload, headers)

    def list_member_licenses(self, member_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/licenses", headers=headers, params=params
        )

    def get_license(self, license_id, headers):
        return self._request("GET", f"{PREFIX}/licenses/{license_id}", headers=headers)

    # ---- vehicles -------------------------------------------------------
    def create_vehicle(self, payload, headers):
        return self._request("POST", f"{PREFIX}/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"{PREFIX}/vehicles/{vehicle_id}", headers=headers)

    def add_vehicle_image(self, vehicle_id, payload, headers):
        return self._request("POST", f"{PREFIX}/vehicles/{vehicle_id}/images", payload, headers)

    def submit_condition(self, vehicle_id, payload, headers):
        return self._request("POST", f"{PREFIX}/vehicles/{vehicle_id}/condition", payload, headers)

    def mark_ready(self, vehicle_id, payload, headers):
        return self._request("POST", f"{PREFIX}/vehicles/{vehicle_id}/mark-ready", payload, headers)

    def cancel_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"{PREFIX}/vehicles/{vehicle_id}/cancel", {}, headers)

    # ---- title records --------------------------------------------------
    def create_title(self, vehicle_id, payload, headers):
        return self._request("POST", f"{PREFIX}/vehicles/{vehicle_id}/title", payload, headers)

    def get_vehicle_title(self, vehicle_id, headers):
        return self._request("GET", f"{PREFIX}/vehicles/{vehicle_id}/title", headers=headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"{PREFIX}/titles/{title_id}", headers=headers)

    # ---- auctions -------------------------------------------------------
    def create_auction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/auctions", payload, headers)

    def list_auctions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/auctions", headers=headers, params=params)

    def get_auction(self, auction_id, headers):
        return self._request("GET", f"{PREFIX}/auctions/{auction_id}", headers=headers)

    def start_auction(self, auction_id, headers):
        return self._request("POST", f"{PREFIX}/auctions/{auction_id}/start", {}, headers)

    # ---- auction items --------------------------------------------------
    def create_auction_item(self, auction_id, payload, headers):
        return self._request("POST", f"{PREFIX}/auctions/{auction_id}/items", payload, headers)

    def list_auction_items(self, auction_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/auctions/{auction_id}/items", headers=headers, params=params
        )

    def list_vehicle_auction_items(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/vehicles/{vehicle_id}/auction-items", headers=headers, params=params
        )

    def get_auction_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/auction-items/{item_id}", headers=headers)

    def open_lot(self, auction_id, item_id, headers):
        return self._request(
            "POST", f"{PREFIX}/auctions/{auction_id}/items/{item_id}/open-lot", {}, headers
        )

    def close_lot(self, auction_id, item_id, headers):
        return self._request(
            "POST", f"{PREFIX}/auctions/{auction_id}/items/{item_id}/close-lot", {}, headers
        )

    def cancel_auction_item(self, auction_id, item_id, headers):
        return self._request(
            "POST", f"{PREFIX}/auctions/{auction_id}/items/{item_id}/cancel", {}, headers
        )

    # ---- bids -----------------------------------------------------------
    def place_bid(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"{PREFIX}/bids/{bid_id}", headers=headers)

    # ---- sales ----------------------------------------------------------
    def list_sales(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sales", headers=headers, params=params)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"{PREFIX}/sales/{sale_id}", headers=headers)

    def approve_sale(self, sale_id, headers):
        return self._request("POST", f"{PREFIX}/sales/{sale_id}/approve", {}, headers)

    def reject_offer(self, sale_id, headers):
        return self._request("POST", f"{PREFIX}/sales/{sale_id}/reject-offer", {}, headers)

    def cancel_sale(self, sale_id, headers):
        return self._request("POST", f"{PREFIX}/sales/{sale_id}/cancel", {}, headers)

    def pay_sale(self, sale_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sales/{sale_id}/payments", payload, headers)

    # ---- gate passes ----------------------------------------------------
    def create_gate_pass(self, sale_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sales/{sale_id}/gate-passes", payload, headers)

    def list_sale_gate_passes(self, sale_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sales/{sale_id}/gate-passes", headers=headers, params=params
        )

    def get_gate_pass(self, gate_pass_id, headers):
        return self._request("GET", f"{PREFIX}/gate-passes/{gate_pass_id}", headers=headers)

    def check_in_gate_pass(self, gate_pass_id, headers):
        return self._request("POST", f"{PREFIX}/gate-passes/{gate_pass_id}/check-in", {}, headers)

    def complete_gate_pass(self, gate_pass_id, headers):
        return self._request("POST", f"{PREFIX}/gate-passes/{gate_pass_id}/complete", {}, headers)

    # ---- settlements ----------------------------------------------------
    def get_sale_settlement(self, sale_id, headers):
        return self._request("GET", f"{PREFIX}/sales/{sale_id}/settlement", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"{PREFIX}/settlements/{settlement_id}", headers=headers)

    # ---- export documents -----------------------------------------------
    def create_export_document(self, sale_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sales/{sale_id}/export-documents", payload, headers)

    def list_sale_export_documents(self, sale_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sales/{sale_id}/export-documents", headers=headers, params=params
        )

    def get_export_document(self, doc_id, headers):
        return self._request("GET", f"{PREFIX}/export-documents/{doc_id}", headers=headers)

    def verify_export_document(self, doc_id, headers):
        return self._request("POST", f"{PREFIX}/export-documents/{doc_id}/verify", {}, headers)

    def reject_export_document(self, doc_id, headers):
        return self._request("POST", f"{PREFIX}/export-documents/{doc_id}/reject", {}, headers)


api_client = ApiClient()
