"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Capacity expansion projects -----------------------------------------
    def create_expansion_project(self, payload, headers):
        return self._request("POST", "/barrel-aging/expansion-projects", payload, headers)

    def get_expansion_project(self, project_id, headers):
        return self._request("GET", f"/barrel-aging/expansion-projects/{project_id}", headers=headers)

    def approve_expansion_project(self, project_id, headers):
        return self._request("POST", f"/barrel-aging/expansion-projects/{project_id}/approve", headers=headers)

    def commission_expansion_project(self, project_id, headers):
        return self._request("POST", f"/barrel-aging/expansion-projects/{project_id}/commission", headers=headers)

    # --- Rickhouses / warehouse slots -----------------------------------------
    def get_rickhouse(self, rickhouse_id, headers):
        return self._request("GET", f"/barrel-aging/rickhouses/{rickhouse_id}", headers=headers)

    def list_rickhouses(self, headers, params=None):
        return self._request("GET", "/barrel-aging/rickhouses", headers=headers, params=params)

    def list_rickhouse_slots(self, rickhouse_id, headers, params=None):
        return self._request("GET", f"/barrel-aging/rickhouses/{rickhouse_id}/slots", headers=headers, params=params)

    def get_warehouse_slot(self, slot_id, headers):
        return self._request("GET", f"/barrel-aging/warehouse-slots/{slot_id}", headers=headers)

    def list_slot_occupancies(self, slot_id, headers, params=None):
        return self._request("GET", f"/barrel-aging/warehouse-slots/{slot_id}/occupancies", headers=headers, params=params)

    # --- Barrels ----------------------------------------------------------------
    def create_barrel(self, payload, headers):
        return self._request("POST", "/barrel-aging/barrels", payload, headers)

    def get_barrel(self, barrel_id, headers):
        return self._request("GET", f"/barrel-aging/barrels/{barrel_id}", headers=headers)

    def list_barrels(self, headers, params=None):
        return self._request("GET", "/barrel-aging/barrels", headers=headers, params=params)

    def list_barrel_occupancies(self, barrel_id, headers, params=None):
        return self._request("GET", f"/barrel-aging/barrels/{barrel_id}/occupancies", headers=headers, params=params)

    def list_barrel_blend_components(self, barrel_id, headers, params=None):
        return self._request("GET", f"/barrel-aging/barrels/{barrel_id}/blend-components", headers=headers, params=params)

    def list_barrel_reservations(self, barrel_id, headers, params=None):
        return self._request("GET", f"/barrel-aging/barrels/{barrel_id}/reservations", headers=headers, params=params)

    def list_barrel_assessments(self, barrel_id, headers, params=None):
        return self._request("GET", f"/barrel-aging/barrels/{barrel_id}/assessments", headers=headers, params=params)

    def create_barrel_assessment(self, barrel_id, payload, headers):
        return self._request("POST", f"/barrel-aging/barrels/{barrel_id}/assessments", payload, headers)

    def rotate_barrel(self, barrel_id, payload, headers):
        return self._request("POST", f"/barrel-aging/barrels/{barrel_id}/rotations", payload, headers)

    def dump_barrel(self, barrel_id, headers):
        return self._request("POST", f"/barrel-aging/barrels/{barrel_id}/dump", headers=headers)

    def withdraw_barrel(self, barrel_id, headers):
        return self._request("POST", f"/barrel-aging/barrels/{barrel_id}/withdraw", headers=headers)

    # --- Labels -------------------------------------------------------------------
    def create_label(self, payload, headers):
        return self._request("POST", "/barrel-aging/labels", payload, headers)

    def get_label(self, label_id, headers):
        return self._request("GET", f"/barrel-aging/labels/{label_id}", headers=headers)

    def activate_label(self, label_id, headers):
        return self._request("POST", f"/barrel-aging/labels/{label_id}/activate", headers=headers)

    # --- Blend batches --------------------------------------------------------------
    def create_blend_batch(self, payload, headers):
        return self._request("POST", "/barrel-aging/blend-batches", payload, headers)

    def get_blend_batch(self, batch_id, headers):
        return self._request("GET", f"/barrel-aging/blend-batches/{batch_id}", headers=headers)

    def list_blend_batches(self, headers, params=None):
        return self._request("GET", "/barrel-aging/blend-batches", headers=headers, params=params)

    def add_blend_component(self, batch_id, payload, headers):
        return self._request("POST", f"/barrel-aging/blend-batches/{batch_id}/components", payload, headers)

    def list_blend_components(self, batch_id, headers, params=None):
        return self._request("GET", f"/barrel-aging/blend-batches/{batch_id}/components", headers=headers, params=params)

    def validate_blend_batch(self, batch_id, headers):
        return self._request("POST", f"/barrel-aging/blend-batches/{batch_id}/validate", headers=headers)

    def revise_blend_batch(self, batch_id, headers):
        return self._request("POST", f"/barrel-aging/blend-batches/{batch_id}/revise", headers=headers)

    def commit_blend_batch(self, batch_id, headers):
        return self._request("POST", f"/barrel-aging/blend-batches/{batch_id}/commit", headers=headers)

    def abort_blend_batch(self, batch_id, headers):
        return self._request("POST", f"/barrel-aging/blend-batches/{batch_id}/abort", headers=headers)

    # --- Private selection programs ----------------------------------------------------
    def create_private_selection_program(self, payload, headers):
        return self._request("POST", "/barrel-aging/private-selection-programs", payload, headers)

    def get_private_selection_program(self, program_id, headers):
        return self._request("GET", f"/barrel-aging/private-selection-programs/{program_id}", headers=headers)

    def list_eligible_barrels(self, program_id, headers, params=None):
        return self._request("GET", f"/barrel-aging/private-selection-programs/{program_id}/eligible-barrels", headers=headers, params=params)

    def create_reservation(self, program_id, payload, headers):
        return self._request("POST", f"/barrel-aging/private-selection-programs/{program_id}/reservations", payload, headers)

    def list_program_reservations(self, program_id, headers, params=None):
        return self._request("GET", f"/barrel-aging/private-selection-programs/{program_id}/reservations", headers=headers, params=params)

    def consume_reservation(self, reservation_id, headers):
        return self._request("POST", f"/barrel-aging/reservations/{reservation_id}/consume", headers=headers)

    def release_reservation(self, reservation_id, headers):
        return self._request("POST", f"/barrel-aging/reservations/{reservation_id}/release", headers=headers)

    # --- Bonded period reports ------------------------------------------------------------
    def create_bonded_report(self, payload, headers):
        return self._request("POST", "/barrel-aging/bonded-reports", payload, headers)

    def get_bonded_report(self, report_id, headers):
        return self._request("GET", f"/barrel-aging/bonded-reports/{report_id}", headers=headers)

    def list_bonded_reports(self, headers, params=None):
        return self._request("GET", "/barrel-aging/bonded-reports", headers=headers, params=params)

    def reconcile_bonded_report(self, report_id, headers):
        return self._request("POST", f"/barrel-aging/bonded-reports/{report_id}/reconcile", headers=headers)

    def file_bonded_report(self, report_id, headers):
        return self._request("POST", f"/barrel-aging/bonded-reports/{report_id}/file", headers=headers)

    def accept_bonded_report(self, report_id, headers):
        return self._request("POST", f"/barrel-aging/bonded-reports/{report_id}/accept", headers=headers)

    def reject_bonded_report(self, report_id, headers):
        return self._request("POST", f"/barrel-aging/bonded-reports/{report_id}/reject", headers=headers)

    def amend_bonded_report(self, report_id, headers):
        return self._request("POST", f"/barrel-aging/bonded-reports/{report_id}/amend", headers=headers)


api_client = ApiClient()
