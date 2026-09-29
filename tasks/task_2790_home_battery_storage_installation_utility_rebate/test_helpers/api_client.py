"""
The HTTP client: one named method per declared operation.

Tests never build paths or pick verbs themselves. They call
`api.review_permit(permit_id, ...)` and get back the raw `requests.Response`, which
they then hand to `validate_success` or `validate_error`. Keeping every path in one
file means a route typo shows up once, here, instead of in thirty test files.

`canonical_ts` exists because two implementations may both be right about an instant
and still disagree about how many fractional digits to print. Comparisons of returned
timestamps go through it so that "2026-08-10T17:00:00Z", "...:00.000Z" and
"...:00.000000Z" all compare equal.
"""

import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Json = Dict[str, Any]

_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(\.\d+)?(Z|z|[+-]\d{2}:?\d{2})$"
)


def canonical_ts(value: Optional[str]) -> Optional[str]:
    """Collapse an ISO 8601 UTC instant onto second precision with a trailing Z.

    Anything that is not a recognizable ISO instant is returned unchanged so that a
    malformed value still fails its assertion loudly rather than being normalized away.
    """
    if not isinstance(value, str):
        return value
    match = _TS_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, fraction, offset = match.groups()
    if offset not in ("Z", "z"):
        # A non-UTC offset is meaningful; leave it alone rather than pretend.
        return value
    if fraction and fraction.rstrip("0") not in ("", "."):
        # Sub-second content that is not all zeros is real; keep it, but normalize
        # the suffix so only the digits differ.
        return "{}T{}{}Z".format(date_part, time_part, fraction.rstrip("0"))
    return "{}T{}Z".format(date_part, time_part)


def _prune(payload: Optional[Json]) -> Optional[Json]:
    """Drop keys whose value is None so optional fields can be passed positionally."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not None}


class ApiClient(GenericApiClient):
    """One method per operation in the endpoint table."""

    # ── Logical clock ────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601},
            headers=headers,
        )

    def set_clock_raw(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload=payload, headers=headers)

    # ── Installer accounts ───────────────────────────
    def create_installer(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/installers", payload=payload, headers=headers)

    def get_installer(self, installer_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/installers/{}".format(installer_id), headers=headers)

    def amend_certification(
        self, installer_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/installers/{}/certification".format(installer_id),
            payload=payload,
            headers=headers,
        )

    # ── Sites ────────────────────────────────────────
    def create_site(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/sites", payload=payload, headers=headers)

    def get_site(self, site_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/sites/{}".format(site_id), headers=headers)

    # ── Load calculations ────────────────────────────
    def create_load_calculation(
        self, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", "/load-calculations", payload=payload, headers=headers)

    def get_load_calculation(
        self, load_calculation_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/load-calculations/{}".format(load_calculation_id), headers=headers
        )

    def list_load_calculations(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/load-calculations", params=_prune(params), headers=headers
        )

    def submit_load_calculation(
        self,
        load_calculation_id: str,
        payload: Optional[Json] = None,
        headers: Optional[Json] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/load-calculations/{}/submit".format(load_calculation_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def review_load_calculation(
        self, load_calculation_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/load-calculations/{}/review".format(load_calculation_id),
            payload=payload,
            headers=headers,
        )

    # ── Battery systems ──────────────────────────────
    def create_battery_system(
        self, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", "/battery-systems", payload=payload, headers=headers)

    def get_battery_system(
        self, battery_system_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/battery-systems/{}".format(battery_system_id), headers=headers
        )

    def list_battery_systems(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/battery-systems", params=_prune(params), headers=headers
        )

    def lock_design(
        self, battery_system_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/battery-systems/{}/lock-design".format(battery_system_id),
            payload={},
            headers=headers,
        )

    def mark_installed(
        self, battery_system_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/battery-systems/{}/mark-installed".format(battery_system_id),
            payload={},
            headers=headers,
        )

    def commission(
        self, battery_system_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/battery-systems/{}/commission".format(battery_system_id),
            payload={},
            headers=headers,
        )

    def register_warranty(
        self,
        battery_system_id: str,
        payload: Optional[Json] = None,
        headers: Optional[Json] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/battery-systems/{}/register-warranty".format(battery_system_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def expand_system(
        self, battery_system_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/battery-systems/{}/expansions".format(battery_system_id),
            payload=payload,
            headers=headers,
        )

    # ── Permits ──────────────────────────────────────
    def create_permit(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/permits", payload=payload, headers=headers)

    def get_permit(self, permit_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/permits/{}".format(permit_id), headers=headers)

    def list_permits(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/permits", params=_prune(params), headers=headers)

    def submit_permit(
        self, permit_id: str, payload: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/permits/{}/submit".format(permit_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def review_permit(
        self, permit_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/permits/{}/review".format(permit_id), payload=payload, headers=headers
        )

    def record_inspection_result(
        self, permit_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/permits/{}/inspection-result".format(permit_id),
            payload=payload,
            headers=headers,
        )

    # ── Interconnection applications ─────────────────
    def create_application(
        self, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/interconnection-applications", payload=payload, headers=headers
        )

    def get_application(
        self, application_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/interconnection-applications/{}".format(application_id), headers=headers
        )

    def list_applications(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/interconnection-applications", params=_prune(params), headers=headers
        )

    def submit_application(
        self,
        application_id: str,
        payload: Optional[Json] = None,
        headers: Optional[Json] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/interconnection-applications/{}/submit".format(application_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def review_application(
        self, application_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/interconnection-applications/{}/review".format(application_id),
            payload=payload,
            headers=headers,
        )

    def grant_pto(
        self, application_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/interconnection-applications/{}/grant-pto".format(application_id),
            payload={},
            headers=headers,
        )

    # ── Incentive programs ───────────────────────────
    def create_program(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/incentive-programs", payload=payload, headers=headers)

    def get_program(self, program_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/incentive-programs/{}".format(program_id), headers=headers)

    def list_programs(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/incentive-programs", params=_prune(params), headers=headers
        )

    # ── Rebate claims ────────────────────────────────
    def create_claim(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/rebate-claims", payload=payload, headers=headers)

    def get_claim(self, claim_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/rebate-claims/{}".format(claim_id), headers=headers)

    def list_claims(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/rebate-claims", params=_prune(params), headers=headers)

    def submit_claim(self, claim_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", "/rebate-claims/{}/submit".format(claim_id), payload={}, headers=headers
        )

    def decide_claim(
        self, claim_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/rebate-claims/{}/decision".format(claim_id),
            payload=payload,
            headers=headers,
        )

    def pay_claim(self, claim_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", "/rebate-claims/{}/pay".format(claim_id), payload={}, headers=headers
        )

    def clawback_claim(
        self, claim_id: str, payload: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/rebate-claims/{}/clawback".format(claim_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def void_claim(
        self, claim_id: str, payload: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/rebate-claims/{}/void".format(claim_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ── Commissioning tests ──────────────────────────
    def create_commissioning_test(
        self, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", "/commissioning-tests", payload=payload, headers=headers)

    def get_commissioning_test(
        self, test_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/commissioning-tests/{}".format(test_id), headers=headers)

    def list_commissioning_tests(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/commissioning-tests", params=_prune(params), headers=headers
        )

    def record_test_result(
        self, test_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/commissioning-tests/{}/record-result".format(test_id),
            payload=payload,
            headers=headers,
        )

    # ── Monitoring alerts ────────────────────────────
    def create_alert(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/monitoring-alerts", payload=payload, headers=headers)

    def get_alert(self, alert_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/monitoring-alerts/{}".format(alert_id), headers=headers)

    def list_alerts(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/monitoring-alerts", params=_prune(params), headers=headers
        )

    def acknowledge_alert(
        self, alert_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/monitoring-alerts/{}/acknowledge".format(alert_id),
            payload={},
            headers=headers,
        )

    def file_warranty_claim(
        self, alert_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/monitoring-alerts/{}/file-claim".format(alert_id),
            payload=payload,
            headers=headers,
        )

    def review_warranty_claim(
        self, alert_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/monitoring-alerts/{}/review-claim".format(alert_id),
            payload=payload,
            headers=headers,
        )

    # ── BYOD enrollments ─────────────────────────────
    def create_enrollment(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/byod-enrollments", payload=payload, headers=headers)

    def get_enrollment(
        self, enrollment_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/byod-enrollments/{}".format(enrollment_id), headers=headers)

    def list_enrollments(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/byod-enrollments", params=_prune(params), headers=headers
        )

    def consent_enrollment(
        self, enrollment_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/byod-enrollments/{}/consent".format(enrollment_id),
            payload={},
            headers=headers,
        )

    def withdraw_enrollment(
        self,
        enrollment_id: str,
        payload: Optional[Json] = None,
        headers: Optional[Json] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/byod-enrollments/{}/withdraw".format(enrollment_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ── Dispatch events, participations and settlement ──
    def create_dispatch_event(
        self, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", "/dispatch-events", payload=payload, headers=headers)

    def get_dispatch_event(
        self, event_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/dispatch-events/{}".format(event_id), headers=headers)

    def list_dispatch_events(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/dispatch-events", params=_prune(params), headers=headers
        )

    def create_participation(
        self, event_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/dispatch-events/{}/participations".format(event_id),
            payload=payload,
            headers=headers,
        )

    def settle_event(self, event_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST", "/dispatch-events/{}/settle".format(event_id), payload={}, headers=headers
        )

    def get_performance(
        self, performance_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/dispatch-performances/{}".format(performance_id), headers=headers
        )

    def list_performances(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/dispatch-performances", params=_prune(params), headers=headers
        )

    def report_delivery(
        self, performance_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/dispatch-performances/{}/report-delivery".format(performance_id),
            payload=payload,
            headers=headers,
        )

    # ── Raw escape hatch ─────────────────────────────
    def request(
        self,
        method: str,
        path: str,
        payload: Optional[Json] = None,
        headers: Optional[Json] = None,
        params: Optional[Json] = None,
    ) -> requests.Response:
        """For probes that need a verb/path pairing no named method offers."""
        return self._request(method, path, payload=payload, headers=headers, params=params)


# One shared client for the whole suite; the base URL comes from the environment.
api_client = ApiClient()
