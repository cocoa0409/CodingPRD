"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Rodeos ---
    def create_rodeo(self, payload, headers):
        return self._request("POST", "/api/rodeos", payload, headers)

    def get_rodeo(self, rodeo_id, headers):
        return self._request("GET", f"/api/rodeos/{rodeo_id}", headers=headers)

    def rodeo_transition(self, rodeo_id, payload, headers):
        return self._request(
            "POST", f"/api/rodeos/{rodeo_id}/transition", payload, headers
        )

    # --- Rodeo events ---
    def create_rodeo_event(self, payload, headers):
        return self._request("POST", "/api/rodeo-events", payload, headers)

    def list_rodeo_events(self, headers, params=None):
        return self._request("GET", "/api/rodeo-events", headers=headers, params=params)

    def get_rodeo_event(self, event_id, headers):
        return self._request(
            "GET", f"/api/rodeo-events/{event_id}", headers=headers
        )

    def execute_draw(self, event_id, payload, headers):
        return self._request(
            "POST", f"/api/rodeo-events/{event_id}/draws", payload, headers
        )

    # --- Performances ---
    def create_performance(self, payload, headers):
        return self._request("POST", "/api/performances", payload, headers)

    def list_performances(self, headers, params=None):
        return self._request("GET", "/api/performances", headers=headers, params=params)

    def get_performance(self, performance_id, headers):
        return self._request(
            "GET", f"/api/performances/{performance_id}", headers=headers
        )

    def performance_transition(self, performance_id, payload, headers):
        return self._request(
            "POST", f"/api/performances/{performance_id}/transition", payload, headers
        )

    # --- Contestants ---
    def create_contestant(self, payload, headers):
        return self._request("POST", "/api/contestants", payload, headers)

    def list_contestants(self, headers, params=None):
        return self._request("GET", "/api/contestants", headers=headers, params=params)

    def get_contestant(self, contestant_id, headers):
        return self._request(
            "GET", f"/api/contestants/{contestant_id}", headers=headers
        )

    def patch_contestant(self, contestant_id, payload, headers):
        return self._request(
            "PATCH", f"/api/contestants/{contestant_id}", payload, headers
        )

    # --- Stock contracts ---
    def create_stock_contract(self, payload, headers):
        return self._request("POST", "/api/stock-contracts", payload, headers)

    def list_stock_contracts(self, headers, params=None):
        return self._request(
            "GET", "/api/stock-contracts", headers=headers, params=params
        )

    def get_stock_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/api/stock-contracts/{contract_id}", headers=headers
        )

    def stock_contract_transition(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/api/stock-contracts/{contract_id}/transition", payload, headers
        )

    # --- Stock animals ---
    def create_stock_animal(self, payload, headers):
        return self._request("POST", "/api/stock-animals", payload, headers)

    def list_stock_animals(self, headers, params=None):
        return self._request("GET", "/api/stock-animals", headers=headers, params=params)

    def get_stock_animal(self, animal_id, headers):
        return self._request(
            "GET", f"/api/stock-animals/{animal_id}", headers=headers
        )

    # --- Judges and assignments ---
    def create_judge(self, payload, headers):
        return self._request("POST", "/api/judges", payload, headers)

    def list_judges(self, headers, params=None):
        return self._request("GET", "/api/judges", headers=headers, params=params)

    def get_judge(self, judge_id, headers):
        return self._request("GET", f"/api/judges/{judge_id}", headers=headers)

    def create_judge_assignment(self, payload, headers):
        return self._request("POST", "/api/judge-assignments", payload, headers)

    def list_judge_assignments(self, headers, params=None):
        return self._request(
            "GET", "/api/judge-assignments", headers=headers, params=params
        )

    def get_judge_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/api/judge-assignments/{assignment_id}", headers=headers
        )

    # --- Entries ---
    def create_entry(self, payload, headers):
        return self._request("POST", "/api/entries", payload, headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/api/entries", headers=headers, params=params)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/api/entries/{entry_id}", headers=headers)

    def entry_transition(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/api/entries/{entry_id}/transition", payload, headers
        )

    # --- Draw assignments ---
    def list_draw_assignments(self, headers, params=None):
        return self._request(
            "GET", "/api/draw-assignments", headers=headers, params=params
        )

    def get_draw_assignment(self, draw_assignment_id, headers):
        return self._request(
            "GET", f"/api/draw-assignments/{draw_assignment_id}", headers=headers
        )

    def reride_assignment(self, draw_assignment_id, payload, headers):
        return self._request(
            "POST", f"/api/draw-assignments/{draw_assignment_id}/reride",
            payload, headers,
        )

    # --- Run results ---
    def create_run_result(self, payload, headers):
        return self._request("POST", "/api/run-results", payload, headers)

    def list_run_results(self, headers, params=None):
        return self._request("GET", "/api/run-results", headers=headers, params=params)

    def get_run_result(self, result_id, headers):
        return self._request("GET", f"/api/run-results/{result_id}", headers=headers)

    def run_result_transition(self, result_id, payload, headers):
        return self._request(
            "POST", f"/api/run-results/{result_id}/transition", payload, headers
        )

    # --- Payouts ---
    def compute_payout(self, payload, headers):
        return self._request("POST", "/api/payouts/compute", payload, headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/api/payouts", headers=headers, params=params)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/api/payouts/{payout_id}", headers=headers)

    def payout_transition(self, payout_id, payload, headers):
        return self._request(
            "POST", f"/api/payouts/{payout_id}/transition", payload, headers
        )

    # --- Vet reports ---
    def create_vet_report(self, payload, headers):
        return self._request("POST", "/api/vet-reports", payload, headers)

    def list_vet_reports(self, headers, params=None):
        return self._request("GET", "/api/vet-reports", headers=headers, params=params)

    def get_vet_report(self, report_id, headers):
        return self._request("GET", f"/api/vet-reports/{report_id}", headers=headers)

    # --- Ticket orders ---
    def create_ticket_order(self, payload, headers):
        return self._request("POST", "/api/ticket-orders", payload, headers)

    def list_ticket_orders(self, headers, params=None):
        return self._request("GET", "/api/ticket-orders", headers=headers, params=params)

    def get_ticket_order(self, order_id, headers):
        return self._request("GET", f"/api/ticket-orders/{order_id}", headers=headers)

    def ticket_order_transition(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/ticket-orders/{order_id}/transition", payload, headers
        )


api_client = ApiClient()
