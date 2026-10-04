"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the `/multistate` path prefix, with exactly
one exception: the logical-clock endpoint `POST /_clock/set_current_utc`
lives outside that prefix (PRD §2.4) and is therefore NOT prefixed here.

Action endpoints that take no request body send an empty JSON object so the
server always receives a parseable JSON body with the role headers.
"""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/multistate"

# Payload-free action endpoints still get an explicit empty JSON body.
_EMPTY = {}


class ApiClient(GenericApiClient):
    # ── Logical clock (PRD §2.4 — lives OUTSIDE the /multistate prefix) ───
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── State offices ─────────────────────────────────────────────────────
    def create_state_office(self, payload, headers):
        return self._request("POST", f"{BASE}/state-offices", payload, headers)

    def get_state_office(self, office_id, headers):
        return self._request("GET", f"{BASE}/state-offices/{office_id}", headers=headers)

    def patch_state_office(self, office_id, payload, headers):
        return self._request("PATCH", f"{BASE}/state-offices/{office_id}", payload, headers)

    def list_state_office_participations(self, office_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/state-offices/{office_id}/participations",
            headers=headers, params=params,
        )

    def list_state_office_allocation_lines(self, office_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/state-offices/{office_id}/allocation-lines",
            headers=headers, params=params,
        )

    # ── Investigations ────────────────────────────────────────────────────
    def create_investigation(self, payload, headers):
        return self._request("POST", f"{BASE}/investigations", payload, headers)

    def get_investigation(self, investigation_id, headers):
        return self._request(
            "GET", f"{BASE}/investigations/{investigation_id}", headers=headers,
        )

    def advance_investigation(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/investigations/{investigation_id}/advance",
            payload, headers,
        )

    def list_investigation_participations(self, investigation_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/investigations/{investigation_id}/participations",
            headers=headers, params=params,
        )

    def list_investigation_responses(self, investigation_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/investigations/{investigation_id}/responses",
            headers=headers, params=params,
        )

    def list_investigation_settlements(self, investigation_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/investigations/{investigation_id}/settlements",
            headers=headers, params=params,
        )

    # ── Participations ────────────────────────────────────────────────────
    def create_participation(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/investigations/{investigation_id}/participations",
            payload, headers,
        )

    def get_participation(self, participation_id, headers):
        return self._request(
            "GET", f"{BASE}/participations/{participation_id}", headers=headers,
        )

    def execute_cia(self, participation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/participations/{participation_id}/execute-cia",
            payload, headers,
        )

    def designate_lead(self, participation_id, headers):
        return self._request(
            "POST", f"{BASE}/participations/{participation_id}/designate-lead",
            _EMPTY, headers,
        )

    def withdraw_participation(self, participation_id, headers):
        return self._request(
            "POST", f"{BASE}/participations/{participation_id}/withdraw",
            _EMPTY, headers,
        )

    # ── Demands ───────────────────────────────────────────────────────────
    def create_demand(self, participation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/participations/{participation_id}/demands",
            payload, headers,
        )

    def list_participation_demands(self, participation_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/participations/{participation_id}/demands",
            headers=headers, params=params,
        )

    # ── Consolidated responses ────────────────────────────────────────────
    def create_response(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/investigations/{investigation_id}/responses",
            payload, headers,
        )

    def accept_response(self, response_id, headers):
        return self._request(
            "POST", f"{BASE}/responses/{response_id}/accept", _EMPTY, headers,
        )

    def fulfill_response(self, response_id, headers):
        return self._request(
            "POST", f"{BASE}/responses/{response_id}/fulfill", _EMPTY, headers,
        )

    # ── Settlements ───────────────────────────────────────────────────────
    def create_settlement(self, investigation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/investigations/{investigation_id}/settlements",
            payload, headers,
        )

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"{BASE}/settlements/{settlement_id}", headers=headers,
        )

    def counter_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/counter", payload, headers,
        )

    def revise_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/revise", payload, headers,
        )

    def agree_terms(self, settlement_id, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/agree-terms", _EMPTY, headers,
        )

    def open_sign_on(self, settlement_id, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/open-sign-on", _EMPTY, headers,
        )

    def record_sign_on(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/sign-ons", payload, headers,
        )

    def execute_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/execute", _EMPTY, headers,
        )

    def deposit_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/deposit", payload, headers,
        )

    def restitution_compute(self, settlement_id, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/restitution-compute",
            _EMPTY, headers,
        )

    # ── Allocation lines ──────────────────────────────────────────────────
    def get_allocation_line(self, line_id, headers):
        return self._request(
            "GET", f"{BASE}/allocation-lines/{line_id}", headers=headers,
        )

    def list_settlement_allocation_lines(self, settlement_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/settlements/{settlement_id}/allocation-lines",
            headers=headers, params=params,
        )

    # ── Disbursements ─────────────────────────────────────────────────────
    def create_disbursement(self, line_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/allocation-lines/{line_id}/disbursements",
            payload, headers,
        )

    def list_allocation_line_disbursements(self, line_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/allocation-lines/{line_id}/disbursements",
            headers=headers, params=params,
        )

    def certify_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"{BASE}/disbursements/{disbursement_id}/certify", _EMPTY, headers,
        )

    def release_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"{BASE}/disbursements/{disbursement_id}/release", _EMPTY, headers,
        )

    # ── Claimants ─────────────────────────────────────────────────────────
    def create_claimant(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/claimants", payload, headers,
        )

    def list_settlement_claimants(self, settlement_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/settlements/{settlement_id}/claimants",
            headers=headers, params=params,
        )

    def validate_claimant(self, claimant_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/claimants/{claimant_id}/validate", payload, headers,
        )

    # ── Monitoring periods ────────────────────────────────────────────────
    def create_monitoring_period(self, settlement_id, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/monitoring-periods",
            _EMPTY, headers,
        )

    def list_settlement_monitoring_periods(self, settlement_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/settlements/{settlement_id}/monitoring-periods",
            headers=headers, params=params,
        )

    def file_finding(self, period_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/monitoring-periods/{period_id}/findings",
            payload, headers,
        )


api_client = ApiClient()
