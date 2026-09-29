"""API client: one method per endpoint defined in the PRD's endpoint table.

Also exposes ``canonical_instant`` / ``same_instant``: the PRD writes ISO 8601 UTC
instants with three fractional digits, but a payload may legitimately be echoed
with or without the ``.000`` component.  Tests compare instants through these
helpers instead of asserting on raw string width.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to whole-second precision for comparison.

    ``2026-08-01T14:30:00.000Z`` and ``2026-08-01T14:30:00Z`` both canonicalise to
    ``2026-08-01T14:30:00Z``.  Values that are not instants (``None``, calendar
    dates) are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    date_part, hour, minute, second, fraction = match.groups()
    if fraction and int(fraction.ljust(6, "0")) != 0:
        # Preserve a genuinely non-zero sub-second component, trimmed to millis.
        return f"{date_part}T{hour}:{minute}:{second}.{fraction[:3].ljust(3, '0')}Z"
    return f"{date_part}T{hour}:{minute}:{second}Z"


def same_instant(actual: Optional[str], expected: Optional[str]) -> bool:
    """True when two ISO 8601 UTC instants denote the same moment."""
    return canonical_instant(actual) == canonical_instant(expected)


class ApiClient(GenericApiClient):
    """One method per row of the PRD endpoint table."""

    # ── Logical clock and operations ──────────────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_expiry_sweep(self, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", "/_ops/expiry-sweep", payload or {}, headers)

    # ── Dialysis facilities ───────────────────────────────────────────────────

    def create_dialysis_facility(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dialysis-facilities", payload, headers)

    def get_dialysis_facility(self, facility_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/dialysis-facilities/{facility_id}", headers=headers
        )

    def list_facility_patients(
        self, facility_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/dialysis-facilities/{facility_id}/patients",
            headers=headers,
            params=params,
        )

    def list_facility_surveillance_readings(
        self, facility_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/dialysis-facilities/{facility_id}/surveillance-readings",
            headers=headers,
            params=params,
        )

    def get_facility_partnership_metrics(
        self, facility_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"/dialysis-facilities/{facility_id}/partnership-metrics",
            headers=headers,
        )

    # ── Patients ──────────────────────────────────────────────────────────────

    def create_patient(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ── Clinicians ────────────────────────────────────────────────────────────

    def create_clinician(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    # ── Procedure rooms ───────────────────────────────────────────────────────

    def create_procedure_room(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/procedure-rooms", payload, headers)

    def get_procedure_room(self, room_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/procedure-rooms/{room_id}", headers=headers)

    # ── Device lots ───────────────────────────────────────────────────────────

    def create_device_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/device-lots", payload, headers)

    def quarantine_device_lot(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/device-lots/{lot_id}/quarantine", payload, headers
        )

    def release_device_lot(
        self, lot_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/device-lots/{lot_id}/release", payload or {}, headers
        )

    def get_device_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/device-lots/{lot_id}", headers=headers)

    def list_device_lots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/device-lots", headers=headers, params=params)

    # ── Vascular accesses ─────────────────────────────────────────────────────

    def create_vascular_access(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vascular-accesses", payload, headers)

    def set_vascular_access_status(
        self, access_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vascular-accesses/{access_id}/status", payload, headers
        )

    def get_vascular_access(self, access_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vascular-accesses/{access_id}", headers=headers)

    def list_vascular_accesses(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/vascular-accesses", headers=headers, params=params)

    def list_access_surveillance_readings(
        self, access_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/vascular-accesses/{access_id}/surveillance-readings",
            headers=headers,
            params=params,
        )

    # ── Surveillance readings ─────────────────────────────────────────────────

    def create_surveillance_reading(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/surveillance-readings", payload, headers)

    def get_surveillance_reading(self, reading_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/surveillance-readings/{reading_id}", headers=headers
        )

    # ── Referrals ─────────────────────────────────────────────────────────────

    def create_referral(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/referrals", payload, headers)

    def request_referral_info(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/request-info", payload, headers
        )

    def resubmit_referral(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/resubmit", payload, headers
        )

    def triage_referral(
        self, referral_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/triage", payload or {}, headers
        )

    def decline_referral(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/decline", payload, headers
        )

    def update_referral_missed_treatments(
        self, referral_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/referrals/{referral_id}/missed-treatments", payload, headers
        )

    def get_referral(self, referral_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    # ── Procedures: booking and cancellation ──────────────────────────────────

    def create_procedure(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/procedures", payload, headers)

    def cancel_procedure(
        self, procedure_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/cancel", payload or {}, headers
        )

    # ── Device usages and allocations ─────────────────────────────────────────

    def create_device_usage(
        self, procedure_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/device-usages", payload, headers
        )

    def create_device_allocation(
        self, procedure_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/device-allocations", payload, headers
        )

    def get_device_usage(self, usage_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/device-usages/{usage_id}", headers=headers)

    def list_device_usages(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/device-usages", headers=headers, params=params)

    # ── Procedures: room flow ─────────────────────────────────────────────────

    def start_procedure(
        self, procedure_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/start", payload or {}, headers
        )

    def move_procedure_to_recovery(
        self, procedure_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/recovery", payload, headers
        )

    def create_recovery_observation(
        self, procedure_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/recovery-observations", payload, headers
        )

    def discharge_procedure(
        self, procedure_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/discharge", payload or {}, headers
        )

    def abort_procedure(
        self, procedure_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/abort", payload, headers
        )

    # ── Procedures: revenue cycle ─────────────────────────────────────────────

    def create_procedure_code(
        self, procedure_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/codes", payload, headers
        )

    def attest_procedure(
        self, procedure_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/attest", payload, headers
        )

    def bill_procedure(
        self, procedure_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/bill", payload or {}, headers
        )

    def deny_procedure(
        self, procedure_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/deny", payload, headers
        )

    def rebill_procedure(
        self, procedure_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/procedures/{procedure_id}/rebill", payload or {}, headers
        )

    # ── Procedures: reads ─────────────────────────────────────────────────────

    def get_procedure(self, procedure_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/procedures/{procedure_id}", headers=headers)

    def list_procedures(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/procedures", headers=headers, params=params)

    def list_procedure_codes(
        self, procedure_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/procedures/{procedure_id}/codes", headers=headers, params=params
        )

    def list_recovery_observations(
        self, procedure_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/procedures/{procedure_id}/recovery-observations",
            headers=headers,
            params=params,
        )

    def get_reimbursement_preview(self, procedure_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/procedures/{procedure_id}/reimbursement-preview", headers=headers
        )

    # ── Access conversion plans ───────────────────────────────────────────────

    def create_conversion_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/access-conversion-plans", payload, headers)

    def activate_conversion_plan(
        self, plan_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST",
            f"/access-conversion-plans/{plan_id}/activate",
            payload or {},
            headers,
        )

    def create_maturation_check(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/access-conversion-plans/{plan_id}/maturation-checks", payload, headers
        )

    def get_conversion_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/access-conversion-plans/{plan_id}", headers=headers
        )

    def list_conversion_plans(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/access-conversion-plans", headers=headers, params=params
        )

    # ── Infection events ──────────────────────────────────────────────────────

    def create_infection_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/infection-events", payload, headers)

    def get_infection_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/infection-events/{event_id}", headers=headers)

    def list_infection_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/infection-events", headers=headers, params=params)


api_client = ApiClient()
