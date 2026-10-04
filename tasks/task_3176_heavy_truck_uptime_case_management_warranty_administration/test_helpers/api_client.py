"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock / ops ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def ops_run(self, headers):
        return self._request("POST", "/_ops/run", {}, headers)

    # ---- Fleets ----
    def create_fleet(self, payload, headers):
        return self._request("POST", "/fleets", payload, headers)

    def list_fleets(self, headers, params=None):
        return self._request("GET", "/fleets", headers=headers, params=params)

    def get_fleet(self, fleet_id, headers):
        return self._request("GET", f"/fleets/{fleet_id}", headers=headers)

    def update_fleet(self, fleet_id, payload, headers):
        return self._request("PUT", f"/fleets/{fleet_id}", payload, headers)

    def suspend_fleet(self, fleet_id, headers):
        return self._request("POST", f"/fleets/{fleet_id}/suspend", {}, headers)

    def reactivate_fleet(self, fleet_id, headers):
        return self._request("POST", f"/fleets/{fleet_id}/reactivate", {}, headers)

    # ---- Trucks ----
    def create_truck(self, fleet_id, payload, headers):
        return self._request("POST", f"/fleets/{fleet_id}/trucks", payload, headers)

    def list_trucks(self, fleet_id, headers, params=None):
        return self._request(
            "GET", f"/fleets/{fleet_id}/trucks", headers=headers, params=params
        )

    def get_truck(self, fleet_id, truck_id, headers):
        return self._request(
            "GET", f"/fleets/{fleet_id}/trucks/{truck_id}", headers=headers
        )

    def update_truck(self, fleet_id, truck_id, payload, headers):
        return self._request(
            "PUT", f"/fleets/{fleet_id}/trucks/{truck_id}", payload, headers
        )

    def decommission_truck(self, fleet_id, truck_id, headers):
        return self._request(
            "POST", f"/fleets/{fleet_id}/trucks/{truck_id}/decommission", {}, headers
        )

    # ---- Fault events ----
    def create_fault_event(self, fleet_id, truck_id, payload, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/fault-events",
            payload,
            headers,
        )

    def list_fault_events(self, fleet_id, truck_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/trucks/{truck_id}/fault-events",
            headers=headers,
            params=params,
        )

    def dismiss_fault_event(self, fleet_id, truck_id, fault_event_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/fault-events/{fault_event_id}/dismiss",
            {},
            headers,
        )

    # ---- Cases ----
    def create_case(self, fleet_id, truck_id, payload, headers):
        return self._request(
            "POST", f"/fleets/{fleet_id}/trucks/{truck_id}/cases", payload, headers
        )

    def list_cases(self, fleet_id, truck_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases",
            headers=headers,
            params=params,
        )

    def get_case(self, fleet_id, truck_id, case_id, headers):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}",
            headers=headers,
        )

    def triage_case(self, fleet_id, truck_id, case_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/triage",
            {},
            headers,
        )

    def schedule_case(self, fleet_id, truck_id, case_id, payload, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/schedule",
            payload,
            headers,
        )

    def start_service(self, fleet_id, truck_id, case_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/start-service",
            {},
            headers,
        )

    def request_close(self, fleet_id, truck_id, case_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/request-close",
            {},
            headers,
        )

    def reopen_service(self, fleet_id, truck_id, case_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/reopen-service",
            {},
            headers,
        )

    def close_case(self, fleet_id, truck_id, case_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/close",
            {},
            headers,
        )

    def cancel_case(self, fleet_id, truck_id, case_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/cancel",
            {},
            headers,
        )

    # ---- Work orders ----
    def list_work_orders(self, fleet_id, truck_id, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/work-orders",
            headers=headers,
            params=params,
        )

    def authorize_work_order(
        self, fleet_id, truck_id, case_id, work_order_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/work-orders/{work_order_id}/authorize",
            payload,
            headers,
        )

    def complete_work_order(
        self, fleet_id, truck_id, case_id, work_order_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/work-orders/{work_order_id}/complete",
            payload,
            headers,
        )

    def cancel_work_order(
        self, fleet_id, truck_id, case_id, work_order_id, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/work-orders/{work_order_id}/cancel",
            {},
            headers,
        )

    # ---- Part orders ----
    def create_part_order(self, fleet_id, truck_id, case_id, payload, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/part-orders",
            payload,
            headers,
        )

    def list_part_orders(self, fleet_id, truck_id, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/part-orders",
            headers=headers,
            params=params,
        )

    def evaluate_expedite(
        self, fleet_id, truck_id, case_id, part_order_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/part-orders/{part_order_id}/evaluate-expedite",
            payload,
            headers,
        )

    def ship_part_order(self, fleet_id, truck_id, case_id, part_order_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/part-orders/{part_order_id}/ship",
            {},
            headers,
        )

    def receive_part_order(self, fleet_id, truck_id, case_id, part_order_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/part-orders/{part_order_id}/receive",
            {},
            headers,
        )

    def install_part_order(self, fleet_id, truck_id, case_id, part_order_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/part-orders/{part_order_id}/install",
            {},
            headers,
        )

    def cancel_part_order(self, fleet_id, truck_id, case_id, part_order_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/part-orders/{part_order_id}/cancel",
            {},
            headers,
        )

    # ---- Warranty claims ----
    def create_claim(self, fleet_id, truck_id, case_id, payload, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims",
            payload,
            headers,
        )

    def list_claims(self, fleet_id, truck_id, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims",
            headers=headers,
            params=params,
        )

    def get_claim(self, fleet_id, truck_id, case_id, claim_id, headers):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}",
            headers=headers,
        )

    def submit_claim(self, fleet_id, truck_id, case_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/submit",
            payload,
            headers,
        )

    def begin_review_claim(self, fleet_id, truck_id, case_id, claim_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/begin-review",
            {},
            headers,
        )

    def approve_claim(self, fleet_id, truck_id, case_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/approve",
            payload,
            headers,
        )

    def deny_claim(self, fleet_id, truck_id, case_id, claim_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/deny",
            {},
            headers,
        )

    # ---- Part returns ----
    def list_part_returns(
        self, fleet_id, truck_id, case_id, claim_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/part-returns",
            headers=headers,
            params=params,
        )

    def ship_part_return(
        self, fleet_id, truck_id, case_id, claim_id, part_return_id, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/part-returns/{part_return_id}/ship",
            {},
            headers,
        )

    def receive_part_return(
        self, fleet_id, truck_id, case_id, claim_id, part_return_id, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/part-returns/{part_return_id}/receive",
            {},
            headers,
        )

    def inspect_part_return(
        self, fleet_id, truck_id, case_id, claim_id, part_return_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/part-returns/{part_return_id}/inspect",
            payload,
            headers,
        )

    # ---- Supplier recoveries ----
    def create_recovery(self, fleet_id, truck_id, case_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/recoveries",
            payload,
            headers,
        )

    def list_recoveries(
        self, fleet_id, truck_id, case_id, claim_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/recoveries",
            headers=headers,
            params=params,
        )

    def dispute_recovery(
        self, fleet_id, truck_id, case_id, claim_id, recovery_id, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/recoveries/{recovery_id}/dispute",
            {},
            headers,
        )

    def refile_recovery(
        self, fleet_id, truck_id, case_id, claim_id, recovery_id, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/recoveries/{recovery_id}/refile",
            {},
            headers,
        )

    def mark_paid_recovery(
        self, fleet_id, truck_id, case_id, claim_id, recovery_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/recoveries/{recovery_id}/mark-paid",
            payload,
            headers,
        )

    def deny_recovery(
        self, fleet_id, truck_id, case_id, claim_id, recovery_id, headers
    ):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/cases/{case_id}/claims/{claim_id}/recoveries/{recovery_id}/deny",
            {},
            headers,
        )

    # ---- Dealers / bays ----
    def create_dealer(self, payload, headers):
        return self._request("POST", "/dealers", payload, headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/dealers", headers=headers, params=params)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/dealers/{dealer_id}", headers=headers)

    def create_bay(self, dealer_id, payload, headers):
        return self._request("POST", f"/dealers/{dealer_id}/bays", payload, headers)

    def list_bays(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"/dealers/{dealer_id}/bays", headers=headers, params=params
        )

    def mark_bay_down(self, dealer_id, bay_id, headers):
        return self._request(
            "POST", f"/dealers/{dealer_id}/bays/{bay_id}/mark-down", {}, headers
        )

    def mark_bay_available(self, dealer_id, bay_id, headers):
        return self._request(
            "POST", f"/dealers/{dealer_id}/bays/{bay_id}/mark-available", {}, headers
        )

    # ---- Coverage contracts ----
    def create_coverage_contract(self, fleet_id, truck_id, payload, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/coverage-contracts",
            payload,
            headers,
        )

    def list_coverage_contracts(
        self, fleet_id, truck_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/trucks/{truck_id}/coverage-contracts",
            headers=headers,
            params=params,
        )

    def cancel_coverage_contract(self, fleet_id, truck_id, contract_id, headers):
        return self._request(
            "POST",
            f"/fleets/{fleet_id}/trucks/{truck_id}/coverage-contracts/{contract_id}/cancel",
            {},
            headers,
        )

    # ---- Campaigns ----
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def close_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/close", payload, headers
        )

    # ---- Campaign completions ----
    def list_campaign_completions(self, campaign_id, headers, params=None):
        return self._request(
            "GET",
            f"/campaigns/{campaign_id}/completions",
            headers=headers,
            params=params,
        )

    def schedule_completion(
        self, campaign_id, completion_id, payload, headers
    ):
        return self._request(
            "POST",
            f"/campaigns/{campaign_id}/completions/{completion_id}/schedule",
            payload,
            headers,
        )

    def exempt_completion(self, campaign_id, completion_id, payload, headers):
        return self._request(
            "POST",
            f"/campaigns/{campaign_id}/completions/{completion_id}/exempt",
            payload,
            headers,
        )

    # ---- Reliability reports ----
    def list_reliability_reports(self, fleet_id, headers, params=None):
        return self._request(
            "GET",
            f"/fleets/{fleet_id}/reliability-reports",
            headers=headers,
            params=params,
        )

    # ---- Cross-aggregate reads ----
    def get_truck_by_id(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    def list_trucks_global(self, headers, params=None):
        return self._request("GET", "/trucks", headers=headers, params=params)

    def get_case_by_id(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases_global(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def get_bay_by_id(self, bay_id, headers):
        return self._request("GET", f"/bays/{bay_id}", headers=headers)

    def list_bays_global(self, headers, params=None):
        return self._request("GET", "/bays", headers=headers, params=params)

    def get_campaign_completion_by_id(self, completion_id, headers):
        return self._request(
            "GET", f"/campaign-completions/{completion_id}", headers=headers
        )

    def list_campaign_completions_global(self, headers, params=None):
        return self._request(
            "GET", "/campaign-completions", headers=headers, params=params
        )


api_client = ApiClient()
