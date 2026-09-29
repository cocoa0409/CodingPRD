"""Temporal overlap of two resources that share a scarce thing.

Two aircraft schedules compete for one airframe and two war placements compete
for one market's aggregate line, but the two conventions are deliberately
opposite: the schedule window is half-open, so schedules that touch are merely
adjacent, while the placement interval is closed, so placements that touch do
overlap.  Both conventions are exercised from the accepting and the refusing
side.
"""

from test_helpers import (
    ApiErrorId,
    CoverageStatus,
    PerilsScope,
    PilotBand,
    PlacementStatus,
    PolicyStatus,
    UseClass,
    assert_field_values,
    assert_ids_in_order,
    assert_instants_equal,
    validate_error,
    validate_list,
    validate_unpaginated,
)
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

SHARED_ENDPOINT = "2027-01-01T00:00:00Z"
STRADDLE_FROM = "2026-12-01T00:00:00Z"
STRADDLE_TO = "2027-02-01T00:00:00Z"
PLACEMENT_ENDPOINT = "2027-03-01T00:00:00Z"


def _band_of(pilot, clock_utc):
    """The rating band a pilot's declared figures earn at a given clock."""
    return c.band_for_score(
        c.qualification_score(
            pilot["total_logged_hours"],
            pilot["hours_on_type"],
            pilot["instrument_rated"],
            pilot["license_type"],
            pilot["last_training_completed_at"],
            clock_utc,
        )
    )


def _expected_private_premium(policy, pilot, agreed_value_cents, live_count):
    rate_ppm = c.rate_ppm_for(
        policy["base_hull_rate_ppm"],
        UseClass.PRIVATE,
        policy["territorial_limit_code"],
        _band_of(pilot, f.CLOCK_BEFORE_INCEPTION),
    )
    return c.annual_premium_cents(
        agreed_value_cents, rate_ppm, policy["policy_type"], live_count
    )


# ----------------------------------------------------------------------
# One airframe, one draft policy, three candidate coverage windows
# ----------------------------------------------------------------------
def _draft_policy_and_one_airframe(api):
    """A draft policy and a single airframe with no cover scheduled on it yet."""
    book = fx.registered_book(api)
    policy = fx.make_policy(api, book["operator_id"])
    book["policy"] = policy
    book["policy_id"] = policy["id"]
    return book


def _window_payload(book, effective_from, effective_to):
    return f.private_schedule_payload(
        book["policy_id"],
        book["aircraft_id"],
        book["pilot_id"],
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _two_touching_schedules(api, book):
    """The two adjacent halves of the term, both scheduled on the one airframe."""
    first = validate_unpaginated(
        api.create_schedule(
            _window_payload(book, f.POLICY_EFFECTIVE_FROM, SHARED_ENDPOINT),
            headers=users.UNDERWRITER,
        ),
        expected_status=201,
    )
    second = validate_unpaginated(
        api.create_schedule(
            _window_payload(book, SHARED_ENDPOINT, f.POLICY_EFFECTIVE_TO),
            headers=users.UNDERWRITER,
        ),
        expected_status=201,
    )
    return first, second


class TestAircraftCoverageHalfOpenAdjacency:
    """One airframe may carry back-to-back cover but never doubled cover."""

    def test_two_schedules_touching_at_one_endpoint_are_both_accepted(self, api):
        """PRD §3.4: "Windows that merely touch — where one schedule's `effective_to`
        equals another's `effective_from` — are adjacent rather than overlapping, and are
        allowed."

        Design: Difficulty/resource_temporal_overlap/aircraft_coverage_half_open_adjacency_allowed
        """
        book = _draft_policy_and_one_airframe(api)
        policy = book["policy"]
        first_payload = _window_payload(book, f.POLICY_EFFECTIVE_FROM, SHARED_ENDPOINT)
        expected_first = _expected_private_premium(
            policy, book["pilot"], first_payload["agreed_value_cents"], live_count=1
        )
        expected_second = _expected_private_premium(
            policy, book["pilot"], first_payload["agreed_value_cents"], live_count=2
        )

        first, second = _two_touching_schedules(api, book)

        assert_field_values(
            first,
            aircraft_id=book["aircraft_id"],
            coverage_status=CoverageStatus.PENDING,
            hull_premium_cents=expected_first,
            rated_pilot_band=PilotBand.BAND_C,
        )
        assert_instants_equal(first["effective_to"], SHARED_ENDPOINT, "effective_to")
        assert_field_values(
            second,
            aircraft_id=book["aircraft_id"],
            coverage_status=CoverageStatus.PENDING,
            hull_premium_cents=expected_second,
            rated_pilot_band=PilotBand.BAND_C,
        )
        assert_instants_equal(second["effective_from"], SHARED_ENDPOINT, "effective_from")
        assert second["id"] != first["id"], "the adjacent window is a second schedule"

    def test_a_window_straddling_the_shared_endpoint_is_refused_as_an_overlap(self, api):
        """PRD §3.4: "Two schedules for the same `aircraft_id` conflict when their
        windows, treated as half-open intervals that include the start instant and
        exclude the end instant, intersect."

        Design: Difficulty/resource_temporal_overlap/aircraft_coverage_half_open_adjacency_allowed
        """
        book = _draft_policy_and_one_airframe(api)
        first, second = _two_touching_schedules(api, book)

        response = api.create_schedule(
            _window_payload(book, STRADDLE_FROM, STRADDLE_TO), headers=users.UNDERWRITER
        )
        validate_error(response, ApiErrorId.AIRCRAFT_COVERAGE_OVERLAP)

        rows, meta = validate_list(
            api.list_schedules(
                headers=users.UNDERWRITER,
                params={"aircraft_id": book["aircraft_id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 2, (
            "the refused window must leave the two adjacent schedules alone, "
            f"got {meta['total_count']} schedules on the airframe"
        )
        assert_ids_in_order(rows, [first["id"], second["id"]])

    def test_the_refused_overlap_leaves_the_draft_policy_aggregates_untouched(self, api):
        """PRD §3.3: "`total_hull_sum_insured_cents` is the sum of `agreed_value_cents`
        over the schedules on the policy whose `coverage_status` is `PENDING`, `ACTIVE`
        or `SUSPENDED_WARRANTY`; schedules that have reached `TOTAL_LOSS_SETTLED` or
        `REMOVED` are excluded."

        Design: Difficulty/resource_temporal_overlap/aircraft_coverage_half_open_adjacency_allowed
        """
        book = _draft_policy_and_one_airframe(api)
        first, second = _two_touching_schedules(api, book)
        validate_error(
            api.create_schedule(
                _window_payload(book, STRADDLE_FROM, STRADDLE_TO),
                headers=users.UNDERWRITER,
            ),
            ApiErrorId.AIRCRAFT_COVERAGE_OVERLAP,
        )

        policy = fx.fetch_policy(api, book["policy_id"])
        assert_field_values(
            policy,
            status=PolicyStatus.DRAFT,
            live_schedule_count=2,
            total_hull_sum_insured_cents=(
                first["agreed_value_cents"] + second["agreed_value_cents"]
            ),
            written_premium_cents=0,
        )


# ----------------------------------------------------------------------
# Two policies competing for one market's aggregate line
# ----------------------------------------------------------------------
def _two_bound_single_aircraft_policies(api):
    """Two bound single-airframe policies, one market, and one line already ceded.

    The first policy's slip runs to the shared endpoint, so the second policy's
    slip can start exactly where the first one finishes.
    """
    book = fx.registered_book(api)
    policies = []
    for aircraft_id in (book["single_id"], book["aircraft_id"]):
        policy = validate_unpaginated(
            api.create_policy(
                f.single_aircraft_policy_payload(book["operator_id"]),
                headers=users.UNDERWRITER,
            ),
            expected_status=201,
        )
        validate_unpaginated(
            api.create_schedule(
                f.private_schedule_payload(
                    policy["id"], aircraft_id, book["senior_pilot_id"]
                ),
                headers=users.UNDERWRITER,
            ),
            expected_status=201,
        )
        policies.append(fx.bind_policy(api, policy["id"]))

    market_payload = f.war_market_payload()
    market = fx.make_war_market(api, market_payload)
    first_placement_payload = f.war_placement_payload(
        policies[0]["id"], market["id"], policies[0]["version"]
    )
    first_placement = validate_unpaginated(
        api.create_war_placement(first_placement_payload, headers=users.UNDERWRITER),
        expected_status=201,
    )
    book.update(
        {
            "policy_a": fx.fetch_policy(api, policies[0]["id"]),
            "policy_a_id": policies[0]["id"],
            "policy_b": fx.fetch_policy(api, policies[1]["id"]),
            "policy_b_id": policies[1]["id"],
            "market_id": market["id"],
            "aggregate_line_cents": market_payload["aggregate_line_cents"],
            "placement_a": first_placement,
            "placement_a_line_cents": first_placement_payload["war_hull_line_cents"],
        }
    )
    return book


def _touching_placement_payload(book, war_hull_line_cents):
    """A slip on the second policy that starts where the first one ends."""
    return f.war_placement_payload(
        book["policy_b_id"],
        book["market_id"],
        book["policy_b"]["version"],
        war_hull_line_cents=war_hull_line_cents,
        coverage_from=PLACEMENT_ENDPOINT,
        coverage_to=f.POLICY_EFFECTIVE_TO,
    )


class TestWarMarketClosedIntervalTouchingOverlaps:
    """Placements that share an endpoint compete for the same market capacity."""

    def test_two_placements_touching_at_one_endpoint_exceed_the_market_line(self, api):
        """PRD §3.7: "Under that definition two placements that merely touch at an
        endpoint **do** overlap."

        Design: Difficulty/resource_temporal_overlap/war_market_closed_interval_touching_endpoints_overlap
        """
        book = _two_bound_single_aircraft_policies(api)
        assert_instants_equal(
            book["placement_a"]["coverage_to"], PLACEMENT_ENDPOINT, "coverage_to"
        )
        headroom = book["aggregate_line_cents"] - book["placement_a_line_cents"]

        response = api.create_war_placement(
            _touching_placement_payload(book, headroom + 100000000),
            headers=users.UNDERWRITER,
        )
        validate_error(response, ApiErrorId.MARKET_LINE_EXCEEDED)

    def test_the_refused_placement_leaves_the_market_and_the_policy_untouched(self, api):
        """PRD §3.7: "A market's `committed_line_cents` starts at 0 and is always the sum
        of `war_hull_line_cents` over the placements on that market whose `status` is
        `BOUND`, with cancelled placements excluded; its `available_line_cents` starts
        equal to `aggregate_line_cents` and is always `aggregate_line_cents` less
        `committed_line_cents`."

        Design: Difficulty/resource_temporal_overlap/war_market_closed_interval_touching_endpoints_overlap
        """
        book = _two_bound_single_aircraft_policies(api)
        policy_b_before = book["policy_b"]
        headroom = book["aggregate_line_cents"] - book["placement_a_line_cents"]

        validate_error(
            api.create_war_placement(
                _touching_placement_payload(book, headroom + 100000000),
                headers=users.UNDERWRITER,
            ),
            ApiErrorId.MARKET_LINE_EXCEEDED,
        )

        market = fx.fetch_war_market(api, book["market_id"])
        assert_field_values(
            market,
            committed_line_cents=book["placement_a_line_cents"],
            available_line_cents=headroom,
        )
        policy_b_after = fx.fetch_policy(api, book["policy_b_id"])
        assert_field_values(
            policy_b_after,
            version=policy_b_before["version"],
            written_premium_cents=policy_b_before["written_premium_cents"],
        )

    def test_the_overlapping_line_may_be_filled_to_its_last_cent(self, api):
        """PRD §3.7: "The test is inclusive, so filling the line to its last cent
        succeeds; exceeding it by one cent is refused with `ERR_MARKET_LINE_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/war_market_closed_interval_touching_endpoints_overlap
        """
        book = _two_bound_single_aircraft_policies(api)
        policy_a_before = book["policy_a"]
        policy_b_before = book["policy_b"]
        headroom = book["aggregate_line_cents"] - book["placement_a_line_cents"]
        validate_error(
            api.create_war_placement(
                _touching_placement_payload(book, headroom + 100000000),
                headers=users.UNDERWRITER,
            ),
            ApiErrorId.MARKET_LINE_EXCEEDED,
        )

        exact_payload = _touching_placement_payload(book, headroom)
        expected_premium = c.war_premium_cents(
            headroom,
            exact_payload["perils_scope"],
            policy_b_before["territorial_limit_code"],
        )

        placement = validate_unpaginated(
            api.create_war_placement(exact_payload, headers=users.UNDERWRITER),
            expected_status=201,
        )
        assert_field_values(
            placement,
            status=PlacementStatus.BOUND,
            war_hull_line_cents=headroom,
            perils_scope=PerilsScope.WAR_HIJACK,
            premium_cents=expected_premium,
        )

        market = fx.fetch_war_market(api, book["market_id"])
        assert_field_values(
            market,
            committed_line_cents=book["aggregate_line_cents"],
            available_line_cents=0,
        )
        policy_b_after = fx.fetch_policy(api, book["policy_b_id"])
        assert_field_values(
            policy_b_after,
            written_premium_cents=(
                policy_b_before["written_premium_cents"] + expected_premium
            ),
            version=policy_b_before["version"] + 1,
        )
        policy_a_after = fx.fetch_policy(api, book["policy_a_id"])
        assert_field_values(
            policy_a_after,
            written_premium_cents=policy_a_before["written_premium_cents"],
            version=policy_a_before["version"],
        )
