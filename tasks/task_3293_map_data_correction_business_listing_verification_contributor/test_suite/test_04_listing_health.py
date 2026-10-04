"""Listing health score variants and visibility boundary tests."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    flag_review,
    get_listing,
    make_auto_published_edit,
    make_contributor,
    make_listing,
    make_region,
    make_review,
    open_moderation_ticket,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_health_variants_diverge_on_under_moderation_review(api):
    """PRD §2.7: "Similarly, listing health has two variants: the public
    `health_score` computes its rating aggregate over published reviews only
    and drives the listing's `visibility`, while the `moderation_health_score`
    counts reviews sitting in `UNDER_MODERATION` at half weight in both its
    numerator and denominator and drives moderator queue prioritisation."
    PRD §3.6: "Third, health is 50 plus 4 times the chosen rating aggregate,
    plus 2 times the listing's accepted-edit count capped at 10 edits, minus
    40 times the revert rate, minus 5 when the listing is currently suspended;
    the total is rounded half-up to two decimals and clamped to the inclusive
    range 0 to 100."
    PRD §3.6: "Second, the rating aggregate is selected per variant: the
    public variant uses the `rating_avg` over published reviews (0.0 when
    none), while the moderation variant averages published ratings at full
    weight and under-moderation ratings at half weight — the sum of published
    ratings plus half the sum of under-moderation ratings, divided by the
    count of published plus half the count of under-moderation, and 0.0 when
    that denominator is zero."
    PRD §3.5: "The listing's `review_count` and `rating_avg` recompute over
    published reviews only — the mean rating rounds half-up to two decimals
    and is 0.0 when no published reviews exist — and both health variants
    recompute."

    Design: Difficulty/dual_variant_calc/health_public_vs_moderation_diverge_on_under_moderation_review
    """
    region = make_region(name="R2")
    listing = make_listing(region["id"], name="Diner Two")
    reviewer = make_contributor(region["id"], display_name="C2", email="c2@x.com")
    flagger = make_contributor(region["id"], display_name="C3", email="c3@x.com")
    review = make_review(listing["id"], reviewer["id"], rating=1,
                         text="Terrible service, waited an hour for cold food.")
    flag = flag_review(review["id"], flagger["id"], reason="OFF_TOPIC")
    open_moderation_ticket(flag["id"])

    data = get_listing(listing["id"])
    assert data["review_count"] == 0, (
        f"UNDER_MODERATION review excluded from public aggregates, "
        f"got review_count {data['review_count']}"
    )
    assert data["health_score"] == pytest.approx(50, abs=0.005), (
        f"public variant: 50 + 4*0.0 = 50, got {data['health_score']}"
    )
    # Moderation variant per PRD §3.6: numerator 0 + 0.5*1 = 0.5, denominator
    # 0 + 0.5*1 = 0.5, aggregate 1.0 -> 50 + 4*1 = 54. (The variants diverge:
    # public excludes the review, moderation counts it at half weight.)
    assert data["moderation_health_score"] == pytest.approx(54, abs=0.005), (
        f"moderation variant: 50 + 4*((0.5*1)/(0.5*1)) = 54, "
        f"got {data['moderation_health_score']}"
    )


def test_moderation_variant_weights_under_moderation_at_half(api):
    """PRD §3.6: "Second, the rating aggregate is selected per variant: the
    public variant uses the `rating_avg` over published reviews (0.0 when
    none), while the moderation variant averages published ratings at full
    weight and under-moderation ratings at half weight — the sum of published
    ratings plus half the sum of under-moderation ratings, divided by the
    count of published plus half the count of under-moderation, and 0.0 when
    that denominator is zero."

    Design: Difficulty/dual_variant_calc/health_public_vs_moderation_diverge_on_under_moderation_review
    """
    region = make_region(name="R2b")
    listing = make_listing(region["id"], name="Diner Two B")
    reviewer = make_contributor(region["id"], display_name="C2b", email="c2b@x.com")
    flagger = make_contributor(region["id"], display_name="C3b", email="c3b@x.com")
    review = make_review(listing["id"], reviewer["id"], rating=1,
                         text="Terrible service, waited an hour for cold food.")

    before = get_listing(listing["id"])
    # While PUBLISHED both variants use the full-weight aggregate: 50 + 4*1.
    assert before["health_score"] == pytest.approx(54, abs=0.005)
    assert before["moderation_health_score"] == pytest.approx(54, abs=0.005)

    flag = flag_review(review["id"], flagger["id"], reason="OFF_TOPIC")
    open_moderation_ticket(flag["id"])

    after = get_listing(listing["id"])
    # Public variant excludes the under-moderation review outright.
    assert after["health_score"] == pytest.approx(50, abs=0.005)
    # Moderation variant: numerator 0 + 0.5*1 = 0.5; denominator 0 + 0.5 = 0.5;
    # aggregate 0.5/0.5 = 1.0 -> 50 + 4*1 = 54.
    assert after["moderation_health_score"] == pytest.approx(54, abs=0.005)


def test_health_restrict_threshold_boundary(api):
    """PRD §3.6: "First, the revert rate is computed over the trailing 30
    days: among the listing's edits created within that window, the number
    reverted is divided by the number published plus the number reverted, with
    a denominator floor of one — and reverted edits are not double-counted as
    published."
    PRD §3.6: "Third, health is 50 plus 4 times the chosen rating aggregate,
    plus 2 times the listing's accepted-edit count capped at 10 edits, minus
    40 times the revert rate, minus 5 when the listing is currently suspended;
    the total is rounded half-up to two decimals and clamped to the inclusive
    range 0 to 100."
    PRD §3.2: "A listing's `visibility` derives from status and health:
    `SUSPENDED` and `PERMANENTLY_CLOSED` listings are always `HIDDEN`;
    otherwise, a listing whose public health score falls below 30 becomes
    `RESTRICTED`; everything else is `PUBLIC`."

    Design: Corner/calculations/health_restrict_threshold_boundary
    """
    region = make_region(name="RH")
    listing = make_listing(region["id"], name="Health Biz")
    reviewer = make_contributor(region["id"], display_name="H1", email="h1@x.com")
    editor = make_contributor(region["id"], display_name="H2", email="h2@x.com")
    make_review(listing["id"], reviewer["id"], rating=1,
                text="Awful experience, never coming back here again.")
    edit = make_auto_published_edit(listing, editor["id"])
    assert edit["status"] == "PUBLISHED"

    resp = api.revert_map_edit(edit["id"], TEST_USERS["policy_analyst_headers"])
    validate_success(resp)

    data = get_listing(listing["id"])
    # revert_rate = 1 / max(1, 0 + 1) = 1.0; accepted_edit_count back to 0;
    # health = 50 + 4*1 + 0 - 40*1.0 - 0 = 14.
    assert data["accepted_edit_count"] == 0
    assert data["health_score"] == pytest.approx(14, abs=0.005), (
        f"50 + 4*1 - 40*1.0 = 14, got {data['health_score']}"
    )
    assert data["visibility"] == "RESTRICTED", (
        f"health below 30 must make visibility RESTRICTED, got {data['visibility']}"
    )
