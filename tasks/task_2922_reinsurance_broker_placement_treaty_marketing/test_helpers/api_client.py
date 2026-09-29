"""API client: one method per endpoint declared in the PRD (§4).

Every method returns the raw ``requests.Response`` so tests can assert on the
HTTP status code as well as on the envelope. There is no path prefix — every
endpoint is rooted at the service origin (PRD §4).
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Cedents (PRD §3.1)
    # ------------------------------------------------------------------
    def create_cedent(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cedents", payload, headers)

    def list_cedents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cedents", headers=headers, params=params)

    def get_cedent(self, cedent_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cedents/{cedent_id}", headers=headers)

    def suspend_cedent(self, cedent_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/cedents/{cedent_id}/suspension", payload, headers)

    def list_cedent_programs(
        self, cedent_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/cedents/{cedent_id}/programs", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Reinsurers (PRD §3.1)
    # ------------------------------------------------------------------
    def create_reinsurer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/reinsurers", payload, headers)

    def list_reinsurers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/reinsurers", headers=headers, params=params)

    def get_reinsurer(self, reinsurer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reinsurers/{reinsurer_id}", headers=headers)

    def set_security_status(
        self, reinsurer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reinsurers/{reinsurer_id}/security-status", payload, headers
        )

    def list_reinsurer_signing_lines(
        self, reinsurer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/reinsurers/{reinsurer_id}/signing-lines", headers=headers, params=params
        )

    def list_reinsurer_market_submissions(
        self, reinsurer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/reinsurers/{reinsurer_id}/market-submissions",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Programs (PRD §3.1, §3.4, §3.5, §3.7, §3.9)
    # ------------------------------------------------------------------
    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/programs", payload, headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def go_to_market(self, program_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/go-to-market", {}, headers)

    def bind_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/bind", {}, headers)

    def settle_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/settle", {}, headers)

    def withdraw_program(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/withdraw", payload, headers)

    def market_sweep(self, program_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/market-sweep", {}, headers)

    def documentation_checkpoint(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/programs/{program_id}/documentation-checkpoint", {}, headers
        )

    # ------------------------------------------------------------------
    # Exposure submissions (PRD §3.2)
    # ------------------------------------------------------------------
    def create_exposure_submission(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/programs/{program_id}/exposure-submissions", payload, headers
        )

    def list_program_exposure_submissions(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/programs/{program_id}/exposure-submissions",
            headers=headers,
            params=params,
        )

    def list_exposure_submissions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/exposure-submissions", headers=headers, params=params)

    def get_exposure_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/exposure-submissions/{submission_id}", headers=headers)

    def submit_exposure_for_review(self, submission_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/exposure-submissions/{submission_id}/submit-for-review", {}, headers
        )

    def signoff_exposure_submission(
        self, submission_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/exposure-submissions/{submission_id}/signoff", payload, headers
        )

    def revise_exposure_submission(
        self, submission_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/exposure-submissions/{submission_id}/revise", payload, headers
        )

    # ------------------------------------------------------------------
    # Layers (PRD §3.3)
    # ------------------------------------------------------------------
    def create_layer(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/layers", payload, headers)

    def list_program_layers(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/programs/{program_id}/layers", headers=headers, params=params
        )

    def list_layers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/layers", headers=headers, params=params)

    def get_layer(self, layer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/layers/{layer_id}", headers=headers)

    def update_layer(self, layer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/layers/{layer_id}", payload, headers)

    def sign_down_layer(self, layer_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/layers/{layer_id}/sign-down", {}, headers)

    # ------------------------------------------------------------------
    # Market submissions and quotes (PRD §3.4)
    # ------------------------------------------------------------------
    def create_market_submission(
        self, layer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/layers/{layer_id}/market-submissions", payload, headers)

    def list_layer_market_submissions(
        self, layer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/layers/{layer_id}/market-submissions", headers=headers, params=params
        )

    def list_market_submissions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/market-submissions", headers=headers, params=params)

    def get_market_submission(self, market_submission_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/market-submissions/{market_submission_id}", headers=headers
        )

    def create_quote(
        self, market_submission_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/market-submissions/{market_submission_id}/quotes", payload, headers
        )

    def list_market_submission_quotes(
        self, market_submission_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/market-submissions/{market_submission_id}/quotes",
            headers=headers,
            params=params,
        )

    def list_quotes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def counter_quote(self, quote_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/quotes/{quote_id}/counter", payload, headers)

    def requote(self, quote_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/quotes/{quote_id}/requote", payload, headers)

    def decline_quote(
        self, quote_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request("POST", f"/quotes/{quote_id}/decline", payload or {}, headers)

    def firm_order(self, quote_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/quotes/{quote_id}/firm-order", payload, headers)

    # ------------------------------------------------------------------
    # Signing lines (PRD §3.5, §3.6)
    # ------------------------------------------------------------------
    def list_signing_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/signing-lines", headers=headers, params=params)

    def list_layer_signing_lines(
        self, layer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/layers/{layer_id}/signing-lines", headers=headers, params=params
        )

    def get_signing_line(self, signing_line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/signing-lines/{signing_line_id}", headers=headers)

    def release_signing_line(self, signing_line_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/signing-lines/{signing_line_id}/release", {}, headers
        )

    # ------------------------------------------------------------------
    # Brokerage disclosures (PRD §3.6)
    # ------------------------------------------------------------------
    def create_brokerage_disclosure(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/programs/{program_id}/brokerage-disclosures", payload, headers
        )

    def list_program_brokerage_disclosures(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/programs/{program_id}/brokerage-disclosures",
            headers=headers,
            params=params,
        )

    def list_brokerage_disclosures(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/brokerage-disclosures", headers=headers, params=params)

    def get_brokerage_disclosure(self, disclosure_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/brokerage-disclosures/{disclosure_id}", headers=headers)

    def disclose_brokerage(self, disclosure_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/brokerage-disclosures/{disclosure_id}/disclose", {}, headers
        )

    def decide_brokerage_disclosure(
        self, disclosure_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/brokerage-disclosures/{disclosure_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Contract documents (PRD §3.7)
    # ------------------------------------------------------------------
    def create_contract_document(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/programs/{program_id}/contract-documents", payload, headers
        )

    def list_program_contract_documents(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/programs/{program_id}/contract-documents", headers=headers, params=params
        )

    def list_contract_documents(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/contract-documents", headers=headers, params=params)

    def get_contract_document(self, document_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/contract-documents/{document_id}", headers=headers)

    # ------------------------------------------------------------------
    # Fiduciary transactions (PRD §3.8)
    # ------------------------------------------------------------------
    def create_fiduciary_transaction(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/programs/{program_id}/fiduciary-transactions", payload, headers
        )

    def list_program_fiduciary_transactions(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/programs/{program_id}/fiduciary-transactions",
            headers=headers,
            params=params,
        )

    def list_fiduciary_transactions(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/fiduciary-transactions", headers=headers, params=params)

    def get_fiduciary_transaction(self, transaction_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/fiduciary-transactions/{transaction_id}", headers=headers)

    def approve_fiduciary_transaction(self, transaction_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fiduciary-transactions/{transaction_id}/approve", {}, headers
        )

    def settle_fiduciary_transaction(self, transaction_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fiduciary-transactions/{transaction_id}/settle", {}, headers
        )

    def reverse_fiduciary_transaction(self, transaction_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/fiduciary-transactions/{transaction_id}/reverse", {}, headers
        )

    # ------------------------------------------------------------------
    # Claim advocacies and cession disputes (PRD §3.9)
    # ------------------------------------------------------------------
    def create_claim_advocacy(
        self, layer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/layers/{layer_id}/claim-advocacies", payload, headers)

    def list_layer_claim_advocacies(
        self, layer_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/layers/{layer_id}/claim-advocacies", headers=headers, params=params
        )

    def list_claim_advocacies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/claim-advocacies", headers=headers, params=params)

    def get_claim_advocacy(self, claim_advocacy_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/claim-advocacies/{claim_advocacy_id}", headers=headers)

    def review_claim_advocacy(self, claim_advocacy_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/claim-advocacies/{claim_advocacy_id}/review", {}, headers
        )

    def withdraw_claim_advocacy(self, claim_advocacy_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/claim-advocacies/{claim_advocacy_id}/withdraw", {}, headers
        )

    def set_advocacy_route(
        self, claim_advocacy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/claim-advocacies/{claim_advocacy_id}/advocacy-route", payload, headers
        )

    def create_cession_dispute(
        self, claim_advocacy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/claim-advocacies/{claim_advocacy_id}/cession-disputes", payload, headers
        )

    def list_advocacy_cession_disputes(
        self, claim_advocacy_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/claim-advocacies/{claim_advocacy_id}/cession-disputes",
            headers=headers,
            params=params,
        )

    def create_collection(
        self, claim_advocacy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/claim-advocacies/{claim_advocacy_id}/collections", payload, headers
        )

    def list_cession_disputes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cession-disputes", headers=headers, params=params)

    def get_cession_dispute(self, dispute_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cession-disputes/{dispute_id}", headers=headers)

    def resolve_cession_dispute(
        self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/cession-disputes/{dispute_id}/resolve", payload, headers)

    # ------------------------------------------------------------------
    # Renewal reports (PRD §3.9)
    # ------------------------------------------------------------------
    def create_renewal_report(self, program_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/renewal-reports", {}, headers)

    def list_program_renewal_reports(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/programs/{program_id}/renewal-reports", headers=headers, params=params
        )

    def list_renewal_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/renewal-reports", headers=headers, params=params)

    def get_renewal_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/renewal-reports/{report_id}", headers=headers)


api_client = ApiClient()
