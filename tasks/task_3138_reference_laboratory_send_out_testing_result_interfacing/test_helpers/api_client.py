"""API client — one method per endpoint on the send-out testing surface."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/reference-lab"


class ApiClient(GenericApiClient):
    # --- logical clock -------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- client laboratories -------------------------------------------------
    def create_client_laboratory(self, payload, headers):
        return self._request("POST", f"{PREFIX}/client-laboratories", payload, headers)

    def list_client_laboratories(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/client-laboratories", headers=headers, params=params)

    def get_client_laboratory(self, client_id, headers):
        return self._request("GET", f"{PREFIX}/client-laboratories/{client_id}", headers=headers)

    def publish_requirements(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/client-laboratories/{client_id}/publish-requirements",
                             {}, headers)

    def activate_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/client-laboratories/{client_id}/activate", {}, headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/client-laboratories/{client_id}/suspend", {}, headers)

    def reinstate_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/client-laboratories/{client_id}/reinstate", {}, headers)

    def settle_balance(self, client_id, settlement_amount_cents, headers):
        return self._request("POST", f"{PREFIX}/client-laboratories/{client_id}/settle-balance",
                             {"settlement_amount_cents": settlement_amount_cents}, headers)

    def deactivate_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/client-laboratories/{client_id}/deactivate", {}, headers)

    # --- courier runs --------------------------------------------------------
    def create_courier_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/courier-runs", payload, headers)

    def list_courier_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/courier-runs", headers=headers, params=params)

    def get_courier_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/courier-runs/{run_id}", headers=headers)

    def dispatch_courier_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/courier-runs/{run_id}/dispatch", {}, headers)

    def recall_courier_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/courier-runs/{run_id}/recall", {}, headers)

    def arrive_courier_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/courier-runs/{run_id}/arrive", {}, headers)

    # --- test catalog entries ------------------------------------------------
    def create_catalog_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/test-catalog-entries", payload, headers)

    def list_catalog_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/test-catalog-entries", headers=headers, params=params)

    def get_catalog_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/test-catalog-entries/{entry_id}", headers=headers)

    def publish_catalog_entry(self, entry_id, headers):
        return self._request("POST", f"{PREFIX}/test-catalog-entries/{entry_id}/publish", {}, headers)

    def deprecate_catalog_entry(self, entry_id, headers):
        return self._request("POST", f"{PREFIX}/test-catalog-entries/{entry_id}/deprecate", {}, headers)

    def withdraw_catalog_entry(self, entry_id, headers):
        return self._request("POST", f"{PREFIX}/test-catalog-entries/{entry_id}/withdraw", {}, headers)

    # --- specimens -----------------------------------------------------------
    def create_specimen(self, payload, headers):
        return self._request("POST", f"{PREFIX}/specimens", payload, headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/specimens", headers=headers, params=params)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"{PREFIX}/specimens/{specimen_id}", headers=headers)

    def accession_specimen(self, specimen_id, headers):
        return self._request("POST", f"{PREFIX}/specimens/{specimen_id}/accession", {}, headers)

    def begin_testing(self, specimen_id, headers):
        return self._request("POST", f"{PREFIX}/specimens/{specimen_id}/begin-testing", {}, headers)

    def reject_specimen(self, specimen_id, rejection_reason_code, headers):
        return self._request("POST", f"{PREFIX}/specimens/{specimen_id}/reject",
                             {"rejection_reason_code": rejection_reason_code}, headers)

    def create_aliquot(self, specimen_id, payload, headers):
        return self._request("POST", f"{PREFIX}/specimens/{specimen_id}/aliquots", payload, headers)

    def delete_aliquot(self, specimen_id, aliquot_id, headers):
        return self._request("DELETE", f"{PREFIX}/specimens/{specimen_id}/aliquots/{aliquot_id}",
                             headers=headers)

    # --- send-out orders -----------------------------------------------------
    def create_send_out_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders", payload, headers)

    def list_send_out_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/send-out-orders", headers=headers, params=params)

    def get_send_out_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/send-out-orders/{order_id}", headers=headers)

    def accession_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/accession", {}, headers)

    def enter_results(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/enter-results",
                             payload, headers)

    def release_results(self, order_id, interpretive_comment, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/release-results",
                             {"interpretive_comment": interpretive_comment}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/cancel", {}, headers)

    def hold_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/hold", {}, headers)

    def release_hold(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/release-hold", {}, headers)

    def repeat_test(self, order_id, order_test_line_id, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/repeat-test",
                             {"order_test_line_id": order_test_line_id}, headers)

    def order_add_on_test(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/order-add-on-test",
                             payload, headers)

    def order_reflex_test(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/order-reflex-test",
                             payload, headers)

    def reflex_cancel(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/reflex-cancel", {}, headers)

    def charge_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/send-out-orders/{order_id}/charge", {}, headers)

    # --- order test lines ----------------------------------------------------
    def list_order_test_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/order-test-lines", headers=headers, params=params)

    def get_order_test_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/order-test-lines/{line_id}", headers=headers)

    # --- instrument runs -----------------------------------------------------
    def create_instrument_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/instrument-runs", payload, headers)

    def list_instrument_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/instrument-runs", headers=headers, params=params)

    def get_instrument_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/instrument-runs/{run_id}", headers=headers)

    def abort_instrument_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/instrument-runs/{run_id}/abort", {}, headers)

    def rebook_instrument_run(self, run_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/instrument-runs/{run_id}", payload, headers)

    # --- interface builds ----------------------------------------------------
    def create_interface_build(self, payload, headers):
        return self._request("POST", f"{PREFIX}/interface-builds", payload, headers)

    def list_interface_builds(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/interface-builds", headers=headers, params=params)

    def get_interface_build(self, build_id, headers):
        return self._request("GET", f"{PREFIX}/interface-builds/{build_id}", headers=headers)

    def start_interface_build(self, build_id, headers):
        return self._request("POST", f"{PREFIX}/interface-builds/{build_id}/start-build", {}, headers)

    def certify_interface_build(self, build_id, headers):
        return self._request("POST", f"{PREFIX}/interface-builds/{build_id}/certify", {}, headers)

    def supersede_interface_build(self, build_id, headers):
        return self._request("POST", f"{PREFIX}/interface-builds/{build_id}/supersede", {}, headers)

    def retire_interface_build(self, build_id, headers):
        return self._request("POST", f"{PREFIX}/interface-builds/{build_id}/retire", {}, headers)

    def amend_interface_build(self, build_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/interface-builds/{build_id}", payload, headers)

    # --- result interface messages -------------------------------------------
    def create_interface_message(self, payload, headers):
        return self._request("POST", f"{PREFIX}/result-interface-messages", payload, headers)

    def list_interface_messages(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/result-interface-messages", headers=headers, params=params)

    def get_interface_message(self, message_id, headers):
        return self._request("GET", f"{PREFIX}/result-interface-messages/{message_id}", headers=headers)

    def validate_interface_message(self, message_id, headers):
        return self._request("POST", f"{PREFIX}/result-interface-messages/{message_id}/validate", {}, headers)

    def transmit_interface_message(self, message_id, headers):
        return self._request("POST", f"{PREFIX}/result-interface-messages/{message_id}/transmit", {}, headers)

    def fail_interface_message(self, message_id, headers):
        return self._request("POST", f"{PREFIX}/result-interface-messages/{message_id}/fail", {}, headers)

    def hold_interface_message(self, message_id, headers):
        return self._request("POST", f"{PREFIX}/result-interface-messages/{message_id}/hold", {}, headers)

    def release_hold_interface_message(self, message_id, headers):
        return self._request("POST", f"{PREFIX}/result-interface-messages/{message_id}/release-hold",
                             {}, headers)

    def acknowledge_interface_message(self, message_id, control_id, headers):
        return self._request("POST", f"{PREFIX}/result-interface-messages/{message_id}/acknowledge",
                             {"control_id": control_id}, headers)

    # --- billing ledgers -----------------------------------------------------
    def create_billing_ledger(self, payload, headers):
        return self._request("POST", f"{PREFIX}/billing-ledgers", payload, headers)

    def list_billing_ledgers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/billing-ledgers", headers=headers, params=params)

    def get_billing_ledger(self, ledger_id, headers):
        return self._request("GET", f"{PREFIX}/billing-ledgers/{ledger_id}", headers=headers)

    def void_charges(self, ledger_id, send_out_order_id, void_amount_cents, headers):
        return self._request("POST", f"{PREFIX}/billing-ledgers/{ledger_id}/void-charges",
                             {"send_out_order_id": send_out_order_id,
                              "void_amount_cents": void_amount_cents}, headers)

    # --- utilization advisories ----------------------------------------------
    def create_utilization_advisory(self, payload, headers):
        return self._request("POST", f"{PREFIX}/utilization-advisories", payload, headers)

    def list_utilization_advisories(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/utilization-advisories", headers=headers, params=params)

    def get_utilization_advisory(self, advisory_id, headers):
        return self._request("GET", f"{PREFIX}/utilization-advisories/{advisory_id}", headers=headers)

    def acknowledge_utilization_advisory(self, advisory_id, headers):
        return self._request("POST", f"{PREFIX}/utilization-advisories/{advisory_id}/acknowledge",
                             {}, headers)

    def dismiss_utilization_advisory(self, advisory_id, headers):
        return self._request("POST", f"{PREFIX}/utilization-advisories/{advisory_id}/dismiss",
                             {}, headers)

    def escalate_utilization_advisory(self, advisory_id, headers):
        return self._request("POST", f"{PREFIX}/utilization-advisories/{advisory_id}/escalate",
                             {}, headers)


api_client = ApiClient()