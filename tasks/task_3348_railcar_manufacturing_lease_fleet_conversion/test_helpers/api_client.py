"""API client: one method per endpoint, mounted under the ``/api/v1`` prefix.

Every method delegates to the inherited ``_request`` and returns the raw
``requests.Response`` so callers can assert on status codes and envelopes.
The server lifecycle is owned by the test runner; this client only speaks HTTP
to whatever ``API_BASE_URL`` names.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/api/v1"


class ApiClient(GenericApiClient):
    """Railcar manufacturing and lease fleet conversion API client."""

    # ─── Production catalogue: car types ──────────────

    def create_car_type(self, payload, headers):
        """Register a car type in the production catalogue."""
        return self._request("POST", f"{API_PREFIX}/car-types", payload, headers)

    def get_car_type(self, car_type_id, headers):
        """Read one car type."""
        return self._request(
            "GET", f"{API_PREFIX}/car-types/{car_type_id}", headers=headers
        )

    # ─── Production catalogue: components ─────────────

    def create_component(self, payload, headers):
        """Register a component part with its cost and supplier lead time."""
        return self._request("POST", f"{API_PREFIX}/components", payload, headers)

    def get_component(self, component_id, headers):
        """Read one component with its derived reserved_qty and shortfall_qty."""
        return self._request(
            "GET", f"{API_PREFIX}/components/{component_id}", headers=headers
        )

    # ─── Production catalogue: bill-of-material rows ──

    def create_car_type_component_requirement(self, payload, headers):
        """Bind a component to a car type at a per-car quantity."""
        return self._request(
            "POST", f"{API_PREFIX}/car-type-component-requirements", payload, headers
        )

    def list_car_type_component_requirements(self, headers, params=None):
        """List bill-of-material rows, filterable by car type or component."""
        return self._request(
            "GET",
            f"{API_PREFIX}/car-type-component-requirements",
            payload=params,
            headers=headers,
        )

    def get_car_type_component_requirement(self, requirement_id, headers):
        """Read one bill-of-material row."""
        return self._request(
            "GET",
            f"{API_PREFIX}/car-type-component-requirements/{requirement_id}",
            headers=headers,
        )

    # ─── Production orders ────────────────────────────

    def create_production_order(self, payload, headers):
        """Take a customer order for cars of one type."""
        return self._request("POST", f"{API_PREFIX}/production-orders", payload, headers)

    def list_production_orders(self, headers, params=None):
        """List production orders, filterable by status and car type."""
        return self._request(
            "GET", f"{API_PREFIX}/production-orders", payload=params, headers=headers
        )

    def get_production_order(self, order_id, headers):
        """Read one production order."""
        return self._request(
            "GET", f"{API_PREFIX}/production-orders/{order_id}", headers=headers
        )

    def list_superseding_orders(self, order_id, headers, params=None):
        """List orders that superseded this production order."""
        return self._request(
            "GET",
            f"{API_PREFIX}/production-orders/{order_id}/superseding-orders",
            payload=params,
            headers=headers,
        )

    def reserve_components(self, order_id, headers, payload=None):
        """Commit wheelset and casting stock to the order and re-quote it."""
        return self._request(
            "POST",
            f"{API_PREFIX}/production-orders/{order_id}/reserve-components",
            payload if payload is not None else {},
            headers,
        )

    def release_production_order(self, order_id, headers, payload=None):
        """Release the fully sourced order to the backlog for scheduling."""
        return self._request(
            "POST",
            f"{API_PREFIX}/production-orders/{order_id}/release",
            payload if payload is not None else {},
            headers,
        )

    def complete_production_order(self, order_id, payload, headers):
        """Complete the remaining cars of an in-production order."""
        return self._request(
            "POST",
            f"{API_PREFIX}/production-orders/{order_id}/complete",
            payload,
            headers,
        )

    def cancel_production_order(self, order_id, headers, payload=None):
        """Cancel a draft or component-reserved order."""
        return self._request(
            "POST",
            f"{API_PREFIX}/production-orders/{order_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Production lines ─────────────────────────────

    def changeover_production_line(self, line, payload, headers):
        """Schedule a line changeover and start the head-of-backlog order."""
        return self._request(
            "POST", f"{API_PREFIX}/production-lines/{line}/changeover", payload, headers
        )

    # ─── Substitution endorsements ────────────────────

    def create_substitution_endorsement(self, payload, headers):
        """Raise a substitution endorsement offering a substitute component."""
        return self._request(
            "POST", f"{API_PREFIX}/substitution-endorsements", payload, headers
        )

    def list_substitution_endorsements(self, headers, params=None):
        """List substitution endorsements."""
        return self._request(
            "GET",
            f"{API_PREFIX}/substitution-endorsements",
            payload=params,
            headers=headers,
        )

    def get_substitution_endorsement(self, endorsement_id, headers):
        """Read one substitution endorsement."""
        return self._request(
            "GET",
            f"{API_PREFIX}/substitution-endorsements/{endorsement_id}",
            headers=headers,
        )

    def approve_substitution_endorsement(self, endorsement_id, headers, payload=None):
        """Approve an endorsement as a second person; re-quotes the order."""
        return self._request(
            "POST",
            f"{API_PREFIX}/substitution-endorsements/{endorsement_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def patch_substitution_endorsement(self, endorsement_id, payload, headers):
        """Reject a pending endorsement, or return a rejected one to pending."""
        return self._request(
            "PATCH",
            f"{API_PREFIX}/substitution-endorsements/{endorsement_id}",
            payload,
            headers,
        )

    # ─── Lease contracts ──────────────────────────────

    def create_lease_contract(self, payload, headers):
        """Write a lease contract with its rate, liability bearer and cap."""
        return self._request("POST", f"{API_PREFIX}/lease-contracts", payload, headers)

    def list_lease_contracts(self, headers, params=None):
        """List lease contracts, filterable by status or lessee."""
        return self._request(
            "GET", f"{API_PREFIX}/lease-contracts", payload=params, headers=headers
        )

    def get_lease_contract(self, contract_id, headers):
        """Read one lease contract."""
        return self._request(
            "GET", f"{API_PREFIX}/lease-contracts/{contract_id}", headers=headers
        )

    def activate_lease_contract(self, contract_id, headers, payload=None):
        """Put a drafted contract into force."""
        return self._request(
            "POST",
            f"{API_PREFIX}/lease-contracts/{contract_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def draft_lease_amendment(self, contract_id, payload, headers):
        """Draft an amendment changing the rate or the liability bearer."""
        return self._request(
            "POST",
            f"{API_PREFIX}/lease-contracts/{contract_id}/amendments",
            payload,
            headers,
        )

    def ratify_lease_amendment(self, contract_id, payload, headers):
        """Ratify the drafted amendment, restating live placements."""
        return self._request(
            "POST",
            f"{API_PREFIX}/lease-contracts/{contract_id}/amendments/ratify",
            payload,
            headers,
        )

    def terminate_lease_contract(self, contract_id, headers, payload=None):
        """Terminate a contract, closing its live placements."""
        return self._request(
            "POST",
            f"{API_PREFIX}/lease-contracts/{contract_id}/terminate",
            payload if payload is not None else {},
            headers,
        )

    # ─── Lessees ──────────────────────────────────────

    def create_lessee(self, payload, headers):
        """Register a lessee account with its credit tier and ceiling."""
        return self._request("POST", f"{API_PREFIX}/lessees", payload, headers)

    def get_lessee_outstanding_balance(self, lessee_id, headers):
        """Compute the lessee's ledger balance and its components."""
        return self._request(
            "GET",
            f"{API_PREFIX}/lessees/{lessee_id}/outstanding-balance",
            headers=headers,
        )

    # ─── Lease fleet cars ─────────────────────────────

    def list_lease_fleet_cars(self, headers, params=None):
        """List lease fleet cars, filterable by status, type, contract or order."""
        return self._request(
            "GET", f"{API_PREFIX}/lease-fleet-cars", payload=params, headers=headers
        )

    def get_lease_fleet_car(self, car_id, headers):
        """Read one lease fleet car with its derived life end and retrofit flag."""
        return self._request(
            "GET", f"{API_PREFIX}/lease-fleet-cars/{car_id}", headers=headers
        )

    def settle_fleet_car_returns(self, car_id, headers, payload=None):
        """Close out a repaired car once every return against it is settled."""
        return self._request(
            "POST",
            f"{API_PREFIX}/lease-fleet-cars/{car_id}/settle-returns",
            payload if payload is not None else {},
            headers,
        )

    def scrap_lease_fleet_car(self, car_id, headers, payload=None):
        """Scrap a car at the end of its regulatory life or as a write-off."""
        return self._request(
            "POST",
            f"{API_PREFIX}/lease-fleet-cars/{car_id}/scrap",
            payload if payload is not None else {},
            headers,
        )

    # ─── Car assignments ──────────────────────────────

    def create_car_assignment(self, payload, headers):
        """Place a free car with a lessee under an active contract."""
        return self._request("POST", f"{API_PREFIX}/car-assignments", payload, headers)

    def list_car_assignments(self, headers, params=None):
        """List car placements, filterable by status, car or contract."""
        return self._request(
            "GET", f"{API_PREFIX}/car-assignments", payload=params, headers=headers
        )

    def get_car_assignment(self, assignment_id, headers):
        """Read one car placement."""
        return self._request(
            "GET", f"{API_PREFIX}/car-assignments/{assignment_id}", headers=headers
        )

    def suspend_car_assignment(self, assignment_id, headers, payload=None):
        """Suspend a placement, stopping the per-diem meter."""
        return self._request(
            "POST",
            f"{API_PREFIX}/car-assignments/{assignment_id}/suspend",
            payload if payload is not None else {},
            headers,
        )

    def resume_car_assignment(self, assignment_id, headers, payload=None):
        """Resume a suspended or reassigned placement."""
        return self._request(
            "POST",
            f"{API_PREFIX}/car-assignments/{assignment_id}/resume",
            payload if payload is not None else {},
            headers,
        )

    def reassign_car_assignment(self, assignment_id, payload, headers):
        """Move a placement to another free car under the same contract."""
        return self._request(
            "POST",
            f"{API_PREFIX}/car-assignments/{assignment_id}/reassign",
            payload,
            headers,
        )

    # ─── Car returns ──────────────────────────────────

    def create_car_return(self, payload, headers):
        """Record a car coming back off a placement."""
        return self._request("POST", f"{API_PREFIX}/car-returns", payload, headers)

    def list_car_returns(self, headers, params=None):
        """List returns, filterable by car, placement or settlement status."""
        return self._request(
            "GET", f"{API_PREFIX}/car-returns", payload=params, headers=headers
        )

    def get_car_return(self, return_id, headers):
        """Read one return."""
        return self._request(
            "GET", f"{API_PREFIX}/car-returns/{return_id}", headers=headers
        )

    def settle_car_return(self, return_id, headers, payload=None):
        """Settle a return, moving its charge into the lessee ledger."""
        return self._request(
            "POST",
            f"{API_PREFIX}/car-returns/{return_id}/settle",
            payload if payload is not None else {},
            headers,
        )


    # ─── Retrofit programs ────────────────────────────

    def create_retrofit_program(self, payload, headers):
        """Open a regulatory retrofit mandate program."""
        return self._request("POST", f"{API_PREFIX}/retrofit-programs", payload, headers)

    def list_retrofit_programs(self, headers, params=None):
        """List retrofit programs."""
        return self._request(
            "GET", f"{API_PREFIX}/retrofit-programs", payload=params, headers=headers
        )

    def get_retrofit_program(self, program_id, headers):
        """Read one retrofit program."""
        return self._request(
            "GET", f"{API_PREFIX}/retrofit-programs/{program_id}", headers=headers
        )

    def start_retrofit_program(self, program_id, headers, payload=None):
        """Start the program, enrolling every covered fleet car."""
        return self._request(
            "POST",
            f"{API_PREFIX}/retrofit-programs/{program_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def complete_retrofit_program(self, program_id, headers, payload=None):
        """Close the program once every covered car type has completed work."""
        return self._request(
            "POST",
            f"{API_PREFIX}/retrofit-programs/{program_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def void_retrofit_program(self, program_id, headers, payload=None):
        """Void the program, cancelling its work orders."""
        return self._request(
            "POST",
            f"{API_PREFIX}/retrofit-programs/{program_id}/void",
            payload if payload is not None else {},
            headers,
        )

    # ─── Retrofit program coverage ────────────────────

    def create_retrofit_program_car_type(self, payload, headers):
        """Cover a car type under a retrofit program."""
        return self._request(
            "POST", f"{API_PREFIX}/retrofit-program-car-types", payload, headers
        )

    def list_retrofit_program_car_types(self, headers, params=None):
        """List program-to-car-type coverage rows."""
        return self._request(
            "GET",
            f"{API_PREFIX}/retrofit-program-car-types",
            payload=params,
            headers=headers,
        )

    def get_retrofit_program_car_type(self, coverage_id, headers):
        """Read one program-to-car-type coverage row."""
        return self._request(
            "GET",
            f"{API_PREFIX}/retrofit-program-car-types/{coverage_id}",
            headers=headers,
        )

    # ─── Retrofit work orders ─────────────────────────

    def create_retrofit_work_order(self, payload, headers):
        """Schedule retrofit shop work on a shop line for a covered car."""
        return self._request(
            "POST", f"{API_PREFIX}/retrofit-work-orders", payload, headers
        )

    def list_retrofit_work_orders(self, headers, params=None):
        """List retrofit work orders, filterable by status, line, car or program."""
        return self._request(
            "GET", f"{API_PREFIX}/retrofit-work-orders", payload=params, headers=headers
        )

    def get_retrofit_work_order(self, work_order_id, headers):
        """Read one retrofit work order."""
        return self._request(
            "GET",
            f"{API_PREFIX}/retrofit-work-orders/{work_order_id}",
            headers=headers,
        )

    def start_retrofit_work_order(self, work_order_id, headers, payload=None):
        """Start shop work, consuming the mandate's retrofit component kit."""
        return self._request(
            "POST",
            f"{API_PREFIX}/retrofit-work-orders/{work_order_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def complete_retrofit_work_order(self, work_order_id, headers, payload=None):
        """Complete shop work, returning the car to service."""
        return self._request(
            "POST",
            f"{API_PREFIX}/retrofit-work-orders/{work_order_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def cancel_retrofit_work_order(self, work_order_id, headers, payload=None):
        """Cancel scheduled shop work before it starts."""
        return self._request(
            "POST",
            f"{API_PREFIX}/retrofit-work-orders/{work_order_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Component purchase orders ────────────────────

    def create_component_purchase_order(self, payload, headers):
        """Raise a purchase order for a component against its supplier lead time."""
        return self._request(
            "POST", f"{API_PREFIX}/component-purchase-orders", payload, headers
        )

    def list_component_purchase_orders(self, headers, params=None):
        """List purchase orders, filterable by status or component."""
        return self._request(
            "GET",
            f"{API_PREFIX}/component-purchase-orders",
            payload=params,
            headers=headers,
        )

    def get_component_purchase_order(self, purchase_order_id, headers):
        """Read one purchase order."""
        return self._request(
            "GET",
            f"{API_PREFIX}/component-purchase-orders/{purchase_order_id}",
            headers=headers,
        )

    def confirm_component_purchase_order(self, purchase_order_id, headers, payload=None):
        """Confirm a placed purchase with the supplier."""
        return self._request(
            "POST",
            f"{API_PREFIX}/component-purchase-orders/{purchase_order_id}/confirm",
            payload if payload is not None else {},
            headers,
        )

    def cancel_component_purchase_order(self, purchase_order_id, headers, payload=None):
        """Cancel a placed purchase before confirmation."""
        return self._request(
            "POST",
            f"{API_PREFIX}/component-purchase-orders/{purchase_order_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # ─── Component receipts ───────────────────────────

    def create_component_receipt(self, payload, headers):
        """Book receipt of a component delivery in the yard."""
        return self._request("POST", f"{API_PREFIX}/component-receipts", payload, headers)

    def list_component_receipts(self, headers, params=None):
        """List component receipts."""
        return self._request(
            "GET", f"{API_PREFIX}/component-receipts", payload=params, headers=headers
        )

    def get_component_receipt(self, receipt_id, headers):
        """Read one component receipt."""
        return self._request(
            "GET", f"{API_PREFIX}/component-receipts/{receipt_id}", headers=headers
        )

    def receive_component_receipt(self, receipt_id, headers, payload=None):
        """Apply a booked receipt to stock, increasing on-hand quantity."""
        return self._request(
            "POST",
            f"{API_PREFIX}/component-receipts/{receipt_id}/receive",
            payload if payload is not None else {},
            headers,
        )


    # ─── Secondary-market fleet sales ─────────────────

    def create_lease_fleet_sale(self, payload, headers):
        """Sell a fleet car on the secondary market."""
        return self._request("POST", f"{API_PREFIX}/lease-fleet-sales", payload, headers)

    def list_lease_fleet_sales(self, headers, params=None):
        """List secondary-market sales."""
        return self._request(
            "GET", f"{API_PREFIX}/lease-fleet-sales", payload=params, headers=headers
        )

    def get_lease_fleet_sale(self, sale_id, headers):
        """Read one fleet sale."""
        return self._request(
            "GET", f"{API_PREFIX}/lease-fleet-sales/{sale_id}", headers=headers
        )

    def settle_lease_fleet_sale(self, sale_id, headers, payload=None):
        """Settle a pending sale into the portfolio ledger."""
        return self._request(
            "POST",
            f"{API_PREFIX}/lease-fleet-sales/{sale_id}/settle",
            payload if payload is not None else {},
            headers,
        )

    def void_lease_fleet_sale(self, sale_id, headers, payload=None):
        """Void a pending sale and return the car to the fleet."""
        return self._request(
            "POST",
            f"{API_PREFIX}/lease-fleet-sales/{sale_id}/void",
            payload if payload is not None else {},
            headers,
        )

    # ─── Portfolio ledger ─────────────────────────────

    def get_portfolio_ledger(self, headers):
        """Read the singleton portfolio ledger."""
        return self._request("GET", f"{API_PREFIX}/portfolio-ledger", headers=headers)

    def get_portfolio_ledger_reconciliation(self, headers):
        """Compute both bases of fleet capital and their drift."""
        return self._request(
            "GET", f"{API_PREFIX}/portfolio-ledger/reconciliation", headers=headers
        )

    # ─── Logical clock ────────────────────────────────

    def set_current_utc(self, to_iso8601, headers):
        """Set the logical clock to the supplied instant."""
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def set_clock(self, to_iso8601, headers):
        """Alias for :meth:`set_current_utc` — advances the logical clock."""
        return self.set_current_utc(to_iso8601, headers)

    def get_current_utc(self, headers):
        """Read the logical clock's current instant."""
        return self._request("GET", f"{API_PREFIX}/_clock/current", headers=headers)


api_client = ApiClient()
