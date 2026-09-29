"""Two occupancy resources with two different interval semantics.

An inspector's on-site time is an explicit half-open window bounded by two
client-supplied instants, so bookings that merely touch are legal while genuine
overlaps are refused.  A structure's bond coverage, by contrast, has no
client-supplied end instant at all: the occupancy opens at issuance and closes
only when the occupying bond reaches ``TERMINATED``.
"""

import pytest

from test_helpers import (
    BOND_ACTIVE,
    BOND_LAPSED,
    BOND_TERMINATED,
    CLOCK_STARTUP_INSTANT,
    ERR_DUPLICATE_ACTIVE_BOND,
    ERR_INSPECTOR_SCHEDULE_OVERLAP,
    ERR_INVALID_BOND_STATE,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    PLAN_COMPLETED,
    TIER_REPAIR_AND_RETREAT,
    assert_bond_money,
    assert_status,
    bond_payload,
    inspection_payload,
    make_field_inspector_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    clean_initial_graph,
    completed_liquid_plan,
    register_inspector,
    register_property,
    register_property_and_inspector,
    review_bond_term,
    set_clock,
)

# The one stored booking every probe is measured against.
BASE_START = "2026-08-10T09:00:00Z"
BASE_END = "2026-08-10T12:00:00Z"

BOND_ISSUE_INSTANT = "2026-09-01T00:00:00Z"
LAPSE_REVIEW_INSTANT = "2027-10-05T00:00:00Z"
REINSTATEMENT_DEADLINE_INSTANT = "2027-12-30T00:00:00Z"
TERMINATION_REVIEW_INSTANT = "2027-12-31T00:00:00Z"

EXPECTED_TERM_END = "2027-09-01"
EXPECTED_LAPSE_DATE = "2027-10-01"
EXPECTED_SECOND_TERM_START = "2027-12-31"
EXPECTED_SECOND_TERM_END = "2028-12-30"

EXPECTED_BASE_PREMIUM = 194.40
EXPECTED_REPAIR_CAP = 11664.00


def _property_and_two_inspectors(api):
    """One FL structure and two FL licensees with independent diaries."""
    set_clock(api, CLOCK_STARTUP_INSTANT)
    prop = register_property(api, state_code="FL")
    first = register_inspector(api, license_state="FL", full_name="Rosa Vance")
    second = register_inspector(api, license_state="FL", full_name="Cleo Ridge")
    return prop, first, second


def _book(api, property_id, inspector_id, start_at, end_at):
    """Attempt one occupation of the structure, returning the raw response."""
    payload = inspection_payload(
        property_id,
        inspector_id,
        scheduled_start_at=start_at,
        scheduled_end_at=end_at,
    )
    return api.create_inspection(payload, make_field_inspector_headers(inspector_id))


def _base_booking(api):
    """A structure, two licensees and the first licensee's 09:00-12:00 booking."""
    prop, first, second = _property_and_two_inspectors(api)
    base = validate_success(
        _book(api, prop["id"], first["id"], BASE_START, BASE_END), 201
    )
    return prop, first, second, base


class TestInspectorOccupationHalfOpenInterval:
    """Touching endpoints are legal; containment in either direction is not."""

    @pytest.mark.parametrize(
        "start_at,end_at",
        [
            ("2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z"),
            ("2026-08-10T07:00:00Z", "2026-08-10T09:00:00Z"),
        ],
        ids=["new_start_equals_stored_end", "new_end_equals_stored_start"],
    )
    def test_bookings_that_merely_touch_are_accepted(self, api, start_at, end_at):
        """A visit ending exactly when the next begins is not an overlap.

        PRD 3.3: "Intervals that merely touch — one visit ending at the exact
        instant the next begins — are permitted", because each of the
        inspector's graphs is treated "as the half-open interval running from
        its `scheduled_start_at` up to but not including its
        `scheduled_end_at`."

        Design: Difficulty/resource_temporal_overlap/inspector_occupation_half_open_interval_adjacency_allowed
        """
        prop, first, _second, base = _base_booking(api)

        adjacent = validate_success(
            _book(api, prop["id"], first["id"], start_at, end_at), 201
        )
        assert adjacent["inspector_id"] == first["id"]
        assert adjacent["sequence_no"] == base["sequence_no"] + 1, (
            "the accepted booking takes the structure's next sequence_no"
        )

    @pytest.mark.parametrize(
        "start_at,end_at",
        [
            ("2026-08-10T11:00:00Z", "2026-08-10T13:00:00Z"),
            ("2026-08-10T09:30:00Z", "2026-08-10T10:30:00Z"),
            ("2026-08-10T08:00:00Z", "2026-08-10T15:00:00Z"),
        ],
        ids=["straddles_the_stored_end", "strictly_inside", "strictly_containing"],
    )
    def test_bookings_that_genuinely_overlap_are_refused(self, api, start_at, end_at):
        """Any shared instant collides, including containment either way.

        PRD 3.3: "no other interval of that inspector may overlap the requested
        one ... a genuine overlap is `ERR_INSPECTOR_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/inspector_occupation_half_open_interval_adjacency_allowed
        """
        prop, first, _second, _base = _base_booking(api)

        response = _book(api, prop["id"], first["id"], start_at, end_at)
        validate_error(response, ERR_INSPECTOR_SCHEDULE_OVERLAP)

        rows, meta = validate_paginated(
            api.list_inspections(OFFICER_HEADERS, property_id=prop["id"])
        )
        assert meta["total_count"] == 1, (
            "a refused booking must not create a graph: %r" % rows
        )

    def test_the_contended_resource_is_the_inspector_not_the_calendar_slot(self, api):
        """A second licensee may take the very window the first was refused.

        PRD 3.3: the collision test is against "the inspector's own diary:
        treating each of that inspector's graphs as the half-open interval
        running from its `scheduled_start_at` up to but not including its
        `scheduled_end_at`."

        Design: Difficulty/resource_temporal_overlap/inspector_occupation_half_open_interval_adjacency_allowed
        """
        prop, first, second, _base = _base_booking(api)
        contested_start = "2026-08-10T09:30:00Z"
        contested_end = "2026-08-10T10:30:00Z"

        validate_error(
            _book(api, prop["id"], first["id"], contested_start, contested_end),
            ERR_INSPECTOR_SCHEDULE_OVERLAP,
        )
        other = validate_success(
            _book(api, prop["id"], second["id"], contested_start, contested_end), 201
        )
        assert other["inspector_id"] == second["id"], (
            "the second licensee holds the window the first could not"
        )

    def test_refused_bookings_consume_no_sequence_number(self, api):
        """The structure's sequence numbers run 1..4 over the accepted bookings.

        PRD 3.3: a new graph "is stamped with a `sequence_no`: a 1-based counter
        that is one greater than the highest `sequence_no` yet issued for that
        structure."

        Design: Difficulty/resource_temporal_overlap/inspector_occupation_half_open_interval_adjacency_allowed
        """
        prop, first, second, base = _base_booking(api)

        after = validate_success(
            _book(
                api,
                prop["id"],
                first["id"],
                "2026-08-10T12:00:00Z",
                "2026-08-10T14:00:00Z",
            ),
            201,
        )
        before = validate_success(
            _book(
                api,
                prop["id"],
                first["id"],
                "2026-08-10T07:00:00Z",
                "2026-08-10T09:00:00Z",
            ),
            201,
        )
        for start_at, end_at in (
            ("2026-08-10T11:00:00Z", "2026-08-10T13:00:00Z"),
            ("2026-08-10T09:30:00Z", "2026-08-10T10:30:00Z"),
            ("2026-08-10T08:00:00Z", "2026-08-10T15:00:00Z"),
        ):
            validate_error(
                _book(api, prop["id"], first["id"], start_at, end_at),
                ERR_INSPECTOR_SCHEDULE_OVERLAP,
            )
        other = validate_success(
            _book(
                api,
                prop["id"],
                second["id"],
                "2026-08-10T09:30:00Z",
                "2026-08-10T10:30:00Z",
            ),
            201,
        )

        assert [
            base["sequence_no"],
            after["sequence_no"],
            before["sequence_no"],
            other["sequence_no"],
        ] == [1, 2, 3, 4], "the three refusals must not consume a sequence_no"

        rows, meta = validate_paginated(
            api.list_inspections(OFFICER_HEADERS, property_id=prop["id"])
        )
        assert meta["total_count"] == 4, (
            "only the four accepted bookings exist: %r" % [row["id"] for row in rows]
        )


def _issue(api, property_id, treatment_plan_id):
    """The identical issuance body replayed at every status of the sitting bond."""
    payload = bond_payload(
        property_id,
        treatment_plan_id,
        coverage_tier=TIER_REPAIR_AND_RETREAT,
        conducive_waiver_codes=[],
    )
    return api.create_bond(payload, MANAGER_HEADERS)


def _two_completed_plans_and_a_bond(api):
    """One structure, two independently COMPLETED plans and a bond on the first.

    The second plan is proposed only after the first has left `PROPOSED`, so the
    proposal sweep of PRD 3.5 never abandons it.
    """
    set_clock(api, CLOCK_STARTUP_INSTANT)
    prop, inspector = register_property_and_inspector(api, state_code="FL")
    graph = clean_initial_graph(api, prop["id"], inspector["id"])
    first_plan = completed_liquid_plan(
        api, prop["id"], graph["id"], inspector["id"]
    )
    second_plan = completed_liquid_plan(
        api, prop["id"], graph["id"], inspector["id"]
    )
    assert_status(second_plan, PLAN_COMPLETED, "treatment_plan")
    set_clock(api, BOND_ISSUE_INSTANT)
    bond = validate_success(_issue(api, prop["id"], first_plan["id"]), 201)
    return prop, first_plan, second_plan, bond


def _lapse(api, bond_id):
    """Drive the sitting bond past its grace deadline and review it into LAPSED."""
    set_clock(api, LAPSE_REVIEW_INSTANT)
    lapsed = review_bond_term(api, bond_id)
    assert_status(lapsed, BOND_LAPSED, "bond")
    return lapsed


class TestPropertyCoverageOccupancyPersistsThroughLapse:
    """Capacity is one bond over the status set {ACTIVE, LAPSED}."""

    def test_a_second_bond_is_refused_while_the_first_is_active(self, api):
        """One live bond occupies the structure completely.

        PRD 3.7: "a structure may hold at most one bond in status `ACTIVE` or
        `LAPSED` at any instant, and a second issuance is refused with
        `ERR_DUPLICATE_ACTIVE_BOND`."

        Design: Difficulty/resource_temporal_overlap/property_bond_coverage_occupancy_persists_through_lapse
        """
        prop, _first_plan, second_plan, bond = _two_completed_plans_and_a_bond(api)
        assert_status(bond, BOND_ACTIVE, "bond")
        assert bond["current_term_end"] == EXPECTED_TERM_END, (
            "a 365-day term from 2026-09-01 ends 2027-09-01"
        )

        validate_error(
            _issue(api, prop["id"], second_plan["id"]), ERR_DUPLICATE_ACTIVE_BOND
        )

        _rows, meta = validate_paginated(
            api.list_bonds(MANAGER_HEADERS, property_id=prop["id"])
        )
        assert meta["total_count"] == 1, "the refusal must not create a second bond"
        losing = validate_success(
            api.get_treatment_plan(second_plan["id"], MANAGER_HEADERS)
        )
        assert_status(losing, PLAN_COMPLETED, "treatment_plan")
        assert losing["version"] == second_plan["version"], (
            "a refused issuance must not advance the losing plan's version"
        )

    def test_a_second_bond_is_still_refused_while_the_first_is_lapsed(self, api):
        """A lapsed bond is dead by the calendar yet still occupies the structure.

        PRD 3.7: "a second issuance is refused with `ERR_DUPLICATE_ACTIVE_BOND`
        even when the first bond is mid-lapse — a lapsed bond is still an
        encumbrance on the structure until it terminates."

        Design: Difficulty/resource_temporal_overlap/property_bond_coverage_occupancy_persists_through_lapse
        """
        prop, _first_plan, second_plan, bond = _two_completed_plans_and_a_bond(api)
        lapsed = _lapse(api, bond["id"])
        assert lapsed["lapse_date"] == EXPECTED_LAPSE_DATE, (
            "PRD 3.8 records the grace deadline that was missed, not the review date"
        )

        validate_error(
            _issue(api, prop["id"], second_plan["id"]), ERR_DUPLICATE_ACTIVE_BOND
        )

        _rows, meta = validate_paginated(
            api.list_bonds(MANAGER_HEADERS, property_id=prop["id"])
        )
        assert meta["total_count"] == 1, (
            "the structure still holds exactly one bond while the first is LAPSED"
        )
        losing = validate_success(
            api.get_treatment_plan(second_plan["id"], MANAGER_HEADERS)
        )
        assert losing["version"] == second_plan["version"], (
            "a refused issuance must not advance the losing plan's version"
        )

    def test_the_reinstatement_deadline_day_itself_does_not_free_the_structure(self, api):
        """On the ninetieth day the bond is still buyable back, so still occupying.

        PRD 3.8: termination requires a bond "already `LAPSED` and whose clock
        date has passed `lapse_date` plus 90 days"; "A review that finds neither
        deadline passed changes nothing and is refused with
        `ERR_INVALID_BOND_STATE`."

        Design: Difficulty/resource_temporal_overlap/property_bond_coverage_occupancy_persists_through_lapse
        """
        prop, _first_plan, second_plan, bond = _two_completed_plans_and_a_bond(api)
        _lapse(api, bond["id"])

        set_clock(api, REINSTATEMENT_DEADLINE_INSTANT)
        validate_error(
            api.term_review(bond["id"], {}, OFFICER_HEADERS), ERR_INVALID_BOND_STATE
        )
        still_lapsed = validate_success(api.get_bond(bond["id"], MANAGER_HEADERS))
        assert_status(still_lapsed, BOND_LAPSED, "bond")

        validate_error(
            _issue(api, prop["id"], second_plan["id"]), ERR_DUPLICATE_ACTIVE_BOND
        )

    def test_a_second_bond_is_admitted_once_the_first_terminates(self, api):
        """The occupancy closes at the TERMINATED transition and not a day earlier.

        PRD 3.8: review of a bond "already `LAPSED` and whose clock date has
        passed `lapse_date` plus 90 days moves it `LAPSED → TERMINATED`, which
        is terminal."

        Design: Difficulty/resource_temporal_overlap/property_bond_coverage_occupancy_persists_through_lapse
        """
        prop, _first_plan, second_plan, bond = _two_completed_plans_and_a_bond(api)
        _lapse(api, bond["id"])

        set_clock(api, TERMINATION_REVIEW_INSTANT)
        terminated = review_bond_term(api, bond["id"])
        assert_status(terminated, BOND_TERMINATED, "bond")

        replacement = validate_success(
            _issue(api, prop["id"], second_plan["id"]), 201
        )
        assert_status(replacement, BOND_ACTIVE, "bond")
        assert replacement["current_term_start"] == EXPECTED_SECOND_TERM_START
        assert replacement["current_term_end"] == EXPECTED_SECOND_TERM_END, (
            "the replacement bond's own 365-day term runs from the issuance date"
        )
        assert_bond_money(
            replacement,
            base_premium_usd=EXPECTED_BASE_PREMIUM,
            repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
            remaining_repair_cap_usd=EXPECTED_REPAIR_CAP,
        )

        rows, meta = validate_paginated(
            api.list_bonds(MANAGER_HEADERS, property_id=prop["id"])
        )
        assert meta["total_count"] == 2, "the structure now records two bonds"
        statuses = sorted(row["status"] for row in rows)
        assert statuses == sorted([BOND_ACTIVE, BOND_TERMINATED]), (
            "capacity one over {ACTIVE, LAPSED} was never breached: %r" % statuses
        )
