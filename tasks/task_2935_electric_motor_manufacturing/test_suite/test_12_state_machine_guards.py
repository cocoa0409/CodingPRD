"""Initial states, out-of-set triggers, terminal lockdowns and side-effect chains."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_DESIGN_STATE,
    ERR_INVALID_NAMEPLATE_STATE,
    ERR_INVALID_ORDER_STATE,
    ERR_INVALID_PERFORMANCE_TEST_STATE,
    ERR_INVALID_SUBASSEMBLY_STATE,
    ERR_INVALID_WORK_ORDER_STATE,
)
from test_helpers.fixtures import Plant, build_plant

SECOND_REVOKE_CLOCK = F.instant("2026-08-06", 14, 0)
CLAIM_CLOCK = F.instant("2027-02-05", 9, 30)
BENIGN_APPLICATION = {
    "measured_load_pct": 118.0,
    "measured_ambient_c": 51.3,
    "measured_voltage_unbalance_pct": 2.5,
    "measured_starts_per_hour": 9,
}


def test_five_machines_entered_in_one_chain_land_on_their_own_initial_states(api):
    """The work order alone initialises two dimensions at once.

    PRD 3.5: "On success the row starts with `build_status` at `RELEASED`,
    `certification_status` at `PENDING`, `design_pin_stale` false and
    `rework_reject_count` at 0, and it captures `pinned_design_revision_index`
    from the design's current `revision_index`."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    plant = Plant(api)
    plant.add_reference_data()

    design = plant.add_design()
    assert design["status"] == "DRAFT"
    assert design["revision_index"] == 0
    assert design["review_round"] == 0
    plant.release_design()
    order = plant.add_order()
    assert order["status"] == "DRAFT"
    plant.confirm_order()

    work_order = plant.add_work_order()
    stator = plant.add_stator()
    rotor = plant.add_rotor()

    assert work_order["build_status"] == "RELEASED"
    assert work_order["certification_status"] == "PENDING"
    assert work_order["design_pin_stale"] is False
    assert work_order["rework_reject_count"] == 0
    assert work_order["pinned_design_revision_index"] == 0
    assert stator["status"] == "WOUND"
    assert stator["winder_user_id"] == U.USER_BUILD_TECHNICIAN
    assert rotor["status"] == "PLANNED"
    assert rotor["rotor_tech_user_id"] == U.USER_BUILD_TECHNICIAN
    assert rotor["construction"] == "DIE_CAST_ALUMINUM"
    assert plant.get_order()["status"] == "IN_PRODUCTION"


def test_four_design_triggers_outside_their_from_set_leave_the_row_untouched(api):
    """Two refusals from DRAFT, one from IN_REVIEW and one from RELEASED.

    PRD 3.3: "**Submitting for review** advances the design `DRAFT → IN_REVIEW`,
    or `REVISION_OPEN → IN_REVIEW` when the engineer is closing out a reopened
    revision."

    Design: Corner/state_machines/design_transitions_outside_the_declared_from_set_are_rejected
    """
    plant = Plant(api)
    design = plant.add_design()

    validate_error(
        api.record_review_decision(
            design["id"], F.review_decision_payload("APPROVE"), U.DESIGN_REVIEWER
        ),
        ERR_INVALID_DESIGN_STATE,
        409,
    )
    validate_error(
        api.open_design_revision(
            design["id"], F.open_revision_payload(), U.DESIGN_ENGINEER
        ),
        ERR_INVALID_DESIGN_STATE,
        409,
    )
    in_review = plant.submit_design()
    validate_error(
        api.submit_design_review(
            design["id"], F.submit_review_payload(), U.DESIGN_ENGINEER
        ),
        ERR_INVALID_DESIGN_STATE,
        409,
    )
    released = plant.decide_design("APPROVE")
    validate_error(
        api.submit_design_review(
            design["id"], F.submit_review_payload(), U.DESIGN_ENGINEER
        ),
        ERR_INVALID_DESIGN_STATE,
        409,
    )

    assert in_review["status"] == "IN_REVIEW"
    assert released["status"] == "RELEASED"
    stored = plant.get_design()
    assert stored["version"] == 3
    assert stored["status"] == "RELEASED"
    assert stored["review_round"] == 1
    assert stored["revision_index"] == 0


def test_an_obsolete_design_refuses_all_three_of_its_endpoints(api):
    """The one terminal design state is reached from IN_REVIEW and locks down.

    PRD 3.3: "`OBSOLETE` moves the design `IN_REVIEW → OBSOLETE`, which is
    terminal."

    Design: Corner/state_machines/obsolete_design_is_terminal_and_refuses_every_declared_trigger
    """
    plant = Plant(api)
    design = plant.add_design()
    plant.submit_design()
    retired = plant.decide_design("OBSOLETE")
    assert retired["status"] == "OBSOLETE"
    assert retired["version"] == 3

    validate_error(
        api.submit_design_review(
            design["id"], F.submit_review_payload(), U.DESIGN_ENGINEER
        ),
        ERR_INVALID_DESIGN_STATE,
        409,
    )
    validate_error(
        api.record_review_decision(
            design["id"], F.review_decision_payload("APPROVE"), U.DESIGN_REVIEWER
        ),
        ERR_INVALID_DESIGN_STATE,
        409,
    )
    validate_error(
        api.open_design_revision(
            design["id"], F.open_revision_payload(), U.DESIGN_ENGINEER
        ),
        ERR_INVALID_DESIGN_STATE,
        409,
    )

    stored = plant.get_design()
    assert stored["status"] == "OBSOLETE"
    assert stored["version"] == 3
    assert stored["released_at"] is None
    assert stored["released_by_user_id"] is None
    assert stored["review_round"] == 1


def test_neither_confirm_nor_cancel_can_be_replayed_on_the_same_order(api):
    """The allowance ledger proves each transition ran exactly once.

    PRD 3.4: "From any other status — that is, from `FULFILLED` or from
    `CANCELLED` — it is refused with `ERR_INVALID_ORDER_STATE`."

    Design: Corner/state_machines/repeating_order_confirm_and_cancel_is_rejected_on_the_second_attempt
    """
    plant = build_plant(api, "confirmed_order")
    order = plant.order
    assert plant.get_distributor()["units_outstanding"] == 12

    validate_error(
        api.confirm_customer_order(
            order["id"], F.confirm_order_payload(), U.PRODUCTION_PLANNER
        ),
        ERR_INVALID_ORDER_STATE,
        409,
    )
    cancelled = plant.cancel_order()
    validate_error(
        api.cancel_customer_order(
            order["id"],
            F.cancel_order_payload(
                cancellation_reason="Duplicate cancellation request."
            ),
            U.PRODUCTION_PLANNER,
        ),
        ERR_INVALID_ORDER_STATE,
        409,
    )
    validate_error(
        api.create_work_order(
            F.work_order_payload(
                order["id"], plant.design["id"], plant.get_design()["version"]
            ),
            U.PRODUCTION_PLANNER,
        ),
        ERR_INVALID_ORDER_STATE,
        409,
    )

    assert cancelled["status"] == "CANCELLED"
    assert plant.get_order()["status"] == "CANCELLED"
    distributor = plant.get_distributor()
    assert distributor["units_outstanding"] == 0
    assert distributor["stock_allowance_remaining_units"] == 500
    _work_orders, meta = validate_paginated(
        api.list_work_orders(U.PRODUCTION_PLANNER, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 0


def test_a_released_work_order_refuses_assembly_scheduling_and_shipping(api):
    """One build_status precondition speaks for three later-stage operations.

    PRD 3.8: "**Assembly** joins an accepted stator to an accepted rotor and is
    the `BuildTechnician`'s last act. It requires the work order's `build_status`
    to be `SUBASSEMBLIES_DONE`; otherwise the request is refused with
    `ERR_INVALID_WORK_ORDER_STATE`."

    Design: Corner/state_machines/work_order_build_status_gates_each_shop_floor_step_it_precedes
    """
    plant = build_plant(api, "subassemblies_opened")
    work_order = plant.get_work_order()
    assert work_order["build_status"] == "RELEASED"
    assert plant.get_stator()["status"] == "WOUND"
    assert plant.get_rotor()["status"] == "PLANNED"

    validate_error(
        api.create_assembly_record(
            F.assembly_record_payload(
                work_order["id"], plant.stator["id"], plant.rotor["id"]
            ),
            U.BUILD_TECHNICIAN,
        ),
        ERR_INVALID_WORK_ORDER_STATE,
        409,
    )
    validate_error(
        api.create_performance_test(
            F.performance_test_payload(
                work_order["id"],
                plant.cell["id"],
                work_order["version"],
                dyno_draw_kw=12.0,
            ),
            U.TEST_ENGINEER,
        ),
        ERR_INVALID_WORK_ORDER_STATE,
        409,
    )
    validate_error(
        api.ship_work_order(work_order["id"], F.ship_payload(), U.PRODUCTION_PLANNER),
        ERR_INVALID_WORK_ORDER_STATE,
        409,
    )

    unchanged = plant.get_work_order()
    assert unchanged["build_status"] == "RELEASED"
    assert unchanged["certification_status"] == "PENDING"
    assert unchanged["shipped_at"] is None
    A.assert_rounded_to(
        plant.get_cell()["peak_reserved_kw"], 0, 1, "peak_reserved_kw"
    )
    _records, meta = validate_paginated(
        api.list_assembly_records(
            U.BUILD_TECHNICIAN, {"work_order_id": work_order["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_both_subassembly_machines_refuse_triggers_from_their_initial_states(api):
    """Three early triggers, then a second impregnation clear of the buffer.

    PRD 3.6: "**Booking impregnation** moves the stator `WOUND → IMPREGNATED` and
    is the `BuildTechnician`'s act."

    Design: Corner/state_machines/subassembly_steps_refuse_triggers_from_the_wrong_status
    """
    plant = build_plant(api, "subassemblies_opened")
    stator, rotor = plant.stator, plant.rotor

    validate_error(
        api.surge_test_stator_build(
            stator["id"], F.surge_test_payload(), U.TEST_ENGINEER
        ),
        ERR_INVALID_SUBASSEMBLY_STATE,
        409,
    )
    validate_error(
        api.machine_rotor_build(rotor["id"], F.machine_payload(), U.BUILD_TECHNICIAN),
        ERR_INVALID_SUBASSEMBLY_STATE,
        409,
    )
    validate_error(
        api.balance_disposition_rotor_build(
            rotor["id"], F.balance_disposition_payload(), U.TEST_ENGINEER
        ),
        ERR_INVALID_SUBASSEMBLY_STATE,
        409,
    )
    impregnated = plant.impregnate_stator()
    validate_error(
        api.impregnate_stator_build(
            stator["id"],
            F.second_impregnation_payload(plant.oven["id"]),
            U.BUILD_TECHNICIAN,
        ),
        ERR_INVALID_SUBASSEMBLY_STATE,
        409,
    )

    assert impregnated["status"] == "IMPREGNATED"
    A.assert_rounded_to(
        impregnated["achieved_capability_kv"],
        A.expected_achieved_capability_kv(400, "F", "VPI", 2),
        2,
        "achieved_capability_kv",
    )
    assert impregnated["achieved_capability_kv"] == 2.58
    stored_stator = plant.get_stator()
    assert stored_stator["impregnation_window_start"] == F.IMPREGNATION_WINDOW_START
    assert stored_stator["impregnation_window_end"] == F.IMPREGNATION_WINDOW_END
    assert stored_stator["impregnation_minutes"] == 240
    assert plant.get_oven()["booked_minutes"] == 240
    stored_rotor = plant.get_rotor()
    assert stored_rotor["status"] == "PLANNED"
    assert stored_rotor["measured_air_gap_mm"] is None
    assert stored_rotor["balance_grade"] is None


def test_issuing_a_nameplate_then_shipping_runs_every_declared_side_effect(api):
    """Two transitions, seven side effects, and one axis left untouched by each.

    PRD 3.9: "On success the nameplate copies `stamped_efficiency_pct` from the
    test's `measured_efficiency_pct` and `stamped_class` from its
    `achieved_class`, captures `certifier_user_id` from the caller's `X-User-ID`
    and `issued_at` from the logical clock — the instant that later serves as the
    pro-rata origin for warranty credit — and lands in `ISSUED` status with
    `revoked_at` and `revocation_reason` both unset."

    Design: Corner/state_machines/nameplate_issue_and_ship_execute_their_full_declared_side_effect_chain
    """
    plant = build_plant(api, "tested", test={"dyno_draw_kw": 12.0})
    assert plant.get_work_order()["build_status"] == "TESTED"
    assert plant.get_test()["measured_efficiency_pct"] == 93.42

    nameplate = plant.issue_nameplate()

    assert nameplate["standard_id"] == plant.standard["id"]
    A.assert_rounded_to(
        nameplate["minimum_efficiency_pct_applied"],
        89.60,
        2,
        "minimum_efficiency_pct_applied",
    )
    assert nameplate["stamped_efficiency_pct"] == 93.42
    assert nameplate["stamped_class"] == "IE3"
    assert nameplate["status"] == "ISSUED"
    assert nameplate["certifier_user_id"] == U.USER_QUALITY_CERTIFIER
    assert nameplate["issued_at"] == F.RECORD_CLOCK
    assert nameplate["revoked_at"] is None
    assert nameplate["revocation_reason"] is None
    assert nameplate["version"] == 1
    certified = plant.get_work_order()
    assert certified["certification_status"] == "CERTIFIED"
    assert certified["build_status"] == "TESTED"
    assert plant.get_assembly()["status"] == "BUILT"

    shipped = plant.ship_work_order()

    assert shipped["build_status"] == "SHIPPED"
    assert shipped["shipped_at"] == F.RECORD_CLOCK
    assert shipped["certification_status"] == "CERTIFIED"
    assert plant.get_order()["status"] == "FULFILLED"
    distributor = plant.get_distributor()
    assert distributor["units_outstanding"] == 0
    assert distributor["stock_allowance_remaining_units"] == 500
    A.assert_rounded_to(
        plant.get_cell()["peak_reserved_kw"], 12.0, 1, "peak_reserved_kw"
    )
    assert plant.get_test()["status"] == "COMPLETED"


def test_a_closed_claim_refuses_analysis_dispute_and_a_second_closure(api):
    """The frozen credit is the observable: nothing moves after closure.

    PRD 3.10: "`CLOSED` is terminal: no further analysis or dispute is possible."

    Design: Corner/state_machines/closed_warranty_claim_is_terminal_and_refuses_analyze_dispute_and_close
    """
    plant = build_plant(api, "shipped")
    assert plant.get_work_order()["shipped_at"] == F.RECORD_CLOCK
    plant.set_clock(CLAIM_CLOCK)
    claim = plant.file_claim(**BENIGN_APPLICATION)
    adjudicated = plant.analyze_claim(F.analyze_field_data_payload())
    assert adjudicated["misuse_index"] == 0.4705
    assert adjudicated["adjudication"] == "DEFECT_CONFIRMED"
    waterfall = A.expected_warranty_credit_cents(
        A.expected_cost_rollup(F.motor_design_payload(), 12)[
            "unit_standard_cost_cents"
        ],
        adjudicated["claimed_parts_cents"],
        adjudicated["claimed_labor_cents"],
        adjudicated["claimed_freight_cents"],
        A.service_age_months(A.date_of(F.RECORD_CLOCK), A.date_of(CLAIM_CLOCK)),
    )
    closed = plant.close_claim()
    assert closed["status"] == "CLOSED"
    assert closed["warranty_credit_cents"] == waterfall["warranty_credit_cents"]
    assert closed["warranty_credit_cents"] == 149922

    validate_error(
        api.analyze_warranty_claim(
            claim["id"], F.analyze_teardown_payload(90.0), U.COMPLIANCE_OFFICER
        ),
        ERR_INVALID_CLAIM_STATE,
        409,
    )
    validate_error(
        api.dispute_warranty_claim(
            claim["id"], F.dispute_payload(), plant.distributor_headers
        ),
        ERR_INVALID_CLAIM_STATE,
        409,
    )
    validate_error(
        api.close_warranty_claim(
            claim["id"],
            F.close_claim_payload(closure_notes="Closing again."),
            U.COMPLIANCE_OFFICER,
        ),
        ERR_INVALID_CLAIM_STATE,
        409,
    )

    frozen = plant.get_claim()
    assert frozen["status"] == "CLOSED"
    assert frozen["version"] == closed["version"]
    assert frozen["adjudication"] == "DEFECT_CONFIRMED"
    assert frozen["misuse_index"] == 0.4705
    assert frozen["warranty_credit_cents"] == 149922
    assert frozen["credit_posted"] is True
    assert frozen["dispute_round"] == 0
    assert frozen["analysis_basis"] == "FIELD_DATA"
    assert frozen["teardown_defect_evidence_pct"] is None
    assert plant.get_distributor()["warranty_credit_balance_cents"] == 149922


def test_revoking_a_revoked_nameplate_neither_moves_the_row_nor_reruns_the_cascade(api):
    """The clock advanced between the calls, and revoked_at kept the first instant.

    PRD 3.9: "**Revoking** a certificate is the same `QualityCertifier` role's
    act, permitted only from `ISSUED` (`ERR_INVALID_NAMEPLATE_STATE`), and takes a
    mandatory `revocation_reason`."

    Design: Corner/state_machines/revoking_an_already_revoked_nameplate_is_rejected_and_changes_nothing
    """
    plant = build_plant(api, "certified")
    revoked = plant.revoke_nameplate()
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_at"] == F.RECORD_CLOCK
    first_reason = revoked["revocation_reason"]
    suspended = plant.get_work_order()
    assert suspended["certification_status"] == "SUSPENDED"
    assert suspended["build_status"] == "TESTED"
    plant.set_clock(SECOND_REVOKE_CLOCK)

    validate_error(
        api.revoke_nameplate(
            revoked["id"],
            F.revoke_nameplate_payload(
                revocation_reason="Second revocation attempt."
            ),
            U.QUALITY_CERTIFIER,
        ),
        ERR_INVALID_NAMEPLATE_STATE,
        409,
    )

    unchanged = plant.get_nameplate()
    assert unchanged["status"] == "REVOKED"
    assert unchanged["revoked_at"] == F.RECORD_CLOCK
    assert unchanged["revoked_at"] != SECOND_REVOKE_CLOCK
    assert unchanged["revocation_reason"] == first_reason
    assert unchanged["version"] == revoked["version"]
    still_suspended = plant.get_work_order()
    assert still_suspended["certification_status"] == "SUSPENDED"
    assert still_suspended["version"] == suspended["version"]


def test_a_superseded_test_can_neither_be_recorded_nor_stamped(api):
    """The replacement does both, and the cell ledger never double-counted.

    PRD 3.8: "Scheduling also supersedes: any performance test already
    `SCHEDULED` on the same work order moves `SCHEDULED → SUPERSEDED`,
    incrementing its own `version`, and the cell's `peak_reserved_kw` is
    recomputed with that test's draw released and the cell's `version`
    incremented."

    Design: Corner/state_machines/superseded_performance_test_cannot_record_and_cannot_back_a_nameplate
    """
    # The replacement reuses the same window, and PRD 2.11 evaluates
    # ERR_TEST_CELL_CAPACITY_EXCEEDED last, so the test being superseded is still
    # SCHEDULED when the aggregate is summed — only a SUPERSEDED test releases
    # its draw. The cell is therefore registered with headroom for both draws, so
    # that this test exercises the supersession machine and not the ceiling.
    plant = build_plant(api, "assembled", cell={"max_concurrent_kw": 40.0})
    first = plant.schedule_test(dyno_draw_kw=12.0)

    replacement = plant.schedule_test(dyno_draw_kw=12.0)

    assert plant.get_test(first)["status"] == "SUPERSEDED"
    assert plant.get_test(replacement)["status"] == "SCHEDULED"
    A.assert_rounded_to(
        plant.get_cell()["peak_reserved_kw"], 12.0, 1, "peak_reserved_kw"
    )
    plant.set_clock(F.RECORD_CLOCK)
    validate_error(
        api.record_performance_test(
            first["id"], F.record_results_payload(), U.TEST_ENGINEER
        ),
        ERR_INVALID_PERFORMANCE_TEST_STATE,
        409,
    )
    abandoned = plant.get_test(first)
    assert abandoned["input_power_kw"] is None
    assert abandoned["measured_efficiency_pct"] is None
    assert abandoned["recorded_at"] is None

    completed = validate_success(
        api.record_performance_test(
            replacement["id"], F.record_results_payload(), U.TEST_ENGINEER
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["measured_efficiency_pct"] == 93.42
    assert plant.get_work_order()["build_status"] == "TESTED"
    validate_error(
        api.create_nameplate(
            F.nameplate_payload(plant.work_order["id"], first["id"]),
            U.QUALITY_CERTIFIER,
        ),
        ERR_INVALID_PERFORMANCE_TEST_STATE,
        409,
    )

    issued = validate_success(
        api.create_nameplate(
            F.nameplate_payload(plant.work_order["id"], replacement["id"]),
            U.QUALITY_CERTIFIER,
        ),
        201,
    )
    assert issued["performance_test_id"] == replacement["id"]
    assert issued["stamped_efficiency_pct"] == 93.42
    _plates, meta = validate_paginated(
        api.list_nameplates(
            U.QUALITY_CERTIFIER, {"work_order_id": plant.work_order["id"]}
        )
    )
    assert meta["total_count"] == 1
