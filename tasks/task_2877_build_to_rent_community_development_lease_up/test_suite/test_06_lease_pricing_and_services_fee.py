"""Lease pricing: base-rent selection, the community-services fee tiers and the product surcharge."""

from test_helpers import (
    NON_EXISTENT_UUID,
    PRODUCT_SURCHARGE_CENTS,
    ApiErrorId,
    assert_instant_equals,
    assert_lease,
    community_version,
    create_household,
    create_lease_payload,
    publish_schedule_payload,
    read_homesite,
    read_household,
    read_lease,
    read_schedule,
    setup_released_community,
    validate_error,
    validate_success,
)

COTTAGE_ONLY_MIX = {"DETACHED": 0, "COTTAGE": 1, "TOWNHOME": 0}
TWO_COTTAGE_MIX = {"DETACHED": 0, "COTTAGE": 2, "TOWNHOME": 0}
TWO_DETACHED_MIX = {"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0}
ONE_OF_EACH_MIX = {"DETACHED": 1, "COTTAGE": 1, "TOWNHOME": 1}


def _cottage_community_at_199999():
    """Plat-approved cottage community whose only published cottage price is 199999 cents."""
    return setup_released_community(
        homesite_count=1,
        product_type="COTTAGE",
        asking_rent_cents=199_999,
        total_planned_units=1,
        product_mix=COTTAGE_ONLY_MIX,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=1,
    )


def test_community_services_fee_rate_tier_is_selected_from_base_rent_below_the_two_hundred_thousand_break(
    api, leasing_agent_headers
):
    """A cottage lease priced at 199999 cents takes the 350 basis point rate and the cottage
    surcharge, so the fee is 10000 cents and the gross charge is 209999 cents.

    Step two picks the fee rate from `base_rent_cents` **alone**: a base rent below 200,000 cents uses 350 basis points, a base rent from 200,000 cents up to but not including 320,000 cents uses 300 basis points, and a base rent of 320,000 cents or more uses 250 basis points.
    Step three computes `community_services_fee_cents` as `base_rent_cents` multiplied by the selected rate in basis points and divided by 10,000, rounded half up to whole cents, plus a flat product surcharge keyed on the home's `product_type`: 4,500 cents for `DETACHED`, 3,000 cents for `COTTAGE` and 2,000 cents for `TOWNHOME`.
    Step four computes `gross_monthly_charge_cents` as `base_rent_cents` plus `community_services_fee_cents`.
    Design: Difficulty/combinatorial_formula/services_fee_tier_keyed_on_base_rent_not_on_the_gross_it_produces
    """
    scenario = _cottage_community_at_199999()
    household = create_household(monthly_income_cents=800_000)

    lease = validate_success(
        api.create_lease(
            create_lease_payload(scenario["homesites"][0]["id"], household["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )

    assert_lease(lease)
    assert lease["base_rent_cents"] == 199_999
    assert lease["community_services_fee_cents"] == 10_000
    assert lease["gross_monthly_charge_cents"] == 209_999


def test_community_services_fee_is_not_reselected_from_the_gross_charge_it_produces(
    api, leasing_agent_headers
):
    """The stored fee stays at the 350 basis point figure even though the gross charge it
    produces, 209999 cents, sits above the 200000 cent break.

    The rate bracket in step two is never selected from `gross_monthly_charge_cents`, and the four steps are never iterated toward a fixed point — the gross charge is an output of the fee, never an input to it.
    Both values are frozen at creation and are never re-derived, so a later repricing of the community never disturbs a lease already drafted.
    Design: Difficulty/combinatorial_formula/services_fee_tier_keyed_on_base_rent_not_on_the_gross_it_produces
    """
    scenario = _cottage_community_at_199999()
    household = create_household(monthly_income_cents=800_000)

    created = validate_success(
        api.create_lease(
            create_lease_payload(scenario["homesites"][0]["id"], household["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )

    stored = read_lease(created["id"])
    assert stored["community_services_fee_cents"] == 10_000
    assert stored["community_services_fee_cents"] != 9_000
    assert stored["gross_monthly_charge_cents"] == 209_999
    assert stored["gross_monthly_charge_cents"] != 208_999
    assert stored["gross_monthly_charge_cents"] == (
        stored["base_rent_cents"] + stored["community_services_fee_cents"]
    )


def _two_cottage_community_at_199999():
    """Two released cottages priced by a single published schedule at 199999 cents effective
    2026-07-15, a fortnight before the intended lease commencement."""
    return setup_released_community(
        homesite_count=2,
        product_type="COTTAGE",
        asking_rent_cents=199_999,
        total_planned_units=2,
        product_mix=TWO_COTTAGE_MIX,
        schedule_effective_from="2026-07-15T00:00:00Z",
        concession_budget_cents=2_000_000,
        facility_commitment_cents=30_000_000,
        maintenance_tech_headcount=1,
    )


def _publish_cottage_price(api, asset_manager_headers, community_id, asking_rent_cents, effective_from):
    """POST /market-rent-schedules for the cottage product type at the community's live version."""
    return validate_success(
        api.publish_market_rent_schedule(
            publish_schedule_payload(
                community_id,
                community_version(community_id),
                product_type="COTTAGE",
                asking_rent_cents=asking_rent_cents,
                effective_from=effective_from,
            ),
            asset_manager_headers,
        ),
        expected_status=201,
    )


def test_cottage_lease_one_cent_below_the_two_hundred_thousand_break_pays_three_hundred_fifty_basis_points(
    api, leasing_agent_headers
):
    """A base rent of 199999 cents rounds the 350 basis point product half up to 7000 cents and
    adds the 3000 cent cottage surcharge, giving a 10000 cent fee on a 209999 cent gross charge.

    The bracket boundaries are inclusive at the bottom and exclusive at the top, so a base rent of exactly 200,000 cents uses 300 basis points while 199,999 cents uses 350.
    The winner's `asking_rent_cents` becomes the lease's `base_rent_cents` and the winner's identifier is stored as the lease's `priced_by_schedule_id`.
    Design: Difficulty/boundary_precision_check/community_services_fee_tier_boundary_at_exactly_200000_cents
    """
    scenario = _two_cottage_community_at_199999()
    household = create_household(monthly_income_cents=700_000)

    lease = validate_success(
        api.create_lease(
            create_lease_payload(scenario["homesites"][0]["id"], household["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )

    assert lease["base_rent_cents"] == 199_999
    assert lease["priced_by_schedule_id"] == scenario["schedules"]["COTTAGE"]["id"]
    assert lease["community_services_fee_cents"] == 10_000
    assert lease["gross_monthly_charge_cents"] == 209_999


def test_cottage_lease_at_exactly_two_hundred_thousand_cents_pays_three_hundred_basis_points(
    api, asset_manager_headers, leasing_agent_headers
):
    """Republishing the cottage price at exactly 200000 cents retires the 199999 cent schedule and
    puts the next lease in the 300 basis point band, for a 9000 cent fee and a 209000 cent gross.

    The bracket boundaries are inclusive at the bottom and exclusive at the top, so a base rent of exactly 200,000 cents uses 300 basis points while 199,999 cents uses 350.
    On success the new schedule is stored with `status` `PUBLISHED`, `superseded_at` null and `published_by_user_id` set from the acting `X-User-ID`; the community's previously `PUBLISHED` schedule for that same community-and-product-type pair moves to `status` `SUPERSEDED` with `superseded_at` stamped at the current logical clock; and the community's `version` increments.
    Design: Difficulty/boundary_precision_check/community_services_fee_tier_boundary_at_exactly_200000_cents
    """
    scenario = _two_cottage_community_at_199999()
    household = create_household(monthly_income_cents=700_000)
    first_schedule = scenario["schedules"]["COTTAGE"]

    second_schedule = _publish_cottage_price(
        api,
        asset_manager_headers,
        scenario["community"]["id"],
        200_000,
        "2026-08-01T00:00:00Z",
    )

    retired = read_schedule(first_schedule["id"])
    assert retired["status"] == "SUPERSEDED"
    assert_instant_equals(retired["superseded_at"], "2026-08-01T00:00:00Z", "superseded_at")
    assert second_schedule["status"] == "PUBLISHED"
    assert second_schedule["superseded_at"] is None

    lease = validate_success(
        api.create_lease(
            create_lease_payload(scenario["homesites"][1]["id"], household["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )

    assert lease["base_rent_cents"] == 200_000
    assert lease["priced_by_schedule_id"] == second_schedule["id"]
    assert lease["community_services_fee_cents"] == 9_000
    assert lease["gross_monthly_charge_cents"] == 209_000


def test_fee_drops_across_the_two_hundred_thousand_break_although_base_rent_rises_by_one_cent(
    api, asset_manager_headers, leasing_agent_headers
):
    """One cottage priced at 199999 cents and its neighbour priced at 200000 cents land in
    different bands, so the second lease's gross charge is 999 cents lower than the first's.

    The bracket boundaries are inclusive at the bottom and exclusive at the top, so a base rent of exactly 200,000 cents uses 300 basis points while 199,999 cents uses 350.
    The rate bracket in step two is never selected from `gross_monthly_charge_cents`, and the four steps are never iterated toward a fixed point — the gross charge is an output of the fee, never an input to it.
    Design: Difficulty/boundary_precision_check/community_services_fee_tier_boundary_at_exactly_200000_cents
    """
    scenario = _two_cottage_community_at_199999()
    first_household = create_household(monthly_income_cents=700_000)
    second_household = create_household(monthly_income_cents=700_000)

    lower_lease = validate_success(
        api.create_lease(
            create_lease_payload(scenario["homesites"][0]["id"], first_household["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )
    _publish_cottage_price(
        api,
        asset_manager_headers,
        scenario["community"]["id"],
        200_000,
        "2026-08-01T00:00:00Z",
    )
    higher_lease = validate_success(
        api.create_lease(
            create_lease_payload(scenario["homesites"][1]["id"], second_household["id"]),
            leasing_agent_headers,
        ),
        expected_status=201,
    )

    assert lower_lease["base_rent_cents"] == 199_999
    assert higher_lease["base_rent_cents"] == 200_000
    assert lower_lease["community_services_fee_cents"] == 10_000
    assert higher_lease["community_services_fee_cents"] == 9_000
    assert lower_lease["gross_monthly_charge_cents"] == 209_999
    assert higher_lease["gross_monthly_charge_cents"] == 209_000
    assert (
        lower_lease["gross_monthly_charge_cents"] - higher_lease["gross_monthly_charge_cents"]
    ) == 999


def _community_whose_only_price_starts_in_september():
    """Released detached homesite in an OPEN community whose single published detached schedule
    only takes effect on 2026-09-01, a month after the intended commencement."""
    return setup_released_community(
        homesite_count=1,
        product_type="DETACHED",
        asking_rent_cents=300_000,
        total_planned_units=2,
        product_mix=TWO_DETACHED_MIX,
        schedule_effective_from="2026-09-01T00:00:00Z",
        phase_overrides={"planned_unit_count": 2},
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=1,
    )


def test_lease_draft_rejected_when_the_only_published_schedule_takes_effect_after_the_start_date(
    api, leasing_agent_headers
):
    """The home is available in a released phase of an open community, yet the draft fails because
    the community's only published detached schedule does not take effect until after the
    commencement instant, leaving the candidate set empty.

    The service assembles the candidate schedules for the home: every `MarketRentSchedule` whose `community_id` is the community reached from the home's phase, whose `product_type` equals the home's `product_type`, whose `status` is `PUBLISHED`, and whose `effective_from` is at or before the lease's `start_date`.
    If the candidate set is empty, the draft is rejected with `ERR_NO_PUBLISHED_RENT_SCHEDULE`.
    Design: Difficulty/cross_entity_state_dependency/lease_create_rejected_when_the_only_published_schedule_takes_effect_after_the_start_date
    """
    scenario = _community_whose_only_price_starts_in_september()
    household = create_household(monthly_income_cents=1_200_000)
    homesite = scenario["homesites"][0]

    assert scenario["community"]["posture"] == "OPEN"
    assert scenario["schedules"]["DETACHED"]["status"] == "PUBLISHED"
    assert homesite["status"] == "AVAILABLE"

    response = api.create_lease(
        create_lease_payload(homesite["id"], household["id"], start_date="2026-08-01T00:00:00Z"),
        leasing_agent_headers,
    )

    validate_error(response, ApiErrorId.ERR_NO_PUBLISHED_RENT_SCHEDULE.value)
    assert read_homesite(homesite["id"])["status"] == "AVAILABLE"
    assert read_household(household["id"])["active_lease_count"] == 0


def test_lease_draft_prices_off_an_earlier_dated_schedule_published_after_the_future_dated_one(
    api, asset_manager_headers, leasing_agent_headers
):
    """Publishing a second detached schedule with an earlier effective_from retires the
    future-dated one and makes the previously rejected draft succeed at 285000 cents.

    On success the new schedule is stored with `status` `PUBLISHED`, `superseded_at` null and `published_by_user_id` set from the acting `X-User-ID`; the community's previously `PUBLISHED` schedule for that same community-and-product-type pair moves to `status` `SUPERSEDED` with `superseded_at` stamped at the current logical clock; and the community's `version` increments.
    Schedules with `status` `SUPERSEDED` are excluded from the candidate set even when their `effective_from` is later than every published one — supersession, not date, decides eligibility.
    The winner's `asking_rent_cents` becomes the lease's `base_rent_cents` and the winner's identifier is stored as the lease's `priced_by_schedule_id`.
    Design: Difficulty/cross_entity_state_dependency/lease_create_rejected_when_the_only_published_schedule_takes_effect_after_the_start_date
    """
    scenario = _community_whose_only_price_starts_in_september()
    household = create_household(monthly_income_cents=1_200_000)
    homesite = scenario["homesites"][0]
    future_schedule = scenario["schedules"]["DETACHED"]

    validate_error(
        api.create_lease(
            create_lease_payload(homesite["id"], household["id"], start_date="2026-08-01T00:00:00Z"),
            leasing_agent_headers,
        ),
        ApiErrorId.ERR_NO_PUBLISHED_RENT_SCHEDULE.value,
    )

    community_id = scenario["community"]["id"]
    earlier_schedule = validate_success(
        api.publish_market_rent_schedule(
            publish_schedule_payload(
                community_id,
                community_version(community_id),
                product_type="DETACHED",
                asking_rent_cents=285_000,
                effective_from="2026-07-15T00:00:00Z",
            ),
            asset_manager_headers,
        ),
        expected_status=201,
    )

    assert read_schedule(future_schedule["id"])["status"] == "SUPERSEDED"
    assert earlier_schedule["status"] == "PUBLISHED"

    lease = validate_success(
        api.create_lease(
            create_lease_payload(homesite["id"], household["id"], start_date="2026-08-01T00:00:00Z"),
            leasing_agent_headers,
        ),
        expected_status=201,
    )

    assert lease["base_rent_cents"] == 285_000
    assert lease["priced_by_schedule_id"] == earlier_schedule["id"]
    assert lease["community_services_fee_cents"] == 13_050
    assert lease["gross_monthly_charge_cents"] == 298_050


def _released_detached_community_for_precedence():
    """One released detached homesite priced at 285000 cents in an OPEN community."""
    return setup_released_community(
        homesite_count=1,
        product_type="DETACHED",
        asking_rent_cents=285_000,
        total_planned_units=2,
        product_mix=TWO_DETACHED_MIX,
        phase_overrides={"planned_unit_count": 2},
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=1,
    )


def test_unknown_homesite_on_a_lease_draft_is_rejected_before_the_invalid_term_months(
    api, leasing_agent_headers
):
    """A draft naming a homesite that does not exist and also carrying a term of 13 months is
    rejected for the unresolvable home rather than for the malformed term.

    An unknown `community_id` on a phase, rent schedule or concession program yields `ERR_COMMUNITY_NOT_FOUND`; an unknown `phase_id` on a homesite, or an unknown `predecessor_phase_id` on a phase, yields `ERR_PHASE_NOT_FOUND`; an unknown `homesite_id` on a lease or a turn work order, or any unknown member of the `homesite_ids` list on a section release, yields `ERR_HOMESITE_NOT_FOUND`; an unknown `household_id` on a lease yields `ERR_HOUSEHOLD_NOT_FOUND`; and an unknown `concession_program_id` on a concession request yields `ERR_CONCESSION_PROGRAM_NOT_FOUND`.
    6. **Body reference existence** — every identifier field in the body resolves (the same family of codes).
    7. **Schema validity** — the body parses, required fields are present and non-null, enum values are declared members, numeric and instant formats are correct (`ERR_INVALID_REQUEST`).
    Design: Difficulty/priority_pair_validation_conflict/unknown_homesite_not_found_rejected_before_the_invalid_term_months_check
    """
    scenario = _released_detached_community_for_precedence()
    household = create_household(monthly_income_cents=1_200_000)

    response = api.create_lease(
        create_lease_payload(NON_EXISTENT_UUID, household["id"], term_months=13),
        leasing_agent_headers,
    )

    validate_error(response, ApiErrorId.ERR_HOMESITE_NOT_FOUND.value)
    assert read_homesite(scenario["homesites"][0]["id"])["status"] == "AVAILABLE"
    assert read_household(household["id"])["active_lease_count"] == 0


def test_invalid_term_months_is_the_masked_violation_once_the_homesite_resolves(
    api, leasing_agent_headers
):
    """Repointing the same malformed draft at the real homesite exposes the term of 13 months as
    the violation that the unresolvable identifier had masked.

    The draft payload names the home in `homesite_id` and the leaseholder in `household_id`, states a `term_months` of exactly 12, 18 or 24 — anything else is `ERR_INVALID_REQUEST` — and a `start_date` commencement instant.
    When a request violates more than one rule, exactly one error is returned, and which one is fully determined by a fixed evaluation order.
    Design: Difficulty/priority_pair_validation_conflict/unknown_homesite_not_found_rejected_before_the_invalid_term_months_check
    """
    scenario = _released_detached_community_for_precedence()
    household = create_household(monthly_income_cents=1_200_000)
    homesite = scenario["homesites"][0]

    validate_error(
        api.create_lease(
            create_lease_payload(NON_EXISTENT_UUID, household["id"], term_months=13),
            leasing_agent_headers,
        ),
        ApiErrorId.ERR_HOMESITE_NOT_FOUND.value,
    )

    response = api.create_lease(
        create_lease_payload(homesite["id"], household["id"], term_months=13),
        leasing_agent_headers,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert read_homesite(homesite["id"])["status"] == "AVAILABLE"
    assert read_household(household["id"])["active_lease_count"] == 0


def test_community_services_fee_applies_the_declared_product_surcharge_for_each_product_type(
    api, leasing_agent_headers
):
    """Three leases priced off three schedules that all ask 285000 cents differ only by the flat
    surcharge for the home's configuration: 13050, 11550 and 10550 cents of fee.

    Step three computes `community_services_fee_cents` as `base_rent_cents` multiplied by the selected rate in basis points and divided by 10,000, rounded half up to whole cents, plus a flat product surcharge keyed on the home's `product_type`: 4,500 cents for `DETACHED`, 3,000 cents for `COTTAGE` and 2,000 cents for `TOWNHOME`.
    Step four computes `gross_monthly_charge_cents` as `base_rent_cents` plus `community_services_fee_cents`.
    The winner's `asking_rent_cents` becomes the lease's `base_rent_cents` and the winner's identifier is stored as the lease's `priced_by_schedule_id`.
    Design: Corner/calculations/community_services_fee_applies_the_declared_surcharge_for_each_product_type
    """
    scenario = setup_released_community(
        homesite_specs=[
            {"product_type": "DETACHED", "bedrooms": 4, "square_feet": 2100},
            {"product_type": "COTTAGE", "bedrooms": 2, "square_feet": 1100},
            {"product_type": "TOWNHOME", "bedrooms": 3, "square_feet": 1500},
        ],
        total_planned_units=3,
        product_mix=ONE_OF_EACH_MIX,
        asking_rent_cents=285_000,
        concession_budget_cents=2_000_000,
        facility_commitment_cents=40_000_000,
        maintenance_tech_headcount=2,
    )
    detached_home, cottage_home, townhome_home = scenario["homesites"]

    leases = {}
    for homesite in (detached_home, cottage_home, townhome_home):
        household = create_household(monthly_income_cents=1_200_000)
        leases[homesite["product_type"]] = validate_success(
            api.create_lease(
                create_lease_payload(homesite["id"], household["id"]),
                leasing_agent_headers,
            ),
            expected_status=201,
        )

    for product_type, lease in leases.items():
        assert lease["base_rent_cents"] == 285_000
        assert lease["priced_by_schedule_id"] == scenario["schedules"][product_type]["id"]

    assert leases["DETACHED"]["community_services_fee_cents"] == 13_050
    assert leases["DETACHED"]["gross_monthly_charge_cents"] == 298_050
    assert leases["COTTAGE"]["community_services_fee_cents"] == 11_550
    assert leases["COTTAGE"]["gross_monthly_charge_cents"] == 296_550
    assert leases["TOWNHOME"]["community_services_fee_cents"] == 10_550
    assert leases["TOWNHOME"]["gross_monthly_charge_cents"] == 295_550

    assert (
        leases["DETACHED"]["community_services_fee_cents"]
        - leases["COTTAGE"]["community_services_fee_cents"]
    ) == PRODUCT_SURCHARGE_CENTS["DETACHED"] - PRODUCT_SURCHARGE_CENTS["COTTAGE"]
    assert (
        leases["COTTAGE"]["community_services_fee_cents"]
        - leases["TOWNHOME"]["community_services_fee_cents"]
    ) == PRODUCT_SURCHARGE_CENTS["COTTAGE"] - PRODUCT_SURCHARGE_CENTS["TOWNHOME"]
