"""One client method per endpoint of the Homestead Exemption & Property Tax
Relief API.

Every method returns the raw response so callers can assert on the status code
themselves.  Collection reads take their equality filters and their pagination
window as keyword arguments and forward them as query parameters.

The module also exposes ``canonical_instant``, which normalises the sub-second
width of an ISO-8601 UTC instant so that "2026-08-01T00:00:00Z",
"2026-08-01T00:00:00.000Z" and "2026-08-01T00:00:00.000000Z" compare equal.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[T ](?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?(?P<zone>Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Any) -> Any:
    """Return an ISO-8601 UTC instant with its sub-second part removed.

    Non-instant values (None, numbers, calendar dates) are returned untouched, so
    the helper is safe to apply to any field before comparing it.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = match.group("frac") or ""
    # A non-zero fractional part is meaningful and must survive canonicalisation.
    if frac and int(frac) != 0:
        return f"{match.group('date')}T{match.group('time')}.{frac.rstrip('0')}Z"
    return f"{match.group('date')}T{match.group('time')}Z"


def _query(**kwargs: Any) -> Optional[Dict[str, Any]]:
    """Drop keyword arguments that were not supplied."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return params or None


class ApiClient(GenericApiClient):
    """Endpoint methods for the county relief administration API."""

    # ---------------------------------------------------------------- clock

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        """Move the logical clock to a supplied instant."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------ registry inject

    def create_registry_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """Inject an external data-source record for a taxpayer."""
        return self._request("POST", "/_registry-records", payload, headers)

    # ------------------------------------------------------ relief programs

    def create_relief_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/relief-programs", payload, headers)

    def get_relief_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/relief-programs/{program_id}", None, headers)

    # -------------------------------------------------------------- parcels

    def create_parcel(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/parcels/{parcel_id}", None, headers)

    # ---------------------------------------------------- taxpayer accounts

    def create_taxpayer_account(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/taxpayer-accounts", payload, headers)

    def get_taxpayer_account(self, taxpayer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/taxpayer-accounts/{taxpayer_id}", None, headers)

    # ---------------------------------------------------- ownership records

    def create_ownership_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/ownership-records", payload, headers)

    def get_ownership_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/ownership-records/{record_id}", None, headers)

    def list_ownership_records(
        self,
        headers: Dict[str, str],
        parcel_id: Optional[str] = None,
        taxpayer_id: Optional[str] = None,
        occupancy_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            "/ownership-records",
            _query(
                parcel_id=parcel_id,
                taxpayer_id=taxpayer_id,
                occupancy_type=occupancy_type,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    # ------------------------------------------------ exemption applications

    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/exemption-applications", payload, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/exemption-applications/{application_id}", None, headers
        )

    def list_applications(
        self,
        headers: Dict[str, str],
        parcel_id: Optional[str] = None,
        taxpayer_id: Optional[str] = None,
        program_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            "/exemption-applications",
            _query(
                parcel_id=parcel_id,
                taxpayer_id=taxpayer_id,
                program_id=program_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def submit_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/exemption-applications/{application_id}/submit", {}, headers
        )

    def create_verification_check(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/exemption-applications/{application_id}/verification-checks",
            payload,
            headers,
        )

    def list_verification_checks(
        self,
        application_id: str,
        headers: Dict[str, str],
        source: Optional[str] = None,
        result: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"/exemption-applications/{application_id}/verification-checks",
            _query(source=source, result=result, limit=limit, offset=offset),
            headers,
        )

    def respond_info(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/exemption-applications/{application_id}/respond-info",
            payload,
            headers,
        )

    def determine_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/exemption-applications/{application_id}/determine",
            payload,
            headers,
        )

    # ------------------------------------------------- income certifications

    def create_income_certification(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/income-certifications", payload, headers)

    def list_income_certifications(
        self,
        taxpayer_id: str,
        headers: Dict[str, str],
        certification_year: Optional[int] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"/taxpayer-accounts/{taxpayer_id}/income-certifications",
            _query(
                certification_year=certification_year,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    # ----------------------------------------------------- exemption grants

    def get_grant(self, grant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/exemption-grants/{grant_id}", None, headers)

    def list_grants(
        self,
        headers: Dict[str, str],
        parcel_id: Optional[str] = None,
        taxpayer_id: Optional[str] = None,
        application_id: Optional[str] = None,
        program_id: Optional[str] = None,
        ported_from_grant_id: Optional[str] = None,
        benefit_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            "/exemption-grants",
            _query(
                parcel_id=parcel_id,
                taxpayer_id=taxpayer_id,
                application_id=application_id,
                program_id=program_id,
                ported_from_grant_id=ported_from_grant_id,
                benefit_status=benefit_status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def port_grant(
        self, grant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/exemption-grants/{grant_id}/port", payload, headers
        )

    def grant_compliance_action(
        self, grant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/exemption-grants/{grant_id}/compliance-actions", payload, headers
        )

    # --------------------------------------------------- retroactive claims

    def create_retroactive_claim(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/retroactive-claims", payload, headers)

    def get_retroactive_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/retroactive-claims/{claim_id}", None, headers)

    def list_grant_retroactive_claims(
        self,
        grant_id: str,
        headers: Dict[str, str],
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"/exemption-grants/{grant_id}/retroactive-claims",
            _query(status=status, limit=limit, offset=offset),
            headers,
        )

    def decide_retroactive_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/retroactive-claims/{claim_id}/decide", payload, headers
        )

    # ---------------------------------------------------------- fraud cases

    def create_fraud_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/fraud-cases", payload, headers)

    def get_fraud_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/fraud-cases/{case_id}", None, headers)

    def list_fraud_cases(
        self,
        headers: Dict[str, str],
        taxpayer_id: Optional[str] = None,
        grant_id: Optional[str] = None,
        investigation_status: Optional[str] = None,
        recovery_status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            "/fraud-cases",
            _query(
                taxpayer_id=taxpayer_id,
                grant_id=grant_id,
                investigation_status=investigation_status,
                recovery_status=recovery_status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def decide_fraud_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/fraud-cases/{case_id}/decide", payload, headers
        )

    def fraud_recovery_action(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/fraud-cases/{case_id}/recovery-actions", payload, headers
        )

    # -------------------------------------------------------------- notices

    def list_notices(
        self,
        taxpayer_id: str,
        headers: Dict[str, str],
        notice_type: Optional[str] = None,
        subject_id: Optional[str] = None,
        subject_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            f"/taxpayer-accounts/{taxpayer_id}/notices",
            _query(
                notice_type=notice_type,
                subject_id=subject_id,
                subject_type=subject_type,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    # ------------------------------------------------------ hearing dockets

    def create_hearing_docket(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/hearing-dockets", payload, headers)

    def get_hearing_docket(self, docket_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/hearing-dockets/{docket_id}", None, headers)

    def close_hearing_docket(
        self,
        docket_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/hearing-dockets/{docket_id}/close", payload or {}, headers
        )

    # -------------------------------------------------------------- appeals

    def create_appeal(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/appeals/{appeal_id}", None, headers)

    def list_appeals(
        self,
        headers: Dict[str, str],
        notice_id: Optional[str] = None,
        taxpayer_id: Optional[str] = None,
        docket_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ):
        return self._request(
            "GET",
            "/appeals",
            _query(
                notice_id=notice_id,
                taxpayer_id=taxpayer_id,
                docket_id=docket_id,
                status=status,
                limit=limit,
                offset=offset,
            ),
            headers,
        )

    def schedule_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/appeals/{appeal_id}/schedule", payload, headers
        )

    def decide_appeal(
        self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # ------------------------------------------------- assessment roll runs

    def create_assessment_roll_run(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/assessment-roll-runs", payload, headers)
