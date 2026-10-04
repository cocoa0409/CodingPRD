"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock (PlatformAdmin) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Clubs ---
    def create_club(self, payload, headers):
        return self._request("POST", "/clubs", payload, headers)

    def get_club(self, club_id, headers):
        return self._request("GET", f"/clubs/{club_id}", headers=headers)

    def update_club(self, club_id, payload, headers):
        return self._request("PATCH", f"/clubs/{club_id}", payload, headers)

    def set_connectivity(self, club_id, posture, headers):
        return self._request(
            "POST", f"/clubs/{club_id}/connectivity", {"posture": posture}, headers,
        )

    def run_closeout(self, club_id, headers):
        return self._request("POST", f"/clubs/{club_id}/run-closeout", {}, headers)

    # --- Catalog items ---
    def create_catalog_item(self, club_id, payload, headers):
        return self._request("POST", f"/clubs/{club_id}/catalog-items", payload, headers)

    def get_catalog_item(self, item_id, headers):
        return self._request("GET", f"/catalog-items/{item_id}", headers=headers)

    def update_catalog_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/catalog-items/{item_id}", payload, headers)

    def list_club_catalog_items(self, club_id, headers, params=None):
        return self._request(
            "GET", f"/clubs/{club_id}/catalog-items", headers=headers, params=params,
        )

    def list_catalog_item_scan_lines(self, item_id, headers, params=None):
        return self._request(
            "GET", f"/catalog-items/{item_id}/scan-lines", headers=headers, params=params,
        )

    # --- Instant savings offers ---
    def create_instant_savings_offer(self, club_id, payload, headers):
        return self._request(
            "POST", f"/clubs/{club_id}/instant-savings-offers", payload, headers,
        )

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/instant-savings-offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/instant-savings-offers", headers=headers, params=params)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def list_member_scan_sessions(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/scan-sessions", headers=headers, params=params,
        )

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers)

    def settle_rewards(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/rewards/settle", {}, headers)

    # --- Scan sessions ---
    def create_scan_session(self, club_id, headers):
        return self._request("POST", "/scan-sessions", {"club_id": club_id}, headers)

    def get_scan_session(self, session_id, headers):
        return self._request("GET", f"/scan-sessions/{session_id}", headers=headers)

    def list_scan_sessions(self, headers, params=None):
        return self._request("GET", "/scan-sessions", headers=headers, params=params)

    def scan_line(self, session_id, payload, headers):
        return self._request("POST", f"/scan-sessions/{session_id}/lines", payload, headers)

    def list_session_lines(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/scan-sessions/{session_id}/lines", headers=headers, params=params,
        )

    def get_scan_line(self, line_id, headers):
        return self._request("GET", f"/scan-lines/{line_id}", headers=headers)

    def remove_scan_line(self, line_id, headers):
        return self._request("POST", f"/scan-lines/{line_id}/remove", {}, headers)

    def pay_session(self, session_id, headers):
        return self._request("POST", f"/scan-sessions/{session_id}/pay", {}, headers)

    def void_payment(self, session_id, headers):
        return self._request("POST", f"/scan-sessions/{session_id}/void-payment", {}, headers)

    def exit_scan(self, session_id, headers, method=None):
        payload = {} if method is None else {"method": method}
        return self._request(
            "POST", f"/scan-sessions/{session_id}/exit-scan", payload, headers,
        )

    def abandon_session(self, session_id, headers):
        return self._request("POST", f"/scan-sessions/{session_id}/abandon", {}, headers)

    # --- Restricted intercepts ---
    def list_session_intercepts(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/scan-sessions/{session_id}/intercepts", headers=headers, params=params,
        )

    def get_intercept(self, intercept_id, headers):
        return self._request("GET", f"/intercepts/{intercept_id}", headers=headers)

    def list_intercepts(self, headers, params=None):
        return self._request("GET", "/intercepts", headers=headers, params=params)

    def resolve_intercept(self, intercept_id, payload, headers):
        return self._request(
            "POST", f"/intercepts/{intercept_id}/resolve", payload, headers,
        )

    # --- Exit verifications ---
    def list_session_exit_verifications(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/scan-sessions/{session_id}/exit-verifications",
            headers=headers, params=params,
        )

    def get_exit_verification(self, verification_id, headers):
        return self._request(
            "GET", f"/exit-verifications/{verification_id}", headers=headers,
        )

    def list_exit_verifications(self, headers, params=None):
        return self._request("GET", "/exit-verifications", headers=headers, params=params)

    def verify_receipt(self, verification_id, receipt_code, headers):
        return self._request(
            "POST", f"/exit-verifications/{verification_id}/verify-receipt",
            {"receipt_code": receipt_code}, headers,
        )

    def cv_report(self, verification_id, observed_item_count, headers):
        return self._request(
            "POST", f"/exit-verifications/{verification_id}/cv-report",
            {"observed_item_count": observed_item_count}, headers,
        )

    def resolve_mismatch(self, verification_id, action, headers):
        return self._request(
            "POST", f"/exit-verifications/{verification_id}/resolve-mismatch",
            {"action": action}, headers,
        )

    # --- Loss prevention cases ---
    def get_lp_case(self, case_id, headers):
        return self._request("GET", f"/loss-prevention-cases/{case_id}", headers=headers)

    def list_lp_cases(self, headers, params=None):
        return self._request("GET", "/loss-prevention-cases", headers=headers, params=params)

    def acknowledge_lp_case(self, case_id, headers):
        return self._request(
            "POST", f"/loss-prevention-cases/{case_id}/acknowledge", {}, headers,
        )

    def escalate_lp_case(self, case_id, headers):
        return self._request(
            "POST", f"/loss-prevention-cases/{case_id}/escalate", {}, headers,
        )

    def resolve_lp_case(self, case_id, outcome, headers):
        return self._request(
            "POST", f"/loss-prevention-cases/{case_id}/resolve", {"outcome": outcome}, headers,
        )

    # --- Curbside orders ---
    def create_curbside_order(self, club_id, item_count, headers):
        return self._request(
            "POST", f"/clubs/{club_id}/curbside-orders", {"item_count": item_count}, headers,
        )

    def get_curbside_order(self, order_id, headers):
        return self._request("GET", f"/curbside-orders/{order_id}", headers=headers)

    def list_curbside_orders(self, headers, params=None):
        return self._request("GET", "/curbside-orders", headers=headers, params=params)

    def list_club_curbside_orders(self, club_id, headers, params=None):
        return self._request(
            "GET", f"/clubs/{club_id}/curbside-orders", headers=headers, params=params,
        )

    def stage_curbside_order(self, order_id, payload, headers):
        return self._request("POST", f"/curbside-orders/{order_id}/stage", payload, headers)

    def mark_staged(self, order_id, headers):
        return self._request("POST", f"/curbside-orders/{order_id}/mark-staged", {}, headers)

    def pickup_curbside_order(self, order_id, headers):
        return self._request("POST", f"/curbside-orders/{order_id}/pickup", {}, headers)

    def cancel_curbside_order(self, order_id, headers):
        return self._request("POST", f"/curbside-orders/{order_id}/cancel", {}, headers)

    def reschedule_curbside_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/curbside-orders/{order_id}/reschedule", payload, headers,
        )


api_client = ApiClient()
