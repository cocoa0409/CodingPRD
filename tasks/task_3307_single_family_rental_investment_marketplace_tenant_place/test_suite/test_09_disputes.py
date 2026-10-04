"""Post-close disputes: condition gating, adjudication, and resolution rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLAIMS_ADJUSTER_HEADERS,
    DEFAULT_CLOCK_ISO,
    PLATFORM_ADMIN_HEADERS,
    get_success_data,
    make_buyer_headers,
    make_claims_adjuster_headers,
    make_seller_headers,
    open_dispute,
    set_clock,
    setup_closed_sale,
    validate_error,
    validate_success,
)


def _sold_ctx_with_defect(api):
    """Sold listing whose verified inspection disclosed ROOF-1."""
    set_clock(DEFAULT_CLOCK_ISO)
    ctx = setup_closed_sale(
        with_lease=True,
        listing_kwargs={
            "inspection_overrides": {
                "disclosed_defects": [
                    {"code": "ROOF-1", "severity": "LOW", "description": "minor"}
                ]
            }
        },
    )
    return ctx


class TestDisputeConditionGating:
    def test_start_evidence_with_undisclosed_condition_rejected(self, api):
        """PRD §3.9: "A `ClaimsAdjuster` starts evidence gathering (`OPENED` →
        `EVIDENCE`) only when the `condition_code` exists among the
        `disclosed_defects` codes of the listing's latest `VERIFIED` inspection
        report — latest by `inspection_date`, ties broken by `created_at`
        descending; a code the seller never disclosed is rejected with
        `ERR_DISPUTE_CONDITION_UNDISCLOSED`."

        Design: Corner/errors/error_dispute_condition_undisclosed
        """
        ctx = _sold_ctx_with_defect(api)
        buyer_h = make_buyer_headers(ctx["buyer"]["id"])
        dispute = open_dispute(
            ctx["listing"]["id"], buyer_h, condition_code="HVAC-9", remedy_cents=100_000
        )
        resp = api.transition_dispute(
            dispute["id"], {"action": "START_EVIDENCE"}, CLAIMS_ADJUSTER_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_CONDITION_UNDISCLOSED)
        disputes = get_success_data(
            api.list_disputes(ctx["listing"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert disputes[0]["status"] == "OPENED"

    def test_start_evidence_with_disclosed_condition_moves_to_evidence(self, api):
        """PRD §3.9: "A `ClaimsAdjuster` starts evidence gathering (`OPENED` →
        `EVIDENCE`) only when the `condition_code` exists among the
        `disclosed_defects` codes of the listing's latest `VERIFIED` inspection
        report — latest by `inspection_date`, ties broken by `created_at`
        descending; a code the seller never disclosed is rejected with
        `ERR_DISPUTE_CONDITION_UNDISCLOSED`."

        Design: Corner/errors/error_dispute_condition_undisclosed
        """
        ctx = _sold_ctx_with_defect(api)
        buyer_h = make_buyer_headers(ctx["buyer"]["id"])
        dispute = open_dispute(
            ctx["listing"]["id"], buyer_h, condition_code="ROOF-1", remedy_cents=100_000
        )
        moved = get_success_data(
            api.transition_dispute(
                dispute["id"], {"action": "START_EVIDENCE"}, CLAIMS_ADJUSTER_HEADERS
            )
        )
        assert moved["status"] == "EVIDENCE"


class TestDisputeResolutionControls:
    def test_resolver_equal_to_opener_rejected(self, api):
        """PRD §2.7: "Second, a dispute can only be resolved by someone other
        than the party who opened it: at resolution time, the resolver's
        `X-User-ID` is compared against the dispute's recorded
        `opener_user_id`, and equality is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Difficulty/transitive_cascade/dispute_resolution_triggers_guarantee_claim
        """
        ctx = _sold_ctx_with_defect(api)
        buyer_h = make_buyer_headers(ctx["buyer"]["id"])
        dispute = open_dispute(
            ctx["listing"]["id"], buyer_h, condition_code="ROOF-1", remedy_cents=0
        )
        get_success_data(
            api.transition_dispute(
                dispute["id"], {"action": "START_EVIDENCE"}, CLAIMS_ADJUSTER_HEADERS
            )
        )
        # Adjuster whose id equals the opener's id violates segregation.
        resp = api.transition_dispute(
            dispute["id"],
            {"action": "RESOLVE_BUYER"},
            make_claims_adjuster_headers(ctx["buyer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_resolve_seller_by_distinct_adjuster_succeeds(self, api):
        """PRD §3.9: "Resolution (`EVIDENCE` → `RESOLVED_BUYER` or `EVIDENCE` →
        `RESOLVED_SELLER`) is the adjuster's action under segregation of
        duties: the resolver's `X-User-ID` must differ from `opener_user_id`,
        else `ERR_SEGREGATION_OF_DUTIES`. Resolving for the buyer carries a
        cascade: if a guarantee in `ACTIVE` covers the listing and the
        contested `condition_code` maps to a disclosed defect, that guarantee
        moves from `ACTIVE` to `CLAIMED` with its `claim_amount_cents`
        recomputed per §3.9's claim formula. Resolving for the seller has no
        such cascade."

        Design: Difficulty/transitive_cascade/dispute_resolution_triggers_guarantee_claim
        """
        ctx = _sold_ctx_with_defect(api)
        buyer_h = make_buyer_headers(ctx["buyer"]["id"])
        dispute = open_dispute(
            ctx["listing"]["id"], buyer_h, condition_code="ROOF-1", remedy_cents=0
        )
        get_success_data(
            api.transition_dispute(
                dispute["id"], {"action": "START_EVIDENCE"}, CLAIMS_ADJUSTER_HEADERS
            )
        )
        resolved = get_success_data(
            api.transition_dispute(
                dispute["id"], {"action": "RESOLVE_SELLER"}, CLAIMS_ADJUSTER_HEADERS
            )
        )
        assert resolved["status"] == "RESOLVED_SELLER"
