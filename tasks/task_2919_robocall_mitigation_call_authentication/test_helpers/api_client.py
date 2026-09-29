"""HTTP client for the Robocall Mitigation & Call Authentication API.

One method per routed operation.  Bodies are passed through untouched so that
tests can send deliberately malformed payloads; query filters are passed as
request parameters.
"""

import re
from typing import Any, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import (
    BLOCKING_DISPUTES,
    BLOCKING_EVENTS,
    CALL_ATTESTATIONS,
    CERTIFICATES,
    CLOCK_PATH,
    CUSTOMERS,
    EFFECTIVENESS_REPORTS,
    ENFORCEMENT_ACTIONS,
    ILLEGAL_TRAFFIC_NOTICES,
    MITIGATION_PLANS,
    NUMBER_ASSIGNMENTS,
    PROVIDERS,
    SWEEPS,
    TRACEBACK_REQUESTS,
    TRAFFIC_OBSERVATIONS,
)
from .types import Headers, Payload

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def normalize_instant(value: Any) -> Any:
    """Canonicalise an ISO-8601 instant so comparisons ignore fraction width.

    ``2026-08-01T00:00:00Z``, ``2026-08-01T00:00:00.000Z`` and
    ``2026-08-01T00:00:00.000000+00:00`` all normalise to the same string.
    Anything that is not an instant is returned unchanged.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    seconds, fraction, offset = match.groups()
    if fraction:
        digits = fraction[1:].rstrip("0")
    else:
        digits = ""
    if offset in ("Z", "+00:00", "-00:00"):
        suffix = "Z"
    else:
        suffix = offset
    if digits:
        return f"{seconds}.{digits}{suffix}"
    return f"{seconds}{suffix}"


def instants_equal(left: Any, right: Any) -> bool:
    """Compare two instants tolerantly of sub-second digit width."""
    return normalize_instant(left) == normalize_instant(right)


def _clean(params: Optional[dict]) -> Optional[dict]:
    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None}


class RmdApiClient(GenericApiClient):
    """Typed wrapper over every routed operation in the contract."""

    # --- logical clock -----------------------------------------------------

    def set_clock(self, current_utc: str, headers: Headers):
        return self.post(CLOCK_PATH, {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload: Payload, headers: Headers):
        return self.post(CLOCK_PATH, payload, headers)

    # --- compliance sweeps -------------------------------------------------

    def run_sweep(self, provider_id: str, headers: Headers):
        return self.post(SWEEPS, {"provider_id": provider_id}, headers)

    def run_sweep_raw(self, payload: Payload, headers: Headers):
        return self.post(SWEEPS, payload, headers)

    # --- providers ---------------------------------------------------------

    def create_provider(self, payload: Payload, headers: Headers):
        return self.post(PROVIDERS, payload, headers)

    def get_provider(self, provider_id: str, headers: Headers):
        return self.get(f"{PROVIDERS}/{provider_id}", headers)

    def list_providers(self, headers: Headers, **filters):
        return self.get(PROVIDERS, headers, _clean(filters))

    # --- certificates ------------------------------------------------------

    def create_certificate(self, payload: Payload, headers: Headers):
        return self.post(CERTIFICATES, payload, headers)

    def issue_certificate(
        self, certificate_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(f"{CERTIFICATES}/{certificate_id}/issue", payload or {}, headers)

    def activate_certificate(
        self, certificate_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            f"{CERTIFICATES}/{certificate_id}/activate", payload or {}, headers
        )

    def renew_certificate(self, certificate_id: str, payload: Payload, headers: Headers):
        return self.post(f"{CERTIFICATES}/{certificate_id}/renew", payload, headers)

    def revoke_certificate(self, certificate_id: str, payload: Payload, headers: Headers):
        return self.post(f"{CERTIFICATES}/{certificate_id}/revoke", payload, headers)

    def get_certificate(self, certificate_id: str, headers: Headers):
        return self.get(f"{CERTIFICATES}/{certificate_id}", headers)

    def list_certificates(self, headers: Headers, **filters):
        return self.get(CERTIFICATES, headers, _clean(filters))

    # --- mitigation plans --------------------------------------------------

    def create_mitigation_plan(self, payload: Payload, headers: Headers):
        return self.post(MITIGATION_PLANS, payload, headers)

    def submit_mitigation_plan(
        self, plan_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(f"{MITIGATION_PLANS}/{plan_id}/submit", payload or {}, headers)

    def decide_mitigation_plan(self, plan_id: str, payload: Payload, headers: Headers):
        return self.post(f"{MITIGATION_PLANS}/{plan_id}/decision", payload, headers)

    def withdraw_mitigation_plan(
        self, plan_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(f"{MITIGATION_PLANS}/{plan_id}/withdraw", payload or {}, headers)

    def get_mitigation_plan(self, plan_id: str, headers: Headers):
        return self.get(f"{MITIGATION_PLANS}/{plan_id}", headers)

    def list_mitigation_plans(self, headers: Headers, **filters):
        return self.get(MITIGATION_PLANS, headers, _clean(filters))

    # --- customers ---------------------------------------------------------

    def create_customer(self, payload: Payload, headers: Headers):
        return self.post(CUSTOMERS, payload, headers)

    def kyc_submit(
        self, customer_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(f"{CUSTOMERS}/{customer_id}/kyc-submit", payload or {}, headers)

    def kyc_decision(self, customer_id: str, payload: Payload, headers: Headers):
        return self.post(f"{CUSTOMERS}/{customer_id}/kyc-decision", payload, headers)

    def origination_action(self, customer_id: str, payload: Payload, headers: Headers):
        return self.post(
            f"{CUSTOMERS}/{customer_id}/origination-actions", payload, headers
        )

    def get_customer(self, customer_id: str, headers: Headers):
        return self.get(f"{CUSTOMERS}/{customer_id}", headers)

    def list_customers(self, headers: Headers, **filters):
        return self.get(CUSTOMERS, headers, _clean(filters))

    # --- number assignments ------------------------------------------------

    def create_number_assignment(self, payload: Payload, headers: Headers):
        return self.post(NUMBER_ASSIGNMENTS, payload, headers)

    def revoke_number_assignment(
        self, assignment_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            f"{NUMBER_ASSIGNMENTS}/{assignment_id}/revoke", payload or {}, headers
        )

    def get_number_assignment(self, assignment_id: str, headers: Headers):
        return self.get(f"{NUMBER_ASSIGNMENTS}/{assignment_id}", headers)

    def list_number_assignments(self, headers: Headers, **filters):
        return self.get(NUMBER_ASSIGNMENTS, headers, _clean(filters))

    # --- call attestations -------------------------------------------------

    def create_call_attestation(self, payload: Payload, headers: Headers):
        return self.post(CALL_ATTESTATIONS, payload, headers)

    def get_call_attestation(self, attestation_id: str, headers: Headers):
        return self.get(f"{CALL_ATTESTATIONS}/{attestation_id}", headers)

    def list_call_attestations(self, headers: Headers, **filters):
        return self.get(CALL_ATTESTATIONS, headers, _clean(filters))

    # --- traffic observations ----------------------------------------------

    def create_traffic_observation(self, payload: Payload, headers: Headers):
        return self.post(TRAFFIC_OBSERVATIONS, payload, headers)

    def get_traffic_observation(self, observation_id: str, headers: Headers):
        return self.get(f"{TRAFFIC_OBSERVATIONS}/{observation_id}", headers)

    def list_traffic_observations(self, headers: Headers, **filters):
        return self.get(TRAFFIC_OBSERVATIONS, headers, _clean(filters))

    # --- traceback requests ------------------------------------------------

    def create_traceback_request(self, payload: Payload, headers: Headers):
        return self.post(TRACEBACK_REQUESTS, payload, headers)

    def respond_traceback_request(
        self, traceback_id: str, payload: Payload, headers: Headers
    ):
        return self.post(f"{TRACEBACK_REQUESTS}/{traceback_id}/respond", payload, headers)

    def get_traceback_request(self, traceback_id: str, headers: Headers):
        return self.get(f"{TRACEBACK_REQUESTS}/{traceback_id}", headers)

    def list_traceback_requests(self, headers: Headers, **filters):
        return self.get(TRACEBACK_REQUESTS, headers, _clean(filters))

    # --- illegal traffic notices -------------------------------------------

    def create_illegal_traffic_notice(self, payload: Payload, headers: Headers):
        return self.post(ILLEGAL_TRAFFIC_NOTICES, payload, headers)

    def investigate_notice(self, notice_id: str, payload: Payload, headers: Headers):
        return self.post(
            f"{ILLEGAL_TRAFFIC_NOTICES}/{notice_id}/investigate", payload, headers
        )

    def mitigate_notice(self, notice_id: str, payload: Payload, headers: Headers):
        return self.post(
            f"{ILLEGAL_TRAFFIC_NOTICES}/{notice_id}/mitigate", payload, headers
        )

    def get_illegal_traffic_notice(self, notice_id: str, headers: Headers):
        return self.get(f"{ILLEGAL_TRAFFIC_NOTICES}/{notice_id}", headers)

    def list_illegal_traffic_notices(self, headers: Headers, **filters):
        return self.get(ILLEGAL_TRAFFIC_NOTICES, headers, _clean(filters))

    # --- blocking events ---------------------------------------------------

    def create_blocking_event(self, payload: Payload, headers: Headers):
        return self.post(BLOCKING_EVENTS, payload, headers)

    def get_blocking_event(self, event_id: str, headers: Headers):
        return self.get(f"{BLOCKING_EVENTS}/{event_id}", headers)

    def list_blocking_events(self, headers: Headers, **filters):
        return self.get(BLOCKING_EVENTS, headers, _clean(filters))

    # --- blocking disputes -------------------------------------------------

    def create_blocking_dispute(self, payload: Payload, headers: Headers):
        return self.post(BLOCKING_DISPUTES, payload, headers)

    def review_blocking_dispute(
        self, dispute_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(f"{BLOCKING_DISPUTES}/{dispute_id}/review", payload or {}, headers)

    def resolve_blocking_dispute(self, dispute_id: str, payload: Payload, headers: Headers):
        return self.post(f"{BLOCKING_DISPUTES}/{dispute_id}/resolve", payload, headers)

    def withdraw_blocking_dispute(
        self, dispute_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            f"{BLOCKING_DISPUTES}/{dispute_id}/withdraw", payload or {}, headers
        )

    def get_blocking_dispute(self, dispute_id: str, headers: Headers):
        return self.get(f"{BLOCKING_DISPUTES}/{dispute_id}", headers)

    def list_blocking_disputes(self, headers: Headers, **filters):
        return self.get(BLOCKING_DISPUTES, headers, _clean(filters))

    # --- enforcement actions -----------------------------------------------

    def create_enforcement_action(self, payload: Payload, headers: Headers):
        return self.post(ENFORCEMENT_ACTIONS, payload, headers)

    def contest_enforcement_action(
        self, action_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            f"{ENFORCEMENT_ACTIONS}/{action_id}/contest", payload or {}, headers
        )

    def adjudicate_enforcement_action(
        self, action_id: str, payload: Payload, headers: Headers
    ):
        return self.post(f"{ENFORCEMENT_ACTIONS}/{action_id}/adjudicate", payload, headers)

    def pay_enforcement_action(self, action_id: str, payload: Payload, headers: Headers):
        return self.post(f"{ENFORCEMENT_ACTIONS}/{action_id}/pay", payload, headers)

    def get_enforcement_action(self, action_id: str, headers: Headers):
        return self.get(f"{ENFORCEMENT_ACTIONS}/{action_id}", headers)

    def list_enforcement_actions(self, headers: Headers, **filters):
        return self.get(ENFORCEMENT_ACTIONS, headers, _clean(filters))

    # --- effectiveness reports ---------------------------------------------

    def create_effectiveness_report(self, payload: Payload, headers: Headers):
        return self.post(EFFECTIVENESS_REPORTS, payload, headers)

    def certify_effectiveness_report(
        self, report_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            f"{EFFECTIVENESS_REPORTS}/{report_id}/certify", payload or {}, headers
        )

    def file_effectiveness_report(
        self, report_id: str, headers: Headers, payload: Optional[Payload] = None
    ):
        return self.post(
            f"{EFFECTIVENESS_REPORTS}/{report_id}/file", payload or {}, headers
        )

    def get_effectiveness_report(self, report_id: str, headers: Headers):
        return self.get(f"{EFFECTIVENESS_REPORTS}/{report_id}", headers)

    def list_effectiveness_reports(self, headers: Headers, **filters):
        return self.get(EFFECTIVENESS_REPORTS, headers, _clean(filters))
