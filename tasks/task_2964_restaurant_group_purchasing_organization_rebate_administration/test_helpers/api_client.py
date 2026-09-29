"""API client: one method per endpoint declared in the PRD's routing table.

Instant canonicalization lives here, not in the tests: the PRD declares every
instant as ISO 8601 UTC with exactly three fractional digits, so responses are
compared through canonical_instant() and never string-matched raw.
"""
import re
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalize an ISO 8601 UTC instant to exactly three fractional digits.

    '2026-08-01T00:00:00Z', '2026-08-01T00:00:00.0Z' and
    '2026-08-01T00:00:00.000000Z' all canonicalize to
    '2026-08-01T00:00:00.000Z' so that a comparison never fails on width alone.
    """
    if value is None:
        return None
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, frac, _offset = match.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{frac}Z"


class ApiClient(GenericApiClient):
    # ----------------------------------------------------- logical clock ----
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------ program tiers ----
    def create_program_tier(self, payload, headers):
        return self._request("POST", "/program-tiers", payload, headers)

    def get_program_tier(self, tier_id, headers):
        return self._request("GET", f"/program-tiers/{tier_id}", headers=headers)

    def list_program_tiers(self, headers, params=None):
        return self._request("GET", "/program-tiers", headers=headers, params=params)

    # ------------------------------------------------------- distributors ----
    def create_distributor(self, payload, headers):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/distributors/{distributor_id}", headers=headers)

    def list_distributors(self, headers, params=None):
        return self._request("GET", "/distributors", headers=headers, params=params)

    # ------------------------------------------------------------ members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def activate_member(self, member_id, headers, payload=None):
        return self._request(
            "POST", f"/members/{member_id}/activate", payload or {}, headers
        )

    def terminate_member(self, member_id, headers, payload=None):
        return self._request(
            "POST", f"/members/{member_id}/terminate", payload or {}, headers
        )

    def get_savings_report(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/savings-report", headers=headers, params=params
        )

    # ----------------------------------------------- authorization letters ----
    def create_authorization_letter(self, payload, headers):
        return self._request("POST", "/authorization-letters", payload, headers)

    def get_authorization_letter(self, letter_id, headers):
        return self._request(
            "GET", f"/authorization-letters/{letter_id}", headers=headers
        )

    def list_authorization_letters(self, headers, params=None):
        return self._request(
            "GET", "/authorization-letters", headers=headers, params=params
        )

    def countersign_letter(self, letter_id, payload, headers):
        return self._request(
            "POST", f"/authorization-letters/{letter_id}/countersign", payload, headers
        )

    def revoke_letter(self, letter_id, headers, payload=None):
        return self._request(
            "POST", f"/authorization-letters/{letter_id}/revoke", payload or {}, headers
        )

    # ------------------------------------------------- manufacturer deals ----
    def create_deal(self, payload, headers):
        return self._request("POST", "/manufacturer-deals", payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/manufacturer-deals/{deal_id}", headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/manufacturer-deals", headers=headers, params=params)

    def activate_deal(self, deal_id, headers, payload=None):
        return self._request(
            "POST", f"/manufacturer-deals/{deal_id}/activate", payload or {}, headers
        )

    def suspend_deal(self, deal_id, headers, payload=None):
        return self._request(
            "POST", f"/manufacturer-deals/{deal_id}/suspend", payload or {}, headers
        )

    def resume_deal(self, deal_id, headers, payload=None):
        return self._request(
            "POST", f"/manufacturer-deals/{deal_id}/resume", payload or {}, headers
        )

    def close_period(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/manufacturer-deals/{deal_id}/close-period", payload, headers
        )

    # -------------------------------------------------- contracted items ----
    def create_contracted_item(self, payload, headers):
        return self._request("POST", "/contracted-items", payload, headers)

    def get_contracted_item(self, item_id, headers):
        return self._request("GET", f"/contracted-items/{item_id}", headers=headers)

    def list_contracted_items(self, headers, params=None):
        return self._request("GET", "/contracted-items", headers=headers, params=params)

    # ---------------------------------------------------------- rate cards ----
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/rate-cards/{rate_card_id}", headers=headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/rate-cards", headers=headers, params=params)

    def approve_rate_card(self, rate_card_id, headers, payload=None):
        return self._request(
            "POST", f"/rate-cards/{rate_card_id}/approve", payload or {}, headers
        )

    # ------------------------------------------------------ purchase batches ----
    def create_purchase_batch(self, payload, headers):
        return self._request("POST", "/purchase-batches", payload, headers)

    def get_purchase_batch(self, batch_id, headers):
        return self._request("GET", f"/purchase-batches/{batch_id}", headers=headers)

    def list_purchase_batches(self, headers, params=None):
        return self._request("GET", "/purchase-batches", headers=headers, params=params)

    def normalize_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/purchase-batches/{batch_id}/normalize", payload or {}, headers
        )

    def renormalize_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/purchase-batches/{batch_id}/renormalize", payload or {}, headers
        )

    def accrue_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/purchase-batches/{batch_id}/accrue", payload or {}, headers
        )

    def audit_markup(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/purchase-batches/{batch_id}/audit-markup", payload or {}, headers
        )

    def request_recovery(self, batch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/purchase-batches/{batch_id}/request-recovery",
            payload or {},
            headers,
        )

    def settle_recovery(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/purchase-batches/{batch_id}/settle-recovery", payload, headers
        )

    # -------------------------------------------------------- purchase lines ----
    def create_purchase_line(self, payload, headers):
        return self._request("POST", "/purchase-lines", payload, headers)

    def get_purchase_line(self, line_id, headers):
        return self._request("GET", f"/purchase-lines/{line_id}", headers=headers)

    def list_purchase_lines(self, headers, params=None):
        return self._request("GET", "/purchase-lines", headers=headers, params=params)

    def map_purchase_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"/purchase-lines/{line_id}/map", payload, headers
        )

    # -------------------------------------------------------------- accruals ----
    def get_accrual(self, accrual_id, headers):
        return self._request("GET", f"/accruals/{accrual_id}", headers=headers)

    def list_accruals(self, headers, params=None):
        return self._request("GET", "/accruals", headers=headers, params=params)

    def validate_accrual(self, accrual_id, payload, headers):
        return self._request(
            "POST", f"/accruals/{accrual_id}/validate", payload, headers
        )

    # --------------------------------------------------- manufacturer claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/manufacturer-claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/manufacturer-claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request(
            "GET", "/manufacturer-claims", headers=headers, params=params
        )

    def reconcile_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/manufacturer-claims/{claim_id}/reconcile", payload or {}, headers
        )

    # -------------------------------------------------------------- disputes ----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def request_evidence(self, dispute_id, headers, payload=None):
        return self._request(
            "POST", f"/disputes/{dispute_id}/request-evidence", payload or {}, headers
        )

    def submit_evidence(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/submit-evidence", payload, headers
        )

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/decide", payload, headers
        )

    # ---------------------------------------------------- compliance reviews ----
    def create_compliance_review(self, payload, headers):
        return self._request("POST", "/compliance-reviews", payload, headers)

    def get_compliance_review(self, review_id, headers):
        return self._request("GET", f"/compliance-reviews/{review_id}", headers=headers)

    def list_compliance_reviews(self, headers, params=None):
        return self._request(
            "GET", "/compliance-reviews", headers=headers, params=params
        )


api_client = ApiClient()
