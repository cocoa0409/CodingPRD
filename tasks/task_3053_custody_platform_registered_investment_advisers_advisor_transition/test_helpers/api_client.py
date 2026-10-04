"""API client: one method per endpoint defined in the PRD.

PRD §2.10: "the platform honors a generic conditional-request contract on every
`PUT` and every state-changing `POST`: such a request must carry an `If-Match`
header, and its absence is refused with `ERR_IF_MATCH_REQUIRED` (HTTP 428),
while a header whose value does not match the target row's current `version` is
refused with `ERR_INVALID_IF_MATCH` (HTTP 412)."

The client therefore carries that token on every such call.  The token is read
from the acting row's current `version`, which the enclosing fixture's own
create/read response already exposes — so tests declare the precondition the
contract requires without an extra round trip.  `_require_version` refuses to
send a state-changing request without a resolvable token: a missing version is a
fixture bug (an inflated precondition), not something to paper over with a
speculative header.
"""
from prd_bench_local_runner.testing import GenericApiClient


def _if_match_headers(headers, row):
    """Copy ``headers`` and attach the If-Match token drawn from ``row``."""
    merged = dict(headers or {})
    merged["If-Match"] = str(row["version"])
    return merged


def _require_version(row, what):
    if not isinstance(row, dict) or "version" not in row:
        raise AssertionError(
            "If-Match token unavailable for %s: the acting row's current version "
            "must be supplied (PRD §2.10 requires it on every PUT and "
            "state-changing POST)." % what
        )
    return row


class ApiClient(GenericApiClient):

    # ─── clock / config / invariants / admin actions ─────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def create_system_config(self, payload, headers):
        return self._request("POST", "/ria/systems/config", payload, headers)

    def patch_system_config(self, config_id, payload, headers, row=None):
        return self._request("PATCH", f"/ria/systems/config/{config_id}", payload,
                             _if_match_headers(headers, _require_version(row, "SystemConfig")))

    def evaluate_invariants(self, payload, headers):
        return self._request("POST", "/ria/invariants/evaluate", payload, headers)

    def list_firm_invariants(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/invariants", headers=headers, params=params)

    def issue_admin_action(self, payload, headers):
        return self._request("POST", "/ria/admin-actions/issue", payload, headers)

    def list_admin_actions(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/admin-actions", headers=headers, params=params)

    def acknowledge_admin_action(self, action_id, payload, headers, row=None):
        return self._request("POST", f"/ria/admin-actions/{action_id}/acknowledge", payload,
                             _if_match_headers(headers, _require_version(row, "AdminActionLog")))

    # ─── firms ───────────────────────────────────────────────────────────────
    def create_firm(self, payload, headers):
        return self._request("POST", "/ria/firms", payload, headers)

    def get_firm(self, firm_id, headers):
        return self._request("GET", f"/ria/firms/{firm_id}", headers=headers)

    def list_firms(self, headers, params=None):
        return self._request("GET", "/ria/firms", headers=headers, params=params)

    def freeze_firm(self, firm_id, payload, headers, row=None):
        return self._request("POST", f"/ria/firms/{firm_id}/freeze", payload,
                             _if_match_headers(headers, _require_version(row, "AdvisorFirm")))

    # ─── custody agreements ──────────────────────────────────────────────────
    def create_custody_agreement(self, firm_id, payload, headers):
        return self._request("POST", f"/ria/firms/{firm_id}/custody-agreements", payload, headers)

    def list_custody_agreements(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/custody-agreements", headers=headers, params=params)

    def get_custody_agreement(self, agreement_id, headers):
        return self._request("GET", f"/ria/custody-agreements/{agreement_id}", headers=headers)

    def submit_custody_agreement(self, agreement_id, payload, headers, row=None):
        return self._request("POST", f"/ria/custody-agreements/{agreement_id}/submit", payload,
                             _if_match_headers(headers, _require_version(row, "CustodyAgreement")))

    def revert_custody_agreement(self, agreement_id, payload, headers, row=None):
        return self._request("POST", f"/ria/custody-agreements/{agreement_id}/revert", payload,
                             _if_match_headers(headers, _require_version(row, "CustodyAgreement")))

    def execute_custody_agreement(self, firm_id, payload, headers, row=None):
        # PRD §3.1: countersignature is stated among its preconditions to target
        # the firm's agreement sitting in PENDING_SIGNATURE.  The caller passes the
        # pending row it read; the header is added only when it is supplied.
        merged = dict(headers or {})
        if row is not None and isinstance(row, dict) and "version" in row:
            merged["If-Match"] = str(row["version"])
        return self._request("POST", f"/ria/firms/{firm_id}/custody-agreements/execute", payload, merged)

    def terminate_custody_agreement(self, firm_id, agreement_id, payload, headers, row=None):
        # PRD §3.1: termination is only available on the firm's current agreement,
        # which is necessarily already EXECUTED and therefore addressable.
        merged = dict(headers or {})
        if row is not None and isinstance(row, dict) and "version" in row:
            merged["If-Match"] = str(row["version"])
        return self._request(
            "POST", f"/ria/firms/{firm_id}/custody-agreements/{agreement_id}/terminate", payload, merged
        )

    def list_agreement_entitlements(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/ria/custody-agreements/{agreement_id}/firm-entitlements", headers=headers, params=params
        )

    def list_agreement_successors(self, agreement_id, headers, params=None):
        return self._request("GET", f"/ria/custody-agreements/{agreement_id}/successors", headers=headers, params=params)

    # ─── entitlements ────────────────────────────────────────────────────────
    def create_entitlement(self, payload, headers):
        return self._request("POST", "/ria/firm-entitlements", payload, headers)

    def list_firm_entitlements(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/firm-entitlements", headers=headers, params=params)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/ria/firm-entitlements/{entitlement_id}", headers=headers)

    def grant_entitlement(self, entitlement_id, payload, headers, row=None):
        return self._request("POST", f"/ria/firm-entitlements/{entitlement_id}/grant", payload,
                             _if_match_headers(headers, _require_version(row, "AdvisorFirmEntitlement")))

    def revoke_entitlement(self, entitlement_id, payload, headers, row=None):
        return self._request("POST", f"/ria/firm-entitlements/{entitlement_id}/revoke", payload,
                             _if_match_headers(headers, _require_version(row, "AdvisorFirmEntitlement")))

    def reopen_entitlement(self, entitlement_id, payload, headers, row=None):
        return self._request("POST", f"/ria/firm-entitlements/{entitlement_id}/reopen", payload,
                             _if_match_headers(headers, _require_version(row, "AdvisorFirmEntitlement")))

    # ─── households ──────────────────────────────────────────────────────────
    def create_household(self, payload, headers):
        return self._request("POST", "/ria/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/ria/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/ria/households", headers=headers, params=params)

    def create_fee_credit(self, household_id, payload, headers):
        return self._request("POST", f"/ria/households/{household_id}/fee-credits", payload, headers)

    def list_household_fee_credits(self, household_id, headers, params=None):
        return self._request("GET", f"/ria/households/{household_id}/fee-credits", headers=headers, params=params)

    def list_household_billing_runs(self, household_id, headers, params=None):
        return self._request("GET", f"/ria/households/{household_id}/billing-runs", headers=headers, params=params)

    # ─── accounts ────────────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/ria/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/ria/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/ria/accounts/{account_id}", headers=headers)

    def patch_account(self, account_id, payload, headers, row=None):
        return self._request("PATCH", f"/ria/accounts/{account_id}", payload,
                             _if_match_headers(headers, _require_version(row, "HouseholdAccount")))

    def activate_account(self, account_id, payload, headers, row=None):
        return self._request("POST", f"/ria/accounts/{account_id}/activate", payload,
                             _if_match_headers(headers, _require_version(row, "HouseholdAccount")))

    def freeze_account(self, account_id, payload, headers, row=None):
        return self._request("POST", f"/ria/accounts/{account_id}/freeze", payload,
                             _if_match_headers(headers, _require_version(row, "HouseholdAccount")))

    def unfreeze_account(self, account_id, payload, headers, row=None):
        return self._request("POST", f"/ria/accounts/{account_id}/unfreeze", payload,
                             _if_match_headers(headers, _require_version(row, "HouseholdAccount")))

    def close_account(self, account_id, payload, headers, row=None):
        return self._request("POST", f"/ria/accounts/{account_id}/close", payload,
                             _if_match_headers(headers, _require_version(row, "HouseholdAccount")))

    def list_account(self, account_id, payload, headers, row=None):
        return self._request("POST", f"/ria/accounts/{account_id}/list", payload,
                             _if_match_headers(headers, _require_version(row, "HouseholdAccount")))

    def relink_account(self, account_id, payload, headers, row=None):
        return self._request("POST", f"/ria/accounts/{account_id}/relink", payload,
                             _if_match_headers(headers, _require_version(row, "HouseholdAccount")))

    def set_account_model(self, account_id, payload, headers, row=None):
        return self._request("PUT", f"/ria/accounts/{account_id}/model", payload,
                             _if_match_headers(headers, _require_version(row, "HouseholdAccount")))

    def list_account_alternatives(self, account_id, headers, params=None):
        return self._request("GET", f"/ria/accounts/{account_id}/alternatives", headers=headers, params=params)

    def list_account_block_allocations(self, account_id, headers, params=None):
        return self._request("GET", f"/ria/accounts/{account_id}/block-allocations", headers=headers, params=params)

    def list_account_asset_transfers(self, account_id, headers, params=None):
        return self._request("GET", f"/ria/accounts/{account_id}/asset-transfers", headers=headers, params=params)

    # ─── transfers ───────────────────────────────────────────────────────────
    def create_asset_transfer(self, payload, headers):
        return self._request("POST", "/ria/asset-transfers", payload, headers)

    def list_asset_transfers(self, headers, params=None):
        return self._request("GET", "/ria/asset-transfers", headers=headers, params=params)

    def get_asset_transfer(self, transfer_id, headers):
        return self._request("GET", f"/ria/asset-transfers/{transfer_id}", headers=headers)

    def transfer_out(self, transfer_id, payload, headers, row=None):
        return self._request("POST", f"/ria/assets/{transfer_id}/transfer-out", payload,
                             _if_match_headers(headers, _require_version(row, "AssetTransfer")))

    def mark_received(self, transfer_id, payload, headers, row=None):
        return self._request("POST", f"/ria/assets/{transfer_id}/mark-received", payload,
                             _if_match_headers(headers, _require_version(row, "AssetTransfer")))

    def accept_basis(self, transfer_id, payload, headers, row=None):
        return self._request("POST", f"/ria/assets/{transfer_id}/accept-basis", payload,
                             _if_match_headers(headers, _require_version(row, "AssetTransfer")))

    def reject_basis(self, transfer_id, payload, headers, row=None):
        return self._request("POST", f"/ria/assets/{transfer_id}/reject-basis", payload,
                             _if_match_headers(headers, _require_version(row, "AssetTransfer")))

    def reject_transfer(self, transfer_id, payload, headers, row=None):
        return self._request("POST", f"/ria/assets/{transfer_id}/reject", payload,
                             _if_match_headers(headers, _require_version(row, "AssetTransfer")))

    def create_transfer_lot(self, transfer_id, payload, headers):
        return self._request("POST", f"/ria/transfers/{transfer_id}/lots", payload, headers)

    def list_transfer_lots(self, transfer_id, headers, params=None):
        return self._request("GET", f"/ria/asset-transfers/{transfer_id}/lots", headers=headers, params=params)

    # ─── models ──────────────────────────────────────────────────────────────
    def create_model(self, payload, headers):
        return self._request("POST", "/ria/models", payload, headers)

    def list_firm_models(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/models", headers=headers, params=params)

    def get_model(self, model_id, headers):
        return self._request("GET", f"/ria/models/{model_id}", headers=headers)

    def create_model_target(self, model_id, payload, headers):
        return self._request("POST", f"/ria/models/{model_id}/targets", payload, headers)

    def replace_model_target(self, target_id, payload, headers, row=None):
        return self._request("PUT", f"/ria/model-targets/{target_id}", payload,
                             _if_match_headers(headers, _require_version(row, "ModelTarget")))

    def list_model_targets(self, model_id, headers, params=None):
        return self._request("GET", f"/ria/models/{model_id}/targets", headers=headers, params=params)

    def approve_model(self, model_id, payload, headers, row=None):
        return self._request("POST", f"/ria/models/{model_id}/approve", payload,
                             _if_match_headers(headers, _require_version(row, "ModelPortfolio")))

    def rebalance_model(self, model_id, payload, headers, row=None):
        return self._request("POST", f"/ria/models/{model_id}/rebalance", payload,
                             _if_match_headers(headers, _require_version(row, "ModelPortfolio")))

    def activate_model(self, model_id, payload, headers, row=None):
        return self._request("POST", f"/ria/models/{model_id}/activate", payload,
                             _if_match_headers(headers, _require_version(row, "ModelPortfolio")))

    def archive_model(self, model_id, payload, headers, row=None):
        return self._request("POST", f"/ria/models/{model_id}/archive", payload,
                             _if_match_headers(headers, _require_version(row, "ModelPortfolio")))

    def list_model_accounts(self, model_id, headers, params=None):
        return self._request("GET", f"/ria/models/{model_id}/accounts", headers=headers, params=params)

    def list_model_block_orders(self, model_id, headers, params=None):
        return self._request("GET", f"/ria/models/{model_id}/block-orders", headers=headers, params=params)

    # ─── block orders ────────────────────────────────────────────────────────
    def create_block_order(self, payload, headers):
        return self._request("POST", "/ria/block-orders", payload, headers)

    def get_block_order(self, block_id, headers):
        return self._request("GET", f"/ria/block-orders/{block_id}", headers=headers)

    def list_firm_block_orders(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/block-orders", headers=headers, params=params)

    def create_block_allocation(self, block_id, payload, headers):
        return self._request("POST", f"/ria/block-orders/{block_id}/allocations", payload, headers)

    def list_block_allocations(self, block_id, headers, params=None):
        return self._request("GET", f"/ria/block-orders/{block_id}/allocations", headers=headers, params=params)

    def submit_block_order(self, block_id, payload, headers, row=None):
        return self._request("POST", f"/ria/block-orders/{block_id}/submit", payload,
                             _if_match_headers(headers, _require_version(row, "BlockOrder")))

    def execute_block_order(self, block_id, payload, headers, row=None):
        return self._request("POST", f"/ria/block-orders/{block_id}/execute", payload,
                             _if_match_headers(headers, _require_version(row, "BlockOrder")))

    def allocate_block_order(self, block_id, payload, headers, row=None):
        return self._request("POST", f"/ria/block-orders/{block_id}/allocate", payload,
                             _if_match_headers(headers, _require_version(row, "BlockOrder")))

    def preview_block_allocation(self, block_id, payload, headers):
        return self._request("POST", f"/ria/block-orders/{block_id}/allocation-preview", payload, headers)

    def settle_block_order(self, block_id, payload, headers, row=None):
        return self._request("POST", f"/ria/block-orders/{block_id}/settle", payload,
                             _if_match_headers(headers, _require_version(row, "BlockOrder")))

    # ─── billing ─────────────────────────────────────────────────────────────
    def create_billing_run(self, payload, headers):
        return self._request("POST", "/ria/billing-runs", payload, headers)

    def get_billing_run(self, run_id, headers):
        return self._request("GET", f"/ria/billing-runs/{run_id}", headers=headers)

    def list_firm_billing_runs(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/billing-runs", headers=headers, params=params)

    def remit_invoice(self, run_id, payload, headers, row=None):
        return self._request("POST", f"/ria/billing-runs/{run_id}/remit-invoice", payload,
                             _if_match_headers(headers, _require_version(row, "FeeBillingRun")))

    def reopen_billing_run(self, run_id, payload, headers, row=None):
        return self._request("POST", f"/ria/billing-runs/{run_id}/reopen", payload,
                             _if_match_headers(headers, _require_version(row, "FeeBillingRun")))

    def resettle_billing_run(self, run_id, payload, headers, row=None):
        return self._request("POST", f"/ria/billing-runs/{run_id}/settle", payload,
                             _if_match_headers(headers, _require_version(row, "FeeBillingRun")))

    def void_billing_run(self, run_id, payload, headers, row=None):
        return self._request("POST", f"/ria/billing-runs/{run_id}/void", payload,
                             _if_match_headers(headers, _require_version(row, "FeeBillingRun")))

    def list_run_fee_credits(self, run_id, headers, params=None):
        return self._request("GET", f"/ria/billing-runs/{run_id}/fee-credits", headers=headers, params=params)

    # ─── alternatives ────────────────────────────────────────────────────────
    def create_alternative(self, payload, headers):
        return self._request("POST", "/ria/alternatives", payload, headers)

    def get_alternative(self, holding_id, headers):
        return self._request("GET", f"/ria/alternatives/{holding_id}", headers=headers)

    def submit_valuation(self, holding_id, payload, headers, row=None):
        return self._request("POST", f"/ria/alternatives/{holding_id}/submit-valuation", payload,
                             _if_match_headers(headers, _require_version(row, "AlternativeAssetHolding")))

    def accept_valuation(self, holding_id, payload, headers, row=None):
        return self._request("POST", f"/ria/alternatives/{holding_id}/accept-valuation", payload,
                             _if_match_headers(headers, _require_version(row, "AlternativeAssetHolding")))

    def reject_valuation(self, holding_id, payload, headers, row=None):
        return self._request("POST", f"/ria/alternatives/{holding_id}/reject-valuation", payload,
                             _if_match_headers(headers, _require_version(row, "AlternativeAssetHolding")))

    # ─── standing instructions & money movement ──────────────────────────────
    def create_standing_instruction(self, account_id, payload, headers):
        return self._request("POST", f"/ria/accounts/{account_id}/standing-instructions", payload, headers)

    def list_account_standing_instructions(self, account_id, headers, params=None):
        return self._request("GET", f"/ria/accounts/{account_id}/standing-instructions", headers=headers, params=params)

    def get_standing_instruction(self, instruction_id, headers):
        return self._request("GET", f"/ria/standing-instructions/{instruction_id}", headers=headers)

    def verify_standing_instruction(self, instruction_id, payload, headers, row=None):
        return self._request("POST", f"/ria/standing-instructions/{instruction_id}/verify", payload,
                             _if_match_headers(headers, _require_version(row, "StandingInstruction")))

    def expire_check_standing_instruction(self, instruction_id, payload, headers, row=None):
        return self._request("POST", f"/ria/standing-instructions/{instruction_id}/expire-check", payload,
                             _if_match_headers(headers, _require_version(row, "StandingInstruction")))

    def revoke_standing_instruction(self, instruction_id, payload, headers, row=None):
        return self._request("POST", f"/ria/standing-instructions/{instruction_id}/revoke", payload,
                             _if_match_headers(headers, _require_version(row, "StandingInstruction")))

    def list_instruction_money_movements(self, instruction_id, headers, params=None):
        return self._request("GET", f"/ria/standing-instructions/{instruction_id}/money-movements", headers=headers, params=params)

    def create_money_movement(self, payload, headers):
        return self._request("POST", "/ria/money-movements", payload, headers)

    def get_money_movement(self, movement_id, headers):
        return self._request("GET", f"/ria/money-movements/{movement_id}", headers=headers)

    def list_account_money_movements(self, account_id, headers, params=None):
        return self._request("GET", f"/ria/accounts/{account_id}/money-movements", headers=headers, params=params)

    def money_movement_summary(self, account_id, headers, params=None):
        return self._request("GET", f"/ria/accounts/{account_id}/money-movements/summary", headers=headers, params=params)

    def submit_money_movement(self, movement_id, payload, headers, row=None):
        return self._request("POST", f"/ria/money-movements/{movement_id}/submit", payload,
                             _if_match_headers(headers, _require_version(row, "MoneyMovementInstruction")))

    def authorize_money_movement(self, movement_id, payload, headers, row=None):
        return self._request("POST", f"/ria/money-movements/{movement_id}/authorize", payload,
                             _if_match_headers(headers, _require_version(row, "MoneyMovementInstruction")))

    def reject_money_movement(self, movement_id, payload, headers, row=None):
        return self._request("POST", f"/ria/money-movements/{movement_id}/reject", payload,
                             _if_match_headers(headers, _require_version(row, "MoneyMovementInstruction")))

    def cancel_money_movement(self, movement_id, payload, headers, row=None):
        return self._request("POST", f"/ria/money-movements/{movement_id}/cancel", payload,
                             _if_match_headers(headers, _require_version(row, "MoneyMovementInstruction")))

    def complete_money_movement(self, movement_id, payload, headers, row=None):
        return self._request("POST", f"/ria/money-movements/{movement_id}/complete", payload,
                             _if_match_headers(headers, _require_version(row, "MoneyMovementInstruction")))

    # ─── onboarding batches ──────────────────────────────────────────────────
    def create_onboarding_batch(self, payload, headers):
        return self._request("POST", "/ria/onboarding-batches", payload, headers)

    def dispatch_onboarding_batch(self, batch_id, payload, headers, row=None):
        return self._request("PUT", f"/ria/onboarding-batches/{batch_id}", payload,
                             _if_match_headers(headers, _require_version(row, "OnboardingBatch")))

    def get_onboarding_batch(self, batch_id, headers):
        return self._request("GET", f"/ria/onboarding-batches/{batch_id}", headers=headers)

    def list_firm_onboarding_batches(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/onboarding-batches", headers=headers, params=params)

    # ─── custody evidence & examination ──────────────────────────────────────
    def create_custody_evidence(self, firm_id, payload, headers):
        return self._request("POST", f"/ria/firms/{firm_id}/custody-evidence", payload, headers)

    def list_firm_custody_evidence(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/custody-evidence", headers=headers, params=params)

    def get_custody_evidence(self, evidence_id, headers):
        return self._request("GET", f"/ria/custody-evidence/{evidence_id}", headers=headers)

    def submit_custody_evidence(self, evidence_id, payload, headers, row=None):
        return self._request("POST", f"/ria/custody-evidence/{evidence_id}/submit", payload,
                             _if_match_headers(headers, _require_version(row, "CustodyRulesEvidence")))

    def accept_custody_evidence(self, evidence_id, payload, headers, row=None):
        return self._request("POST", f"/ria/custody-evidence/{evidence_id}/accept", payload,
                             _if_match_headers(headers, _require_version(row, "CustodyRulesEvidence")))

    def reject_custody_evidence(self, evidence_id, payload, headers, row=None):
        return self._request("POST", f"/ria/custody-evidence/{evidence_id}/reject", payload,
                             _if_match_headers(headers, _require_version(row, "CustodyRulesEvidence")))

    def resubmit_custody_evidence(self, evidence_id, payload, headers, row=None):
        return self._request("POST", f"/ria/custody-evidence/{evidence_id}/resubmit", payload,
                             _if_match_headers(headers, _require_version(row, "CustodyRulesEvidence")))

    def waive_custody_evidence(self, evidence_id, payload, headers, row=None):
        return self._request("POST", f"/ria/custody-evidence/{evidence_id}/waive", payload,
                             _if_match_headers(headers, _require_version(row, "CustodyRulesEvidence")))

    def lapse_custody_evidence(self, evidence_id, payload, headers, row=None):
        return self._request("POST", f"/ria/custody-evidence/{evidence_id}/lapse", payload,
                             _if_match_headers(headers, _require_version(row, "CustodyRulesEvidence")))

    def create_examination_bundle(self, firm_id, payload, headers):
        return self._request("POST", f"/ria/firms/{firm_id}/examination-bundles", payload, headers)

    def list_examination_bundles(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/examination-bundles", headers=headers, params=params)

    def generate_examination_bundle(self, bundle_id, payload, headers, row=None):
        return self._request("POST", f"/ria/examination-bundles/{bundle_id}/generate", payload,
                             _if_match_headers(headers, _require_version(row, "ExaminationBundle")))

    def seal_examination_bundle(self, bundle_id, payload, headers, row=None):
        return self._request("POST", f"/ria/examination-bundles/{bundle_id}/seal", payload,
                             _if_match_headers(headers, _require_version(row, "ExaminationBundle")))

    # ─── data feeds ──────────────────────────────────────────────────────────
    def create_data_feed(self, payload, headers):
        return self._request("POST", "/ria/data-feeds", payload, headers)

    def list_firm_data_feeds(self, firm_id, headers, params=None):
        return self._request("GET", f"/ria/firms/{firm_id}/data-feeds", headers=headers, params=params)

    def provision_data_feed(self, feed_id, payload, headers, row=None):
        return self._request("POST", f"/ria/data-feeds/{feed_id}/provision", payload,
                             _if_match_headers(headers, _require_version(row, "DataFeedProvision")))

    def revoke_data_feed(self, feed_id, payload, headers, row=None):
        return self._request("POST", f"/ria/data-feeds/{feed_id}/revoke", payload,
                             _if_match_headers(headers, _require_version(row, "DataFeedProvision")))

    def pull_data_feed(self, feed_id, payload, headers):
        return self._request("POST", f"/ria/data-feeds/{feed_id}/pull", payload, headers)

    # ─── custodian research ──────────────────────────────────────────────────
    def lookup_lot_inventory(self, payload, headers):
        return self._request("POST", "/ria/lookup/lot-inventory", payload, headers)


api_client = ApiClient()