"""Uniqueness scopes, curve tiling, the suspension gate and secondary capacity.

Covers PRD sections 2.8, 3.1, 3.2, 3.8 and 3.9: the three uniqueness codes and
their scopes, the histogram that must tile its window, the coarse suspension
gate that outranks transition legality, the aggregate secondary-slot rule, and
the three ways an escalation's resolution lane can be wrong.
"""

from test_helpers import (
    ADMIN_HEADERS,
    MANAGER_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_lane_snapshot,
    assert_posture,
    assert_referral_counters,
    assert_secondary_slots,
    factories as f,
    make_screening_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BAND_1000, CLOCK_0800, Scenario

GAPPED_BUCKETS = [f.curve_bucket(60, 45, 50), f.curve_bucket(30, 0, 50)]
OVERLAPPING_BUCKETS = [f.curve_bucket(60, 20, 50), f.curve_bucket(30, 0, 50)]
SHORT_SHARE_BUCKETS = [f.curve_bucket(60, 30, 49), f.curve_bucket(30, 0, 50)]
TILING_BUCKETS = [f.curve_bucket(60, 30, 40), f.curve_bucket(30, 0, 60)]


class TestUniquenessScopes:
    """PRD 2.8 - two constraints are per checkpoint and the third is global."""

    def test_position_index_and_band_start_are_scoped_per_checkpoint(
        self, base: Scenario
    ):
        """A badge number collides everywhere; a position or a band start only locally.

        Design: Corner/validations/uniqueness_rules_reject_duplicate_position_band_start_and_badge
        """
        scenario = base
        scenario.lane = scenario.create_lane()
        scenario.create_band(BAND_1000)
        scenario.build_officer()

        validate_error(
            scenario.api.create_lane(
                f.lane_payload(
                    scenario.checkpoint_id,
                    lane_type="EXPEDITED",
                    position_index=1,
                    max_concurrent_officers=1,
                    secondary_positions=0,
                ),
                MANAGER_HEADERS,
            ),
            ApiErrorId.DUPLICATE_LANE_POSITION,
            409,
        )
        validate_error(
            scenario.api.create_time_band(
                f.time_band_payload(scenario.checkpoint_id, BAND_1000, expedited_share_pct=50),
                PLANNER_HEADERS,
            ),
            ApiErrorId.DUPLICATE_TIME_BAND,
            409,
        )
        validate_error(
            scenario.api.create_officer(
                f.officer_payload(
                    badge_number="B-1001",
                    full_name="Ada Clone",
                    certifications=["STANDARD_LANE"],
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.DUPLICATE_BADGE_NUMBER,
            409,
        )

        other = scenario.create_checkpoint(
            name="T2 West", terminal_code="T2", total_lane_positions=4, secondary_slot_capacity=1
        )
        scoped_lane = validate_success(
            scenario.api.create_lane(
                f.lane_payload(
                    other["id"],
                    position_index=1,
                    max_concurrent_officers=1,
                    secondary_positions=0,
                ),
                MANAGER_HEADERS,
            ),
            201,
        )
        assert scoped_lane["position_index"] == 1
        validate_success(
            scenario.api.create_time_band(
                f.time_band_payload(other["id"], BAND_1000), PLANNER_HEADERS
            ),
            201,
        )

        rows, _meta = validate_paginated(
            scenario.api.list_lanes(
                MANAGER_HEADERS, {"checkpoint_id": scenario.checkpoint_id}
            )
        )
        assert len(rows) == 1, "the rejected create left no row behind"


class TestCurveBucketsMustTileTheWindow:
    """PRD 3.2 - the histogram is the forecast's denominator, so it must be exact."""

    def test_gaps_overlaps_and_short_shares_are_all_the_same_rejection(
        self, scenario: Scenario
    ):
        """Adjacent buckets meeting at one point are a tiling, not an overlap.

        Design: Corner/validations/show_up_curve_buckets_must_tile_the_window_and_sum_to_one_hundred
        """
        scenario.set_clock(CLOCK_0800)

        for name, buckets in (
            ("Gapped", GAPPED_BUCKETS),
            ("Overlapping", OVERLAPPING_BUCKETS),
            ("Short shares", SHORT_SHARE_BUCKETS),
        ):
            validate_error(
                scenario.api.create_show_up_curve(
                    f.show_up_curve_payload(
                        name=name,
                        window_start_minutes_before=60,
                        window_end_minutes_before=0,
                        buckets=buckets,
                    ),
                    ADMIN_HEADERS,
                ),
                ApiErrorId.CURVE_BUCKETS_INVALID,
                422,
            )

        created = validate_success(
            scenario.api.create_show_up_curve(
                f.show_up_curve_payload(
                    name="Valid two bucket",
                    carrier_type="INTERNATIONAL",
                    window_start_minutes_before=60,
                    window_end_minutes_before=0,
                    buckets=TILING_BUCKETS,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert created["name"] == "Valid two bucket"

        reread = validate_success(
            scenario.api.get_show_up_curve(created["id"], ADMIN_HEADERS)
        )
        assert [bucket["minutes_before_start"] for bucket in reread["buckets"]] == [60, 30], (
            "the buckets are returned in the order they were supplied"
        )
        assert len(reread["buckets"]) == 2


class TestSuspensionGateOutranksTransitionLegality:
    """PRD 2.8 rung 10 - a coarse posture gate above the state machine at rung 11."""

    def test_operational_writes_are_refused_while_reads_and_the_patch_stay_open(
        self, plan_with_assignment: Scenario
    ):
        """Re-opening the lane the suspension paused reports the posture, not the edge.

        Design: Corner/validations/suspended_checkpoint_blocks_operational_writes_but_not_reads_or_patch
        """
        scenario = plan_with_assignment
        scenario.build_supervisor(on_duty=True)

        suspended = validate_success(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id,
                f.checkpoint_patch_payload(suspended=True),
                MANAGER_HEADERS,
            )
        )
        assert_posture(suspended, "SUSPENDED")
        paused = validate_success(scenario.api.get_lane(scenario.lane_id, MANAGER_HEADERS))
        assert_lane_snapshot(
            paused,
            lane_state="PAUSED",
            equipment_state="SERVICEABLE",
            paused_reason_code="SECURITY_INCIDENT",
        )

        # PAUSED -> OPEN is a declared edge, so only the coarser gate can refuse it.
        validate_error(
            scenario.api.open_lane(scenario.lane_id, MANAGER_HEADERS),
            ApiErrorId.CHECKPOINT_SUSPENDED,
            409,
        )
        validate_error(
            scenario.api.create_wait_observation(
                scenario.checkpoint_id,
                f.wait_observation_payload(),
                scenario.supervisor_headers,
            ),
            ApiErrorId.CHECKPOINT_SUSPENDED,
            409,
        )
        validate_error(
            scenario.api.create_screening_referral(
                f.referral_payload(scenario.lane_id), scenario.supervisor_headers
            ),
            ApiErrorId.CHECKPOINT_SUSPENDED,
            409,
        )
        validate_error(
            scenario.api.submit_staffing_plan(scenario.plan_id, PLANNER_HEADERS),
            ApiErrorId.CHECKPOINT_SUSPENDED,
            409,
        )

        published = validate_success(
            scenario.api.get_published_wait_time(
                scenario.checkpoint_id, MANAGER_HEADERS, {"lane_type": "STANDARD"}
            )
        )
        assert published["sample_count"] == 0, "reads are never gated by the posture"

        lowered = validate_success(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id,
                f.checkpoint_patch_payload(suspended=False),
                MANAGER_HEADERS,
            )
        )
        assert lowered["suspended"] is False
        assert_posture(lowered, "NORMAL")

        reopened = validate_success(scenario.api.open_lane(scenario.lane_id, MANAGER_HEADERS))
        assert reopened["lane_state"] == "OPEN", (
            "the identical call now succeeds, so the refusal was the posture gate alone"
        )


def _begin(scenario: Scenario, referral_id: str):
    return scenario.api.begin_screening_referral(
        referral_id,
        f.referral_begin_payload(scenario.resolver["id"]),
        scenario.supervisor_headers,
    )


class TestSecondarySlotCapacityIsAnAggregateRule:
    """PRD 3.9 - the slot is reserved at creation and the begin excludes its own."""

    def test_a_third_begin_is_refused_until_a_slot_is_released(
        self, supervised_floor: Scenario
    ):
        """Each begin counts only the OTHER held slots, so a capacity of 2 admits two.

        Design: Corner/validations/referral_begin_rejected_when_other_secondary_slots_fill_the_capacity
        """
        scenario = supervised_floor.build_resolver(on_duty=True)
        assert scenario.resolver["duty_status"] == "ON_DUTY"

        # Two raised referrals exactly fill the capacity of 2.
        referrals = [scenario.raise_referral() for _ in range(2)]
        checkpoint = validate_success(
            scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
        )
        # The slot is taken the instant the referral is raised, not when work begins.
        assert_secondary_slots(checkpoint, in_use=2)

        # Each begin counts only the OTHER held slots, so with two live referrals
        # the count is 1 - strictly below the capacity - and both are admitted.
        for referral in referrals:
            begun = validate_success(_begin(scenario, referral["id"]))
            assert begun["state"] == "IN_PROGRESS"
            assert begun["secondary_slot_held"] is True

        # A third referral takes the other-held count to 2, which is no longer
        # strictly below the capacity, so its begin is refused.
        referrals.append(scenario.raise_referral())
        filled = validate_success(
            scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
        )
        assert_secondary_slots(filled, in_use=3)

        validate_error(
            _begin(scenario, referrals[2]["id"]),
            ApiErrorId.SECONDARY_CAPACITY_EXHAUSTED,
            409,
        )

        # The nominated resolver clears their own referral: a ScreeningOfficer may
        # clear the referral they were nominated to work, and they differ from the
        # supervisor who raised it, so segregation of duties is satisfied.
        cleared = validate_success(
            scenario.api.resolve_screening_referral(
                referrals[0]["id"],
                f.referral_resolution_payload("CLEARED"),
                make_screening_officer_headers(scenario.resolver["id"]),
            )
        )
        assert cleared["state"] == "CLEARED"
        assert cleared["secondary_slot_held"] is False
        after_release = validate_success(
            scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
        )
        assert_secondary_slots(after_release, in_use=2)
        assert_referral_counters(after_release, cleared_referral_count=1)

        retried = validate_success(_begin(scenario, referrals[2]["id"]))
        assert retried["state"] == "IN_PROGRESS", (
            "the rule reads live aggregate state, not a per-referral flag"
        )


def _resolve_with_lane(scenario: Scenario, ticket_id: str, lane_id: str):
    return scenario.api.resolve_escalation_ticket(
        ticket_id,
        f.ticket_resolution_payload("LANE_OPENED", resolved_lane_id=lane_id),
        scenario.supervisor_headers,
    )


class TestResolutionLaneMustMatchTheTicketScope:
    """PRD 3.8 rung 20 - three different faults collapse into one error code."""

    def test_a_foreign_a_mismatched_and_a_paused_lane_are_all_invalid(
        self, acknowledged_ticket: Scenario
    ):
        """Every one of the three tests reads the TICKET's scope, not the lane alone.

        Design: Corner/validations/escalation_resolution_lane_must_match_scope_and_be_open
        """
        scenario = acknowledged_ticket
        ticket = scenario.extras["ticket"]
        assert ticket["lane_type_scope"] == "STANDARD"
        assert ticket["state"] == "ACKNOWLEDGED"

        expedited = scenario.create_lane(
            lane_type="EXPEDITED", position_index=4, max_concurrent_officers=1, secondary_positions=0
        )
        scenario.install_required_equipment(
            expedited["id"], lane_type="EXPEDITED", serial_prefix="E4"
        )
        opened_expedited = scenario.open_lane(expedited["id"])
        assert opened_expedited["lane_state"] == "OPEN", (
            "an EXPEDITED lane needs only WTMD and AT_XRAY"
        )

        other_checkpoint = scenario.create_checkpoint(
            name="T2 West", terminal_code="T2", total_lane_positions=4, secondary_slot_capacity=1
        )
        foreign_lane = scenario.create_lane(
            checkpoint_id=other_checkpoint["id"], secondary_positions=0
        )

        validate_error(
            _resolve_with_lane(scenario, ticket["id"], foreign_lane["id"]),
            ApiErrorId.RESOLUTION_LANE_INVALID,
            422,
        )
        validate_error(
            _resolve_with_lane(scenario, ticket["id"], expedited["id"]),
            ApiErrorId.RESOLUTION_LANE_INVALID,
            422,
        )

        paused = validate_success(
            scenario.api.stand_down_lane(
                scenario.lane_id,
                f.stand_down_payload("PAUSED", paused_reason_code="LOW_DEMAND"),
                MANAGER_HEADERS,
            )
        )
        assert paused["lane_state"] == "PAUSED"
        validate_error(
            _resolve_with_lane(scenario, ticket["id"], scenario.lane_id),
            ApiErrorId.RESOLUTION_LANE_INVALID,
            422,
        )

        reopened = scenario.open_lane(scenario.lane_id)
        assert reopened["lane_state"] == "OPEN"
        resolved = validate_success(
            _resolve_with_lane(scenario, ticket["id"], scenario.lane_id)
        )
        assert resolved["state"] == "RESOLVED_LANE_OPENED"
        assert resolved["resolved_lane_id"] == scenario.lane_id

        checkpoint = validate_success(
            scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
        )
        assert_referral_counters(checkpoint, diverted_pax_total=0)
