"""Asset marketplace: revenue share, self-purchase, refund window, listing cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_org_owner_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_org,
    create_asset_listing_payload,
    setup_personal_and_pro_tiers,
    setup_approved_listing,
    setup_purchase,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Queue B — calculations / creator_share_tier_boundary_average_rate
# ---------------------------------------------------------------------------

class TestCreatorRevenueShare:
    def test_below_boundary_thirty_percent_split(self, api):
        """PRD §3.6: "below one hundred million cents of lifetime gross the platform
        takes 30 percent; at or above that boundary the platform takes 25 percent. The
        percentage is applied to this purchase's gross only — it is an average-rate
        tiering, not a marginal one. The platform_share_cents is the gross times the
        percentage, rounded half up to whole cents; the creator_share_cents is the
        remainder."
        PRD §3.6: "The creator org's marketplace_credit_cents — its accumulated payout
        balance, which never goes negative — increases by the creator share".

        Design: Corner/calculations/creator_share_tier_boundary_average_rate
        """
        creator, buyer, listing, purchase = setup_purchase(price_cents=200_000)
        assert purchase["gross_cents"] == 200_000
        assert purchase["platform_share_cents"] == 60_000
        assert purchase["creator_share_cents"] == 140_000

        creator_now = get_success_data(api.get_org(creator["id"], ADMIN), 200)
        assert creator_now["marketplace_credit_cents"] == 140_000


# ---------------------------------------------------------------------------
# Queue B — errors / buyer_cannot_purchase_own_listing
# ---------------------------------------------------------------------------

class TestBuyerIsCreator:
    def test_self_purchase_rejected(self, api):
        """PRD §3.6: "the server records the calling org as the purchase's
        buyer_org_id and the listing's owning org as its creator_org_id, and an org
        buying its own listing is rejected with ERR_BUYER_IS_CREATOR."

        Design: Corner/errors/buyer_cannot_purchase_own_listing
        """
        creator, listing = setup_approved_listing(price_cents=50_000, title="Own Asset")
        resp = api.purchase_asset_listing(
            listing["id"], make_org_owner_headers(creator["id"])
        )
        validate_error(resp, ApiErrorId.ERR_BUYER_IS_CREATOR.value)


# ---------------------------------------------------------------------------
# Queue B — validations / refund_after_window_returns_error
# ---------------------------------------------------------------------------

class TestRefundWindow:
    def test_refund_after_14_days_rejected(self, api):
        """PRD §3.6: "A PlatformAdmin or FinanceOps operator may refund a purchase
        within 14 days of its purchased_at timestamp; a refund attempted later, or
        against an already-REFUNDED purchase, is rejected with
        ERR_REFUND_WINDOW_EXPIRED."

        Design: Corner/validations/refund_after_window_returns_error
        """
        set_clock("2026-09-01T00:00:00Z")
        creator, buyer, listing, purchase = setup_purchase(price_cents=200_000)
        set_clock("2026-09-21T00:00:00Z")

        resp = api.refund_asset_purchase(purchase["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_EXPIRED.value)

        purchase_now = get_success_data(api.get_asset_purchase(purchase["id"], ADMIN), 200)
        assert purchase_now["purchase_status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_layers / refund_reverses_marketplace_credit_exactly
# ---------------------------------------------------------------------------

class TestRefundReversal:
    def test_refund_nets_credit_to_zero(self, api):
        """PRD §3.6: "A successful refund sets purchase_status to REFUNDED and
        decrements the creator org's marketplace_credit_cents by exactly the
        creator_share_cents the purchase added — purchase and refund net to zero."

        Design: Corner/cross_cutting_layers/refund_reverses_marketplace_credit_exactly
        """
        set_clock("2026-09-01T00:00:00Z")
        creator, buyer, listing, purchase = setup_purchase(price_cents=200_000)
        creator_after_purchase = get_success_data(api.get_org(creator["id"], ADMIN), 200)
        assert creator_after_purchase["marketplace_credit_cents"] == 140_000

        refunded = get_success_data(api.refund_asset_purchase(purchase["id"], FINANCE), 200)
        assert refunded["purchase_status"] == "REFUNDED"

        creator_after_refund = get_success_data(api.get_org(creator["id"], ADMIN), 200)
        assert creator_after_refund["marketplace_credit_cents"] == 0


# ---------------------------------------------------------------------------
# Queue B — state_machines / listing_delist_resubmit_cycle_increments_rounds
# ---------------------------------------------------------------------------

class TestListingCycle:
    def test_delist_revise_resubmit_cycle(self, api):
        """PRD §3.6: "an APPROVED listing may be delisted by its owner into DELISTED —
        which removes it from purchase but leaves historical purchases untouched — and a
        DELISTED listing may likewise be revised back to DRAFT, so the loop from DRAFT
        through review and back can repeat, each resubmission incrementing
        review_rounds."

        Design: Corner/state_machines/listing_delist_resubmit_cycle_increments_rounds
        """
        setup_personal_and_pro_tiers()
        creator = create_org("PRO", legal_name="Asset Co", contact_email="as@x.com")
        owner = make_org_owner_headers(creator["id"])
        listing = get_success_data(
            api.create_asset_listing(
                creator["id"],
                create_asset_listing_payload(title="Shader Pack", price_cents=100_000),
                owner,
            ),
            201,
        )
        get_success_data(api.submit_listing_review(listing["id"], owner), 200)
        approved = get_success_data(
            api.review_asset_listing(listing["id"], {"action": "APPROVE"}, REVIEWER), 200
        )
        assert approved["review_rounds"] == 1

        get_success_data(api.delist_asset_listing(listing["id"], owner), 200)
        get_success_data(
            api.revise_asset_listing(listing["id"], {"title": "Shader Pack v2"}, owner), 200
        )
        resubmitted = get_success_data(api.submit_listing_review(listing["id"], owner), 200)

        assert resubmitted["listing_status"] == "PENDING_REVIEW"
        assert resubmitted["review_rounds"] == 2
        assert resubmitted["title"] == "Shader Pack v2"
