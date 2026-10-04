"""API client: one method per endpoint exposed by the Corridor Operations API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ──────────────────────────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Ledger checkpoints ─────────────────────────────────────────────────
    def create_ledger_checkpoint(self, payload, headers):
        return self._request("POST", "/api/ledger-checkpoints", payload, headers)

    def list_ledger_checkpoints(self, headers, params=None):
        return self._request("GET", "/api/ledger-checkpoints", headers=headers, params=params)

    def get_ledger_checkpoint(self, checkpoint_id, headers):
        return self._request("GET", f"/api/ledger-checkpoints/{checkpoint_id}", headers=headers)

    def adopt_ledger_checkpoint(self, checkpoint_id, headers, payload=None):
        return self._request("POST", f"/api/ledger-checkpoints/{checkpoint_id}/adopt",
                             payload or {}, headers)

    def roll_over_ledger_checkpoint(self, checkpoint_id, headers, payload=None):
        return self._request("POST", f"/api/ledger-checkpoints/{checkpoint_id}/roll-over",
                             payload or {}, headers)

    # ─── Terminals ──────────────────────────────────────────────────────────
    def create_terminal(self, payload, headers):
        return self._request("POST", "/api/terminals", payload, headers)

    def list_terminals(self, headers, params=None):
        return self._request("GET", "/api/terminals", headers=headers, params=params)

    def get_terminal(self, terminal_id, headers):
        return self._request("GET", f"/api/terminals/{terminal_id}", headers=headers)

    def operate_terminal(self, terminal_id, headers, payload=None):
        return self._request("POST", f"/api/terminals/{terminal_id}/operate",
                             payload or {}, headers)

    def list_terminal_corridors(self, terminal_id, headers, params=None):
        return self._request("GET", f"/api/terminals/{terminal_id}/corridors",
                             headers=headers, params=params)

    def list_terminal_driver_prospects(self, terminal_id, headers, params=None):
        return self._request("GET", f"/api/terminals/{terminal_id}/driver-prospects",
                             headers=headers, params=params)

    def list_terminal_driver_transitions(self, terminal_id, headers, params=None):
        return self._request("GET", f"/api/terminals/{terminal_id}/driver-transitions",
                             headers=headers, params=params)

    def list_terminal_run_plans(self, terminal_id, headers, params=None):
        return self._request("GET", f"/api/terminals/{terminal_id}/run-plans",
                             headers=headers, params=params)

    def list_terminal_fleet_units(self, terminal_id, headers, params=None):
        return self._request("GET", f"/api/terminals/{terminal_id}/fleet-units",
                             headers=headers, params=params)

    def list_terminal_security_records(self, terminal_id, headers, params=None):
        return self._request("GET", f"/api/terminals/{terminal_id}/security-records",
                             headers=headers, params=params)

    # ─── State authorities ──────────────────────────────────────────────────
    def create_state_authority(self, payload, headers):
        return self._request("POST", "/api/state-authorities", payload, headers)

    def list_state_authorities(self, headers, params=None):
        return self._request("GET", "/api/state-authorities", headers=headers, params=params)

    def get_state_authority(self, authority_id, headers):
        return self._request("GET", f"/api/state-authorities/{authority_id}", headers=headers)

    def list_state_authority_engagements(self, authority_id, headers, params=None):
        return self._request("GET", f"/api/state-authorities/{authority_id}/regulatory-engagements",
                             headers=headers, params=params)

    # ─── Carriers ───────────────────────────────────────────────────────────
    def create_carrier(self, payload, headers):
        return self._request("POST", "/api/carriers", payload, headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/api/carriers", headers=headers, params=params)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/api/carriers/{carrier_id}", headers=headers)

    def list_carrier_incident_reports(self, carrier_id, headers, params=None):
        return self._request("GET", f"/api/carriers/{carrier_id}/incident-reports",
                             headers=headers, params=params)

    def list_carrier_run_plans(self, carrier_id, headers, params=None):
        return self._request("GET", f"/api/carriers/{carrier_id}/run-plans",
                             headers=headers, params=params)

    def list_backup_carriers(self, carrier_id, headers, params=None):
        return self._request("GET", f"/api/carriers/{carrier_id}/backup-carriers",
                             headers=headers, params=params)

    def activate_carrier(self, carrier_id, headers, payload=None):
        return self._request("POST", f"/api/carriers/{carrier_id}/activate",
                             payload or {}, headers)

    def reinstate_carrier(self, carrier_id, headers, payload=None):
        return self._request("POST", f"/api/carriers/{carrier_id}/reinstate",
                             payload or {}, headers)

    def offboard_carrier(self, carrier_id, headers, payload=None):
        return self._request("POST", f"/api/carriers/{carrier_id}/offboard",
                             payload or {}, headers)

    # ─── Corridors ──────────────────────────────────────────────────────────
    def create_corridor(self, payload, headers):
        return self._request("POST", "/api/corridors", payload, headers)

    def list_corridors(self, headers, params=None):
        return self._request("GET", "/api/corridors", headers=headers, params=params)

    def get_corridor(self, corridor_id, headers):
        return self._request("GET", f"/api/corridors/{corridor_id}", headers=headers)

    def start_launch_readiness(self, corridor_id, headers, payload=None):
        return self._request("POST", f"/api/corridors/{corridor_id}/launch-readiness/start",
                             payload or {}, headers)

    def validate_launch_readiness(self, corridor_id, headers, payload):
        return self._request("POST", f"/api/corridors/{corridor_id}/launch-readiness/validate",
                             payload, headers)

    def fail_launch_readiness(self, corridor_id, headers, payload=None):
        return self._request("POST", f"/api/corridors/{corridor_id}/launch-readiness/fail",
                             payload or {}, headers)

    def retire_corridor(self, corridor_id, headers, payload=None):
        return self._request("POST", f"/api/corridors/{corridor_id}/retire",
                             payload or {}, headers)

    def list_corridor_checks(self, corridor_id, headers, params=None):
        return self._request("GET", f"/api/corridors/{corridor_id}/launch-readiness-checks",
                             headers=headers, params=params)

    def list_corridor_state_authorities(self, corridor_id, headers, params=None):
        return self._request("GET", f"/api/corridors/{corridor_id}/state-authorities",
                             headers=headers, params=params)

    def get_corridor_state_authority(self, corridor_id, authority_id, headers):
        return self._request("GET",
                             f"/api/corridors/{corridor_id}/state-authorities/{authority_id}",
                             headers=headers)

    def list_corridor_run_plans(self, corridor_id, headers, params=None):
        return self._request("GET", f"/api/corridors/{corridor_id}/run-plans",
                             headers=headers, params=params)

    def list_corridor_safety_cases(self, corridor_id, headers, params=None):
        return self._request("GET", f"/api/corridors/{corridor_id}/safety-cases",
                             headers=headers, params=params)

    def list_corridor_incident_reports(self, corridor_id, headers, params=None):
        return self._request("GET", f"/api/corridors/{corridor_id}/incident-reports",
                             headers=headers, params=params)

    def list_corridor_engagements(self, corridor_id, headers, params=None):
        return self._request("GET", f"/api/corridors/{corridor_id}/regulatory-engagements",
                             headers=headers, params=params)

    def list_corridor_remote_support(self, corridor_id, headers, params=None):
        return self._request("GET", f"/api/corridors/{corridor_id}/remote-support-assignments",
                             headers=headers, params=params)

    # ─── Launch readiness checks ────────────────────────────────────────────
    def create_readiness_check(self, corridor_id, payload, headers):
        return self._request("POST", f"/api/corridors/{corridor_id}/launch-readiness-checks",
                             payload, headers)

    def list_readiness_checks(self, headers, params=None):
        return self._request("GET", "/api/launch-readiness-checks", headers=headers, params=params)

    def get_readiness_check(self, check_id, headers):
        return self._request("GET", f"/api/launch-readiness-checks/{check_id}", headers=headers)

    def calibrate_check(self, check_id, headers, payload=None):
        return self._request("POST", f"/api/launch-readiness-checks/{check_id}/calibrate",
                             payload or {}, headers)

    def validate_check(self, check_id, headers, payload):
        return self._request("POST", f"/api/launch-readiness-checks/{check_id}/validate",
                             payload, headers)

    def expire_check(self, check_id, headers, payload=None):
        return self._request("POST", f"/api/launch-readiness-checks/{check_id}/expire",
                             payload or {}, headers)

    # ─── Driver prospects / transitions ─────────────────────────────────────
    def create_driver_prospect(self, payload, headers):
        return self._request("POST", "/api/driver-prospects", payload, headers)

    def list_driver_prospects(self, headers, params=None):
        return self._request("GET", "/api/driver-prospects", headers=headers, params=params)

    def get_driver_prospect(self, prospect_id, headers):
        return self._request("GET", f"/api/driver-prospects/{prospect_id}", headers=headers)

    def list_prospect_transitions(self, prospect_id, headers, params=None):
        return self._request("GET", f"/api/driver-prospects/{prospect_id}/driver-transitions",
                             headers=headers, params=params)

    def list_prospect_run_plans(self, prospect_id, headers, params=None):
        return self._request("GET", f"/api/driver-prospects/{prospect_id}/run-plans",
                             headers=headers, params=params)

    def list_prospect_remote_support(self, prospect_id, headers, params=None):
        return self._request("GET",
                             f"/api/driver-prospects/{prospect_id}/remote-support-assignments",
                             headers=headers, params=params)

    def create_driver_transition(self, payload, headers):
        return self._request("POST", "/api/driver-transitions", payload, headers)

    def list_driver_transitions(self, headers, params=None):
        return self._request("GET", "/api/driver-transitions", headers=headers, params=params)

    def get_driver_transition(self, transition_id, headers):
        return self._request("GET", f"/api/driver-transitions/{transition_id}", headers=headers)

    def list_transition_haulers(self, transition_id, headers, params=None):
        return self._request("GET", f"/api/driver-transitions/{transition_id}/haulers",
                             headers=headers, params=params)

    def ride_along_transition(self, transition_id, payload, headers):
        return self._request("POST", f"/api/driver-transitions/{transition_id}/ride-along",
                             payload, headers)

    def credential_lapse_transition(self, transition_id, headers, payload=None):
        return self._request("POST", f"/api/driver-transitions/{transition_id}/credential-lapse",
                             payload or {}, headers)

    def cancel_transition(self, transition_id, headers, payload=None):
        return self._request("POST", f"/api/driver-transitions/{transition_id}/cancel",
                             payload or {}, headers)

    # ─── Safety cases ───────────────────────────────────────────────────────
    def create_safety_case(self, payload, headers):
        return self._request("POST", "/api/safety-cases", payload, headers)

    def list_safety_cases(self, headers, params=None):
        return self._request("GET", "/api/safety-cases", headers=headers, params=params)

    def get_safety_case(self, case_id, headers):
        return self._request("GET", f"/api/safety-cases/{case_id}", headers=headers)

    def submit_safety_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/api/safety-cases/{case_id}/submit",
                             payload or {}, headers)

    def file_safety_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/safety-cases/{case_id}/file", payload, headers)

    # ─── Run plans ──────────────────────────────────────────────────────────
    def create_run_plan(self, payload, headers):
        return self._request("POST", "/api/run-plans", payload, headers)

    def list_run_plans(self, headers, params=None):
        return self._request("GET", "/api/run-plans", headers=headers, params=params)

    def get_run_plan(self, run_plan_id, headers):
        return self._request("GET", f"/api/run-plans/{run_plan_id}", headers=headers)

    def submit_run_plan(self, run_plan_id, headers, payload=None):
        return self._request("POST", f"/api/run-plans/{run_plan_id}/submit",
                             payload or {}, headers)

    def dispatch_ready_run_plan(self, run_plan_id, headers, payload):
        return self._request("POST", f"/api/run-plans/{run_plan_id}/dispatch-ready",
                             payload, headers)

    def requeue_run_plan(self, run_plan_id, headers, payload=None):
        return self._request("POST", f"/api/run-plans/{run_plan_id}/requeue",
                             payload or {}, headers)

    def abort_run_plan(self, run_plan_id, headers, payload=None):
        return self._request("POST", f"/api/run-plans/{run_plan_id}/abort",
                             payload or {}, headers)

    def start_highway_segment(self, run_plan_id, headers, payload=None):
        return self._request("POST", f"/api/run-plans/{run_plan_id}/start-highway-segment",
                             payload or {}, headers)

    def complete_run_plan(self, run_plan_id, headers, payload=None):
        return self._request("POST", f"/api/run-plans/{run_plan_id}/complete",
                             payload or {}, headers)

    def safe_stop_run_plan(self, run_plan_id, headers, payload=None):
        return self._request("POST", f"/api/run-plans/{run_plan_id}/safe-stop",
                             payload or {}, headers)

    def attach_chassis(self, run_plan_id, payload, headers):
        return self._request("POST", f"/api/run-plans/{run_plan_id}/chassis", payload, headers)

    def list_chassis(self, run_plan_id, headers, params=None):
        return self._request("GET", f"/api/run-plans/{run_plan_id}/chassis",
                             headers=headers, params=params)

    def recompute_chassis(self, chassis_id, headers, payload=None):
        return self._request("POST", f"/api/run-plan-chassis/{chassis_id}/recompute",
                             payload or {}, headers)

    def list_run_plan_checks(self, run_plan_id, headers, params=None):
        return self._request("GET", f"/api/run-plans/{run_plan_id}/launch-readiness-checks",
                             headers=headers, params=params)

    def list_run_plan_service_windows(self, run_plan_id, headers, params=None):
        return self._request("GET", f"/api/run-plans/{run_plan_id}/service-windows",
                             headers=headers, params=params)

    def list_run_plan_incident_reports(self, run_plan_id, headers, params=None):
        return self._request("GET", f"/api/run-plans/{run_plan_id}/incident-reports",
                             headers=headers, params=params)

    def list_run_plan_instructions(self, run_plan_id, headers, params=None):
        return self._request("GET", f"/api/run-plans/{run_plan_id}/shipping-instructions",
                             headers=headers, params=params)

    def list_run_plan_haulers(self, run_plan_id, headers, params=None):
        return self._request("GET", f"/api/run-plans/{run_plan_id}/haulers",
                             headers=headers, params=params)

    # ─── Shipping instructions / container units ────────────────────────────
    def create_shipping_instruction(self, payload, headers):
        return self._request("POST", "/api/shipping-instructions", payload, headers)

    def list_shipping_instructions(self, headers, params=None):
        return self._request("GET", "/api/shipping-instructions", headers=headers, params=params)

    def get_shipping_instruction(self, instruction_id, headers):
        return self._request("GET", f"/api/shipping-instructions/{instruction_id}",
                             headers=headers)

    def place_holds(self, instruction_id, payload, headers):
        return self._request("POST", f"/api/shipping-instructions/{instruction_id}/place-holds",
                             payload, headers)

    def cancel_holds(self, instruction_id, payload, headers):
        return self._request("POST", f"/api/shipping-instructions/{instruction_id}/cancel-holds",
                             payload, headers)

    def verify_vgm(self, instruction_id, payload, headers):
        return self._request("POST", f"/api/shipping-instructions/{instruction_id}/verify-vgm",
                             payload, headers)

    def complete_carriage(self, instruction_id, headers, payload=None):
        return self._request("POST", f"/api/shipping-instructions/{instruction_id}/complete-carriage",
                             payload or {}, headers)

    def reject_instruction(self, instruction_id, payload, headers):
        return self._request("POST", f"/api/shipping-instructions/{instruction_id}/reject",
                             payload, headers)

    def list_container_units(self, headers, params=None):
        return self._request("GET", "/api/container-units", headers=headers, params=params)

    def get_container_unit(self, unit_id, headers):
        return self._request("GET", f"/api/container-units/{unit_id}", headers=headers)

    def gate_in_container(self, unit_id, headers, payload=None):
        return self._request("POST", f"/api/container-units/{unit_id}/gate-in",
                             payload or {}, headers)

    def load_container(self, unit_id, headers, payload=None):
        return self._request("POST", f"/api/container-units/{unit_id}/load",
                             payload or {}, headers)

    def discharge_container(self, unit_id, headers, payload=None):
        return self._request("POST", f"/api/container-units/{unit_id}/discharge",
                             payload or {}, headers)

    def offload_container(self, unit_id, headers, payload=None):
        return self._request("POST", f"/api/container-units/{unit_id}/offload",
                             payload or {}, headers)

    def gate_out_container(self, unit_id, headers, payload=None):
        return self._request("POST", f"/api/container-units/{unit_id}/gate-out",
                             payload or {}, headers)

    # ─── Shipper commitments ────────────────────────────────────────────────
    def create_shipper_commitment(self, payload, headers):
        return self._request("POST", "/api/shipper-commitments", payload, headers)

    def list_shipper_commitments(self, headers, params=None):
        return self._request("GET", "/api/shipper-commitments", headers=headers, params=params)

    def get_shipper_commitment(self, commitment_id, headers):
        return self._request("GET", f"/api/shipper-commitments/{commitment_id}", headers=headers)

    def confirm_shipper_commitment(self, commitment_id, headers, payload=None):
        return self._request("POST", f"/api/shipper-commitments/{commitment_id}/confirm",
                             payload or {}, headers)

    def revoke_shipper_commitment(self, commitment_id, headers, payload=None):
        return self._request("POST", f"/api/shipper-commitments/{commitment_id}/revoke",
                             payload or {}, headers)

    # ─── Terminal service windows ───────────────────────────────────────────
    def create_service_window(self, terminal_id, payload, headers):
        return self._request("POST", f"/api/terminals/{terminal_id}/service-windows",
                             payload, headers)

    def list_service_windows(self, terminal_id, headers, params=None):
        return self._request("GET", f"/api/terminals/{terminal_id}/service-windows",
                             headers=headers, params=params)

    def get_service_window(self, terminal_id, window_id, headers):
        return self._request("GET", f"/api/terminals/{terminal_id}/service-windows/{window_id}",
                             headers=headers)

    def approve_service_window(self, window_id, headers, payload=None):
        return self._request("POST", f"/api/terminal-service-windows/{window_id}/approve",
                             payload or {}, headers)

    def cancel_service_window(self, window_id, headers, payload=None):
        return self._request("POST", f"/api/terminal-service-windows/{window_id}/cancel",
                             payload or {}, headers)

    def complete_handoff(self, window_id, headers, payload=None):
        return self._request("POST", f"/api/terminal-service-windows/{window_id}/complete-handoff",
                             payload or {}, headers)

    # ─── Remote support assignments ─────────────────────────────────────────
    def create_remote_support_assignment(self, payload, headers):
        return self._request("POST", "/api/remote-support-assignments", payload, headers)

    def list_remote_support_assignments(self, headers, params=None):
        return self._request("GET", "/api/remote-support-assignments", headers=headers, params=params)

    def get_remote_support_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/remote-support-assignments/{assignment_id}",
                             headers=headers)

    def acknowledge_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST",
                             f"/api/remote-support-assignments/{assignment_id}/acknowledge",
                             payload or {}, headers)

    def release_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/api/remote-support-assignments/{assignment_id}/release",
                             payload or {}, headers)

    def log_intervention(self, assignment_id, payload, headers):
        return self._request("POST",
                             f"/api/remote-support-assignments/{assignment_id}/interventions",
                             payload, headers)

    # ─── Incident reports ───────────────────────────────────────────────────
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/api/incident-reports", payload, headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/api/incident-reports", headers=headers, params=params)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/api/incident-reports/{incident_id}", headers=headers)

    def investigate_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/api/incident-reports/{incident_id}/investigate",
                             payload or {}, headers)

    def corrective_action_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/api/incident-reports/{incident_id}/corrective-action",
                             payload, headers)

    def close_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/api/incident-reports/{incident_id}/close",
                             payload or {}, headers)

    def submit_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/api/incident-reports/{incident_id}/submit",
                             payload or {}, headers)

    def reopen_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/api/incident-reports/{incident_id}/reopen",
                             payload or {}, headers)

    # ─── Maintenance programs ───────────────────────────────────────────────
    def create_maintenance_program(self, payload, headers):
        return self._request("POST", "/api/maintenance-programs", payload, headers)

    def list_maintenance_programs(self, headers, params=None):
        return self._request("GET", "/api/maintenance-programs", headers=headers, params=params)

    def get_maintenance_program(self, program_id, headers):
        return self._request("GET", f"/api/maintenance-programs/{program_id}", headers=headers)

    def list_fleet_unit_programs(self, fleet_unit_id, headers, params=None):
        return self._request("GET", f"/api/fleet-units/{fleet_unit_id}/maintenance-programs",
                             headers=headers, params=params)

    def schedule_maintenance_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/api/maintenance-programs/{program_id}/schedule",
                             payload or {}, headers)

    def record_inspection(self, program_id, payload, headers):
        return self._request("POST", f"/api/maintenance-programs/{program_id}/record-inspection",
                             payload, headers)

    def reschedule_maintenance_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/api/maintenance-programs/{program_id}/reschedule",
                             payload or {}, headers)

    def void_maintenance_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/api/maintenance-programs/{program_id}/void",
                             payload or {}, headers)

    def close_maintenance_program(self, program_id, headers, payload=None):
        return self._request("POST", f"/api/maintenance-programs/{program_id}/close",
                             payload or {}, headers)

    # ─── Regulatory engagements ─────────────────────────────────────────────
    def create_regulatory_engagement(self, payload, headers):
        return self._request("POST", "/api/regulatory-engagements", payload, headers)

    def list_regulatory_engagements(self, headers, params=None):
        return self._request("GET", "/api/regulatory-engagements", headers=headers, params=params)

    def get_regulatory_engagement(self, engagement_id, headers):
        return self._request("GET", f"/api/regulatory-engagements/{engagement_id}",
                             headers=headers)

    def submit_engagement(self, engagement_id, headers, payload=None):
        return self._request("POST", f"/api/regulatory-engagements/{engagement_id}/submit",
                             payload or {}, headers)

    def accept_engagement(self, engagement_id, headers, payload=None):
        return self._request("POST", f"/api/regulatory-engagements/{engagement_id}/accept",
                             payload or {}, headers)

    def reject_engagement(self, engagement_id, headers, payload=None):
        return self._request("POST", f"/api/regulatory-engagements/{engagement_id}/reject",
                             payload or {}, headers)

    # ─── Multi-day holds ────────────────────────────────────────────────────
    def create_multi_day_hold(self, payload, headers):
        return self._request("POST", "/api/multi-day-holds", payload, headers)

    def list_multi_day_holds(self, headers, params=None):
        return self._request("GET", "/api/multi-day-holds", headers=headers, params=params)

    def get_multi_day_hold(self, hold_id, headers):
        return self._request("GET", f"/api/multi-day-holds/{hold_id}", headers=headers)

    def bulk_insert_holds(self, payload, headers):
        return self._request("POST", "/api/multi-day-holds/bulk-insert", payload, headers)

    def remove_multi_day_hold(self, hold_id, headers, payload=None):
        return self._request("POST", f"/api/multi-day-holds/{hold_id}/remove",
                             payload or {}, headers)

    def decline_multi_day_hold(self, hold_id, headers, payload=None):
        return self._request("POST", f"/api/multi-day-holds/{hold_id}/decline",
                             payload or {}, headers)

    # ─── Fleet units ────────────────────────────────────────────────────────
    def create_fleet_unit(self, payload, headers):
        return self._request("POST", "/api/fleet-units", payload, headers)

    def list_fleet_units(self, headers, params=None):
        return self._request("GET", "/api/fleet-units", headers=headers, params=params)

    def get_fleet_unit(self, fleet_unit_id, headers):
        return self._request("GET", f"/api/fleet-units/{fleet_unit_id}", headers=headers)

    def post_operational_hours(self, fleet_unit_id, payload, headers):
        return self._request("POST", f"/api/fleet-units/{fleet_unit_id}/post-operational-hours",
                             payload, headers)

    def post_route_driven_hours(self, fleet_unit_id, payload, headers):
        return self._request("POST",
                             f"/api/fleet-units/{fleet_unit_id}/route-driven-operational-hours",
                             payload, headers)

    def clear_watch_squad(self, fleet_unit_id, headers, payload=None):
        return self._request("POST", f"/api/fleet-units/{fleet_unit_id}/clear-watch-squad",
                             payload or {}, headers)

    # ─── Security records ───────────────────────────────────────────────────
    def create_security_record(self, payload, headers):
        return self._request("POST", "/api/security-records", payload, headers)

    def list_security_records(self, headers, params=None):
        return self._request("GET", "/api/security-records", headers=headers, params=params)

    def get_security_record(self, record_id, headers):
        return self._request("GET", f"/api/security-records/{record_id}", headers=headers)

    def consignor_roll(self, record_id, headers, payload=None):
        return self._request("POST", f"/api/security-records/{record_id}/consignor-roll",
                             payload or {}, headers)

    def route_security_record(self, record_id, payload, headers):
        return self._request("POST", f"/api/security-records/{record_id}/route", payload, headers)

    def clamp_security_record(self, record_id, headers, payload=None):
        return self._request("POST", f"/api/security-records/{record_id}/clamp",
                             payload or {}, headers)

    def outbound_vessel_roll(self, record_id, payload, headers):
        return self._request("POST", f"/api/security-records/{record_id}/outbound-vessel-roll",
                             payload, headers)

    def mark_security_reporting(self, record_id, payload, headers):
        return self._request("POST", f"/api/security-records/{record_id}/reporting",
                             payload, headers)

    # ─── Clause variants ────────────────────────────────────────────────────
    def create_clause_variant(self, payload, headers):
        return self._request("POST", "/api/clause-variants", payload, headers)

    def list_clause_variants(self, headers, params=None):
        return self._request("GET", "/api/clause-variants", headers=headers, params=params)

    def get_clause_variant(self, variant_id, headers):
        return self._request("GET", f"/api/clause-variants/{variant_id}", headers=headers)

    def elect_clause_variant(self, variant_id, headers, payload=None):
        return self._request("POST", f"/api/clause-variants/{variant_id}/elect",
                             payload or {}, headers)

    def decline_clause_variant(self, variant_id, payload, headers):
        return self._request("POST", f"/api/clause-variants/{variant_id}/decline",
                             payload, headers)

    # ─── Agreement codes ────────────────────────────────────────────────────
    def create_agreement_code(self, payload, headers):
        return self._request("POST", "/api/agreement-codes", payload, headers)

    def list_agreement_codes(self, headers, params=None):
        return self._request("GET", "/api/agreement-codes", headers=headers, params=params)

    def get_agreement_code(self, agreement_id, headers):
        return self._request("GET", f"/api/agreement-codes/{agreement_id}", headers=headers)

    def execute_agreement_code(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/agreement-codes/{agreement_id}/execute",
                             payload, headers)

    # ─── Test-driving capabilities ──────────────────────────────────────────
    def simulate_vehicle_routing_i2(self, payload, headers):
        return self._request("POST", "/_testing/simulate-vehicle-routing/I2", payload, headers)

    def simulate_vehicle_routing_i5(self, payload, headers):
        return self._request("POST", "/_testing/simulate-vehicle-routing/I5", payload, headers)

    def simulate_ring_maintenance_i5(self, payload, headers):
        return self._request("POST", "/_testing/simulate-ring-maintenance/I5", payload, headers)


api_client = ApiClient()