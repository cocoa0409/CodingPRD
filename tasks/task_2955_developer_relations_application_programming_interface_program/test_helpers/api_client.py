"""One method per endpoint of the Developer Relations API Program.

Also provides ``canonical_instant``: the API echoes instants with exactly three
fractional-second digits, while request payloads and fixture literals are written in
the shorter ``...Z`` form. Tests compare instants through this canonicaliser so that
sub-second precision never masquerades as a behavioural difference.
"""
import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(\.\d+)?(?:[Zz]|([+-]\d{2}):?(\d{2}))?$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Trailing zero-padding of the fractional part is normalised to three digits so
    that ``2026-09-30T00:00:00Z`` and ``2026-09-30T00:00:00.000Z`` compare equal.
    A value that is not an instant (including None) is returned unchanged.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, frac = match.group(1), match.group(2), match.group(3)
    millis = "000"
    if frac:
        digits = frac[1:]
        millis = (digits + "000")[:3]
    return f"{date_part}T{time_part}.{millis}Z"


class ApiClient(GenericApiClient):
    """Endpoint-per-method client. Every method returns the raw response."""

    # ------------------------------------------------------------------ raw escapes
    def get_path(self, path: str, headers=None, params: Optional[Dict] = None):
        return self._request("GET", path, headers=headers, params=params)

    def post_path(self, path: str, payload: Any = None, headers=None):
        return self._request("POST", path, payload, headers)

    # ----------------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def get_clock(self, headers=None):
        return self._request("GET", "/_clock/current", headers=headers)

    # ------------------------------------------------------------------ developers
    def register_developer(self, payload, headers=None):
        return self._request("POST", "/developers", payload, headers)

    def get_developer(self, developer_id, headers=None):
        return self._request("GET", f"/developers/{developer_id}", headers=headers)

    def list_developers(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/developers", headers=headers, params=params)

    def acknowledge_onboarding(self, developer_id, payload, headers=None):
        return self._request(
            "POST", f"/developers/{developer_id}/onboarding-acknowledgement", payload, headers
        )

    def record_ecosystem_participation(self, developer_id, payload, headers=None):
        return self._request(
            "POST", f"/developers/{developer_id}/ecosystem-participations", payload, headers
        )

    def submit_directory_listing(self, developer_id, payload, headers=None):
        return self._request(
            "POST", f"/developers/{developer_id}/directory-submission", payload, headers
        )

    def review_directory_listing(self, developer_id, payload, headers=None):
        return self._request(
            "POST", f"/developers/{developer_id}/directory-review", payload, headers
        )

    def revoke_developer_access(self, developer_id, payload, headers=None):
        return self._request(
            "POST", f"/developers/{developer_id}/revoke-access", payload, headers
        )

    # ---------------------------------------------------------------- api products
    def create_api_product(self, payload, headers=None):
        return self._request("POST", "/api-products", payload, headers)

    def get_api_product(self, product_id, headers=None):
        return self._request("GET", f"/api-products/{product_id}", headers=headers)

    def list_api_products(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/api-products", headers=headers, params=params)

    def adjust_program(self, product_id, payload, headers=None):
        return self._request(
            "POST", f"/api-products/{product_id}/program-adjustments", payload, headers
        )

    def create_api_version(self, product_id, payload, headers=None):
        return self._request("POST", f"/api-products/{product_id}/versions", payload, headers)

    def list_api_versions(self, product_id, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api-products/{product_id}/versions", headers=headers, params=params
        )

    def get_product_roadmap(self, product_id, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api-products/{product_id}/roadmap", headers=headers, params=params
        )

    def run_upgrade_allocation(self, product_id, payload=None, headers=None):
        return self._request(
            "POST", f"/api-products/{product_id}/upgrade-allocation-run", payload or {}, headers
        )

    # ---------------------------------------------------------------- api versions
    def get_api_version(self, version_id, headers=None):
        return self._request("GET", f"/api-versions/{version_id}", headers=headers)

    def promote_api_version(self, version_id, payload=None, headers=None):
        return self._request(
            "POST", f"/api-versions/{version_id}/promote", payload or {}, headers
        )

    def publish_migration_guide(self, version_id, payload, headers=None):
        return self._request(
            "POST", f"/api-versions/{version_id}/migration-guide", payload, headers
        )

    def announce_deprecation(self, version_id, payload, headers=None):
        return self._request(
            "POST", f"/api-versions/{version_id}/announce-deprecation", payload, headers
        )

    # ---------------------------------------------------------- access applications
    def create_access_application(self, payload, headers=None):
        return self._request("POST", "/access-applications", payload, headers)

    def get_access_application(self, application_id, headers=None):
        return self._request(
            "GET", f"/access-applications/{application_id}", headers=headers
        )

    def list_access_applications(self, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", "/access-applications", headers=headers, params=params
        )

    def submit_access_application(self, application_id, payload=None, headers=None):
        return self._request(
            "POST", f"/access-applications/{application_id}/submit", payload or {}, headers
        )

    def claim_application_review(self, application_id, payload=None, headers=None):
        return self._request(
            "POST", f"/access-applications/{application_id}/claim-review", payload or {}, headers
        )

    def request_application_changes(self, application_id, payload, headers=None):
        return self._request(
            "POST", f"/access-applications/{application_id}/request-changes", payload, headers
        )

    def decide_access_application(self, application_id, payload, headers=None):
        return self._request(
            "POST", f"/access-applications/{application_id}/decide", payload, headers
        )

    # ------------------------------------------------------------ quota assignments
    def create_quota_assignment(self, payload, headers=None):
        return self._request("POST", "/quota-assignments", payload, headers)

    def get_quota_assignment(self, assignment_id, headers=None):
        return self._request("GET", f"/quota-assignments/{assignment_id}", headers=headers)

    def list_quota_assignments(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/quota-assignments", headers=headers, params=params)

    def activate_quota_assignment(self, assignment_id, payload=None, headers=None):
        return self._request(
            "POST", f"/quota-assignments/{assignment_id}/activate", payload or {}, headers
        )

    def suspend_quota_assignment(self, assignment_id, payload, headers=None):
        return self._request(
            "POST", f"/quota-assignments/{assignment_id}/suspend", payload, headers
        )

    def reinstate_quota_assignment(self, assignment_id, payload, headers=None):
        return self._request(
            "POST", f"/quota-assignments/{assignment_id}/reinstate", payload, headers
        )

    def create_usage_window(self, assignment_id, payload, headers=None):
        return self._request(
            "POST", f"/quota-assignments/{assignment_id}/usage-windows", payload, headers
        )

    def list_usage_windows(self, assignment_id, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/quota-assignments/{assignment_id}/usage-windows",
            headers=headers, params=params,
        )

    def create_upgrade_request(self, assignment_id, payload, headers=None):
        return self._request(
            "POST", f"/quota-assignments/{assignment_id}/upgrade-requests", payload, headers
        )

    def list_upgrade_requests(self, assignment_id, headers=None, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/quota-assignments/{assignment_id}/upgrade-requests",
            headers=headers, params=params,
        )

    def get_upgrade_request(self, request_id, headers=None):
        return self._request("GET", f"/upgrade-requests/{request_id}", headers=headers)

    # -------------------------------------------------------------- sandbox leases
    def create_sandbox_lease(self, payload, headers=None):
        return self._request("POST", "/sandbox-leases", payload, headers)

    def get_sandbox_lease(self, lease_id, headers=None):
        return self._request("GET", f"/sandbox-leases/{lease_id}", headers=headers)

    def list_sandbox_leases(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/sandbox-leases", headers=headers, params=params)

    def validate_sandbox_lease(self, lease_id, payload=None, headers=None):
        return self._request(
            "POST", f"/sandbox-leases/{lease_id}/validate", payload or {}, headers
        )

    def release_sandbox_lease(self, lease_id, payload=None, headers=None):
        return self._request(
            "POST", f"/sandbox-leases/{lease_id}/release", payload or {}, headers
        )

    # ------------------------------------------------------------- violation cases
    def create_violation_case(self, payload, headers=None):
        return self._request("POST", "/violation-cases", payload, headers)

    def get_violation_case(self, case_id, headers=None):
        return self._request("GET", f"/violation-cases/{case_id}", headers=headers)

    def list_violation_cases(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/violation-cases", headers=headers, params=params)

    def investigate_violation_case(self, case_id, payload=None, headers=None):
        return self._request(
            "POST", f"/violation-cases/{case_id}/investigate", payload or {}, headers
        )

    def adjudicate_violation_case(self, case_id, payload, headers=None):
        return self._request(
            "POST", f"/violation-cases/{case_id}/adjudicate", payload, headers
        )

    def appeal_violation_case(self, case_id, payload, headers=None):
        return self._request("POST", f"/violation-cases/{case_id}/appeal", payload, headers)

    # --------------------------------------------------------------- support cases
    def create_support_case(self, payload, headers=None):
        return self._request("POST", "/support-cases", payload, headers)

    def get_support_case(self, case_id, headers=None):
        return self._request("GET", f"/support-cases/{case_id}", headers=headers)

    def list_support_cases(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/support-cases", headers=headers, params=params)

    def create_support_communication(self, case_id, payload, headers=None):
        return self._request(
            "POST", f"/support-cases/{case_id}/communications", payload, headers
        )

    def escalate_support_case(self, case_id, payload=None, headers=None):
        return self._request(
            "POST", f"/support-cases/{case_id}/escalate", payload or {}, headers
        )

    def resolve_support_case(self, case_id, payload, headers=None):
        return self._request("POST", f"/support-cases/{case_id}/resolve", payload, headers)

    # -------------------------------------------------------------- feedback items
    def create_feedback_item(self, payload, headers=None):
        return self._request("POST", "/feedback-items", payload, headers)

    def get_feedback_item(self, item_id, headers=None):
        return self._request("GET", f"/feedback-items/{item_id}", headers=headers)

    def list_feedback_items(self, headers=None, params: Optional[Dict] = None):
        return self._request("GET", "/feedback-items", headers=headers, params=params)

    def triage_feedback_item(self, item_id, payload=None, headers=None):
        return self._request(
            "POST", f"/feedback-items/{item_id}/triage", payload or {}, headers
        )

    def decide_feedback_roadmap(self, item_id, payload, headers=None):
        return self._request(
            "POST", f"/feedback-items/{item_id}/roadmap-decision", payload, headers
        )

    # ---------------------------------------------------------- programme checkpoint
    def run_program_checkpoint(self, payload=None, headers=None):
        return self._request("POST", "/program-checkpoints", payload or {}, headers)
