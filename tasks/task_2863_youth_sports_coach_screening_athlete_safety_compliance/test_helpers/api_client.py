"""One method per endpoint of the SafeSport compliance API (PRD 4).

Every method returns the raw ``requests.Response`` so a test can assert the HTTP
status itself.  ``headers`` is always explicit: the platform refuses any request
whose identity headers are absent, so there is no implicit default caller.

Timestamps that come back from the API are normalised to exactly three
fractional digits before a test compares them, because PRD 2.2 and PRD 2.4
mandate that width and a server that emits a wider or narrower fraction is
still reporting the same instant.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import BASE

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Render an ISO 8601 instant with the three fractional digits PRD 2.2 asks for."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    seconds, fraction, offset = match.groups()
    if offset in ("+00:00", "+0000"):
        offset = "Z"
    millis = (fraction or "")[:3].ljust(3, "0")
    return f"{seconds}.{millis}{offset}"


class ApiClient(GenericApiClient):
    """Endpoint-level client for the API mounted under ``/safesport``."""

    # ------------------------------------------------------------------
    # Logical clock (PRD 2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Clubs (PRD 3.1)
    # ------------------------------------------------------------------
    def charter_club(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/clubs", payload, headers)

    def get_club(self, club_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/clubs/{club_id}", None, headers)

    def fund_escrow(
        self, club_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/clubs/{club_id}/escrow-funding", payload, headers
        )

    def list_club_members(self, club_id: str, headers: Dict[str, str], **filters: Any):
        return self._request(
            "GET", f"{BASE}/clubs/{club_id}/members", filters or None, headers
        )

    def list_audits_of_club(self, club_id: str, headers: Dict[str, str], **filters: Any):
        """The club-scoped audit list of PRD 4, ordered created_at descending."""
        return self._request(
            "GET", f"{BASE}/clubs/{club_id}/audits", filters or None, headers
        )

    def list_club_room_stays(
        self, club_id: str, headers: Dict[str, str], **filters: Any
    ):
        return self._request(
            "GET", f"{BASE}/clubs/{club_id}/room-stays", filters or None, headers
        )

    # ------------------------------------------------------------------
    # Members (PRD 3.1, PRD 3.5)
    # ------------------------------------------------------------------
    def register_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/members/{member_id}", None, headers)

    def list_members(self, headers: Dict[str, str], **filters: Any):
        return self._request("GET", f"{BASE}/members", filters or None, headers)

    def get_eligibility_projection(
        self, member_id: str, headers: Dict[str, str], **filters: Any
    ):
        return self._request(
            "GET",
            f"{BASE}/members/{member_id}/eligibility-projection",
            filters or None,
            headers,
        )

    def renew_membership(
        self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/members/{member_id}/renew", payload, headers
        )

    def list_member_screening_orders(
        self, member_id: str, headers: Dict[str, str], **filters: Any
    ):
        return self._request(
            "GET",
            f"{BASE}/members/{member_id}/screening-orders",
            filters or None,
            headers,
        )

    def list_member_training_assignments(
        self, member_id: str, headers: Dict[str, str], **filters: Any
    ):
        return self._request(
            "GET",
            f"{BASE}/members/{member_id}/training-assignments",
            filters or None,
            headers,
        )

    def list_member_room_stays(
        self, member_id: str, headers: Dict[str, str], **filters: Any
    ):
        return self._request(
            "GET", f"{BASE}/members/{member_id}/room-stays", filters or None, headers
        )

    # ------------------------------------------------------------------
    # Screening orders (PRD 3.2, PRD 3.3)
    # ------------------------------------------------------------------
    def order_screening(
        self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/members/{member_id}/screening-orders", payload, headers
        )

    def get_screening_order(self, screening_order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/screening-orders/{screening_order_id}", None, headers
        )

    def list_screening_orders(self, headers: Dict[str, str], **filters: Any):
        return self._request(
            "GET", f"{BASE}/screening-orders", filters or None, headers
        )

    def post_screening_result(
        self,
        screening_order_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/screening-orders/{screening_order_id}/result",
            payload,
            headers,
        )

    def adjudicate_screening_order(
        self,
        screening_order_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/screening-orders/{screening_order_id}/adjudicate",
            payload,
            headers,
        )

    def void_screening_order(
        self,
        screening_order_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/screening-orders/{screening_order_id}/void",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Training (PRD 3.4)
    # ------------------------------------------------------------------
    def publish_course(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/training-courses", payload, headers)

    def assign_training(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/training-assignments", payload, headers)

    def get_training_assignment(
        self, training_assignment_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"{BASE}/training-assignments/{training_assignment_id}", None, headers
        )

    def list_training_assignments(self, headers: Dict[str, str], **filters: Any):
        return self._request(
            "GET", f"{BASE}/training-assignments", filters or None, headers
        )

    def start_training(self, training_assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{BASE}/training-assignments/{training_assignment_id}/start",
            {},
            headers,
        )

    def complete_training(
        self,
        training_assignment_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/training-assignments/{training_assignment_id}/complete",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Coach placements (PRD 3.6)
    # ------------------------------------------------------------------
    def create_coach_assignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/coach-assignments", payload, headers)

    def get_coach_assignment(self, coach_assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/coach-assignments/{coach_assignment_id}", None, headers
        )

    def list_coach_assignments(self, headers: Dict[str, str], **filters: Any):
        return self._request(
            "GET", f"{BASE}/coach-assignments", filters or None, headers
        )

    def activate_coach_assignment(
        self,
        coach_assignment_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/coach-assignments/{coach_assignment_id}/activate",
            payload,
            headers,
        )

    def authorize_electronic_communication(
        self,
        coach_assignment_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/coach-assignments/{coach_assignment_id}"
            "/electronic-communication-authorization",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Travel and lodging (PRD 3.7)
    # ------------------------------------------------------------------
    def book_room_stay(
        self, club_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/clubs/{club_id}/room-stays", payload, headers
        )

    def get_room_stay(self, room_stay_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/room-stays/{room_stay_id}", None, headers)

    def list_room_stays(self, headers: Dict[str, str], **filters: Any):
        return self._request("GET", f"{BASE}/room-stays", filters or None, headers)

    def cancel_room_stay(
        self,
        room_stay_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"{BASE}/room-stays/{room_stay_id}/cancel",
            {} if payload is None else payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Investigating bodies, cases and interim measures (PRD 3.8)
    # ------------------------------------------------------------------
    def register_investigating_body(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/investigating-bodies", payload, headers)

    def get_investigating_body(
        self, investigating_body_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"{BASE}/investigating-bodies/{investigating_body_id}",
            None,
            headers,
        )

    def file_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/cases/{case_id}", None, headers)

    def list_cases(self, headers: Dict[str, str], **filters: Any):
        return self._request("GET", f"{BASE}/cases", filters or None, headers)

    def route_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/cases/{case_id}/route", payload, headers)

    def close_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/cases/{case_id}/close", payload, headers)

    def impose_interim_measure(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/cases/{case_id}/interim-measures", payload, headers
        )

    def get_interim_measure(self, interim_measure_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/interim-measures/{interim_measure_id}", None, headers
        )

    def list_interim_measures(self, headers: Dict[str, str], **filters: Any):
        return self._request(
            "GET", f"{BASE}/interim-measures", filters or None, headers
        )

    def lift_interim_measure(
        self,
        interim_measure_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/interim-measures/{interim_measure_id}/lift",
            payload,
            headers,
        )

    def convert_interim_measure_permanent(
        self,
        interim_measure_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/interim-measures/{interim_measure_id}/convert-permanent",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Compliance audits and findings (PRD 3.9)
    # ------------------------------------------------------------------
    def open_club_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/club-audits", payload, headers)

    def get_club_audit(self, club_audit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/club-audits/{club_audit_id}", None, headers)

    def list_club_audits(self, headers: Dict[str, str], **filters: Any):
        return self._request("GET", f"{BASE}/club-audits", filters or None, headers)

    def write_finding(
        self, club_audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/club-audits/{club_audit_id}/findings", payload, headers
        )

    def finalize_club_audit(
        self, club_audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/club-audits/{club_audit_id}/finalize", payload, headers
        )

    def close_club_audit(
        self, club_audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/club-audits/{club_audit_id}/close", payload, headers
        )

    def get_audit_finding(self, audit_finding_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/audit-findings/{audit_finding_id}", None, headers
        )

    def list_audit_findings(self, headers: Dict[str, str], **filters: Any):
        return self._request("GET", f"{BASE}/audit-findings", filters or None, headers)

    def decide_finding(
        self,
        audit_finding_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"{BASE}/audit-findings/{audit_finding_id}/decision",
            payload,
            headers,
        )
