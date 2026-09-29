"""Scouting evidence, regulated applications and the re-entry cascade."""
from test_helpers import (
    DUAL_ROLE_USER_IDS,
    ApiErrorId,
    assert_instant,
    assert_money,
    assert_pest_observation,
    assert_plan_ledger,
    assert_spray_record,
    assert_version,
    make_agronomist_headers,
    make_applicator_headers,
    make_compliance_officer_headers,
    make_crew_supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _approved_plan_on_an_unenrolled_block(api):
    """Ranch, block and an approved 2026 programme, with no agreement in play.

    The block's `version` is 2 at the end: 1 at create and 2 when the approval
    cascade drives it `ESTABLISHING → BEARING`.
    """
    ranch = fx.create_vineyard(api)
    block = fx.create_block(api, ranch["id"])
    plan = fx.create_farming_plan(api, block["id"])
    fx.submit_farming_plan(api, plan["id"])
    plan = fx.approve_farming_plan(api, plan["id"])
    return fx.Scenario(vineyard=ranch, block=fx.read_block(api, block["id"]),
                       plan=plan)


class TestScoutingObservations:
    """PRD §2.4 and §3.6 — a filed observation is a lean immutable event record."""

    def test_a_filed_observation_carries_no_version_field(self, api):
        """Neither has an `updated_at` field and neither has a `version` field — those keys are absent from their representations entirely, not merely null.

        Design: Corner/entities/pest_observation_is_immutable_and_carries_no_version
        """
        s = fx.setup_ranch_with_block(api)

        data = validate_success(
            api.create_pest_observation(
                s.block["id"],
                f.pest_observation_payload(
                    pest_code="VINE_MEALYBUG", incidence_pct=3.0, severity_index=2,
                    scouting_note="Crawlers under bark on rows 4-9",
                ),
                fx.AG,
            ),
            201,
        )

        assert_pest_observation(data)
        assert "version" not in data
        assert "updated_at" not in data
        assert_instant(data["observed_at"], "2026-08-01T00:00:00Z", "observed_at")
        assert data["scout_user_id"] == "u-ag-1"
        assert data["action_threshold_pct"] == 2.0
        assert data["exceeds_threshold"] is True
        assert data["scouting_note"] == "Crawlers under bark on rows 4-9"

        rows, meta = validate_paginated(
            api.list_pest_observations(s.block["id"], fx.AG,
                                       {"limit": 10, "offset": 0})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert "version" not in rows[0]
        assert "updated_at" not in rows[0]


class TestRecommendationRequiresEvidence:
    """PRD §3.6 — the cited observation decides whether a spray may be written."""

    def test_a_sub_threshold_observation_cannot_justify_a_spray(self, api):
        """The cited observation must have `exceeds_threshold` true — a spray may not be recommended below the pest's action threshold, and citing a sub-threshold observation is refused with `ERR_ACTION_THRESHOLD_NOT_MET`.

        Design: Corner/validations/spray_recommendation_below_action_threshold_rejected
        """
        s = fx.setup_approved_plan(api)
        observation = fx.file_pest_observation(
            api, s.block["id"], pest_code="POWDERY_MILDEW", incidence_pct=4.0,
            severity_index=1,
        )
        assert observation["action_threshold_pct"] == 5.0
        assert observation["exceeds_threshold"] is False

        validate_error(
            api.create_spray_record(
                f.spray_record_payload(s.block["id"], s.plan["id"],
                                       observation["id"]),
                fx.AG,
            ),
            ApiErrorId.ERR_ACTION_THRESHOLD_NOT_MET,
        )

        block = fx.read_block(api, s.block["id"])
        assert block["compliance_posture"] == "CLEAR"
        assert block["rei_clear_at"] is None
        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 0.00,
                     "committed_cost")

    def test_an_observation_exactly_at_the_threshold_justifies_a_spray(self, api):
        """The registered thresholds are fixed at 5.0 for `POWDERY_MILDEW`, 2.0 for `VINE_MEALYBUG`, 3.0 for `BOTRYTIS` and 10.0 for `LEAFHOPPER` — and it sets `exceeds_threshold` to true exactly when the observed `incidence_pct` is greater than or equal to that `action_threshold_pct`, and to false otherwise.

        Design: Corner/validations/pest_observation_at_exact_action_threshold_permits_recommendation
        """
        s = fx.setup_approved_plan(api)
        observation = fx.file_pest_observation(
            api, s.block["id"], pest_code="POWDERY_MILDEW", incidence_pct=5.0,
            severity_index=2,
        )
        assert observation["action_threshold_pct"] == 5.0
        assert observation["exceeds_threshold"] is True

        data = validate_success(
            api.create_spray_record(
                f.spray_record_payload(s.block["id"], s.plan["id"],
                                       observation["id"]),
                fx.AG,
            ),
            201,
        )

        assert_spray_record(data)
        assert data["spray_status"] == "RECOMMENDED"
        assert data["recommended_by_user_id"] == "u-ag-1"
        assert data["applied_by_user_id"] is None
        assert data["verified_by_user_id"] is None
        assert data["rei_clear_at"] is None
        assert data["phi_clear_at"] is None
        assert data["applied_at"] is None
        assert_version(data, 1, "spray record")

        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 0.00,
                     "committed_cost")


class TestVerificationGuards:
    """PRD §3.6 — three distinct people must sign a regulated application."""

    def test_verifying_a_recommendation_that_was_never_applied_is_refused(self, api):
        """The record must be `APPLIED`, otherwise `ERR_SPRAY_NOT_APPLIED`, and the verifying `X-User-ID` must differ from both `recommended_by_user_id` and `applied_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` — three distinct people must touch a regulated application before it is fully attested.

        Design: Corner/state_machines/spray_verify_from_recommended_rejected
        """
        s = fx.setup_recommended_spray(api, fx.setup_approved_plan(api))

        validate_error(
            api.verify_spray_record(s.spray["id"], fx.CO, f.verify_spray_payload()),
            ApiErrorId.ERR_SPRAY_NOT_APPLIED,
        )

        spray = fx.read_spray_record(api, s.spray["id"])
        assert spray["spray_status"] == "RECOMMENDED"
        assert spray["verified_by_user_id"] is None
        assert spray["applied_at"] is None
        assert_version(spray, 1, "spray record")

        block = fx.read_block(api, s.block["id"])
        assert block["rei_clear_at"] is None
        assert block["phi_clear_at"] is None
        assert block["compliance_posture"] == "CLEAR"
        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 0.00,
                     "committed_cost")

    def test_neither_the_recommender_nor_the_applicator_may_verify(self, api):
        """The record must be `APPLIED`, otherwise `ERR_SPRAY_NOT_APPLIED`, and the verifying `X-User-ID` must differ from both `recommended_by_user_id` and `applied_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` — three distinct people must touch a regulated application before it is fully attested.

        Design: Corner/rbac/spray_verify_by_recommender_or_applicator_rejected
        """
        s = fx.setup_applied_spray(api, fx.setup_approved_plan(api))
        assert s.spray["recommended_by_user_id"] == "u-ag-1"
        assert s.spray["applied_by_user_id"] == "u-app-1"
        version_before = s.spray["version"]

        for user_id in ("u-ag-1", "u-app-1"):
            validate_error(
                api.verify_spray_record(
                    s.spray["id"], make_compliance_officer_headers(user_id),
                    f.verify_spray_payload(),
                ),
                ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            )
            barred = fx.read_spray_record(api, s.spray["id"])
            assert barred["spray_status"] == "APPLIED"
            assert barred["verified_by_user_id"] is None
            assert_version(barred, version_before, "spray record")

        verified = validate_success(
            api.verify_spray_record(s.spray["id"], fx.CO, f.verify_spray_payload())
        )
        assert verified["spray_status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "u-co-1"
        assert_version(verified, version_before + 1, "spray record")
        assert_instant(fx.read_block(api, s.block["id"])["rei_clear_at"],
                       "2026-08-04T00:00:00Z", "block rei_clear_at")


class TestApplicationSignatureAndVersionGuard:
    """PRD §3.6 and §2.8 — who may apply, and against which block version."""

    def test_the_recommending_user_may_not_log_the_application(self, api):
        """The record must be `RECOMMENDED`, otherwise `ERR_SPRAY_NOT_RECOMMENDED`; the block must not be `REMOVED`; and the acting `X-User-ID` must differ from `recommended_by_user_id`, because the person who wrote the recommendation may not be the person who signs for having carried it out.

        Design: Corner/rbac/spray_apply_by_the_recommending_user_rejected
        """
        dual = DUAL_ROLE_USER_IDS["SPRAY_RECOMMENDER_AND_APPLICATOR"]
        s = _approved_plan_on_an_unenrolled_block(api)
        assert_version(s.block, 2, "block")
        observation = fx.file_pest_observation(api, s.block["id"],
                                              headers=make_agronomist_headers(dual))
        spray = fx.create_spray_record(api, s.block["id"], s.plan["id"],
                                       observation["id"],
                                       headers=make_agronomist_headers(dual))
        assert spray["recommended_by_user_id"] == dual
        assert spray["spray_status"] == "RECOMMENDED"

        validate_error(
            api.apply_spray_record(spray["id"], f.apply_spray_payload(2),
                                   make_applicator_headers(dual)),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        block = fx.read_block(api, s.block["id"])
        assert block["rei_clear_at"] is None
        assert_version(block, 2, "block")

        applied = validate_success(
            api.apply_spray_record(spray["id"], f.apply_spray_payload(2), fx.APP)
        )
        assert applied["spray_status"] == "APPLIED"
        assert applied["applied_by_user_id"] == "u-app-1"
        assert_instant(applied["rei_clear_at"], "2026-08-04T00:00:00Z",
                       "rei_clear_at")
        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 812.50,
                     "committed_cost")

    def test_an_application_quoting_a_stale_block_version_is_refused(self, api):
        """If the block's `version` has advanced since that read, the application is rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412).

        Design: Corner/complexity layers/stale_block_version_on_spray_apply_returns_conflict
        """
        s = _approved_plan_on_an_unenrolled_block(api)
        assert_version(s.block, 2, "block")
        assert s.block["farming_status"] == "BEARING"
        s = fx.setup_recommended_spray(api, s)

        validate_error(
            api.apply_spray_record(s.spray["id"], f.apply_spray_payload(1), fx.APP),
            ApiErrorId.ERR_STALE_BLOCK_VERSION,
        )

        spray = fx.read_spray_record(api, s.spray["id"])
        assert spray["spray_status"] == "RECOMMENDED"
        assert spray["applied_at"] is None

        retried = validate_success(
            api.apply_spray_record(s.spray["id"], f.apply_spray_payload(2), fx.APP)
        )
        assert retried["spray_status"] == "APPLIED"

        block = fx.read_block(api, s.block["id"])
        assert_version(block, 3, "block")
        assert_instant(block["rei_clear_at"], "2026-08-04T00:00:00Z",
                       "rei_clear_at")
        assert block["compliance_posture"] == "REENTRY_RESTRICTED"

    def test_the_block_version_moves_for_every_writer_that_touches_it(self, api):
        """`version` is 1 the moment the resource is created and increases by exactly 1 on every mutation of that resource, whether the mutation is caused by a direct request against the resource or by a cascade fired from somewhere else in the system; `updated_at` is refreshed to the current instant on the same occasions.

        Design: Corner/complexity layers/block_version_increments_on_every_write_that_touches_it
        """
        ranch = fx.create_vineyard(api)
        contract = fx.create_contract(api, ranch["id"])

        created = validate_success(
            api.create_block(f.block_payload(ranch["id"]), fx.VM), 201
        )
        assert_version(created, 1, "block after create")

        enrolled = fx.enroll_block(api, contract["id"], created["id"], 12.5)
        assert_version(enrolled, 2, "block after enrollment")

        plan = fx.create_farming_plan(api, created["id"])
        fx.submit_farming_plan(api, plan["id"])
        plan = fx.approve_farming_plan(api, plan["id"])
        after_approval = fx.read_block(api, created["id"])
        assert_version(after_approval, 3, "block after plan approval")
        assert after_approval["farming_status"] == "BEARING"

        observation = fx.file_pest_observation(api, created["id"])
        spray = fx.create_spray_record(api, created["id"], plan["id"],
                                       observation["id"])
        assert_version(fx.read_block(api, created["id"]), 3,
                       "block after scouting and recommendation")

        applied = fx.apply_spray_record(api, spray["id"], 3)
        assert applied["spray_status"] == "APPLIED"
        assert_version(fx.read_block(api, created["id"]), 4,
                       "block after the application")

    def test_block_clearances_never_shorten_under_a_later_short_interval(self, api):
        """Because the block takes the maximum, a later application carrying a short interval never shortens a longer restriction already in force, and a `RECOMMENDED` record — having no clearances at all — imposes no restriction whatever.

        Design: Corner/calculations/block_clearances_take_the_maximum_across_applied_sprays
        """
        s = _approved_plan_on_an_unenrolled_block(api)
        assert_version(s.block, 2, "block")
        mildew = fx.file_pest_observation(api, s.block["id"])
        mealybug = fx.file_pest_observation(
            api, s.block["id"], pest_code="VINE_MEALYBUG", incidence_pct=5.0,
            severity_index=2,
        )
        long_rei = fx.create_spray_record(api, s.block["id"], s.plan["id"],
                                         mildew["id"])
        short_rei = fx.create_spray_record(
            api, s.block["id"], s.plan["id"], mealybug["id"],
            product_name="Movento", active_ingredient="spirotetramat",
            rei_hours=24, phi_days=30, material_cost=640.00,
        )

        first = fx.apply_spray_record(api, long_rei["id"], 2)
        assert_instant(first["rei_clear_at"], "2026-08-04T00:00:00Z",
                       "first rei_clear_at")
        assert_instant(first["phi_clear_at"], "2026-08-22T00:00:00Z",
                       "first phi_clear_at")
        block = fx.read_block(api, s.block["id"])
        assert_version(block, 3, "block after the first application")
        assert_instant(block["rei_clear_at"], "2026-08-04T00:00:00Z",
                       "block rei_clear_at")
        assert_instant(block["phi_clear_at"], "2026-08-22T00:00:00Z",
                       "block phi_clear_at")

        second = fx.apply_spray_record(api, short_rei["id"], 3)
        assert_instant(second["rei_clear_at"], "2026-08-02T00:00:00Z",
                       "second rei_clear_at")
        assert_instant(second["phi_clear_at"], "2026-08-31T00:00:00Z",
                       "second phi_clear_at")

        block = fx.read_block(api, s.block["id"])
        assert_instant(block["rei_clear_at"], "2026-08-04T00:00:00Z",
                       "block rei_clear_at")
        assert_instant(block["phi_clear_at"], "2026-08-31T00:00:00Z",
                       "block phi_clear_at")
        assert block["compliance_posture"] == "REENTRY_RESTRICTED"
        assert_version(block, 4, "block after the second application")
        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 1452.50,
                     "committed_cost")


class TestReentryGatesOnFieldWork:
    """PRD §3.6 — re-entry governs booking and starting, and certification exempts."""

    def test_booking_an_uncertified_crew_into_an_open_reentry_window_is_refused(self, api):
        """At scheduling time, a work order whose `scheduled_start` falls before the block's current `rei_clear_at` may only be booked for a crew whose `pest_certified` flag is true; booking an uncertified crew into an open re-entry window is refused with `ERR_CREW_NOT_PEST_CERTIFIED`.

        Design: Corner/validations/work_order_booked_inside_reentry_for_uncertified_crew_rejected
        """
        s = fx.setup_approved_plan(api)
        plain_crew = fx.create_crew(api)
        certified_crew = fx.create_crew(api, crew_name="Cuadrilla Certificada",
                                        pest_certified=True)
        s = fx.setup_applied_spray(api, s)
        assert_instant(s.block["rei_clear_at"], "2026-08-04T00:00:00Z",
                       "rei_clear_at")
        assert s.block["compliance_posture"] == "REENTRY_RESTRICTED"

        def booking(crew_id):
            return f.work_order_payload(
                s.block["id"], s.plan["id"], crew_id, task_type="LEAFING",
                scheduled_start="2026-08-03T14:00:00Z",
                scheduled_end="2026-08-03T22:00:00Z",
                planned_vines=3000, planned_hours=8.0,
            )

        validate_error(api.create_work_order(booking(plain_crew["id"]), fx.VM),
                       ApiErrorId.ERR_CREW_NOT_PEST_CERTIFIED)

        accepted = validate_success(
            api.create_work_order(booking(certified_crew["id"]), fx.VM), 201
        )
        assert accepted["execution_status"] == "SCHEDULED"
        assert_money(accepted["estimated_labor_cost"], 2505.75,
                     "estimated_labor_cost")

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 3318.25, 11369.25,
                           "WITHIN_BUDGET")
        assert fx.read_crew(api, plain_crew["id"])["scheduled_work_order_count"] == 0

    def test_a_certified_crew_may_start_inside_the_reentry_interval(self, api):
        """At start time, the logical clock must read at or after the block's `rei_clear_at` unless the crew is `pest_certified`; a block with a null `rei_clear_at` imposes no restriction at all.

        Design: Corner/endpoints/work_order_start_during_reentry_permitted_for_pest_certified_crew
        """
        s = fx.setup_approved_plan(api)
        plain_crew = fx.create_crew(api)
        certified_crew = fx.create_crew(api, crew_name="Cuadrilla Certificada",
                                        pest_certified=True)
        certified_order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], certified_crew["id"],
            task_type="LEAFING",
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T22:00:00Z",
            planned_vines=3000, planned_hours=8.0,
        )
        plain_order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], plain_crew["id"], task_type="LEAFING",
            scheduled_start="2026-08-05T14:00:00Z",
            scheduled_end="2026-08-05T22:00:00Z",
            planned_vines=3000, planned_hours=8.0,
        )

        s = fx.setup_applied_spray(api, s)
        assert_instant(s.block["rei_clear_at"], "2026-08-04T00:00:00Z",
                       "rei_clear_at")
        assert fx.read_work_order(api, plain_order["id"])["execution_status"] == \
            "SCHEDULED"

        started = fx.start_work_order(api, certified_order["id"],
                                      certified_crew["id"])
        assert started["execution_status"] == "IN_PROGRESS"
        assert_instant(started["started_at"], "2026-08-01T00:00:00Z", "started_at")

        validate_error(
            api.start_work_order(plain_order["id"],
                                 make_crew_supervisor_headers(plain_crew["id"])),
            ApiErrorId.ERR_REENTRY_INTERVAL_ACTIVE,
        )
        refused = fx.read_work_order(api, plain_order["id"])
        assert refused["execution_status"] == "SCHEDULED"
        assert refused["started_at"] is None


class TestApplicationCascade:
    """PRD §3.6 — one application reaches the block, the calendar and the ledger."""

    def test_the_application_derives_both_clearance_instants(self, api):
        """From `applied_at` two clearance instants are derived on the record itself, both expressed in ISO 8601 UTC to whole seconds: `rei_clear_at` is `applied_at` advanced by `rei_hours` hours, and `phi_clear_at` is `applied_at` advanced by `phi_days` multiplied by 24 hours.

        Design: Difficulty/transitive_cascade/spray_apply_cascades_five_levels_to_plan_posture
        """
        s = fx.setup_spray_cascade_scenario(api)
        assert_plan_ledger(s.plan, 13364.00, 1323.50, "AT_RISK")
        s = fx.setup_recommended_spray(api, s)

        applied = fx.apply_spray_record(api, s.spray["id"],
                                        fx.block_version(api, s.block["id"]))

        assert applied["spray_status"] == "APPLIED"
        assert applied["applied_by_user_id"] == "u-app-1"
        assert_instant(applied["applied_at"], "2026-08-02T06:00:00Z", "applied_at")
        assert_instant(applied["rei_clear_at"], "2026-08-05T06:00:00Z",
                       "rei_clear_at")
        assert_instant(applied["phi_clear_at"], "2026-08-23T06:00:00Z",
                       "phi_clear_at")

        block = fx.read_block(api, s.block["id"])
        assert_instant(block["rei_clear_at"], "2026-08-05T06:00:00Z",
                       "block rei_clear_at")
        assert_instant(block["phi_clear_at"], "2026-08-23T06:00:00Z",
                       "block phi_clear_at")
        assert block["compliance_posture"] == "REENTRY_RESTRICTED"
        assert_version(block, 4, "block")

    def test_the_sweep_cancels_only_the_orders_caught_by_the_interval(self, api):
        """Each auto-cancellation behaves exactly like an operator cancellation from `SCHEDULED`: `actual_labor_cost` stays null, `payroll_status` stays `NOT_PAYABLE`, and the frozen estimate leaves the plan ledger.

        Design: Difficulty/transitive_cascade/spray_apply_cascades_five_levels_to_plan_posture
        """
        s = fx.setup_spray_cascade_scenario(api)
        assert fx.read_crew(api, s.crew["id"])["scheduled_work_order_count"] == 2
        s = fx.setup_recommended_spray(api, s)

        fx.apply_spray_record(api, s.spray["id"],
                              fx.block_version(api, s.block["id"]))

        caught = fx.read_work_order(api, s.work_order_a["id"])
        assert caught["execution_status"] == "CANCELLED"
        assert caught["cancel_reason"] == "REENTRY_RESTRICTION"
        assert caught["actual_labor_cost"] is None
        assert caught["payroll_status"] == "NOT_PAYABLE"
        assert_money(caught["estimated_labor_cost"], 10858.25,
                     "estimated_labor_cost")

        survivor = fx.read_work_order(api, s.work_order_b["id"])
        assert survivor["execution_status"] == "SCHEDULED"
        assert survivor["cancel_reason"] is None
        assert_money(survivor["estimated_labor_cost"], 2505.75,
                     "estimated_labor_cost")

        assert fx.read_crew(api, s.crew["id"])["scheduled_work_order_count"] == 1

    def test_the_ledger_absorbs_the_material_and_releases_the_cancelled_estimate(self, api):
        """The plan's `committed_cost`, `remaining_budget` and `budget_posture` are then recomputed once with both movements folded in — the new `material_cost` joining the ledger and the cancelled estimates leaving it — the `scheduled_work_order_count` of every affected crew is recomputed, and the spray record's own `version` is incremented by 1.

        Design: Difficulty/transitive_cascade/spray_apply_cascades_five_levels_to_plan_posture
        """
        s = fx.setup_spray_cascade_scenario(api)
        assert_plan_ledger(s.plan, 13364.00, 1323.50, "AT_RISK")
        s = fx.setup_recommended_spray(api, s)
        assert_version(s.spray, 1, "spray record")

        applied = fx.apply_spray_record(api, s.spray["id"],
                                        fx.block_version(api, s.block["id"]))
        assert_version(applied, 2, "spray record")

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 3318.25, 11369.25,
                           "WITHIN_BUDGET")


class TestReentryClearanceBoundary:
    """PRD §3.6 — the clearance instant itself is on the permitted side."""

    def _order_after_the_interval(self, api):
        s = fx.setup_operational_block(api)
        s.work_order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="LEAFING",
            scheduled_start="2026-08-10T06:00:00Z",
            scheduled_end="2026-08-10T14:00:00Z",
            planned_vines=3000, planned_hours=8.0,
        )
        assert_money(s.work_order["estimated_labor_cost"], 2505.75,
                     "estimated_labor_cost")
        fx.set_clock(api, "2026-08-02T06:00:00Z")
        s = fx.setup_applied_spray(api, s)
        assert_instant(s.block["rei_clear_at"], "2026-08-05T06:00:00Z",
                       "rei_clear_at")
        assert_instant(s.block["phi_clear_at"], "2026-08-23T06:00:00Z",
                       "phi_clear_at")
        assert fx.read_work_order(api, s.work_order["id"])["execution_status"] == \
            "SCHEDULED"
        return s

    def test_one_second_before_the_clearance_instant_the_start_is_refused(self, api):
        """An application at 06:00:00Z on 2 August 2026 with a 72-hour re-entry interval and a 21-day pre-harvest interval clears re-entry at 06:00:00Z on 5 August and pre-harvest at 06:00:00Z on 23 August; starting a work order at exactly 06:00:00Z on 5 August is permitted, and one second earlier is refused with `ERR_REENTRY_INTERVAL_ACTIVE`.

        Design: Difficulty/boundary_precision_check/work_order_start_at_exact_reentry_clearance_instant_is_permitted
        """
        s = self._order_after_the_interval(api)
        fx.set_clock(api, "2026-08-05T05:59:59Z")

        validate_error(
            api.start_work_order(s.work_order["id"],
                                 make_crew_supervisor_headers(s.crew["id"])),
            ApiErrorId.ERR_REENTRY_INTERVAL_ACTIVE,
        )

        order = fx.read_work_order(api, s.work_order["id"])
        assert order["execution_status"] == "SCHEDULED"
        assert order["started_at"] is None
        assert_version(order, 1, "work order")
        assert fx.read_block(api, s.block["id"])["compliance_posture"] == \
            "REENTRY_RESTRICTED"

    def test_at_the_clearance_instant_the_start_is_permitted(self, api):
        """Both comparisons that consume these instants are inclusive of the instant itself: entry is permitted once the logical clock reads at or after the block's `rei_clear_at`, and harvest is permitted once it reads at or after the block's `phi_clear_at`.

        Design: Difficulty/boundary_precision_check/work_order_start_at_exact_reentry_clearance_instant_is_permitted
        """
        s = self._order_after_the_interval(api)
        fx.set_clock(api, "2026-08-05T06:00:00Z")

        started = fx.start_work_order(api, s.work_order["id"], s.crew["id"])

        assert started["execution_status"] == "IN_PROGRESS"
        assert_instant(started["started_at"], "2026-08-05T06:00:00Z", "started_at")
        assert_version(started, 2, "work order")

        assert fx.read_block(api, s.block["id"])["compliance_posture"] == \
            "PHI_RESTRICTED"
        assert_money(fx.read_plan(api, s.plan["id"])["committed_cost"], 3318.25,
                     "committed_cost")


class TestCertifiedCrewSurvivesTheSweep:
    """PRD §3.6 — the sweep spares certified crews whatever the calendar says."""

    def test_the_certified_crews_order_survives_an_application(self, api):
        """Orders whose `scheduled_start` is at or after the new clearance instant stay `SCHEDULED`, and orders held by a certified crew stay `SCHEDULED` no matter when they start.

        Design: Corner/state_machines/spray_apply_leaves_pest_certified_crew_order_scheduled
        """
        s = fx.setup_operational_block(api)
        certified_crew = fx.create_hourly_crew(api, crew_name="Cuadrilla Sur",
                                               pest_certified=True)
        uncertified_order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], s.crew["id"], task_type="PRUNING",
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T22:00:00Z",
            planned_vines=6000, planned_hours=10.0,
        )
        certified_order = fx.create_work_order(
            api, s.block["id"], s.plan["id"], certified_crew["id"],
            task_type="LEAFING",
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T22:00:00Z",
            planned_vines=3000, planned_hours=8.0,
        )
        assert_money(uncertified_order["estimated_labor_cost"], 5011.50,
                     "estimated_labor_cost")
        assert_money(certified_order["estimated_labor_cost"], 1809.28,
                     "estimated_labor_cost")

        s = fx.setup_applied_spray(api, s)
        assert_instant(s.spray["rei_clear_at"], "2026-08-04T00:00:00Z",
                       "rei_clear_at")
        assert_instant(s.spray["phi_clear_at"], "2026-08-22T00:00:00Z",
                       "phi_clear_at")
        assert s.block["compliance_posture"] == "REENTRY_RESTRICTED"

        cancelled = fx.read_work_order(api, uncertified_order["id"])
        assert cancelled["execution_status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "REENTRY_RESTRICTION"
        assert cancelled["actual_labor_cost"] is None
        assert cancelled["payroll_status"] == "NOT_PAYABLE"

        survivor = fx.read_work_order(api, certified_order["id"])
        assert survivor["execution_status"] == "SCHEDULED"
        assert survivor["cancel_reason"] is None

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 2621.78, 12065.72,
                           "WITHIN_BUDGET")
