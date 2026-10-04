"""API client: one method per operation in the PRD's endpoint table."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Regions ──────────────────────────────────────
    def create_region(self, payload, headers):
        return self._request("POST", "/corps/regions", payload, headers)

    # ─── Partner districts ────────────────────────────
    def create_partner_district(self, payload, headers):
        return self._request("POST", "/corps/partner-districts", payload, headers)

    def list_partner_districts(self, headers, params=None):
        return self._request("GET", "/corps/partner-districts", payload=params, headers=headers)

    def get_partner_district(self, district_id, headers, projection=None):
        params = {"projection": projection} if projection else None
        return self._request(
            "GET", f"/corps/partner-districts/{district_id}", payload=params, headers=headers
        )

    def set_partner_district_status(self, district_id, to_status, headers):
        return self._request(
            "POST",
            f"/corps/partner-districts/{district_id}/status",
            {"to_status": to_status},
            headers,
        )

    def list_district_schools(self, district_id, headers, params=None):
        return self._request(
            "GET",
            f"/corps/partner-districts/{district_id}/partner-schools",
            payload=params,
            headers=headers,
        )

    # ─── Partner schools ──────────────────────────────
    def create_partner_school(self, payload, headers):
        return self._request("POST", "/corps/partner-schools", payload, headers)

    def get_partner_school(self, school_id, headers):
        return self._request("GET", f"/corps/partner-schools/{school_id}", headers=headers)

    def list_school_placements(self, school_id, headers, params=None):
        return self._request(
            "GET", f"/corps/partner-schools/{school_id}/placements", payload=params, headers=headers
        )

    # ─── Applicants and applications ──────────────────
    def create_applicant(self, payload, headers):
        return self._request("POST", "/corps/applicants", payload, headers)

    def create_application(self, payload, headers):
        return self._request("POST", "/corps/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/corps/applications", payload=params, headers=headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/corps/applications/{application_id}", headers=headers)

    def review_application(self, application_id, verified_gpa, headers):
        return self._request(
            "POST",
            f"/corps/applications/{application_id}/review",
            {"verified_gpa": verified_gpa},
            headers,
        )

    def return_application(self, application_id, headers, return_reason=None):
        payload: Dict[str, Any] = {}
        if return_reason is not None:
            payload["return_reason"] = return_reason
        return self._request(
            "POST", f"/corps/applications/{application_id}/return", payload, headers
        )

    def resubmit_application(self, application_id, headers):
        return self._request(
            "POST", f"/corps/applications/{application_id}/resubmit", {}, headers
        )

    def decide_application(self, application_id, decision, headers, decision_reason=None):
        payload: Dict[str, Any] = {"decision": decision}
        if decision_reason is not None:
            payload["decision_reason"] = decision_reason
        return self._request(
            "POST", f"/corps/applications/{application_id}/decision", payload, headers
        )

    def extend_offer(self, application_id, headers):
        return self._request(
            "POST", f"/corps/applications/{application_id}/offer", {}, headers
        )

    def respond_to_offer(self, application_id, accept, headers):
        return self._request(
            "POST",
            f"/corps/applications/{application_id}/offer/respond",
            {"accept": accept},
            headers,
        )

    # ─── Certification pathways ───────────────────────
    def create_certification_pathway(self, payload, headers):
        return self._request("POST", "/corps/certification-pathways", payload, headers)

    def list_certification_pathways(self, headers, params=None):
        return self._request("GET", "/corps/certification-pathways", payload=params, headers=headers)

    def get_certification_pathway(self, pathway_id, headers):
        return self._request("GET", f"/corps/certification-pathways/{pathway_id}", headers=headers)

    def list_pathway_milestones(self, pathway_id, headers, params=None):
        return self._request(
            "GET",
            f"/corps/certification-pathways/{pathway_id}/certification-milestones",
            payload=params,
            headers=headers,
        )

    # ─── Corps members ────────────────────────────────
    def list_corps_members(self, headers, params=None):
        return self._request("GET", "/corps/corps-members", payload=params, headers=headers)

    def get_corps_member(self, member_id, headers):
        return self._request("GET", f"/corps/corps-members/{member_id}", headers=headers)

    def place_member_on_leave(self, member_id, headers):
        return self._request("POST", f"/corps/corps-members/{member_id}/leave", {}, headers)

    def return_member_from_leave(self, member_id, headers):
        return self._request(
            "POST", f"/corps/corps-members/{member_id}/return-from-leave", {}, headers
        )

    def exit_corps_member(self, member_id, exit_reason, headers):
        return self._request(
            "POST",
            f"/corps/corps-members/{member_id}/exit",
            {"exit_reason": exit_reason},
            headers,
        )

    def record_practice_hours(self, member_id, practice_hours_delta, headers):
        return self._request(
            "POST",
            f"/corps/corps-members/{member_id}/institute/practice-hours",
            {"practice_hours_delta": practice_hours_delta},
            headers,
        )

    def complete_institute(self, member_id, headers):
        return self._request(
            "POST", f"/corps/corps-members/{member_id}/institute/complete", {}, headers
        )

    def list_member_placements(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/corps/corps-members/{member_id}/placements", payload=params, headers=headers
        )

    def list_member_milestones(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/corps/corps-members/{member_id}/certification-milestones",
            payload=params,
            headers=headers,
        )

    def list_member_support_records(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/corps/corps-members/{member_id}/support-records",
            payload=params,
            headers=headers,
        )

    # ─── Placements ───────────────────────────────────
    def create_placement(self, payload, headers):
        return self._request("POST", "/corps/placements", payload, headers)

    def confirm_placement(self, placement_id, headers):
        return self._request("POST", f"/corps/placements/{placement_id}/confirm", {}, headers)

    def activate_placement(self, placement_id, headers):
        return self._request("POST", f"/corps/placements/{placement_id}/activate", {}, headers)

    def early_exit_placement(self, placement_id, early_exit_reason, headers):
        return self._request(
            "POST",
            f"/corps/placements/{placement_id}/early-exit",
            {"early_exit_reason": early_exit_reason},
            headers,
        )

    def reinstate_placement(self, placement_id, headers):
        return self._request("POST", f"/corps/placements/{placement_id}/reinstate", {}, headers)

    # ─── Certification milestones ─────────────────────
    def create_certification_milestone(self, payload, headers):
        return self._request("POST", "/corps/certification-milestones", payload, headers)

    def get_certification_milestone(self, milestone_id, headers):
        return self._request("GET", f"/corps/certification-milestones/{milestone_id}", headers=headers)

    def start_certification_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"/corps/certification-milestones/{milestone_id}/start", {}, headers
        )

    def complete_certification_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"/corps/certification-milestones/{milestone_id}/complete", {}, headers
        )

    def verify_certification_milestone(self, milestone_id, outcome, headers):
        return self._request(
            "POST",
            f"/corps/certification-milestones/{milestone_id}/verify",
            {"outcome": outcome},
            headers,
        )

    # ─── Support records ──────────────────────────────
    def create_support_record(self, payload, headers):
        return self._request("POST", "/corps/support-records", payload, headers)

    # ─── Logical clock ────────────────────────────────
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/corps/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Raw escape hatch (header-shape tests) ────────
    def request_raw(
        self,
        method: str,
        path: str,
        payload: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(method, path, payload, headers)


api_client = ApiClient()
