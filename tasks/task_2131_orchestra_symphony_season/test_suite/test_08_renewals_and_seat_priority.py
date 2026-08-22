"""Renewal chains: the price lock, the loyalty discount, the priority gate and OCC."""

from test_helpers import (
    BOX_OFFICE,
    ApiErrorId,
    create_package,
    create_patron,
    current_package_version,
    inventory_for,
    open_renewal_window,
    read_concert,
    read_patron,
    read_season,
    read_subscription,
    renew_package,
    set_clock,
    setup_renewal_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

IRIS = {"full_name": "Iris Lund", "email": "iris-renewal@patron.test",
        "subscriber_since_year": 2018}


def _renew_request(chain, seat_count=1, expected_package_version=None):
    payload = {
        "season_id": chain.season_b["id"],
        "concert_ids": chain.concert_ids_b,
        "expected_package_version": (
            expected_package_version
            if expected_package_version is not None
            else current_package_version(chain.package["id"])
        ),
        "seat_count": seat_count,
    }
    return payload


# --------------------------------------------------------------------------
# NEW versus RENEWAL pricing
# --------------------------------------------------------------------------
def test_renewal_reuses_the_prior_locked_line_and_applies_loyalty(api):
    """PRD 3.6: "In step one, `locked_unit_price_cents` is **not** recomputed from
    the new season's base price; it is copied verbatim from the prior package's
    `locked_unit_price_cents`. That is the price lock a subscriber renews for."
    PRD 3.6: "The loyalty rate in basis points is the season's
    `loyalty_discount_bp` plus 100 basis points for each of the patron's
    `consecutive_renewal_years`, capped at 2000 basis points — a twenty percent
    ceiling no length of subscription can exceed."
    PRD 3.6: "`price_cents` is the step-three figure multiplied by 10000 less that
    loyalty rate, divided by 10,000, and rounded half up."

    Design: Difficulty/dual_variant_calc/subscription_new_vs_renewal_price_diverge
    """
    chain = setup_renewal_chain(
        season_a_overrides={"base_ticket_price_cents": 6000, "loyalty_discount_bp": 500},
        season_b_overrides={"base_ticket_price_cents": 7000, "loyalty_discount_bp": 500},
        concerts_a=3, concerts_b=3, seat_count=2, patron_overrides=IRIS,
    )

    assert chain.package["locked_unit_price_cents"] == 4800
    assert chain.package["price_cents"] == 27360
    assert read_patron(chain.patron["id"])["consecutive_renewal_years"] == 1

    renewal = renew_package(
        chain.package["id"], chain.season_b["id"], chain.concert_ids_b, seat_count=2
    )

    assert renewal["package_type"] == "RENEWAL"
    assert renewal["prior_package_id"] == chain.package["id"]
    assert renewal["locked_unit_price_cents"] == 4800, (
        "the 2028 base price of 7000 is ignored; the prior line is copied verbatim"
    )
    assert renewal["price_cents"] == 25718, (
        "28800 subtotal, 500bp package tier to 27360, then a 600bp loyalty rate"
    )


def test_new_package_prices_at_the_current_base_and_costs_more_than_the_renewal(api):
    """PRD 3.5: "Step one fixes the per-line unit price,
    `locked_unit_price_cents`: for a `NEW` package it is the season's
    `base_ticket_price_cents` multiplied by the section's `price_multiplier_bp`,
    divided by 10,000 and rounded half up to a whole cent."
    PRD 3.5: "Step four is the loyalty discount, which a `NEW` package never
    receives — for a `NEW` package `price_cents` is simply the step-three result."
    PRD 3.6: "The consequence is the one the orchestra advertises: for an identical
    concert set, section and seat count, a renewal costs less than a fresh purchase
    whenever the base price has moved between seasons, and never costs more."

    Design: Difficulty/dual_variant_calc/subscription_new_vs_renewal_price_diverge
    """
    chain = setup_renewal_chain(
        season_a_overrides={"base_ticket_price_cents": 6000, "loyalty_discount_bp": 500},
        season_b_overrides={"base_ticket_price_cents": 7000, "loyalty_discount_bp": 500},
        concerts_a=3, concerts_b=3, seat_count=2, patron_overrides=IRIS,
    )
    renewal = renew_package(
        chain.package["id"], chain.season_b["id"], chain.concert_ids_b, seat_count=2
    )

    newcomer = create_patron(full_name="Otto Brandt", email="otto-new@patron.test")
    fresh = create_package(
        newcomer["id"], chain.season_b["id"], chain.section["id"],
        chain.concert_ids_b, seat_count=2,
    )

    assert fresh["package_type"] == "NEW"
    assert fresh["locked_unit_price_cents"] == 5600, "7000 base times the 8000bp section"
    assert fresh["price_cents"] == 31920, "33600 subtotal less the 500bp three-concert tier"
    assert renewal["price_cents"] != fresh["price_cents"]
    assert renewal["price_cents"] < fresh["price_cents"]


# --------------------------------------------------------------------------
# The target-season gate
# --------------------------------------------------------------------------
def test_renewing_into_a_planning_season_is_refused(api):
    """PRD 3.6: "The **target** season — the one being renewed into — must be in
    `RENEWAL_WINDOW`, else `ERR_RENEWAL_WINDOW_CLOSED`; note that this is the
    destination season's status, not the prior package's season."

    Design: Difficulty/cross_entity_state_dependency/renew_requires_target_season_renewal_window
    """
    chain = setup_renewal_chain(concerts_a=3, concerts_b=3, patron_overrides=IRIS,
                                advance_b=False)
    assert chain.package["status"] == "ACTIVE"
    assert chain.package["price_cents"] == 13680
    assert read_season(chain.season_b["id"])["status"] == "PLANNING"

    response = api.renew_subscription(
        chain.package["id"], _renew_request(chain), BOX_OFFICE
    )
    validate_error(response, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value, 409)

    _, meta = validate_paginated(
        api.list_subscriptions(BOX_OFFICE, params={"season_id": chain.season_b["id"]})
    )
    assert meta["total_count"] == 0, "no renewal package is minted by the refused call"


def test_renewal_succeeds_once_the_target_season_opens_its_window(api):
    """PRD 3.6: "The **target** season — the one being renewed into — must be in
    `RENEWAL_WINDOW`, else `ERR_RENEWAL_WINDOW_CLOSED`; note that this is the
    destination season's status, not the prior package's season."
    PRD 3.6: "Renewing an `ACTIVE` package mints a **new** package whose
    `package_type` is `RENEWAL`, whose `prior_package_id` points at the package
    being renewed, and whose `seat_section_id` is inherited from that prior package
    rather than supplied by the caller."
    PRD 3.6: "Creating a renewal holds seats immediately: on every concert in the
    new `concert_ids`, the seat count is added to `held_count` on the inherited
    section's inventory element, exactly as a new package does."

    Design: Difficulty/cross_entity_state_dependency/renew_requires_target_season_renewal_window
    """
    chain = setup_renewal_chain(concerts_a=3, concerts_b=3, patron_overrides=IRIS,
                                advance_b=False)
    validate_error(
        api.renew_subscription(chain.package["id"], _renew_request(chain), BOX_OFFICE),
        ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value,
        409,
    )

    open_renewal_window(chain.season_b["id"])
    renewal = validate_success(
        api.renew_subscription(chain.package["id"], _renew_request(chain), BOX_OFFICE),
        201,
    )

    assert renewal["package_type"] == "RENEWAL"
    assert renewal["status"] == "PENDING_PAYMENT"
    assert renewal["prior_package_id"] == chain.package["id"]
    assert renewal["seat_section_id"] == chain.section["id"], (
        "the section is inherited and was never supplied in the request"
    )
    assert renewal["price_cents"] == 12859, "13680 less the 600bp loyalty rate"

    element = inventory_for(read_concert(chain.concert_ids_b[0]), chain.section["id"])
    assert element["held_count"] == 1


def test_renewing_a_pending_package_is_refused(api):
    """PRD 3.6: "Four gates guard the renewal beyond the ordinary ladder. The
    package being renewed must be `ACTIVE`, else `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Corner/state_machines/renew_pending_package_returns_subscription_not_active
    """
    chain = setup_renewal_chain(patron_overrides=IRIS, pay=False)
    assert chain.package["status"] == "PENDING_PAYMENT"

    response = api.renew_subscription(
        chain.package["id"], _renew_request(chain), BOX_OFFICE
    )
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value, 409)

    _, meta = validate_paginated(
        api.list_subscriptions(BOX_OFFICE, params={"season_id": chain.season_b["id"]})
    )
    assert meta["total_count"] == 0
    assert read_subscription(chain.package["id"])["status"] == "PENDING_PAYMENT"


# --------------------------------------------------------------------------
# The renewal priority gate
# --------------------------------------------------------------------------
def test_renewal_below_the_section_priority_floor_is_refused(api):
    """PRD 3.6: "And the **renewal priority gate**: the patron's
    `renewal_priority_score`, freshly recomputed at this moment rather than read
    from storage, must be at least the `min_renewal_priority_score` of the prior
    package's seat section. A score exactly equal to the threshold passes; a lower
    one is refused with `ERR_RENEWAL_PRIORITY_INSUFFICIENT`."

    Design: Corner/validations/renewal_below_section_priority_returns_priority_insufficient
    """
    chain = setup_renewal_chain(
        balcony=False,
        section_spec={"min_renewal_priority_score": 600},
        donation_cents=2_500_000,
        patron_overrides={"full_name": "Iris Lund", "email": "iris-low@patron.test",
                          "subscriber_since_year": 2019},
    )
    patron = read_patron(chain.patron["id"])
    assert patron["donor_level"] == "BENEFACTOR"
    assert patron["renewal_priority_score"] == 570, (
        "100 for one renewal year, 400 BENEFACTOR points and 70 of seniority"
    )

    response = api.renew_subscription(
        chain.package["id"], _renew_request(chain), BOX_OFFICE
    )
    validate_error(response, ApiErrorId.ERR_RENEWAL_PRIORITY_INSUFFICIENT.value, 422)

    _, meta = validate_paginated(
        api.list_subscriptions(BOX_OFFICE, params={"season_id": chain.season_b["id"]})
    )
    assert meta["total_count"] == 0


def test_renewal_at_exactly_the_section_priority_floor_succeeds(api):
    """PRD 3.6: "And the **renewal priority gate**: the patron's
    `renewal_priority_score`, freshly recomputed at this moment rather than read
    from storage, must be at least the `min_renewal_priority_score` of the prior
    package's seat section. A score exactly equal to the threshold passes; a lower
    one is refused with `ERR_RENEWAL_PRIORITY_INSUFFICIENT`."
    PRD 3.6: "In step one, `locked_unit_price_cents` is **not** recomputed from the
    new season's base price; it is copied verbatim from the prior package's
    `locked_unit_price_cents`. That is the price lock a subscriber renews for."

    Design: Corner/validations/renewal_at_exact_section_priority_threshold_succeeds
    """
    chain = setup_renewal_chain(
        balcony=False,
        section_spec={"min_renewal_priority_score": 600},
        donation_cents=2_500_000,
        patron_overrides={"full_name": "Iris Lund", "email": "iris-exact@patron.test",
                          "subscriber_since_year": 2016},
    )
    assert read_patron(chain.patron["id"])["renewal_priority_score"] == 600

    renewal = validate_success(
        api.renew_subscription(chain.package["id"], _renew_request(chain), BOX_OFFICE),
        201,
    )

    assert renewal["package_type"] == "RENEWAL"
    assert renewal["locked_unit_price_cents"] == 9000
    assert renewal["price_cents"] == 8460, "9000 less the 600bp loyalty rate"
    assert renewal["seat_section_id"] == chain.section["id"]


def test_renewing_past_the_target_seasons_deadline_is_refused(api):
    """PRD 3.6: "The logical clock must be at or before that target season's
    `renewal_deadline_utc`, and an instant exactly equal to the deadline still
    qualifies; past it the renewal is `ERR_RENEWAL_DEADLINE_PASSED`."
    PRD 2.6: "**Renewal deadline.** The logical clock must be at or before the
    **target** season's `renewal_deadline_utc`; an instant exactly equal to the
    deadline still passes. A later instant yields `ERR_RENEWAL_DEADLINE_PASSED`
    with HTTP 409."

    Design: Corner/validations/renew_after_target_season_deadline_returns_deadline_passed
    """
    chain = setup_renewal_chain(patron_overrides=IRIS)
    payload = _renew_request(chain)

    set_clock("2027-11-01T00:00:00Z")

    response = api.renew_subscription(chain.package["id"], payload, BOX_OFFICE)
    validate_error(response, ApiErrorId.ERR_RENEWAL_DEADLINE_PASSED.value, 409)

    assert read_season(chain.season_b["id"])["status"] == "RENEWAL_WINDOW", (
        "the target season is still open; only the clock has moved past its deadline"
    )
    _, meta = validate_paginated(
        api.list_subscriptions(BOX_OFFICE, params={"season_id": chain.season_b["id"]})
    )
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# The renewal chain and its optimistic concurrency guard
# --------------------------------------------------------------------------
def test_renewal_chain_is_reachable_through_the_prior_package_filter(api):
    """PRD 3.6: "Renewing an `ACTIVE` package mints a **new** package whose
    `package_type` is `RENEWAL`, whose `prior_package_id` points at the package
    being renewed, and whose `seat_section_id` is inherited from that prior package
    rather than supplied by the caller."
    PRD 3.6: "The loyalty rate in basis points is the season's
    `loyalty_discount_bp` plus 100 basis points for each of the patron's
    `consecutive_renewal_years`, capped at 2000 basis points — a twenty percent
    ceiling no length of subscription can exceed."

    Design: Corner/entities/renewal_chain_is_discoverable_through_self_referential_fk
    """
    chain = setup_renewal_chain(patron_overrides=IRIS)

    renewal = renew_package(
        chain.package["id"], chain.season_b["id"], chain.concert_ids_b, seat_count=1
    )

    data, meta = validate_paginated(
        api.list_subscriptions(
            BOX_OFFICE, params={"prior_package_id": chain.package["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == renewal["id"]
    assert renewal["prior_package_id"] == chain.package["id"]
    assert renewal["package_type"] == "RENEWAL"
    assert renewal["price_cents"] == 4512, (
        "one 4800 line, no package tier, then the 600bp loyalty rate"
    )


def test_second_renewal_from_a_stale_package_version_is_rejected(api):
    """PRD 2.12: "If that value does not equal the prior package's current
    `version`, the renewal is rejected with `ERR_STALE_PACKAGE_VERSION` and HTTP
    412."
    PRD 2.12: "A successful renewal increments the prior package's `version` by
    one, which is precisely what makes a second renewal from the same observed
    version fail."

    Design: Corner/cross_cutting_layers/occ_stale_package_version_on_second_renew_returns_412
    """
    chain = setup_renewal_chain(patron_overrides=IRIS)
    observed_version = current_package_version(chain.package["id"])

    first = renew_package(
        chain.package["id"], chain.season_b["id"], chain.concert_ids_b,
        seat_count=1, expected_package_version=observed_version,
    )

    response = api.renew_subscription(
        chain.package["id"],
        _renew_request(chain, expected_package_version=observed_version),
        BOX_OFFICE,
    )
    validate_error(response, ApiErrorId.ERR_STALE_PACKAGE_VERSION.value, 412)

    data, meta = validate_paginated(
        api.list_subscriptions(
            BOX_OFFICE, params={"prior_package_id": chain.package["id"]}
        )
    )
    assert meta["total_count"] == 1, "the stale retry must not mint a duplicate claim"
    assert data[0]["id"] == first["id"]

    element = inventory_for(read_concert(chain.concert_ids_b[0]), chain.section["id"])
    assert element["held_count"] == 1

    assert read_subscription(chain.package["id"])["status"] == "ACTIVE"
