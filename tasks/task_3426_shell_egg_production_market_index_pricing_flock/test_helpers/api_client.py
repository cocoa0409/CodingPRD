"""API client: one method per endpoint the PRD defines.

Also carries :func:`canonical_instant`, which normalises ISO 8601 UTC instants
to a fixed three-fractional-digit width (PRD §2.5 stamps timestamps with three
fractional digits) so a literal like ``2026-09-01T00:00:00Z`` and the stamped
``2026-09-01T00:00:00.000Z`` compare equal.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/api"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Canonicalise an ISO 8601 UTC instant to exactly three fractional digits.

    ``None`` passes through untouched so null timestamp fields stay null.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[: -len("+00:00")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = "".join(ch for ch in frac if ch.isdigit())
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """True when two instants denote the same moment at millisecond width."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    # ----- logical clock (PRD §2.4) ------------------------------------------

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ----- complexes (PRD §3.1) ----------------------------------------------

    def create_complex(self, payload, headers):
        return self._request("POST", f"{BASE}/complexes", payload, headers)

    def get_complex(self, complex_id, headers):
        return self._request("GET", f"{BASE}/complexes/{complex_id}", headers=headers)

    def get_capacity_projection(self, complex_id, week_offset, headers):
        return self._request(
            "GET",
            f"{BASE}/complexes/{complex_id}/capacity-projection",
            {"week_offset": week_offset},
            headers,
        )

    def run_ops(self, complex_id, headers):
        return self._request(
            "POST", f"{BASE}/complexes/{complex_id}/run-ops", {}, headers
        )

    # ----- houses (PRD §3.1) ---------------------------------------------------

    def create_house(self, complex_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/complexes/{complex_id}/houses", payload, headers
        )

    def list_houses(self, complex_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/complexes/{complex_id}/houses", headers=headers,
            params=params,
        )

    def get_house(self, house_id, headers):
        return self._request("GET", f"{BASE}/houses/{house_id}", headers=headers)

    # ----- certifications (PRD §3.1) -------------------------------------------

    def create_certification(self, house_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/houses/{house_id}/certifications", payload, headers
        )

    def list_certifications(self, house_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/houses/{house_id}/certifications", headers=headers,
            params=params,
        )

    def record_certification_result(self, certification_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/certifications/{certification_id}/record-result",
            payload,
            headers,
        )

    # ----- flocks (PRD §3.2) -----------------------------------------------------

    def create_flock(self, house_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/houses/{house_id}/flocks", payload, headers
        )

    def list_flocks(self, house_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/houses/{house_id}/flocks", headers=headers,
            params=params,
        )

    def get_flock(self, flock_id, headers):
        return self._request("GET", f"{BASE}/flocks/{flock_id}", headers=headers)

    def place_flock(self, flock_id, headers):
        return self._request(
            "POST", f"{BASE}/flocks/{flock_id}/place", {}, headers
        )

    def molt_flock(self, flock_id, headers):
        return self._request("POST", f"{BASE}/flocks/{flock_id}/molt", {}, headers)

    # ----- disease events and depopulation (PRD §3.3) -----------------------------

    def create_disease_event(self, complex_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/complexes/{complex_id}/disease-events", payload,
            headers,
        )

    def list_disease_events(self, complex_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/complexes/{complex_id}/disease-events",
            headers=headers, params=params,
        )

    def get_disease_event(self, event_id, headers):
        return self._request(
            "GET", f"{BASE}/disease-events/{event_id}", headers=headers
        )

    def confirm_disease_event(self, event_id, headers):
        return self._request(
            "POST", f"{BASE}/disease-events/{event_id}/confirm", {}, headers
        )

    def dismiss_disease_event(self, event_id, headers):
        return self._request(
            "POST", f"{BASE}/disease-events/{event_id}/dismiss", {}, headers
        )

    def create_depopulation_order(self, event_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/disease-events/{event_id}/depopulation-orders",
            payload, headers,
        )

    def list_depopulation_orders(self, event_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/disease-events/{event_id}/depopulation-orders",
            headers=headers, params=params,
        )

    def complete_depopulation_order(self, order_id, headers):
        return self._request(
            "POST", f"{BASE}/depopulation-orders/{order_id}/complete", {}, headers
        )

    def list_house_depopulation_orders(self, house_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/houses/{house_id}/depopulation-orders",
            headers=headers, params=params,
        )

    # ----- market quotations (PRD §3.4) -------------------------------------------

    def create_market_quotation(self, payload, headers):
        return self._request("POST", f"{BASE}/market-quotations", payload, headers)

    def list_market_quotations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/market-quotations", headers=headers, params=params
        )

    # ----- customers and commitments (PRD §3.5) ------------------------------------

    def create_customer(self, payload, headers):
        return self._request("POST", f"{BASE}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{BASE}/customers/{customer_id}", headers=headers)

    def create_commitment(self, customer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/customers/{customer_id}/commitments", payload, headers
        )

    def list_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/commitments", headers=headers, params=params
        )

    def get_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"{BASE}/commitments/{commitment_id}", headers=headers
        )

    def activate_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"{BASE}/commitments/{commitment_id}/activate", {}, headers
        )

    # ----- orders (PRD §3.6) ---------------------------------------------------------

    def create_order(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/commitments/{commitment_id}/orders", payload, headers
        )

    def list_commitment_orders(self, commitment_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/commitments/{commitment_id}/orders", headers=headers,
            params=params,
        )

    def get_order(self, order_id, headers):
        return self._request("GET", f"{BASE}/orders/{order_id}", headers=headers)

    def allocate_order(self, order_id, headers):
        return self._request(
            "POST", f"{BASE}/orders/{order_id}/allocate", {}, headers
        )

    def ship_order(self, order_id, headers):
        return self._request("POST", f"{BASE}/orders/{order_id}/ship", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"{BASE}/orders/{order_id}/cancel", {}, headers)

    def list_complex_orders(self, complex_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/complexes/{complex_id}/orders", headers=headers,
            params=params,
        )

    def list_order_settlements(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/orders/{order_id}/settlements", headers=headers,
            params=params,
        )

    # ----- settlements (PRD §3.7) ------------------------------------------------------

    def finalize_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/finalize", {}, headers
        )

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/dispute", payload, headers
        )

    def resolve_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/resolve", {}, headers
        )

    def mark_settlement_paid(self, settlement_id, headers):
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/mark-paid", {}, headers
        )

    # ----- feed contracts and batches (PRD §3.8) ----------------------------------------

    def create_feed_contract(self, payload, headers):
        return self._request("POST", f"{BASE}/feed-contracts", payload, headers)

    def list_feed_contracts(self, complex_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/complexes/{complex_id}/feed-contracts",
            headers=headers, params=params,
        )

    def hedge_feed_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/feed-contracts/{contract_id}/hedge", payload, headers
        )

    def receive_feed_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/feed-contracts/{contract_id}/receive", payload, headers
        )

    def create_feed_batch(self, complex_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/complexes/{complex_id}/feed-batches", payload, headers
        )

    def list_feed_batches(self, complex_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/complexes/{complex_id}/feed-batches", headers=headers,
            params=params,
        )

    # ----- packing runs (PRD §3.9) ---------------------------------------------------------

    def create_packing_run(self, complex_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/complexes/{complex_id}/packing-runs", payload, headers
        )

    def list_packing_runs(self, complex_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/complexes/{complex_id}/packing-runs", headers=headers,
            params=params,
        )

    def verify_packing_run(self, run_id, headers):
        return self._request(
            "POST", f"{BASE}/packing-runs/{run_id}/verify", {}, headers
        )

    # ----- capital projects (PRD §3.5) --------------------------------------------------------

    def create_capital_project(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/commitments/{commitment_id}/capital-projects",
            payload, headers,
        )

    def list_capital_projects(self, commitment_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/commitments/{commitment_id}/capital-projects",
            headers=headers, params=params,
        )

    def list_house_capital_projects(self, house_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/houses/{house_id}/capital-projects", headers=headers,
            params=params,
        )

    def approve_capital_project(self, project_id, headers):
        return self._request(
            "POST", f"{BASE}/capital-projects/{project_id}/approve", {}, headers
        )

    def commission_capital_project(self, project_id, headers):
        return self._request(
            "POST", f"{BASE}/capital-projects/{project_id}/commission", {}, headers
        )


api_client = ApiClient()
