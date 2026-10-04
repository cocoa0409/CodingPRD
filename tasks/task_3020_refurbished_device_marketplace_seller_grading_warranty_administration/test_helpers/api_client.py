"""API client: one method per endpoint of the seller grading & warranty API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Sellers -----------------------------------------------------------
    def create_seller(self, payload, headers):
        return self._request("POST", "/v1/sellers", payload, headers)

    def list_sellers(self, headers, params=None):
        return self._request("GET", "/v1/sellers", headers=headers, params=params)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/v1/sellers/{seller_id}", headers=headers)

    def verify_documents(self, seller_id, headers, payload=None):
        return self._request("POST", f"/v1/sellers/{seller_id}/verify-documents", payload or {}, headers)

    def create_audit_record(self, seller_id, payload, headers):
        return self._request("POST", f"/v1/sellers/{seller_id}/audit-records", payload, headers)

    def list_seller_audit_records(self, seller_id, headers, params=None):
        return self._request("GET", f"/v1/sellers/{seller_id}/audit-records", headers=headers, params=params)

    def get_audit_record(self, audit_record_id, headers):
        return self._request("GET", f"/v1/audit-records/{audit_record_id}", headers=headers)

    def transition_audit_record(self, audit_record_id, payload, headers):
        return self._request("POST", f"/v1/audit-records/{audit_record_id}/transition", payload, headers)

    def suspend_seller(self, seller_id, payload, headers):
        return self._request("POST", f"/v1/sellers/{seller_id}/suspend", payload, headers)

    def blocklist_seller(self, seller_id, payload, headers):
        return self._request("POST", f"/v1/sellers/{seller_id}/blocklist", payload, headers)

    def get_exposure_floor(self, seller_id, headers):
        return self._request("GET", f"/v1/sellers/{seller_id}/exposure-floor", headers=headers)

    def list_seller_listings(self, seller_id, headers, params=None):
        return self._request("GET", f"/v1/sellers/{seller_id}/listings", headers=headers, params=params)

    def list_seller_verifications(self, seller_id, headers, params=None):
        return self._request("GET", f"/v1/sellers/{seller_id}/mystery-shop-verifications", headers=headers, params=params)

    def list_seller_scores(self, seller_id, headers, params=None):
        return self._request("GET", f"/v1/sellers/{seller_id}/service-scores", headers=headers, params=params)

    # --- Listings ----------------------------------------------------------
    def create_listing(self, seller_id, payload, headers):
        return self._request("POST", f"/v1/sellers/{seller_id}/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/v1/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/v1/listings/{listing_id}", headers=headers)

    def submit_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/v1/listings/{listing_id}/submit", payload, headers)

    def review_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/v1/listings/{listing_id}/review", payload, headers)

    def suspend_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/v1/listings/{listing_id}/suspend", payload, headers)

    def withdraw_listing(self, listing_id, payload, headers):
        return self._request("POST", f"/v1/listings/{listing_id}/withdraw", payload, headers)

    def get_buy_box(self, listing_id, headers):
        return self._request("GET", f"/v1/listings/{listing_id}/buy-box", headers=headers)

    def list_listing_verifications(self, listing_id, headers, params=None):
        return self._request("GET", f"/v1/listings/{listing_id}/mystery-shop-verifications", headers=headers, params=params)

    # --- Mystery-shop verifications ----------------------------------------
    def create_verification(self, payload, headers):
        return self._request("POST", "/v1/mystery-shop-verifications", payload, headers)

    def list_verifications(self, headers, params=None):
        return self._request("GET", "/v1/mystery-shop-verifications", headers=headers, params=params)

    def get_verification(self, verification_id, headers):
        return self._request("GET", f"/v1/mystery-shop-verifications/{verification_id}", headers=headers)

    def disclose_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/v1/mystery-shop-verifications/{verification_id}/disclose", payload, headers)

    def void_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/v1/mystery-shop-verifications/{verification_id}/void", payload, headers)

    # --- Warranty reservations ---------------------------------------------
    def create_reservation(self, listing_id, payload, headers):
        return self._request("POST", f"/v1/listings/{listing_id}/warranty-reservations", payload, headers)

    def list_listing_reservations(self, listing_id, headers, params=None):
        return self._request("GET", f"/v1/listings/{listing_id}/warranty-reservations", headers=headers, params=params)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/v1/warranty-reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/v1/warranty-reservations/{reservation_id}", headers=headers)

    def remediate_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/v1/warranty-reservations/{reservation_id}/remediate", payload, headers)

    # --- Warranty claims ---------------------------------------------------
    def file_claim(self, seller_id, payload, headers):
        return self._request("POST", f"/v1/sellers/{seller_id}/warranty-claims", payload, headers)

    def list_listing_claims(self, listing_id, headers, params=None):
        return self._request("GET", f"/v1/listings/{listing_id}/warranty-claims", headers=headers, params=params)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/v1/warranty-claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/v1/warranty-claims/{claim_id}", headers=headers)

    def attach_evidence(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/warranty-claims/{claim_id}/evidence", payload, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/warranty-claims/{claim_id}/adjudicate", payload, headers)

    def route_return(self, claim_id, payload, headers):
        return self._request("POST", f"/v1/warranty-claims/{claim_id}/route-return", payload, headers)

    # --- Grading definitions ------------------------------------------------
    def create_grading_definition(self, payload, headers):
        return self._request("POST", "/v1/grading-definitions", payload, headers)

    def list_grading_definitions(self, headers, params=None):
        return self._request("GET", "/v1/grading-definitions", headers=headers, params=params)

    def get_grading_definition(self, definition_id, headers):
        return self._request("GET", f"/v1/grading-definitions/{definition_id}", headers=headers)

    def list_definition_listings(self, definition_id, headers, params=None):
        return self._request("GET", f"/v1/grading-definitions/{definition_id}/device-listings", headers=headers, params=params)

    def activate_grading_definition(self, definition_id, headers, payload=None):
        return self._request("POST", f"/v1/grading-definitions/{definition_id}/activate", payload or {}, headers)

    def retire_grading_definition(self, definition_id, payload, headers):
        return self._request("POST", f"/v1/grading-definitions/{definition_id}/retire", payload, headers)

    def reinstate_grading_definition(self, definition_id, headers, payload=None):
        return self._request("POST", f"/v1/grading-definitions/{definition_id}/reinstate", payload or {}, headers)

    # --- Trade-ins ----------------------------------------------------------
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/v1/trade-ins", payload, headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/v1/trade-ins", headers=headers, params=params)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/v1/trade-ins/{trade_in_id}", headers=headers)

    def inspect_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/v1/trade-ins/{trade_in_id}/inspection", payload, headers)

    def revise_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/v1/trade-ins/{trade_in_id}/inspection-revision", payload, headers)

    def accept_trade_in(self, trade_in_id, headers, payload=None):
        return self._request("POST", f"/v1/trade-ins/{trade_in_id}/accept", payload or {}, headers)

    # --- Service scores -----------------------------------------------------
    def create_service_score(self, payload, headers):
        return self._request("POST", "/v1/service-scores", payload, headers)

    def list_service_scores(self, headers, params=None):
        return self._request("GET", "/v1/service-scores", headers=headers, params=params)

    def get_service_score(self, section_id, headers):
        return self._request("GET", f"/v1/service-scores/{section_id}", headers=headers)

    def close_service_score(self, section_id, payload, headers):
        return self._request("POST", f"/v1/service-scores/{section_id}/close", payload, headers)

    # --- Logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Governance catalogues (operator configuration) ---------------------
    def list_supported_models(self, headers):
        return self._request("GET", "/v1/supported-models", headers=headers)

    def register_supported_model(self, payload, headers):
        return self._request("POST", "/v1/supported-models", payload, headers)

    def restrict_model(self, model_code, payload, headers):
        return self._request("POST", f"/v1/supported-models/{model_code}/restriction", payload, headers)

    def list_blocklist(self, kind, headers):
        return self._request("GET", f"/v1/blocklists/{kind}", headers=headers)

    def add_blocklist_entry(self, kind, imei, headers):
        return self._request("POST", f"/v1/blocklists/{kind}", {"imei": imei}, headers)


api_client = ApiClient()