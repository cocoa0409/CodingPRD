"""API client: one method per endpoint defined in the PRD endpoint table.

The clock capability is a platform-level endpoint and lives outside the
/ptab prefix (PRD §2.4), so set_clock uses its bare path.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Platform clock (unprefixed, PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Parties ---
    def create_party(self, payload, headers):
        return self._request("POST", "/ptab/parties", payload, headers)

    # --- Patents ---
    def create_patent(self, payload, headers):
        return self._request("POST", "/ptab/patents", payload, headers)

    def list_patents(self, headers, params=None):
        return self._request("GET", "/ptab/patents", headers=headers, params=params)

    def get_patent(self, patent_id, headers):
        return self._request("GET", f"/ptab/patents/{patent_id}", headers=headers)

    # --- Litigation matters ---
    def create_litigation_matter(self, patent_id, payload, headers):
        return self._request(
            "POST", f"/ptab/patents/{patent_id}/litigation-matters", payload, headers
        )

    def list_litigation_matters(self, headers, params=None):
        return self._request(
            "GET", "/ptab/litigation-matters", headers=headers, params=params
        )

    def get_litigation_matter(self, matter_id, headers):
        return self._request(
            "GET", f"/ptab/litigation-matters/{matter_id}", headers=headers
        )

    def patch_litigation_matter(self, matter_id, payload, headers):
        return self._request(
            "PATCH", f"/ptab/litigation-matters/{matter_id}", payload, headers
        )

    # --- Petitions ---
    def create_petition(self, payload, headers):
        return self._request("POST", "/ptab/petitions", payload, headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", "/ptab/petitions", headers=headers, params=params)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/ptab/petitions/{petition_id}", headers=headers)

    def accord_filing_date(self, petition_id, headers):
        return self._request(
            "POST", f"/ptab/petitions/{petition_id}/accord-filing-date", {}, headers
        )

    def decide_institution(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/ptab/petitions/{petition_id}/decide-institution", payload, headers
        )

    def get_institution_decision(self, petition_id, headers):
        return self._request(
            "GET", f"/ptab/petitions/{petition_id}/institution-decision", headers=headers
        )

    # --- Proceedings ---
    def list_proceedings(self, headers, params=None):
        return self._request("GET", "/ptab/proceedings", headers=headers, params=params)

    def get_proceeding(self, proceeding_id, headers):
        return self._request(
            "GET", f"/ptab/proceedings/{proceeding_id}", headers=headers
        )

    def create_brief(self, proceeding_id, payload, headers):
        return self._request(
            "POST", f"/ptab/proceedings/{proceeding_id}/briefs", payload, headers
        )

    def list_briefs(self, proceeding_id, headers):
        return self._request(
            "GET", f"/ptab/proceedings/{proceeding_id}/briefs", headers=headers
        )

    def get_brief(self, brief_id, headers):
        return self._request("GET", f"/ptab/briefs/{brief_id}", headers=headers)

    # --- Expert declarations ---
    def create_expert_declaration(self, brief_id, payload, headers):
        return self._request(
            "POST", f"/ptab/briefs/{brief_id}/expert-declarations", payload, headers
        )

    def list_expert_declarations(self, brief_id, headers):
        return self._request(
            "GET", f"/ptab/briefs/{brief_id}/expert-declarations", headers=headers
        )

    # --- Discovery ---
    def create_discovery_request(self, proceeding_id, payload, headers):
        return self._request(
            "POST", f"/ptab/proceedings/{proceeding_id}/discovery-requests",
            payload, headers,
        )

    def list_discovery_requests(self, proceeding_id, headers):
        return self._request(
            "GET", f"/ptab/proceedings/{proceeding_id}/discovery-requests",
            headers=headers,
        )

    def rule_discovery_request(self, request_id, headers):
        return self._request(
            "POST", f"/ptab/discovery-requests/{request_id}/rule", {}, headers
        )

    # --- Amendment motions ---
    def create_amendment_motion(self, proceeding_id, payload, headers):
        return self._request(
            "POST", f"/ptab/proceedings/{proceeding_id}/amendment-motions",
            payload, headers,
        )

    def list_amendment_motions(self, proceeding_id, headers):
        return self._request(
            "GET", f"/ptab/proceedings/{proceeding_id}/amendment-motions",
            headers=headers,
        )

    def resolve_amendment_motion(self, motion_id, payload, headers):
        return self._request(
            "POST", f"/ptab/amendment-motions/{motion_id}/resolve", payload, headers
        )

    # --- Extension requests ---
    def create_extension_request(self, proceeding_id, payload, headers):
        return self._request(
            "POST", f"/ptab/proceedings/{proceeding_id}/extension-requests",
            payload, headers,
        )

    # --- Oral hearings ---
    def create_oral_hearing(self, proceeding_id, payload, headers):
        return self._request(
            "POST", f"/ptab/proceedings/{proceeding_id}/oral-hearings", payload, headers
        )

    def list_oral_hearings(self, headers, params=None):
        return self._request("GET", "/ptab/oral-hearings", headers=headers, params=params)

    def get_oral_hearing(self, hearing_id, headers):
        return self._request(
            "GET", f"/ptab/oral-hearings/{hearing_id}", headers=headers
        )

    def schedule_oral_hearing(self, hearing_id, payload, headers):
        return self._request(
            "PATCH", f"/ptab/oral-hearings/{hearing_id}", payload, headers
        )

    def resolve_oral_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/ptab/oral-hearings/{hearing_id}/resolve", payload, headers
        )

    # --- Final written decisions ---
    def create_final_decision(self, proceeding_id, payload, headers):
        return self._request(
            "POST", f"/ptab/proceedings/{proceeding_id}/final-decisions",
            payload, headers,
        )

    def list_final_decisions(self, proceeding_id, headers):
        return self._request(
            "GET", f"/ptab/proceedings/{proceeding_id}/final-decisions", headers=headers
        )

    # --- Appeals ---
    def create_appeal(self, proceeding_id, headers):
        return self._request(
            "POST", f"/ptab/proceedings/{proceeding_id}/appeals", {}, headers
        )

    def list_appeals(self, proceeding_id, headers):
        return self._request(
            "GET", f"/ptab/proceedings/{proceeding_id}/appeals", headers=headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/ptab/appeals/{appeal_id}/decide", payload, headers
        )

    # --- Hearing rooms ---
    def create_hearing_room(self, payload, headers):
        return self._request("POST", "/ptab/hearing-rooms", payload, headers)


api_client = ApiClient()
