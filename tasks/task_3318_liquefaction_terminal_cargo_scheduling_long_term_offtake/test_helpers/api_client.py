"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- customers / SPAs ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def list_customer_spas(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/api/customers/{customer_id}/spas", headers=headers, params=params
        )

    def create_spa(self, payload, headers):
        return self._request("POST", "/api/spas", payload, headers)

    def get_spa(self, spa_id, headers):
        return self._request("GET", f"/api/spas/{spa_id}", headers=headers)

    def list_spa_adps(self, spa_id, headers, params=None):
        return self._request(
            "GET", f"/api/spas/{spa_id}/adps", headers=headers, params=params
        )

    def commence_spa_deliveries(self, spa_id, headers):
        return self._request(
            "POST", f"/api/spas/{spa_id}/commence-deliveries", {}, headers
        )

    # ---- trains / turnarounds ----
    def create_train(self, payload, headers):
        return self._request("POST", "/api/trains", payload, headers)

    def get_train(self, train_id, headers):
        return self._request("GET", f"/api/trains/{train_id}", headers=headers)

    def begin_commissioning(self, train_id, headers):
        return self._request(
            "POST", f"/api/trains/{train_id}/begin-commissioning", {}, headers
        )

    def record_commissioning_cargo(self, train_id, payload, headers):
        return self._request(
            "POST", f"/api/trains/{train_id}/record-commissioning-cargo", payload, headers
        )

    def declare_cod(self, train_id, payload, headers):
        return self._request("POST", f"/api/trains/{train_id}/declare-cod", payload, headers)

    def propose_turnaround(self, train_id, payload, headers):
        return self._request(
            "POST", f"/api/trains/{train_id}/turnarounds", payload, headers
        )

    def list_train_turnarounds(self, train_id, headers, params=None):
        return self._request(
            "GET", f"/api/trains/{train_id}/turnarounds", headers=headers, params=params
        )

    def get_turnaround(self, turnaround_id, headers):
        return self._request("GET", f"/api/turnarounds/{turnaround_id}", headers=headers)

    def approve_turnaround(self, turnaround_id, headers):
        return self._request(
            "POST", f"/api/turnarounds/{turnaround_id}/approve", {}, headers
        )

    def begin_turnaround(self, turnaround_id, headers):
        return self._request(
            "POST", f"/api/turnarounds/{turnaround_id}/begin", {}, headers
        )

    def complete_turnaround(self, turnaround_id, headers):
        return self._request(
            "POST", f"/api/turnarounds/{turnaround_id}/complete", {}, headers
        )

    # ---- ADPs / cargo slots ----
    def create_adp(self, payload, headers):
        return self._request("POST", "/api/adps", payload, headers)

    def get_adp(self, adp_id, headers):
        return self._request("GET", f"/api/adps/{adp_id}", headers=headers)

    def propose_adp(self, adp_id, headers):
        return self._request("POST", f"/api/adps/{adp_id}/propose", {}, headers)

    def confirm_adp(self, adp_id, headers):
        return self._request("POST", f"/api/adps/{adp_id}/confirm", {}, headers)

    def lock_adp(self, adp_id, headers):
        return self._request("POST", f"/api/adps/{adp_id}/lock", {}, headers)

    def reconcile_adp(self, adp_id, payload, headers):
        return self._request("POST", f"/api/adps/{adp_id}/reconcile", payload, headers)

    def create_cargo_slot(self, adp_id, payload, headers):
        return self._request("POST", f"/api/adps/{adp_id}/cargo-slots", payload, headers)

    def list_adp_cargo_slots(self, adp_id, headers, params=None):
        return self._request(
            "GET", f"/api/adps/{adp_id}/cargo-slots", headers=headers, params=params
        )

    def get_cargo_slot(self, slot_id, headers):
        return self._request("GET", f"/api/cargo-slots/{slot_id}", headers=headers)

    def nominate_vessel(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/api/cargo-slots/{slot_id}/vessel-nominations", payload, headers
        )

    def list_cargo_slot_vessel_calls(self, slot_id, headers, params=None):
        return self._request(
            "GET", f"/api/cargo-slots/{slot_id}/vessel-calls", headers=headers, params=params
        )

    def cancel_cargo_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/api/cargo-slots/{slot_id}/cancellations", {}, headers
        )

    def list_cargo_slot_cancellations(self, slot_id, headers, params=None):
        return self._request(
            "GET", f"/api/cargo-slots/{slot_id}/cancellations", headers=headers, params=params
        )

    def list_cargo_slot_nominations(self, slot_id, headers, params=None):
        return self._request(
            "GET", f"/api/cargo-slots/{slot_id}/nominations", headers=headers, params=params
        )

    def issue_final_invoice(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/api/cargo-slots/{slot_id}/issue-final-invoice", payload, headers
        )

    # ---- berths / vessel calls / laytime ----
    def create_berth(self, payload, headers):
        return self._request("POST", "/api/berths", payload, headers)

    def get_berth(self, berth_id, headers):
        return self._request("GET", f"/api/berths/{berth_id}", headers=headers)

    def list_berth_vessel_calls(self, berth_id, headers, params=None):
        return self._request(
            "GET", f"/api/berths/{berth_id}/vessel-calls", headers=headers, params=params
        )

    def get_vessel_call(self, call_id, headers):
        return self._request("GET", f"/api/vessel-calls/{call_id}", headers=headers)

    def accept_vessel_call(self, call_id, payload, headers):
        return self._request("POST", f"/api/vessel-calls/{call_id}/accept", payload, headers)

    def tender_nor(self, call_id, headers):
        return self._request("POST", f"/api/vessel-calls/{call_id}/tender-nor", {}, headers)

    def berth_vessel_call(self, call_id, headers):
        return self._request("POST", f"/api/vessel-calls/{call_id}/berth", {}, headers)

    def depart_vessel_call(self, call_id, headers):
        return self._request("POST", f"/api/vessel-calls/{call_id}/depart", {}, headers)

    def create_laytime_statement(self, call_id, payload, headers):
        return self._request(
            "POST", f"/api/vessel-calls/{call_id}/laytime-statements", payload, headers
        )

    def list_vessel_call_laytime_statements(self, call_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/vessel-calls/{call_id}/laytime-statements",
            headers=headers,
            params=params,
        )

    def get_laytime_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/api/laytime-statements/{statement_id}", headers=headers
        )

    def agree_laytime_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/api/laytime-statements/{statement_id}/agree", {}, headers
        )

    def dispute_laytime_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/api/laytime-statements/{statement_id}/dispute", payload, headers
        )

    def resolve_laytime_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/api/laytime-statements/{statement_id}/resolve", payload, headers
        )

    # ---- pipelines / nominations ----
    def create_pipeline(self, payload, headers):
        return self._request("POST", "/api/pipelines", payload, headers)

    def get_pipeline(self, pipeline_id, headers):
        return self._request("GET", f"/api/pipelines/{pipeline_id}", headers=headers)

    def create_day_schedule(self, pipeline_id, payload, headers):
        return self._request(
            "POST", f"/api/pipelines/{pipeline_id}/day-schedules", payload, headers
        )

    def list_pipeline_day_schedules(self, pipeline_id, headers, params=None):
        return self._request(
            "GET", f"/api/pipelines/{pipeline_id}/day-schedules", headers=headers, params=params
        )

    def get_day_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/api/pipeline-day-schedules/{schedule_id}", headers=headers
        )

    def close_day_schedule(self, schedule_id, headers):
        return self._request(
            "POST", f"/api/pipeline-day-schedules/{schedule_id}/close", {}, headers
        )

    def create_nomination(self, schedule_id, payload, headers):
        return self._request(
            "POST",
            f"/api/pipeline-day-schedules/{schedule_id}/nominations",
            payload,
            headers,
        )

    def list_day_schedule_nominations(self, schedule_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/pipeline-day-schedules/{schedule_id}/nominations",
            headers=headers,
            params=params,
        )

    def get_nomination(self, nomination_id, headers):
        return self._request(
            "GET", f"/api/feed-gas-nominations/{nomination_id}", headers=headers
        )

    def reconcile_nomination(self, nomination_id, headers):
        return self._request(
            "POST", f"/api/feed-gas-nominations/{nomination_id}/reconcile", {}, headers
        )

    # ---- cancellations / resales ----
    def get_cancellation(self, cancellation_id, headers):
        return self._request(
            "GET", f"/api/cargo-cancellations/{cancellation_id}", headers=headers
        )

    def settle_cancellation(self, cancellation_id, headers):
        return self._request(
            "POST", f"/api/cargo-cancellations/{cancellation_id}/settle", {}, headers
        )

    def create_resale(self, cancellation_id, payload, headers):
        return self._request(
            "POST", f"/api/cargo-cancellations/{cancellation_id}/resales", payload, headers
        )

    def list_cancellation_resales(self, cancellation_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/cargo-cancellations/{cancellation_id}/resales",
            headers=headers,
            params=params,
        )

    def sell_resale(self, resale_id, payload, headers):
        return self._request(
            "POST", f"/api/feed-gas-resales/{resale_id}/sell", payload, headers
        )

    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
