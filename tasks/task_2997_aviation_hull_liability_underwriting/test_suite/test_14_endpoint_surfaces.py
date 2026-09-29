"""Endpoint surfaces: creations, reads, filtered lists and the actions between them.

Each test here drives a whole endpoint family and checks that the three views of
the same resource agree — the creation response, the single read and the filtered
collection read — and that the actions hung off a resource move the money and the
state the contract says they move.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    AcquisitionSource,
    ApiErrorId,
    CoverageStatus,
    PerilsScope,
    PlacementStatus,
    PolicyStatus,
    PolicyType,
    TxnBasis,
    TxnType,
    UseClass,
    WarrantyBasis,
    WarrantyStatus,
    assert_field_values,
    assert_fields_present,
    assert_instants_equal,
    assert_ledger_row,
    assert_ledger_txn_types,
    assert_no_zero_amount_rows,
    assert_policy_shape,
    assert_premium_transaction_shape,
    assert_request_meta,
    assert_schedule_shape,
    assert_war_market_shape,
    assert_war_placement_shape,
    ledger_signed_sum,
    validate_error,
    validate_list,
    validate_unpaginated,
)
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# The revised agreed value used by the value-revision surface, chosen to sit under
# the over-insurance ceiling of the 2016 twin at the schedule's inception year.
REVISED_AGREED_VALUE_CENTS = 40000000

# The war hull line ceded in the placement surface, well inside the market's line.
WAR_HULL_LINE_CENTS = 600000000

# A policy term that spans 29 February 2028, with a hull value that clears the
# over-insurance ceiling of the 2016 twin at that term's inception year.
LEAP_TERM_FROM = "2027-09-01T00:00:00Z"
LEAP_TERM_TO = "2028-09-01T00:00:00Z"
LEAP_HULL_VALUE_CENTS = 40000000

# The private hull value used by the fleet-clause surface, inside the ceiling of the
# 2020 single.
PRIVATE_HULL_VALUE_CENTS = 30000000


def _expected_hull_terms(policy, pilot, use_class, agreed_value_cents, live_count):
    """The rate and annual premium the contract derives for one hull, from inputs only."""
    rate_ppm = c.rate_ppm_for(
        policy["base_hull_rate_ppm"],
        use_class,
        policy["territorial_limit_code"],
        pilot["rating_band_logged"],
    )
    premium_cents = c.annual_premium_cents(
        agreed_value_cents,
        rate_ppm,
        policy_type=policy["policy_type"],
        live_schedule_count=live_count,
    )
    return rate_ppm, premium_cents


# ----------------------------------------------------------------------
# The aircraft-schedule surface
# ----------------------------------------------------------------------
def test_a_hull_creation_and_its_single_read_report_the_same_rated_terms(api):
    """PRD §4: "Endpoints that bring a new resource into existence answer with HTTP 201;
    endpoints that modify, transition or interrogate an existing resource answer with
    HTTP 200."

    Design: Corner/endpoints/corner_schedule_crud_surface_create_read_and_filtered_list_agree
    """
    book = fx.registered_book(api)
    policy = fx.make_policy(api, book["operator_id"])
    payload = f.schedule_payload(
        policy["id"], book["aircraft_id"], book["pilot_id"]
    )

    created_response = api.create_schedule(payload, headers=users.UNDERWRITER)
    created = validate_unpaginated(created_response, expected_status=201)

    assert created_response.status_code == 201
    assert_request_meta(created_response)
    assert_schedule_shape(created)
    assert_fields_present(created, a.SCHEDULE_FIELDS)

    expected_rate, expected_premium = _expected_hull_terms(
        policy,
        book["pilot"],
        payload["use_class"],
        payload["agreed_value_cents"],
        live_count=1,
    )
    expected_values = {
        "policy_id": policy["id"],
        "aircraft_id": book["aircraft_id"],
        "named_pilot_id": book["pilot_id"],
        "use_class": payload["use_class"],
        "agreed_value_cents": payload["agreed_value_cents"],
        "coverage_status": CoverageStatus.PENDING,
        "warranty_status": WarrantyStatus.PENDING_EVIDENCE,
        "warranty_basis": WarrantyBasis.LOGGED_HOURS,
        "warranted_min_total_hours": c.WARRANTY_MIN_TOTAL_HOURS[payload["use_class"]],
        "warranted_min_hours_on_type": c.WARRANTY_MIN_ON_TYPE_HOURS[
            payload["use_class"]
        ],
        "rated_pilot_band": book["pilot"]["rating_band_logged"],
        "rate_ppm": expected_rate,
        "hull_premium_cents": expected_premium,
        "acquisition_source": AcquisitionSource.SCHEDULED,
    }
    assert_field_values(created, **expected_values)
    assert created["reported_declaration_id"] is None
    assert_instants_equal(created["effective_from"], payload["effective_from"])
    assert_instants_equal(created["effective_to"], payload["effective_to"])

    read_response = api.get_schedule(created["id"], headers=users.UNDERWRITER)
    read_back = validate_unpaginated(read_response)

    assert read_response.status_code == 200
    assert read_back["id"] == created["id"]
    assert_schedule_shape(read_back)
    assert_field_values(read_back, **expected_values)


def test_the_hull_list_filtered_by_coverage_status_agrees_with_the_single_read(api):
    """PRD §2.3: "Filters are additive: when several are supplied on the same request,
    only rows matching all of them are returned."

    Design: Corner/endpoints/corner_schedule_crud_surface_create_read_and_filtered_list_agree
    """
    book = fx.registered_book(api)
    policy = fx.make_policy(api, book["operator_id"])
    schedule = fx.make_schedule(
        api, policy["id"], book["aircraft_id"], book["pilot_id"]
    )
    expected_rate, expected_premium = _expected_hull_terms(
        policy,
        book["pilot"],
        UseClass.INSTRUCTIONAL,
        schedule["agreed_value_cents"],
        live_count=1,
    )

    pending_rows, pending_meta = validate_list(
        api.list_schedules(
            headers=users.UNDERWRITER,
            params={
                "policy_id": policy["id"],
                "coverage_status": CoverageStatus.PENDING,
            },
        )
    )
    assert [row["id"] for row in pending_rows] == [schedule["id"]]
    assert pending_meta["limit"] == c.DEFAULT_LIMIT
    assert pending_meta["offset"] == c.DEFAULT_OFFSET
    assert pending_meta["total_count"] == 1
    assert pending_meta["has_more"] is False
    assert_field_values(
        pending_rows[0],
        rate_ppm=expected_rate,
        hull_premium_cents=expected_premium,
        rated_pilot_band=book["pilot"]["rating_band_logged"],
    )

    active_rows, active_meta = validate_list(
        api.list_schedules(
            headers=users.UNDERWRITER,
            params={
                "policy_id": policy["id"],
                "coverage_status": CoverageStatus.ACTIVE,
            },
        )
    )
    assert active_rows == [], "the hull is pending until the policy is bound"
    assert active_meta["total_count"] == 0

    on_policy = fx.fetch_policy(api, policy["id"])
    assert_policy_shape(on_policy)
    assert_field_values(
        on_policy,
        status=PolicyStatus.DRAFT,
        total_hull_sum_insured_cents=schedule["agreed_value_cents"],
        live_schedule_count=1,
        written_premium_cents=0,
    )


# ----------------------------------------------------------------------
# The value-revision action
# ----------------------------------------------------------------------
def test_a_value_revision_reprices_the_hull_and_leaves_the_pilot_band_alone(api):
    """PRD §3.4: "The revision replaces `agreed_value_cents`, then re-derives `rate_ppm`
    and `hull_premium_cents` — leaving `rated_pilot_band` and `warranty_basis` exactly as
    they were, because nothing about the pilot has changed — and takes the annual
    difference between the new and old `hull_premium_cents`."

    Design: Corner/endpoints/corner_value_revision_action_reprices_and_posts_one_ledger_row
    """
    book = fx.bound_policy_with_hull(api)
    policy = book["policy"]
    before = fx.fetch_schedule(api, book["schedule_id"])
    ceiling = c.over_insurance_ceiling_cents(
        c.depreciated_value_cents(
            book["aircraft"]["hull_new_value_cents"],
            book["aircraft"]["manufacture_year"],
            c.calendar_year_of(before["effective_from"]),
        )
    )
    assert REVISED_AGREED_VALUE_CENTS <= ceiling, "the revision must clear the ceiling"

    response = api.revise_schedule_value(
        book["schedule_id"],
        f.value_revision_payload(REVISED_AGREED_VALUE_CENTS, before["version"]),
        headers=users.UNDERWRITER,
    )
    revised = validate_unpaginated(response)

    assert response.status_code == 200
    assert_schedule_shape(revised)
    expected_rate, expected_premium = _expected_hull_terms(
        policy,
        book["pilot"],
        before["use_class"],
        REVISED_AGREED_VALUE_CENTS,
        live_count=1,
    )
    assert_field_values(
        revised,
        agreed_value_cents=REVISED_AGREED_VALUE_CENTS,
        rate_ppm=expected_rate,
        hull_premium_cents=expected_premium,
        rated_pilot_band=before["rated_pilot_band"],
        warranty_basis=WarrantyBasis.LOGGED_HOURS,
        coverage_status=CoverageStatus.ACTIVE,
    )
    assert revised["rate_ppm"] == before["rate_ppm"], (
        "nothing about the pilot moved, so the rate must not move"
    )
    assert revised["version"] == before["version"] + 1
    assert fx.fetch_schedule(api, book["schedule_id"]) == revised


def test_a_value_revision_posts_the_annual_difference_as_one_rerate_row(api):
    """PRD §3.4: "When that difference is not zero and the policy's `status` is `BOUND`, a
    `RERATE_ADJUSTMENT` ledger row is appended with a `basis` of `ANNUAL`, a null
    `endorsement_id`, an `effective_date` of the current logical clock and an
    `amount_cents` equal to the difference; a zero difference or a draft policy writes no
    row."

    Design: Corner/endpoints/corner_value_revision_action_reprices_and_posts_one_ledger_row
    """
    book = fx.bound_policy_with_hull(api)
    policy = book["policy"]
    before = fx.fetch_schedule(api, book["schedule_id"])
    _, initial_premium = _expected_hull_terms(
        policy, book["pilot"], before["use_class"], before["agreed_value_cents"], 1
    )
    _, revised_premium = _expected_hull_terms(
        policy, book["pilot"], before["use_class"], REVISED_AGREED_VALUE_CENTS, 1
    )
    expected_delta = revised_premium - initial_premium
    assert expected_delta != 0, "the revision must move the premium"

    validate_unpaginated(
        api.revise_schedule_value(
            book["schedule_id"],
            f.value_revision_payload(REVISED_AGREED_VALUE_CENTS, before["version"]),
            headers=users.UNDERWRITER,
        )
    )

    rows, meta = validate_list(
        api.list_premium_transactions(
            headers=users.UNDERWRITER, params={"policy_id": book["policy_id"]}
        )
    )

    assert meta["total_count"] == 2
    assert_ledger_txn_types(rows, [TxnType.INITIAL_PREMIUM, TxnType.RERATE_ADJUSTMENT])
    assert_ledger_row(
        rows[0],
        txn_type=TxnType.INITIAL_PREMIUM,
        amount_cents=initial_premium,
        basis=TxnBasis.ANNUAL,
        effective_date=policy["effective_from"],
        policy_id=book["policy_id"],
    )
    assert_ledger_row(
        rows[1],
        txn_type=TxnType.RERATE_ADJUSTMENT,
        amount_cents=expected_delta,
        basis=TxnBasis.ANNUAL,
        effective_date=f.CLOCK_BEFORE_INCEPTION,
        policy_id=book["policy_id"],
    )
    assert rows[1]["endorsement_id"] is None
    assert_premium_transaction_shape(rows[1])
    assert_no_zero_amount_rows(rows)

    after = fx.fetch_policy(api, book["policy_id"])
    assert_field_values(
        after,
        status=PolicyStatus.BOUND,
        total_hull_sum_insured_cents=REVISED_AGREED_VALUE_CENTS,
        live_schedule_count=1,
        written_premium_cents=revised_premium,
    )
    assert after["written_premium_cents"] == ledger_signed_sum(rows)


# ----------------------------------------------------------------------
# The war-risk placement surface
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "broken_reference,expected_error",
    [
        ("market_id", ApiErrorId.MARKET_NOT_FOUND),
        ("policy_id", ApiErrorId.POLICY_NOT_FOUND),
    ],
)
def test_a_placement_body_must_resolve_both_the_policy_and_the_market(
    api, broken_reference, expected_error
):
    """PRD §2.11: "Every foreign key in the request body resolves, in the declared
    body-field order — the matching not-found code, 404."

    Design: Corner/endpoints/corner_war_placement_links_policy_and_market_and_both_must_exist
    """
    book = fx.registered_book(api)
    policy = fx.make_policy(api, book["operator_id"], policy_type=PolicyType.FLEET)
    market = fx.make_war_market(api)

    payload = f.war_placement_payload(policy["id"], market["id"], policy["version"])
    payload[broken_reference] = NON_EXISTENT_UUID

    validate_error(
        api.create_war_placement(payload, headers=users.UNDERWRITER), expected_error
    )

    placements, meta = validate_list(
        api.list_war_placements(
            headers=users.UNDERWRITER, params={"market_id": market["id"]}
        )
    )
    assert placements == [], "a refused placement must not be recorded"
    assert meta["total_count"] == 0

    after_market = fx.fetch_war_market(api, market["id"])
    assert_field_values(
        after_market,
        committed_line_cents=0,
        available_line_cents=after_market["aggregate_line_cents"],
    )
    assert fx.fetch_policy(api, policy["id"])["version"] == policy["version"], (
        "a refused placement must not advance the policy"
    )


def test_a_placement_links_the_policy_and_the_market_on_both_sides(api):
    """PRD §3.7: "Creating a placement appends one `WAR_RISK_PREMIUM` ledger row, updates
    the market's `committed_line_cents` and `available_line_cents`, re-derives the policy's
    `written_premium_cents` and advances the policy's `version`."

    Design: Corner/endpoints/corner_war_placement_links_policy_and_market_and_both_must_exist
    """
    book = fx.registered_book(api)
    policy = fx.make_policy(api, book["operator_id"], policy_type=PolicyType.FLEET)
    market = fx.make_war_market(api)
    assert_war_market_shape(market)

    response = api.create_war_placement(
        f.war_placement_payload(
            policy["id"],
            market["id"],
            policy["version"],
            war_hull_line_cents=WAR_HULL_LINE_CENTS,
            perils_scope=PerilsScope.WAR_ONLY,
            coverage_from=f.POLICY_EFFECTIVE_FROM,
            coverage_to=f.POLICY_EFFECTIVE_TO,
        ),
        headers=users.UNDERWRITER,
    )
    placement = validate_unpaginated(response, expected_status=201)

    expected_premium = c.war_premium_cents(
        WAR_HULL_LINE_CENTS, PerilsScope.WAR_ONLY, policy["territorial_limit_code"]
    )
    assert response.status_code == 201
    assert_war_placement_shape(placement)
    assert_fields_present(placement, a.WAR_PLACEMENT_FIELDS)
    assert_field_values(
        placement,
        policy_id=policy["id"],
        market_id=market["id"],
        war_hull_line_cents=WAR_HULL_LINE_CENTS,
        perils_scope=PerilsScope.WAR_ONLY,
        status=PlacementStatus.BOUND,
        premium_cents=expected_premium,
    )
    assert placement["cancellation_reason"] is None
    assert_instants_equal(placement["coverage_from"], f.POLICY_EFFECTIVE_FROM)
    assert_instants_equal(placement["coverage_to"], f.POLICY_EFFECTIVE_TO)
    assert fx.fetch_war_placement(api, placement["id"]) == placement

    by_market, market_meta = validate_list(
        api.list_war_placements(
            headers=users.UNDERWRITER, params={"market_id": market["id"]}
        )
    )
    assert [row["id"] for row in by_market] == [placement["id"]]
    assert market_meta["total_count"] == 1

    by_policy, policy_meta = validate_list(
        api.list_war_placements(
            headers=users.UNDERWRITER,
            params={"policy_id": policy["id"], "status": PlacementStatus.BOUND},
        )
    )
    assert [row["id"] for row in by_policy] == [placement["id"]]
    assert policy_meta["total_count"] == 1

    after_market = fx.fetch_war_market(api, market["id"])
    assert_field_values(
        after_market,
        committed_line_cents=WAR_HULL_LINE_CENTS,
        available_line_cents=market["aggregate_line_cents"] - WAR_HULL_LINE_CENTS,
    )

    after_policy = fx.fetch_policy(api, policy["id"])
    assert_field_values(
        after_policy,
        status=PolicyStatus.DRAFT,
        written_premium_cents=expected_premium,
        version=policy["version"] + 1,
    )

    rows = fx.ledger_rows(api, policy["id"])
    assert_ledger_txn_types(rows, [TxnType.WAR_RISK_PREMIUM])
    assert_ledger_row(
        rows[0],
        txn_type=TxnType.WAR_RISK_PREMIUM,
        amount_cents=expected_premium,
        policy_id=policy["id"],
    )
    assert after_policy["written_premium_cents"] == ledger_signed_sum(rows)


# ----------------------------------------------------------------------
# The policy read across a leap day
# ----------------------------------------------------------------------
def test_a_term_spanning_a_leap_day_is_one_day_longer(api):
    """PRD §3.3: "`term_days` is the pro-rata denominator used by every apportioned charge
    on the policy, and it is the number of whole days between the calendar date of
    `effective_from` and the calendar date of `effective_to`."

    Design: Corner/endpoints/corner_policy_read_rederives_term_days_across_a_leap_day
    """
    book = fx.registered_book(api)
    common_term = fx.make_policy(
        api,
        book["operator_id"],
        effective_from=f.POLICY_EFFECTIVE_FROM,
        effective_to=f.POLICY_EFFECTIVE_TO,
    )
    leap_term = fx.make_policy(
        api,
        book["operator_id"],
        effective_from=LEAP_TERM_FROM,
        effective_to=LEAP_TERM_TO,
    )

    expected_common = c.whole_days_between(f.POLICY_EFFECTIVE_FROM, f.POLICY_EFFECTIVE_TO)
    expected_leap = c.whole_days_between(LEAP_TERM_FROM, LEAP_TERM_TO)

    assert common_term["term_days"] == expected_common == f.POLICY_TERM_DAYS
    assert leap_term["term_days"] == expected_leap
    assert leap_term["term_days"] == common_term["term_days"] + 1, (
        "the term carrying the extra February day counts one more whole day"
    )

    for policy, expected in ((common_term, expected_common), (leap_term, expected_leap)):
        read_back = fx.fetch_policy(api, policy["id"])
        assert_policy_shape(read_back)
        assert read_back["term_days"] == expected
        assert_instants_equal(read_back["effective_from"], policy["effective_from"])
        assert_instants_equal(read_back["effective_to"], policy["effective_to"])


def test_the_leap_term_policy_prices_its_hull_over_the_longer_term(api):
    """PRD §3.3: "`written_premium_cents` is the signed sum of the whole ledger for the
    policy, as set out in §2.9."

    Design: Corner/endpoints/corner_policy_read_rederives_term_days_across_a_leap_day
    """
    book = fx.registered_book(api)
    policy = fx.make_policy(
        api,
        book["operator_id"],
        effective_from=LEAP_TERM_FROM,
        effective_to=LEAP_TERM_TO,
    )
    pilot = book["senior_pilot"]
    ceiling = c.over_insurance_ceiling_cents(
        c.depreciated_value_cents(
            book["aircraft"]["hull_new_value_cents"],
            book["aircraft"]["manufacture_year"],
            c.calendar_year_of(LEAP_TERM_FROM),
        )
    )
    assert LEAP_HULL_VALUE_CENTS <= ceiling, "the hull must clear the ceiling"

    schedule = fx.make_schedule(
        api,
        policy["id"],
        book["aircraft_id"],
        pilot["id"],
        agreed_value_cents=LEAP_HULL_VALUE_CENTS,
        effective_from=LEAP_TERM_FROM,
        effective_to=LEAP_TERM_TO,
    )
    expected_rate, expected_premium = _expected_hull_terms(
        policy, pilot, schedule["use_class"], LEAP_HULL_VALUE_CENTS, live_count=1
    )
    assert schedule["rate_ppm"] == expected_rate
    assert schedule["hull_premium_cents"] == expected_premium

    bound = fx.bind_policy(api, policy["id"])
    assert_policy_shape(bound)
    assert_field_values(
        bound,
        status=PolicyStatus.BOUND,
        term_days=c.whole_days_between(LEAP_TERM_FROM, LEAP_TERM_TO),
        total_hull_sum_insured_cents=LEAP_HULL_VALUE_CENTS,
        live_schedule_count=1,
        written_premium_cents=expected_premium,
        outstanding_reserve_cents=0,
        paid_hull_cents=0,
    )
    assert fx.fetch_schedule(api, schedule["id"])["coverage_status"] == (
        CoverageStatus.ACTIVE
    )

    rows = fx.ledger_rows(api, policy["id"])
    assert_ledger_txn_types(rows, [TxnType.INITIAL_PREMIUM])
    assert_ledger_row(
        rows[0],
        txn_type=TxnType.INITIAL_PREMIUM,
        amount_cents=expected_premium,
        basis=TxnBasis.ANNUAL,
        effective_date=LEAP_TERM_FROM,
        policy_id=policy["id"],
    )
    assert bound["written_premium_cents"] == ledger_signed_sum(rows)


# ----------------------------------------------------------------------
# The acquisition source and the policy state it demands
# ----------------------------------------------------------------------
def _fleet_clause_book(api):
    """Two bound fleet policies — one with the fleet clause, one without — and a draft."""
    book = fx.registered_book(api)
    frames = [
        fx.make_aircraft(
            api,
            f.single_piston_aircraft_payload(
                registration_mark=f.unique_registration_mark()
            ),
        )
        for _ in range(3)
    ]
    pilot = book["senior_pilot"]

    without_clause = fx.make_policy(
        api,
        book["operator_id"],
        policy_type=PolicyType.FLEET,
        automatic_acquisition_enabled=False,
    )
    fx.make_schedule(
        api,
        without_clause["id"],
        frames[0]["id"],
        pilot["id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
    )
    fx.bind_policy(api, without_clause["id"])

    with_clause = fx.make_policy(
        api,
        book["operator_id"],
        policy_type=PolicyType.FLEET,
        automatic_acquisition_enabled=True,
    )
    fx.make_schedule(
        api,
        with_clause["id"],
        frames[1]["id"],
        pilot["id"],
        use_class=UseClass.PRIVATE,
        agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
    )
    fx.bind_policy(api, with_clause["id"])

    still_draft = fx.make_policy(
        api,
        book["operator_id"],
        policy_type=PolicyType.FLEET,
        automatic_acquisition_enabled=True,
    )

    fx.advance_clock(api, f.CLOCK_MID_TERM)
    return {
        "pilot": pilot,
        "frames": frames,
        "without_clause": fx.fetch_policy(api, without_clause["id"]),
        "with_clause": fx.fetch_policy(api, with_clause["id"]),
        "still_draft": fx.fetch_policy(api, still_draft["id"]),
    }


def test_the_fleet_clause_flag_and_the_bound_state_both_gate_an_automatic_hull(api):
    """PRD §3.4: "An `AUTOMATIC_ACQUISITION` attachment represents an aircraft bought
    mid-term under the fleet clause and requires the policy to be in `BOUND`; attempting one
    against a draft or expired policy is refused with `ERR_POLICY_NOT_BOUND`, and attempting
    one against a policy whose `automatic_acquisition_enabled` is false is refused with
    `ERR_AUTO_ACQUISITION_DISABLED`."

    Design: Corner/endpoints/corner_acquisition_source_flips_the_required_policy_state
    """
    book = _fleet_clause_book(api)
    without_clause = book["without_clause"]
    still_draft = book["still_draft"]

    def automatic_payload(policy_id, aircraft_id):
        return f.schedule_payload(
            policy_id,
            aircraft_id,
            book["pilot"]["id"],
            use_class=UseClass.PRIVATE,
            agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
            acquisition_source=AcquisitionSource.AUTOMATIC_ACQUISITION,
            effective_from=f.CLOCK_MID_TERM,
        )

    validate_error(
        api.create_schedule(
            automatic_payload(without_clause["id"], book["frames"][2]["id"]),
            headers=users.UNDERWRITER,
        ),
        ApiErrorId.AUTO_ACQUISITION_DISABLED,
    )
    validate_error(
        api.create_schedule(
            automatic_payload(still_draft["id"], book["frames"][2]["id"]),
            headers=users.UNDERWRITER,
        ),
        ApiErrorId.POLICY_NOT_BOUND,
    )

    assert len(fx.schedules_of_policy(api, without_clause["id"])) == 1
    assert fx.schedules_of_policy(api, still_draft["id"]) == []
    for policy_id, live in ((without_clause["id"], 1), (still_draft["id"], 0)):
        after = fx.fetch_policy(api, policy_id)
        assert after["live_schedule_count"] == live, (
            "a refused attachment must leave the policy's population alone"
        )


def test_a_scheduled_hull_demands_a_draft_policy(api):
    """PRD §3.4: "A `SCHEDULED` attachment is part of the original underwriting and requires
    the policy to be in `DRAFT`; attempting one against a bound or expired policy is refused
    with `ERR_POLICY_NOT_DRAFT`."

    Design: Corner/endpoints/corner_acquisition_source_flips_the_required_policy_state
    """
    book = _fleet_clause_book(api)
    frame = book["frames"][2]

    validate_error(
        api.create_schedule(
            f.schedule_payload(
                book["with_clause"]["id"],
                frame["id"],
                book["pilot"]["id"],
                use_class=UseClass.PRIVATE,
                agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
                acquisition_source=AcquisitionSource.SCHEDULED,
            ),
            headers=users.UNDERWRITER,
        ),
        ApiErrorId.POLICY_NOT_DRAFT,
    )

    response = api.create_schedule(
        f.schedule_payload(
            book["still_draft"]["id"],
            frame["id"],
            book["pilot"]["id"],
            use_class=UseClass.PRIVATE,
            agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
            acquisition_source=AcquisitionSource.SCHEDULED,
        ),
        headers=users.UNDERWRITER,
    )
    accepted = validate_unpaginated(response, expected_status=201)
    assert_schedule_shape(accepted)
    assert_field_values(
        accepted,
        policy_id=book["still_draft"]["id"],
        acquisition_source=AcquisitionSource.SCHEDULED,
        coverage_status=CoverageStatus.PENDING,
        warranty_status=WarrantyStatus.PENDING_EVIDENCE,
    )
    assert [row["id"] for row in fx.schedules_of_policy(api, book["with_clause"]["id"])] == [
        row["id"]
        for row in fx.schedules_of_policy(
            api, book["with_clause"]["id"], coverage_status=CoverageStatus.ACTIVE
        )
    ], "the refused attachment left the bound policy with only its activated hull"


def test_an_automatic_hull_on_a_bound_fleet_policy_is_covered_but_uncharged(api):
    """PRD §3.8: "Where a policy has `automatic_acquisition_enabled` set to true, a new hull
    may be attached with `acquisition_source` `AUTOMATIC_ACQUISITION` against the `BOUND`
    policy, and it sits in `coverage_status` `PENDING`: it is covered and counts toward
    `total_hull_sum_insured_cents`, but it has not been activated and no premium has been
    charged for it."

    Design: Corner/endpoints/corner_acquisition_source_flips_the_required_policy_state
    """
    book = _fleet_clause_book(api)
    policy = book["with_clause"]
    ledger_before = fx.ledger_rows(api, policy["id"])

    response = api.create_schedule(
        f.schedule_payload(
            policy["id"],
            book["frames"][2]["id"],
            book["pilot"]["id"],
            use_class=UseClass.PRIVATE,
            agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
            acquisition_source=AcquisitionSource.AUTOMATIC_ACQUISITION,
            effective_from=f.CLOCK_MID_TERM,
        ),
        headers=users.UNDERWRITER,
    )
    acquired = validate_unpaginated(response, expected_status=201)

    expected_rate, expected_premium = _expected_hull_terms(
        policy, book["pilot"], UseClass.PRIVATE, PRIVATE_HULL_VALUE_CENTS, live_count=2
    )
    assert_schedule_shape(acquired)
    assert_field_values(
        acquired,
        acquisition_source=AcquisitionSource.AUTOMATIC_ACQUISITION,
        coverage_status=CoverageStatus.PENDING,
        agreed_value_cents=PRIVATE_HULL_VALUE_CENTS,
        rate_ppm=expected_rate,
        hull_premium_cents=expected_premium,
    )
    assert acquired["reported_declaration_id"] is None
    assert_instants_equal(acquired["effective_from"], f.CLOCK_MID_TERM)

    after = fx.fetch_policy(api, policy["id"])
    assert_field_values(
        after,
        status=PolicyStatus.BOUND,
        total_hull_sum_insured_cents=PRIVATE_HULL_VALUE_CENTS * 2,
        live_schedule_count=2,
        written_premium_cents=policy["written_premium_cents"],
    )
    assert fx.ledger_rows(api, policy["id"]) == ledger_before, (
        "the automatic attachment charges no premium of its own"
    )
    assert after["written_premium_cents"] == ledger_signed_sum(ledger_before)
