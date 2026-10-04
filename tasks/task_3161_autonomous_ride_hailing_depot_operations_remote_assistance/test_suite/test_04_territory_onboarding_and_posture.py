"""Bringing a territory online: mapping ticks, validation runs, posture gates.

A territory cannot serve a rider until it has cleared mapping coverage and
supervised validation hours, and its posture is decided by an evaluation
order in which the exclusion-zone gates always win.
"""

from test_helpers import constants as c
from test_helpers.api_errors import ERR_INVALID_STATE, ERR_NOT_FOUND
from test_helpers.assertions import get_success_data, validate_error, validate_paginated, validate_success
from test_helpers.fixtures import (
    activate_zones,
    create_exclusion_zone,
    create_territory,
    read_territory,
    set_clock,
)
from test_helpers.test_users import FLEET, MAPPING, PLANNER, SAFETY


class TestTerritoryRegistration:
    """A fresh territory carries the zero accumulators and a derived posture."""

    def test_territory_created_without_posture_input_starts_pending(self, api):
        """Registration freezes the accumulators at zero and derives PENDING.

        PRD 3.1: "Registration freezes the accumulators into their starting
        values: `active_zone_count` begins at zero, `total_credit_cents` begins
        at zero, and `total_severe_incidents` begins at zero."
        PRD 3.1: "The `posture` is then derived from those figures under the
        rules in section 2.7, which for a fresh territory with no mapping
        progress means `PENDING`."

        Design: Corner/entities/if_match_territory_create_starts_pending_with_zero_counters
        """
        set_clock(api)
        resp = api.create_territory(
            {"name": "Phoenix Metro", "region_code": "PHX-METRO"}, headers=PLANNER
        )
        territory = validate_success(resp, expected_status=201)

        assert territory["posture"] == c.POSTURE_PENDING
        assert territory["mapped_pct"] == 0
        assert territory["validation_hours"] == 0
        assert territory["active_zone_count"] == 0
        assert territory["total_credit_cents"] == 0
        assert territory["total_severe_incidents"] == 0
        assert territory["version"] == 1

    def test_territory_posture_is_never_client_supplied(self, api):
        """Supplying a posture in the body cannot steer the derived value.

        PRD 3.1: "Registration freezes the accumulators into their starting
        values: `active_zone_count` begins at zero, `total_credit_cents` begins
        at zero, and `total_severe_incidents` begins at zero."

        Design: Corner/entities/if_match_territory_create_starts_pending_with_zero_counters
        """
        set_clock(api)
        territory = create_territory(
            api, name="Smuggled", region_code="SMG-METRO", posture=c.POSTURE_ACTIVE
        )
        assert territory["posture"] == c.POSTURE_PENDING, (
            "posture is derived from the accumulators, never accepted from the client"
        )


class TestTerritoryListing:
    """The territory list is paginated with a total count and a has-more flag."""

    def test_three_territories_paginate_two_then_one(self, api):
        """A limit of 2 over three territories reports total_count 3.

        PRD 2.3: "The `limit` parameter caps how many items are returned; when
        omitted it defaults to 10, and it accepts a minimum of 1 and a maximum
        of 100. The `offset` parameter skips that many items from the front of
        the result set and defaults to 0."
        PRD 2.3: "The `meta` object of a paginated response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/if_match_territory_list_pagination_envelope
        """
        set_clock(api)
        create_territory(api, name="T1", region_code="T1-METRO")
        create_territory(api, name="T2", region_code="T2-METRO")
        create_territory(api, name="T3", region_code="T3-METRO")

        page_one, meta_one = validate_paginated(
            api.list_territories(headers=FLEET, params={"limit": 2, "offset": 0})
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True

        page_two, meta_two = validate_paginated(
            api.list_territories(headers=FLEET, params={"limit": 2, "offset": 2})
        )
        assert len(page_two) == 1
        assert meta_two["has_more"] is False


class TestMappingAndValidationGates:
    """Mapping ticks accumulate coverage; validation runs need MAPPING first."""

    def test_validation_run_in_pending_is_refused(self, api):
        """Hours cannot be logged before any mapping progress exists.

        PRD 3.1: "A run logged in any other posture — including `PENDING`,
        `RESTRICTED` or `SUSPENDED` — is refused with `ERR_INVALID_STATE`
        (HTTP 409), and so is a mapping tick logged outside `PENDING`."
        PRD 3.1: "A `MappingEngineer` or a `SafetyReviewer` logs a validation run
        carrying an `hours` figure, which is added to the territory's cumulative
        `validation_hours`. Runs are accepted while the territory's `posture` is
        either `MAPPING` or `VALIDATING`."

        Design: Corner/state_machines/if_match_validation_run_in_pending_invalid_state
        """
        set_clock(api)
        territory = create_territory(api, name="Phoenix Metro", region_code="PHX-METRO")
        assert territory["posture"] == c.POSTURE_PENDING

        resp = api.validation_run(territory["id"], {"hours": 20}, headers=MAPPING)
        validate_error(resp, ERR_INVALID_STATE, 409)

        after = read_territory(api, territory["id"])
        assert after["posture"] == c.POSTURE_PENDING
        assert after["validation_hours"] == 0

    def test_first_mapping_tick_moves_pending_to_mapping(self, api):
        """A tick below the 95 gate accumulates coverage and opens MAPPING.

        PRD 3.1: "A tick is accepted only while the territory's `posture` is
        still `PENDING` and it is what moves the territory from `PENDING` to
        `MAPPING`; once coverage reaches 95 percent the territory advances on its
        own, without any further client action, from `MAPPING` to `VALIDATING`."
        PRD 3.1: "the territory's `mapped_pct` becomes the smaller of 100 and
        the current coverage plus that delta, so the accumulator saturates rather
        than overshooting."

        Design: Corner/state_machines/if_match_mapping_tick_moves_pending_to_mapping
        """
        set_clock(api)
        territory = create_territory(api, name="Phoenix Metro", region_code="PHX-METRO")
        updated = get_success_data(
            api.mapping_tick(territory["id"], {"mapped_pct_delta": 60}, headers=MAPPING)
        )
        assert updated["mapped_pct"] == 60
        assert updated["posture"] == c.POSTURE_MAPPING
        assert updated["version"] == 2

    def test_mapping_tick_saturates_coverage_at_one_hundred(self, api):
        """A large delta cannot push coverage past 100.

        PRD 3.1: "the territory's `mapped_pct` becomes the smaller of 100 and
        the current coverage plus that delta, so the accumulator saturates rather
        than overshooting."

        Design: Corner/state_machines/if_match_mapping_tick_moves_pending_to_mapping
        """
        set_clock(api)
        territory = create_territory(api, name="Phoenix Metro", region_code="PHX-METRO")
        updated = get_success_data(
            api.mapping_tick(territory["id"], {"mapped_pct_delta": 140}, headers=MAPPING)
        )
        assert updated["mapped_pct"] == 100
        assert updated["posture"] == c.POSTURE_VALIDATING

    def test_validation_hours_accumulate_while_validating(self, api):
        """Repeated runs in VALIDATING form a self-loop that keeps adding hours.

        PRD 3.1: "repeated runs while the territory remains in `VALIDATING` form
        a self-loop that simply keeps accumulating hours."
        PRD 3.1: "The territory reaches `ACTIVE` on its own once coverage is at
        95 percent or above and cumulative validation hours are at 100 or above."

        Design: Corner/state_machines/if_match_mapping_tick_moves_pending_to_mapping
        """
        set_clock(api)
        territory = create_territory(api, name="Phoenix Metro", region_code="PHX-METRO")
        get_success_data(
            api.mapping_tick(territory["id"], {"mapped_pct_delta": 95}, headers=MAPPING)
        )
        first = get_success_data(
            api.validation_run(territory["id"], {"hours": 40}, headers=MAPPING)
        )
        assert first["posture"] == c.POSTURE_VALIDATING
        assert first["validation_hours"] == 40

        second = get_success_data(
            api.validation_run(territory["id"], {"hours": 60}, headers=SAFETY)
        )
        assert second["validation_hours"] == 100
        assert second["posture"] == c.POSTURE_ACTIVE, (
            "coverage at 95 and hours at 100 reach ACTIVE without a further call"
        )


class TestTerritoryPostureGates:
    """The zone gates are evaluated before mapping and validation."""

    def test_two_active_zones_leave_the_territory_active(self, api):
        """Below three active zones the territory stays ACTIVE.

        PRD 2.7: "Five or more active zones puts the territory in `SUSPENDED`;
        three or four active zones puts it in `RESTRICTED`; only when fewer than
        three zones are active do mapping and validation figures come into play."

        Design: Corner/state_machines/if_match_zone_count_gate_at_three
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=100, validation_hours=120,
        )
        assert read_territory(api, territory["id"])["posture"] == c.POSTURE_ACTIVE

        activate_zones(api, territory["id"], 2)
        read = read_territory(api, territory["id"])
        assert read["active_zone_count"] == 2
        assert read["posture"] == c.POSTURE_ACTIVE

    def test_third_active_zone_moves_the_territory_to_restricted(self, api):
        """The third active zone is the gate that leaves ACTIVE.

        PRD 2.7: "The posture is decided by a strict evaluation order in which
        the zone gates always win. Five or more active zones puts the territory
        in `SUSPENDED`; three or four active zones puts it in `RESTRICTED`."

        Design: Corner/state_machines/if_match_zone_count_gate_at_three
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=100, validation_hours=120,
        )
        activate_zones(api, territory["id"], 3)
        read = read_territory(api, territory["id"])
        assert read["active_zone_count"] == 3
        assert read["posture"] == c.POSTURE_RESTRICTED

    def test_scheduled_zones_do_not_count_toward_posture(self, api):
        """A still-SCHEDULED zone is not part of active_zone_count at all.

        PRD 2.7: "The zone accumulator is `active_zone_count`, the number of
        that territory's exclusion zones currently in `ACTIVE` status — zones
        that are still `SCHEDULED` or have passed to `EXPIRED` are not counted
        at all."

        Design: Corner/state_machines/if_match_zone_count_gate_at_three
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=100, validation_hours=120,
        )
        create_exclusion_zone(api, territory["id"], route_class=c.ROUTE_FREEWAY)
        create_exclusion_zone(api, territory["id"], route_class=c.ROUTE_ARTERIAL)
        read = read_territory(api, territory["id"])
        assert read["active_zone_count"] == 0
        assert read["posture"] == c.POSTURE_ACTIVE

    def test_zone_override_beats_the_mapping_gate(self, api):
        """Three active zones read RESTRICTED even at 40 percent coverage.

        PRD 2.7: "Because the zone gates are evaluated first, a territory with
        three active zones reads `RESTRICTED` even if its mapping coverage has
        not yet reached 95 percent; the mapping-first reading, which would call
        it `MAPPING`, is wrong."

        Design: Corner/calculations/if_match_territory_posture_zone_override_beats_mapping
        """
        set_clock(api)
        territory = create_territory(
            api, name="Phoenix Metro", region_code="PHX-METRO",
            mapped_pct=40, validation_hours=0,
        )
        assert read_territory(api, territory["id"])["posture"] == c.POSTURE_MAPPING

        activate_zones(api, territory["id"], 3)
        read = read_territory(api, territory["id"])
        assert read["mapped_pct"] == 40
        assert read["active_zone_count"] == 3
        assert read["posture"] == c.POSTURE_RESTRICTED, (
            "the zone gate is evaluated first, so a barely-mapped territory reads RESTRICTED"
        )

    def test_mapping_gate_boundaries_are_inclusive(self, api):
        """Exactly 95 percent coverage with zero hours reads VALIDATING.

        PRD 2.7: "With `mapped_pct` at 95 or above and `validation_hours` at 100
        or above the territory is `ACTIVE`. With `mapped_pct` at 95 or above but
        fewer than 100 validation hours it is `VALIDATING`. With `mapped_pct`
        above zero but below 95 it is `MAPPING`. With no mapping progress at all
        it is `PENDING`."

        Design: Corner/calculations/if_match_territory_posture_zone_override_beats_mapping
        """
        set_clock(api)
        at_gate = create_territory(
            api, name="AtGate", region_code="GATE-1", mapped_pct=95, validation_hours=0
        )
        assert at_gate["posture"] == c.POSTURE_VALIDATING

        below_gate = create_territory(
            api, name="BelowGate", region_code="GATE-2", mapped_pct=94, validation_hours=0
        )
        assert below_gate["posture"] == c.POSTURE_MAPPING

        zero = create_territory(
            api, name="Zero", region_code="GATE-3", mapped_pct=0, validation_hours=0
        )
        assert zero["posture"] == c.POSTURE_PENDING


class TestTerritoryNotFound:
    """An unknown identifier reports ERR_NOT_FOUND, never an empty object."""

    def test_unknown_depot_id_returns_not_found(self, api):
        """A GET against an unknown depot id answers 404 in the error envelope.

        PRD 3.7: "Resource existence comes third, validated strictly left to
        right along the path as section 2.11 describes, so a request naming a
        nonexistent outer resource reports `ERR_NOT_FOUND` (HTTP 404) even if a
        later path segment would also have failed."

        Design: Corner/entities/if_match_depot_site_not_found_returns_404
        """
        set_clock(api)
        create_territory(api, name="Phoenix Metro", region_code="PHX-METRO")
        resp = api.get_depot("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers=FLEET)
        validate_error(resp, ERR_NOT_FOUND, 404)
        assert resp.json()["response_type"] == "error"

    def test_unknown_territory_id_returns_not_found(self, api):
        """The territory is resolved before anything nested inside it.

        PRD 2.11: "The first identifier in the path that does not correspond to
        an existing resource determines the response: the request fails with
        `ERR_NOT_FOUND` (HTTP 404), and no later identifier in the path is
        examined."

        Design: Corner/entities/if_match_depot_site_not_found_returns_404
        """
        set_clock(api)
        resp = api.get_depot("11111111-2222-4333-8444-555555555555", headers=FLEET)
        validate_error(resp, ERR_NOT_FOUND, 404)