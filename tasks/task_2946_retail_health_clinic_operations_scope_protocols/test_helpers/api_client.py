"""API client: one method per endpoint in the PRD endpoint table."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value):
    """Canonicalise an ISO 8601 UTC instant to a comparable datetime.

    The PRD pins three fractional digits for the envelope timestamp and for
    `created_at` / `updated_at`, but a server may echo domain instants
    (`starts_at`, `arrived_at`, `due_at`, `window_start`, ...) with any
    sub-second width. Tests therefore compare instants by value, never by the
    width of the string they arrived in.
    """
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def same_instant(left, right) -> bool:
    """True when two ISO 8601 UTC strings denote the same instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # State rules
    # ------------------------------------------------------------------
    def create_state_rule(self, payload, headers):
        return self._request("POST", "/state-rules", payload, headers)

    # ------------------------------------------------------------------
    # Protocols
    # ------------------------------------------------------------------
    def create_protocol(self, payload, headers):
        return self._request("POST", "/protocols", payload, headers)

    def get_protocol(self, protocol_id, headers):
        return self._request("GET", f"/protocols/{protocol_id}", headers=headers)

    def list_protocols(self, headers, params=None):
        return self._request("GET", "/protocols", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Clinics
    # ------------------------------------------------------------------
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    # ------------------------------------------------------------------
    # Physicians
    # ------------------------------------------------------------------
    def create_physician(self, payload, headers):
        return self._request("POST", "/physicians", payload, headers)

    def get_physician(self, physician_id, headers):
        return self._request("GET", f"/physicians/{physician_id}", headers=headers)

    # ------------------------------------------------------------------
    # Clinicians
    # ------------------------------------------------------------------
    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    def list_clinicians(self, headers, params=None):
        return self._request("GET", "/clinicians", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ------------------------------------------------------------------
    # Staffing assignments and float coverage
    # ------------------------------------------------------------------
    def create_staffing_assignment(self, payload, headers):
        return self._request("POST", "/staffing-assignments", payload, headers)

    def cancel_staffing_assignment(self, assignment_id, headers, cancel_reason=None):
        payload = {} if cancel_reason is None else {"cancel_reason": cancel_reason}
        return self._request("POST", f"/staffing-assignments/{assignment_id}/cancel",
                             payload, headers)

    def get_staffing_assignment(self, assignment_id, headers):
        return self._request("GET", f"/staffing-assignments/{assignment_id}",
                             headers=headers)

    def list_staffing_assignments(self, headers, params=None):
        return self._request("GET", "/staffing-assignments", headers=headers,
                             params=params)

    def create_float_coverage(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/float-coverages",
                             payload, headers)

    # ------------------------------------------------------------------
    # Queue entries
    # ------------------------------------------------------------------
    def create_queue_entry(self, payload, headers):
        return self._request("POST", "/queue-entries", payload, headers)

    def arrive_queue_entry(self, queue_entry_id, headers):
        return self._request("POST", f"/queue-entries/{queue_entry_id}/arrive",
                             {}, headers)

    def get_queue_entry(self, queue_entry_id, headers):
        return self._request("GET", f"/queue-entries/{queue_entry_id}", headers=headers)

    def list_queue_entries(self, headers, params=None):
        return self._request("GET", "/queue-entries", headers=headers, params=params)

    def call_next(self, clinic_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/call-next", {}, headers)

    # ------------------------------------------------------------------
    # Visits
    # ------------------------------------------------------------------
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def eligibility_check(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/eligibility-check",
                             payload, headers)

    def accept_self_pay(self, visit_id, acknowledged_price_cents, headers):
        return self._request("POST", f"/visits/{visit_id}/accept-self-pay",
                             {"acknowledged_price_cents": acknowledged_price_cents},
                             headers)

    def accept_self_pay_raw(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/accept-self-pay",
                             payload, headers)

    def checkout(self, visit_id, headers, services_rendered=None):
        payload = ({} if services_rendered is None
                   else {"services_rendered": list(services_rendered)})
        return self._request("POST", f"/visits/{visit_id}/checkout", payload, headers)

    def charge_void(self, visit_id, void_reason, headers):
        return self._request("POST", f"/visits/{visit_id}/charge-void",
                             {"void_reason": void_reason}, headers)

    def charge_void_raw(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/charge-void", payload, headers)

    # ------------------------------------------------------------------
    # Assessments
    # ------------------------------------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def submit_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/submit", {}, headers)

    def cosign_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/cosign", {}, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Prescriptions
    # ------------------------------------------------------------------
    def create_prescription(self, payload, headers):
        return self._request("POST", "/prescriptions", payload, headers)

    def route_prescription(self, prescription_id, headers):
        return self._request("POST", f"/prescriptions/{prescription_id}/route",
                             {}, headers)

    def cancel_prescription(self, prescription_id, headers, cancel_reason=None):
        payload = {} if cancel_reason is None else {"cancel_reason": cancel_reason}
        return self._request("POST", f"/prescriptions/{prescription_id}/cancel",
                             payload, headers)

    def get_prescription(self, prescription_id, headers):
        return self._request("GET", f"/prescriptions/{prescription_id}", headers=headers)

    def list_prescriptions(self, headers, params=None):
        return self._request("GET", "/prescriptions", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Chart reviews
    # ------------------------------------------------------------------
    def run_chart_review_sampling(self, clinic_id, window_start, window_end, headers):
        return self._request("POST", f"/clinics/{clinic_id}/chart-review-samplings",
                             {"window_start": window_start, "window_end": window_end},
                             headers)

    def run_chart_review_sampling_raw(self, clinic_id, payload, headers):
        return self._request("POST", f"/clinics/{clinic_id}/chart-review-samplings",
                             payload, headers)

    def request_chart_review_changes(self, chart_review_id, change_note, headers):
        return self._request("POST", f"/chart-reviews/{chart_review_id}/request-changes",
                             {"change_note": change_note}, headers)

    def resubmit_chart_review(self, chart_review_id, amendment_note, headers):
        return self._request("POST", f"/chart-reviews/{chart_review_id}/resubmit",
                             {"amendment_note": amendment_note}, headers)

    def attest_chart_review(self, chart_review_id, outcome, headers,
                            attestation_note=None):
        payload = {"outcome": outcome}
        if attestation_note is not None:
            payload["attestation_note"] = attestation_note
        return self._request("POST", f"/chart-reviews/{chart_review_id}/attest",
                             payload, headers)

    def reassign_chart_review(self, chart_review_id, headers):
        return self._request("POST", f"/chart-reviews/{chart_review_id}/reassign",
                             {}, headers)

    def get_chart_review(self, chart_review_id, headers):
        return self._request("GET", f"/chart-reviews/{chart_review_id}", headers=headers)

    def list_chart_reviews(self, headers, params=None):
        return self._request("GET", "/chart-reviews", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Visit summaries
    # ------------------------------------------------------------------
    def transmit_visit_summary(self, visit_summary_id, transport_outcome, headers,
                               failure_code=None):
        payload = {"transport_outcome": transport_outcome}
        if failure_code is not None:
            payload["failure_code"] = failure_code
        return self._request("POST", f"/visit-summaries/{visit_summary_id}/transmit",
                             payload, headers)

    def retry_visit_summary(self, visit_summary_id, headers):
        return self._request("POST", f"/visit-summaries/{visit_summary_id}/retry",
                             {}, headers)

    def get_visit_summary(self, visit_summary_id, headers):
        return self._request("GET", f"/visit-summaries/{visit_summary_id}",
                             headers=headers)

    def list_visit_summaries(self, headers, params=None):
        return self._request("GET", "/visit-summaries", headers=headers, params=params)


api_client = ApiClient()
