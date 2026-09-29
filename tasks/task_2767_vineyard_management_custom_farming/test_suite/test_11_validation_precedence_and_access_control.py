"""Identity, pagination, foreign-key order and the observable rejection ladder."""
from test_helpers import (
    MISSING_UUID_A,
    MISSING_UUID_C,
    ApiErrorId,
    assert_block_harvest_ledger,
    assert_crew,
    assert_delivery_window,
    assert_instant,
    assert_money,
    assert_pest_observation,
    assert_plan_ledger,
    assert_version,
    assert_vineyard,
    assert_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestIdentityPrecedesEverything:
    """PRD §2.1 — the two headers are inspected before the request is."""

    def test_a_read_without_the_user_id_header_is_unauthenticated(self, api):
        """If either header is absent, blank, or `X-User-Role` does not name one of the seven roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

        Design: Corner/validations/request_missing_x_user_id_header_rejected
        """
        s = fx.setup_ranch(api, name="Ridgecrest Ranch")

        headerless = {k: v for k, v in fx.VM.items() if k.lower() != "x-user-id"}
        assert headerless["X-User-Role"] == "VineyardManager"

        response = api.get_vineyard(s.vineyard["id"], headerless)
        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip() != ""

        data = validate_success(api.get_vineyard(s.vineyard["id"], fx.VM))
        assert_vineyard(data)
        assert data["id"] == s.vineyard["id"]
        assert data["name"] == "Ridgecrest Ranch"


class TestPaginationBand:
    """PRD §2.3 — the permitted page size is refused, never clamped."""

    def test_a_limit_of_one_hundred_and_one_is_refused_while_one_hundred_pages(self, api):
        """When `limit` is omitted it defaults to 10; supplied values must be integers no smaller than 1 and no larger than 100.

        Design: Corner/validations/block_list_limit_above_maximum_rejected
        """
        s = fx.setup_ranch_with_block(api)

        validate_error(
            api.list_blocks(fx.VM, {"vineyard_id": s.vineyard["id"],
                                    "limit": 101, "offset": 0}),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        response = api.list_blocks(fx.VM, {"vineyard_id": s.vineyard["id"],
                                           "limit": 100, "offset": 0})
        assert response.status_code == 200
        assert response.json()["response_type"] == "array"
        rows, meta = validate_paginated(response)
        assert len(rows) == 1
        assert rows[0]["id"] == s.block["id"]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestPayStructureCoherence:
    """PRD §2.6 — the piece rate is constrained in both directions."""

    def test_the_piece_rate_must_match_the_pay_structure_both_ways(self, api):
        """when registering a crew whose `pay_structure` is `PIECE_RATE`, `piece_rate_per_vine` must be greater than zero; when it is `HOURLY`, `piece_rate_per_vine` must be exactly zero. Either violation is `ERR_INVALID_REQUEST`.

        Design: Corner/validations/crew_hourly_with_nonzero_piece_rate_rejected
        """
        validate_error(
            api.create_crew(
                f.hourly_crew_payload(crew_name="Bad Hourly",
                                      piece_rate_per_vine=0.65,
                                      task_capabilities=["PRUNING"]),
                fx.VM,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        validate_error(
            api.create_crew(
                f.crew_payload(crew_name="Bad Piece", piece_rate_per_vine=0.0,
                               task_capabilities=["PRUNING"]),
                fx.VM,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        data = validate_success(
            api.create_crew(
                f.hourly_crew_payload(crew_name="Good Hourly",
                                      piece_rate_per_vine=0.0,
                                      task_capabilities=["PRUNING"]),
                fx.VM,
            ),
            201,
        )
        assert_crew(data)
        assert data["pay_structure"] == "HOURLY"
        assert_money(data["piece_rate_per_vine"], 0.0, "piece_rate_per_vine")
        assert data["crew_status"] == "ACTIVE"
        assert data["scheduled_work_order_count"] == 0


class TestPlanChargingIntegrity:
    """PRD §3.4 — a plan pays only for work on its own block."""

    def test_a_plan_cannot_be_charged_for_work_on_a_neighbouring_block(self, api):
        """The plan must belong to the very block named in the payload — a plan may not be charged for work on a different block — and a mismatch is `ERR_PLAN_BLOCK_MISMATCH`.

        Design: Corner/validations/work_order_charged_to_plan_of_another_block_rejected
        """
        s = fx.setup_approved_plan(api)
        assert_money(s.plan["total_budget"], 14687.50, "total_budget")
        b14 = fx.create_block_b14(api, s.vineyard["id"])
        crew = fx.create_crew(api)

        validate_error(
            api.create_work_order(
                f.work_order_payload(b14["id"], s.plan["id"], crew["id"],
                                     task_type="PRUNING",
                                     scheduled_start="2026-08-10T14:00:00Z",
                                     scheduled_end="2026-08-10T22:00:00Z",
                                     planned_vines=2000, planned_hours=8.0),
                fx.VM,
            ),
            ApiErrorId.ERR_PLAN_BLOCK_MISMATCH,
            409,
        )

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 0.00, 14687.50,
                           "WITHIN_BUDGET")
        assert fx.read_crew(api, crew["id"])["scheduled_work_order_count"] == 0


class TestCrewCapabilityGate:
    """PRD §3.4 — the capability list is checked against the requested task."""

    def test_a_crew_without_harvest_may_still_be_sent_pruning(self, api):
        """The crew must be `ACTIVE`, and the requested `task_type` must appear in that crew's `task_capabilities`, or `ERR_CREW_TASK_MISMATCH`.

        Design: Corner/validations/work_order_task_outside_crew_capabilities_rejected
        """
        s = fx.setup_operational_block(
            api,
            crew_overrides={"crew_name": "Cuadrilla Limitada",
                            "task_capabilities": ["PRUNING", "SUCKERING"]},
        )

        validate_error(
            api.create_work_order(
                f.work_order_payload(s.block["id"], s.plan["id"], s.crew["id"],
                                     task_type="HARVEST",
                                     scheduled_start="2026-09-14T14:00:00Z",
                                     scheduled_end="2026-09-14T22:00:00Z",
                                     planned_vines=3000, planned_hours=8.0),
                fx.VM,
            ),
            ApiErrorId.ERR_CREW_TASK_MISMATCH,
            409,
        )

        data = validate_success(
            api.create_work_order(
                f.work_order_payload(s.block["id"], s.plan["id"], s.crew["id"],
                                     task_type="PRUNING",
                                     scheduled_start="2026-09-14T14:00:00Z",
                                     scheduled_end="2026-09-14T22:00:00Z",
                                     planned_vines=3000, planned_hours=8.0),
                fx.VM,
            ),
            201,
        )
        assert_work_order(data)
        assert data["task_type"] == "PRUNING"
        assert data["execution_status"] == "SCHEDULED"
        assert_money(data["estimated_labor_cost"], 2505.75, "estimated_labor_cost")

        assert fx.read_crew(api, s.crew["id"])["scheduled_work_order_count"] == 1
        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 2505.75, 12181.75,
                           "WITHIN_BUDGET")


class TestForeignKeyResolutionOrder:
    """PRD §2.5 — body references resolve in a fixed order, not in serialisation order."""

    def test_an_unknown_block_is_reported_ahead_of_an_unknown_crew(self, api):
        """Because the order is fixed, a request naming both a non-existent block and a non-existent crew always reports the block.

        Design: Corner/validations/work_order_with_unknown_block_and_crew_returns_block_not_found
        """
        s = fx.setup_approved_plan(api)

        validate_error(
            api.create_work_order(
                f.work_order_payload(MISSING_UUID_A, s.plan["id"], MISSING_UUID_C,
                                     task_type="PRUNING",
                                     scheduled_start="2026-08-03T14:00:00Z",
                                     scheduled_end="2026-08-03T22:00:00Z",
                                     planned_vines=3000, planned_hours=8.0),
                fx.VM,
            ),
            ApiErrorId.ERR_BLOCK_NOT_FOUND,
            404,
        )

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 0.00, 14687.50,
                           "WITHIN_BUDGET")

        rows, meta = validate_paginated(
            api.list_work_orders(fx.CTL, {"farming_plan_id": s.plan["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_resolvable_block_and_plan_leave_the_crew_as_the_first_failure(self, api):
        """A body-supplied `vineyard_id` that does not resolve yields `ERR_VINEYARD_NOT_FOUND`; a `block_id` or `replaces_block_id` that does not resolve yields `ERR_BLOCK_NOT_FOUND`; a `farming_plan_id` yields `ERR_PLAN_NOT_FOUND`; a `crew_id` yields `ERR_CREW_NOT_FOUND`; a `delivery_window_id` yields `ERR_DELIVERY_WINDOW_NOT_FOUND`.

        Design: Corner/errors/unknown_crew_foreign_key_returns_crew_not_found
        """
        s = fx.setup_approved_plan(api)

        validate_error(
            api.create_work_order(
                f.work_order_payload(s.block["id"], s.plan["id"], MISSING_UUID_C,
                                     task_type="PRUNING",
                                     scheduled_start="2026-08-03T14:00:00Z",
                                     scheduled_end="2026-08-03T22:00:00Z",
                                     planned_vines=3000, planned_hours=8.0),
                fx.VM,
            ),
            ApiErrorId.ERR_CREW_NOT_FOUND,
            404,
        )

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 0.00, 14687.50,
                           "WITHIN_BUDGET")


class TestLogicalClock:
    """PRD §2.4 — the logical clock is the only time source."""

    def test_moving_the_clock_moves_the_next_observation_stamp(self, api):
        """The server's logical clock starts at exactly `2026-08-01T00:00:00Z` and stays there until a client moves it; it never falls back to the machine's real time. An administrative test-driving capability sets the clock to a supplied `current_utc` instant and is open to all seven roles.

        Design: Corner/endpoints/clock_set_endpoint_echoes_current_utc_and_drives_stamps
        """
        s = fx.setup_ranch_with_block(api)

        first = validate_success(
            api.create_pest_observation(
                s.block["id"],
                f.pest_observation_payload(incidence_pct=6.0, severity_index=2,
                                          scouting_note="First scouting round"),
                fx.AG,
            ),
            201,
        )
        assert_pest_observation(first)
        assert_instant(first["observed_at"], "2026-08-01T00:00:00Z", "observed_at")

        echo = validate_success(api.set_clock("2026-08-05T09:30:00Z", fx.AG))
        assert_instant(echo["current_utc"], "2026-08-05T09:30:00Z", "current_utc")

        second = validate_success(
            api.create_pest_observation(
                s.block["id"],
                f.pest_observation_payload(incidence_pct=9.0, severity_index=3,
                                          scouting_note="Second scouting round"),
                fx.AG,
            ),
            201,
        )
        assert_pest_observation(second)
        assert_instant(second["observed_at"], "2026-08-05T09:30:00Z", "observed_at")
        assert second["severity_index"] == 3


class TestRanchRegistrationAuthority:
    """PRD §2.1 — registering a client ranch is one role's privilege."""

    def test_only_the_vineyard_manager_may_register_a_client_ranch(self, api):
        """When the headers are well-formed but the named role is not authorised for the endpoint being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

        Design: Corner/rbac/agronomist_cannot_create_a_vineyard
        """
        validate_error(
            api.create_vineyard(f.vineyard_payload(), fx.AG),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        data = validate_success(api.create_vineyard(f.vineyard_payload(), fx.VM), 201)
        assert_vineyard(data)
        assert data["block_count"] == 0
        assert_money(data["managed_acres"], 0.00, "managed_acres")
        assert_version(data, 1, "vineyard")

        rows, meta = validate_paginated(api.list_blocks(fx.VM))
        assert rows == []
        assert meta["total_count"] == 0


def _b14_with_a_draft_plan(api):
    """A 4.0-acre B-14 block, an ACTIVE agreement and a DRAFT plan of 1,028.00.

    The 6-by-10-foot spacing gives 726 vines per acre and a frozen vine count of
    2,904, and the four per-acre lines of 100.00 / 60.00 / 37.00 / 60.00 come to
    257.00 an acre.
    """
    s = fx.setup_approved_plan(
        api,
        contracted_acres=4.0,
        block_overrides={"block_code": "B-14", "variety": "CHARDONNAY",
                         "clone": "FPS-04", "rootstock": "ROOTSTOCK_110R",
                         "trellis_system": "SPRAWL", "planting_year": 2020,
                         "vine_spacing_ft": 6.0, "row_spacing_ft": 10.0,
                         "acres": 4.0},
        plan_overrides={"pruning_budget_per_acre": 100.00,
                        "canopy_budget_per_acre": 60.00,
                        "irrigation_budget_per_acre": 37.00,
                        "pest_budget_per_acre": 60.00},
        submit=False,
    )
    s.crew = fx.create_hourly_crew(api, crew_name="Cuadrilla Unipersonal",
                                   crew_size=1, base_hourly_rate=100.00)
    return s


def _twelve_hour_pruning_order(block_id, plan_id, crew_id):
    """One worker for twelve hours — eight regular and four overtime."""
    return f.work_order_payload(block_id, plan_id, crew_id,
                                task_type="PRUNING",
                                scheduled_start="2026-08-06T06:00:00Z",
                                scheduled_end="2026-08-06T18:00:00Z",
                                planned_vines=2900, planned_hours=12.0)


class TestPlanLifecycleBeatsTheBudget:
    """PRD §2.6 — the plan's state is read before its wallet."""

    def test_a_draft_plan_reports_its_state_not_its_budget(self, api):
        """Several coherence rules bite here. The cited plan must be `APPROVED`, or `ERR_PLAN_NOT_APPROVED`.

        Design: Difficulty/priority_pair_validation_conflict/plan_not_approved_beats_budget_exceeded_on_work_order_create
        """
        s = _b14_with_a_draft_plan(api)
        assert s.plan["plan_status"] == "DRAFT"
        assert_money(s.plan["total_budget"], 1028.00, "total_budget")
        assert fx.read_block(api, s.block["id"])["vine_count"] == 2904

        validate_error(
            api.create_work_order(
                _twelve_hour_pruning_order(s.block["id"], s.plan["id"], s.crew["id"]),
                fx.VM,
            ),
            ApiErrorId.ERR_PLAN_NOT_APPROVED,
            409,
        )

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 0.00, 1028.00,
                           "WITHIN_BUDGET")
        assert fx.read_crew(api, s.crew["id"])["scheduled_work_order_count"] == 0

    def test_the_identical_body_reports_the_budget_once_the_plan_is_approved(self, api):
        """Only after the calendar is clear does the budget gate run: the plan's current `committed_cost` plus this order's freshly computed `estimated_labor_cost`, rounded to two decimal places, must not exceed the plan's `total_budget`.

        Design: Difficulty/priority_pair_validation_conflict/plan_not_approved_beats_budget_exceeded_on_work_order_create
        """
        s = _b14_with_a_draft_plan(api)
        s.plan = fx.submit_farming_plan(api, s.plan["id"])
        s.plan = fx.approve_farming_plan(api, s.plan["id"])
        assert s.plan["plan_status"] == "APPROVED"

        validate_error(
            api.create_work_order(
                _twelve_hour_pruning_order(s.block["id"], s.plan["id"], s.crew["id"]),
                fx.VM,
            ),
            ApiErrorId.ERR_PLAN_BUDGET_EXCEEDED,
            409,
        )

        assert_plan_ledger(fx.read_plan(api, s.plan["id"]), 0.00, 1028.00,
                           "WITHIN_BUDGET")
        assert fx.read_crew(api, s.crew["id"])["scheduled_work_order_count"] == 0

        roomier = fx.setup_approved_plan(api)
        accepted = validate_success(
            api.create_work_order(
                _twelve_hour_pruning_order(roomier.block["id"], roomier.plan["id"],
                                           s.crew["id"]),
                fx.VM,
            ),
            201,
        )
        assert_work_order(accepted)
        assert_money(accepted["estimated_labor_cost"], 1799.00,
                     "estimated_labor_cost")
        assert accepted["estimated_labor_cost"] > 1028.00


def _sprayed_block_without_an_estimate(api):
    """An applied spray at the epoch, no yield estimate, and two windows.

    The 72-hour re-entry and 21-day pre-harvest product logged at
    2026-08-01T00:00:00Z clears the block for picking at 2026-08-22T00:00:00Z,
    which sits between the two windows.
    """
    s = fx.setup_operational_block(api)
    s = fx.setup_applied_spray(api, s)
    s.window_early = fx.create_delivery_window(
        api, winery_name="Coastal Cellars",
        window_start="2026-08-20T06:00:00Z", window_end="2026-08-20T18:00:00Z",
        capacity_tons=40.00)
    s.window_late = fx.create_delivery_window(
        api, winery_name="Coastal Cellars",
        window_start="2026-08-25T06:00:00Z", window_end="2026-08-25T18:00:00Z",
        capacity_tons=40.00)
    return s


class TestSafetyBeatsReferentialCompleteness:
    """PRD §2.6 — the pre-harvest interval is read before the estimate file."""

    def test_an_arrival_before_the_block_clears_reports_the_interval(self, api):
        """Pre-harvest compliance is checked against the planned arrival rather than the present moment: the `delivery_eta` must be at or after the block's `phi_clear_at`, and an earlier arrival is refused with `ERR_PREHARVEST_INTERVAL_ACTIVE`; a null `phi_clear_at` imposes no restriction.

        Design: Difficulty/priority_pair_validation_conflict/preharvest_interval_beats_no_yield_estimate_on_harvest_load_create
        """
        s = _sprayed_block_without_an_estimate(api)
        block = fx.read_block(api, s.block["id"])
        assert_instant(block["phi_clear_at"], "2026-08-22T00:00:00Z", "phi_clear_at")
        assert block["harvest_posture"] == "NOT_ESTIMATED"

        validate_error(
            api.create_harvest_load(
                f.harvest_load_payload(s.block["id"], s.crew["id"],
                                       s.window_early["id"],
                                       fx.window_version(api, s.window_early["id"]),
                                       estimated_tons=10.00,
                                       delivery_eta="2026-08-20T09:00:00Z"),
                fx.VM,
            ),
            ApiErrorId.ERR_PREHARVEST_INTERVAL_ACTIVE,
            409,
        )

        early = fx.read_delivery_window(api, s.window_early["id"])
        assert_delivery_window(early)
        assert_money(early["committed_tons"], 0.00, "committed_tons")
        assert_money(early["remaining_tons"], 40.00, "remaining_tons")
        assert early["window_posture"] == "OPEN"
        assert_block_harvest_ledger(fx.read_block(api, s.block["id"]),
                                    0.00, 0.00, 0.00, 0.00, "NOT_ESTIMATED")

    def test_a_later_arrival_on_the_same_block_reports_the_missing_estimate(self, api):
        """The block must also have at least one yield estimate on file — a `harvest_posture` of `NOT_ESTIMATED` is refused with `ERR_NO_YIELD_ESTIMATE` — and the picking crew's `task_capabilities` must include `HARVEST`, or `ERR_CREW_TASK_MISMATCH`.

        Design: Difficulty/priority_pair_validation_conflict/preharvest_interval_beats_no_yield_estimate_on_harvest_load_create
        """
        s = _sprayed_block_without_an_estimate(api)
        assert "HARVEST" in s.crew["task_capabilities"]

        validate_error(
            api.create_harvest_load(
                f.harvest_load_payload(s.block["id"], s.crew["id"],
                                       s.window_late["id"],
                                       fx.window_version(api, s.window_late["id"]),
                                       estimated_tons=10.00,
                                       delivery_eta="2026-08-25T09:00:00Z"),
                fx.VM,
            ),
            ApiErrorId.ERR_NO_YIELD_ESTIMATE,
            409,
        )

        late = fx.read_delivery_window(api, s.window_late["id"])
        assert_delivery_window(late)
        assert_money(late["committed_tons"], 0.00, "committed_tons")
        assert_money(late["remaining_tons"], 40.00, "remaining_tons")
        assert late["window_posture"] == "OPEN"
        assert_version(late, 1, "delivery window")


def _nearly_full_ten_ton_window(api):
    """A ten-ton slot already carrying one nine-ton `PLANNED` load."""
    s = fx.setup_harvest_ready(api, capacity_tons=10.00)
    s = fx.setup_booked_load(api, s, estimated_tons=9.00)
    s.window = fx.read_delivery_window(api, s.window["id"])
    assert_money(s.window["committed_tons"], 9.00, "committed_tons")
    assert_money(s.window["remaining_tons"], 1.00, "remaining_tons")
    assert s.window["window_posture"] == "NEARLY_FULL"
    return s


class TestContainmentBeatsCapacity:
    """PRD §2.6 — arrival time is judged before the slot's tonnage."""

    def test_an_arrival_past_the_close_reports_containment_not_capacity(self, api):
        """Rejections are not evaluated in an arbitrary order, and the order is observable: exactly one error is reported per request, and it is the first one that fails in the ladder below. Later checks are never reached, so a request that violates three rules always reports the earliest of them.

        Design: Difficulty/priority_pair_validation_conflict/delivery_eta_outside_window_beats_window_capacity_exceeded
        """
        s = _nearly_full_ten_ton_window(api)

        validate_error(
            api.create_harvest_load(
                f.harvest_load_payload(s.block["id"], s.crew["id"], s.window["id"],
                                       fx.window_version(api, s.window["id"]),
                                       estimated_tons=5.00,
                                       delivery_eta="2026-09-14T19:00:00Z"),
                fx.VM,
            ),
            ApiErrorId.ERR_DELIVERY_ETA_OUTSIDE_WINDOW,
            409,
        )

        window = fx.read_delivery_window(api, s.window["id"])
        assert_delivery_window(window)
        assert_money(window["committed_tons"], 9.00, "committed_tons")
        assert_money(window["remaining_tons"], 1.00, "remaining_tons")
        assert window["window_posture"] == "NEARLY_FULL"
        assert_version(window, 2, "delivery window")

    def test_an_arrival_exactly_at_the_close_reports_the_tonnage_ceiling(self, api):
        """Two ceilings then close the booking out, in this order. The window's tonnage ceiling requires that the window's current `committed_tons` plus the new `estimated_tons`, rounded to two decimal places, not exceed its `capacity_tons`; equality is permitted, and anything above is refused with `ERR_WINDOW_CAPACITY_EXCEEDED`.

        Design: Difficulty/priority_pair_validation_conflict/delivery_eta_outside_window_beats_window_capacity_exceeded
        """
        s = _nearly_full_ten_ton_window(api)

        validate_error(
            api.create_harvest_load(
                f.harvest_load_payload(s.block["id"], s.crew["id"], s.window["id"],
                                       fx.window_version(api, s.window["id"]),
                                       estimated_tons=5.00,
                                       delivery_eta="2026-09-14T18:00:00Z"),
                fx.VM,
            ),
            ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED,
            409,
        )

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 9.00, "committed_tons")
        assert_money(window["remaining_tons"], 1.00, "remaining_tons")
        assert window["window_posture"] == "NEARLY_FULL"

        rows, meta = validate_paginated(
            api.list_harvest_loads(fx.VM, {"delivery_window_id": s.window["id"]})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == s.load["id"]
        assert rows[0]["load_status"] == "PLANNED"
