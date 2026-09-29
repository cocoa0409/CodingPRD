"""The two occupancy conventions: half-open seat terms and closed asset periods.

Committee seats and tagged assets are both single-occupancy resources, and the
specification deliberately reads their intervals the opposite way round. A seat
term is half-open, so a successor may start on the day the incumbent's term ends;
an asset service period is closed and then inflated by a fourteen-day
mobilisation buffer, so even a fortnight's gap is still a collision.
"""

from test_helpers import (
    STOP_DRAFT,
    assert_cents,
    errors,
    f,
    k,
    validate_unpaginated,
    validate_error,
)

# --- Committee seat scenario data ------------------------------------------
EARLY_CHILDHOOD_CIP = "19.0709"

CONTESTED_SEAT = "EMP-3"
INCUMBENT_TERM_START = "2026-01-01"
INCUMBENT_TERM_END = "2027-01-01"
SUCCESSOR_TERM_END = "2027-12-31"
DAY_BEFORE_INCUMBENT_TERM_END = "2026-12-31"

# --- Tagged asset scenario data --------------------------------------------
MECHATRONICS_CIP = "15.0403"

ASSET_TAG = "LATHE-01"
RIG_UNIT_COST_CENTS = 300000
GRANT_ALLOCATION_CENTS = 5000000

FIRST_PERIOD_START = "2026-09-01"
FIRST_PERIOD_END = "2026-09-30"

# Fourteen days after the incumbent period's closing day, and one day later.
FOURTEEN_DAY_GAP_START = "2026-10-14"
FIFTEEN_DAY_GAP_START = "2026-10-15"
SECOND_PERIOD_END = "2026-11-30"

SECOND_BOOKING_DESCRIPTION = "Second rig booking"


def _committee_with_incumbent_seat(build):
    """A chartered committee holding four seated members, EMP-3 among them."""
    scenario = build.program(
        EARLY_CHILDHOOD_CIP,
        stop_at=STOP_DRAFT,
        title="Early Childhood Education",
        cluster=k.CLUSTER_HEALTH_SCIENCE,
    )
    committee_row = build.charter_committee(
        scenario.program_id,
        name="Early Childhood Advisory Committee",
        quorum_min_members=3,
        employer_seat_min=2,
    )
    committee = build.seat_roster(committee_row["id"])
    incumbent = build.seat_member(
        committee.committee_id,
        "Hana Ito",
        k.SECTOR_EMPLOYER,
        CONTESTED_SEAT,
        term_start_on=INCUMBENT_TERM_START,
        term_end_on=INCUMBENT_TERM_END,
    )
    return committee, incumbent["id"]


def _successor_payload(term_start_on):
    """A second employer claiming the contested seat from ``term_start_on``."""
    return f.member_payload(
        "Leo Marsh",
        k.SECTOR_EMPLOYER,
        CONTESTED_SEAT,
        term_start_on=term_start_on,
        term_end_on=SUCCESSOR_TERM_END,
    )


def _award_with_tagged_rig(build):
    """A grant award carrying one REQUESTED, asset-tagged September booking."""
    scenario = build.program(
        MECHATRONICS_CIP,
        stop_at=STOP_DRAFT,
        title="Mechatronics",
        cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
    )
    grant = build.grant(
        fiscal_year=2027,
        allocation_cents=GRANT_ALLOCATION_CENTS,
        obligation_window_start="2026-07-01",
        obligation_window_end="2027-06-30",
    )
    first = build.expenditure(
        grant.grant_id,
        scenario.program_id,
        k.CATEGORY_EQUIPMENT,
        RIG_UNIT_COST_CENTS,
        service_period_start=FIRST_PERIOD_START,
        service_period_end=FIRST_PERIOD_END,
        asset_tag=ASSET_TAG,
        description="Mechatronics trainer rig",
    )
    return scenario, grant, first["id"]


def _second_booking_payload(program_id, award_version, service_period_start):
    """A second booking of the same tagged asset, starting on the given day."""
    return f.expenditure_payload(
        program_id,
        k.CATEGORY_EQUIPMENT,
        RIG_UNIT_COST_CENTS,
        1,
        award_version,
        service_period_start=service_period_start,
        service_period_end=SECOND_PERIOD_END,
        description=SECOND_BOOKING_DESCRIPTION,
        asset_tag=ASSET_TAG,
    )


class TestCommitteeSeatTermOccupancy:
    """A seat term runs [term_start_on, term_end_on), so adjacency is legal."""

    def test_a_successor_starting_before_the_incumbent_term_ends_is_refused(
        self, api, build, director_headers
    ):
        """PRD §3.3: "A new member is refused with `ERR_SEAT_TERM_OVERLAP` when an existing `ACTIVE` member on the same committee holds the same `seat_code` and the two terms genuinely overlap — that is, when the new `term_start_on` falls strictly before the incumbent's `term_end_on` and the incumbent's `term_start_on` falls strictly before the new `term_end_on`."

        Design: Difficulty/resource_temporal_overlap/committee_seat_terms_are_half_open_so_a_term_starting_on_the_end_date_is_legal
        """
        committee, _incumbent_id = _committee_with_incumbent_seat(build)

        response = api.seat_member(
            committee.committee_id,
            _successor_payload(DAY_BEFORE_INCUMBENT_TERM_END),
            director_headers,
        )

        validate_error(response, errors.ERR_SEAT_TERM_OVERLAP)

    def test_a_successor_starting_on_the_incumbent_end_date_is_seated(
        self, api, build, director_headers
    ):
        """PRD §3.3: "A new member is refused with `ERR_SEAT_TERM_OVERLAP` when an existing `ACTIVE` member on the same committee holds the same `seat_code` and the two terms genuinely overlap — that is, when the new `term_start_on` falls strictly before the incumbent's `term_end_on` and the incumbent's `term_start_on` falls strictly before the new `term_end_on`. Adjacency is consequently legal: a successor whose `term_start_on` is exactly the incumbent's `term_end_on` is accepted, because a zero-length gap is not an overlap."

        PRD §2.5: "Committee seat terms are **half-open**: a member's term covers every date from `term_start_on` inclusive up to but excluding `term_end_on`, so the seat is free again on `term_end_on` itself and back-to-back terms are legal."

        Design: Difficulty/resource_temporal_overlap/committee_seat_terms_are_half_open_so_a_term_starting_on_the_end_date_is_legal
        """
        committee, _incumbent_id = _committee_with_incumbent_seat(build)

        response = api.seat_member(
            committee.committee_id,
            _successor_payload(INCUMBENT_TERM_END),
            director_headers,
        )

        successor = validate_unpaginated(response, 201)
        assert successor["status"] == k.MEMBER_ACTIVE
        assert successor["seat_code"] == CONTESTED_SEAT
        assert successor["term_start_on"] == INCUMBENT_TERM_END

    def test_the_incumbent_holds_its_seat_after_the_successor_is_seated(
        self, api, build, director_headers
    ):
        """PRD §3.3: "A member's `status` begins as `ACTIVE` and becomes `EXPIRED` once the logical clock's date reaches `term_end_on`; the term is inclusive of `term_start_on` and exclusive of `term_end_on`."

        PRD §2.5: "Before any client sets it, that clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."

        Design: Difficulty/resource_temporal_overlap/committee_seat_terms_are_half_open_so_a_term_starting_on_the_end_date_is_legal
        """
        committee, incumbent_id = _committee_with_incumbent_seat(build)
        validate_unpaginated(
            api.seat_member(
                committee.committee_id,
                _successor_payload(INCUMBENT_TERM_END),
                director_headers,
            ),
            201,
        )

        incumbent = validate_unpaginated(
            api.get_member(incumbent_id, director_headers), 200
        )
        assert incumbent["status"] == k.MEMBER_ACTIVE
        assert incumbent["term_end_on"] == INCUMBENT_TERM_END

    def test_back_to_back_seating_rebuilds_the_committee_member_counts(
        self, api, build, director_headers
    ):
        """PRD §3.3: "Each successful seating rebuilds the committee's derived counts. `active_member_count` becomes the number of that committee's members whose `status` is `ACTIVE`, `employer_member_count` becomes the number of those whose `sector` is also `EMPLOYER`, and `chair_member_id` becomes the `id` of the single `ACTIVE` member whose `is_chair` is true (staying null while no such member exists)."

        Design: Difficulty/resource_temporal_overlap/committee_seat_terms_are_half_open_so_a_term_starting_on_the_end_date_is_legal
        """
        committee, _incumbent_id = _committee_with_incumbent_seat(build)
        validate_unpaginated(
            api.seat_member(
                committee.committee_id,
                _successor_payload(INCUMBENT_TERM_END),
                director_headers,
            ),
            201,
        )

        row = validate_unpaginated(
            api.get_committee(committee.committee_id, director_headers), 200
        )
        assert row["active_member_count"] == 5
        # The default roster seats EMP-1 and EMP-2 as employers alongside the
        # POSTSECONDARY seat; the incumbent on EMP-3 and its back-to-back
        # successor are both employers and both still ACTIVE at the default
        # clock, so four of the five ACTIVE members carry sector EMPLOYER.
        assert row["employer_member_count"] == 4
        assert row["chair_member_id"] == committee.chair_member_id


class TestTaggedAssetServicePeriodOccupancy:
    """A tagged asset's closed period is inflated by fourteen days on each side."""

    def test_a_second_booking_fourteen_days_after_the_first_still_collides(
        self, api, build, director_headers
    ):
        """PRD §3.7: "When `asset_tag` is non-null, the new request is refused if any existing expenditure on the same award carries the same `asset_tag`, holds a `status` of `REQUESTED`, `CERTIFIED`, `OBLIGATED` or `BLOCKED`, and has a service period that comes within a two-week mobilisation buffer of the new one. Concretely: the request fails when the new `service_period_start` falls on or before the incumbent's `service_period_end` plus 14 days **and** the new `service_period_end` falls on or after the incumbent's `service_period_start` minus 14 days. Adjacency is therefore illegal here — a gap of exactly 14 days between the two periods is rejected, and only a gap of 15 days or more is accepted. The refusal is `ERR_ASSET_PERIOD_OVERLAP`."

        PRD §2.5: "Grant obligation windows and asset service periods are **closed** on both ends: `obligation_window_start` and `obligation_window_end` are both obligable days, and `service_period_start` and `service_period_end` are both days of possession."

        Design: Difficulty/resource_temporal_overlap/tagged_asset_periods_are_closed_and_inflated_by_a_fourteen_day_mobilisation_buffer
        """
        scenario, grant, _first_id = _award_with_tagged_rig(build)
        award_version = build.grant_version(grant.grant_id)

        response = api.request_expenditure(
            grant.grant_id,
            _second_booking_payload(
                scenario.program_id, award_version, FOURTEEN_DAY_GAP_START
            ),
            director_headers,
        )

        validate_error(response, errors.ERR_ASSET_PERIOD_OVERLAP)

    def test_a_second_booking_fifteen_days_after_the_first_is_accepted(
        self, api, build, director_headers
    ):
        """PRD §3.7: "When `asset_tag` is non-null, the new request is refused if any existing expenditure on the same award carries the same `asset_tag`, holds a `status` of `REQUESTED`, `CERTIFIED`, `OBLIGATED` or `BLOCKED`, and has a service period that comes within a two-week mobilisation buffer of the new one. Concretely: the request fails when the new `service_period_start` falls on or before the incumbent's `service_period_end` plus 14 days **and** the new `service_period_end` falls on or after the incumbent's `service_period_start` minus 14 days. Adjacency is therefore illegal here — a gap of exactly 14 days between the two periods is rejected, and only a gap of 15 days or more is accepted. The refusal is `ERR_ASSET_PERIOD_OVERLAP`."

        PRD §3.7: "The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification, leaves `certified_by_user_id`, `finding_code`, `obligation_reference` and `void_reason` null, and increments the award's `version`."

        Design: Difficulty/resource_temporal_overlap/tagged_asset_periods_are_closed_and_inflated_by_a_fourteen_day_mobilisation_buffer
        """
        scenario, grant, _first_id = _award_with_tagged_rig(build)
        award_version = build.grant_version(grant.grant_id)

        response = api.request_expenditure(
            grant.grant_id,
            _second_booking_payload(
                scenario.program_id, award_version, FIFTEEN_DAY_GAP_START
            ),
            director_headers,
        )

        booking = validate_unpaginated(response, 201)
        assert booking["status"] == k.EXP_REQUESTED
        assert booking["asset_tag"] == ASSET_TAG
        assert booking["service_period_start"] == FIFTEEN_DAY_GAP_START
        assert booking["service_period_end"] == SECOND_PERIOD_END
        assert_cents(booking["gross_cents"], RIG_UNIT_COST_CENTS, "gross_cents")
        assert booking["approved_cents"] is None

    def test_the_refused_booking_leaves_the_award_version_untouched(
        self, api, build, director_headers, fiscal_headers
    ):
        """PRD §2.4: "`version` is an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that record, including mutations the record did not itself request — a cascade that changes a program's approval status increments that program's `version` just as an explicit call would."

        PRD §2.9: "Requesting an expenditure against a grant award requires `expected_grant_award_version` in the body, carrying the client's last observed `version` of that `GrantAward`. A mismatch with the award's current `version` is refused with `ERR_STALE_GRANT_VERSION` (HTTP 412)."

        Design: Difficulty/resource_temporal_overlap/tagged_asset_periods_are_closed_and_inflated_by_a_fourteen_day_mobilisation_buffer
        """
        scenario, grant, _first_id = _award_with_tagged_rig(build)
        award_version = build.grant_version(grant.grant_id)

        validate_error(
            api.request_expenditure(
                grant.grant_id,
                _second_booking_payload(
                    scenario.program_id, award_version, FOURTEEN_DAY_GAP_START
                ),
                director_headers,
            ),
            errors.ERR_ASSET_PERIOD_OVERLAP,
        )

        award = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers), 200)
        assert award["version"] == award_version
        # The same observed version still guards a request the buffer admits.
        validate_unpaginated(
            api.request_expenditure(
                grant.grant_id,
                _second_booking_payload(
                    scenario.program_id, award_version, FIFTEEN_DAY_GAP_START
                ),
                director_headers,
            ),
            201,
        )

    def test_neither_booking_moves_the_obligation_ledger(
        self, api, build, director_headers, fiscal_headers
    ):
        """PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation."

        PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero, and `admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents."

        Design: Difficulty/resource_temporal_overlap/tagged_asset_periods_are_closed_and_inflated_by_a_fourteen_day_mobilisation_buffer
        """
        scenario, grant, first_id = _award_with_tagged_rig(build)
        award_version = build.grant_version(grant.grant_id)
        validate_unpaginated(
            api.request_expenditure(
                grant.grant_id,
                _second_booking_payload(
                    scenario.program_id, award_version, FIFTEEN_DAY_GAP_START
                ),
                director_headers,
            ),
            201,
        )

        incumbent = validate_unpaginated(
            api.get_expenditure(first_id, fiscal_headers), 200
        )
        assert incumbent["status"] == k.EXP_REQUESTED
        assert incumbent["service_period_start"] == FIRST_PERIOD_START
        assert incumbent["service_period_end"] == FIRST_PERIOD_END

        award = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers), 200)
        assert_cents(award["direct_obligated_cents"], 0, "direct_obligated_cents")
        assert_cents(award["obligated_cents"], 0, "obligated_cents")
        assert_cents(
            award["remaining_cents"], GRANT_ALLOCATION_CENTS, "remaining_cents"
        )
