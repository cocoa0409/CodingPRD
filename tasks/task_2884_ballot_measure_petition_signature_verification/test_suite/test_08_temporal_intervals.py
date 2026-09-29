"""Two interval regimes that differ at their endpoints.

Cure periods occupy a half-open interval, so a new period may open exactly on
the previous deadline. Assignments occupy a closed interval widened by a
three-day buffer on each side, so adjacency is forbidden and a two-day gap is
still a conflict.

Note on list assertions: §2.4 fixes pagination but pins no default ordering for
list endpoints, so these tests assert membership and count rather than position.
"""
from test_helpers import (
    api_client,
    assert_instants_equal,
    create_assignment_payload,
    parse_instant,
    file_batch_with_lines,
    make_sos_admin_headers,
    open_cure_period,
    open_round,
    read_circulator,
    read_cure_period,
    read_line,
    read_petition,
    run_verification_round,
    setup_circulation_ready,
    tally_round,
    validate_error,
    validate_open_sample,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import set_clock

CURE_VOTERS = [
    {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "registration_status": "INACTIVE"},
    {"voter_id_number": "VA3", "registration_status": "INACTIVE"},
]


class TestCurePeriodHalfOpenInterval:
    """`opened_at` inclusive, `deadline_at` exclusive — so adjacency is legal
    and anything inside the first interval is not."""

    def _petition_with_one_closed_cure(self):
        """A petition driven to CURE_PERIOD, given a first cure period C1 over
        [2026-09-01, 2026-10-01), fed one supplemental line that turned out
        invalid, and closed by a CURE_RECHECK round."""
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            counties=[("ALPHA", 20)],
            voters=CURE_VOTERS,
            effective_to="2026-12-31T00:00:00Z",
        )
        file_batch_with_lines(world, ["VA1", "VA2"], batch_key="b1")
        first = run_verification_round(world)
        assert first["sample_size"] == 2
        assert first["validity_rate_bps"] == 5000
        assert first["projected_valid_count"] == 1
        assert first["determination"] == "INSUFFICIENT"
        assert read_petition(world["petition"]["id"])["status"] == "CURE_PERIOD"

        set_clock("2026-09-01T00:00:00Z")
        first_cure = open_cure_period(world["petition"]["id"])
        assert first_cure["opened_at"] == "2026-09-01T00:00:00.000Z"
        assert first_cure["deadline_at"] == "2026-10-01T00:00:00.000Z"
        assert first_cure["shortfall_at_open"] == 1
        assert first_cure["assumed_validity_rate_bps"] == 5000
        assert first_cure["cure_target_raw_signatures"] == 2, "ceil(1 * 10000 / 5000)"
        world["first_cure"] = first_cure

        set_clock("2026-09-05T00:00:00Z")
        file_batch_with_lines(
            world,
            [{"claimed_voter_id_number": "VA3", "signed_on": "2026-09-05T00:00:00Z"}],
            batch_key="b2",
            is_supplemental=True,
            cure_period_id=first_cure["id"],
        )
        recheck = open_round(
            world["petition"]["id"],
            round_type="CURE_RECHECK",
            cure_period_id=first_cure["id"],
        )
        assert recheck["eligible_pool_size"] == 1, (
            "only the supplemental line is still unexamined"
        )
        world["round"] = recheck
        validate_open_sample(world)
        closed = tally_round(recheck["id"])
        assert closed["validity_rate_bps"] == 0
        assert closed["determination"] == "INSUFFICIENT"
        assert read_line(world["batches"]["b2"]["lines"][0]["id"])[
            "validation_status"
        ] == "INVALID_NOT_REGISTERED"
        assert read_cure_period(first_cure["id"])["status"] == "CLOSED_INSUFFICIENT"
        assert read_petition(world["petition"]["id"])["status"] == "CURE_PERIOD", (
            "one period consumed of two, and still above the eligibility floor"
        )
        return world

    def test_a_second_cure_period_cannot_open_inside_the_first_interval(self):
        """The clock sits strictly between `opened_at` and `deadline_at`, so the
        proposed interval overlaps the closed period.

        PRD §3.7: "the new period must not overlap any existing cure period of
        the same petition, refused with ERR_CURE_PERIOD_OVERLAP ... The pair is
        treated as a half-open interval: opened_at is inclusive, deadline_at is
        exclusive, and it is those half-open intervals that the overlap check
        compares."

        Design: Difficulty/resource_temporal_overlap/cure_period_half_open_adjacency_allowed_on_petition
        """
        world = self._petition_with_one_closed_cure()

        set_clock("2026-09-15T00:00:00Z")
        validate_error(
            api_client.create_cure_period(world["petition"]["id"], make_sos_admin_headers()),
            "ERR_CURE_PERIOD_OVERLAP",
            409,
        )

        petition = read_petition(world["petition"]["id"])
        assert petition["cure_period_count"] == 1, "the refusal created nothing"
        assert petition["status"] == "CURE_PERIOD"

    def test_a_second_cure_period_may_open_exactly_on_the_first_deadline(self):
        """`deadline_at` is exclusive, so an adjacent period is admissible — and
        the observed rate of zero is clamped up before the target division.

        PRD §3.7: "assumed_validity_rate_bps is the round's validity_rate_bps
        clamped into the inclusive range from 2500 basis points to 10000 basis
        points — the floor exists so that a pathological observed rate of zero
        cannot produce an infinite target ... the clamp is applied before the
        division, not after. A shortfall of 1 at an observed rate of 2500 basis
        points therefore yields a target of 4 raw signatures."

        Design: Difficulty/resource_temporal_overlap/cure_period_half_open_adjacency_allowed_on_petition
        """
        world = self._petition_with_one_closed_cure()

        set_clock("2026-10-01T00:00:00Z")
        second = open_cure_period(world["petition"]["id"])
        assert second["opened_at"] == "2026-10-01T00:00:00.000Z", (
            "adjacency is legal: the first interval excluded this instant"
        )
        assert second["deadline_at"] == "2026-10-31T00:00:00.000Z"
        assert second["shortfall_at_open"] == 1
        assert second["assumed_validity_rate_bps"] == 2500, (
            "the recheck's observed rate of 0 is clamped up to the statutory floor"
        )
        assert second["cure_target_raw_signatures"] == 4, "ceil(1 * 10000 / 2500)"
        assert second["status"] == "OPEN"

        petition = read_petition(world["petition"]["id"])
        assert petition["cure_period_count"] == 2, "the counter counts periods in any status"
        assert petition["verified_valid_count"] == 1
        assert petition["verification_cost_accrued_cents"] == 15, "10 + 5"


class TestAssignmentClosedIntervalBuffer:
    """`[effective_from, effective_to]` widened by ASSIGNMENT_BUFFER_DAYS on
    both sides — so adjacency conflicts and only a full three-day gap clears."""

    FIRST_FROM = "2026-08-01T00:00:00Z"
    FIRST_TO = "2026-08-10T00:00:00Z"
    LATER_TO = "2026-08-31T00:00:00Z"

    def _world_with_first_assignment(self):
        """One ACTIVE assignment occupying the closed span 2026-08-01 through
        2026-08-10, plus the circulator's version read once and reused for every
        later attempt so optimistic concurrency can never be the refusal."""
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            counties=[("ALPHA", 20)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
            effective_from=self.FIRST_FROM,
            effective_to=self.FIRST_TO,
        )
        assert world["assignments"]["c1"]["status"] == "ACTIVE"
        world["circulator_version"] = read_circulator(
            world["circulators"]["c1"]["id"]
        )["version"]
        return world

    def _attempt(self, world, effective_from):
        return api_client.create_circulation_assignment(
            create_assignment_payload(
                world["petition"]["id"],
                world["circulators"]["c1"]["id"],
                world["circulator_version"],
                assigned_county_codes=["ALPHA"],
                effective_from=effective_from,
                effective_to=self.LATER_TO,
            ),
            make_sos_admin_headers(),
        )

    def test_an_assignment_starting_on_the_previous_end_date_is_refused(self):
        """Adjacency is not enough: the closed interval already contains
        2026-08-10, and the buffer extends three days past it.

        PRD §3.3: "The occupied interval is the closed span from effective_from
        through effective_to, extended by a three-day clearance on each side. A
        new assignment must clear every interval already occupied by an ACTIVE or
        SUSPENDED assignment of the same circulator by at least those three days
        on both sides; a request that fails to is refused with
        ERR_ASSIGNMENT_WINDOW_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/assignment_closed_interval_buffer_on_circulator
        """
        world = self._world_with_first_assignment()

        validate_error(
            self._attempt(world, "2026-08-10T00:00:00Z"),
            "ERR_ASSIGNMENT_WINDOW_CONFLICT",
            409,
        )

        assert read_circulator(world["circulators"]["c1"]["id"])["version"] == (
            world["circulator_version"]
        ), "a refused create never advances the circulator's version"

    def test_an_assignment_two_days_after_the_previous_end_is_refused(self):
        """A two-day gap is short of ASSIGNMENT_BUFFER_DAYS, so the buffer still
        bites.

        PRD §3.3: "A new assignment must clear every interval already occupied by
        an ACTIVE or SUSPENDED assignment of the same circulator by at least those
        three days on both sides."

        Design: Difficulty/resource_temporal_overlap/assignment_closed_interval_buffer_on_circulator
        """
        world = self._world_with_first_assignment()

        validate_error(
            self._attempt(world, "2026-08-12T00:00:00Z"),
            "ERR_ASSIGNMENT_WINDOW_CONFLICT",
            409,
        )

        assert read_circulator(world["circulators"]["c1"]["id"])["version"] == (
            world["circulator_version"]
        )

    def test_an_assignment_three_days_after_the_previous_end_is_admitted(self):
        """Exactly three days of clearance satisfies the buffer, and the
        circulator then holds two assignments.

        PRD §3.3: "A new assignment must clear every interval already occupied by
        an ACTIVE or SUSPENDED assignment of the same circulator by at least those
        three days on both sides."

        Design: Difficulty/resource_temporal_overlap/assignment_closed_interval_buffer_on_circulator
        """
        world = self._world_with_first_assignment()

        created = validate_success(self._attempt(world, "2026-08-13T00:00:00Z"), 201)
        assert created["status"] == "ACTIVE"
        assert_instants_equal(
            created["effective_from"], "2026-08-13T00:00:00Z", "effective_from"
        )

        assignments, meta = validate_paginated(
            api_client.list_circulation_assignments(
                make_sos_admin_headers(),
                params={"circulator_id": world["circulators"]["c1"]["id"]},
            )
        )
        assert meta["total_count"] == 2
        assert {parse_instant(row["effective_from"]) for row in assignments} == {
            parse_instant("2026-08-01T00:00:00Z"),
            parse_instant("2026-08-13T00:00:00Z"),
        }
