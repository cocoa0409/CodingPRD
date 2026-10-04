"""API client: one method per endpoint defined in PRD §4.

Paths are written exactly as PRD §4 lists them. The platform logical clock
(POST /_clock/set_current_utc) deliberately lives OUTSIDE the
/battery-ecosystem prefix (PRD §2.5).
"""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/battery-ecosystem"
CLOCK_PATH = "/_clock/set_current_utc"  # outside the API prefix, per PRD §2.5


class ApiClient(GenericApiClient):
    # --- platform & catalog ---
    def create_platform(self, payload, headers):
        return self._request("POST", f"{BASE}/battery-platforms", payload, headers)

    def create_pack(self, payload, headers):
        return self._request("POST", f"{BASE}/battery-packs", payload, headers)

    def get_pack(self, pack_id, headers, params=None):
        return self._request("GET", f"{BASE}/battery-packs/{pack_id}", headers=headers, params=params)

    def list_packs(self, headers, params=None):
        return self._request("GET", f"{BASE}/battery-packs", headers=headers, params=params)

    def submit_pack_certification(self, pack_id, headers):
        return self._request("POST", f"{BASE}/battery-packs/{pack_id}/submit-certification", {}, headers)

    def decide_pack_certification(self, pack_id, payload, headers):
        return self._request("POST", f"{BASE}/battery-packs/{pack_id}/decide-certification", payload, headers)

    def list_pack_counterfeit_cases(self, pack_id, headers, params=None):
        return self._request("GET", f"{BASE}/battery-packs/{pack_id}/counterfeit-cases", headers=headers, params=params)

    def create_charger(self, payload, headers):
        return self._request("POST", f"{BASE}/chargers", payload, headers)

    def get_charger(self, charger_id, headers):
        return self._request("GET", f"{BASE}/chargers/{charger_id}", headers=headers)

    def list_chargers(self, headers, params=None):
        return self._request("GET", f"{BASE}/chargers", headers=headers, params=params)

    # --- tool development ---
    def create_tool_model(self, payload, headers):
        return self._request("POST", f"{BASE}/tool-models", payload, headers)

    def get_tool_model(self, tool_id, headers):
        return self._request("GET", f"{BASE}/tool-models/{tool_id}", headers=headers)

    def list_tool_models(self, headers, params=None):
        return self._request("GET", f"{BASE}/tool-models", headers=headers, params=params)

    def transition_tool_model(self, tool_id, payload, headers):
        return self._request("POST", f"{BASE}/tool-models/{tool_id}/transition", payload, headers)

    def list_tool_insights(self, tool_id, headers, params=None):
        return self._request("GET", f"{BASE}/tool-models/{tool_id}/insights", headers=headers, params=params)

    def create_insight(self, payload, headers):
        return self._request("POST", f"{BASE}/insights", payload, headers)

    def decide_insight(self, insight_id, payload, headers):
        return self._request("POST", f"{BASE}/insights/{insight_id}/decide", payload, headers)

    # --- service network & One-Key accounts ---
    def create_service_center(self, payload, headers):
        return self._request("POST", f"{BASE}/service-centers", payload, headers)

    def create_asset_account(self, payload, headers):
        return self._request("POST", f"{BASE}/asset-accounts", payload, headers)

    def create_tracked_asset(self, payload, headers):
        return self._request("POST", f"{BASE}/tracked-assets", payload, headers)

    def get_tracked_asset(self, asset_id, headers):
        return self._request("GET", f"{BASE}/tracked-assets/{asset_id}", headers=headers)

    def list_tracked_assets(self, headers, params=None):
        return self._request("GET", f"{BASE}/tracked-assets", headers=headers, params=params)

    def customize_tracked_asset(self, asset_id, payload, headers):
        return self._request("POST", f"{BASE}/tracked-assets/{asset_id}/customize", payload, headers)

    def transition_tracked_asset(self, asset_id, payload, headers):
        return self._request("POST", f"{BASE}/tracked-assets/{asset_id}/transition", payload, headers)

    # --- warranty ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{BASE}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"{BASE}/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", f"{BASE}/warranty-claims", headers=headers, params=params)

    def adjudicate_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{BASE}/warranty-claims/{claim_id}/adjudicate", payload, headers)

    def complete_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"{BASE}/warranty-claims/{claim_id}/complete", {}, headers)

    # --- distribution ---
    def create_channel_partner(self, payload, headers):
        return self._request("POST", f"{BASE}/channel-partners", payload, headers)

    def create_listing(self, payload, headers):
        return self._request("POST", f"{BASE}/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"{BASE}/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", f"{BASE}/listings", headers=headers, params=params)

    def transition_listing(self, listing_id, payload, headers):
        return self._request("POST", f"{BASE}/listings/{listing_id}/transition", payload, headers)

    # --- counterfeit & safety communication ---
    def create_counterfeit_case(self, payload, headers):
        return self._request("POST", f"{BASE}/counterfeit-cases", payload, headers)

    def resolve_counterfeit_case(self, case_id, payload, headers):
        return self._request("POST", f"{BASE}/counterfeit-cases/{case_id}/resolve", payload, headers)

    def create_safety_bulletin(self, payload, headers):
        return self._request("POST", f"{BASE}/safety-bulletins", payload, headers)

    def get_safety_bulletin(self, bulletin_id, headers):
        return self._request("GET", f"{BASE}/safety-bulletins/{bulletin_id}", headers=headers)

    def list_safety_bulletins(self, headers, params=None):
        return self._request("GET", f"{BASE}/safety-bulletins", headers=headers, params=params)

    # --- platform logical clock (OUTSIDE the API prefix, PRD §2.5) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
