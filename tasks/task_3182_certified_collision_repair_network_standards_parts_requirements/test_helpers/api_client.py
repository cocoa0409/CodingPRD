"""API client: one method per endpoint defined in the PRD's endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Shops ---
    def create_shop(self, payload, headers):
        return self._request("POST", "/network/shops", payload, headers)

    def list_shops(self, headers, params=None):
        return self._request("GET", "/network/shops", headers=headers, params=params)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/network/shops/{shop_id}", headers=headers)

    def decertify_shop(self, shop_id, headers):
        return self._request("POST", f"/network/shops/{shop_id}/decertify", {}, headers)

    # --- Certification cycles ---
    def create_cycle(self, shop_id, payload, headers):
        return self._request("POST", f"/network/shops/{shop_id}/certification-cycles", payload, headers)

    def list_cycles(self, shop_id, headers, params=None):
        return self._request("GET", f"/network/shops/{shop_id}/certification-cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/network/certification-cycles/{cycle_id}", headers=headers)

    def close_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/network/certification-cycles/{cycle_id}/close", payload, headers)

    # --- Requirements ---
    def create_requirement(self, payload, headers):
        return self._request("POST", "/network/requirements", payload, headers)

    def list_requirements(self, headers, params=None):
        return self._request("GET", "/network/requirements", headers=headers, params=params)

    def get_requirement(self, requirement_id, headers):
        return self._request("GET", f"/network/requirements/{requirement_id}", headers=headers)

    def publish_requirement(self, requirement_id, headers):
        return self._request("POST", f"/network/requirements/{requirement_id}/publish", {}, headers)

    def publish_revision(self, requirement_id, payload, headers):
        return self._request("POST", f"/network/requirements/{requirement_id}/publish-revision", payload, headers)

    def retire_requirement(self, requirement_id, headers):
        return self._request("POST", f"/network/requirements/{requirement_id}/retire", {}, headers)

    # --- Attestations ---
    def create_attestation(self, shop_id, payload, headers):
        return self._request("POST", f"/network/shops/{shop_id}/attestations", payload, headers)

    def list_shop_attestations(self, shop_id, headers, params=None):
        return self._request("GET", f"/network/shops/{shop_id}/attestations", headers=headers, params=params)

    def list_attestations(self, headers, params=None):
        return self._request("GET", "/network/attestations", headers=headers, params=params)

    def get_attestation(self, attestation_id, headers):
        return self._request("GET", f"/network/attestations/{attestation_id}", headers=headers)

    # --- Audits ---
    def schedule_audit(self, cycle_id, payload, headers):
        return self._request("POST", f"/network/certification-cycles/{cycle_id}/audits", payload, headers)

    def list_audits(self, cycle_id, headers, params=None):
        return self._request("GET", f"/network/certification-cycles/{cycle_id}/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/network/audits/{audit_id}", headers=headers)

    def begin_audit(self, audit_id, headers):
        return self._request("POST", f"/network/audits/{audit_id}/begin", {}, headers)

    def cancel_audit(self, audit_id, headers):
        return self._request("POST", f"/network/audits/{audit_id}/cancel", {}, headers)

    def issue_findings(self, audit_id, payload, headers):
        return self._request("POST", f"/network/audits/{audit_id}/issue-findings", payload, headers)

    # --- Corrective actions ---
    def list_audit_corrective_actions(self, audit_id, headers, params=None):
        return self._request("GET", f"/network/audits/{audit_id}/corrective-actions", headers=headers, params=params)

    def list_corrective_actions(self, headers, params=None):
        return self._request("GET", "/network/corrective-actions", headers=headers, params=params)

    def get_corrective_action(self, action_id, headers):
        return self._request("GET", f"/network/corrective-actions/{action_id}", headers=headers)

    def submit_corrective_action(self, action_id, payload, headers):
        return self._request("POST", f"/network/corrective-actions/{action_id}/submit", payload, headers)

    def verify_corrective_action(self, action_id, payload, headers):
        return self._request("POST", f"/network/corrective-actions/{action_id}/verify", payload, headers)

    # --- Technicians & training ---
    def create_technician(self, shop_id, payload, headers):
        return self._request("POST", f"/network/shops/{shop_id}/technicians", payload, headers)

    def list_technicians(self, shop_id, headers, params=None):
        return self._request("GET", f"/network/shops/{shop_id}/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/network/technicians/{technician_id}", headers=headers)

    def deactivate_technician(self, technician_id, headers):
        return self._request("POST", f"/network/technicians/{technician_id}/deactivate", {}, headers)

    def create_course(self, payload, headers):
        return self._request("POST", "/network/training-courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/network/training-courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/network/training-courses/{course_id}", headers=headers)

    def create_completion(self, technician_id, payload, headers):
        return self._request("POST", f"/network/technicians/{technician_id}/course-completions", payload, headers)

    def list_completions(self, technician_id, headers, params=None):
        return self._request("GET", f"/network/technicians/{technician_id}/course-completions", headers=headers, params=params)

    def list_course_completions(self, course_id, headers, params=None):
        return self._request("GET", f"/network/training-courses/{course_id}/completions", headers=headers, params=params)

    def list_technician_repair_orders(self, technician_id, headers, params=None):
        return self._request("GET", f"/network/technicians/{technician_id}/repair-orders", headers=headers, params=params)

    def list_technician_procedure_steps(self, technician_id, headers, params=None):
        return self._request("GET", f"/network/technicians/{technician_id}/procedure-steps", headers=headers, params=params)

    def list_referral_repair_orders(self, referral_id, headers, params=None):
        return self._request("GET", f"/network/referrals/{referral_id}/repair-orders", headers=headers, params=params)

    def list_relation_repair_orders(self, relation_id, headers, params=None):
        return self._request("GET", f"/network/insurer-relations/{relation_id}/repair-orders", headers=headers, params=params)

    # --- Repair orders ---
    def create_repair_order(self, shop_id, payload, headers):
        return self._request("POST", f"/network/shops/{shop_id}/repair-orders", payload, headers)

    def list_repair_orders(self, shop_id, headers, params=None):
        return self._request("GET", f"/network/shops/{shop_id}/repair-orders", headers=headers, params=params)

    def get_repair_order(self, order_id, headers):
        return self._request("GET", f"/network/repair-orders/{order_id}", headers=headers)

    def approve_order(self, order_id, headers):
        return self._request("POST", f"/network/repair-orders/{order_id}/approve", {}, headers)

    def start_repair(self, order_id, headers):
        return self._request("POST", f"/network/repair-orders/{order_id}/start-repair", {}, headers)

    def submit_qc(self, order_id, headers):
        return self._request("POST", f"/network/repair-orders/{order_id}/submit-qc", {}, headers)

    def fail_qc(self, order_id, headers):
        return self._request("POST", f"/network/repair-orders/{order_id}/fail-qc", {}, headers)

    def pass_qc(self, order_id, headers):
        return self._request("POST", f"/network/repair-orders/{order_id}/pass-qc", {}, headers)

    def void_order(self, order_id, payload, headers):
        return self._request("POST", f"/network/repair-orders/{order_id}/void", payload, headers)

    # --- Procedure steps ---
    def create_procedure_step(self, order_id, payload, headers):
        return self._request("POST", f"/network/repair-orders/{order_id}/procedure-steps", payload, headers)

    def list_procedure_steps(self, order_id, headers, params=None):
        return self._request("GET", f"/network/repair-orders/{order_id}/procedure-steps", headers=headers, params=params)

    # --- Part line items ---
    def create_part_line(self, order_id, payload, headers):
        return self._request("POST", f"/network/repair-orders/{order_id}/part-lines", payload, headers)

    def list_part_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/network/repair-orders/{order_id}/part-lines", headers=headers, params=params)

    def delete_part_line(self, order_id, line_id, headers):
        return self._request("DELETE", f"/network/repair-orders/{order_id}/part-lines/{line_id}", headers=headers)

    # --- Warranty claims ---
    def create_warranty_claim(self, order_id, payload, headers):
        return self._request("POST", f"/network/repair-orders/{order_id}/warranty-claims", payload, headers)

    def list_warranty_claims(self, order_id, headers, params=None):
        return self._request("GET", f"/network/repair-orders/{order_id}/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/network/warranty-claims/{claim_id}", headers=headers)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/network/warranty-claims/{claim_id}/review", {}, headers)

    def escalate_claim(self, claim_id, headers):
        return self._request("POST", f"/network/warranty-claims/{claim_id}/escalate", {}, headers)

    def resolve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/network/warranty-claims/{claim_id}/resolve", payload, headers)

    # --- Insurer relations ---
    def create_insurer_relation(self, shop_id, payload, headers):
        return self._request("POST", f"/network/shops/{shop_id}/insurer-relations", payload, headers)

    def list_insurer_relations(self, shop_id, headers, params=None):
        return self._request("GET", f"/network/shops/{shop_id}/insurer-relations", headers=headers, params=params)

    def get_insurer_relation(self, relation_id, headers):
        return self._request("GET", f"/network/insurer-relations/{relation_id}", headers=headers)

    def suspend_relation(self, relation_id, headers):
        return self._request("POST", f"/network/insurer-relations/{relation_id}/suspend", {}, headers)

    def reinstate_relation(self, relation_id, headers):
        return self._request("POST", f"/network/insurer-relations/{relation_id}/reinstate", {}, headers)

    def terminate_relation(self, relation_id, headers):
        return self._request("POST", f"/network/insurer-relations/{relation_id}/terminate", {}, headers)

    # --- Referrals & locator ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/network/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/network/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/network/referrals", headers=headers, params=params)

    def route_referral(self, referral_id, headers):
        return self._request("POST", f"/network/referrals/{referral_id}/route", {}, headers)

    def accept_referral(self, referral_id, headers):
        return self._request("POST", f"/network/referrals/{referral_id}/accept", {}, headers)

    def decline_referral(self, referral_id, headers):
        return self._request("POST", f"/network/referrals/{referral_id}/decline", {}, headers)

    def locator_search(self, payload, headers=None):
        return self._request("POST", "/network/locator/search", payload, headers)

    # --- Test-driving endpoints ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/network/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/network/_sweep/run", {}, headers)


api_client = ApiClient()
