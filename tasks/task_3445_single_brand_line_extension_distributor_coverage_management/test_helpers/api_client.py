"""API client: one method per endpoint defined in the PRD.

The logical-clock endpoint lives OUTSIDE the /brand-ops prefix; every
other path is under /brand-ops exactly as the PRD declares.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Brand Line Coverage API client."""

    # ------------------------------------------------------------------
    # Platform (UNPREFIXED logical clock)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        """POST /_clock/set_current_utc — advance the logical clock (runs the time sweep)."""
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Brand
    # ------------------------------------------------------------------
    def create_brand(self, payload, headers):
        """POST /brand-ops/brands — create a brand."""
        return self._request("POST", "/brand-ops/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        """GET /brand-ops/brands/{id} — get a brand with computed fields."""
        return self._request("GET", f"/brand-ops/brands/{brand_id}", headers=headers)

    def lockdown_brand(self, brand_id, reason, headers):
        """POST /brand-ops/brands/{id}/lockdown — enter PROTECTIVE_LOCKDOWN."""
        return self._request("POST", f"/brand-ops/brands/{brand_id}/lockdown",
                             {"reason": reason}, headers)

    def lift_brand_lockdown(self, brand_id, headers):
        """POST /brand-ops/brands/{id}/lift-lockdown — return to OPERATING."""
        return self._request("POST", f"/brand-ops/brands/{brand_id}/lift-lockdown",
                             {}, headers)

    # ------------------------------------------------------------------
    # ProductLine
    # ------------------------------------------------------------------
    def create_product_line(self, brand_id, payload, headers):
        """POST /brand-ops/brands/{brandId}/product-lines — create a line."""
        return self._request("POST", f"/brand-ops/brands/{brand_id}/product-lines",
                             payload, headers)

    def get_product_line(self, line_id, headers):
        """GET /brand-ops/product-lines/{id}."""
        return self._request("GET", f"/brand-ops/product-lines/{line_id}", headers=headers)

    def list_product_lines(self, headers, params=None):
        """GET /brand-ops/product-lines (brand_id, status, limit, offset)."""
        return self._request("GET", "/brand-ops/product-lines", headers=headers, params=params)

    def brand_review(self, line_id, decision, headers):
        """POST /brand-ops/product-lines/{id}/brand-review."""
        return self._request("POST", f"/brand-ops/product-lines/{line_id}/brand-review",
                             {"decision": decision}, headers)

    def launch_product_line(self, line_id, headers):
        """POST /brand-ops/product-lines/{id}/launch."""
        return self._request("POST", f"/brand-ops/product-lines/{line_id}/launch",
                             {}, headers)

    def discontinue_product_line(self, line_id, headers):
        """POST /brand-ops/product-lines/{id}/discontinue."""
        return self._request("POST", f"/brand-ops/product-lines/{line_id}/discontinue",
                             {}, headers)

    # ------------------------------------------------------------------
    # Formulation
    # ------------------------------------------------------------------
    def create_formulation(self, line_id, payload, headers):
        """POST /brand-ops/product-lines/{lineId}/formulations."""
        return self._request("POST", f"/brand-ops/product-lines/{line_id}/formulations",
                             payload, headers)

    def get_formulation(self, formulation_id, headers):
        """GET /brand-ops/formulations/{id}."""
        return self._request("GET", f"/brand-ops/formulations/{formulation_id}", headers=headers)

    def list_formulations(self, headers, params=None):
        """GET /brand-ops/formulations (product_line_id, master_formulation_id, status)."""
        return self._request("GET", "/brand-ops/formulations", headers=headers, params=params)

    def seal_formulation(self, formulation_id, headers):
        """POST /brand-ops/formulations/{id}/seal."""
        return self._request("POST", f"/brand-ops/formulations/{formulation_id}/seal",
                             {}, headers)

    # ------------------------------------------------------------------
    # ContractManufacturer
    # ------------------------------------------------------------------
    def create_contract_manufacturer(self, payload, headers):
        """POST /brand-ops/contract-manufacturers."""
        return self._request("POST", "/brand-ops/contract-manufacturers", payload, headers)

    def get_contract_manufacturer(self, manufacturer_id, headers):
        """GET /brand-ops/contract-manufacturers/{id}."""
        return self._request("GET", f"/brand-ops/contract-manufacturers/{manufacturer_id}",
                             headers=headers)

    def qualify_contract_manufacturer(self, manufacturer_id, headers):
        """POST /brand-ops/contract-manufacturers/{id}/qualify."""
        return self._request("POST",
                             f"/brand-ops/contract-manufacturers/{manufacturer_id}/qualify",
                             {}, headers)

    # ------------------------------------------------------------------
    # ConfidentialityGrant
    # ------------------------------------------------------------------
    def create_confidentiality_grant(self, payload, headers):
        """POST /brand-ops/confidentiality-grants."""
        return self._request("POST", "/brand-ops/confidentiality-grants", payload, headers)

    def get_confidentiality_grant(self, grant_id, headers):
        """GET /brand-ops/confidentiality-grants/{id}."""
        return self._request("GET", f"/brand-ops/confidentiality-grants/{grant_id}",
                             headers=headers)

    def list_confidentiality_grants(self, headers, params=None):
        """GET /brand-ops/confidentiality-grants (manufacturer_id, formulation_id, status)."""
        return self._request("GET", "/brand-ops/confidentiality-grants",
                             headers=headers, params=params)

    def grant_confidentiality_grant(self, grant_id, headers):
        """POST /brand-ops/confidentiality-grants/{id}/grant."""
        return self._request("POST", f"/brand-ops/confidentiality-grants/{grant_id}/grant",
                             {}, headers)

    def activate_confidentiality_grant(self, grant_id, headers):
        """POST /brand-ops/confidentiality-grants/{id}/activate."""
        return self._request("POST",
                             f"/brand-ops/confidentiality-grants/{grant_id}/activate",
                             {}, headers)

    def revoke_confidentiality_grant(self, grant_id, for_cause, headers):
        """POST /brand-ops/confidentiality-grants/{id}/revoke."""
        return self._request("POST", f"/brand-ops/confidentiality-grants/{grant_id}/revoke",
                             {"for_cause": for_cause}, headers)

    # ------------------------------------------------------------------
    # Distributor
    # ------------------------------------------------------------------
    def create_distributor(self, payload, headers):
        """POST /brand-ops/distributors."""
        return self._request("POST", "/brand-ops/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        """GET /brand-ops/distributors/{id} — includes computed attainment fields."""
        return self._request("GET", f"/brand-ops/distributors/{distributor_id}", headers=headers)

    def list_distributors(self, headers, params=None):
        """GET /brand-ops/distributors (home_market_id, status, limit, offset)."""
        return self._request("GET", "/brand-ops/distributors", headers=headers, params=params)

    def approve_distributor(self, distributor_id, headers):
        """POST /brand-ops/distributors/{id}/approve."""
        return self._request("POST", f"/brand-ops/distributors/{distributor_id}/approve",
                             {}, headers)

    def suspend_distributor(self, distributor_id, headers):
        """POST /brand-ops/distributors/{id}/suspend."""
        return self._request("POST", f"/brand-ops/distributors/{distributor_id}/suspend",
                             {}, headers)

    def reinstate_distributor(self, distributor_id, headers):
        """POST /brand-ops/distributors/{id}/reinstate."""
        return self._request("POST", f"/brand-ops/distributors/{distributor_id}/reinstate",
                             {}, headers)

    def terminate_distributor(self, distributor_id, headers):
        """POST /brand-ops/distributors/{id}/terminate."""
        return self._request("POST", f"/brand-ops/distributors/{distributor_id}/terminate",
                             {}, headers)

    def get_rebate_preview(self, distributor_id, reference_unit_price_cents, headers):
        """GET /brand-ops/distributors/{id}/rebate-preview (query: reference_unit_price_cents)."""
        return self._request(
            "GET", f"/brand-ops/distributors/{distributor_id}/rebate-preview",
            headers=headers,
            params={"reference_unit_price_cents": reference_unit_price_cents},
        )

    # ------------------------------------------------------------------
    # Market
    # ------------------------------------------------------------------
    def create_market(self, payload, headers):
        """POST /brand-ops/markets."""
        return self._request("POST", "/brand-ops/markets", payload, headers)

    def get_market(self, market_id, headers):
        """GET /brand-ops/markets/{id}."""
        return self._request("GET", f"/brand-ops/markets/{market_id}", headers=headers)

    def close_market(self, market_id, headers):
        """POST /brand-ops/markets/{id}/close."""
        return self._request("POST", f"/brand-ops/markets/{market_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # MarketRegistration
    # ------------------------------------------------------------------
    def create_market_registration(self, payload, headers):
        """POST /brand-ops/market-registrations."""
        return self._request("POST", "/brand-ops/market-registrations", payload, headers)

    def get_market_registration(self, registration_id, headers):
        """GET /brand-ops/market-registrations/{id}."""
        return self._request("GET", f"/brand-ops/market-registrations/{registration_id}",
                             headers=headers)

    def list_market_registrations(self, headers, params=None):
        """GET /brand-ops/market-registrations (market_id, product_line_id, formulation_id, status)."""
        return self._request("GET", "/brand-ops/market-registrations",
                             headers=headers, params=params)

    def submit_market_registration(self, registration_id, headers):
        """POST /brand-ops/market-registrations/{id}/submit."""
        return self._request("POST",
                             f"/brand-ops/market-registrations/{registration_id}/submit",
                             {}, headers)

    def approve_market_registration(self, registration_id, registration_number, headers):
        """POST /brand-ops/market-registrations/{id}/approve."""
        return self._request("POST",
                             f"/brand-ops/market-registrations/{registration_id}/approve",
                             {"registration_number": registration_number}, headers)

    def reject_market_registration(self, registration_id, reason, headers):
        """POST /brand-ops/market-registrations/{id}/reject."""
        return self._request("POST",
                             f"/brand-ops/market-registrations/{registration_id}/reject",
                             {"reason": reason}, headers)

    def revise_market_registration(self, registration_id, headers):
        """POST /brand-ops/market-registrations/{id}/revise."""
        return self._request("POST",
                             f"/brand-ops/market-registrations/{registration_id}/revise",
                             {}, headers)

    def renew_market_registration(self, registration_id, new_expires_on, headers):
        """POST /brand-ops/market-registrations/{id}/renew."""
        return self._request("POST",
                             f"/brand-ops/market-registrations/{registration_id}/renew",
                             {"new_expires_on": new_expires_on}, headers)

    def revoke_market_registration(self, registration_id, headers):
        """POST /brand-ops/market-registrations/{id}/revoke."""
        return self._request("POST",
                             f"/brand-ops/market-registrations/{registration_id}/revoke",
                             {}, headers)

    # ------------------------------------------------------------------
    # CoverageAssignment
    # ------------------------------------------------------------------
    def create_coverage_assignment(self, distributor_id, payload, headers):
        """POST /brand-ops/distributors/{distributorId}/coverage-assignments (OCC)."""
        return self._request("POST",
                             f"/brand-ops/distributors/{distributor_id}/coverage-assignments",
                             payload, headers)

    def get_coverage_assignment(self, assignment_id, headers):
        """GET /brand-ops/coverage-assignments/{id}."""
        return self._request("GET", f"/brand-ops/coverage-assignments/{assignment_id}",
                             headers=headers)

    def list_coverage_assignments(self, headers, params=None):
        """GET /brand-ops/coverage-assignments (distributor_id, market_id, product_line_id, channel, status)."""
        return self._request("GET", "/brand-ops/coverage-assignments",
                             headers=headers, params=params)

    def activate_coverage_assignment(self, assignment_id, headers):
        """POST /brand-ops/coverage-assignments/{id}/activate."""
        return self._request("POST",
                             f"/brand-ops/coverage-assignments/{assignment_id}/activate",
                             {}, headers)

    def suspend_coverage_assignment(self, assignment_id, headers):
        """POST /brand-ops/coverage-assignments/{id}/suspend."""
        return self._request("POST",
                             f"/brand-ops/coverage-assignments/{assignment_id}/suspend",
                             {}, headers)

    def resume_coverage_assignment(self, assignment_id, headers):
        """POST /brand-ops/coverage-assignments/{id}/resume."""
        return self._request("POST",
                             f"/brand-ops/coverage-assignments/{assignment_id}/resume",
                             {}, headers)

    def withdraw_coverage_assignment(self, assignment_id, headers):
        """POST /brand-ops/coverage-assignments/{id}/withdraw."""
        return self._request("POST",
                             f"/brand-ops/coverage-assignments/{assignment_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # PackFormat
    # ------------------------------------------------------------------
    def create_pack_format(self, line_id, payload, headers):
        """POST /brand-ops/product-lines/{lineId}/pack-formats."""
        return self._request("POST", f"/brand-ops/product-lines/{line_id}/pack-formats",
                             payload, headers)

    def get_pack_format(self, pack_format_id, headers):
        """GET /brand-ops/pack-formats/{id}."""
        return self._request("GET", f"/brand-ops/pack-formats/{pack_format_id}",
                             headers=headers)

    def list_pack_formats(self, headers, params=None):
        """GET /brand-ops/pack-formats (product_line_id, status)."""
        return self._request("GET", "/brand-ops/pack-formats", headers=headers, params=params)

    def tool_pack_format(self, pack_format_id, headers):
        """POST /brand-ops/pack-formats/{id}/tool."""
        return self._request("POST", f"/brand-ops/pack-formats/{pack_format_id}/tool",
                             {}, headers)

    def enter_production_pack_format(self, pack_format_id, headers):
        """POST /brand-ops/pack-formats/{id}/enter-production."""
        return self._request("POST",
                             f"/brand-ops/pack-formats/{pack_format_id}/enter-production",
                             {}, headers)

    def retire_pack_format(self, pack_format_id, headers):
        """POST /brand-ops/pack-formats/{id}/retire."""
        return self._request("POST", f"/brand-ops/pack-formats/{pack_format_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # ChannelPriceList
    # ------------------------------------------------------------------
    def create_price_list(self, pack_format_id, payload, headers):
        """POST /brand-ops/pack-formats/{packFormatId}/price-lists (OCC)."""
        return self._request("POST",
                             f"/brand-ops/pack-formats/{pack_format_id}/price-lists",
                             payload, headers)

    def get_price_list(self, price_list_id, headers):
        """GET /brand-ops/price-lists/{id}."""
        return self._request("GET", f"/brand-ops/price-lists/{price_list_id}", headers=headers)

    def list_price_lists(self, headers, params=None):
        """GET /brand-ops/price-lists (pack_format_id, channel, status)."""
        return self._request("GET", "/brand-ops/price-lists", headers=headers, params=params)

    def get_effective_price(self, pack_format_id, channel, headers, at=None):
        """GET /brand-ops/pack-formats/{id}/effective-price (query: channel, at?)."""
        params = {"channel": channel}
        if at is not None:
            params["at"] = at
        return self._request("GET",
                             f"/brand-ops/pack-formats/{pack_format_id}/effective-price",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------
    def create_promotion(self, payload, headers):
        """POST /brand-ops/promotions."""
        return self._request("POST", "/brand-ops/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        """GET /brand-ops/promotions/{id}."""
        return self._request("GET", f"/brand-ops/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers, params=None):
        """GET /brand-ops/promotions (product_line_id, channel, status)."""
        return self._request("GET", "/brand-ops/promotions", headers=headers, params=params)

    def submit_promotion(self, promotion_id, headers):
        """POST /brand-ops/promotions/{id}/submit."""
        return self._request("POST", f"/brand-ops/promotions/{promotion_id}/submit",
                             {}, headers)

    def approve_promotion(self, promotion_id, headers):
        """POST /brand-ops/promotions/{id}/approve."""
        return self._request("POST", f"/brand-ops/promotions/{promotion_id}/approve",
                             {}, headers)

    def resume_promotion(self, promotion_id, headers):
        """POST /brand-ops/promotions/{id}/resume."""
        return self._request("POST", f"/brand-ops/promotions/{promotion_id}/resume",
                             {}, headers)

    def create_redemption(self, promotion_id, pack_format_id, units, headers):
        """POST /brand-ops/promotions/{id}/redemptions."""
        return self._request("POST", f"/brand-ops/promotions/{promotion_id}/redemptions",
                             {"pack_format_id": pack_format_id, "units": units}, headers)

    # ------------------------------------------------------------------
    # CounterfeitCase
    # ------------------------------------------------------------------
    def create_counterfeit_case(self, brand_id, payload, headers):
        """POST /brand-ops/brands/{brandId}/counterfeit-cases."""
        return self._request("POST", f"/brand-ops/brands/{brand_id}/counterfeit-cases",
                             payload, headers)

    def get_counterfeit_case(self, case_id, headers):
        """GET /brand-ops/counterfeit-cases/{id}."""
        return self._request("GET", f"/brand-ops/counterfeit-cases/{case_id}", headers=headers)

    def list_counterfeit_cases(self, headers, params=None):
        """GET /brand-ops/counterfeit-cases (brand_id, market_id, status)."""
        return self._request("GET", "/brand-ops/counterfeit-cases",
                             headers=headers, params=params)

    def take_action_counterfeit_case(self, case_id, units_seized, headers):
        """POST /brand-ops/counterfeit-cases/{id}/take-action."""
        return self._request("POST",
                             f"/brand-ops/counterfeit-cases/{case_id}/take-action",
                             {"units_seized": units_seized}, headers)

    def close_counterfeit_case(self, case_id, headers):
        """POST /brand-ops/counterfeit-cases/{id}/close."""
        return self._request("POST", f"/brand-ops/counterfeit-cases/{case_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # UseCaseSubmission
    # ------------------------------------------------------------------
    def create_use_case(self, line_id, payload, headers):
        """POST /brand-ops/product-lines/{lineId}/use-cases."""
        return self._request("POST", f"/brand-ops/product-lines/{line_id}/use-cases",
                             payload, headers)

    def get_use_case(self, use_case_id, headers):
        """GET /brand-ops/use-cases/{id}."""
        return self._request("GET", f"/brand-ops/use-cases/{use_case_id}", headers=headers)

    def list_use_cases(self, headers, params=None):
        """GET /brand-ops/use-cases (product_line_id, status, submitter_ref)."""
        return self._request("GET", "/brand-ops/use-cases", headers=headers, params=params)

    def review_use_case(self, use_case_id, decision, generic_use_flag, headers):
        """POST /brand-ops/use-cases/{id}/review."""
        return self._request("POST", f"/brand-ops/use-cases/{use_case_id}/review",
                             {"decision": decision, "generic_use_flag": generic_use_flag},
                             headers)

    def publish_use_case(self, use_case_id, headers):
        """POST /brand-ops/use-cases/{id}/publish."""
        return self._request("POST", f"/brand-ops/use-cases/{use_case_id}/publish",
                             {}, headers)

    def retract_use_case(self, use_case_id, headers):
        """POST /brand-ops/use-cases/{id}/retract."""
        return self._request("POST", f"/brand-ops/use-cases/{use_case_id}/retract",
                             {}, headers)

    # ------------------------------------------------------------------
    # SellThroughReport
    # ------------------------------------------------------------------
    def create_sell_through_report(self, distributor_id, payload, headers):
        """POST /brand-ops/distributors/{distributorId}/sell-through-reports."""
        return self._request("POST",
                             f"/brand-ops/distributors/{distributor_id}/sell-through-reports",
                             payload, headers)

    def get_sell_through_report(self, report_id, headers):
        """GET /brand-ops/sell-through-reports/{id}."""
        return self._request("GET", f"/brand-ops/sell-through-reports/{report_id}",
                             headers=headers)

    def list_sell_through_reports(self, headers, params=None):
        """GET /brand-ops/sell-through-reports (distributor_id, coverage_assignment_id, period_month)."""
        return self._request("GET", "/brand-ops/sell-through-reports",
                             headers=headers, params=params)


api_client = ApiClient()
