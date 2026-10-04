"""API client: one method per endpoint declared by the PRD.

Every method delegates to the framework's `_request()` and returns the raw
`requests.Response` so tests can assert status codes and error ids.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───────────────────────────────────────────────────────
    def set_current_utc(self, to_iso8601: str, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Hospital accounts ───────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/api/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def close_account(self, account_id, payload, headers):
        return self._request("POST", f"/api/accounts/{account_id}/close", payload, headers)

    def reactivate_account(self, account_id, payload, headers):
        return self._request("POST", f"/api/households/{account_id}/reactivate", payload, headers)

    def activate_account_readiness(self, review_id, payload, headers):
        return self._request("POST", f"/api/account-readiness-reviews/{review_id}/activate",
                             payload, headers)

    # ─── Site readiness ──────────────────────────────────────────────────────
    def create_readiness_review(self, account_id, payload, headers):
        return self._request("POST", f"/api/accounts/{account_id}/readiness-reviews",
                             payload, headers)

    def list_account_readiness_reviews(self, account_id, headers, params=None):
        return self._request("GET", f"/api/accounts/{account_id}/readiness-reviews",
                             headers=headers, params=params)

    def list_readiness_reviews(self, headers, params=None):
        return self._request("GET", "/api/account-readiness-reviews", headers=headers, params=params)

    def get_readiness_review(self, review_id, headers):
        return self._request("GET", f"/api/account-readiness-reviews/{review_id}", headers=headers)

    def submit_readiness_verdict(self, review_id, payload, headers):
        return self._request("POST", f"/api/account-readiness-reviews/{review_id}/submit-verdict",
                             payload, headers)

    def reject_readiness_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/account-readiness-reviews/{review_id}/reject",
                             payload, headers)

    def return_readiness_review_to_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/account-readiness-reviews/{review_id}/return-to-review",
                             payload, headers)

    def submit_readiness_check(self, review_id, payload, headers):
        return self._request("POST", f"/api/account-readiness-reviews/{review_id}/readiness-checks",
                             payload, headers)

    # ─── System configurations ───────────────────────────────────────────────
    def create_configuration(self, payload, headers):
        return self._request("POST", "/api/system-configurations", payload, headers)

    def list_configurations(self, headers, params=None):
        return self._request("GET", "/api/system-configurations", headers=headers, params=params)

    def get_configuration(self, config_id, headers):
        return self._request("GET", f"/api/system-configurations/{config_id}", headers=headers)

    def update_configuration(self, config_id, payload, headers):
        return self._request("PUT", f"/api/system-configurations/{config_id}", payload, headers)

    # ─── Placement agreements ────────────────────────────────────────────────
    def create_agreement(self, payload, headers):
        return self._request("POST", "/api/placement-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/api/placement-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/placement-agreements/{agreement_id}", headers=headers)

    def submit_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/placement-agreements/{agreement_id}/submit",
                             payload, headers)

    def accept_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/placement-agreements/{agreement_id}/accept",
                             payload, headers)

    def suspend_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/placement-agreements/{agreement_id}/suspend",
                             payload, headers)

    def reinstate_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/placement-agreements/{agreement_id}/reinstate",
                             payload, headers)

    def reject_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/placement-agreements/{agreement_id}/reject",
                             payload, headers)

    def terminate_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/placement-agreements/{agreement_id}/terminate",
                             payload, headers)

    def waive_shortfall(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/placement-agreements/{agreement_id}/waive-shortfall",
                             payload, headers)

    def list_account_agreements(self, account_id, headers, params=None):
        return self._request("GET", f"/api/accounts/{account_id}/placement-agreements",
                             headers=headers, params=params)

    # ─── Robot systems ───────────────────────────────────────────────────────
    def list_robot_systems(self, headers, params=None):
        return self._request("GET", "/api/robot-systems", headers=headers, params=params)

    def get_robot_system(self, system_id, headers):
        return self._request("GET", f"/api/robot-systems/{system_id}", headers=headers)

    def list_agreement_robot_systems(self, agreement_id, headers, params=None):
        return self._request("GET", f"/api/placement-agreements/{agreement_id}/robot-systems",
                             headers=headers, params=params)

    def list_account_robot_systems(self, account_id, headers, params=None):
        return self._request("GET", f"/api/accounts/{account_id}/robot-systems",
                             headers=headers, params=params)

    def install_robot_system(self, system_id, payload, headers):
        return self._request("POST", f"/api/robot-systems/{system_id}/install", payload, headers)

    def commission_robot_system(self, system_id, payload, headers):
        return self._request("POST", f"/api/robot-systems/{system_id}/commission", payload, headers)

    def open_service_action(self, system_id, payload, headers):
        return self._request("POST", f"/api/robot-systems/{system_id}/open-service-action",
                             payload, headers)

    def restore_system_service(self, system_id, payload, headers):
        return self._request("POST", f"/api/robot-systems/{system_id}/restore-service",
                             payload, headers)

    def decommission_robot_system(self, system_id, payload, headers):
        return self._request("POST", f"/api/robot-systems/{system_id}/decommission",
                             payload, headers)

    def decrement_instrument_lives(self, system_id, payload, headers):
        return self._request("POST", f"/api/robot-systems/{system_id}/instrument-lives/decrement",
                             payload, headers)

    def reset_instrument_lives(self, system_id, payload, headers):
        return self._request("POST", f"/api/robot-systems/{system_id}/instrument-lives/reset",
                             payload, headers)

    # ─── Software ────────────────────────────────────────────────────────────
    def create_software_release(self, config_id, payload, headers):
        return self._request("POST", f"/api/system-configurations/{config_id}/releases",
                             payload, headers)

    def list_software_releases(self, headers, params=None):
        return self._request("GET", "/api/software-releases", headers=headers, params=params)

    def list_configuration_releases(self, config_id, headers, params=None):
        return self._request("GET", f"/api/system-configurations/{config_id}/software-releases",
                             headers=headers, params=params)

    def get_software_release(self, release_id, headers):
        return self._request("GET", f"/api/software-releases/{release_id}", headers=headers)

    def create_software_deployment(self, system_id, payload, headers):
        return self._request("POST", f"/api/robot-systems/{system_id}/software-deployments",
                             payload, headers)

    def list_system_software_deployments(self, system_id, headers, params=None):
        return self._request("GET", f"/api/robot-systems/{system_id}/software-deployments",
                             headers=headers, params=params)

    def get_software_deployment(self, deployment_id, headers):
        return self._request("GET", f"/api/software-deployments/{deployment_id}", headers=headers)

    def complete_software_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"/api/software-deployments/{deployment_id}/complete",
                             payload, headers)

    def list_software_deployments(self, headers, params=None):
        return self._request("GET", "/api/software-deployments", headers=headers, params=params)

    # ─── Utilization cycles ──────────────────────────────────────────────────
    def list_system_utilization_cycles(self, system_id, headers, params=None):
        return self._request("GET", f"/api/robot-systems/{system_id}/utilization-cycles",
                             headers=headers, params=params)

    def get_current_utilization_cycle(self, system_id, headers):
        return self._request("GET", f"/api/robot-systems/{system_id}/current-utilization-cycle",
                             headers=headers)

    def list_utilization_cycles(self, headers, params=None):
        return self._request("GET", "/api/utilization-cycles", headers=headers, params=params)

    def get_utilization_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/utilization-cycles/{cycle_id}", headers=headers)

    def list_agreement_utilization_cycles(self, agreement_id, headers, params=None):
        return self._request("GET", f"/api/placement-agreements/{agreement_id}/utilization-cycles",
                             headers=headers, params=params)

    def run_month_close(self, headers, payload=None):
        return self._request("POST", "/api/month-close/runs", payload or {}, headers)

    # ─── Procedure cases ─────────────────────────────────────────────────────
    def create_procedure_case(self, system_id, payload, headers):
        return self._request("POST", f"/api/robot-systems/{system_id}/procedure-cases",
                             payload, headers)

    def list_procedure_cases(self, headers, params=None):
        return self._request("GET", "/api/procedure-cases", headers=headers, params=params)

    def get_procedure_case(self, case_id, headers):
        return self._request("GET", f"/api/procedure-cases/{case_id}", headers=headers)

    def list_system_procedure_cases(self, system_id, headers, params=None):
        return self._request("GET", f"/api/robot-systems/{system_id}/procedure-cases",
                             headers=headers, params=params)

    def reschedule_procedure_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/procedure-cases/{case_id}/reschedule",
                             payload, headers)

    def mark_case_completed(self, case_id, payload, headers):
        return self._request("POST", f"/api/procedure-cases/{case_id}/mark-completed",
                             payload, headers)

    def bulk_complete_cases(self, payload, headers):
        return self._request("POST", "/api/procedure-cases/bulk-complete", payload, headers)

    def cancel_procedure_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/procedure-cases/{case_id}/cancel", payload, headers)

    # ─── Surgeons, training and credentialing ────────────────────────────────
    def create_training_record(self, account_id, payload, headers):
        return self._request("POST", f"/api/accounts/{account_id}/training-records",
                             payload, headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/api/training-records", headers=headers, params=params)

    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/api/training-records/{record_id}", headers=headers)

    def list_account_training_records(self, account_id, headers, params=None):
        return self._request("GET", f"/api/accounts/{account_id}/training-records",
                             headers=headers, params=params)

    def complete_simulation(self, record_id, payload, headers):
        return self._request("POST", f"/api/training-records/{record_id}/complete-simulation",
                             payload, headers)

    def begin_proctoring(self, record_id, payload, headers):
        return self._request("POST", f"/api/training-records/{record_id}/begin-proctoring",
                             payload, headers)

    def log_proctor_case(self, record_id, payload, headers):
        return self._request("POST", f"/api/training-records/{record_id}/proctor-cases",
                             payload, headers)

    def approve_proctor_case(self, proctor_case_id, payload, headers):
        return self._request("POST", f"/api/proctor-cases/{proctor_case_id}/approve",
                             payload, headers)

    def reject_proctor_case(self, proctor_case_id, payload, headers):
        return self._request("POST", f"/api/proctor-cases/{proctor_case_id}/reject",
                             payload, headers)

    def create_credentialing_evidence(self, record_id, payload, headers):
        return self._request("POST", f"/api/training-records/{record_id}/credentialing-evidence",
                             payload, headers)

    def list_record_evidence(self, record_id, headers, params=None):
        return self._request("GET", f"/api/training-records/{record_id}/credentialing-evidence",
                             headers=headers, params=params)

    def list_credentialing_evidence(self, headers, params=None):
        return self._request("GET", "/api/credentialing-evidence", headers=headers, params=params)

    def get_credentialing_evidence(self, evidence_id, headers):
        return self._request("GET", f"/api/credentialing-evidence/{evidence_id}", headers=headers)

    def renew_credentialing_evidence(self, evidence_id, payload, headers):
        return self._request("POST", f"/api/credentialing-evidence/{evidence_id}/renew",
                             payload, headers)

    def revoke_credentialing_evidence(self, evidence_id, payload, headers):
        return self._request("POST", f"/api/credentialing-evidence/{evidence_id}/revoke",
                             payload, headers)

    def trigger_reevaluation(self, record_id, payload, headers):
        return self._request("POST", f"/api/training-records/{record_id}/trigger-reevaluation",
                             payload, headers)

    # ─── Service coverage, incidents and loaners ─────────────────────────────
    def create_service_contract(self, payload, headers):
        return self._request("POST", "/api/service-contracts", payload, headers)

    def list_service_contracts(self, headers, params=None):
        return self._request("GET", "/api/service-contracts", headers=headers, params=params)

    def get_service_contract(self, contract_id, headers):
        return self._request("GET", f"/api/service-contracts/{contract_id}", headers=headers)

    def list_system_service_contracts(self, system_id, headers, params=None):
        return self._request("GET", f"/api/robot-systems/{system_id}/service-contracts",
                             headers=headers, params=params)

    def terminate_service_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/api/service-contracts/{contract_id}/terminate",
                             payload, headers)

    def create_incident(self, payload, headers):
        return self._request("POST", "/api/incident-service-requests", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/api/incident-service-requests", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/api/incident-service-requests/{incident_id}", headers=headers)

    def list_system_incidents(self, system_id, headers, params=None):
        return self._request("GET", f"/api/robot-systems/{system_id}/incident-service-requests",
                             headers=headers, params=params)

    def acknowledge_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/api/incident-service-requests/{incident_id}/acknowledge",
                             payload, headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/api/incident-service-requests/{incident_id}/resolve",
                             payload, headers)

    def create_loaner_dispatch(self, payload, headers):
        return self._request("POST", "/api/loaner-dispatches", payload, headers)

    def list_loaner_dispatches(self, headers, params=None):
        return self._request("GET", "/api/loaner-dispatches", headers=headers, params=params)

    def get_loaner_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/api/loaner-dispatches/{dispatch_id}", headers=headers)

    def list_system_loaner_dispatches(self, system_id, headers, params=None):
        return self._request("GET", f"/api/robot-systems/{system_id}/loaner-dispatches",
                             headers=headers, params=params)

    def activate_loaner_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/api/loaner-dispatches/{dispatch_id}/activate",
                             payload, headers)

    # ─── Expansion reviews ───────────────────────────────────────────────────
    def create_expansion_review(self, payload, headers):
        return self._request("POST", "/api/expansion-reviews", payload, headers)

    def list_expansion_reviews(self, headers, params=None):
        return self._request("GET", "/api/expansion-reviews", headers=headers, params=params)

    def get_expansion_review(self, review_id, headers):
        return self._request("GET", f"/api/expansion-reviews/{review_id}", headers=headers)

    def list_account_expansion_reviews(self, account_id, headers, params=None):
        return self._request("GET", f"/api/accounts/{account_id}/expansion-reviews",
                             headers=headers, params=params)

    def submit_expansion_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/expansion-reviews/{review_id}/submit",
                             payload, headers)

    def approve_expansion_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/expansion-reviews/{review_id}/approve",
                             payload, headers)

    def reject_expansion_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/expansion-reviews/{review_id}/reject",
                             payload, headers)

    # ─── IDN utilisation credit pool ─────────────────────────────────────────
    def create_consumption_ledger(self, account_id, payload, headers):
        return self._request("POST", f"/api/accounts/{account_id}/consumption-ledgers",
                             payload, headers)

    def list_consumption_ledgers(self, headers, params=None):
        return self._request("GET", "/api/utilisation-consumption-ledgers",
                             headers=headers, params=params)

    def get_consumption_ledger(self, ledger_id, headers):
        return self._request("GET", f"/api/utilisation-consumption-ledgers/{ledger_id}",
                             headers=headers)

    def list_account_transfers(self, account_id, headers, params=None):
        return self._request("GET", f"/api/accounts/{account_id}/utilisation-transfer-transactions",
                             headers=headers, params=params)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/api/utilisation-transfer-transactions",
                             headers=headers, params=params)

    def get_transfer(self, transaction_id, headers):
        return self._request("GET", f"/api/utilisation-transfer-transactions/{transaction_id}",
                             headers=headers)

    def create_transfer(self, payload, headers):
        return self._request("POST", "/api/utilisation-transfer-transactions", payload, headers)

    def settle_transfer(self, transaction_id, payload, headers):
        return self._request("POST",
                             f"/api/utilisation-transfer-transactions/{transaction_id}/settle",
                             payload, headers)

    def reverse_transfer(self, transaction_id, payload, headers):
        return self._request("POST",
                             f"/api/utilisation-transfer-transactions/{transaction_id}/reverse",
                             payload, headers)

    def bootstrap_decrement_ledger(self, ledger_id, payload, headers):
        return self._request("POST",
                             f"/api/utilisation-consumption-ledgers/{ledger_id}/bootstrap-decrement",
                             payload, headers)


api_client = ApiClient()