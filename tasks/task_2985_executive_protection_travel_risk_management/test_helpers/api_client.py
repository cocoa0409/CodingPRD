"""HTTP client for the Executive Protection & Travel Risk Management API.

One method per endpoint of the routing table, returning the raw response so
tests can assert on status codes and on the response envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/exec-protection"


def _params(**kwargs: Any) -> Optional[Dict[str, Any]]:
    """Drop unset query arguments so an omitted filter is genuinely omitted."""
    cleaned = {k: v for k, v in kwargs.items() if v is not None}
    return cleaned or None


class ExecProtectionClient(GenericApiClient):
    """Endpoint methods for every route the service publishes."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------- security staff
    def create_security_staff(self, payload, headers):
        return self._request("POST", f"{BASE}/security-staff", payload, headers)

    def get_security_staff(self, staff_id, headers):
        return self._request("GET", f"{BASE}/security-staff/{staff_id}", None, headers)

    # ---------------------------------------------------------- executives
    def create_executive(self, payload, headers):
        return self._request("POST", f"{BASE}/executives", payload, headers)

    def get_executive(self, executive_id, headers):
        return self._request("GET", f"{BASE}/executives/{executive_id}", None, headers)

    def patch_executive_consent(self, executive_id, payload, headers):
        return self._request(
            "PATCH", f"{BASE}/executives/{executive_id}/consent", payload, headers
        )

    def record_residential_survey(self, executive_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/executives/{executive_id}/residential-survey",
            payload,
            headers,
        )

    def create_exposure_signal(self, executive_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/executives/{executive_id}/exposure-signals",
            payload,
            headers,
        )

    def list_exposure_signals(
        self, executive_id, headers, signal_type=None, limit=None, offset=None
    ):
        return self._request(
            "GET",
            f"{BASE}/executives/{executive_id}/exposure-signals",
            _params(signal_type=signal_type, limit=limit, offset=offset),
            headers,
        )

    def list_executive_insurance_policies(
        self, executive_id, headers, status=None, policy_type=None,
        limit=None, offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/executives/{executive_id}/insurance-policies",
            _params(
                status=status, policy_type=policy_type, limit=limit, offset=offset
            ),
            headers,
        )

    def get_perquisite_disclosure(self, executive_id, headers):
        return self._request(
            "GET",
            f"{BASE}/executives/{executive_id}/perquisite-disclosure",
            None,
            headers,
        )

    # ---------------------------------------------------- insurance policies
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", f"{BASE}/insurance-policies", payload, headers)

    def verify_insurance_policy(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/insurance-policies/{policy_id}/verify", payload, headers
        )

    # -------------------------------------------------- destination ratings
    def create_destination_rating(self, payload, headers):
        return self._request("POST", f"{BASE}/destination-ratings", payload, headers)

    def update_destination_rating(self, country_code, payload, headers):
        return self._request(
            "PATCH", f"{BASE}/destination-ratings/{country_code}", payload, headers
        )

    # ------------------------------------------------------ risk assessments
    def create_risk_assessment(self, payload, headers):
        return self._request("POST", f"{BASE}/risk-assessments", payload, headers)

    def list_risk_assessments(
        self, headers, executive_id=None, status=None, authored_by_staff_id=None,
        limit=None, offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/risk-assessments",
            _params(
                executive_id=executive_id,
                status=status,
                authored_by_staff_id=authored_by_staff_id,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_risk_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{BASE}/risk-assessments/{assessment_id}", None, headers
        )

    def submit_risk_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/risk-assessments/{assessment_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def review_risk_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/risk-assessments/{assessment_id}/review", payload, headers
        )

    # ------------------------------------------------------------------ trips
    def create_trip(self, payload, headers):
        return self._request("POST", f"{BASE}/trips", payload, headers)

    def list_trips(
        self, headers, executive_id=None, created_by_staff_id=None,
        risk_assessment_id=None, insurance_policy_id=None, approval_state=None,
        readiness_state=None, limit=None, offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/trips",
            _params(
                executive_id=executive_id,
                created_by_staff_id=created_by_staff_id,
                risk_assessment_id=risk_assessment_id,
                insurance_policy_id=insurance_policy_id,
                approval_state=approval_state,
                readiness_state=readiness_state,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"{BASE}/trips/{trip_id}", None, headers)

    def create_trip_leg(self, trip_id, payload, headers):
        return self._request("POST", f"{BASE}/trips/{trip_id}/legs", payload, headers)

    def list_trip_legs(self, trip_id, headers, limit=None, offset=None):
        return self._request(
            "GET",
            f"{BASE}/trips/{trip_id}/legs",
            _params(limit=limit, offset=offset),
            headers,
        )

    def submit_trip_for_approval(self, trip_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/trips/{trip_id}/submit-for-approval",
            payload if payload is not None else {},
            headers,
        )

    def decide_trip(self, trip_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/trips/{trip_id}/decision", payload, headers
        )

    def acknowledge_briefing(self, trip_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/trips/{trip_id}/briefing-ack",
            payload if payload is not None else {},
            headers,
        )

    def create_check_in(self, trip_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/trips/{trip_id}/check-ins", payload, headers
        )

    def list_check_ins(self, trip_id, headers, kind=None, limit=None, offset=None):
        return self._request(
            "GET",
            f"{BASE}/trips/{trip_id}/check-ins",
            _params(kind=kind, limit=limit, offset=offset),
            headers,
        )

    def report_incident(self, trip_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/trips/{trip_id}/incidents", payload, headers
        )

    def list_incidents(
        self, trip_id, headers, status=None, incident_type=None,
        limit=None, offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/trips/{trip_id}/incidents",
            _params(
                status=status, incident_type=incident_type, limit=limit, offset=offset
            ),
            headers,
        )

    def close_trip(self, trip_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/trips/{trip_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # -------------------------------------------------------------- trip legs
    def get_trip_leg(self, leg_id, headers):
        return self._request("GET", f"{BASE}/trip-legs/{leg_id}", None, headers)

    def record_advance_progress(self, leg_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/trip-legs/{leg_id}/advance-progress", payload, headers
        )

    # ------------------------------------------------------ detail assignments
    def create_detail_assignment(self, payload, headers):
        return self._request("POST", f"{BASE}/detail-assignments", payload, headers)

    def list_detail_assignments(
        self, headers, trip_leg_id=None, staff_id=None, status=None,
        limit=None, offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/detail-assignments",
            _params(
                trip_leg_id=trip_leg_id,
                staff_id=staff_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_detail_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{BASE}/detail-assignments/{assignment_id}", None, headers
        )

    def release_detail_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/detail-assignments/{assignment_id}/release",
            payload,
            headers,
        )

    # -------------------------------------------------------------- vendors
    def create_vendor(self, payload, headers):
        return self._request("POST", f"{BASE}/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"{BASE}/vendors/{vendor_id}", None, headers)

    def suspend_vendor(self, vendor_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/vendors/{vendor_id}/suspend", payload, headers
        )

    # --------------------------------------------------- vendor engagements
    def create_vendor_engagement(self, payload, headers):
        return self._request("POST", f"{BASE}/vendor-engagements", payload, headers)

    def list_vendor_engagements(
        self, headers, vendor_id=None, trip_leg_id=None, incident_id=None,
        status=None, limit=None, offset=None,
    ):
        return self._request(
            "GET",
            f"{BASE}/vendor-engagements",
            _params(
                vendor_id=vendor_id,
                trip_leg_id=trip_leg_id,
                incident_id=incident_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def get_vendor_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"{BASE}/vendor-engagements/{engagement_id}", None, headers
        )

    def complete_vendor_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/vendor-engagements/{engagement_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------ incidents
    def triage_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/incidents/{incident_id}/triage", payload, headers
        )

    def resolve_incident(self, incident_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/incidents/{incident_id}/resolve",
            payload if payload is not None else {},
            headers,
        )

    def close_incident(self, incident_id, headers, payload=None):
        return self._request(
            "POST",
            f"{BASE}/incidents/{incident_id}/close",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------- raw pagination probe
    def list_trips_raw(self, headers, params):
        """List trips passing the pagination arguments through verbatim."""
        return self._request("GET", f"{BASE}/trips", params, headers)
