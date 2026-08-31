"""API client: one method per endpoint published in the PRD's endpoint table.

Every collection is mounted at the root path.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Firm ─────────────────────────────────────────

    def create_firm(self, payload, headers):
        return self._request("POST", "/firms", payload, headers)

    def get_firm(self, firm_id, headers):
        return self._request("GET", f"/firms/{firm_id}", headers=headers)

    # ─── Recall ───────────────────────────────────────

    def create_recall(self, payload, headers):
        return self._request("POST", "/recalls", payload, headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/recalls", headers=headers, params=params)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/recalls/{recall_id}", headers=headers)

    def classify_recall(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/classify", payload, headers
        )

    def run_checkpoint(self, recall_id, headers):
        return self._request("POST", f"/recalls/{recall_id}/checkpoint", {}, headers)

    def get_effectiveness(self, recall_id, headers):
        return self._request(
            "GET", f"/recalls/{recall_id}/effectiveness", headers=headers
        )

    def request_termination(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/request-termination", payload, headers
        )

    def decide_termination(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/decide-termination", payload, headers
        )

    # ─── HazardEvaluation ─────────────────────────────

    def create_hazard_evaluation(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/hazard-evaluations", payload, headers
        )

    def list_hazard_evaluations(self, recall_id, headers, params=None):
        return self._request(
            "GET", f"/recalls/{recall_id}/hazard-evaluations",
            headers=headers, params=params,
        )

    def submit_hazard_evaluation(self, evaluation_id, headers):
        return self._request(
            "POST", f"/hazard-evaluations/{evaluation_id}/submit", {}, headers
        )

    def decide_hazard_evaluation(self, evaluation_id, payload, headers):
        return self._request(
            "POST", f"/hazard-evaluations/{evaluation_id}/decide", payload, headers
        )

    # ─── Consignee ────────────────────────────────────

    def create_consignee(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/consignees", payload, headers
        )

    def list_consignees(self, recall_id, headers, params=None):
        return self._request(
            "GET", f"/recalls/{recall_id}/consignees", headers=headers, params=params
        )

    def get_consignee(self, consignee_id, headers):
        return self._request("GET", f"/consignees/{consignee_id}", headers=headers)

    def list_sub_consignees(self, consignee_id, headers, params=None):
        return self._request(
            "GET", f"/consignees/{consignee_id}/sub-consignees",
            headers=headers, params=params,
        )

    # ─── DistributionRecord ───────────────────────────

    def create_distribution_record(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/distribution-records", payload, headers
        )

    def list_distribution_records(self, recall_id, headers, params=None):
        return self._request(
            "GET", f"/recalls/{recall_id}/distribution-records",
            headers=headers, params=params,
        )

    def list_consignee_distribution_records(self, consignee_id, headers, params=None):
        return self._request(
            "GET", f"/consignees/{consignee_id}/distribution-records",
            headers=headers, params=params,
        )

    def reconcile_distribution_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/distribution-records/{record_id}/reconcile", payload, headers
        )

    # ─── ConsigneeNotification ────────────────────────

    def create_notification(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/notifications", payload, headers
        )

    def list_notifications(self, recall_id, headers, params=None):
        return self._request(
            "GET", f"/recalls/{recall_id}/notifications",
            headers=headers, params=params,
        )

    def list_consignee_notifications(self, consignee_id, headers, params=None):
        return self._request(
            "GET", f"/consignees/{consignee_id}/notifications",
            headers=headers, params=params,
        )

    def record_delivery(self, notification_id, payload, headers):
        return self._request(
            "POST", f"/notifications/{notification_id}/delivery", payload, headers
        )

    def record_response(self, notification_id, payload, headers):
        return self._request(
            "POST", f"/notifications/{notification_id}/response", payload, headers
        )

    # ─── RetrievalReceipt ─────────────────────────────

    def create_retrieval_receipt(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/retrieval-receipts", payload, headers
        )

    def list_retrieval_receipts(self, recall_id, headers, params=None):
        return self._request(
            "GET", f"/recalls/{recall_id}/retrieval-receipts",
            headers=headers, params=params,
        )

    def list_consignee_retrieval_receipts(self, consignee_id, headers, params=None):
        return self._request(
            "GET", f"/consignees/{consignee_id}/retrieval-receipts",
            headers=headers, params=params,
        )

    def verify_retrieval_receipt(self, receipt_id, payload, headers):
        return self._request(
            "POST", f"/retrieval-receipts/{receipt_id}/verify", payload, headers
        )

    # ─── PublicWarning ────────────────────────────────

    def create_public_warning(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/public-warnings", payload, headers
        )

    def list_public_warnings(self, recall_id, headers, params=None):
        return self._request(
            "GET", f"/recalls/{recall_id}/public-warnings",
            headers=headers, params=params,
        )

    def submit_public_warning(self, warning_id, headers):
        return self._request(
            "POST", f"/public-warnings/{warning_id}/submit", {}, headers
        )

    def review_public_warning(self, warning_id, payload, headers):
        return self._request(
            "POST", f"/public-warnings/{warning_id}/review", payload, headers
        )

    def publish_public_warning(self, warning_id, headers):
        return self._request(
            "POST", f"/public-warnings/{warning_id}/publish", {}, headers
        )

    # ─── DispositionOrder ─────────────────────────────

    def create_disposition_order(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/disposition-orders", payload, headers
        )

    def list_disposition_orders(self, recall_id, headers, params=None):
        return self._request(
            "GET", f"/recalls/{recall_id}/disposition-orders",
            headers=headers, params=params,
        )

    def authorize_disposition_order(self, order_id, headers):
        return self._request(
            "POST", f"/disposition-orders/{order_id}/authorize", {}, headers
        )

    def execute_disposition_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/disposition-orders/{order_id}/execute", payload, headers
        )

    def verify_disposition_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/disposition-orders/{order_id}/verify", payload, headers
        )

    # ─── StatusReport ─────────────────────────────────

    def create_status_report(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/status-reports", payload, headers
        )

    def list_status_reports(self, recall_id, headers, params=None):
        return self._request(
            "GET", f"/recalls/{recall_id}/status-reports",
            headers=headers, params=params,
        )

    def submit_status_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/status-reports/{report_id}/submit", payload, headers
        )

    def adjudicate_status_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/status-reports/{report_id}/adjudicate", payload, headers
        )

    # ─── CostEntry ────────────────────────────────────

    def create_cost_entry(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/cost-entries", payload, headers
        )

    def list_cost_entries(self, recall_id, headers, params=None):
        return self._request(
            "GET", f"/recalls/{recall_id}/cost-entries",
            headers=headers, params=params,
        )

    def adjudicate_cost_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/cost-entries/{entry_id}/adjudicate", payload, headers
        )

    # ─── InsuranceClaim ───────────────────────────────

    def create_insurance_claim(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/recalls/{recall_id}/insurance-claims", payload, headers
        )

    def list_insurance_claims(self, recall_id, headers, params=None):
        return self._request(
            "GET", f"/recalls/{recall_id}/insurance-claims",
            headers=headers, params=params,
        )

    def submit_insurance_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/submit", {}, headers
        )

    def adjudicate_insurance_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/insurance-claims/{claim_id}/adjudicate", payload, headers
        )


api_client = ApiClient()
