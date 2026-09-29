"""ApiClient — one method per endpoint of the Child Care Licensing Compliance API.

Every method returns the raw ``requests.Response`` so tests can assert status
codes and envelope shape with the framework validators.  Optional body fields
are omitted from the JSON payload unless explicitly supplied, which matters for
the "omitted optionals take their declared defaults" rules of the PRD.

``params`` for list endpoints are built the same way: only the filters a caller
actually passes are sent, so a request that omits every optional parameter is a
well-formed request (PRD §2.3).
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_OMITTED = object()


def _body(**kwargs: Any) -> Dict[str, Any]:
    """Build a JSON body dropping only the keys whose value is the omission
    sentinel.  Explicit ``None`` is preserved so tests can send a null."""
    return {k: v for k, v in kwargs.items() if v is not _OMITTED}


class ApiClient(GenericApiClient):
    """Typed endpoint wrapper for the ``/licensing`` service."""

    # ─── §2.4 Logical clock ────────────────────────────────────────────
    def set_clock(self, to_iso8601: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── §3.1 Checklist catalog ────────────────────────────────────────
    def create_checklist_item(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/checklist-items", payload, headers)

    def list_checklist_items(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/checklist-items", None, headers, params=params or None
        )

    def get_checklist_item(self, checklist_item_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/checklist-items/{checklist_item_id}", None, headers
        )

    # ─── §3.1 Inspector roll ───────────────────────────────────────────
    def create_inspector(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/inspectors", payload, headers)

    def list_inspectors(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/inspectors", None, headers, params=params or None
        )

    def get_inspector(self, inspector_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/inspectors/{inspector_id}", None, headers
        )

    def set_inspector_leave_status(self, inspector_id: str, status: str, headers=None):
        return self._request(
            "POST",
            f"/licensing/inspectors/{inspector_id}/leave-status",
            {"status": status},
            headers,
        )

    # ─── §3.2 Providers ────────────────────────────────────────────────
    def create_provider(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/providers", payload, headers)

    def list_providers(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/providers", None, headers, params=params or None
        )

    def get_provider(self, provider_id: str, headers=None):
        return self._request("GET", f"/licensing/providers/{provider_id}", None, headers)

    def submit_application(self, provider_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/providers/{provider_id}/submit-application", {}, headers
        )

    def clear_checks(self, provider_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/providers/{provider_id}/clear-checks", {}, headers
        )

    def license_decision(
        self, provider_id: str, decision: str, decision_reason: Any = _OMITTED, headers=None
    ):
        return self._request(
            "POST",
            f"/licensing/providers/{provider_id}/license-decision",
            _body(decision=decision, decision_reason=decision_reason),
            headers,
        )

    def promote_to_full(self, provider_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/providers/{provider_id}/promote-to-full", {}, headers
        )

    def restore_full(self, provider_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/providers/{provider_id}/restore-full", {}, headers
        )

    def get_risk_assessment(
        self, provider_id: str, variant: Optional[str] = None, headers=None
    ):
        params = {"variant": variant} if variant is not None else None
        return self._request(
            "GET",
            f"/licensing/providers/{provider_id}/risk-assessment",
            None,
            headers,
            params=params,
        )

    # ─── §3.2 Staff members ────────────────────────────────────────────
    def create_staff_member(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/staff-members", payload, headers)

    def list_staff_members(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/staff-members", None, headers, params=params or None
        )

    def get_staff_member(self, staff_member_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/staff-members/{staff_member_id}", None, headers
        )

    # ─── §3.3 Background checks ────────────────────────────────────────
    def create_background_check(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/background-checks", payload, headers)

    def list_background_checks(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/background-checks", None, headers, params=params or None
        )

    def get_background_check(self, background_check_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/background-checks/{background_check_id}", None, headers
        )

    def record_check_result(
        self,
        background_check_id: str,
        result: str,
        disqualifying_offense_tier: Any = _OMITTED,
        headers=None,
    ):
        return self._request(
            "POST",
            f"/licensing/background-checks/{background_check_id}/result",
            _body(
                result=result,
                disqualifying_offense_tier=disqualifying_offense_tier,
            ),
            headers,
        )

    def request_waiver(self, background_check_id: str, waiver_rationale: str, headers=None):
        return self._request(
            "POST",
            f"/licensing/background-checks/{background_check_id}/waiver",
            {"waiver_rationale": waiver_rationale},
            headers,
        )

    def decide_waiver(self, background_check_id: str, decision: str, headers=None):
        return self._request(
            "POST",
            f"/licensing/background-checks/{background_check_id}/waiver-decision",
            {"decision": decision},
            headers,
        )

    # ─── §3.2 Age-group rosters ────────────────────────────────────────
    def create_roster(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/age-group-rosters", payload, headers)

    def list_rosters(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/age-group-rosters", None, headers, params=params or None
        )

    def get_roster(self, roster_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/age-group-rosters/{roster_id}", None, headers
        )

    def patch_roster(
        self,
        roster_id: str,
        enrolled_count: Any = _OMITTED,
        staff_assigned_count: Any = _OMITTED,
        lead_staff_member_id: Any = _OMITTED,
        headers=None,
    ):
        return self._request(
            "PATCH",
            f"/licensing/age-group-rosters/{roster_id}",
            _body(
                enrolled_count=enrolled_count,
                staff_assigned_count=staff_assigned_count,
                lead_staff_member_id=lead_staff_member_id,
            ),
            headers,
        )

    def verify_ratio(self, roster_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/age-group-rosters/{roster_id}/verify-ratio", {}, headers
        )

    # ─── §3.4 Inspections ──────────────────────────────────────────────
    def create_inspection(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/inspections", payload, headers)

    def list_inspections(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/inspections", None, headers, params=params or None
        )

    def get_inspection(self, inspection_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/inspections/{inspection_id}", None, headers
        )

    def start_inspection(self, inspection_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/inspections/{inspection_id}/start", {}, headers
        )

    def submit_for_review(
        self, inspection_id: str, outcome: str, age_groups_observed, headers=None
    ):
        return self._request(
            "POST",
            f"/licensing/inspections/{inspection_id}/submit-for-review",
            {"outcome": outcome, "age_groups_observed": age_groups_observed},
            headers,
        )

    def reopen_inspection(self, inspection_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/inspections/{inspection_id}/reopen", {}, headers
        )

    def finalize_inspection(self, inspection_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/inspections/{inspection_id}/finalize", {}, headers
        )

    def void_inspection(self, inspection_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/inspections/{inspection_id}/void", {}, headers
        )

    def get_compliance_score(
        self, inspection_id: str, variant: Optional[str] = None, headers=None
    ):
        params = {"variant": variant} if variant is not None else None
        return self._request(
            "GET",
            f"/licensing/inspections/{inspection_id}/compliance-score",
            None,
            headers,
            params=params,
        )

    # ─── §3.5 Violations ───────────────────────────────────────────────
    def create_violation(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/violations", payload, headers)

    def list_violations(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/violations", None, headers, params=params or None
        )

    def get_violation(self, violation_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/violations/{violation_id}", None, headers
        )

    def disposition_violation(
        self,
        violation_id: str,
        disposition: str,
        vacated_reason: Any = _OMITTED,
        headers=None,
    ):
        return self._request(
            "POST",
            f"/licensing/violations/{violation_id}/disposition",
            _body(disposition=disposition, vacated_reason=vacated_reason),
            headers,
        )

    # ─── §3.7 Complaints ───────────────────────────────────────────────
    def create_complaint(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/complaints", payload, headers)

    def list_complaints(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/complaints", None, headers, params=params or None
        )

    def get_complaint(self, complaint_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/complaints/{complaint_id}", None, headers
        )

    def screen_complaint(self, complaint_id: str, decision: str, headers=None):
        return self._request(
            "POST",
            f"/licensing/complaints/{complaint_id}/screen",
            {"decision": decision},
            headers,
        )

    def assign_investigator(self, complaint_id: str, investigator_id: str, headers=None):
        return self._request(
            "POST",
            f"/licensing/complaints/{complaint_id}/assign-investigator",
            {"investigator_id": investigator_id},
            headers,
        )

    def record_determination(self, complaint_id: str, determination: str, headers=None):
        return self._request(
            "POST",
            f"/licensing/complaints/{complaint_id}/determination",
            {"determination": determination},
            headers,
        )

    def close_complaint(self, complaint_id: str, closure_note: str, headers=None):
        return self._request(
            "POST",
            f"/licensing/complaints/{complaint_id}/close",
            {"closure_note": closure_note},
            headers,
        )

    # ─── §3.6 Corrective action plans ──────────────────────────────────
    def create_cap(self, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", "/licensing/corrective-action-plans", payload, headers
        )

    def list_caps(self, headers=None, **params):
        return self._request(
            "GET",
            "/licensing/corrective-action-plans",
            None,
            headers,
            params=params or None,
        )

    def get_cap(self, cap_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/corrective-action-plans/{cap_id}", None, headers
        )

    def review_cap(
        self, cap_id: str, decision: str, review_note: Any = _OMITTED, headers=None
    ):
        return self._request(
            "POST",
            f"/licensing/corrective-action-plans/{cap_id}/review",
            _body(decision=decision, review_note=review_note),
            headers,
        )

    def resubmit_cap(self, cap_id: str, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST",
            f"/licensing/corrective-action-plans/{cap_id}/resubmit",
            payload,
            headers,
        )

    def complete_cap(self, cap_id: str, result: str, headers=None):
        return self._request(
            "POST",
            f"/licensing/corrective-action-plans/{cap_id}/complete",
            {"result": result},
            headers,
        )

    # ─── §3.8 Enforcement actions ──────────────────────────────────────
    def create_enforcement_action(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/enforcement-actions", payload, headers)

    def list_enforcement_actions(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/enforcement-actions", None, headers, params=params or None
        )

    def get_enforcement_action(self, action_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/enforcement-actions/{action_id}", None, headers
        )

    def issue_action(self, action_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/enforcement-actions/{action_id}/issue", {}, headers
        )

    def effectuate_action(self, action_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/enforcement-actions/{action_id}/effectuate", {}, headers
        )

    def appeal_action(self, action_id: str, appeal_note: str, headers=None):
        return self._request(
            "POST",
            f"/licensing/enforcement-actions/{action_id}/appeal",
            {"appeal_note": appeal_note},
            headers,
        )

    def decide_appeal(self, action_id: str, appeal_decision: str, headers=None):
        return self._request(
            "POST",
            f"/licensing/enforcement-actions/{action_id}/appeal-decision",
            {"appeal_decision": appeal_decision},
            headers,
        )

    # ─── §3.9 Licence amendments ───────────────────────────────────────
    def create_amendment(self, payload: Dict[str, Any], headers=None):
        return self._request("POST", "/licensing/license-amendments", payload, headers)

    def list_amendments(self, headers=None, **params):
        return self._request(
            "GET", "/licensing/license-amendments", None, headers, params=params or None
        )

    def get_amendment(self, amendment_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/license-amendments/{amendment_id}", None, headers
        )

    def attach_pre_move_inspection(
        self, amendment_id: str, pre_move_inspection_id: str, headers=None
    ):
        return self._request(
            "POST",
            f"/licensing/license-amendments/{amendment_id}/attach-inspection",
            {"pre_move_inspection_id": pre_move_inspection_id},
            headers,
        )

    def decide_amendment(
        self,
        amendment_id: str,
        decision: str,
        decision_rationale: Any = _OMITTED,
        headers=None,
    ):
        return self._request(
            "POST",
            f"/licensing/license-amendments/{amendment_id}/decide",
            _body(decision=decision, decision_rationale=decision_rationale),
            headers,
        )

    def withdraw_amendment(self, amendment_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/license-amendments/{amendment_id}/withdraw", {}, headers
        )

    # ─── §3.7 Serious incident reports ─────────────────────────────────
    def create_incident_report(self, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", "/licensing/serious-incident-reports", payload, headers
        )

    def list_incident_reports(self, headers=None, **params):
        return self._request(
            "GET",
            "/licensing/serious-incident-reports",
            None,
            headers,
            params=params or None,
        )

    def get_incident_report(self, report_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/serious-incident-reports/{report_id}", None, headers
        )

    def review_incident_report(
        self, report_id: str, disposition: str, agency_note: Any = _OMITTED, headers=None
    ):
        return self._request(
            "POST",
            f"/licensing/serious-incident-reports/{report_id}/review",
            _body(disposition=disposition, agency_note=agency_note),
            headers,
        )

    def close_incident_report(
        self, report_id: str, agency_note: Any = _OMITTED, headers=None
    ):
        return self._request(
            "POST",
            f"/licensing/serious-incident-reports/{report_id}/close",
            _body(agency_note=agency_note),
            headers,
        )

    # ─── §3.9 Public report postings ───────────────────────────────────
    def create_posting(self, payload: Dict[str, Any], headers=None):
        return self._request(
            "POST", "/licensing/public-report-postings", payload, headers
        )

    def list_postings(self, headers=None, **params):
        return self._request(
            "GET",
            "/licensing/public-report-postings",
            None,
            headers,
            params=params or None,
        )

    def get_posting(self, posting_id: str, headers=None):
        return self._request(
            "GET", f"/licensing/public-report-postings/{posting_id}", None, headers
        )

    def post_posting(self, posting_id: str, headers=None):
        return self._request(
            "POST", f"/licensing/public-report-postings/{posting_id}/post", {}, headers
        )

    def revise_posting(
        self, posting_id: str, action: str, revision_note: str, headers=None
    ):
        return self._request(
            "POST",
            f"/licensing/public-report-postings/{posting_id}/revise",
            {"action": action, "revision_note": revision_note},
            headers,
        )

    # ─── Raw escape hatches for shape and header tests ─────────────────
    def raw_post(self, path: str, payload: Any, headers=None):
        """POST an arbitrary body — used by unknown-key and wrong-type tests."""
        return self._request("POST", path, payload, headers)

    def raw_get(self, path: str, headers=None, **params):
        return self._request("GET", path, None, headers, params=params or None)


# Module-level singleton used by conftest's session-scoped ``api`` fixture.
api_client = ApiClient()
