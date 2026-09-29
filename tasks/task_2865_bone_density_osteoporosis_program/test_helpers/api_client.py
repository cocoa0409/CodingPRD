"""One method per endpoint of the Bone Density & Osteoporosis Program API.

Instant-valued inputs are canonicalised in one place here rather than in every
test, so that a caller may write ``"2026-03-10T09:00:00Z"`` or
``"2026-03-10T09:00:00"`` and the wire format stays identical.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HAS_ZONE = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")

# Body fields whose value the specification defines as an ISO-8601 instant.
INSTANT_FIELDS = ("to_iso8601", "start_utc", "end_utc")


def canonical_instant(value: Any) -> Any:
    """Return ``value`` as a full ISO-8601 UTC instant when it is instant-like."""
    if not isinstance(value, str) or not value:
        return value
    if _DATE_ONLY.match(value):
        return value + "T00:00:00Z"
    if not _HAS_ZONE.search(value):
        return value + "Z"
    return value


def canonicalise_payload(payload: Any) -> Any:
    """Apply instant canonicalisation to every instant-valued body field."""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    for field in INSTANT_FIELDS:
        if field in out:
            out[field] = canonical_instant(out[field])
    return out


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the program API."""

    # ── Logical clock ───────────────────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": canonical_instant(to_iso8601)},
            headers,
        )

    def set_clock_raw(self, payload: Any, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ── Payer policies ──────────────────────────────────────────────────────

    def create_payer_policy(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/payer-policies", payload, headers)

    def get_payer_policy(self, policy_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/payer-policies/{policy_id}", None, headers
        )

    def list_payer_policies(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/payer-policies", params, headers)

    # ── Densitometers ───────────────────────────────────────────────────────

    def create_densitometer(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/densitometers", payload, headers)

    def get_densitometer(self, device_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/densitometers/{device_id}", None, headers
        )

    def list_densitometers(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/densitometers", params, headers)

    def create_precision_assessment(
        self, device_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/densitometers/{device_id}/precision-assessment",
            payload,
            headers,
        )

    def retire_densitometer(self, device_id: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/densitometers/{device_id}/retire", None, headers
        )

    # ── Phantom quality control ─────────────────────────────────────────────

    def create_qc_run(
        self, device_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/densitometers/{device_id}/qc-runs", payload, headers
        )

    def get_qc_run(self, qc_run_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/qc-runs/{qc_run_id}", None, headers)

    def list_qc_runs(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/qc-runs", params, headers)

    # ── Calibration events ──────────────────────────────────────────────────

    def create_calibration_event(
        self, device_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/densitometers/{device_id}/calibration-events",
            payload,
            headers,
        )

    def get_calibration_event(self, event_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/calibration-events/{event_id}", None, headers
        )

    def list_device_calibration_events(
        self,
        device_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/densitometers/{device_id}/calibration-events",
            params,
            headers,
        )

    def close_calibration_event(self, event_id: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/calibration-events/{event_id}/close", None, headers
        )

    def adjudicate_calibration_event(
        self, event_id: str, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/calibration-events/{event_id}/adjudicate",
            None,
            headers,
        )

    # ── Patients and risk factor profiles ───────────────────────────────────

    def create_patient(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"{API_PREFIX}/patients/{patient_id}", None, headers)

    def list_patients(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/patients", params, headers)

    def create_risk_factor_profile(
        self, patient_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/patients/{patient_id}/risk-factor-profiles",
            payload,
            headers,
        )

    def list_risk_factor_profiles(
        self,
        patient_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/patients/{patient_id}/risk-factor-profiles",
            params,
            headers,
        )

    # ── Scan orders ─────────────────────────────────────────────────────────

    def create_scan_order(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/scan-orders", payload, headers)

    def get_scan_order(self, order_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/scan-orders/{order_id}", None, headers
        )

    def list_scan_orders(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/scan-orders", params, headers)

    # ── Scan appointments ───────────────────────────────────────────────────

    def create_scan_appointment(self, payload: Any, headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/scan-appointments",
            canonicalise_payload(payload),
            headers,
        )

    def get_scan_appointment(self, appointment_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/scan-appointments/{appointment_id}", None, headers
        )

    def list_scan_appointments(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        canonical = None
        if params:
            canonical = dict(params)
            for key in ("from_utc", "to_utc"):
                if key in canonical:
                    canonical[key] = canonical_instant(canonical[key])
        return self._request(
            "GET", f"{API_PREFIX}/scan-appointments", canonical, headers
        )

    def cancel_scan_appointment(
        self, appointment_id: str, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/scan-appointments/{appointment_id}/cancel",
            None,
            headers,
        )

    # ── Scan sessions ───────────────────────────────────────────────────────

    def create_scan_session(
        self, appointment_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/scan-appointments/{appointment_id}/scan-sessions",
            payload,
            headers,
        )

    def get_scan_session(self, session_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/scan-sessions/{session_id}", None, headers
        )

    def list_scan_sessions(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/scan-sessions", params, headers)

    def create_site_measurement(
        self, session_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/scan-sessions/{session_id}/site-measurements",
            payload,
            headers,
        )

    def list_site_measurements(
        self,
        session_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/scan-sessions/{session_id}/site-measurements",
            params,
            headers,
        )

    def create_vfa(
        self, session_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{API_PREFIX}/scan-sessions/{session_id}/vfa", payload, headers
        )

    def submit_acquisition(self, session_id: str, headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/scan-sessions/{session_id}/submit-acquisition",
            None,
            headers,
        )

    def create_positioning_review(
        self, session_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/scan-sessions/{session_id}/positioning-reviews",
            payload,
            headers,
        )

    def list_positioning_reviews(
        self,
        session_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/scan-sessions/{session_id}/positioning-reviews",
            params,
            headers,
        )

    def repeat_acquisition(self, session_id: str, headers: Optional[Dict] = None):
        return self._request(
            "POST",
            f"{API_PREFIX}/scan-sessions/{session_id}/repeat-acquisition",
            None,
            headers,
        )

    # ── Fracture risk assessments ───────────────────────────────────────────

    def create_frax_assessment(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/frax-assessments", payload, headers)

    def get_frax_assessment(self, assessment_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/frax-assessments/{assessment_id}", None, headers
        )

    def list_frax_assessments(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/frax-assessments", params, headers)

    # ── Diagnostic reports ──────────────────────────────────────────────────

    def create_diagnostic_report(self, payload: Any, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"{API_PREFIX}/diagnostic-reports", payload, headers
        )

    def get_diagnostic_report(self, report_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/diagnostic-reports/{report_id}", None, headers
        )

    def list_diagnostic_reports(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/diagnostic-reports", params, headers)

    def update_diagnostic_report(
        self, report_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/diagnostic-reports/{report_id}", payload, headers
        )

    def finalize_diagnostic_report(
        self, report_id: str, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/diagnostic-reports/{report_id}/finalize",
            None,
            headers,
        )

    def amend_diagnostic_report(
        self, report_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/diagnostic-reports/{report_id}/amend",
            payload,
            headers,
        )

    # ── Treatment plans ─────────────────────────────────────────────────────

    def create_treatment_plan(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", f"{API_PREFIX}/treatment-plans", payload, headers)

    def get_treatment_plan(self, plan_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/treatment-plans/{plan_id}", None, headers
        )

    def list_treatment_plans(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", f"{API_PREFIX}/treatment-plans", params, headers)

    def create_adherence_refill(
        self, plan_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/treatment-plans/{plan_id}/adherence-refills",
            payload,
            headers,
        )

    def list_adherence_refills(
        self,
        plan_id: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"{API_PREFIX}/treatment-plans/{plan_id}/adherence-refills",
            params,
            headers,
        )

    def create_adherence_review(
        self, plan_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/treatment-plans/{plan_id}/adherence-review",
            payload,
            headers,
        )
