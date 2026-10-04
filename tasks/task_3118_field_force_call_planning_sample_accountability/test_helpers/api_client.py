"""One transport method per endpoint in PRD section 4.

Every method returns the raw HTTP response so the test may assert on the
status code and on the envelope, rather than on a pre-digested value.  The
``/field-force`` prefix and the shape of each path live here and nowhere
else.
"""

import os

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/field-force"


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    def __init__(self, base_url=None):
        if base_url is None:
            base_url = os.environ.get("API_BASE_URL") or os.environ.get(
                "_PRD_BENCH_API_URL"
            )
        super().__init__(base_url=base_url)

    # ─── Logical clock ──────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601},
            headers=headers,
        )

    # ─── Regions ────────────────────────────────────────────────────────

    def create_region(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/regions", payload, headers)

    def list_regions(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/regions", headers=headers, params=params
        )

    def get_region(self, region_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/regions/{region_id}", headers=headers
        )

    # ─── Territories ────────────────────────────────────────────────────

    def create_territory(self, region_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/regions/{region_id}/territories",
            payload,
            headers,
        )

    def list_territories(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/territories", headers=headers, params=params
        )

    def list_region_territories(self, region_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/regions/{region_id}/territory-list",
            headers=headers,
            params=params,
        )

    def get_territory(self, territory_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/territories/{territory_id}", headers=headers
        )

    # ─── Representatives ────────────────────────────────────────────────

    def create_representative(self, territory_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/territories/{territory_id}/representatives",
            payload,
            headers,
        )

    def list_territory_representatives(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/territories/{territory_id}/representatives",
            headers=headers,
            params=params,
        )

    def list_representatives(self, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/representatives",
            headers=headers,
            params=params,
        )

    def get_representative(self, rep_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/representatives/{rep_id}", headers=headers
        )

    # ─── Prescribers ────────────────────────────────────────────────────

    def create_prescriber(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/prescribers", payload, headers
        )

    def list_prescribers(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/prescribers", headers=headers, params=params
        )

    def get_prescriber(self, prescriber_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/prescribers/{prescriber_id}", headers=headers
        )

    def verify_prescriber_eligibility(self, prescriber_id, outcome, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/prescribers/{prescriber_id}/verify-eligibility",
            payload={"outcome": outcome},
            headers=headers,
        )

    # ─── Products ───────────────────────────────────────────────────────

    def create_product(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/products", headers=headers, params=params
        )

    def get_product(self, product_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/products/{product_id}", headers=headers
        )

    # ─── Sample lots ────────────────────────────────────────────────────

    def create_sample_lot(self, product_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/products/{product_id}/sample-lots",
            payload,
            headers,
        )

    def list_sample_lots(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/sample-lots", headers=headers, params=params
        )

    def list_product_sample_lots(self, product_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/products/{product_id}/sample-lot-list",
            headers=headers,
            params=params,
        )

    def get_sample_lot(self, lot_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/sample-lots/{lot_id}", headers=headers
        )

    # ─── Rep lot balances / issuance ────────────────────────────────────

    def issue_lot_balance(self, rep_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/representatives/{rep_id}/lot-balances",
            payload,
            headers,
        )

    def list_rep_lot_balances(self, rep_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/representatives/{rep_id}/lot-balances",
            headers=headers,
            params=params,
        )

    def list_lot_balances(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/lot-balances", headers=headers, params=params
        )

    def get_lot_balance(self, balance_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/lot-balances/{balance_id}", headers=headers
        )

    # ─── Target list ────────────────────────────────────────────────────

    def create_target_list_entry(self, territory_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/territories/{territory_id}/target-list-entries",
            payload,
            headers,
        )

    def list_territory_target_entries(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/territories/{territory_id}/target-list-entries",
            headers=headers,
            params=params,
        )

    def list_target_list_entries(self, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/target-list-entries",
            headers=headers,
            params=params,
        )

    def get_target_list_entry(self, entry_id, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/target-list-entries/{entry_id}",
            headers=headers,
        )

    # ─── Call plans ─────────────────────────────────────────────────────

    def create_call_plan(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/call-plans", payload, headers
        )

    def list_call_plans(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/call-plans", headers=headers, params=params
        )

    def get_call_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/call-plans/{plan_id}", headers=headers
        )

    def publish_call_plan(self, plan_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/call-plans/{plan_id}/publish",
            payload={},
            headers=headers,
        )

    # ─── Call visits ────────────────────────────────────────────────────

    def create_call_visit(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/call-visits", payload, headers
        )

    def list_call_visits(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/call-visits", headers=headers, params=params
        )

    def get_call_visit(self, visit_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/call-visits/{visit_id}", headers=headers
        )

    def complete_call_visit(self, visit_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/call-visits/{visit_id}/complete",
            payload={},
            headers=headers,
        )

    def cancel_call_visit(self, visit_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/call-visits/{visit_id}/cancel",
            payload={},
            headers=headers,
        )

    def mark_visit_no_show(self, visit_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/call-visits/{visit_id}/mark-no-show",
            payload={},
            headers=headers,
        )

    def list_visit_disbursements(self, visit_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/call-visits/{visit_id}/sample-disbursements",
            headers=headers,
            params=params,
        )

    # ─── Sample disbursements ───────────────────────────────────────────

    def create_sample_disbursement(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/sample-disbursements", payload, headers
        )

    def list_sample_disbursements(self, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/sample-disbursements",
            headers=headers,
            params=params,
        )

    def get_sample_disbursement(self, disbursement_id, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/sample-disbursements/{disbursement_id}",
            headers=headers,
        )

    def capture_signature(self, disbursement_id, signature_payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sample-disbursements/{disbursement_id}/capture-signature",
            payload={"signature_payload": signature_payload},
            headers=headers,
        )

    def reject_signature(self, disbursement_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sample-disbursements/{disbursement_id}/reject-signature",
            payload={},
            headers=headers,
        )

    # ─── Count lines ────────────────────────────────────────────────────

    def list_count_lines(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/count-lines", headers=headers, params=params
        )

    def get_count_line(self, line_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/count-lines/{line_id}", headers=headers
        )

    # ─── Transfers ──────────────────────────────────────────────────────

    def create_sample_transfer(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/sample-transfers", payload, headers
        )

    def list_sample_transfers(self, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/sample-transfers",
            headers=headers,
            params=params,
        )

    def get_sample_transfer(self, transfer_id, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/sample-transfers/{transfer_id}",
            headers=headers,
        )

    def accept_transfer(self, transfer_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sample-transfers/{transfer_id}/accept",
            payload={},
            headers=headers,
        )

    def reject_transfer(self, transfer_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sample-transfers/{transfer_id}/reject",
            payload={},
            headers=headers,
        )

    def cancel_transfer(self, transfer_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sample-transfers/{transfer_id}/cancel",
            payload={},
            headers=headers,
        )

    def reverse_transfer(self, transfer_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sample-transfers/{transfer_id}/reverse",
            payload={},
            headers=headers,
        )

    # ─── Inventory count sessions ───────────────────────────────────────

    def create_count_session(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/inventory-count-sessions", payload, headers
        )

    def list_count_sessions(self, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/inventory-count-sessions",
            headers=headers,
            params=params,
        )

    def get_count_session(self, session_id, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/inventory-count-sessions/{session_id}",
            headers=headers,
        )

    def list_session_count_lines(self, session_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/inventory-count-sessions/{session_id}/count-lines",
            headers=headers,
            params=params,
        )

    def submit_count(self, session_id, lines, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/inventory-count-sessions/{session_id}/submit-count",
            payload={"lines": lines},
            headers=headers,
        )

    def reconcile_count_session(self, session_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/inventory-count-sessions/{session_id}/reconcile",
            payload={},
            headers=headers,
        )

    def reopen_count_session(self, session_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/inventory-count-sessions/{session_id}/reopen",
            payload={},
            headers=headers,
        )

    def close_count_session(self, session_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/inventory-count-sessions/{session_id}/close",
            payload={},
            headers=headers,
        )

    def void_count_session(self, session_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/inventory-count-sessions/{session_id}/void",
            payload={},
            headers=headers,
        )

    # ─── Temperature excursions ─────────────────────────────────────────

    def create_temperature_excursion(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/temperature-excursions", payload, headers
        )

    def list_temperature_excursions(self, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/temperature-excursions",
            headers=headers,
            params=params,
        )

    def get_temperature_excursion(self, excursion_id, headers):
        return self._request(
            "GET",
            f"{API_PREFIX}/temperature-excursions/{excursion_id}",
            headers=headers,
        )

    def assess_temperature_excursion(self, excursion_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/temperature-excursions/{excursion_id}/assess",
            payload={},
            headers=headers,
        )

    def resolve_temperature_excursion(self, excursion_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/temperature-excursions/{excursion_id}/resolve",
            payload={},
            headers=headers,
        )

    # ─── Sample returns ─────────────────────────────────────────────────

    def create_sample_return(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/sample-returns", payload, headers
        )

    def list_sample_returns(self, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/sample-returns",
            headers=headers,
            params=params,
        )

    def get_sample_return(self, return_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/sample-returns/{return_id}", headers=headers
        )

    def submit_sample_return(self, return_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sample-returns/{return_id}/submit",
            payload={},
            headers=headers,
        )

    def confirm_destruction(self, return_id, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/sample-returns/{return_id}/confirm-destruction",
            payload={},
            headers=headers,
        )


api_client = ApiClient()
