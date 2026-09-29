"""The authorisation ladder: identity, role membership, values, ownership and duties.

Covers PRD sections 2.1 and 2.8 rungs 1, 2, 6, 7, 8 and 18: the two identity
headers, endpoint role membership, value-level gates on endpoints a role may
call, officer-backed ownership and its single release carve-out, segregation of
duties on two independent chains, the supervisor certification that reads the
Officer row rather than the header, and the operations peer roles share.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    DUTY_MANAGER_AS_PLANNER_HEADERS,
    DUTY_MANAGER_HEADERS,
    DUTY_MANAGER_USER_ID,
    MANAGER_HEADERS,
    NON_EXISTENT_UUID,
    PLANNER_HEADERS,
    PLANNER_USER_ID,
    ApiErrorId,
    assert_instant,
    assert_lane_snapshot,
    assert_officer_ledger,
    assert_posture,
    assert_secondary_slots,
    factories as f,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_screening_officer_headers,
    make_supervisory_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    BAND_1100,
    BAND_1130,
    CLOCK_0800,
    OPERATIONAL_DATE,
    Scenario,
)


def _checkpoint(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
    )


def _resolver_headers(scenario: Scenario) -> dict:
    """The nominated line officer's own identity headers."""
    return make_screening_officer_headers(scenario.resolver["id"])


def _referral_in_progress(open_lane_floor: Scenario) -> Scenario:
    """A RANDOM referral raised by the supervisor and begun on a second officer."""
    scenario = open_lane_floor.build_supervisor(on_duty=True).build_resolver()
    referral = scenario.raise_referral(
        headers=scenario.supervisor_headers,
        referral_reason="RANDOM",
        passenger_category="ADULT",
        requires_private_screening=False,
    )
    begun = validate_success(
        scenario.api.begin_screening_referral(
            referral["id"],
            f.referral_begin_payload(scenario.resolver["id"]),
            scenario.supervisor_headers,
        )
    )
    assert begun["state"] == "IN_PROGRESS"
    assert begun["detecting_officer_id"] == scenario.supervisor_id
    assert begun["resolving_officer_id"] == scenario.resolver["id"]
    scenario.extras["referral"] = begun
    return scenario


class TestIdentityHeaders:
    """PRD 2.1 - both headers must be present and non-blank, and rung 1 outranks all."""

    def test_an_absent_or_blank_identity_header_is_unauthenticated_before_anything_else(
        self, base: Scenario
    ):
        """Four degenerate header pairs all reach the same code, and 401 beats 404.

        Design: Corner/rbac/missing_or_whitespace_only_identity_headers_are_unauthenticated
        """
        # PRD 2.1 declares a whitespace-only value equivalent to an absent one.
        # An HTTP client cannot transmit a value that is only spaces, so the
        # empty string is the wire-representable form of the same condition and
        # is what the PRD names first: "absent, empty, or consists only of
        # whitespace".
        degenerate = (
            ("no role header at all", headers_without_role(ADMIN_USER_ID)),
            ("no user-id header at all", headers_without_user_id()),
            ("a blank role header", headers_with_empty_role(ADMIN_USER_ID)),
            ("a blank user-id header", headers_with_empty_user_id()),
        )
        for label, headers in degenerate:
            error = validate_error(
                base.api.get_checkpoint(base.checkpoint_id, headers),
                ApiErrorId.UNAUTHENTICATED,
                401,
            )
            assert error["message"].strip(), f"{label} produced an empty message"

        outranked = validate_error(
            base.api.get_checkpoint(NON_EXISTENT_UUID, headers_without_role(ADMIN_USER_ID)),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        assert outranked["error_id"] != ApiErrorId.CHECKPOINT_NOT_FOUND, (
            "rung 1 is evaluated before the rung 4 path-identifier lookup"
        )

        allowed = validate_success(base.api.get_checkpoint(base.checkpoint_id, ADMIN_HEADERS))
        assert allowed["id"] == base.checkpoint_id


class TestEndpointRoleMembership:
    """PRD 2.1 - rung 2 covers both an undeclared role and a non-listed one."""

    def test_a_role_the_endpoint_never_lists_is_refused_before_the_body_is_read(
        self, base: Scenario
    ):
        """An unauthorised role sending a body missing seven fields still gets 403.

        Design: Corner/rbac/roles_not_listed_on_the_endpoint_are_forbidden_before_the_body_is_read
        """
        officer_headers = make_screening_officer_headers("someone")
        version = base.checkpoint_version()

        validate_error(
            base.api.create_checkpoint(
                f.checkpoint_payload(
                    name="T9",
                    terminal_code="T9",
                    total_lane_positions=2,
                    secondary_slot_capacity=1,
                ),
                officer_headers,
            ),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )

        validate_error(
            base.api.get_checkpoint(base.checkpoint_id, headers_with_unknown_role()),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )

        # Every declared role may read a checkpoint, yet PlatformAdmin sits
        # deliberately outside the plan chain: this role model has no
        # hierarchical override.
        validate_error(
            base.api.create_staffing_plan(
                f.staffing_plan_payload(base.checkpoint_id, OPERATIONAL_DATE, version),
                ADMIN_HEADERS,
            ),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )

        malformed = validate_error(
            base.api.create_checkpoint({"name": "T9"}, officer_headers),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )
        assert malformed["error_id"] != ApiErrorId.INVALID_REQUEST, (
            "rung 2 precedes the rung 3 shape check, so the body was never inspected"
        )

        rows, _meta = validate_paginated(
            base.api.list_staffing_plans(PLANNER_HEADERS, {"checkpoint_id": base.checkpoint_id})
        )
        assert rows == [], "no plan survived the refusal"
        assert base.checkpoint_version() == version, "no refused call mutated the checkpoint"


class TestValueLevelRoleGates:
    """PRD 2.1 rung 6 - the role passes the endpoint check and fails on the value."""

    def test_the_same_role_and_endpoint_succeed_on_a_permitted_value(
        self, open_lane_floor: Scenario
    ):
        """Three refusals on forbidden values, then the identical calls on allowed ones.

        Design: Corner/rbac/action_values_are_gated_per_role_on_endpoints_the_role_may_call
        """
        scenario = _referral_in_progress(open_lane_floor)
        referral = scenario.extras["referral"]

        # PlatformAdmin may patch a checkpoint, but suspended is CheckpointManager-only.
        validate_error(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id, f.checkpoint_patch_payload(suspended=True), ADMIN_HEADERS
            ),
            ApiErrorId.FORBIDDEN_ACTION_FOR_ROLE,
            403,
        )

        # CheckpointManager may patch a checkpoint, but the cost cap is PlatformAdmin-only.
        validate_error(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id,
                f.checkpoint_patch_payload(plan_cost_cap_cents=5000),
                MANAGER_HEADERS,
            ),
            ApiErrorId.FORBIDDEN_ACTION_FOR_ROLE,
            403,
        )

        # A ScreeningOfficer may resolve the referral they were nominated to work,
        # but only with the cleared outcome.
        validate_error(
            scenario.api.resolve_screening_referral(
                referral["id"],
                f.referral_resolution_payload(
                    "REFERRED_LEO", resolution_note="line officer overreach"
                ),
                _resolver_headers(scenario),
            ),
            ApiErrorId.FORBIDDEN_ACTION_FOR_ROLE,
            403,
        )

        patched = validate_success(
            scenario.api.update_checkpoint(
                scenario.checkpoint_id,
                f.checkpoint_patch_payload(wait_threshold_minutes_standard=14),
                ADMIN_HEADERS,
            )
        )
        assert patched["wait_threshold_minutes_standard"] == 14, (
            "the gate is per value, not per role: the same role and endpoint succeed"
        )

        cleared = validate_success(
            scenario.api.resolve_screening_referral(
                referral["id"],
                f.referral_resolution_payload("CLEARED"),
                _resolver_headers(scenario),
            )
        )
        assert cleared["state"] == "CLEARED"
        assert cleared["secondary_slot_held"] is False

        final = _checkpoint(scenario)
        assert final["suspended"] is False, "the refused patch never took effect"
        assert_posture(final, "NORMAL")
        assert_secondary_slots(final, in_use=0)


class TestAssignmentOwnership:
    """PRD 2.1 rung 7 - officer-backed identity owns its own row, release excepted."""

    def test_only_the_named_officer_may_check_in_and_only_release_is_carved_out(
        self, activated_plan: Scenario
    ):
        """A foreign officer and the supervisor are both refused the check-in.

        Design: Corner/rbac/entity_backed_actors_own_their_assignment_except_supervisor_release
        """
        scenario = activated_plan.build_supervisor(on_duty=True)
        other = scenario.create_officer(
            badge_number="B-4002",
            full_name="Ola Other",
            certifications=["STANDARD_LANE", "ADVANCED_IMAGING"],
        )
        other_headers = make_screening_officer_headers(other["id"])

        validate_error(
            scenario.api.assignment_duty(
                scenario.assignment_id, f.duty_action_payload("CHECK_IN"), other_headers
            ),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )
        validate_error(
            scenario.api.assignment_duty(
                scenario.assignment_id,
                f.duty_action_payload("CHECK_IN"),
                scenario.supervisor_headers,
            ),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )

        checked_in = validate_success(
            scenario.api.assignment_duty(
                scenario.assignment_id,
                f.duty_action_payload("CHECK_IN"),
                scenario.officer_headers,
            )
        )
        assert checked_in["assignment_state"] == "CHECKED_IN"
        assert_instant(checked_in["break_baseline_utc"], CLOCK_0800, "break_baseline_utc")

        # Ownership is rung 7 and the break-due gate is rung 14, so the foreign
        # officer never reaches the reason their break would have been refused for.
        foreign_break = validate_error(
            scenario.api.assignment_break(
                scenario.assignment_id, f.break_action_payload("START"), other_headers
            ),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )
        assert foreign_break["error_id"] != ApiErrorId.BREAK_NOT_DUE

        released = validate_success(
            scenario.api.assignment_duty(
                scenario.assignment_id,
                f.duty_action_payload("RELEASE"),
                scenario.supervisor_headers,
            )
        )
        assert released["assignment_state"] == "RELEASED", (
            "the one carve-out: a SupervisoryOfficer releases a row on their own checkpoint"
        )
        assert released["actual_minutes"] == 0, "checked in and released at the same instant"

        assert_officer_ledger(
            validate_success(scenario.api.get_officer(scenario.officer_id, MANAGER_HEADERS)),
            committed_duty_minutes=0,
        )


class TestSegregationOfDuties:
    """PRD 2.1 rung 8 - the rule compares identifiers on two independent chains."""

    def test_the_preparer_and_the_detector_are_both_refused_their_own_second_signature(
        self, submitted_plan: Scenario
    ):
        """One rule, two stored user ids: prepared_by_user_id and detecting_officer_id.

        Design: Corner/rbac/segregation_of_duties_blocks_self_approval_on_both_chains
        """
        scenario = _referral_in_progress(submitted_plan)
        referral = scenario.extras["referral"]
        assert scenario.plan["prepared_by_user_id"] == PLANNER_USER_ID

        # The role is right and only the identity is wrong.
        validate_error(
            scenario.api.decide_staffing_plan(
                scenario.plan_id,
                f.plan_decision_payload("APPROVE"),
                DUTY_MANAGER_AS_PLANNER_HEADERS,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )

        untouched = validate_success(
            scenario.api.get_staffing_plan(scenario.plan_id, DUTY_MANAGER_HEADERS)
        )
        assert untouched["state"] == "SUBMITTED"
        assert untouched["approved_by_user_id"] is None
        assert untouched["approved_at_utc"] is None

        # CLEARED is an outcome a SupervisoryOfficer may always send, so nothing
        # but the detect-versus-resolve comparison can refuse this call.
        validate_error(
            scenario.api.resolve_screening_referral(
                referral["id"],
                f.referral_resolution_payload("CLEARED"),
                scenario.supervisor_headers,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )

        approved = validate_success(
            scenario.api.decide_staffing_plan(
                scenario.plan_id, f.plan_decision_payload("APPROVE"), DUTY_MANAGER_HEADERS
            )
        )
        assert approved["state"] == "APPROVED"
        assert approved["approved_by_user_id"] == DUTY_MANAGER_USER_ID

        cleared = validate_success(
            scenario.api.resolve_screening_referral(
                referral["id"],
                f.referral_resolution_payload("CLEARED"),
                _resolver_headers(scenario),
            )
        )
        assert cleared["state"] == "CLEARED", "the other officer carries the resolution"
        assert cleared["resolving_officer_id"] == scenario.resolver["id"]


def _uncertified_supervisor_floor(closed_lane_floor: Scenario) -> Scenario:
    """One on-duty officer holding SUPERVISOR and one on-duty officer without it."""
    scenario = closed_lane_floor.build_supervisor(on_duty=True)
    nosup = scenario.create_officer(
        badge_number="B-3001",
        full_name="Noa Nosup",
        certifications=["STANDARD_LANE", "SPECIAL_PROCEDURES", "ETD_RESOLUTION"],
    )
    scenario.extras["nosup"] = scenario.set_duty_status(nosup["id"], "ON_DUTY")
    assert scenario.extras["nosup"]["duty_status"] == "ON_DUTY"
    assert "SUPERVISOR" not in scenario.extras["nosup"]["certifications"]
    return scenario


class TestSupervisorCertificationGate:
    """PRD 2.1 rung 18 - the gate reads the Officer row, not the header role."""

    def test_the_certification_gates_the_open_and_the_begin_but_never_the_manager(
        self, closed_lane_floor: Scenario
    ):
        """The same open on the same lane succeeds for the opaque CheckpointManager.

        Design: Corner/rbac/supervisor_certification_gates_lane_open_and_private_screening
        """
        scenario = _uncertified_supervisor_floor(closed_lane_floor)
        nosup = scenario.extras["nosup"]
        nosup_headers = make_supervisory_officer_headers(nosup["id"])

        validate_error(
            scenario.api.open_lane(scenario.lane_id, nosup_headers),
            ApiErrorId.SUPERVISOR_CERTIFICATION_REQUIRED,
            403,
        )

        opened = validate_success(scenario.api.open_lane(scenario.lane_id, MANAGER_HEADERS))
        assert_lane_snapshot(opened, lane_state="OPEN", equipment_state="SERVICEABLE")

        # Creation is not gated by the certification: only the begin is.
        referral = validate_success(
            scenario.api.create_screening_referral(
                f.referral_payload(
                    scenario.lane_id,
                    referral_reason="MEDICAL_DEVICE",
                    passenger_category="MEDICAL_DEVICE_WEARER",
                    requires_private_screening=True,
                ),
                nosup_headers,
            ),
            201,
        )
        assert referral["requires_private_screening"] is True
        assert referral["detecting_officer_id"] == nosup["id"]

        # The nominee is the SUPERVISOR-holding officer, who also holds the
        # SPECIAL_PROCEDURES that a MEDICAL_DEVICE referral demands, so the rung
        # 15 certification check on the nominee passes and only the rung 18 check
        # on the actor can refuse this call.
        refused = validate_error(
            scenario.api.begin_screening_referral(
                referral["id"],
                f.referral_begin_payload(scenario.supervisor_id),
                nosup_headers,
            ),
            ApiErrorId.SUPERVISOR_CERTIFICATION_REQUIRED,
            403,
        )
        assert refused["error_id"] != ApiErrorId.OFFICER_NOT_CERTIFIED

        begun = validate_success(
            scenario.api.begin_screening_referral(
                referral["id"],
                f.referral_begin_payload(scenario.supervisor_id),
                scenario.supervisor_headers,
            )
        )
        assert begun["state"] == "IN_PROGRESS"

        denied = validate_success(
            scenario.api.resolve_screening_referral(
                referral["id"],
                f.referral_resolution_payload("DENIED_ENTRY", resolution_note="no valid ID"),
                scenario.supervisor_headers,
            )
        )
        assert denied["state"] == "DENIED_ENTRY", (
            "detecting and resolving officers differ, so segregation of duties holds"
        )


class TestSharedOperations:
    """PRD 2.1 - peer roles that declare an operation must not be collapsed into one."""

    def test_every_declared_role_reaches_the_operation_it_is_listed_on(
        self, activated_plan: Scenario
    ):
        """Three roles publish into one window, two create bands, one drives another's duty.

        Design: Corner/rbac/shared_operations_work_for_every_role_that_declares_them
        """
        scenario = activated_plan.build_supervisor(on_duty=True)

        posters = (
            (MANAGER_HEADERS, "BLE_SENSOR"),
            (DUTY_MANAGER_HEADERS, "MANUAL_TIMESTAMP"),
            (scenario.supervisor_headers, "STAFF_ESTIMATE"),
        )
        for headers, measurement_method in posters:
            observation = scenario.post_observation(
                headers=headers,
                lane_type="STANDARD",
                sampled_wait_seconds=300,
                measurement_method=measurement_method,
                sample_size=10,
            )
            # Identical 300-second samples publish 5 minutes whichever peer role
            # posted them, and 5 is below the 15-minute standard threshold.
            assert observation["published_wait_minutes_snapshot"] == 5, measurement_method
            assert observation["breached_threshold"] is False

        band_ids = []
        for band_start_utc, headers in ((BAND_1100, ADMIN_HEADERS), (BAND_1130, PLANNER_HEADERS)):
            created = validate_success(
                scenario.api.create_time_band(
                    f.time_band_payload(scenario.checkpoint_id, band_start_utc), headers
                ),
                201,
            )
            band_ids.append(created["id"])
        assert len(set(band_ids)) == 2, "POST /time-bands is shared by two roles"

        # A DutyManager acts on behalf of the officer, so the ownership
        # comparison that binds officer-backed roles does not apply to it.
        checked_in = validate_success(
            scenario.api.assignment_duty(
                scenario.assignment_id, f.duty_action_payload("CHECK_IN"), DUTY_MANAGER_HEADERS
            )
        )
        assert checked_in["assignment_state"] == "CHECKED_IN"

        paused = validate_success(
            scenario.api.stand_down_lane(
                scenario.lane_id,
                f.stand_down_payload("PAUSED", paused_reason_code="LOW_DEMAND"),
                scenario.supervisor_headers,
            )
        )
        assert_lane_snapshot(
            paused,
            lane_state="PAUSED",
            equipment_state="SERVICEABLE",
            paused_reason_code="LOW_DEMAND",
        )

        flipped = validate_success(
            scenario.api.get_lane_assignment(scenario.assignment_id, PLANNER_HEADERS)
        )
        assert flipped["assignment_state"] == "REASSIGN_PENDING"
