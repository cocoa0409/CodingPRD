"""One method per declared endpoint of PRD section 4 (51 endpoints).

Two responsibilities live here and nowhere else:

1.  **Instant canonicalisation.**  PRD 2.4 requires every instant in a request
    body to be ISO 8601 with an explicit ``Z``, and PRD 2.3/3.7 declare the
    invoice billing period and the bunching cluster window as *instants*
    bounding a **closed** interval.  :func:`canonicalise_payload` therefore
    expands a bare ``YYYY-MM-DD`` to the first millisecond of that date, or -
    for a field whose name ends in ``_end`` - to the last millisecond
    ``23:59:59.999Z``, and normalises every already-``Z`` instant to exactly
    three fractional digits.  It deliberately does **not** append a missing
    ``Z``, because a Z-less instant is itself a declared schema violation that
    tests need to be able to send.

2.  **Path construction** under the ``/demurrage`` prefix.

Every method returns the raw ``requests.Response`` so that the framework's
``validate_success`` / ``validate_error`` / ``validate_paginated`` remain the
single place the response envelope of PRD 2.2 is unwrapped.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_Z = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z$"
)


def canonicalise_instant(value: str, key: str = "") -> str:
    """Return ``value`` as an ISO 8601 UTC instant with three fractional digits.

    A bare date expands to the first millisecond of that date, except for a
    field whose name ends in ``_end``, which expands to the last millisecond of
    the date so that the closed intervals of PRD 3.6 and 3.7 really do include
    everything that happened on their final date.
    """
    if _DATE_ONLY.match(value):
        if key.endswith("_end"):
            return value + "T23:59:59.999Z"
        return value + "T00:00:00.000Z"
    match = _INSTANT_Z.match(value)
    if match:
        frac = (match.group(2) or "")[:3].ljust(3, "0")
        return "%s.%sZ" % (match.group(1), frac)
    return value


def canonicalise_payload(payload: Any, key: str = "") -> Any:
    """Recursively canonicalise every instant-shaped string in a payload."""
    if isinstance(payload, dict):
        return {k: canonicalise_payload(v, k) for k, v in payload.items()}
    if isinstance(payload, list):
        return [canonicalise_payload(v, key) for v in payload]
    if isinstance(payload, str):
        return canonicalise_instant(payload, key)
    return payload


def canonicalise_response_instant(value: Optional[str]) -> Optional[str]:
    """Canonicalise an instant read back out of a response body.

    Used by ``assertions.assert_instant_eq`` so that a comparison never fails
    purely on sub-second rendering width.
    """
    if value is None:
        return None
    return canonicalise_instant(value)


class ApiClient(GenericApiClient):
    """Domain client for the rail demurrage service."""

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------
    def _path(self, suffix: str) -> str:
        return API_PREFIX + suffix

    def _send(
        self,
        method: str,
        suffix: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
        canonicalise: bool = True,
    ):
        body = canonicalise_payload(payload) if canonicalise else payload
        query = canonicalise_payload(params) if canonicalise else params
        return self._request(method, self._path(suffix), body, headers, query)

    def raw_post(self, suffix: str, payload: Any, headers: Dict[str, str]):
        """POST a body exactly as given, with no instant canonicalisation.

        Needed for the PRD 2.8 band-8 tests that must send an instant without
        its ``Z`` designator.
        """
        return self._send("POST", suffix, payload, headers, canonicalise=False)

    # ------------------------------------------------------------------
    # PRD 3.9 - the test-driving logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers):
        return self._send(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # PRD 3.1 - Customer
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._send("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._send("GET", "/customers/%s" % customer_id, None, headers)

    def set_credit_hold(self, customer_id, payload, headers):
        return self._send(
            "POST", "/customers/%s/credit-hold" % customer_id, payload, headers
        )

    def list_customer_average_agreements(self, customer_id, headers, params=None):
        return self._send(
            "GET",
            "/customers/%s/average-agreements" % customer_id,
            None,
            headers,
            params,
        )

    def list_customer_bunching_claims(self, customer_id, headers, params=None):
        return self._send(
            "GET",
            "/customers/%s/bunching-claims" % customer_id,
            None,
            headers,
            params,
        )

    # ------------------------------------------------------------------
    # PRD 3.1 - TariffRuleSet
    # ------------------------------------------------------------------
    def create_tariff_rule_set(self, payload, headers):
        return self._send("POST", "/tariff-rule-sets", payload, headers)

    def get_tariff_rule_set(self, tariff_id, headers):
        return self._send("GET", "/tariff-rule-sets/%s" % tariff_id, None, headers)

    def publish_tariff_rule_set(self, tariff_id, headers):
        return self._send(
            "POST", "/tariff-rule-sets/%s/publish" % tariff_id, {}, headers
        )

    # ------------------------------------------------------------------
    # PRD 3.1 - Facility
    # ------------------------------------------------------------------
    def create_facility(self, payload, headers):
        return self._send("POST", "/facilities", payload, headers)

    def set_facility_access_mode(self, facility_id, payload, headers):
        return self._send(
            "POST", "/facilities/%s/access-mode" % facility_id, payload, headers
        )

    # ------------------------------------------------------------------
    # PRD 3.1 - RailCar
    # ------------------------------------------------------------------
    def create_rail_car(self, payload, headers):
        return self._send("POST", "/rail-cars", payload, headers)

    def get_rail_car(self, rail_car_id, headers):
        return self._send("GET", "/rail-cars/%s" % rail_car_id, None, headers)

    # ------------------------------------------------------------------
    # PRD 3.2 - 3.5 - PlacementCycle
    # ------------------------------------------------------------------
    def create_placement_cycle(self, payload, headers):
        return self._send("POST", "/placement-cycles", payload, headers)

    def get_placement_cycle(self, cycle_id, headers):
        return self._send("GET", "/placement-cycles/%s" % cycle_id, None, headers)

    def list_placement_cycles(self, headers, params=None):
        return self._send("GET", "/placement-cycles", None, headers, params)

    def constructive_placement(self, cycle_id, payload, headers):
        return self._send(
            "POST",
            "/placement-cycles/%s/constructive-placement" % cycle_id,
            payload,
            headers,
        )

    def notify(self, cycle_id, payload, headers):
        return self._send(
            "POST", "/placement-cycles/%s/notify" % cycle_id, payload, headers
        )

    def list_notifications(self, cycle_id, headers, params=None):
        return self._send(
            "GET",
            "/placement-cycles/%s/notifications" % cycle_id,
            None,
            headers,
            params,
        )

    def acknowledge_notification(self, cycle_id, payload, headers):
        return self._send(
            "POST",
            "/placement-cycles/%s/acknowledge-notification" % cycle_id,
            payload,
            headers,
        )

    def actual_placement(self, cycle_id, payload, headers):
        return self._send(
            "POST",
            "/placement-cycles/%s/actual-placement" % cycle_id,
            payload,
            headers,
        )

    def refuse(self, cycle_id, payload, headers):
        return self._send(
            "POST", "/placement-cycles/%s/refuse" % cycle_id, payload, headers
        )

    def release(self, cycle_id, payload, headers):
        return self._send(
            "POST", "/placement-cycles/%s/release" % cycle_id, payload, headers
        )

    def void_cycle(self, cycle_id, payload, headers):
        return self._send(
            "POST", "/placement-cycles/%s/void" % cycle_id, payload, headers
        )

    # ------------------------------------------------------------------
    # PRD 3.2 - DemurrageCharge (read-only)
    # ------------------------------------------------------------------
    def get_charge(self, charge_id, headers):
        return self._send("GET", "/charges/%s" % charge_id, None, headers)

    def list_charges(self, headers, params=None):
        return self._send("GET", "/charges", None, headers, params)

    # ------------------------------------------------------------------
    # PRD 3.7 - Invoice
    # ------------------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._send("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._send("GET", "/invoices/%s" % invoice_id, None, headers)

    def list_invoices(self, headers, params=None):
        return self._send("GET", "/invoices", None, headers, params)

    def issue_invoice(self, invoice_id, headers):
        return self._send("POST", "/invoices/%s/issue" % invoice_id, {}, headers)

    def close_invoice(self, invoice_id, headers):
        return self._send("POST", "/invoices/%s/close" % invoice_id, {}, headers)

    # ------------------------------------------------------------------
    # PRD 3.7 - AverageAgreement
    # ------------------------------------------------------------------
    def create_average_agreement(self, payload, headers):
        return self._send("POST", "/average-agreements", payload, headers)

    def reconcile_average_agreement(self, agreement_id, headers):
        return self._send(
            "POST", "/average-agreements/%s/reconcile" % agreement_id, {}, headers
        )

    # ------------------------------------------------------------------
    # PRD 3.6 - BunchingClaim
    # ------------------------------------------------------------------
    def create_bunching_claim(self, payload, headers):
        return self._send("POST", "/bunching-claims", payload, headers)

    def analyze_bunching_claim(self, claim_id, headers):
        return self._send(
            "POST", "/bunching-claims/%s/analyze" % claim_id, {}, headers
        )

    # ------------------------------------------------------------------
    # PRD 3.8 - DemurrageDispute
    # ------------------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._send("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._send("GET", "/disputes/%s" % dispute_id, None, headers)

    def list_disputes(self, headers, params=None):
        return self._send("GET", "/disputes", None, headers, params)

    def create_evidence(self, dispute_id, payload, headers):
        return self._send(
            "POST", "/disputes/%s/evidence" % dispute_id, payload, headers
        )

    def list_evidence(self, dispute_id, headers, params=None):
        return self._send(
            "GET", "/disputes/%s/evidence" % dispute_id, None, headers, params
        )

    def submit_dispute(self, dispute_id, headers):
        return self._send("POST", "/disputes/%s/submit" % dispute_id, {}, headers)

    def begin_review(self, dispute_id, headers):
        return self._send(
            "POST", "/disputes/%s/begin-review" % dispute_id, {}, headers
        )

    def request_info(self, dispute_id, payload, headers):
        return self._send(
            "POST", "/disputes/%s/request-info" % dispute_id, payload, headers
        )

    def resubmit_dispute(self, dispute_id, headers):
        return self._send("POST", "/disputes/%s/resubmit" % dispute_id, {}, headers)

    def decide_dispute(self, dispute_id, payload, headers):
        return self._send(
            "POST", "/disputes/%s/decide" % dispute_id, payload, headers
        )

    def appeal_dispute(self, dispute_id, payload, headers):
        return self._send(
            "POST", "/disputes/%s/appeal" % dispute_id, payload, headers
        )

    # ------------------------------------------------------------------
    # PRD 3.9 - RegulatoryComplaint
    # ------------------------------------------------------------------
    def create_regulatory_complaint(self, payload, headers):
        return self._send("POST", "/regulatory-complaints", payload, headers)

    def get_regulatory_complaint(self, complaint_id, headers):
        return self._send(
            "GET", "/regulatory-complaints/%s" % complaint_id, None, headers
        )

    def list_regulatory_complaints(self, headers, params=None):
        return self._send("GET", "/regulatory-complaints", None, headers, params)

    def answer_regulatory_complaint(self, complaint_id, payload, headers):
        return self._send(
            "POST",
            "/regulatory-complaints/%s/answer" % complaint_id,
            payload,
            headers,
        )

    def decide_regulatory_complaint(self, complaint_id, payload, headers):
        return self._send(
            "POST",
            "/regulatory-complaints/%s/decide" % complaint_id,
            payload,
            headers,
        )
