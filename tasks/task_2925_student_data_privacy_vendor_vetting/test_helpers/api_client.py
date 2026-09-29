"""HTTP client for the Student Data Privacy Vendor Vetting API.

One method per PRD §4 endpoint (50 in total).  Every method returns the raw
`requests.Response` so tests can assert on status codes as well as bodies.

Timestamp canonicalisation
--------------------------
PRD §2.4 requires stored instants to be rendered with exactly three
fractional digits.  Tests that need to compare an instant they computed with
one the service returned go through :func:`canonical_instant` rather than
comparing raw strings, so a service that renders ``2026-08-01T00:00:00.000Z``
and a fixture literal of ``2026-08-01T00:00:00Z`` compare equal on *instant*
while the separate three-digit rendering rule is asserted explicitly and only
where the design calls for it.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: str) -> str:
    """Normalise an ISO-8601 instant to a single comparable form.

    Accepts a trailing ``Z`` or a numeric offset and any number of fractional
    digits, and returns the UTC instant rendered with exactly three fractional
    digits.  Comparing two canonical forms compares the instants themselves,
    never the incidental width of the fraction.
    """
    assert isinstance(value, str), f"Expected an ISO-8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


def instants_equal(left: str, right: str) -> bool:
    """True when two ISO-8601 strings denote the same UTC instant."""
    return canonical_instant(left) == canonical_instant(right)


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 instant into a timezone-aware UTC datetime."""
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def render_instant(moment: datetime) -> str:
    """Render a datetime the way the service renders stored instants."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def shift_instant(value: str, **delta: Any) -> str:
    """Return ``value`` moved by a timedelta, rendered with three digits."""
    return render_instant(parse_instant(value) + timedelta(**delta))


def _clean(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is the sentinel ``OMIT``.

    Lets a factory declare every optional field while a caller still models
    "field absent from the body" rather than "field present and null".
    """
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not OMIT}


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "OMIT"


OMIT = _Omit()


class ApiClient(GenericApiClient):
    """Typed wrapper over the 50 declared endpoints."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers=None):
        """POST /_clock/set_current_utc"""
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------
    def create_vendor(self, payload, headers=None):
        """POST /vendors"""
        return self._request("POST", "/vendors", _clean(payload), headers)

    def list_vendors(self, headers=None, **params):
        """GET /vendors"""
        return self._request("GET", "/vendors", _clean(params), headers)

    def get_vendor(self, vendor_id, headers=None):
        """GET /vendors/{vendorId}"""
        return self._request("GET", f"/vendors/{vendor_id}", None, headers)

    def suspend_vendor(self, vendor_id, payload, headers=None):
        """POST /vendors/{vendorId}/suspend"""
        return self._request(
            "POST", f"/vendors/{vendor_id}/suspend", _clean(payload), headers
        )

    def reinstate_vendor(self, vendor_id, payload=None, headers=None):
        """POST /vendors/{vendorId}/reinstate"""
        return self._request(
            "POST", f"/vendors/{vendor_id}/reinstate", _clean(payload or {}), headers
        )

    # ------------------------------------------------------------------
    # Subprocessors
    # ------------------------------------------------------------------
    def create_subprocessor(self, payload, headers=None):
        """POST /subprocessors"""
        return self._request("POST", "/subprocessors", _clean(payload), headers)

    def list_subprocessors(self, headers=None, **params):
        """GET /subprocessors"""
        return self._request("GET", "/subprocessors", _clean(params), headers)

    def get_subprocessor(self, subprocessor_id, headers=None):
        """GET /subprocessors/{subprocessorId}"""
        return self._request(
            "GET", f"/subprocessors/{subprocessor_id}", None, headers
        )

    def review_subprocessor(self, subprocessor_id, payload, headers=None):
        """POST /subprocessors/{subprocessorId}/review"""
        return self._request(
            "POST",
            f"/subprocessors/{subprocessor_id}/review",
            _clean(payload),
            headers,
        )

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers=None):
        """POST /applications"""
        return self._request("POST", "/applications", _clean(payload), headers)

    def list_applications(self, headers=None, **params):
        """GET /applications"""
        return self._request("GET", "/applications", _clean(params), headers)

    def get_application(self, application_id, headers=None):
        """GET /applications/{applicationId}"""
        return self._request("GET", f"/applications/{application_id}", None, headers)

    def attest_integration(self, application_id, payload, headers=None):
        """POST /applications/{applicationId}/attest-integration"""
        return self._request(
            "POST",
            f"/applications/{application_id}/attest-integration",
            _clean(payload),
            headers,
        )

    # ------------------------------------------------------------------
    # Teachers and analysts
    # ------------------------------------------------------------------
    def create_teacher(self, payload, headers=None):
        """POST /teachers"""
        return self._request("POST", "/teachers", _clean(payload), headers)

    def get_teacher(self, teacher_id, headers=None):
        """GET /teachers/{teacherId}"""
        return self._request("GET", f"/teachers/{teacher_id}", None, headers)

    def create_analyst(self, payload, headers=None):
        """POST /privacy-analysts"""
        return self._request("POST", "/privacy-analysts", _clean(payload), headers)

    def get_analyst(self, analyst_id, headers=None):
        """GET /privacy-analysts/{analystId}"""
        return self._request("GET", f"/privacy-analysts/{analyst_id}", None, headers)

    # ------------------------------------------------------------------
    # Application requests
    # ------------------------------------------------------------------
    def create_request(self, payload, headers=None):
        """POST /application-requests"""
        return self._request(
            "POST", "/application-requests", _clean(payload), headers
        )

    def list_requests(self, headers=None, **params):
        """GET /application-requests"""
        return self._request("GET", "/application-requests", _clean(params), headers)

    def get_request(self, request_id, headers=None):
        """GET /application-requests/{requestId}"""
        return self._request(
            "GET", f"/application-requests/{request_id}", None, headers
        )

    def submit_request(self, request_id, payload=None, headers=None):
        """POST /application-requests/{requestId}/submit"""
        return self._request(
            "POST",
            f"/application-requests/{request_id}/submit",
            _clean(payload or {}),
            headers,
        )

    def triage_request(self, request_id, payload, headers=None):
        """POST /application-requests/{requestId}/triage"""
        return self._request(
            "POST",
            f"/application-requests/{request_id}/triage",
            _clean(payload),
            headers,
        )

    # ------------------------------------------------------------------
    # Data practice reviews
    # ------------------------------------------------------------------
    def create_review(self, payload, headers=None):
        """POST /data-practice-reviews"""
        return self._request(
            "POST", "/data-practice-reviews", _clean(payload), headers
        )

    def list_reviews(self, headers=None, **params):
        """GET /data-practice-reviews"""
        return self._request("GET", "/data-practice-reviews", _clean(params), headers)

    def get_review(self, review_id, headers=None):
        """GET /data-practice-reviews/{reviewId}"""
        return self._request(
            "GET", f"/data-practice-reviews/{review_id}", None, headers
        )

    def issue_findings(self, review_id, payload, headers=None):
        """POST /data-practice-reviews/{reviewId}/issue-findings"""
        return self._request(
            "POST",
            f"/data-practice-reviews/{review_id}/issue-findings",
            _clean(payload),
            headers,
        )

    def submit_remediation(self, review_id, payload, headers=None):
        """POST /data-practice-reviews/{reviewId}/submit-remediation"""
        return self._request(
            "POST",
            f"/data-practice-reviews/{review_id}/submit-remediation",
            _clean(payload),
            headers,
        )

    def decide_review(self, review_id, payload, headers=None):
        """POST /data-practice-reviews/{reviewId}/decide"""
        return self._request(
            "POST",
            f"/data-practice-reviews/{review_id}/decide",
            _clean(payload),
            headers,
        )

    def reassign_review(self, review_id, payload, headers=None):
        """POST /data-practice-reviews/{reviewId}/reassign"""
        return self._request(
            "POST",
            f"/data-practice-reviews/{review_id}/reassign",
            _clean(payload),
            headers,
        )

    # ------------------------------------------------------------------
    # Data element commitments
    # ------------------------------------------------------------------
    def create_commitment(self, payload, headers=None):
        """POST /data-element-commitments"""
        return self._request(
            "POST", "/data-element-commitments", _clean(payload), headers
        )

    def list_commitments(self, headers=None, **params):
        """GET /data-element-commitments"""
        return self._request(
            "GET", "/data-element-commitments", _clean(params), headers
        )

    def get_commitment(self, commitment_id, headers=None):
        """GET /data-element-commitments/{commitmentId}"""
        return self._request(
            "GET", f"/data-element-commitments/{commitment_id}", None, headers
        )

    def decide_commitment(self, commitment_id, payload, headers=None):
        """POST /data-element-commitments/{commitmentId}/decide"""
        return self._request(
            "POST",
            f"/data-element-commitments/{commitment_id}/decide",
            _clean(payload),
            headers,
        )

    # ------------------------------------------------------------------
    # Catalog entries
    # ------------------------------------------------------------------
    def create_catalog_entry(self, payload, headers=None):
        """POST /catalog-entries"""
        return self._request("POST", "/catalog-entries", _clean(payload), headers)

    def list_catalog_entries(self, headers=None, **params):
        """GET /catalog-entries"""
        return self._request("GET", "/catalog-entries", _clean(params), headers)

    def get_catalog_entry(self, entry_id, headers=None):
        """GET /catalog-entries/{entryId}"""
        return self._request("GET", f"/catalog-entries/{entry_id}", None, headers)

    def revoke_catalog_entry(self, entry_id, payload, headers=None):
        """POST /catalog-entries/{entryId}/revoke"""
        return self._request(
            "POST", f"/catalog-entries/{entry_id}/revoke", _clean(payload), headers
        )

    def reauthorize_catalog_entry(self, entry_id, payload, headers=None):
        """POST /catalog-entries/{entryId}/reauthorize"""
        return self._request(
            "POST",
            f"/catalog-entries/{entry_id}/reauthorize",
            _clean(payload),
            headers,
        )

    # ------------------------------------------------------------------
    # Compliance sweep
    # ------------------------------------------------------------------
    def run_sweep(self, headers=None):
        """POST /compliance-sweeps"""
        return self._request("POST", "/compliance-sweeps", {}, headers)

    # ------------------------------------------------------------------
    # Telemetry detections
    # ------------------------------------------------------------------
    def create_detection(self, payload, headers=None):
        """POST /telemetry-detections"""
        return self._request(
            "POST", "/telemetry-detections", _clean(payload), headers
        )

    def list_detections(self, headers=None, **params):
        """GET /telemetry-detections"""
        return self._request("GET", "/telemetry-detections", _clean(params), headers)

    def get_detection(self, detection_id, headers=None):
        """GET /telemetry-detections/{detectionId}"""
        return self._request(
            "GET", f"/telemetry-detections/{detection_id}", None, headers
        )

    def triage_detection(self, detection_id, payload, headers=None):
        """POST /telemetry-detections/{detectionId}/triage"""
        return self._request(
            "POST",
            f"/telemetry-detections/{detection_id}/triage",
            _clean(payload),
            headers,
        )

    # ------------------------------------------------------------------
    # Vendor incidents
    # ------------------------------------------------------------------
    def create_incident(self, payload, headers=None):
        """POST /vendor-incidents"""
        return self._request("POST", "/vendor-incidents", _clean(payload), headers)

    def list_incidents(self, headers=None, **params):
        """GET /vendor-incidents"""
        return self._request("GET", "/vendor-incidents", _clean(params), headers)

    def get_incident(self, incident_id, headers=None):
        """GET /vendor-incidents/{incidentId}"""
        return self._request("GET", f"/vendor-incidents/{incident_id}", None, headers)

    def contain_incident(self, incident_id, payload=None, headers=None):
        """POST /vendor-incidents/{incidentId}/contain"""
        return self._request(
            "POST",
            f"/vendor-incidents/{incident_id}/contain",
            _clean(payload or {}),
            headers,
        )

    def send_notification(self, incident_id, payload, headers=None):
        """POST /vendor-incidents/{incidentId}/send-notification"""
        return self._request(
            "POST",
            f"/vendor-incidents/{incident_id}/send-notification",
            _clean(payload),
            headers,
        )

    def resolve_incident(self, incident_id, payload, headers=None):
        """POST /vendor-incidents/{incidentId}/resolve"""
        return self._request(
            "POST",
            f"/vendor-incidents/{incident_id}/resolve",
            _clean(payload),
            headers,
        )
