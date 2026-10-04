"""API client: one method per endpoint defined in the PRD.

The base ``_request()`` is inherited from the framework's GenericApiClient.
For GET/DELETE the framework passes the payload dict as query params; for
POST/PUT it is sent as the JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock / payment simulation (test-driving) ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def simulate_payment(self, subscription_id, outcome, headers):
        return self._request(
            "POST",
            "/_payments/simulate",
            {"subscription_id": subscription_id, "outcome": outcome},
            headers,
        )

    # --- Rights grants ---
    def create_rights_grant(self, payload, headers):
        return self._request("POST", "/rights-grants", payload, headers)

    def list_rights_grants(self, headers, params=None):
        return self._request("GET", "/rights-grants", params or {}, headers)

    def get_rights_grant(self, grant_id, headers):
        return self._request("GET", f"/rights-grants/{grant_id}", headers=headers)

    def terminate_rights_grant(self, grant_id, headers):
        return self._request(
            "POST", f"/rights-grants/{grant_id}/terminate", {}, headers
        )

    # --- Seasons ---
    def create_season(self, payload, headers):
        return self._request("POST", "/seasons", payload, headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/seasons", params or {}, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def advance_season_phase(self, season_id, expected_season_version, headers):
        return self._request(
            "POST",
            f"/seasons/{season_id}/advance-phase",
            {"expected_season_version": expected_season_version},
            headers,
        )

    # --- Markets ---
    def create_market(self, payload, headers):
        return self._request("POST", "/markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/markets", params or {}, headers)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/markets/{market_id}", headers=headers)

    # --- Games ---
    def create_game(self, payload, headers):
        return self._request("POST", "/games", payload, headers)

    def list_games(self, headers, params=None):
        return self._request("GET", "/games", params or {}, headers)

    def get_game(self, game_id, headers):
        return self._request("GET", f"/games/{game_id}", headers=headers)

    # --- Week slates ---
    def create_week_slate(self, payload, headers):
        return self._request("POST", "/week-slates", payload, headers)

    def list_week_slates(self, headers, params=None):
        return self._request("GET", "/week-slates", params or {}, headers)

    def get_week_slate(self, slate_id, headers):
        return self._request("GET", f"/week-slates/{slate_id}", headers=headers)

    def slate_selection(self, slate_id, game_id, action, expected_slate_version, headers):
        return self._request(
            "POST",
            f"/week-slates/{slate_id}/selections",
            {
                "game_id": game_id,
                "action": action,
                "expected_slate_version": expected_slate_version,
            },
            headers,
        )

    def finalize_week_slate(self, slate_id, expected_slate_version, headers):
        return self._request(
            "POST",
            f"/week-slates/{slate_id}/finalize",
            {"expected_slate_version": expected_slate_version},
            headers,
        )

    def reopen_week_slate(self, slate_id, headers):
        return self._request("POST", f"/week-slates/{slate_id}/reopen", {}, headers)

    def lock_week_slate(self, slate_id, headers):
        return self._request("POST", f"/week-slates/{slate_id}/lock", {}, headers)

    # --- Offers ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/offers", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", params or {}, headers)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/offers/{offer_id}/withdraw", {}, headers)

    # --- Accounts ---
    def register_account(self, payload, headers):
        return self._request("POST", "/accounts/register", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", params or {}, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def update_account(self, account_id, payload, headers):
        return self._request("PUT", f"/accounts/{account_id}", payload, headers)

    def flag_commercial_misuse(self, account_id, reason, headers):
        return self._request(
            "POST",
            f"/accounts/{account_id}/flag-commercial-misuse",
            {"reason": reason},
            headers,
        )

    def clear_commercial_flag(self, account_id, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/clear-commercial-flag", {}, headers
        )

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    # --- Student verifications ---
    def create_student_verification(self, payload, headers):
        return self._request("POST", "/student-verifications", payload, headers)

    def list_student_verifications(self, headers, params=None):
        return self._request("GET", "/student-verifications", params or {}, headers)

    def get_student_verification(self, sv_id, headers):
        return self._request(
            "GET", f"/student-verifications/{sv_id}", headers=headers
        )

    def revoke_student_verification(self, sv_id, headers):
        return self._request(
            "POST", f"/student-verifications/{sv_id}/revoke", {}, headers
        )

    # --- Venue licenses ---
    def create_venue_license(self, payload, headers):
        return self._request("POST", "/venue-licenses", payload, headers)

    def list_venue_licenses(self, headers, params=None):
        return self._request("GET", "/venue-licenses", params or {}, headers)

    def get_venue_license(self, license_id, headers):
        return self._request("GET", f"/venue-licenses/{license_id}", headers=headers)

    def certify_venue_license(self, license_id, headers):
        return self._request(
            "POST", f"/venue-licenses/{license_id}/certify", {}, headers
        )

    def recertify_venue_license(self, license_id, fire_code_occupancy, headers):
        return self._request(
            "POST",
            f"/venue-licenses/{license_id}/recertify",
            {"fire_code_occupancy": fire_code_occupancy},
            headers,
        )

    def suspend_venue_license(self, license_id, headers):
        return self._request(
            "POST", f"/venue-licenses/{license_id}/suspend", {}, headers
        )

    def reinstate_venue_license(self, license_id, headers):
        return self._request(
            "POST", f"/venue-licenses/{license_id}/reinstate", {}, headers
        )

    def revoke_venue_license(self, license_id, headers):
        return self._request(
            "POST", f"/venue-licenses/{license_id}/revoke", {}, headers
        )

    # --- Subscriptions ---
    def create_subscription(self, account_id, offer_id, headers):
        return self._request(
            "POST",
            "/subscriptions",
            {"account_id": account_id, "offer_id": offer_id},
            headers,
        )

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", params or {}, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cancel", {}, headers
        )

    def suspend_entitlement(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/suspend-entitlement", {}, headers
        )

    def restore_entitlement(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/restore-entitlement", {}, headers
        )

    def get_subscription_features(self, subscription_id, headers):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/features", headers=headers
        )

    def list_subscription_payments(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/subscriptions/{subscription_id}/payments",
            params or {},
            headers,
        )

    # --- Territory checks ---
    def create_territory_check(self, account_id, subscription_id, game_id, device_zip, headers):
        return self._request(
            "POST",
            "/territory-checks",
            {
                "account_id": account_id,
                "subscription_id": subscription_id,
                "game_id": game_id,
                "device_zip": device_zip,
            },
            headers,
        )

    def list_territory_checks(self, headers, params=None):
        return self._request("GET", "/territory-checks", params or {}, headers)

    def get_territory_check(self, check_id, headers):
        return self._request("GET", f"/territory-checks/{check_id}", headers=headers)

    # --- Game entitlements ---
    def list_game_entitlements(self, headers, params=None):
        return self._request("GET", "/game-entitlements", params or {}, headers)

    def get_game_entitlement(self, entitlement_id, headers):
        return self._request(
            "GET", f"/game-entitlements/{entitlement_id}", headers=headers
        )

    # --- Complaint cases ---
    def create_complaint_case(self, account_id, subscription_id, game_id, category, detail, headers):
        return self._request(
            "POST",
            "/complaint-cases",
            {
                "account_id": account_id,
                "subscription_id": subscription_id,
                "game_id": game_id,
                "category": category,
                "detail": detail,
            },
            headers,
        )

    def list_complaint_cases(self, headers, params=None):
        return self._request("GET", "/complaint-cases", params or {}, headers)

    def get_complaint_case(self, case_id, headers):
        return self._request("GET", f"/complaint-cases/{case_id}", headers=headers)

    def resolve_complaint_case(self, case_id, decision, note, headers):
        return self._request(
            "POST",
            f"/complaint-cases/{case_id}/resolve",
            {"decision": decision, "note": note},
            headers,
        )

    def escalate_complaint_case(self, case_id, headers):
        return self._request(
            "POST", f"/complaint-cases/{case_id}/escalate", {}, headers
        )

    def deescalate_complaint_case(self, case_id, headers):
        return self._request(
            "POST", f"/complaint-cases/{case_id}/deescalate", {}, headers
        )

    # --- Entitlement overrides ---
    def create_entitlement_override(self, account_id, game_id, reason_code, headers):
        return self._request(
            "POST",
            "/entitlement-overrides",
            {
                "account_id": account_id,
                "game_id": game_id,
                "reason_code": reason_code,
            },
            headers,
        )

    def list_entitlement_overrides(self, headers, params=None):
        return self._request("GET", "/entitlement-overrides", params or {}, headers)

    def get_entitlement_override(self, override_id, headers):
        return self._request(
            "GET", f"/entitlement-overrides/{override_id}", headers=headers
        )

    def rescind_entitlement_override(self, override_id, headers):
        return self._request(
            "POST", f"/entitlement-overrides/{override_id}/rescind", {}, headers
        )

    # --- Multiview sessions ---
    def start_multiview_session(self, subscription_id, headers):
        return self._request(
            "POST", "/multiview-sessions", {"subscription_id": subscription_id}, headers
        )

    def end_multiview_session(self, session_id, headers):
        return self._request(
            "POST", f"/multiview-sessions/{session_id}/end", {}, headers
        )


api_client = ApiClient()
