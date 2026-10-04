"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # --- accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/api/accounts", payload, headers)

    # --- points of presence ---
    def create_pop(self, payload, headers):
        return self._request("POST", "/api/pops", payload, headers)

    def get_pop(self, pop_id, headers, params=None):
        return self._request("GET", f"/api/pops/{pop_id}", headers=headers, params=params)

    def add_maintenance_window(self, pop_id, payload, headers):
        return self._request(
            "POST", f"/api/pops/{pop_id}/maintenance-windows", payload, headers
        )

    # --- zones ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/api/zones", payload, headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/api/zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/api/zones/{zone_id}", headers=headers)

    def patch_zone(self, zone_id, payload, headers):
        return self._request("PATCH", f"/api/zones/{zone_id}", payload, headers)

    def verify_zone(self, zone_id, headers):
        return self._request("POST", f"/api/zones/{zone_id}/verify", {}, headers)

    def delete_zone(self, zone_id, headers):
        return self._request("DELETE", f"/api/zones/{zone_id}", headers=headers)

    # --- traffic hits / bot classification / honeypots ---
    def record_traffic_hit(self, zone_id, payload, headers):
        return self._request("POST", f"/api/zones/{zone_id}/traffic-hits", payload, headers)

    def create_bot_classification(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/api/zones/{zone_id}/bot-classifications", payload, headers
        )

    def add_honeypot(self, zone_id, payload, headers):
        return self._request("POST", f"/api/zones/{zone_id}/honeypots", payload, headers)

    def record_honeypot_hit(self, zone_id, payload, headers):
        return self._request(
            "POST", f"/api/zones/{zone_id}/honeypot-hits", payload, headers
        )

    # --- DDoS events ---
    def create_ddos_event(self, zone_id, payload, headers):
        return self._request("POST", f"/api/zones/{zone_id}/ddos-events", payload, headers)

    def list_ddos_events(self, headers, params=None):
        return self._request("GET", "/api/ddos-events", headers=headers, params=params)

    def get_ddos_event(self, event_id, headers):
        return self._request("GET", f"/api/ddos-events/{event_id}", headers=headers)

    # --- purge requests ---
    def create_purge_request(self, payload, headers):
        return self._request("POST", "/api/purge-requests", payload, headers)

    def list_purge_requests(self, headers, params=None):
        return self._request("GET", "/api/purge-requests", headers=headers, params=params)

    def get_purge_request(self, purge_id, headers):
        return self._request("GET", f"/api/purge-requests/{purge_id}", headers=headers)

    # --- IP blocks ---
    def create_ip_block(self, payload, headers):
        return self._request("POST", "/api/ip-blocks", payload, headers)

    def list_ip_blocks(self, headers, params=None):
        return self._request("GET", "/api/ip-blocks", headers=headers, params=params)

    def get_ip_block(self, block_id, headers):
        return self._request("GET", f"/api/ip-blocks/{block_id}", headers=headers)

    def confirm_ip_block(self, block_id, headers):
        return self._request("POST", f"/api/ip-blocks/{block_id}/confirm", {}, headers)

    def extend_ip_block(self, block_id, payload, headers):
        return self._request("PATCH", f"/api/ip-blocks/{block_id}", payload, headers)

    # --- abuse reports ---
    def create_abuse_report(self, payload, headers):
        return self._request("POST", "/api/abuse-reports", payload, headers)

    def list_abuse_reports(self, headers, params=None):
        return self._request("GET", "/api/abuse-reports", headers=headers, params=params)

    def get_abuse_report(self, report_id, headers):
        return self._request("GET", f"/api/abuse-reports/{report_id}", headers=headers)

    def claim_abuse_report(self, report_id, headers):
        return self._request("POST", f"/api/abuse-reports/{report_id}/claim", {}, headers)

    def close_abuse_report(self, report_id, headers):
        return self._request("POST", f"/api/abuse-reports/{report_id}/close", {}, headers)

    def disposition_abuse_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/api/abuse-reports/{report_id}/disposition", payload, headers
        )


api_client = ApiClient()
