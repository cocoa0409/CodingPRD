"""Quote pricing arithmetic, the fundraising allocation waterfall and the
community approval percentage.

Every value asserted here is computed by the server: the tests only supply the
design content and then read back the frozen numbers.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["design_consultant_headers"]
CLIENT = TEST_USERS["client_representative_headers"]

MONEY_FIELDS = ("subtotal_cents", "freight_cents", "discount_cents", "total_cents")
ALLOCATION_BUCKETS = (
    "alloc_permit_freight_cents",
    "alloc_surfacing_cents",
    "alloc_structure_cents",
    "alloc_contingency_cents",
)


# --------------------------------------------------------------------------
# Local setup helpers
# --------------------------------------------------------------------------
def _assert_money_is_integer_cents(quote):
    for field in MONEY_FIELDS:
        a.assert_cents(quote[field], field)


def _buckets(project):
    return tuple(project[name] for name in ALLOCATION_BUCKETS)


def _rendered_project_with_one_placement(
    standard_id,
    component_model_id,
    *,
    client_name,
    age_group="TODDLER_6_23M",
    color_choice="CEDAR",
    x_start_cm=200,
    quantity=1,
):
    """A CONSULTATION project carrying one area, one DRAFT placement and an
    ISSUED rendering, ready to be priced."""
    project = fx.create_project_in_consultation(
        client_name=client_name,
        required_age_groups=[age_group],
        budget_cents=6000000,
    )
    area = fx.create_play_area(project["id"], age_group=age_group)
    fx.create_placement(
        area["id"],
        component_model_id,
        color_choice=color_choice,
        x_start_cm=x_start_cm,
        quantity=quantity,
    )
    rendering = fx.issue_rendering(project["id"], standard_id)
    return project, rendering


def _issue_provisional_quote(project_id, rendering_id):
    response = api_client.create_quote(
        f.quote_payload(
            project_id,
            rendering_id,
            fx.project_version(project_id),
            variant="PROVISIONAL",
        ),
        CONSULTANT,
    )
    return validate_success(response, 201)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_volume_discount_tier_is_selected_on_the_subtotal_alone():
    """Three PROVISIONAL quotes prove the tier is keyed on subtotal_cents and that freight is never discounted.

    PRD: "When `subtotal_cents` is at least 5000000 cents the rate is six percent; otherwise, when it is at least 2000000 cents the rate is three percent; otherwise the rate is zero."

    Design: Corner/calculations/quote_volume_discount_tier_selected_on_subtotal_alone
    """
    standard = fx.create_active_standard()
    deck = fx.create_certified_model(f.deck_model_payload())
    climber = fx.create_certified_model(
        f.climber_model_payload(sku="CLIMB-SCH-122", age_group="SCHOOL_AGE_5_12")
    )

    project_one, rendering_one = _rendered_project_with_one_placement(
        standard["id"], deck["id"], client_name="Tier Edge Park One", quantity=31
    )
    project_two, rendering_two = _rendered_project_with_one_placement(
        standard["id"], deck["id"], client_name="Tier Edge Park Two", quantity=32
    )
    project_three, rendering_three = _rendered_project_with_one_placement(
        standard["id"],
        climber["id"],
        client_name="Tier Edge Park Three",
        age_group="SCHOOL_AGE_5_12",
        color_choice="GRAPHITE",
        x_start_cm=900,
        quantity=24,
    )

    quote_one = _issue_provisional_quote(project_one["id"], rendering_one["id"])
    quote_two = _issue_provisional_quote(project_two["id"], rendering_two["id"])
    quote_three = _issue_provisional_quote(project_three["id"], rendering_three["id"])

    for quote in (quote_one, quote_two, quote_three):
        _assert_money_is_integer_cents(quote)
        a.assert_quote_arithmetic(quote)
        a.assert_freight(quote)
        assert quote["status"] == "ISSUED", (
            f"expected ISSUED, got {quote['status']} for a freshly issued quote"
        )
        assert quote["variant"] == "PROVISIONAL", (
            f"expected PROVISIONAL, got {quote['variant']}"
        )

    assert quote_one["priced_unit_count"] == 31, (
        f"expected 31 priced units, got {quote_one['priced_unit_count']}"
    )
    assert quote_one["subtotal_cents"] == 1994850, (
        f"expected subtotal 1994850, got {quote_one['subtotal_cents']}"
    )
    assert quote_one["freight_cents"] == 86750, (
        f"expected freight 86750, got {quote_one['freight_cents']}"
    )
    assert quote_one["discount_cents"] == 0, (
        "a subtotal below 2000000 earns no discount even though subtotal plus "
        f"freight clears the tier minimum, got {quote_one['discount_cents']}"
    )
    assert quote_one["total_cents"] == 2081600, (
        f"expected total 2081600, got {quote_one['total_cents']}"
    )
    assert quote_one["subtotal_cents"] + quote_one["freight_cents"] == 2081600, (
        "subtotal plus freight is 2081600, which would have selected the three "
        "percent tier had freight been included in the tier test"
    )

    assert quote_two["priced_unit_count"] == 32, (
        f"expected 32 priced units, got {quote_two['priced_unit_count']}"
    )
    assert quote_two["subtotal_cents"] == 2059200, (
        f"expected subtotal 2059200, got {quote_two['subtotal_cents']}"
    )
    assert quote_two["freight_cents"] == 88000, (
        f"expected freight 88000, got {quote_two['freight_cents']}"
    )
    assert quote_two["discount_cents"] == 61776, (
        f"expected a three percent discount of 61776, got {quote_two['discount_cents']}"
    )
    assert quote_two["total_cents"] == 2085424, (
        f"expected total 2085424, got {quote_two['total_cents']}"
    )

    assert quote_three["priced_unit_count"] == 24, (
        f"expected 24 priced units, got {quote_three['priced_unit_count']}"
    )
    assert quote_three["subtotal_cents"] == 5170800, (
        f"expected subtotal 5170800, got {quote_three['subtotal_cents']}"
    )
    assert quote_three["freight_cents"] == 78000, (
        f"expected freight 78000, got {quote_three['freight_cents']}"
    )
    assert quote_three["discount_cents"] == 310248, (
        f"expected a six percent discount of 310248, got {quote_three['discount_cents']}"
    )
    assert quote_three["total_cents"] == 4938552, (
        f"expected total 4938552, got {quote_three['total_cents']}"
    )


def test_fundraising_allocation_fills_buckets_in_order_and_overflows_to_contingency():
    """Three successive collections walk the waterfall from freight through surfacing and structure into contingency.

    PRD: "Fill the buckets in that order. `alloc_permit_freight_cents` receives the smaller of the remaining funds and the first target, and that amount leaves the remaining funds."

    PRD: "`alloc_structure_cents` receives the smaller of what now remains and the third target, and that amount leaves the remainder. `alloc_contingency_cents` receives every cent still remaining."

    Design: Corner/calculations/fundraising_allocation_fills_buckets_in_order_and_overflows_to_contingency
    """
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Willow Bend"}
    )
    project = scenario["project"]
    fx.create_validated_placement(
        scenario["area"]["id"],
        scenario["deck"]["id"],
        color_choice="SKY_BLUE",
        x_start_cm=700,
        quantity=1,
    )
    rendering = fx.issue_rendering(project["id"], scenario["standard"]["id"])
    quote = fx.issue_quote(project["id"], rendering["id"], variant="FIRM")

    _assert_money_is_integer_cents(quote)
    assert quote["subtotal_cents"] == 68855, (
        f"expected subtotal 68855, got {quote['subtotal_cents']}"
    )
    assert quote["freight_cents"] == 49250, (
        f"expected freight 49250, got {quote['freight_cents']}"
    )
    assert quote["discount_cents"] == 0, (
        f"expected no discount, got {quote['discount_cents']}"
    )
    assert quote["total_cents"] == 118105, (
        f"expected total 118105, got {quote['total_cents']}"
    )

    at_start = fx.get_project(project["id"])
    assert at_start["funds_collected_cents"] == 0, (
        "a pledge contributes nothing until it is collected, got "
        f"{at_start['funds_collected_cents']}"
    )
    assert _buckets(at_start) == (0, 0, 0, 0), (
        f"expected every bucket at zero, got {_buckets(at_start)}"
    )
    a.assert_allocation_invariant(at_start)

    first = fx.create_pledge(project["id"], amount_cents=60000)
    second = fx.create_pledge(project["id"], amount_cents=58105)
    third = fx.create_pledge(project["id"], amount_cents=11895)

    steps = (
        (first, 60000, (49250, 10750, 0, 0)),
        (second, 118105, (49250, 13771, 55084, 0)),
        (third, 130000, (49250, 13771, 55084, 11895)),
    )
    for pledge, expected_funds, expected_buckets in steps:
        collected = validate_success(api_client.collect_pledge(pledge["id"], CLIENT))
        assert collected["status"] == "COLLECTED", (
            f"expected COLLECTED, got {collected['status']}"
        )
        now = fx.get_project(project["id"])
        assert now["funds_collected_cents"] == expected_funds, (
            f"expected funds_collected_cents {expected_funds}, "
            f"got {now['funds_collected_cents']}"
        )
        assert _buckets(now) == expected_buckets, (
            f"expected buckets {expected_buckets}, got {_buckets(now)} after "
            f"collecting {pledge['amount_cents']}"
        )
        for bucket in ALLOCATION_BUCKETS:
            a.assert_cents(now[bucket], bucket)
        a.assert_allocation_invariant(now)


def test_community_approval_pct_is_recomputed_from_running_totals_to_one_decimal():
    """Two vote batches accumulate and the percentage is re-derived from the running totals each time.

    PRD: "After the batch is absorbed, `community_approval_pct` is re-derived: with no votes at all it is 0.0; otherwise it is one hundred multiplied by the accumulated `yes_votes`, divided by the sum of `yes_votes` and `no_votes`, rounded half up to exactly one decimal place."

    Design: Corner/calculations/community_approval_pct_recomputed_from_running_totals_to_one_decimal
    """
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Yarrow Field"}
    )
    project = scenario["project"]
    fx.create_placement(
        scenario["area"]["id"],
        scenario["post"]["id"],
        x_start_cm=200,
        quantity=3,
    )
    rendering = fx.issue_rendering(project["id"], scenario["standard"]["id"])

    before_any_batch = fx.get_rendering(rendering["id"])
    assert before_any_batch["yes_votes"] == 0, (
        f"expected 0 yes votes, got {before_any_batch['yes_votes']}"
    )
    assert before_any_batch["no_votes"] == 0, (
        f"expected 0 no votes, got {before_any_batch['no_votes']}"
    )
    assert before_any_batch["community_approval_pct"] == pytest.approx(0.0, abs=1e-9), (
        "with no votes at all the percentage is 0.0, got "
        f"{before_any_batch['community_approval_pct']}"
    )

    validate_success(
        api_client.record_community_votes(
            rendering["id"], f.community_votes_payload(14, 12), CLIENT
        )
    )
    after_first = fx.get_rendering(rendering["id"])
    assert after_first["yes_votes"] == 14, (
        f"expected 14 accumulated yes votes, got {after_first['yes_votes']}"
    )
    assert after_first["no_votes"] == 12, (
        f"expected 12 accumulated no votes, got {after_first['no_votes']}"
    )
    assert after_first["community_approval_pct"] == pytest.approx(53.8, abs=1e-9), (
        "14 of 26 votes is 53.8 percent to one decimal place, got "
        f"{after_first['community_approval_pct']}"
    )
    assert fx.get_project(project["id"])["design_status"] == "COMMUNITY_REVIEW", (
        "recording a batch moves the project into COMMUNITY_REVIEW"
    )

    validate_success(
        api_client.record_community_votes(
            rendering["id"], f.community_votes_payload(1, 0), CLIENT
        )
    )
    after_second = fx.get_rendering(rendering["id"])
    assert after_second["yes_votes"] == 15, (
        f"expected 15 accumulated yes votes, got {after_second['yes_votes']}"
    )
    assert after_second["no_votes"] == 12, (
        f"expected 12 accumulated no votes, got {after_second['no_votes']}"
    )
    assert after_second["community_approval_pct"] == pytest.approx(55.6, abs=1e-9), (
        "15 of 27 votes is 55.6 percent to one decimal place, got "
        f"{after_second['community_approval_pct']}"
    )
    assert fx.get_project(project["id"])["design_status"] == "COMMUNITY_REVIEW", (
        "a second batch leaves the project in COMMUNITY_REVIEW"
    )


def test_colour_uplift_applies_only_to_a_non_default_colour_choice():
    """Two otherwise identical single-deck designs differ by exactly the seven percent colour uplift.

    PRD: "When the placement's `color_choice` differs from the first element of the model's `color_options`, the raw line is the base line increased by seven percent — that is, the base line multiplied by one plus seven hundredths."

    Design: Corner/calculations/quote_colour_uplift_applies_only_to_non_default_colour_options
    """
    standard = fx.create_active_standard()
    deck = fx.create_certified_model(f.deck_model_payload())
    assert deck["color_options"][0] == "CEDAR", (
        f"the no-cost default colour is the first option, got {deck['color_options']}"
    )

    default_project, default_rendering = _rendered_project_with_one_placement(
        standard["id"],
        deck["id"],
        client_name="Colour Park Default",
        color_choice="CEDAR",
        x_start_cm=700,
    )
    uplift_project, uplift_rendering = _rendered_project_with_one_placement(
        standard["id"],
        deck["id"],
        client_name="Colour Park Uplift",
        color_choice="SKY_BLUE",
        x_start_cm=700,
    )

    default_quote = _issue_provisional_quote(
        default_project["id"], default_rendering["id"]
    )
    uplift_quote = _issue_provisional_quote(
        uplift_project["id"], uplift_rendering["id"]
    )

    for quote in (default_quote, uplift_quote):
        _assert_money_is_integer_cents(quote)
        a.assert_quote_arithmetic(quote)
        a.assert_freight(quote)
        assert quote["priced_unit_count"] == 1, (
            f"expected a single priced unit, got {quote['priced_unit_count']}"
        )
        assert quote["discount_cents"] == 0, (
            f"expected no discount, got {quote['discount_cents']}"
        )

    assert default_quote["subtotal_cents"] == 64350, (
        "the default colour prices at the unchanged base line, got "
        f"{default_quote['subtotal_cents']}"
    )
    assert default_quote["freight_cents"] == 49250, (
        f"expected freight 49250, got {default_quote['freight_cents']}"
    )
    assert default_quote["total_cents"] == 113600, (
        f"expected total 113600, got {default_quote['total_cents']}"
    )

    assert uplift_quote["subtotal_cents"] == 68855, (
        "the non-default colour prices at the base line plus seven percent, got "
        f"{uplift_quote['subtotal_cents']}"
    )
    assert uplift_quote["freight_cents"] == 49250, (
        "freight is untouched by the colour choice, got "
        f"{uplift_quote['freight_cents']}"
    )
    assert uplift_quote["total_cents"] == 118105, (
        f"expected total 118105, got {uplift_quote['total_cents']}"
    )

    assert (
        uplift_quote["subtotal_cents"] - default_quote["subtotal_cents"] == 4505
    ), (
        "the uplift is the only difference between the two subtotals, expected "
        f"4505, got {uplift_quote['subtotal_cents'] - default_quote['subtotal_cents']}"
    )
    assert uplift_quote["freight_cents"] == default_quote["freight_cents"], (
        "both designs ship one unit, so freight must be identical"
    )
