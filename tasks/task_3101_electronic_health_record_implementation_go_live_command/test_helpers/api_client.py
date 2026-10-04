"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, typed wrapper over the PRD's endpoint surface."""

    # ------------------------------------------------------------------
    # Implementation programs and the logical clock
    # ------------------------------------------------------------------
    def create_ehr_implementation(self, payload, headers):
        return self._request("POST", "/ehr-implementations", payload, headers)

    def list_ehr_implementations(self, headers, params=None):
        return self._request("GET", "/ehr-implementations", None, headers, params)

    def get_ehr_implementation(self, impl_id, headers, params=None):
        return self._request("GET", f"/ehr-implementations/{impl_id}", None, headers, params)

    def advance_epoch(self, impl_id, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/advance-epoch", None, headers)

    def start_build(self, impl_id, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/start-build", None, headers)

    def start_validation(self, impl_id, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/start-validation", None, headers)

    def finalize_validation(self, impl_id, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/finalize-validation", None, headers)

    def execute_go_live(self, impl_id, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/execute-go-live", None, headers)

    def activate_command_center(self, impl_id, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/activate-command-center", None, headers)

    def begin_optimization(self, impl_id, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/begin-optimization", None, headers)

    def archive_ehr_implementation(self, impl_id, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/archive", None, headers)

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Facilities
    # ------------------------------------------------------------------
    def create_facility(self, impl_id, payload, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/facilities", payload, headers)

    def list_program_facilities(self, impl_id, headers, params=None):
        return self._request("GET", f"/ehr-implementations/{impl_id}/facilities", None, headers, params)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", None, headers, params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", None, headers)

    def configure_build(self, facility_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/configure-build", None, headers)

    def mark_validated(self, facility_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/mark-validated", None, headers)

    def complete_cutover_dress_rehearsal(self, facility_id, headers):
        return self._request(
            "POST", f"/facilities/{facility_id}/complete-cutover-dress-rehearsal", None, headers
        )

    def stabilize_facility(self, facility_id, headers):
        return self._request("POST", f"/facilities/{facility_id}/stabilize", None, headers)

    # ------------------------------------------------------------------
    # Cutover tasks
    # ------------------------------------------------------------------
    def create_cutover_task(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/cutover-tasks", payload, headers)

    def list_facility_cutover_tasks(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/cutover-tasks", None, headers, params)

    def list_cutover_tasks(self, headers, params=None):
        return self._request("GET", "/cutover-tasks", None, headers, params)

    def get_cutover_task(self, task_id, headers):
        return self._request("GET", f"/cutover-tasks/{task_id}", None, headers)

    def start_cutover_task(self, task_id, headers):
        return self._request("POST", f"/cutover-tasks/{task_id}/start", None, headers)

    def complete_cutover_task(self, task_id, headers):
        return self._request("POST", f"/cutover-tasks/{task_id}/complete", None, headers)

    def skip_cutover_task(self, task_id, headers):
        return self._request("POST", f"/cutover-tasks/{task_id}/skip", None, headers)

    def block_cutover_task(self, task_id, payload, headers):
        return self._request("POST", f"/cutover-tasks/{task_id}/block", payload, headers)

    def unblock_cutover_task(self, task_id, headers):
        return self._request("POST", f"/cutover-tasks/{task_id}/unblock", None, headers)

    # ------------------------------------------------------------------
    # Departments
    # ------------------------------------------------------------------
    def create_department(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/departments", payload, headers)

    def list_facility_departments(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/departments", None, headers, params)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/departments", None, headers, params)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", None, headers)

    def complete_department_build(self, department_id, headers):
        return self._request("POST", f"/departments/{department_id}/complete-build", None, headers)

    def begin_training(self, department_id, headers):
        return self._request("POST", f"/departments/{department_id}/begin-training", None, headers)

    def close_proficiency_gate(self, department_id, headers):
        return self._request(
            "POST", f"/departments/{department_id}/close-proficiency-gate", None, headers
        )

    def list_department_optimization_items(self, department_id, headers, params=None):
        return self._request(
            "GET", f"/departments/{department_id}/optimization-backlog-items", None, headers, params
        )

    # ------------------------------------------------------------------
    # System build items
    # ------------------------------------------------------------------
    def create_build_item(self, department_id, payload, headers):
        return self._request("POST", f"/departments/{department_id}/system-build-items", payload, headers)

    def list_department_build_items(self, department_id, headers, params=None):
        return self._request(
            "GET", f"/departments/{department_id}/system-build-items", None, headers, params
        )

    def list_build_items(self, headers, params=None):
        return self._request("GET", "/system-build-items", None, headers, params)

    def get_build_item(self, item_id, headers):
        return self._request("GET", f"/system-build-items/{item_id}", None, headers)

    def start_build_item(self, item_id, headers):
        return self._request("POST", f"/system-build-items/{item_id}/start-build", None, headers)

    def complete_build_item(self, item_id, headers):
        return self._request("POST", f"/system-build-items/{item_id}/complete-build", None, headers)

    def start_testing(self, item_id, headers):
        return self._request("POST", f"/system-build-items/{item_id}/start-testing", None, headers)

    def complete_item_validation(self, item_id, headers):
        return self._request("POST", f"/system-build-items/{item_id}/complete-validation", None, headers)

    def rework_build_item(self, item_id, headers):
        return self._request("POST", f"/system-build-items/{item_id}/rework", None, headers)

    def reset_build_item_to_draft(self, item_id, headers):
        return self._request("POST", f"/system-build-items/{item_id}/reset-to-draft", None, headers)

    # ------------------------------------------------------------------
    # Staff
    # ------------------------------------------------------------------
    def create_staff(self, impl_id, payload, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/staffs", payload, headers)

    def list_program_staffs(self, impl_id, headers, params=None):
        return self._request("GET", f"/ehr-implementations/{impl_id}/staffs", None, headers, params)

    def list_staffs(self, headers, params=None):
        return self._request("GET", "/staffs", None, headers, params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staffs/{staff_id}", None, headers)

    def issue_credential(self, staff_id, headers):
        return self._request("POST", f"/staffs/{staff_id}/issue-credential", None, headers)

    def reassign_training(self, staff_id, headers):
        return self._request("POST", f"/staffs/{staff_id}/reassign-training", None, headers)

    # ------------------------------------------------------------------
    # Training assignments
    # ------------------------------------------------------------------
    def create_training_assignment(self, staff_id, payload, headers):
        return self._request("POST", f"/staffs/{staff_id}/training-assignments", payload, headers)

    def list_staff_assignments(self, staff_id, headers, params=None):
        return self._request("GET", f"/staffs/{staff_id}/training-assignments", None, headers, params)

    def list_training_assignments(self, headers, params=None):
        return self._request("GET", "/training-assignments", None, headers, params)

    def get_training_assignment(self, assignment_id, headers):
        return self._request("GET", f"/training-assignments/{assignment_id}", None, headers)

    def log_hours(self, assignment_id, payload, headers):
        return self._request("POST", f"/training-assignments/{assignment_id}/log-hours", payload, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"/training-assignments/{assignment_id}/complete", None, headers)

    def waive_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/training-assignments/{assignment_id}/waive", payload, headers)

    # ------------------------------------------------------------------
    # Credentialed trainers
    # ------------------------------------------------------------------
    def create_credentialed_trainer(self, staff_id, payload, headers):
        return self._request("POST", f"/staffs/{staff_id}/credentialed-trainers", payload, headers)

    def list_staff_trainers(self, staff_id, headers, params=None):
        return self._request("GET", f"/staffs/{staff_id}/credentialed-trainers", None, headers, params)

    def list_credentialed_trainers(self, headers, params=None):
        return self._request("GET", "/credentialed-trainers", None, headers, params)

    def get_credentialed_trainer(self, trainer_id, headers):
        return self._request("GET", f"/credentialed-trainers/{trainer_id}", None, headers)

    def certify_trainer(self, trainer_id, headers):
        return self._request("POST", f"/credentialed-trainers/{trainer_id}/certify", None, headers)

    def revoke_trainer(self, trainer_id, headers):
        return self._request("POST", f"/credentialed-trainers/{trainer_id}/revoke", None, headers)

    def recertify_trainer(self, trainer_id, headers):
        return self._request("POST", f"/credentialed-trainers/{trainer_id}/recertify", None, headers)

    # ------------------------------------------------------------------
    # Proficiency exams
    # ------------------------------------------------------------------
    def schedule_exam(self, staff_id, payload, headers):
        return self._request("POST", f"/staffs/{staff_id}/proficiency-exams", payload, headers)

    def list_staff_exams(self, staff_id, headers, params=None):
        return self._request("GET", f"/staffs/{staff_id}/proficiency-exams", None, headers, params)

    def list_proficiency_exams(self, headers, params=None):
        return self._request("GET", "/proficiency-exams", None, headers, params)

    def get_proficiency_exam(self, exam_id, headers):
        return self._request("GET", f"/proficiency-exams/{exam_id}", None, headers)

    def record_exam_result(self, exam_id, payload, headers):
        return self._request("POST", f"/proficiency-exams/{exam_id}/record-result", payload, headers)

    def mark_exam_no_show(self, exam_id, headers):
        return self._request("POST", f"/proficiency-exams/{exam_id}/mark-no-show", None, headers)

    # ------------------------------------------------------------------
    # Test scenarios
    # ------------------------------------------------------------------
    def create_test_scenario(self, item_id, payload, headers):
        return self._request("POST", f"/system-build-items/{item_id}/test-scenarios", payload, headers)

    def list_build_item_scenarios(self, item_id, headers, params=None):
        return self._request("GET", f"/system-build-items/{item_id}/test-scenarios", None, headers, params)

    def list_test_scenarios(self, headers, params=None):
        return self._request("GET", "/test-scenarios", None, headers, params)

    def get_test_scenario(self, scenario_id, headers):
        return self._request("GET", f"/test-scenarios/{scenario_id}", None, headers)

    def execute_scenario(self, scenario_id, payload, headers):
        return self._request("POST", f"/test-scenarios/{scenario_id}/execute", payload, headers)

    def reset_scenario(self, scenario_id, headers):
        return self._request("POST", f"/test-scenarios/{scenario_id}/reset", None, headers)

    def record_defect(self, scenario_id, payload, headers):
        return self._request("POST", f"/test-scenarios/{scenario_id}/record-defect", payload, headers)

    # ------------------------------------------------------------------
    # Test defects
    # ------------------------------------------------------------------
    def list_test_defects(self, headers, params=None):
        return self._request("GET", "/test-defects", None, headers, params)

    def get_test_defect(self, defect_id, headers):
        return self._request("GET", f"/test-defects/{defect_id}", None, headers)

    def begin_remediation(self, defect_id, headers):
        return self._request("POST", f"/test-defects/{defect_id}/begin-remediation", None, headers)

    def resolve_defect(self, defect_id, headers):
        return self._request("POST", f"/test-defects/{defect_id}/resolve", None, headers)

    def defer_defect(self, defect_id, headers):
        return self._request("POST", f"/test-defects/{defect_id}/defer", None, headers)

    def reopen_defect(self, defect_id, headers):
        return self._request("POST", f"/test-defects/{defect_id}/reopen", None, headers)

    # ------------------------------------------------------------------
    # Data conversion batches
    # ------------------------------------------------------------------
    def create_conversion_batch(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/data-conversion-batches", payload, headers)

    def list_facility_batches(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/data-conversion-batches", None, headers, params)

    def list_conversion_batches(self, headers, params=None):
        return self._request("GET", "/data-conversion-batches", None, headers, params)

    def get_conversion_batch(self, batch_id, headers):
        return self._request("GET", f"/data-conversion-batches/{batch_id}", None, headers)

    def begin_batch_validation(self, batch_id, headers):
        return self._request("POST", f"/data-conversion-batches/{batch_id}/begin-validation", None, headers)

    def load_batch(self, batch_id, headers):
        return self._request("POST", f"/data-conversion-batches/{batch_id}/load", None, headers)

    def reconcile_batch(self, batch_id, headers):
        return self._request("POST", f"/data-conversion-batches/{batch_id}/reconcile", None, headers)

    def rollback_batch(self, batch_id, headers):
        return self._request("POST", f"/data-conversion-batches/{batch_id}/rollback", None, headers)

    # ------------------------------------------------------------------
    # Patient orders
    # ------------------------------------------------------------------
    def create_patient_order(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/patient-orders", payload, headers)

    def list_facility_orders(self, facility_id, headers, params=None):
        return self._request("GET", f"/facilities/{facility_id}/patient-orders", None, headers, params)

    def list_patient_orders(self, headers, params=None):
        return self._request("GET", "/patient-orders", None, headers, params)

    def get_patient_order(self, order_id, headers):
        return self._request("GET", f"/patient-orders/{order_id}", None, headers)

    def reconcile_order(self, order_id, headers):
        return self._request("POST", f"/patient-orders/{order_id}/reconcile", None, headers)

    def backfill_paper_order(self, order_id, headers):
        return self._request("POST", f"/patient-orders/{order_id}/backfill-paper-order", None, headers)

    def post_charge(self, order_id, headers):
        return self._request("POST", f"/patient-orders/{order_id}/post-charge", None, headers)

    def submit_claim(self, order_id, headers):
        return self._request("POST", f"/patient-orders/{order_id}/submit-claim", None, headers)

    def record_claim_response(self, order_id, payload, headers):
        return self._request("POST", f"/patient-orders/{order_id}/record-claim-response", payload, headers)

    def reopen_claim(self, order_id, headers):
        return self._request("POST", f"/patient-orders/{order_id}/reopen-claim", None, headers)

    # ------------------------------------------------------------------
    # Interface channels
    # ------------------------------------------------------------------
    def create_interface_channel(self, impl_id, payload, headers):
        return self._request("POST", f"/ehr-implementations/{impl_id}/interface-channels", payload, headers)

    def list_program_channels(self, impl_id, headers, params=None):
        return self._request("GET", f"/ehr-implementations/{impl_id}/interface-channels", None, headers, params)

    def list_interface_channels(self, headers, params=None):
        return self._request("GET", "/interface-channels", None, headers, params)

    def get_interface_channel(self, channel_id, headers):
        return self._request("GET", f"/interface-channels/{channel_id}", None, headers)

    def begin_channel_build(self, channel_id, headers):
        return self._request("POST", f"/interface-channels/{channel_id}/begin-build", None, headers)

    def begin_message_validation(self, channel_id, headers):
        return self._request("POST", f"/interface-channels/{channel_id}/begin-validation", None, headers)

    def complete_channel_validation(self, channel_id, headers):
        return self._request("POST", f"/interface-channels/{channel_id}/complete-validation", None, headers)

    def return_channel_to_build(self, channel_id, headers):
        return self._request("POST", f"/interface-channels/{channel_id}/return-to-build", None, headers)

    # ------------------------------------------------------------------
    # Interface messages
    # ------------------------------------------------------------------
    def receive_message(self, channel_id, payload, headers):
        return self._request("POST", f"/interface-channels/{channel_id}/messages", payload, headers)

    def list_channel_messages(self, channel_id, headers, params=None):
        return self._request("GET", f"/interface-channels/{channel_id}/messages", None, headers, params)

    def list_interface_messages(self, headers, params=None):
        return self._request("GET", "/interface-messages", None, headers, params)

    def get_interface_message(self, message_id, headers):
        return self._request("GET", f"/interface-messages/{message_id}", None, headers)

    def validate_message(self, message_id, headers):
        return self._request("POST", f"/interface-messages/{message_id}/validate", None, headers)

    # ------------------------------------------------------------------
    # Command-center tickets
    # ------------------------------------------------------------------
    def create_ticket(self, payload, headers):
        return self._request("POST", "/command-center-tickets", payload, headers)

    def list_command_center_tickets(self, headers, params=None):
        return self._request("GET", "/command-center-tickets", None, headers, params)

    def get_command_center_ticket(self, ticket_id, headers):
        return self._request("GET", f"/command-center-tickets/{ticket_id}", None, headers)

    def triage_ticket(self, ticket_id, headers):
        return self._request("POST", f"/command-center-tickets/{ticket_id}/triage", None, headers)

    def begin_ticket_resolution(self, ticket_id, headers):
        return self._request("POST", f"/command-center-tickets/{ticket_id}/begin-resolution", None, headers)

    def resolve_ticket(self, ticket_id, headers):
        return self._request("POST", f"/command-center-tickets/{ticket_id}/resolve", None, headers)

    # ------------------------------------------------------------------
    # Staffing shifts
    # ------------------------------------------------------------------
    def create_shift(self, payload, headers):
        return self._request("POST", "/staffing-shifts", payload, headers)

    def list_staffing_shifts(self, headers, params=None):
        return self._request("GET", "/staffing-shifts", None, headers, params)

    def get_staffing_shift(self, shift_id, headers):
        return self._request("GET", f"/staffing-shifts/{shift_id}", None, headers)

    def activate_shift(self, shift_id, headers):
        return self._request("POST", f"/staffing-shifts/{shift_id}/activate", None, headers)

    def complete_shift(self, shift_id, headers):
        return self._request("POST", f"/staffing-shifts/{shift_id}/complete", None, headers)

    def reassign_shift(self, shift_id, headers):
        return self._request("POST", f"/staffing-shifts/{shift_id}/reassign", None, headers)

    # ------------------------------------------------------------------
    # Optimization backlog
    # ------------------------------------------------------------------
    def create_optimization_item(self, payload, headers):
        return self._request("POST", "/optimization-backlog-items", payload, headers)

    def list_optimization_items(self, headers, params=None):
        return self._request("GET", "/optimization-backlog-items", None, headers, params)

    def get_optimization_item(self, item_id, headers):
        return self._request("GET", f"/optimization-backlog-items/{item_id}", None, headers)

    def triage_optimization_item(self, item_id, headers):
        return self._request("POST", f"/optimization-backlog-items/{item_id}/triage", None, headers)

    def schedule_optimization_item(self, item_id, payload, headers):
        return self._request("POST", f"/optimization-backlog-items/{item_id}/schedule", payload, headers)

    def start_optimization_item(self, item_id, headers):
        return self._request("POST", f"/optimization-backlog-items/{item_id}/start", None, headers)

    def release_optimization_item(self, item_id, headers):
        return self._request("POST", f"/optimization-backlog-items/{item_id}/release", None, headers)

    def reject_optimization_item(self, item_id, headers):
        return self._request("POST", f"/optimization-backlog-items/{item_id}/reject", None, headers)


api_client = ApiClient()