"""API client: one method per endpoint defined in PRD §4 (all under /stb)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/stb/_clock/set_current_utc", payload, headers)

    # --- carriers ---
    def create_carrier(self, payload, headers):
        return self._request("POST", "/stb/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/stb/carriers/{carrier_id}", headers=headers)

    def list_carrier_findings(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/stb/carriers/{carrier_id}/revenue-adequacy-findings",
            headers=headers, params=params)

    def list_carrier_rate_complaints(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/stb/carriers/{carrier_id}/rate-complaints",
            headers=headers, params=params)

    def list_carrier_service_complaints(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/stb/carriers/{carrier_id}/service-complaints",
            headers=headers, params=params)

    def list_carrier_esos(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/stb/carriers/{carrier_id}/emergency-service-orders",
            headers=headers, params=params)

    def list_carrier_mergers(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/stb/carriers/{carrier_id}/merger-applications",
            headers=headers, params=params)

    def list_carrier_abandonments(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/stb/carriers/{carrier_id}/abandonment-applications",
            headers=headers, params=params)

    def list_carrier_petitions(self, carrier_id, headers, params=None):
        return self._request(
            "GET", f"/stb/carriers/{carrier_id}/reciprocal-switching-petitions",
            headers=headers, params=params)

    def create_finding(self, carrier_id, payload, headers):
        return self._request(
            "POST", f"/stb/carriers/{carrier_id}/revenue-adequacy-findings",
            payload, headers)

    # --- rate complaints ---
    def create_rate_complaint(self, payload, headers):
        return self._request("POST", "/stb/rate-complaints", payload, headers)

    def get_rate_complaint(self, complaint_id, headers):
        return self._request(
            "GET", f"/stb/rate-complaints/{complaint_id}", headers=headers)

    def determine_market_dominance(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/stb/rate-complaints/{complaint_id}/determine-market-dominance",
            payload, headers)

    def submit_evidence(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/stb/rate-complaints/{complaint_id}/evidence", payload, headers)

    def list_evidence(self, complaint_id, headers, params=None):
        return self._request(
            "GET", f"/stb/rate-complaints/{complaint_id}/evidence",
            headers=headers, params=params)

    def verify_evidence(self, evidence_id, payload, headers):
        return self._request(
            "POST", f"/stb/evidence-submissions/{evidence_id}/verify",
            payload, headers)

    def decide_rate_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/stb/rate-complaints/{complaint_id}/decide", payload, headers)

    def reopen_rate_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/stb/rate-complaints/{complaint_id}/reopen", payload, headers)

    def post_reparation_event(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"/stb/rate-complaints/{complaint_id}/reparation-events",
            payload, headers)

    # --- service complaints / emergency service orders ---
    def create_service_complaint(self, payload, headers):
        return self._request("POST", "/stb/service-complaints", payload, headers)

    def get_service_complaint(self, sc_id, headers):
        return self._request(
            "GET", f"/stb/service-complaints/{sc_id}", headers=headers)

    def list_service_complaint_esos(self, sc_id, headers, params=None):
        return self._request(
            "GET", f"/stb/service-complaints/{sc_id}/emergency-service-orders",
            headers=headers, params=params)

    def resolve_service_complaint(self, sc_id, payload, headers):
        return self._request(
            "POST", f"/stb/service-complaints/{sc_id}/resolve", payload, headers)

    def escalate_service_complaint(self, sc_id, payload, headers):
        return self._request(
            "POST", f"/stb/service-complaints/{sc_id}/escalate", payload, headers)

    # --- merger applications / service assurance plans ---
    def create_merger_application(self, payload, headers):
        return self._request("POST", "/stb/merger-applications", payload, headers)

    def get_merger_application(self, merger_id, headers):
        return self._request(
            "GET", f"/stb/merger-applications/{merger_id}", headers=headers)

    def amend_merger_application(self, merger_id, payload, headers):
        return self._request(
            "POST", f"/stb/merger-applications/{merger_id}/amend", payload, headers)

    def decide_merger_application(self, merger_id, payload, headers):
        return self._request(
            "POST", f"/stb/merger-applications/{merger_id}/decide", payload, headers)

    def create_service_assurance_plan(self, merger_id, payload, headers):
        return self._request(
            "POST", f"/stb/merger-applications/{merger_id}/service-assurance-plans",
            payload, headers)

    def list_service_assurance_plans(self, merger_id, headers, params=None):
        return self._request(
            "GET", f"/stb/merger-applications/{merger_id}/service-assurance-plans",
            headers=headers, params=params)

    # --- abandonment applications ---
    def create_abandonment_application(self, payload, headers):
        return self._request("POST", "/stb/abandonment-applications", payload, headers)

    def get_abandonment_application(self, ab_id, headers):
        return self._request(
            "GET", f"/stb/abandonment-applications/{ab_id}", headers=headers)

    def decide_abandonment(self, ab_id, payload, headers):
        return self._request(
            "POST", f"/stb/abandonment-applications/{ab_id}/decide", payload, headers)

    def issue_trail_use_notice(self, ab_id, payload, headers):
        return self._request(
            "POST", f"/stb/abandonment-applications/{ab_id}/issue-trail-use-notice",
            payload, headers)

    def convert_to_trail_use(self, ab_id, payload, headers):
        return self._request(
            "POST", f"/stb/abandonment-applications/{ab_id}/convert-to-trail-use",
            payload, headers)

    def consummate_abandonment(self, ab_id, payload, headers):
        return self._request(
            "POST", f"/stb/abandonment-applications/{ab_id}/consummate-abandonment",
            payload, headers)

    # --- reciprocal switching petitions ---
    def create_petition(self, payload, headers):
        return self._request(
            "POST", "/stb/reciprocal-switching-petitions", payload, headers)

    def decide_petition(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/stb/reciprocal-switching-petitions/{petition_id}/decide",
            payload, headers)

    def terminate_petition(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/stb/reciprocal-switching-petitions/{petition_id}/terminate",
            payload, headers)


api_client = ApiClient()
