"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Every method returns the raw ``requests.Response``."""

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Institutions ─────────────────────────────────
    def create_institution(self, payload, headers):
        return self._request("POST", "/institutions", payload, headers)

    def get_institution(self, institution_id, headers):
        return self._request("GET", f"/institutions/{institution_id}", headers=headers)

    def list_institutions(self, headers, params=None):
        return self._request("GET", "/institutions", headers=headers, params=params)

    def change_capital_category(self, institution_id, payload, headers):
        return self._request(
            "PATCH", f"/institutions/{institution_id}/capital-category", payload, headers
        )

    def adjust_balances(self, institution_id, payload, headers):
        return self._request(
            "POST", f"/institutions/{institution_id}/balance-adjustments", payload, headers
        )

    def get_wholesale_funding_summary(self, institution_id, headers, params=None):
        return self._request(
            "GET",
            f"/institutions/{institution_id}/wholesale-funding-summary",
            headers=headers,
            params=params,
        )

    # ─── National rate benchmark ──────────────────────
    def publish_national_rate_cap(self, payload, headers):
        return self._request("POST", "/national-rate-caps", payload, headers)

    def list_national_rate_caps(self, headers, params=None):
        return self._request("GET", "/national-rate-caps", headers=headers, params=params)

    # ─── Counterparties ───────────────────────────────
    def create_broker(self, payload, headers):
        return self._request("POST", "/brokers", payload, headers)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/brokers/{broker_id}", headers=headers)

    def list_brokers(self, headers, params=None):
        return self._request("GET", "/brokers", headers=headers, params=params)

    # ─── Broker agreements ────────────────────────────
    def create_agreement(self, broker_id, payload, headers):
        return self._request("POST", f"/brokers/{broker_id}/agreements", payload, headers)

    def list_broker_agreements(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/brokers/{broker_id}/agreements", headers=headers, params=params
        )

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/broker-agreements/{agreement_id}", headers=headers)

    def diligence_action(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/broker-agreements/{agreement_id}/diligence-actions", payload, headers
        )

    def get_fee_summary(self, agreement_id, headers):
        return self._request(
            "GET", f"/broker-agreements/{agreement_id}/fee-summary", headers=headers
        )

    # ─── Primary purpose exceptions ───────────────────
    def create_exception(self, payload, headers):
        return self._request("POST", "/primary-purpose-exceptions", payload, headers)

    def get_exception(self, exception_id, headers):
        return self._request(
            "GET", f"/primary-purpose-exceptions/{exception_id}", headers=headers
        )

    def list_exceptions(self, headers, params=None):
        return self._request(
            "GET", "/primary-purpose-exceptions", headers=headers, params=params
        )

    def exception_filing_action(self, exception_id, payload, headers):
        return self._request(
            "POST",
            f"/primary-purpose-exceptions/{exception_id}/filing-actions",
            payload,
            headers,
        )

    def exception_review_action(self, exception_id, payload, headers):
        return self._request(
            "POST",
            f"/primary-purpose-exceptions/{exception_id}/review-actions",
            payload,
            headers,
        )

    # ─── Deposit programs ─────────────────────────────
    def create_program(self, payload, headers):
        return self._request("POST", "/deposit-programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/deposit-programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/deposit-programs", headers=headers, params=params)

    def program_state_action(self, program_id, payload, headers):
        return self._request(
            "POST", f"/deposit-programs/{program_id}/state-actions", payload, headers
        )

    # ─── Classification determinations ────────────────
    def create_classification(self, payload, headers):
        return self._request("POST", "/deposit-classifications", payload, headers)

    def get_classification(self, classification_id, headers):
        return self._request(
            "GET", f"/deposit-classifications/{classification_id}", headers=headers
        )

    def list_classifications(self, headers, params=None):
        return self._request(
            "GET", "/deposit-classifications", headers=headers, params=params
        )

    # ─── Deposit placements ───────────────────────────
    def create_placement(self, payload, headers):
        return self._request("POST", "/deposit-placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/deposit-placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/deposit-placements", headers=headers, params=params)

    def funding_action(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/deposit-placements/{placement_id}/funding-actions", payload, headers
        )

    def create_rate_cap_check(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/deposit-placements/{placement_id}/rate-cap-checks", payload, headers
        )

    def list_rate_cap_checks(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"/deposit-placements/{placement_id}/rate-cap-checks",
            headers=headers,
            params=params,
        )

    # ─── Concentration limits ─────────────────────────
    def create_concentration_limit(self, institution_id, payload, headers):
        return self._request(
            "POST", f"/institutions/{institution_id}/concentration-limits", payload, headers
        )

    def list_concentration_limits(self, institution_id, headers, params=None):
        return self._request(
            "GET",
            f"/institutions/{institution_id}/concentration-limits",
            headers=headers,
            params=params,
        )

    # ─── Liquidity contingency plans ──────────────────
    def create_contingency_plan(self, institution_id, payload, headers):
        return self._request(
            "POST", f"/institutions/{institution_id}/contingency-plans", payload, headers
        )

    def list_contingency_plans(self, institution_id, headers, params=None):
        return self._request(
            "GET",
            f"/institutions/{institution_id}/contingency-plans",
            headers=headers,
            params=params,
        )

    def get_contingency_plan(self, plan_id, headers):
        return self._request("GET", f"/contingency-plans/{plan_id}", headers=headers)

    def plan_lifecycle_action(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/contingency-plans/{plan_id}/lifecycle-actions", payload, headers
        )

    # ─── Call report filings ──────────────────────────
    def create_call_report_filing(self, institution_id, payload, headers):
        return self._request(
            "POST", f"/institutions/{institution_id}/call-report-filings", payload, headers
        )

    def list_call_report_filings(self, institution_id, headers, params=None):
        return self._request(
            "GET",
            f"/institutions/{institution_id}/call-report-filings",
            headers=headers,
            params=params,
        )

    def get_call_report_filing(self, filing_id, headers):
        return self._request("GET", f"/call-report-filings/{filing_id}", headers=headers)

    def filing_workflow_action(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/call-report-filings/{filing_id}/workflow-actions", payload, headers
        )

    # ─── Maturity sweep ───────────────────────────────
    def run_maturity_sweep(self, payload, headers):
        return self._request("POST", "/maturity-runs", payload, headers)


api_client = ApiClient()
