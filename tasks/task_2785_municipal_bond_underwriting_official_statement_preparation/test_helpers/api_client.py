"""Typed HTTP surface for the municipal bond underwriting API.

One method per row of PRD.md section 4, so no test body ever spells a URL.
Every method returns the raw ``requests.Response``; validation is the caller's
job via the framework validators.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

PREFIX = API_PREFIX


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the ``/bond-offerings`` namespace."""

    # ------------------------------------------------------------------
    # Issuers (PRD section 3.1)
    # ------------------------------------------------------------------
    def create_issuer(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/issuers", payload, headers)

    def list_issuers(self, headers=None, **params):
        return self._request(
            "GET", f"{PREFIX}/issuers", headers=headers, params=params or None
        )

    def get_issuer(self, issuer_id, headers=None):
        return self._request("GET", f"{PREFIX}/issuers/{issuer_id}", headers=headers)

    # ------------------------------------------------------------------
    # Firms (PRD section 3.1)
    # ------------------------------------------------------------------
    def create_firm(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/firms", payload, headers)

    def list_firms(self, headers=None, **params):
        return self._request(
            "GET", f"{PREFIX}/firms", headers=headers, params=params or None
        )

    def get_firm(self, firm_id, headers=None):
        return self._request("GET", f"{PREFIX}/firms/{firm_id}", headers=headers)

    def list_firm_syndicate_memberships(self, firm_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/firms/{firm_id}/syndicate-memberships",
            headers=headers,
            params=params or None,
        )

    # ------------------------------------------------------------------
    # Deals (PRD sections 3.2, 3.6, 3.8, 3.9)
    # ------------------------------------------------------------------
    def create_deal(self, payload, headers=None):
        return self._request("POST", f"{PREFIX}/deals", payload, headers)

    def list_deals(self, headers=None, **params):
        return self._request(
            "GET", f"{PREFIX}/deals", headers=headers, params=params or None
        )

    def get_deal(self, deal_id, headers=None):
        return self._request("GET", f"{PREFIX}/deals/{deal_id}", headers=headers)

    def submit_structure(self, deal_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/submit-structure", payload or {}, headers
        )

    def designate_sale_method(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/designate-sale-method", payload, headers
        )

    def price_deal(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/price", payload, headers
        )

    def award_deal(self, deal_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/award", payload or {}, headers
        )

    def post_issuance_handoff(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/post-issuance-handoff", payload, headers
        )

    def yield_restriction_analysis(self, deal_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/deals/{deal_id}/yield-restriction-analysis",
            payload,
            headers,
        )

    def close_deal(self, deal_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/close", payload or {}, headers
        )

    def cancel_deal(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Maturity tranches (PRD section 3.2)
    # ------------------------------------------------------------------
    def create_maturity_tranche(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/maturity-tranches", payload, headers
        )

    def list_deal_maturity_tranches(self, deal_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/deals/{deal_id}/maturity-tranches",
            headers=headers,
            params=params or None,
        )

    def list_maturity_tranches(self, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/maturity-tranches",
            headers=headers,
            params=params or None,
        )

    def get_maturity_tranche(self, tranche_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/maturity-tranches/{tranche_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Credit enhancements (PRD section 3.3)
    # ------------------------------------------------------------------
    def create_credit_enhancement(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/credit-enhancements", payload, headers
        )

    def list_deal_credit_enhancements(self, deal_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/deals/{deal_id}/credit-enhancements",
            headers=headers,
            params=params or None,
        )

    def commit_credit_enhancement(self, enhancement_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/credit-enhancements/{enhancement_id}/commit",
            payload or {},
            headers,
        )

    def withdraw_credit_enhancement(self, enhancement_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/credit-enhancements/{enhancement_id}/withdraw",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Official statements (PRD section 3.4)
    # ------------------------------------------------------------------
    def create_official_statement(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/official-statements", payload, headers
        )

    def list_deal_official_statements(self, deal_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/deals/{deal_id}/official-statements",
            headers=headers,
            params=params or None,
        )

    def get_official_statement(self, statement_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/official-statements/{statement_id}", headers=headers
        )

    def submit_for_review(self, statement_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/official-statements/{statement_id}/submit-for-review",
            payload or {},
            headers,
        )

    def request_revision(self, statement_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/official-statements/{statement_id}/request-revision",
            payload,
            headers,
        )

    def resume_drafting(self, statement_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/official-statements/{statement_id}/resume-drafting",
            payload or {},
            headers,
        )

    def post_preliminary(self, statement_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/official-statements/{statement_id}/post-preliminary",
            payload or {},
            headers,
        )

    def post_final(self, statement_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/official-statements/{statement_id}/post-final",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Official statement sections (PRD section 3.4)
    # ------------------------------------------------------------------
    def create_section(self, statement_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/official-statements/{statement_id}/sections",
            payload,
            headers,
        )

    def list_statement_sections(self, statement_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/official-statements/{statement_id}/sections",
            headers=headers,
            params=params or None,
        )

    def list_os_sections(self, headers=None, **params):
        return self._request(
            "GET", f"{PREFIX}/os-sections", headers=headers, params=params or None
        )

    def get_os_section(self, section_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/os-sections/{section_id}", headers=headers
        )

    def approve_section(self, section_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/os-sections/{section_id}/approve",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Continuing disclosure undertakings (PRD section 3.4)
    # ------------------------------------------------------------------
    def create_undertaking(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/undertakings", payload, headers
        )

    def list_deal_undertakings(self, deal_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/deals/{deal_id}/undertakings",
            headers=headers,
            params=params or None,
        )

    def activate_undertaking(self, undertaking_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/undertakings/{undertaking_id}/activate",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Rating engagements (PRD section 3.5)
    # ------------------------------------------------------------------
    def create_rating_engagement(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/rating-engagements", payload, headers
        )

    def list_deal_rating_engagements(self, deal_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/deals/{deal_id}/rating-engagements",
            headers=headers,
            params=params or None,
        )

    def get_rating_engagement(self, engagement_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/rating-engagements/{engagement_id}", headers=headers
        )

    def acknowledge_engagement(self, engagement_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/rating-engagements/{engagement_id}/acknowledge",
            payload or {},
            headers,
        )

    def request_info(self, engagement_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/rating-engagements/{engagement_id}/request-info",
            payload,
            headers,
        )

    def respond_info(self, engagement_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/rating-engagements/{engagement_id}/respond-info",
            payload,
            headers,
        )

    def assign_rating(self, engagement_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/rating-engagements/{engagement_id}/assign-rating",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Rating presentations (PRD section 3.5)
    # ------------------------------------------------------------------
    def create_presentation(self, engagement_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/rating-engagements/{engagement_id}/presentations",
            payload,
            headers,
        )

    def list_engagement_presentations(self, engagement_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/rating-engagements/{engagement_id}/presentations",
            headers=headers,
            params=params or None,
        )

    def get_presentation(self, presentation_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/rating-presentations/{presentation_id}", headers=headers
        )

    def cancel_presentation(self, presentation_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/rating-presentations/{presentation_id}/cancel",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Syndicate members (PRD section 3.6)
    # ------------------------------------------------------------------
    def create_syndicate_member(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/syndicate-members", payload, headers
        )

    def list_deal_syndicate_members(self, deal_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/deals/{deal_id}/syndicate-members",
            headers=headers,
            params=params or None,
        )

    # ------------------------------------------------------------------
    # Order periods and orders (PRD section 3.7)
    # ------------------------------------------------------------------
    def create_order_period(self, deal_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/deals/{deal_id}/order-periods", payload, headers
        )

    def list_deal_order_periods(self, deal_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/deals/{deal_id}/order-periods",
            headers=headers,
            params=params or None,
        )

    def get_order_period(self, period_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/order-periods/{period_id}", headers=headers
        )

    def open_order_period(self, period_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/order-periods/{period_id}/open", payload or {}, headers
        )

    def close_order_period(self, period_id, payload=None, headers=None):
        return self._request(
            "POST", f"{PREFIX}/order-periods/{period_id}/close", payload or {}, headers
        )

    def reopen_order_period(self, period_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/order-periods/{period_id}/reopen", payload, headers
        )

    def create_order(self, period_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/order-periods/{period_id}/orders", payload, headers
        )

    def list_period_orders(self, period_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/order-periods/{period_id}/orders",
            headers=headers,
            params=params or None,
        )

    def list_orders(self, headers=None, **params):
        return self._request(
            "GET", f"{PREFIX}/orders", headers=headers, params=params or None
        )

    def get_order(self, order_id, headers=None):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def cancel_order(self, order_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Closing documents (PRD section 3.9)
    # ------------------------------------------------------------------
    def list_deal_closing_documents(self, deal_id, headers=None, **params):
        return self._request(
            "GET",
            f"{PREFIX}/deals/{deal_id}/closing-documents",
            headers=headers,
            params=params or None,
        )

    def get_closing_document(self, document_id, headers=None):
        return self._request(
            "GET", f"{PREFIX}/closing-documents/{document_id}", headers=headers
        )

    def execute_closing_document(self, document_id, payload, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/closing-documents/{document_id}/execute",
            payload,
            headers,
        )

    def waive_closing_document(self, document_id, payload, headers=None):
        return self._request(
            "POST", f"{PREFIX}/closing-documents/{document_id}/waive", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock capability (PRD sections 2.4, 4)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers=None):
        """Move the logical clock. Returns ``current_utc`` and ``held_presentation_ids``."""
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload, headers=None):
        """Move the logical clock with an arbitrary payload, for shape testing."""
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
