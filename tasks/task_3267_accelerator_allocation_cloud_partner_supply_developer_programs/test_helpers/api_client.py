"""API client: one method per endpoint declared in the PRD, all under /accelerators."""
from prd_bench_local_runner.testing import GenericApiClient

P = "/accelerators"


class ApiClient(GenericApiClient):
    # --- logical clock / epoch ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{P}/_clock/set_current_utc", payload, headers)

    def advance_epoch(self, headers, payload=None):
        return self._request("POST", f"{P}/_ops/advance_epoch", payload or {}, headers)

    def close_epoch(self, epoch_id, headers, payload=None):
        return self._request("POST", f"{P}/epochs/{epoch_id}/close", payload or {}, headers)

    # --- accelerator catalog ---
    def create_product(self, payload, headers):
        return self._request("POST", f"{P}/allocations", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{P}/allocations", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{P}/allocations/{product_id}", headers=headers)

    def update_product(self, product_id, payload, headers):
        return self._request("PUT", f"{P}/allocations/{product_id}", payload, headers)

    def advance_product_lifecycle(self, product_id, headers, payload=None):
        return self._request("POST", f"{P}/allocations/{product_id}/advance_lifecycle",
                             payload or {}, headers)

    def promote_evaluation_pool(self, product_id, payload, headers):
        return self._request("POST", f"{P}/allocations/{product_id}/promote_evaluation_pool",
                             payload, headers)

    # --- supply nodes ---
    def create_supply_node(self, payload, headers):
        return self._request("POST", f"{P}/supply-nodes", payload, headers)

    def list_supply_nodes(self, headers, params=None):
        return self._request("GET", f"{P}/supply-nodes", headers=headers, params=params)

    def get_supply_node(self, node_id, headers):
        return self._request("GET", f"{P}/supply-nodes/{node_id}", headers=headers)

    def rank_supply_node(self, node_id, headers, payload=None):
        return self._request("POST", f"{P}/supply-nodes/{node_id}/rank", payload or {}, headers)

    def set_supply_node_stage(self, node_id, payload, headers):
        return self._request("POST", f"{P}/supply-nodes/{node_id}/stage", payload, headers)

    def drain_supply_node(self, node_id, headers, payload=None):
        return self._request("POST", f"{P}/supply-nodes/{node_id}/drain", payload or {}, headers)

    def bind_supply_node(self, node_id, headers, payload=None):
        return self._request("POST", f"{P}/supply-nodes/{node_id}/bind", payload or {}, headers)

    # --- partners ---
    def create_partner(self, payload, headers):
        return self._request("POST", f"{P}/partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"{P}/partners/{partner_id}", headers=headers)

    def list_partner_audit_entries(self, partner_id, headers, params=None):
        return self._request("GET", f"{P}/partners/{partner_id}/audit-entries",
                             headers=headers, params=params)

    def create_validation(self, partner_id, payload, headers):
        return self._request("POST", f"{P}/partners/{partner_id}/validations", payload, headers)

    def qualify_partner(self, partner_id, headers, payload=None):
        return self._request("POST", f"{P}/partners/{partner_id}/qualify", payload or {}, headers)

    def reject_partner(self, partner_id, headers, payload=None):
        return self._request("POST", f"{P}/partners/{partner_id}/reject", payload or {}, headers)

    def suspend_partner(self, partner_id, headers, payload=None):
        return self._request("POST", f"{P}/partners/{partner_id}/suspend", payload or {}, headers)

    def reinstate_partner(self, partner_id, headers, payload=None):
        return self._request("POST", f"{P}/partners/{partner_id}/reinstate", payload or {}, headers)

    def terminate_partner(self, partner_id, headers, payload=None):
        return self._request("POST", f"{P}/partners/{partner_id}/terminate", payload or {}, headers)

    def reapply_partner(self, partner_id, headers, payload=None):
        return self._request("POST", f"{P}/partners/{partner_id}/reapply", payload or {}, headers)

    # --- blueprints / evidence ---
    def create_blueprint(self, payload, headers):
        return self._request("POST", f"{P}/blueprints", payload, headers)

    def get_blueprint(self, blueprint_id, headers):
        return self._request("GET", f"{P}/blueprints/{blueprint_id}", headers=headers)

    def certify_blueprint(self, blueprint_id, headers, payload=None):
        return self._request("POST", f"{P}/blueprints/{blueprint_id}/certify",
                             payload or {}, headers)

    def retire_blueprint(self, blueprint_id, headers, payload=None):
        return self._request("POST", f"{P}/blueprints/{blueprint_id}/retire",
                             payload or {}, headers)

    def list_validations(self, headers, params=None):
        return self._request("GET", f"{P}/validations", headers=headers, params=params)

    def get_validation(self, evidence_id, headers):
        return self._request("GET", f"{P}/validations/{evidence_id}", headers=headers)

    def accept_validation(self, evidence_id, headers, payload=None):
        return self._request("POST", f"{P}/validations/{evidence_id}/accept",
                             payload or {}, headers)

    def reject_validation(self, evidence_id, headers, payload=None):
        return self._request("POST", f"{P}/validations/{evidence_id}/reject",
                             payload or {}, headers)

    # --- allocation holds ---
    def create_allocation_hold(self, payload, headers):
        return self._request("POST", f"{P}/allocation-holds", payload, headers)

    def create_allocation_holds_bulk(self, payload, headers):
        return self._request("POST", f"{P}/allocation-holds/bulk", payload, headers)

    def list_allocation_holds(self, headers, params=None):
        return self._request("GET", f"{P}/allocation-holds", headers=headers, params=params)

    def get_allocation_hold(self, hold_id, headers):
        return self._request("GET", f"{P}/allocation-holds/{hold_id}", headers=headers)

    def commit_allocation_hold(self, hold_id, headers, payload=None):
        return self._request("POST", f"{P}/allocation-holds/{hold_id}/commit",
                             payload or {}, headers)

    def cancel_allocation_hold(self, hold_id, headers, payload=None):
        return self._request("POST", f"{P}/allocation-holds/{hold_id}/cancel",
                             payload or {}, headers)

    def reclaim_allocation_hold(self, hold_id, headers, payload=None):
        return self._request("POST", f"{P}/allocation-holds/{hold_id}/reclaim",
                             payload or {}, headers)

    def expire_allocation_hold(self, hold_id, headers, payload=None):
        return self._request("POST", f"{P}/allocation-holds/{hold_id}/expire",
                             payload or {}, headers)

    # --- licence hold groups ---
    def create_license_hold_group(self, payload, headers):
        return self._request("POST", f"{P}/license-hold-groups", payload, headers)

    def get_license_hold_group(self, group_id, headers):
        return self._request("GET", f"{P}/license-hold-groups/{group_id}", headers=headers)

    def get_license_hold(self, hold_id, headers):
        return self._request("GET", f"{P}/license-holds/{hold_id}", headers=headers)

    def preempt_license_hold_group(self, group_id, headers, payload=None):
        return self._request("POST", f"{P}/license-hold-groups/{group_id}/preempt",
                             payload or {}, headers)

    # --- demand forecasts ---
    def create_demand_forecast(self, payload, headers):
        return self._request("POST", f"{P}/demand-forecasts", payload, headers)

    def list_demand_forecasts(self, headers, params=None):
        return self._request("GET", f"{P}/demand-forecasts", headers=headers, params=params)

    def get_demand_forecast(self, forecast_id, headers):
        return self._request("GET", f"{P}/demand-forecasts/{forecast_id}", headers=headers)

    def acknowledge_demand_forecast(self, forecast_id, headers, payload=None):
        return self._request("POST", f"{P}/demand-forecasts/{forecast_id}/acknowledge",
                             payload or {}, headers)

    def commit_demand_forecast(self, forecast_id, payload, headers):
        return self._request("POST", f"{P}/demand-forecasts/{forecast_id}/commit",
                             payload, headers)

    def cancel_demand_forecast(self, forecast_id, headers, payload=None):
        return self._request("POST", f"{P}/demand-forecasts/{forecast_id}/cancel",
                             payload or {}, headers)

    def revise_demand_forecast(self, forecast_id, headers, payload=None):
        return self._request("POST", f"{P}/demand-forecasts/{forecast_id}/revise",
                             payload or {}, headers)

    # --- stack licenses ---
    def create_stack_license(self, payload, headers):
        return self._request("POST", f"{P}/stack-licenses", payload, headers)

    def list_stack_licenses(self, headers, params=None):
        return self._request("GET", f"{P}/stack-licenses", headers=headers, params=params)

    def get_stack_license(self, stack_id, headers):
        return self._request("GET", f"{P}/stack-licenses/{stack_id}", headers=headers)

    def release_stack_license(self, stack_id, headers, payload=None):
        return self._request("POST", f"{P}/stack-licenses/{stack_id}/release",
                             payload or {}, headers)

    def retire_stack_license(self, stack_id, headers, payload=None):
        return self._request("POST", f"{P}/stack-licenses/{stack_id}/retire",
                             payload or {}, headers)

    # --- export licenses ---
    def create_export_license(self, payload, headers):
        return self._request("POST", f"{P}/export-licenses", payload, headers)

    def list_export_licenses(self, headers, params=None):
        return self._request("GET", f"{P}/export-licenses", headers=headers, params=params)

    def get_export_license(self, grant_id, headers):
        return self._request("GET", f"{P}/export-licenses/{grant_id}", headers=headers)

    def revoke_export_license(self, grant_id, headers, payload=None):
        return self._request("POST", f"{P}/export-licenses/{grant_id}/revoke",
                             payload or {}, headers)

    # --- deployments ---
    def create_deployment(self, payload, headers):
        return self._request("POST", f"{P}/deployments", payload, headers)

    def list_deployments(self, headers, params=None):
        return self._request("GET", f"{P}/deployments", headers=headers, params=params)

    def get_deployment(self, deployment_id, headers):
        return self._request("GET", f"{P}/deployments/{deployment_id}", headers=headers)

    def activate_deployment(self, deployment_id, headers, payload=None):
        return self._request("POST", f"{P}/deployments/{deployment_id}/activate",
                             payload or {}, headers)

    def terminate_deployment(self, deployment_id, headers, payload=None):
        return self._request("POST", f"{P}/deployments/{deployment_id}/terminate",
                             payload or {}, headers)

    def reinstate_deployment(self, deployment_id, headers, payload=None):
        return self._request("POST", f"{P}/deployments/{deployment_id}/reinstate",
                             payload or {}, headers)

    def handover_deployment(self, deployment_id, payload, headers):
        return self._request("POST", f"{P}/deployments/{deployment_id}/handover",
                             payload, headers)

    # --- deployment groups ---
    def create_deployment_group(self, payload, headers):
        return self._request("POST", f"{P}/deployment-groups", payload, headers)

    def get_deployment_group(self, group_id, headers):
        return self._request("GET", f"{P}/deployment-groups/{group_id}", headers=headers)

    def dispatch_deployment_group(self, group_id, headers, payload=None):
        return self._request("POST", f"{P}/deployment-groups/{group_id}/dispatch",
                             payload or {}, headers)

    # --- subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", f"{P}/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", f"{P}/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"{P}/subscriptions/{subscription_id}", headers=headers)

    def activate_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"{P}/subscriptions/{subscription_id}/activate",
                             payload or {}, headers)

    def reinstate_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"{P}/subscriptions/{subscription_id}/reinstate",
                             payload or {}, headers)

    def reclaim_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"{P}/subscriptions/{subscription_id}/reclaim",
                             payload or {}, headers)

    def evaluate_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"{P}/subscriptions/{subscription_id}/evaluate",
                             payload, headers)

    # --- developer memberships ---
    def create_membership(self, payload, headers):
        return self._request("POST", f"{P}/developer-memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", f"{P}/developer-memberships", headers=headers, params=params)

    def list_memberships_with_children(self, headers, params=None):
        return self._request("GET", f"{P}/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"{P}/developer-memberships/{membership_id}", headers=headers)

    def evaluate_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"{P}/developer-memberships/{membership_id}/evaluate",
                             payload or {}, headers)

    def renew_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"{P}/developer-memberships/{membership_id}/renew",
                             payload or {}, headers)

    def lapse_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"{P}/developer-memberships/{membership_id}/lapse",
                             payload or {}, headers)

    def revoke_membership(self, membership_id, headers, payload=None):
        return self._request("POST", f"{P}/developer-memberships/{membership_id}/revoke",
                             payload or {}, headers)

    # --- preview grants / confidentiality ---
    def create_preview_grant(self, payload, headers):
        return self._request("POST", f"{P}/preview-grants", payload, headers)

    def list_preview_grants(self, headers, params=None):
        return self._request("GET", f"{P}/preview-grants", headers=headers, params=params)

    def get_preview_grant(self, grant_id, headers):
        return self._request("GET", f"{P}/preview-grants/{grant_id}", headers=headers)

    def revoke_preview_grant(self, grant_id, headers, payload=None):
        return self._request("POST", f"{P}/preview-grants/{grant_id}/revoke",
                             payload or {}, headers)

    def create_confidentiality_ack(self, payload, headers):
        return self._request("POST", f"{P}/confidentiality-acks", payload, headers)

    def list_confidentiality_acks(self, headers, params=None):
        return self._request("GET", f"{P}/confidentiality-acks", headers=headers, params=params)

    def get_confidentiality_ack(self, ack_id, headers):
        return self._request("GET", f"{P}/confidentiality-acks/{ack_id}", headers=headers)

    # --- evaluation loans / milestones ---
    def create_evaluation_loan(self, payload, headers):
        return self._request("POST", f"{P}/evaluation-loans", payload, headers)

    def list_evaluation_loans(self, headers, params=None):
        return self._request("GET", f"{P}/evaluation-loans", headers=headers, params=params)

    def get_evaluation_loan(self, loan_id, headers):
        return self._request("GET", f"{P}/evaluation-loans/{loan_id}", headers=headers)

    def approve_evaluation_loan(self, loan_id, payload, headers):
        return self._request("POST", f"{P}/evaluation-loans/{loan_id}/approve", payload, headers)

    def start_evaluation_loan(self, loan_id, headers, payload=None):
        return self._request("POST", f"{P}/evaluation-loans/{loan_id}/start",
                             payload or {}, headers)

    def return_evaluation_loan(self, loan_id, headers, payload=None):
        return self._request("POST", f"{P}/evaluation-loans/{loan_id}/return",
                             payload or {}, headers)

    def reclaim_evaluation_loan(self, loan_id, headers, payload=None):
        return self._request("POST", f"{P}/evaluation-loans/{loan_id}/reclaim",
                             payload or {}, headers)

    def record_milestone(self, loan_id, payload, headers):
        return self._request("POST", f"{P}/evaluation-loans/{loan_id}/milestones",
                             payload, headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", f"{P}/milestones", headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"{P}/milestones/{milestone_id}", headers=headers)

    # --- lifecycle commitments / supply contracts ---
    def create_lifecycle_commitment(self, payload, headers):
        return self._request("POST", f"{P}/lifecycle-commitments", payload, headers)

    def list_lifecycle_commitments(self, headers, params=None):
        return self._request("GET", f"{P}/lifecycle-commitments", headers=headers, params=params)

    def get_lifecycle_commitment(self, commitment_id, headers):
        return self._request("GET", f"{P}/lifecycle-commitments/{commitment_id}", headers=headers)

    def grant_lifecycle_commitment(self, commitment_id, payload, headers):
        return self._request("POST", f"{P}/lifecycle-commitments/{commitment_id}/grant",
                             payload, headers)

    def decline_lifecycle_commitment(self, commitment_id, headers, payload=None):
        return self._request("POST", f"{P}/lifecycle-commitments/{commitment_id}/decline",
                             payload or {}, headers)

    def create_supply_contract(self, payload, headers):
        return self._request("POST", f"{P}/supply-contracts", payload, headers)

    def list_supply_contracts(self, headers, params=None):
        return self._request("GET", f"{P}/supply-contracts", headers=headers, params=params)

    def get_supply_contract(self, contract_id, headers):
        return self._request("GET", f"{P}/supply-contracts/{contract_id}", headers=headers)

    # --- friction penalties / audit ---
    def list_friction_penalties(self, headers, params=None):
        return self._request("GET", f"{P}/friction-penalties", headers=headers, params=params)

    def get_friction_penalty(self, penalty_id, headers):
        return self._request("GET", f"{P}/friction-penalties/{penalty_id}", headers=headers)

    def list_audit_entries(self, headers, params=None):
        return self._request("GET", f"{P}/audit-entries", headers=headers, params=params)

    def get_audit_entry(self, entry_id, headers):
        return self._request("GET", f"{P}/audit-entries/{entry_id}", headers=headers)


api_client = ApiClient()