"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the /blood-bank prefix per the PRD endpoint table.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/blood-bank"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and maintenance sweep (supervisor-only, test-driving)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def sweep(self, headers):
        return self._request("POST", f"{PREFIX}/_clock/sweep", {}, headers)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"{PREFIX}/patients/{patient_id}", headers=headers)

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"{PREFIX}/suppliers/{supplier_id}", headers=headers)

    def suspend_supplier(self, supplier_id, payload, headers):
        return self._request("POST", f"{PREFIX}/suppliers/{supplier_id}/suspend",
                             payload, headers)

    def reinstate_supplier(self, supplier_id, headers):
        return self._request("POST", f"{PREFIX}/suppliers/{supplier_id}/reinstate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Supplier orders
    # ------------------------------------------------------------------
    def create_supplier_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/supplier-orders", payload, headers)

    def list_supplier_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/supplier-orders", headers=headers,
                             params=params)

    def get_supplier_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/supplier-orders/{order_id}",
                             headers=headers)

    def submit_supplier_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/supplier-orders/{order_id}/submit",
                             {}, headers)

    def acknowledge_supplier_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/supplier-orders/{order_id}/acknowledge",
                             {}, headers)

    def receive_supplier_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/supplier-orders/{order_id}/receive",
                             payload, headers)

    def close_supplier_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/supplier-orders/{order_id}/close",
                             {}, headers)

    def cancel_supplier_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/supplier-orders/{order_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Blood units
    # ------------------------------------------------------------------
    def list_blood_units(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/blood-units", headers=headers,
                             params=params)

    def get_blood_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/blood-units/{unit_id}", headers=headers)

    def release_unit_from_quarantine(self, unit_id, headers):
        return self._request("POST",
                             f"{PREFIX}/blood-units/{unit_id}/release-from-quarantine",
                             {}, headers)

    def reject_unit_intake(self, unit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/blood-units/{unit_id}/reject-intake",
                             payload, headers)

    def discard_unit(self, unit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/blood-units/{unit_id}/discard",
                             payload, headers)

    # ------------------------------------------------------------------
    # Type & screens
    # ------------------------------------------------------------------
    def create_type_and_screen(self, payload, headers):
        return self._request("POST", f"{PREFIX}/type-and-screens", payload, headers)

    def list_type_and_screens(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/type-and-screens", headers=headers,
                             params=params)

    def get_type_and_screen(self, ts_id, headers):
        return self._request("GET", f"{PREFIX}/type-and-screens/{ts_id}", headers=headers)

    def result_type_and_screen(self, ts_id, payload, headers):
        return self._request("POST", f"{PREFIX}/type-and-screens/{ts_id}/result",
                             payload, headers)

    def validate_type_and_screen(self, ts_id, headers):
        return self._request("POST", f"{PREFIX}/type-and-screens/{ts_id}/validate",
                             {}, headers)

    def reject_specimen(self, ts_id, payload, headers):
        return self._request("POST", f"{PREFIX}/type-and-screens/{ts_id}/reject-specimen",
                             payload, headers)

    # ------------------------------------------------------------------
    # Transfusion orders
    # ------------------------------------------------------------------
    def create_transfusion_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transfusion-orders", payload, headers)

    def list_transfusion_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/transfusion-orders", headers=headers,
                             params=params)

    def get_transfusion_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/transfusion-orders/{order_id}",
                             headers=headers)

    def verify_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/transfusion-orders/{order_id}/verify",
                             {}, headers)

    def reject_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/transfusion-orders/{order_id}/reject",
                             payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/transfusion-orders/{order_id}/cancel",
                             payload, headers)

    def reactivate_order(self, order_id, headers):
        return self._request("POST",
                             f"{PREFIX}/transfusion-orders/{order_id}/reactivate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Crossmatches
    # ------------------------------------------------------------------
    def create_crossmatch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/crossmatches", payload, headers)

    def list_crossmatches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/crossmatches", headers=headers,
                             params=params)

    def get_crossmatch(self, crossmatch_id, headers):
        return self._request("GET", f"{PREFIX}/crossmatches/{crossmatch_id}",
                             headers=headers)

    def record_crossmatch_result(self, crossmatch_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/crossmatches/{crossmatch_id}/record-result",
                             payload, headers)

    def cancel_crossmatch(self, crossmatch_id, headers):
        return self._request("POST", f"{PREFIX}/crossmatches/{crossmatch_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Issue records
    # ------------------------------------------------------------------
    def create_issue_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/issue-records", payload, headers)

    def list_issue_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/issue-records", headers=headers,
                             params=params)

    def get_issue_record(self, issue_id, headers):
        return self._request("GET", f"{PREFIX}/issue-records/{issue_id}", headers=headers)

    def start_transfusion(self, issue_id, headers):
        return self._request("POST",
                             f"{PREFIX}/issue-records/{issue_id}/start-transfusion",
                             {}, headers)

    def complete_transfusion(self, issue_id, headers):
        return self._request("POST",
                             f"{PREFIX}/issue-records/{issue_id}/complete-transfusion",
                             {}, headers)

    def return_issue(self, issue_id, payload, headers):
        return self._request("POST", f"{PREFIX}/issue-records/{issue_id}/return",
                             payload, headers)

    def stop_transfusion(self, issue_id, headers):
        return self._request("POST",
                             f"{PREFIX}/issue-records/{issue_id}/stop-transfusion",
                             {}, headers)

    def acknowledge_emergency(self, issue_id, headers):
        return self._request("POST",
                             f"{PREFIX}/issue-records/{issue_id}/acknowledge-emergency",
                             {}, headers)

    # ------------------------------------------------------------------
    # Massive transfusion protocol
    # ------------------------------------------------------------------
    def create_mtp_activation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mtp-activations", payload, headers)

    def list_mtp_activations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/mtp-activations", headers=headers,
                             params=params)

    def get_mtp_activation(self, mtp_id, headers):
        return self._request("GET", f"{PREFIX}/mtp-activations/{mtp_id}", headers=headers)

    def dispatch_pack(self, mtp_id, payload, headers):
        return self._request("POST", f"{PREFIX}/mtp-activations/{mtp_id}/dispatch-pack",
                             payload, headers)

    def stand_down_mtp(self, mtp_id, headers):
        return self._request("POST", f"{PREFIX}/mtp-activations/{mtp_id}/stand-down",
                             {}, headers)

    def deactivate_mtp(self, mtp_id, headers):
        return self._request("POST", f"{PREFIX}/mtp-activations/{mtp_id}/deactivate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Transfusion reactions
    # ------------------------------------------------------------------
    def create_transfusion_reaction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transfusion-reactions", payload, headers)

    def list_transfusion_reactions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/transfusion-reactions", headers=headers,
                             params=params)

    def get_transfusion_reaction(self, reaction_id, headers):
        return self._request("GET", f"{PREFIX}/transfusion-reactions/{reaction_id}",
                             headers=headers)

    def begin_investigation(self, reaction_id, headers):
        return self._request(
            "POST", f"{PREFIX}/transfusion-reactions/{reaction_id}/begin-investigation",
            {}, headers)

    def record_workup(self, reaction_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transfusion-reactions/{reaction_id}/record-workup",
            payload, headers)

    def conclude_reaction(self, reaction_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transfusion-reactions/{reaction_id}/conclude",
            payload, headers)

    def close_reaction(self, reaction_id, headers):
        return self._request(
            "POST", f"{PREFIX}/transfusion-reactions/{reaction_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Recall / look-back
    # ------------------------------------------------------------------
    def create_recall_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/recall-cases", payload, headers)

    def list_recall_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/recall-cases", headers=headers,
                             params=params)

    def get_recall_case(self, recall_id, headers):
        return self._request("GET", f"{PREFIX}/recall-cases/{recall_id}", headers=headers)

    def identify_recall_units(self, recall_id, headers):
        return self._request("POST", f"{PREFIX}/recall-cases/{recall_id}/identify-units",
                             {}, headers)

    def execute_recall_quarantine(self, recall_id, headers):
        return self._request(
            "POST", f"{PREFIX}/recall-cases/{recall_id}/execute-quarantine", {}, headers)

    def record_recall_notification(self, recall_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/recall-cases/{recall_id}/record-notification",
            payload, headers)

    def complete_recall_notifications(self, recall_id, headers):
        return self._request(
            "POST", f"{PREFIX}/recall-cases/{recall_id}/complete-notifications",
            {}, headers)

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"{PREFIX}/recall-cases/{recall_id}/close",
                             {}, headers)

    def void_recall(self, recall_id, headers):
        return self._request("POST", f"{PREFIX}/recall-cases/{recall_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Wastage
    # ------------------------------------------------------------------
    def list_wastage_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/wastage-records", headers=headers,
                             params=params)

    def get_wastage_record(self, record_id, headers):
        return self._request("GET", f"{PREFIX}/wastage-records/{record_id}",
                             headers=headers)

    def get_wastage_summary(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/wastage-summary", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Par-level policies / shortage posture
    # ------------------------------------------------------------------
    def create_par_level_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/par-level-policies", payload, headers)

    def list_par_level_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/par-level-policies", headers=headers,
                             params=params)

    def get_par_level_policy(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/par-level-policies/{policy_id}",
                             headers=headers)

    def update_par_level_policy(self, policy_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/par-level-policies/{policy_id}",
                             payload, headers)

    def retire_policy(self, policy_id, headers):
        return self._request("POST", f"{PREFIX}/par-level-policies/{policy_id}/retire",
                             {}, headers)

    def get_policy_posture(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/par-level-policies/{policy_id}/posture",
                             headers=headers)

    # ------------------------------------------------------------------
    # Transport coolers and checkouts
    # ------------------------------------------------------------------
    def create_cooler(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coolers", payload, headers)

    def list_coolers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coolers", headers=headers, params=params)

    def get_cooler(self, cooler_id, headers):
        return self._request("GET", f"{PREFIX}/coolers/{cooler_id}", headers=headers)

    def create_cooler_checkout(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cooler-checkouts", payload, headers)

    def list_cooler_checkouts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cooler-checkouts", headers=headers,
                             params=params)

    def get_cooler_checkout(self, checkout_id, headers):
        return self._request("GET", f"{PREFIX}/cooler-checkouts/{checkout_id}",
                             headers=headers)

    def return_cooler_checkout(self, checkout_id, headers):
        return self._request("POST", f"{PREFIX}/cooler-checkouts/{checkout_id}/return",
                             {}, headers)


api_client = ApiClient()
