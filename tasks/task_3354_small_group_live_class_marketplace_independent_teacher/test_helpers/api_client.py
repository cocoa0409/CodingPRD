"""API client: one method per endpoint in the PRD's endpoint table (§4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin wrapper over the /outschool surface. Every method returns the raw response."""

    # --- Teacher applications (PRD §3.1) ----------------------------------
    def create_teacher_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/outschool/teacher-applications", payload=payload, headers=headers)

    def get_teacher_application(self, application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/outschool/teacher-applications/{application_id}", headers=headers)

    def submit_application(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/teacher-applications/{application_id}/submit",
            payload=payload, headers=headers,
        )

    def submit_sample(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/teacher-applications/{application_id}/submit-sample",
            payload=payload, headers=headers,
        )

    def review_application(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/teacher-applications/{application_id}/review",
            payload=payload, headers=headers,
        )

    def approve_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/teacher-applications/{application_id}/approve",
            payload={}, headers=headers,
        )

    # --- Teachers (PRD §3.2) ----------------------------------------------
    def get_teacher(self, teacher_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/outschool/teachers/{teacher_id}", headers=headers)

    def list_teachers(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/outschool/teachers", headers=headers, params=params)

    def activate_teacher(self, teacher_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/outschool/teachers/{teacher_id}/activate", payload={}, headers=headers)

    def suspend_teacher(self, teacher_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/outschool/teachers/{teacher_id}/suspend", payload=payload, headers=headers)

    def reinstate_teacher(self, teacher_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/outschool/teachers/{teacher_id}/reinstate", payload={}, headers=headers)

    def terminate_teacher(self, teacher_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/outschool/teachers/{teacher_id}/terminate", payload={}, headers=headers)

    # --- Class listings (PRD §3.3) ----------------------------------------
    def create_class_listing(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/outschool/class-listings", payload=payload, headers=headers)

    def get_class_listing(self, listing_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/outschool/class-listings/{listing_id}", headers=headers)

    def list_class_listings(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/outschool/class-listings", headers=headers, params=params)

    def policy_review_listing(self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/class-listings/{listing_id}/policy-review",
            payload=payload, headers=headers,
        )

    def publish_listing(self, listing_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/outschool/class-listings/{listing_id}/publish", payload={}, headers=headers)

    # --- Sections (PRD §3.4) ----------------------------------------------
    def create_section(self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/class-listings/{listing_id}/sections",
            payload=payload, headers=headers,
        )

    def list_sections(self, listing_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/outschool/class-listings/{listing_id}/sections",
            headers=headers, params=params,
        )

    def open_section(self, listing_id: str, section_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/class-listings/{listing_id}/sections/{section_id}/open",
            payload={}, headers=headers,
        )

    def meet_minimum(self, listing_id: str, section_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/class-listings/{listing_id}/sections/{section_id}/meet-minimum",
            payload={}, headers=headers,
        )

    def cancel_section(self, listing_id: str, section_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/class-listings/{listing_id}/sections/{section_id}/cancel",
            payload={}, headers=headers,
        )

    # --- Learners (PRD §3.5) ----------------------------------------------
    def create_learner(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/outschool/learners", payload=payload, headers=headers)

    def get_learner(self, learner_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/outschool/learners/{learner_id}", headers=headers)

    def set_subscription(self, learner_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/learners/{learner_id}/subscription",
            payload=payload, headers=headers,
        )

    # --- Enrollments (PRD §3.5, §3.6) -------------------------------------
    def create_enrollment(self, listing_id: str, section_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/class-listings/{listing_id}/sections/{section_id}/enrollments",
            payload=payload, headers=headers,
        )

    def get_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/outschool/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/outschool/enrollments", headers=headers, params=params)

    def confirm_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/outschool/enrollments/{enrollment_id}/confirm", payload={}, headers=headers)

    def cancel_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/outschool/enrollments/{enrollment_id}/cancel", payload={}, headers=headers)

    # --- Payouts (PRD §3.8) -----------------------------------------------
    def create_payout(self, teacher_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/outschool/teachers/{teacher_id}/payouts", payload=payload, headers=headers)

    def get_payout(self, payout_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/outschool/teacher-payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/outschool/teacher-payouts", headers=headers, params=params)

    def transition_payout(self, payout_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/teacher-payouts/{payout_id}/transition",
            payload=payload, headers=headers,
        )

    # --- Reports (PRD §3.7) -----------------------------------------------
    def create_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/outschool/class-reports", payload=payload, headers=headers)

    def get_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/outschool/class-reports/{report_id}", headers=headers)

    def list_reports(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/outschool/class-reports", headers=headers, params=params)

    def dispose_report(self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/outschool/class-reports/{report_id}/disposition",
            payload=payload, headers=headers,
        )

    # --- Operator capabilities (PRD §2.4, §3.9) ---------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/outschool/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601}, headers=headers,
        )

    def run_ops(self, headers: Dict[str, str]):
        return self._request("POST", "/outschool/_ops/run", payload={}, headers=headers)

    # --- Header-less probe (used to prove authentication outranks existence) ---
    def get_without_auth_headers(self, path: str):
        return self._request("GET", path, headers={})


api_client = ApiClient()
