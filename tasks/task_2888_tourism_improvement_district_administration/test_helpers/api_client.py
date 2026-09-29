"""HTTP client for the Tourism Improvement District Administration API.

One method per endpoint of PRD 4, rooted at the service root exactly as the
table publishes the paths.  The base URL comes from the environment the runner
provides, so no port is ever hardcoded in a test.
"""
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 instant to UTC with exactly three fractional digits.

    PRD 2.5 fixes the wire format of every server-stamped timestamp at "ISO 8601
    ... in UTC with three fractional digits", but a request literal may legally
    be written without them.  Comparing instants through this function therefore
    compares the instants themselves rather than their textual width.
    """
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (parsed.microsecond // 1000)


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO 8601 strings denote the same instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Every operation of PRD 4, one method apiece."""

    def __init__(self, base_url: Optional[str] = None):
        resolved = (
            base_url
            or os.environ.get("API_BASE_URL")
            or os.environ.get("API_URL")
            or os.environ.get("BASE_URL")
            or "http://localhost:10000"
        )
        super().__init__(base_url=resolved)

    # ------------------------------------------------------------------
    # Logical clock (PRD 2.4)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Optional[Dict[str, str]] = None):
        """POST /_clock/set_current_utc"""
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Districts (PRD 3.1)
    # ------------------------------------------------------------------
    def list_districts(self, headers=None, params: Optional[Dict] = None):
        """GET /districts"""
        return self._request("GET", "/districts", params=params, headers=headers)

    def get_district(self, district_id: str, headers=None):
        """GET /districts/{id}"""
        return self._request("GET", "/districts/%s" % district_id, headers=headers)

    def get_district_financial_summary(
        self, district_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /districts/{id}/financial-summary"""
        return self._request(
            "GET",
            "/districts/%s/financial-summary" % district_id,
            params=params,
            headers=headers,
        )

    def list_district_lodging_businesses(
        self, district_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /districts/{id}/lodging-businesses"""
        return self._request(
            "GET",
            "/districts/%s/lodging-businesses" % district_id,
            params=params,
            headers=headers,
        )

    def list_district_petition_drives(
        self, district_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /districts/{id}/petition-drives"""
        return self._request(
            "GET",
            "/districts/%s/petition-drives" % district_id,
            params=params,
            headers=headers,
        )

    def list_district_assessment_periods(
        self, district_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /districts/{id}/assessment-periods"""
        return self._request(
            "GET",
            "/districts/%s/assessment-periods" % district_id,
            params=params,
            headers=headers,
        )

    def list_district_annual_work_plans(
        self, district_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /districts/{id}/annual-work-plans"""
        return self._request(
            "GET",
            "/districts/%s/annual-work-plans" % district_id,
            params=params,
            headers=headers,
        )

    def list_district_transparency_records(
        self, district_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /districts/{id}/transparency-records"""
        return self._request(
            "GET",
            "/districts/%s/transparency-records" % district_id,
            params=params,
            headers=headers,
        )

    def create_district(self, payload: Dict[str, Any], headers=None):
        """POST /districts"""
        return self._request("POST", "/districts", payload, headers)

    def revise_district_boundary(self, district_id: str, payload: Dict[str, Any], headers=None):
        """POST /districts/{id}/boundary-revisions"""
        return self._request(
            "POST", "/districts/%s/boundary-revisions" % district_id, payload, headers
        )

    def record_dmo_coordination(self, district_id: str, payload: Dict[str, Any], headers=None):
        """POST /districts/{id}/dmo-coordination"""
        return self._request(
            "POST", "/districts/%s/dmo-coordination" % district_id, payload, headers
        )

    def advance_district_lifecycle(self, district_id: str, payload: Dict[str, Any], headers=None):
        """POST /districts/{id}/lifecycle-advances"""
        return self._request(
            "POST", "/districts/%s/lifecycle-advances" % district_id, payload, headers
        )

    # ------------------------------------------------------------------
    # Lodging businesses (PRD 3.1)
    # ------------------------------------------------------------------
    def create_lodging_business(self, payload: Dict[str, Any], headers=None):
        """POST /lodging-businesses"""
        return self._request("POST", "/lodging-businesses", payload, headers)

    def revise_lodging_business(self, business_id: str, payload: Dict[str, Any], headers=None):
        """POST /lodging-businesses/{id}/revisions"""
        return self._request(
            "POST", "/lodging-businesses/%s/revisions" % business_id, payload, headers
        )

    def get_lodging_business(self, business_id: str, headers=None):
        """GET /lodging-businesses/{id}"""
        return self._request(
            "GET", "/lodging-businesses/%s" % business_id, headers=headers
        )

    def list_business_petition_signatures(
        self, business_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /lodging-businesses/{id}/petition-signatures"""
        return self._request(
            "GET",
            "/lodging-businesses/%s/petition-signatures" % business_id,
            params=params,
            headers=headers,
        )

    def list_business_assessment_statements(
        self, business_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /lodging-businesses/{id}/assessment-statements"""
        return self._request(
            "GET",
            "/lodging-businesses/%s/assessment-statements" % business_id,
            params=params,
            headers=headers,
        )

    def list_business_room_night_claims(
        self, business_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /lodging-businesses/{id}/room-night-claims"""
        return self._request(
            "GET",
            "/lodging-businesses/%s/room-night-claims" % business_id,
            params=params,
            headers=headers,
        )

    def list_business_disputes(
        self, business_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /lodging-businesses/{id}/disputes"""
        return self._request(
            "GET",
            "/lodging-businesses/%s/disputes" % business_id,
            params=params,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Petition drives and signatures (PRD 3.2)
    # ------------------------------------------------------------------
    def create_petition_drive(self, payload: Dict[str, Any], headers=None):
        """POST /petition-drives"""
        return self._request("POST", "/petition-drives", payload, headers)

    def get_petition_drive(self, drive_id: str, headers=None):
        """GET /petition-drives/{id}"""
        return self._request("GET", "/petition-drives/%s" % drive_id, headers=headers)

    def list_drive_signatures(self, drive_id: str, headers=None, params: Optional[Dict] = None):
        """GET /petition-drives/{id}/signatures"""
        return self._request(
            "GET",
            "/petition-drives/%s/signatures" % drive_id,
            params=params,
            headers=headers,
        )

    def sign_petition(self, drive_id: str, payload: Dict[str, Any], headers=None):
        """POST /petition-drives/{id}/signatures"""
        return self._request(
            "POST", "/petition-drives/%s/signatures" % drive_id, payload, headers
        )

    def tally_petition_drive(self, drive_id: str, payload: Optional[Dict[str, Any]] = None, headers=None):
        """POST /petition-drives/{id}/tally"""
        return self._request(
            "POST", "/petition-drives/%s/tally" % drive_id, payload if payload is not None else {}, headers
        )

    def certify_petition_drive(self, drive_id: str, payload: Optional[Dict[str, Any]] = None, headers=None):
        """POST /petition-drives/{id}/certification"""
        return self._request(
            "POST",
            "/petition-drives/%s/certification" % drive_id,
            payload if payload is not None else {},
            headers,
        )

    def get_petition_signature(self, signature_id: str, headers=None):
        """GET /petition-signatures/{id}"""
        return self._request(
            "GET", "/petition-signatures/%s" % signature_id, headers=headers
        )

    def withdraw_signature(self, signature_id: str, payload: Optional[Dict[str, Any]] = None, headers=None):
        """POST /petition-signatures/{id}/withdrawal"""
        return self._request(
            "POST",
            "/petition-signatures/%s/withdrawal" % signature_id,
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Assessment periods and statements (PRD 3.3)
    # ------------------------------------------------------------------
    def create_assessment_period(self, payload: Dict[str, Any], headers=None):
        """POST /assessment-periods"""
        return self._request("POST", "/assessment-periods", payload, headers)

    def get_assessment_period(self, period_id: str, headers=None):
        """GET /assessment-periods/{id}"""
        return self._request(
            "GET", "/assessment-periods/%s" % period_id, headers=headers
        )

    def list_period_statements(self, period_id: str, headers=None, params: Optional[Dict] = None):
        """GET /assessment-periods/{id}/statements"""
        return self._request(
            "GET",
            "/assessment-periods/%s/statements" % period_id,
            params=params,
            headers=headers,
        )

    def generate_statements(self, period_id: str, payload: Optional[Dict[str, Any]] = None, headers=None):
        """POST /assessment-periods/{id}/statement-generation"""
        return self._request(
            "POST",
            "/assessment-periods/%s/statement-generation" % period_id,
            payload if payload is not None else {},
            headers,
        )

    def close_assessment_period(self, period_id: str, payload: Optional[Dict[str, Any]] = None, headers=None):
        """POST /assessment-periods/{id}/closure"""
        return self._request(
            "POST",
            "/assessment-periods/%s/closure" % period_id,
            payload if payload is not None else {},
            headers,
        )

    def sweep_delinquency(self, period_id: str, payload: Optional[Dict[str, Any]] = None, headers=None):
        """POST /assessment-periods/{id}/delinquency-sweep"""
        return self._request(
            "POST",
            "/assessment-periods/%s/delinquency-sweep" % period_id,
            payload if payload is not None else {},
            headers,
        )

    def get_assessment_statement(self, statement_id: str, headers=None):
        """GET /assessment-statements/{id}"""
        return self._request(
            "GET", "/assessment-statements/%s" % statement_id, headers=headers
        )

    def file_statement(self, statement_id: str, payload: Dict[str, Any], headers=None):
        """POST /assessment-statements/{id}/filings"""
        return self._request(
            "POST", "/assessment-statements/%s/filings" % statement_id, payload, headers
        )

    def amend_statement(self, statement_id: str, payload: Dict[str, Any], headers=None):
        """POST /assessment-statements/{id}/amendments"""
        return self._request(
            "POST",
            "/assessment-statements/%s/amendments" % statement_id,
            payload,
            headers,
        )

    def submit_remittance(self, statement_id: str, payload: Dict[str, Any], headers=None):
        """POST /assessment-statements/{id}/remittances"""
        return self._request(
            "POST",
            "/assessment-statements/%s/remittances" % statement_id,
            payload,
            headers,
        )

    def list_statement_remittances(
        self, statement_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /assessment-statements/{id}/remittances"""
        return self._request(
            "GET",
            "/assessment-statements/%s/remittances" % statement_id,
            params=params,
            headers=headers,
        )

    def reverse_remittance(self, statement_id: str, payload: Dict[str, Any], headers=None):
        """POST /assessment-statements/{id}/remittance-reversals"""
        return self._request(
            "POST",
            "/assessment-statements/%s/remittance-reversals" % statement_id,
            payload,
            headers,
        )

    def audit_certify_statement(self, statement_id: str, payload: Dict[str, Any], headers=None):
        """POST /assessment-statements/{id}/audit-certification"""
        return self._request(
            "POST",
            "/assessment-statements/%s/audit-certification" % statement_id,
            payload,
            headers,
        )

    def get_remittance(self, remittance_id: str, headers=None):
        """GET /remittances/{id}"""
        return self._request("GET", "/remittances/%s" % remittance_id, headers=headers)

    # ------------------------------------------------------------------
    # Disputes (PRD 3.6)
    # ------------------------------------------------------------------
    def create_dispute(self, payload: Dict[str, Any], headers=None):
        """POST /assessment-disputes"""
        return self._request("POST", "/assessment-disputes", payload, headers)

    def get_dispute(self, dispute_id: str, headers=None):
        """GET /assessment-disputes/{id}"""
        return self._request(
            "GET", "/assessment-disputes/%s" % dispute_id, headers=headers
        )

    def list_statement_disputes(
        self, statement_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /assessment-statements/{id}/disputes"""
        return self._request(
            "GET",
            "/assessment-statements/%s/disputes" % statement_id,
            params=params,
            headers=headers,
        )

    def advance_dispute(self, dispute_id: str, payload: Dict[str, Any], headers=None):
        """POST /assessment-disputes/{id}/proceedings"""
        return self._request(
            "POST", "/assessment-disputes/%s/proceedings" % dispute_id, payload, headers
        )

    def resolve_dispute(self, dispute_id: str, payload: Dict[str, Any], headers=None):
        """POST /assessment-disputes/{id}/resolution"""
        return self._request(
            "POST", "/assessment-disputes/%s/resolution" % dispute_id, payload, headers
        )

    # ------------------------------------------------------------------
    # Annual work plans (PRD 3.7)
    # ------------------------------------------------------------------
    def create_work_plan(self, payload: Dict[str, Any], headers=None):
        """POST /annual-work-plans"""
        return self._request("POST", "/annual-work-plans", payload, headers)

    def get_work_plan(self, plan_id: str, headers=None):
        """GET /annual-work-plans/{id}"""
        return self._request("GET", "/annual-work-plans/%s" % plan_id, headers=headers)

    def board_action(self, plan_id: str, payload: Dict[str, Any], headers=None):
        """POST /annual-work-plans/{id}/board-actions"""
        return self._request(
            "POST", "/annual-work-plans/%s/board-actions" % plan_id, payload, headers
        )

    def amend_work_plan(self, plan_id: str, payload: Dict[str, Any], headers=None):
        """POST /annual-work-plans/{id}/amendments"""
        return self._request(
            "POST", "/annual-work-plans/%s/amendments" % plan_id, payload, headers
        )

    def list_plan_marketing_programs(
        self, plan_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /annual-work-plans/{id}/marketing-programs"""
        return self._request(
            "GET",
            "/annual-work-plans/%s/marketing-programs" % plan_id,
            params=params,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Marketing programs, claims and performance (PRD 3.8)
    # ------------------------------------------------------------------
    def create_marketing_program(self, payload: Dict[str, Any], headers=None):
        """POST /marketing-programs"""
        return self._request("POST", "/marketing-programs", payload, headers)

    def get_marketing_program(self, program_id: str, headers=None):
        """GET /marketing-programs/{id}"""
        return self._request(
            "GET", "/marketing-programs/%s" % program_id, headers=headers
        )

    def launch_marketing_program(self, program_id: str, payload: Optional[Dict[str, Any]] = None, headers=None):
        """POST /marketing-programs/{id}/launch"""
        return self._request(
            "POST",
            "/marketing-programs/%s/launch" % program_id,
            payload if payload is not None else {},
            headers,
        )

    def close_marketing_program(self, program_id: str, payload: Optional[Dict[str, Any]] = None, headers=None):
        """POST /marketing-programs/{id}/closure"""
        return self._request(
            "POST",
            "/marketing-programs/%s/closure" % program_id,
            payload if payload is not None else {},
            headers,
        )

    def create_room_night_claim(self, program_id: str, payload: Dict[str, Any], headers=None):
        """POST /marketing-programs/{id}/room-night-claims"""
        return self._request(
            "POST",
            "/marketing-programs/%s/room-night-claims" % program_id,
            payload,
            headers,
        )

    def list_program_room_night_claims(
        self, program_id: str, headers=None, params: Optional[Dict] = None
    ):
        """GET /marketing-programs/{id}/room-night-claims"""
        return self._request(
            "GET",
            "/marketing-programs/%s/room-night-claims" % program_id,
            params=params,
            headers=headers,
        )

    def get_room_night_claim(self, claim_id: str, headers=None):
        """GET /room-night-claims/{id}"""
        return self._request(
            "GET", "/room-night-claims/%s" % claim_id, headers=headers
        )

    def verify_room_night_claim(self, claim_id: str, payload: Dict[str, Any], headers=None):
        """POST /room-night-claims/{id}/verification"""
        return self._request(
            "POST", "/room-night-claims/%s/verification" % claim_id, payload, headers
        )

    # ------------------------------------------------------------------
    # Transparency records (PRD 3.9)
    # ------------------------------------------------------------------
    def create_transparency_record(self, payload: Dict[str, Any], headers=None):
        """POST /transparency-records"""
        return self._request("POST", "/transparency-records", payload, headers)

    def get_transparency_record(self, record_id: str, headers=None):
        """GET /transparency-records/{id}"""
        return self._request(
            "GET", "/transparency-records/%s" % record_id, headers=headers
        )

    def advance_transparency_record(self, record_id: str, payload: Dict[str, Any], headers=None):
        """POST /transparency-records/{id}/advance"""
        return self._request(
            "POST", "/transparency-records/%s/advance" % record_id, payload, headers
        )
