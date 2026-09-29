"""The seven-day cooling gap between promotional windows on one channel.

An approved July discount on CORE12 holds 2026-07-01 through 2026-07-31. Filings six days
away on either side are refused and filings exactly seven days away are accepted, while the
identical July window on a second template is free.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_approved_promotion,
    create_franchisee,
    create_promotion_payload,
    create_published_plan_template,
    make_franchise_owner_headers,
    read_promotion,
)

BRAND = TEST_USERS["brand_administrator_headers"]


def _july_discount_on_one_of_two_templates() -> dict:
    """One operator, two published templates, and an APPROVED July promotion on the first."""
    franchisee = create_franchisee(
        legal_name="Cadence Fitness LLC", contact_email="ops@cadencefit.example"
    )
    core = create_published_plan_template(code="CORE12")
    elite = create_published_plan_template(
        code="ELITE24",
        monthly_dues_cents=7900,
        initiation_fee_cents=9900,
        term_months=24,
        floor_price_cents=6300,
    )
    july = create_approved_promotion(
        franchisee["id"],
        core["id"],
        code="JULY10",
        discount_pct=0.10,
        starts_on="2026-07-01",
        ends_on="2026-07-31",
    )
    return {"franchisee": franchisee, "core": core, "elite": elite, "july": july}


def _file(setup: dict, plan_template_id: str, code: str, starts_on: str, ends_on: str):
    return api_client.create_promotion(
        create_promotion_payload(
            setup["franchisee"]["id"],
            plan_template_id,
            code=code,
            discount_pct=0.10,
            starts_on=starts_on,
            ends_on=ends_on,
        ),
        make_franchise_owner_headers(setup["franchisee"]["id"]),
    )


def test_a_six_day_gap_after_the_incumbent_window_is_refused():
    """2026-08-06 is six whole days after 2026-07-31, one short of the required separation on
    the later side.

    PRD 3.2: "When a new filing is compared against every other promotion for that same pair
    whose `status` is `PENDING_REVIEW` or `APPROVED`, the two closed windows must be separated
    by at least a full week — 7 whole days — on whichever side they meet: if the new window
    sits later, the gap from the existing promotion's `ends_on` to the new `starts_on` must be
    at least 7 days; if the new window sits earlier, the gap from the new `ends_on` to the
    existing promotion's `starts_on` must be at least 7 days."

    Design: Difficulty/resource_temporal_overlap/promotion_windows_need_a_seven_day_cooling_gap_on_both_sides_of_the_channel
    """
    setup = _july_discount_on_one_of_two_templates()

    response = _file(setup, setup["core"]["id"], "LATE6", "2026-08-06", "2026-08-31")
    validate_error(response, ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value)


def test_a_gap_of_exactly_seven_days_after_the_incumbent_window_is_accepted():
    """One day later the gap is precisely seven whole days, which the rule accepts, and the
    filing is created awaiting review.

    PRD 3.2: "The boundary is exact: a gap of precisely 7 whole days is accepted, and a gap of
    6 is rejected."

    Design: Difficulty/resource_temporal_overlap/promotion_windows_need_a_seven_day_cooling_gap_on_both_sides_of_the_channel
    """
    setup = _july_discount_on_one_of_two_templates()

    filed = validate_success(
        _file(setup, setup["core"]["id"], "LATE7", "2026-08-07", "2026-08-31"),
        expected_status=201,
    )
    assert filed["status"] == "PENDING_REVIEW"
    assert filed["starts_on"] == "2026-08-07"


def test_a_six_day_gap_before_the_incumbent_window_is_refused():
    """The rule bites in the other direction too: 2026-06-25 leaves only six days before the
    incumbent's 2026-07-01 start.

    PRD 3.2: "When a new filing is compared against every other promotion for that same pair
    whose `status` is `PENDING_REVIEW` or `APPROVED`, the two closed windows must be separated
    by at least a full week — 7 whole days — on whichever side they meet: if the new window
    sits later, the gap from the existing promotion's `ends_on` to the new `starts_on` must be
    at least 7 days; if the new window sits earlier, the gap from the new `ends_on` to the
    existing promotion's `starts_on` must be at least 7 days."

    Design: Difficulty/resource_temporal_overlap/promotion_windows_need_a_seven_day_cooling_gap_on_both_sides_of_the_channel
    """
    setup = _july_discount_on_one_of_two_templates()

    response = _file(setup, setup["core"]["id"], "EARLY6", "2026-06-01", "2026-06-25")
    validate_error(response, ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value)


def test_a_gap_of_exactly_seven_days_before_the_incumbent_window_is_accepted():
    """Ending one day earlier makes the separation exactly seven whole days on the earlier
    side, which is accepted.

    PRD 3.2: "The boundary is exact: a gap of precisely 7 whole days is accepted, and a gap of
    6 is rejected."

    Design: Difficulty/resource_temporal_overlap/promotion_windows_need_a_seven_day_cooling_gap_on_both_sides_of_the_channel
    """
    setup = _july_discount_on_one_of_two_templates()

    filed = validate_success(
        _file(setup, setup["core"]["id"], "EARLY7", "2026-06-01", "2026-06-24"),
        expected_status=201,
    )
    assert filed["status"] == "PENDING_REVIEW"
    assert filed["ends_on"] == "2026-06-24"


def test_the_identical_window_on_a_second_template_is_free():
    """The separation rule is keyed on the franchisee-and-template pair, so a fully
    overlapping July window on the other template collides with nothing.

    PRD 3.2: "Promotions for the same `franchisee_id` and `plan_template_id` pair must also be
    kept apart in time, so that a franchisee cannot chain back-to-back discounts into a
    permanent price cut."

    Design: Difficulty/resource_temporal_overlap/promotion_windows_need_a_seven_day_cooling_gap_on_both_sides_of_the_channel
    """
    setup = _july_discount_on_one_of_two_templates()
    _file(setup, setup["core"]["id"], "LATE6", "2026-08-06", "2026-08-31")
    later = validate_success(
        _file(setup, setup["core"]["id"], "LATE7", "2026-08-07", "2026-08-31"),
        expected_status=201,
    )
    _file(setup, setup["core"]["id"], "EARLY6", "2026-06-01", "2026-06-25")
    earlier = validate_success(
        _file(setup, setup["core"]["id"], "EARLY7", "2026-06-01", "2026-06-24"),
        expected_status=201,
    )

    elite_july = validate_success(
        _file(setup, setup["elite"]["id"], "ELITEJULY", "2026-07-01", "2026-07-31"),
        expected_status=201,
    )
    assert elite_july["starts_on"] == "2026-07-01"
    assert elite_july["ends_on"] == "2026-07-31"

    _, core_meta = validate_paginated(
        api_client.list_promotions(
            BRAND,
            params={
                "franchisee_id": setup["franchisee"]["id"],
                "plan_template_id": setup["core"]["id"],
            },
        )
    )
    assert core_meta["total_count"] == 3
    _, elite_meta = validate_paginated(
        api_client.list_promotions(
            BRAND,
            params={
                "franchisee_id": setup["franchisee"]["id"],
                "plan_template_id": setup["elite"]["id"],
            },
        )
    )
    assert elite_meta["total_count"] == 1
    assert read_promotion(setup["july"]["id"])["status"] == "APPROVED"
    assert read_promotion(later["id"])["status"] == "PENDING_REVIEW"
    assert read_promotion(earlier["id"])["status"] == "PENDING_REVIEW"
