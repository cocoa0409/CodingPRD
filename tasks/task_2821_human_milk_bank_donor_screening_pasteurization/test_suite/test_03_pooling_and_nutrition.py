"""Pool construction: donor spread, the volume-weighted nutrition projection,
the ten-rule draw ladder, the four commit constraints and the scrap compensation.

Every pool in this module is built from containers logged against accepted
coolers, because that is the only documented way milk reaches a pool. The
logical clock is nudged forward between two draws wherever a test asserts the
`created_at` ascending order of a component list, so that the two rows carry
distinguishable stamps rather than relying on a tie-break the contract leaves to
the primary key.
"""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    QA_OFFICER_HEADERS,
    TECHNICIAN_HEADERS,
    TECHNICIAN_ID,
)
from test_helpers.types import (
    ComponentStatus,
    DeferralReason,
    DeferralType,
    DonationStatus,
    DonorStatus,
    MilkClass,
    PoolStatus,
    RecallScope,
    RunStatus,
    TargetMilkClass,
)

CLOCK = C.CLOCK_INTAKE
CLOCK_DATE = C.CLOCK_INTAKE_DATE

# The first pool's three containers average to exactly 21.00 kcal/oz, the closed
# upper bound. The second pool's three containers average to 21.005 kcal/oz,
# which is inside the bound before rounding and outside it after.
BOUNDARY_CONTAINERS = ((700, 20.0), (700, 21.0), (700, 22.0))
OVER_BOUNDARY_CONTAINERS = ((650, 24.0), (650, 24.8), (700, 14.7))


def _qualified_donor(index):
    """One qualified donor built from the shared enrolment spec."""
    spec = fx.donor_spec(index)
    return fx.qualified_donor(
        donor_code=spec["donor_code"],
        full_name=spec["full_name"],
        email=spec["email"],
        zone_code=spec["zone_code"],
        collected_on=spec["collected_on"],
        physician_npi=spec["physician_npi"],
        approved_on=spec["approved_on"],
    )


def _bank_at_the_nutrition_boundary():
    """Three donors, each shipping a two-container cooler, and two TERM pools:
    the first drawn to exactly 21.00 kcal/oz, the second to 21.005."""
    fx.set_clock(CLOCK)
    first_set = []
    second_set = []
    for index in range(1, 4):
        first_volume, first_kcal = BOUNDARY_CONTAINERS[index - 1]
        second_volume, second_kcal = OVER_BOUNDARY_CONTAINERS[index - 1]
        donor = _qualified_donor(index)
        cooler = fx.accepted_cooler(
            donor["id"],
            tracking_code=f"TRK-{index:04d}",
            container_count=2,
            declared_volume_ml=first_volume + second_volume,
        )
        first_set.append(
            fx.log_container(
                cooler["id"],
                container_label=f"A{index}",
                volume_ml=first_volume,
                kcal_per_oz=first_kcal,
            )
        )
        second_set.append(
            fx.log_container(
                cooler["id"],
                container_label=f"B{index}",
                volume_ml=second_volume,
                kcal_per_oz=second_kcal,
            )
        )

    on_bound = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)
    for donation, (volume, _) in zip(first_set, BOUNDARY_CONTAINERS):
        fx.draw_component(on_bound["id"], donation["id"], volume)

    over_bound = fx.open_pool(pool_code="POOL-0002", target_milk_class=TargetMilkClass.TERM)
    for donation, (volume, _) in zip(second_set, OVER_BOUNDARY_CONTAINERS):
        fx.draw_component(over_bound["id"], donation["id"], volume)

    return fx.get_pool(on_bound["id"]), fx.get_pool(over_bound["id"])


class TestPoolNutritionClosedUpperBound:
    """The nutrition constraint is a closed range, and the projection that is
    compared against it has already been rounded half up to two decimals."""

    def test_a_projection_of_exactly_21_00_passes_the_closed_upper_bound(self):
        """700 ml at 20.0, 700 ml at 21.0 and 700 ml at 22.0 average to exactly
        21.00 kcal/oz, which sits on the upper bound and therefore commits.

        PRD: "A pool is balanced when all three conditions hold at once: its `distinct_donor_count` is at least 3, its `projected_kcal_per_oz` lies inside the **closed** range from 19.00 through 21.00, and its `total_volume_ml` lies inside the **closed** range from 1500 through 6000 millilitres."
        PRD: "On success the pool moves `BALANCED → COMMITTED`, `committed_at` is stamped with the clock instant, `committed_by_user_id` with the acting technician's `X-User-ID`, and the pool's `version` increases by 1."

        Design: Difficulty/boundary_precision_check/pool_nutrition_closed_upper_bound_21_00
        """
        on_bound, _over_bound = _bank_at_the_nutrition_boundary()

        assert on_bound["projected_kcal_per_oz"] == A.expected_projected_kcal(
            BOUNDARY_CONTAINERS
        ) == 21.0
        assert on_bound["total_volume_ml"] == 2100
        assert on_bound["distinct_donor_count"] == 3
        assert on_bound["status"] == PoolStatus.BALANCED
        assert A.is_balanced(3, 21.0, 2100) is True

        committed = validate_success(api_client.commit_pool(on_bound["id"], TECHNICIAN_HEADERS))
        A.assert_pool(
            committed,
            status=PoolStatus.COMMITTED,
            projected_kcal_per_oz=21.0,
            total_volume_ml=2100,
            distinct_donor_count=3,
            committed_by_user_id=TECHNICIAN_ID,
            version=5,
        )
        A.assert_instant_equals(committed["committed_at"], CLOCK, "committed_at")

    def test_a_projection_that_rounds_half_up_to_21_02_is_refused_at_commit(self):
        """650 ml at 24.0, 650 ml at 24.8 and 700 ml at 14.7 average to 21.005
        kcal/oz. That exact quotient is inside the closed range, but the stored
        projection is the quotient rounded half up to two places, so the commit
        is refused — truncating to 21.00 would let the batch through.

        PRD: "`projected_kcal_per_oz` is the volume-weighted average caloric density — multiply each counted component's `allocated_volume_ml` by its `component_kcal_per_oz`, sum those products at exact decimal precision with no intermediate rounding, divide that sum by `total_volume_ml`, and round the single quotient half up to two decimal places."
        PRD: "The four constraints are then evaluated in the fixed order of §2.10: the pool must hold at least one `ALLOCATED` component (`ERR_POOL_EMPTY`); its `distinct_donor_count` must be at least 3 (`ERR_POOL_DONOR_COUNT_INSUFFICIENT`) and, as the add-time cap already guarantees, no more than 5; its `projected_kcal_per_oz` must lie in the closed range 19.00 through 21.00, where exactly 19.00 and exactly 21.00 both pass (`ERR_POOL_NUTRITION_OUT_OF_RANGE`); and its `total_volume_ml` must lie in the closed range 1500 through 6000 (`ERR_POOL_VOLUME_OUT_OF_RANGE`)."

        Design: Difficulty/boundary_precision_check/pool_nutrition_closed_upper_bound_21_00
        """
        _on_bound, over_bound = _bank_at_the_nutrition_boundary()

        weighted = sum(
            Decimal(volume) * Decimal(str(kcal)) for volume, kcal in OVER_BOUNDARY_CONTAINERS
        )
        total_volume = sum(volume for volume, _ in OVER_BOUNDARY_CONTAINERS)
        exact_quotient = weighted / Decimal(total_volume)
        assert exact_quotient == Decimal("21.005")
        assert exact_quotient <= Decimal(str(C.POOL_KCAL_MAX)) + Decimal("0.005")

        assert over_bound["total_volume_ml"] == 2000
        assert over_bound["distinct_donor_count"] == 3
        assert over_bound["projected_kcal_per_oz"] == A.expected_projected_kcal(
            OVER_BOUNDARY_CONTAINERS
        ) == 21.01
        assert Decimal(str(over_bound["projected_kcal_per_oz"])) > Decimal(str(C.POOL_KCAL_MAX))
        assert over_bound["status"] == PoolStatus.DRAFT

        validate_error(
            api_client.commit_pool(over_bound["id"], TECHNICIAN_HEADERS),
            ApiErrorId.POOL_NUTRITION_OUT_OF_RANGE.value,
            409,
        )

        after = fx.get_pool(over_bound["id"])
        assert after["status"] == PoolStatus.DRAFT
        assert after["committed_at"] is None
        assert after["committed_by_user_id"] is None
        assert after["version"] == 4


def _draft_pool_and_a_deferred_donors_container():
    """One 800 ml eligible container whose donor was permanently deferred after
    the milk was logged, plus an empty TERM pool to draw it into."""
    fx.set_clock(CLOCK)
    bank = fx.donor_with_donation(index=1, volume_ml=800, kcal_per_oz=20.0)
    fx.record_deferral(
        bank.donor["id"],
        reason_code=DeferralReason.PHYSICIAN_WITHDRAWAL,
        deferral_type=DeferralType.PERMANENT,
        effective_from=CLOCK_DATE,
        deferral_days=0,
        lookback_days=0,
        recall_scope=RecallScope.NONE,
    )
    pool = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)
    return bank, pool


class TestSafetyOutranksArithmeticOnADraw:
    """A draw that is both unsafe and over-sized reports the safety failure,
    because the donor-qualification rule is evaluated before the volume rule."""

    def test_a_deferred_donor_is_reported_before_the_over_sized_allocation(self):
        """The container holds 800 ml and the draw asks for 1200 ml, so the
        arithmetic rule is violated too — yet the answer names the donor.

        PRD: "**Adding a component to a pool** enforces, after existence and shape: the donation's own eligibility (`ERR_DONATION_STATE_INVALID`), then the pool's state gate (`ERR_POOL_STATE_INVALID`), then the concurrency token (`ERR_STALE_VERSION`), then the donor's qualification (`ERR_DONOR_NOT_QUALIFIED`), then the deferral-window overlap (`ERR_DONATION_IN_DEFERRAL_WINDOW`), then the raw-milk age ceiling (`ERR_DONOR_MILK_AGE_EXCEEDED`), then nutritional-class compatibility (`ERR_MILK_CLASS_MISMATCH`), then the single-pool exclusivity rule (`ERR_COMPONENT_ALREADY_ALLOCATED`), then the donation's unallocated volume (`ERR_ALLOCATION_EXCEEDS_DONATION_REMAINING`), and last the pool's donor ceiling (`ERR_POOL_DONOR_CAP_EXCEEDED`)."
        PRD: "The donation's owning donor must still be `QUALIFIED`, or the draw is `ERR_DONOR_NOT_QUALIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_over_constraint_on_component_add
        """
        bank, pool = _draft_pool_and_a_deferred_donors_container()

        donor = fx.get_donor(bank.donor["id"])
        assert donor["status"] == DonorStatus.PERMANENTLY_DEFERRED
        donation = fx.get_donation(bank.donation["id"])
        assert donation["status"] == DonationStatus.ELIGIBLE
        assert donation["remaining_ml"] == 800

        body = validate_error(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(bank.donation["id"], 1200, pool["version"]),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.DONOR_NOT_QUALIFIED.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.ALLOCATION_EXCEEDS_DONATION_REMAINING.value

    def test_the_doubly_invalid_draw_leaves_no_partial_write_behind(self):
        """The pool keeps its opening aggregates and the container keeps all
        800 millilitres, because a rejected request writes nothing.

        PRD: "The service evaluates the applicable checks in the sequence below, and the **first** check that fails determines the response; no later check runs, and no partial write survives a rejection."
        PRD: "A new pool is `DRAFT` at `version` 1 with `distinct_donor_count` 0, `total_volume_ml` 0, `projected_kcal_per_oz` null, `bottled_volume_ml` 0, and null `committed_at` and `committed_by_user_id`."

        Design: Difficulty/priority_pair_validation_conflict/safety_over_constraint_on_component_add
        """
        bank, pool = _draft_pool_and_a_deferred_donors_container()

        validate_error(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(bank.donation["id"], 1200, pool["version"]),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.DONOR_NOT_QUALIFIED.value,
            409,
        )

        after = fx.get_pool(pool["id"])
        A.assert_pool(
            after,
            status=PoolStatus.DRAFT,
            total_volume_ml=0,
            distinct_donor_count=0,
            projected_kcal_per_oz=None,
            bottled_volume_ml=0,
            committed_at=None,
            committed_by_user_id=None,
            version=1,
        )
        rows, meta = validate_paginated(
            api_client.list_pool_components(pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 0
        assert rows == []

        donation = fx.get_donation(bank.donation["id"])
        assert donation["status"] == DonationStatus.ELIGIBLE
        assert donation["remaining_ml"] == 800
        assert fx.get_donor(bank.donor["id"])["status"] == DonorStatus.PERMANENTLY_DEFERRED


def _committed_pool_with_a_scheduled_run():
    """The canonical 800 / 700 / 600 ml pool, committed, with one SCHEDULED run
    holding a pasteurizer interval and no readings yet."""
    chain = fx.build_chain()
    fx.set_clock("2026-08-10T08:00:00Z")
    run = fx.schedule_run(
        chain.pool["id"],
        scheduled_start_at="2026-08-10T09:00:00Z",
        cycle_minutes=60,
    )
    return chain, run


class TestMillilitreConservationAcrossAScrap:
    """Scrapping is the compensating action for a pool, and the millilitres it
    returns must be exactly the millilitres it took."""

    def test_the_scrap_credits_back_every_millilitre_it_had_taken(self):
        """2100 millilitres were drawn into the pool; after the scrap the three
        containers hold 800, 700 and 600 again and the components are VOIDED.

        PRD: "Every component still `ALLOCATED` becomes `VOIDED`; each affected donation has the voided `allocated_volume_ml` credited back to its `remaining_ml` and, unless it has been recalled, returns from `ALLOCATED` to `ELIGIBLE`, so a container can be allocated, released and re-allocated to a different pool without any volume drift."
        PRD: "The pool's three aggregates are recomputed, with `projected_kcal_per_oz` falling to null when no component remains."

        Design: Difficulty/compensating_invariant/milk_volume_conservation_across_pool_scrap_and_reallocation
        """
        chain, _run = _committed_pool_with_a_scheduled_run()
        drawn = [800, 700, 600]
        assert chain.pool["total_volume_ml"] == sum(drawn) == 2100

        fx.scrap_pool(chain.pool["id"], QA_OFFICER_HEADERS)

        scrapped = fx.get_pool(chain.pool["id"])
        A.assert_pool(
            scrapped,
            status=PoolStatus.SCRAPPED,
            total_volume_ml=0,
            distinct_donor_count=0,
            projected_kcal_per_oz=None,
        )

        rows, meta = validate_paginated(
            api_client.list_pool_components(chain.pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 3
        assert [row["status"] for row in rows] == [ComponentStatus.VOIDED] * 3

        donations = [fx.get_donation(donation["id"]) for donation in chain.donations]
        assert [donation["remaining_ml"] for donation in donations] == drawn
        assert [donation["status"] for donation in donations] == [DonationStatus.ELIGIBLE] * 3

        held_in_components = sum(
            row["allocated_volume_ml"] for row in rows if row["status"] != ComponentStatus.VOIDED
        )
        assert sum(d["remaining_ml"] for d in donations) + held_in_components == 2100
        A.assert_volume_conservation(donations, rows)

    def test_the_returned_volume_is_re_allocable_in_full_and_frees_the_run(self):
        """The whole 800 ml goes straight into a new pool, which proves not one
        millilitre was lost, and the scrapped pool's SCHEDULED run is voided
        while its commit audit trail survives.

        PRD: "Any `PasteurizationRun` of that pool whose `run_status` is `SCHEDULED` or `IN_PROGRESS` moves to `VOIDED`, which frees its occupied interval on the pasteurizer so a later run may take the slot."
        PRD: "The donation advances `ELIGIBLE → ALLOCATED` **only** when the debit brings its `remaining_ml` to exactly 0; a partially drawn container stays `ELIGIBLE` and remains available for a further draw."

        Design: Difficulty/compensating_invariant/milk_volume_conservation_across_pool_scrap_and_reallocation
        """
        chain, run = _committed_pool_with_a_scheduled_run()
        assert run["run_status"] == RunStatus.SCHEDULED

        fx.scrap_pool(chain.pool["id"], QA_OFFICER_HEADERS)

        assert fx.get_run(run["id"])["run_status"] == RunStatus.VOIDED

        scrapped = fx.get_pool(chain.pool["id"])
        A.assert_instant_equals(scrapped["committed_at"], CLOCK, "committed_at")
        assert scrapped["committed_by_user_id"] == TECHNICIAN_ID

        rebuilt = fx.open_pool(pool_code="POOL-0002", target_milk_class=TargetMilkClass.TERM)
        component = validate_success(
            api_client.add_pool_component(
                rebuilt["id"],
                f.pool_component(chain.donations[0]["id"], 800, rebuilt["version"]),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        A.assert_pool_component(
            component,
            donation_id=chain.donations[0]["id"],
            allocated_volume_ml=800,
            component_kcal_per_oz=18.5,
            status=ComponentStatus.ALLOCATED,
        )

        A.assert_pool(
            fx.get_pool(rebuilt["id"]),
            total_volume_ml=800,
            distinct_donor_count=1,
            projected_kcal_per_oz=18.5,
        )
        reallocated = fx.get_donation(chain.donations[0]["id"])
        assert reallocated["remaining_ml"] == 0
        assert reallocated["status"] == DonationStatus.ALLOCATED


class TestPoolComponentReferenceResolution:
    """A draw names one identifier in the path and one in the body, and both are
    resolved before any shape or business rule runs."""

    def test_an_unknown_donation_and_an_unknown_pool_both_report_not_found(self):
        """The body foreign key is resolved after the path parameter, so a draw
        that names a missing container and a draw that names a missing pool both
        answer with the same not-found identifier and change nothing.

        PRD: "Existence resolution in step 5 runs **left to right**: path parameters first, in the order they appear in the path, and then body foreign keys in the order the endpoint declares its input fields."
        PRD: "A request for a component of a pool that does not exist therefore reports the missing pool, never the missing donation."

        Design: Corner/entities/pool_component_unknown_donation_fk_is_checked_after_path_param
        """
        fx.set_clock(CLOCK)
        pool = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)
        missing_donation = "22222222-2222-4222-8222-222222222222"
        missing_pool = "33333333-3333-4333-8333-333333333333"

        validate_error(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(missing_donation, 400, pool["version"]),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.RESOURCE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.add_pool_component(
                missing_pool,
                f.pool_component(missing_donation, 400, 1),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.RESOURCE_NOT_FOUND.value,
            404,
        )

        A.assert_pool(
            fx.get_pool(pool["id"]),
            status=PoolStatus.DRAFT,
            total_volume_ml=0,
            projected_kcal_per_oz=None,
            version=1,
        )
        _rows, meta = validate_paginated(
            api_client.list_pool_components(pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 0


class TestPoolOpeningSurface:
    """Opening a pool writes a counter and a set of empty aggregates."""

    def test_a_new_pool_is_draft_with_a_sequence_and_zeroed_metrics(self):
        """The first pool of the bank takes `pool_sequence` 1 and carries no
        volume, no donors, no projection and no commit stamps.

        PRD: "The server assigns the pool a `pool_sequence`, a monotonic 1-based counter equal to 1 plus the number of pools that already exist — it is assigned in pool-creation order, is never derived from the pool's `id`, and later reappears in the middle segment of every lot code bottled from this pool."
        PRD: "A new pool is `DRAFT` at `version` 1 with `distinct_donor_count` 0, `total_volume_ml` 0, `projected_kcal_per_oz` null, `bottled_volume_ml` 0, and null `committed_at` and `committed_by_user_id`."

        Design: Corner/state_machines/pool_initial_state_is_draft_with_zero_metrics
        """
        fx.set_clock(CLOCK)
        response = api_client.create_pool(
            f.pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM),
            TECHNICIAN_HEADERS,
        )
        assert response.json()["response_type"] == "object"
        pool = validate_success(response, 201)

        A.assert_pool(
            pool,
            pool_code="POOL-0001",
            target_milk_class=TargetMilkClass.TERM,
            pool_sequence=1,
            status=PoolStatus.DRAFT,
            distinct_donor_count=0,
            total_volume_ml=0,
            projected_kcal_per_oz=None,
            bottled_volume_ml=0,
            committed_at=None,
            committed_by_user_id=None,
            version=1,
        )


class TestBalanceOscillates:
    """Balance is re-derived after every draw, in both directions."""

    def test_a_fourth_rich_container_pushes_a_balanced_pool_back_to_draft(self):
        """Three 700 ml containers at 20.0 kcal/oz balance the pool; a fourth at
        26.0 lifts the projection to 21.50 and the pool falls back to DRAFT even
        though its volume and donor spread both improved.

        PRD: "A `DRAFT` pool that satisfies all three moves `DRAFT → BALANCED`; a `BALANCED` pool whose newest component pushes any one of the three back outside its range moves `BALANCED → DRAFT`."
        PRD: "The pool oscillates between the two as freely as the technician adds milk, so eligibility to commit is never monotonic."

        Design: Corner/state_machines/pool_returns_to_draft_when_a_fourth_component_breaks_nutrition
        """
        fx.set_clock(CLOCK)
        banks = [
            fx.donor_with_donation(
                index=index, volume_ml=700, kcal_per_oz=kcal, expressed_on="2026-07-10"
            )
            for index, kcal in enumerate((20.0, 20.0, 20.0, 26.0), start=1)
        ]
        pool = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)
        for bank in banks[:3]:
            fx.draw_component(pool["id"], bank.donation["id"], 700)

        balanced = fx.get_pool(pool["id"])
        A.assert_pool(
            balanced,
            status=PoolStatus.BALANCED,
            total_volume_ml=2100,
            distinct_donor_count=3,
            projected_kcal_per_oz=20.0,
        )

        fx.draw_component(pool["id"], banks[3].donation["id"], 700)

        unbalanced = fx.get_pool(pool["id"])
        A.assert_pool(
            unbalanced,
            status=PoolStatus.DRAFT,
            total_volume_ml=2800,
            distinct_donor_count=4,
            projected_kcal_per_oz=21.5,
        )
        assert A.is_balanced(4, 21.5, 2800) is False

        rows, meta = validate_paginated(
            api_client.list_pool_components(pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 4
        assert [row["status"] for row in rows] == [ComponentStatus.ALLOCATED] * 4

        fourth = fx.get_donation(banks[3].donation["id"])
        assert fourth["remaining_ml"] == 0
        assert fourth["status"] == DonationStatus.ALLOCATED


# 800 ml at 18.5, 700 ml at 20.0 and 600 ml at 22.5 kcal/oz.
CANONICAL_DRAWS = ((800, 18.5, "2026-07-05"), (700, 20.0, "2026-07-10"), (600, 22.5, "2026-07-12"))


def _canonical_term_pool():
    """Three donors' whole containers drawn into one TERM pool, each draw an
    hour after the last so the component rows carry distinguishable stamps."""
    fx.set_clock(CLOCK)
    banks = [
        fx.donor_with_donation(
            index=index, volume_ml=volume, kcal_per_oz=kcal, expressed_on=expressed
        )
        for index, (volume, kcal, expressed) in enumerate(CANONICAL_DRAWS, start=1)
    ]
    pool = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)
    for step, (bank, draw) in enumerate(zip(banks, CANONICAL_DRAWS)):
        if step:
            fx.set_clock(f"2026-08-05T{8 + step:02d}:00:00Z")
        fx.draw_component(pool["id"], bank.donation["id"], draw[0])
    return banks, fx.get_pool(pool["id"])


class TestWeightedNutritionProjection:
    """The projection is one division of exactly summed products, rounded once."""

    def test_the_weighted_average_is_rounded_half_up_to_two_decimals(self):
        """42300 kcal-millilitres over 2100 millilitres is 20.142857…, which the
        pool stores as 20.14, and the component list reads back in draw order.

        PRD: "`projected_kcal_per_oz` is the volume-weighted average caloric density — multiply each counted component's `allocated_volume_ml` by its `component_kcal_per_oz`, sum those products at exact decimal precision with no intermediate rounding, divide that sum by `total_volume_ml`, and round the single quotient half up to two decimal places."
        PRD: "Pool components, whether listed by pool or by donation: `created_at` ascending."

        Design: Corner/calculations/pool_kcal_weighted_average_rounds_half_up_to_two_decimals
        """
        _banks, pool = _canonical_term_pool()

        weighted = sum(Decimal(volume) * Decimal(str(kcal)) for volume, kcal, _ in CANONICAL_DRAWS)
        assert weighted == Decimal("42300.0")
        A.assert_pool(
            pool,
            total_volume_ml=2100,
            distinct_donor_count=3,
            projected_kcal_per_oz=20.14,
            status=PoolStatus.BALANCED,
        )
        assert pool["projected_kcal_per_oz"] == A.expected_projected_kcal(
            [(volume, kcal) for volume, kcal, _ in CANONICAL_DRAWS]
        )

        rows, meta = validate_paginated(
            api_client.list_pool_components(pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 3
        A.assert_ordered_by(rows, "created_at")
        assert rows[0]["allocated_volume_ml"] == 800
        assert rows[0]["component_kcal_per_oz"] == 18.5
        assert rows[2]["allocated_volume_ml"] == 600
        assert rows[2]["component_kcal_per_oz"] == 22.5

    def test_a_second_pool_recomputes_only_from_its_own_components(self):
        """A fourth donor's rich container goes into a second pool, and the
        first pool's three aggregates do not move a millilitre.

        PRD: "At each of those moments only components whose `status` is `ALLOCATED` are counted; `VOIDED`, `CONSUMED_PASTEURIZED` and `CONSUMED_LOST` components are excluded, which is why a scrapped-and-rebuilt pool re-derives its nutrition from scratch instead of accumulating history."
        PRD: "Otherwise `total_volume_ml` is the sum of `allocated_volume_ml` across the counted components; `distinct_donor_count` is the number of distinct `component_donor_id` values among them; and `projected_kcal_per_oz` is the volume-weighted average caloric density — multiply each counted component's `allocated_volume_ml` by its `component_kcal_per_oz`, sum those products at exact decimal precision with no intermediate rounding, divide that sum by `total_volume_ml`, and round the single quotient half up to two decimal places."

        Design: Corner/calculations/pool_metrics_count_only_that_pools_own_components
        """
        _banks, first = _canonical_term_pool()
        outsider = fx.donor_with_donation(
            index=4, volume_ml=700, kcal_per_oz=26.0, expressed_on="2026-07-14"
        )

        second = fx.open_pool(pool_code="POOL-0002", target_milk_class=TargetMilkClass.TERM)
        assert second["pool_sequence"] == 2
        fx.draw_component(second["id"], outsider.donation["id"], 700)

        A.assert_pool(
            fx.get_pool(first["id"]),
            total_volume_ml=2100,
            distinct_donor_count=3,
            projected_kcal_per_oz=20.14,
            status=PoolStatus.BALANCED,
        )
        A.assert_pool(
            fx.get_pool(second["id"]),
            total_volume_ml=700,
            distinct_donor_count=1,
            projected_kcal_per_oz=26.0,
            status=PoolStatus.DRAFT,
            pool_sequence=2,
        )

        rows, meta = validate_paginated(
            api_client.list_pool_components(second["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 1
        assert rows[0]["component_donor_id"] == outsider.donor["id"]


def _two_container_cooler(first, second, tracking_code="TRK-0001"):
    """One qualified donor and one accepted two-container cooler. Each of
    `first` and `second` is a `(container_label, expressed_on, volume_ml,
    kcal_per_oz, milk_class)` tuple."""
    donor = fx.qualified_donor()
    volumes = first[2] + second[2]
    cooler = fx.accepted_cooler(
        donor["id"],
        tracking_code=tracking_code,
        container_count=2,
        declared_volume_ml=volumes,
    )
    logged = [
        fx.log_container(
            cooler["id"],
            container_label=label,
            expressed_on=expressed_on,
            volume_ml=volume_ml,
            kcal_per_oz=kcal_per_oz,
            milk_class=milk_class,
        )
        for label, expressed_on, volume_ml, kcal_per_oz, milk_class in (first, second)
    ]
    return donor, cooler, logged


class TestDeferralWindowSurvivesRequalification:
    """The requalification gate reads the newest deferral, but pooling reads
    every ACTIVE one."""

    def test_milk_inside_a_surviving_lookback_window_is_refused_while_its_neighbour_is_drawn(self):
        """A 30-day lookback event recorded first and a 1-day event recorded
        second let the donor back to QUALIFIED, yet the first event still closes
        the window [2026-07-06, 2026-08-05] over her 10 July container.

        PRD: "The consequence is deliberate: if a long-dated deferral was recorded first and a short one afterwards, the short one governs the requalification gate, so the donor can return to screening and even to `QUALIFIED` while the long-dated event remains `ACTIVE` — and that still-`ACTIVE` event will keep refusing her milk at pooling time through the lookback-window rule of §3.6."
        PRD: "The donation's `expressed_on` must **not** fall inside the closed lookback interval — from `lookback_days` before `effective_from` through `effective_from` inclusive — of **any** `ACTIVE` `DeferralEvent` of its donor, or the draw is `ERR_DONATION_IN_DEFERRAL_WINDOW`; this is the rule that a still-`ACTIVE` long-dated deferral keeps enforcing even after its donor has been requalified."

        Design: Corner/validations/pooling_a_donation_expressed_inside_an_active_deferral_lookback_window
        """
        fx.set_clock(CLOCK)
        donor, _cooler, (inside, outside) = _two_container_cooler(
            ("C1", "2026-07-10", 700, 20.0, MilkClass.TERM),
            ("C2", "2026-07-05", 700, 20.0, MilkClass.TERM),
        )
        fx.record_deferral(
            donor["id"],
            reason_code=DeferralReason.ILLNESS,
            deferral_type=DeferralType.TEMPORARY,
            effective_from=CLOCK_DATE,
            deferral_days=30,
            lookback_days=30,
            recall_scope=RecallScope.NONE,
        )
        fx.record_deferral(
            donor["id"],
            reason_code=DeferralReason.TRAVEL,
            deferral_type=DeferralType.TEMPORARY,
            effective_from="2026-07-15",
            deferral_days=1,
            lookback_days=0,
            recall_scope=RecallScope.NONE,
        )
        fx.requalify(donor["id"])
        fx.qualify(donor["id"])

        reinstated = fx.get_donor(donor["id"])
        assert reinstated["status"] == DonorStatus.QUALIFIED
        assert reinstated["active_deferral_until_date"] == A.add_days(CLOCK_DATE, 30) == "2026-09-04"
        assert reinstated["surveillance_risk_score"] == A.expected_surveillance_score(
            30, [0, A.days_between("2026-07-15", CLOCK_DATE)]
        ) == 59

        pool = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)
        body = validate_error(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(inside["id"], 700, pool["version"]),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.DONATION_IN_DEFERRAL_WINDOW.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.DONOR_NOT_QUALIFIED.value
        assert fx.pool_version(pool["id"]) == 1

        component = validate_success(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(outside["id"], 700, 1),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        assert component["allocated_volume_ml"] == 700
        assert component["component_kcal_per_oz"] == 20.0

        A.assert_pool(
            fx.get_pool(pool["id"]),
            total_volume_ml=700,
            distinct_donor_count=1,
            projected_kcal_per_oz=20.0,
            status=PoolStatus.DRAFT,
        )
        refused = fx.get_donation(inside["id"])
        assert refused["remaining_ml"] == 700
        assert refused["status"] == DonationStatus.ELIGIBLE
        drawn = fx.get_donation(outside["id"])
        assert drawn["remaining_ml"] == 0
        assert drawn["status"] == DonationStatus.ALLOCATED


class TestRawMilkAgeCeiling:
    """The 365-day floor is a closed boundary at the exact calendar day."""

    def test_milk_expressed_365_days_ago_is_pooled_and_one_day_older_is_refused(self):
        """At clock date 2026-08-05 the floor is 2025-08-05: the 4 August
        container is refused and the 5 August container is drawn.

        PRD: "The donation's `expressed_on` must also be on or after the date exactly 365 days before the current clock date, because raw milk more than a year old cannot be pooled; a violation is `ERR_DONOR_MILK_AGE_EXCEEDED`."
        PRD: "Day arithmetic on dates is exact calendar addition, so leap days count, and all dates exchanged over the API use the `YYYY-MM-DD` form."

        Design: Corner/validations/pooling_raw_milk_older_than_365_days_is_refused_at_the_exact_day
        """
        fx.set_clock(CLOCK)
        floor = A.add_days(CLOCK_DATE, -C.RAW_MILK_MAX_AGE_DAYS)
        assert floor == "2025-08-05"

        _donor, _cooler, (too_old, exactly_old_enough) = _two_container_cooler(
            ("C1", A.add_days(floor, -1), 700, 20.0, MilkClass.TERM),
            ("C2", floor, 700, 20.0, MilkClass.TERM),
        )
        pool = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)

        validate_error(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(too_old["id"], 700, pool["version"]),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.DONOR_MILK_AGE_EXCEEDED.value,
            409,
        )
        assert fx.pool_version(pool["id"]) == 1

        component = validate_success(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(exactly_old_enough["id"], 700, 1),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        assert component["donation_id"] == exactly_old_enough["id"]
        assert component["allocated_volume_ml"] == 700
        assert component["status"] == ComponentStatus.ALLOCATED

        A.assert_pool(
            fx.get_pool(pool["id"]),
            total_volume_ml=700,
            distinct_donor_count=1,
            projected_kcal_per_oz=20.0,
            status=PoolStatus.DRAFT,
            version=2,
        )
        refused = fx.get_donation(too_old["id"])
        assert refused["remaining_ml"] == 700
        assert refused["status"] == DonationStatus.ELIGIBLE
        _rows, meta = validate_paginated(
            api_client.list_pool_components(pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 1


class TestMilkClassCompatibility:
    """Compatibility is read against the pool's target, not the donation alone."""

    def test_a_preterm_pool_refuses_term_milk_that_a_mixed_pool_accepts(self):
        """The same TERM container is refused by the PRETERM pool and drawn by
        the MIXED pool, which then also takes the PRETERM container and projects
        22.00 kcal/oz across the two.

        PRD: "The donation's `milk_class` must be compatible with the pool's `target_milk_class`: a `PRETERM` pool accepts only `PRETERM` donations, a `TERM` pool only `TERM` donations, and a `MIXED` pool accepts either, with a mismatch reported as `ERR_MILK_CLASS_MISMATCH`."
        PRD: "The resulting component freezes two values from the donation at the moment it is written: `component_kcal_per_oz`, copied from the donation's `kcal_per_oz`, and `component_donor_id`, copied from the donation's `donor_id`."

        Design: Corner/validations/milk_class_gate_refuses_term_milk_for_a_preterm_pool_but_a_mixed_pool_takes_both
        """
        fx.set_clock(CLOCK)
        _donor, _cooler, (term, preterm) = _two_container_cooler(
            ("C1", "2026-07-10", 700, 20.0, MilkClass.TERM),
            ("C2", "2026-07-10", 700, 24.0, MilkClass.PRETERM),
        )
        preterm_pool = fx.open_pool(
            pool_code="POOL-0001", target_milk_class=TargetMilkClass.PRETERM
        )
        mixed_pool = fx.open_pool(pool_code="POOL-0002", target_milk_class=TargetMilkClass.MIXED)

        validate_error(
            api_client.add_pool_component(
                preterm_pool["id"],
                f.pool_component(term["id"], 700, preterm_pool["version"]),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.MILK_CLASS_MISMATCH.value,
            409,
        )

        first = validate_success(
            api_client.add_pool_component(
                mixed_pool["id"],
                f.pool_component(term["id"], 700, mixed_pool["version"]),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        assert first["component_kcal_per_oz"] == 20.0
        second = validate_success(
            api_client.add_pool_component(
                mixed_pool["id"],
                f.pool_component(preterm["id"], 700, fx.pool_version(mixed_pool["id"])),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        assert second["component_kcal_per_oz"] == 24.0

        A.assert_pool(
            fx.get_pool(preterm_pool["id"]),
            total_volume_ml=0,
            projected_kcal_per_oz=None,
            version=1,
        )
        A.assert_pool(
            fx.get_pool(mixed_pool["id"]),
            total_volume_ml=1400,
            distinct_donor_count=1,
            projected_kcal_per_oz=22.0,
            status=PoolStatus.DRAFT,
        )
        _rows, meta = validate_paginated(
            api_client.list_pool_components(mixed_pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 2


class TestSinglePoolExclusivityThenTheStateGate:
    """A part-drawn container is exclusive to its pool; a fully drawn one is
    refused by its own status instead."""

    def test_a_second_pool_is_refused_then_the_exhausted_container_reports_its_state(self):
        """Splitting the container inside one pool is legal, a second pool is
        `ERR_COMPONENT_ALREADY_ALLOCATED`, and once the container is empty the
        next draw reports the earlier-evaluated `ERR_DONATION_STATE_INVALID`.

        PRD: "The donation must have no existing `ALLOCATED` component in any **different** pool, since a container cannot be committed to two pools at once — that is `ERR_COMPONENT_ALREADY_ALLOCATED`, and it does not prevent a second draw from the same donation into the *same* pool."
        PRD: "The donation must be `ELIGIBLE`."

        Design: Corner/validations/a_donation_allocated_to_one_pool_is_refused_by_another_then_locked_by_its_own_state
        """
        fx.set_clock(CLOCK)
        bank = fx.donor_with_donation(
            index=1, volume_ml=700, kcal_per_oz=20.0, expressed_on="2026-07-10"
        )
        first = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)
        second = fx.open_pool(pool_code="POOL-0002", target_milk_class=TargetMilkClass.TERM)
        fx.draw_component(first["id"], bank.donation["id"], 400)
        assert fx.get_donation(bank.donation["id"])["remaining_ml"] == 300

        validate_error(
            api_client.add_pool_component(
                second["id"],
                f.pool_component(bank.donation["id"], 300, second["version"]),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.COMPONENT_ALREADY_ALLOCATED.value,
            409,
        )

        topped_up = validate_success(
            api_client.add_pool_component(
                first["id"],
                f.pool_component(bank.donation["id"], 300, fx.pool_version(first["id"])),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        assert topped_up["allocated_volume_ml"] == 300

        exhausted = fx.get_donation(bank.donation["id"])
        assert exhausted["remaining_ml"] == 0
        assert exhausted["status"] == DonationStatus.ALLOCATED

        body = validate_error(
            api_client.add_pool_component(
                first["id"],
                f.pool_component(bank.donation["id"], 100, fx.pool_version(first["id"])),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.DONATION_STATE_INVALID.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.COMPONENT_ALREADY_ALLOCATED.value

        A.assert_pool(
            fx.get_pool(first["id"]),
            total_volume_ml=700,
            distinct_donor_count=1,
            projected_kcal_per_oz=20.0,
        )
        A.assert_pool(fx.get_pool(second["id"]), total_volume_ml=0, version=1)

        rows, meta = validate_paginated(
            api_client.list_donation_components(bank.donation["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == [ComponentStatus.ALLOCATED] * 2


class TestCommitConstraintLadder:
    """Commit admits a DRAFT pool on purpose, so each balance constraint gets to
    speak for itself in the declared order."""

    def test_commit_reports_emptiness_then_donor_count_then_volume(self):
        """One pool is walked from empty to committed, and each intermediate
        commit attempt names exactly the next unmet constraint.

        PRD: "The state gate admits both `DRAFT` and `BALANCED` — deliberately, so that an unbalanced pool reports which specific constraint it failed rather than a generic state error."
        PRD: "**Committing a pool** enforces its state gate first, and then the four balance constraints in this exact order: emptiness (`ERR_POOL_EMPTY`) before donor count (`ERR_POOL_DONOR_COUNT_INSUFFICIENT`) before nutritional range (`ERR_POOL_NUTRITION_OUT_OF_RANGE`) before total volume (`ERR_POOL_VOLUME_OUT_OF_RANGE`)."

        Design: Corner/validations/pool_commit_gate_ladder_empty_then_donor_count_then_volume
        """
        fx.set_clock(CLOCK)
        banks = [
            fx.donor_with_donation(
                index=index, volume_ml=1200, kcal_per_oz=20.0, expressed_on="2026-07-10"
            )
            for index in range(1, 4)
        ]
        pool = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)

        empty = validate_error(
            api_client.commit_pool(pool["id"], TECHNICIAN_HEADERS),
            ApiErrorId.POOL_EMPTY.value,
            409,
        )
        assert empty["error_id"] != ApiErrorId.POOL_NUTRITION_OUT_OF_RANGE.value

        fx.draw_component(pool["id"], banks[0].donation["id"], 400)
        assert fx.pool_version(pool["id"]) == 2
        validate_error(
            api_client.commit_pool(pool["id"], TECHNICIAN_HEADERS),
            ApiErrorId.POOL_DONOR_COUNT_INSUFFICIENT.value,
            409,
        )

        fx.draw_component(pool["id"], banks[1].donation["id"], 400)
        assert fx.pool_version(pool["id"]) == 3
        fx.draw_component(pool["id"], banks[2].donation["id"], 400)
        assert fx.pool_version(pool["id"]) == 4
        validate_error(
            api_client.commit_pool(pool["id"], TECHNICIAN_HEADERS),
            ApiErrorId.POOL_VOLUME_OUT_OF_RANGE.value,
            409,
        )

        fx.draw_component(pool["id"], banks[0].donation["id"], 800)
        balanced = fx.get_pool(pool["id"])
        A.assert_pool(
            balanced,
            status=PoolStatus.BALANCED,
            total_volume_ml=2000,
            distinct_donor_count=3,
            projected_kcal_per_oz=20.0,
            version=5,
        )

        committed = validate_success(api_client.commit_pool(pool["id"], TECHNICIAN_HEADERS))
        A.assert_pool(
            committed,
            status=PoolStatus.COMMITTED,
            committed_by_user_id=TECHNICIAN_ID,
            version=6,
        )
        A.assert_instant_equals(committed["committed_at"], CLOCK, "committed_at")

        _rows, meta = validate_paginated(
            api_client.list_pool_components(pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 4

        drained = fx.get_donation(banks[0].donation["id"])
        assert drained["remaining_ml"] == 0
        assert drained["status"] == DonationStatus.ALLOCATED
        for bank in banks[1:]:
            partial = fx.get_donation(bank.donation["id"])
            assert partial["remaining_ml"] == 800
            assert partial["status"] == DonationStatus.ELIGIBLE


class TestDonorSpreadCap:
    """The ceiling counts donors, not components."""

    def test_a_sixth_donor_is_refused_while_a_repeat_donors_second_draw_lands(self):
        """With five donors in the pool a sixth is `ERR_POOL_DONOR_CAP_EXCEEDED`,
        yet another 300 ml from the first donor is accepted and leaves the count
        at five while the volume rises to 1800.

        PRD: "And the draw must not push the pool's `distinct_donor_count` above 5, reported as `ERR_POOL_DONOR_CAP_EXCEEDED`; a second draw from a donor already represented in the pool does not raise that count and so is never refused by this rule."
        PRD: "`distinct_donor_count` is the number of distinct `component_donor_id` values among them"

        Design: Corner/validations/pool_donor_cap_refuses_a_sixth_distinct_donor_but_not_a_repeat_donor
        """
        fx.set_clock(CLOCK)
        banks = [
            fx.donor_with_donation(
                index=index, volume_ml=600, kcal_per_oz=20.0, expressed_on="2026-07-10"
            )
            for index in range(1, 7)
        ]
        pool = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)
        for bank in banks[:5]:
            fx.draw_component(pool["id"], bank.donation["id"], 300)

        full = fx.get_pool(pool["id"])
        A.assert_pool(
            full,
            status=PoolStatus.BALANCED,
            distinct_donor_count=5,
            total_volume_ml=1500,
            projected_kcal_per_oz=20.0,
            version=6,
        )
        assert C.POOL_DONOR_CAP == 5

        validate_error(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(banks[5].donation["id"], 300, full["version"]),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.POOL_DONOR_CAP_EXCEEDED.value,
            409,
        )

        repeat = validate_success(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(banks[0].donation["id"], 300, full["version"]),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        assert repeat["allocated_volume_ml"] == 300
        assert repeat["component_donor_id"] == banks[0].donor["id"]

        A.assert_pool(
            fx.get_pool(pool["id"]),
            status=PoolStatus.BALANCED,
            distinct_donor_count=5,
            total_volume_ml=1800,
            projected_kcal_per_oz=20.0,
            version=7,
        )
        refused = fx.get_donation(banks[5].donation["id"])
        assert refused["remaining_ml"] == 600
        assert refused["status"] == DonationStatus.ELIGIBLE
        repeated = fx.get_donation(banks[0].donation["id"])
        assert repeated["remaining_ml"] == 0
        assert repeated["status"] == DonationStatus.ALLOCATED
        _rows, meta = validate_paginated(
            api_client.list_pool_components(pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 6


class TestPoolConcurrencyToken:
    """The pool is the concurrency parent of a draw, and every accepted draw
    moves it on."""

    def test_a_replayed_pool_version_is_refused_and_the_re_read_one_lands(self):
        """Two containers of the same donor are drawn one after the other; the
        second draw sent with the pre-draw token is `ERR_STALE_VERSION` and
        changes nothing, and the same draw with the fresh token succeeds.

        PRD: "Adding a component to a pool requires `expected_pool_version` to equal the parent `Pool`'s current `version`, and is otherwise rejected with `ERR_STALE_VERSION` (HTTP 412). This protects the technician who sized an allocation from a `projected_kcal_per_oz` and `distinct_donor_count` snapshot that another component write has already invalidated."
        PRD: "Pool components, whether listed by pool or by donation: `created_at` ascending."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_pool_version_refuses_the_second_component_then_the_fresh_version_lands_it
        """
        fx.set_clock(CLOCK)
        _donor, _cooler, (first, second) = _two_container_cooler(
            ("C1", "2026-07-10", 1200, 20.0, MilkClass.TERM),
            ("C2", "2026-07-10", 1200, 20.0, MilkClass.TERM),
        )
        pool = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)
        stale_token = pool["version"]

        landed = validate_success(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(first["id"], 400, stale_token),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        assert landed["donation_id"] == first["id"]
        assert landed["allocated_volume_ml"] == 400
        assert landed["status"] == ComponentStatus.ALLOCATED

        after_first = fx.get_pool(pool["id"])
        A.assert_pool(
            after_first,
            total_volume_ml=400,
            distinct_donor_count=1,
            projected_kcal_per_oz=20.0,
            status=PoolStatus.DRAFT,
            version=stale_token + 1,
        )

        validate_error(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(second["id"], 400, stale_token),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.STALE_VERSION.value,
            412,
        )
        unchanged = fx.get_pool(pool["id"])
        assert unchanged["total_volume_ml"] == 400
        assert unchanged["version"] == after_first["version"]

        rows, meta = validate_paginated(
            api_client.list_pool_components(pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 1
        assert rows[0]["donation_id"] == first["id"]

        fx.set_clock("2026-08-05T09:00:00Z")
        fresh = validate_success(
            api_client.add_pool_component(
                pool["id"],
                f.pool_component(second["id"], 400, unchanged["version"]),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        assert fresh["donation_id"] == second["id"]

        final = fx.get_pool(pool["id"])
        assert final["total_volume_ml"] == 800
        assert final["version"] == stale_token + 2
        assert final["distinct_donor_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_pool_components(pool["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 2
        A.assert_ordered_by(rows, "created_at")
        assert [row["donation_id"] for row in rows] == [first["id"], second["id"]]
        assert [row["allocated_volume_ml"] for row in rows] == [400, 400]
        assert [row["status"] for row in rows] == [ComponentStatus.ALLOCATED] * 2

        assert fx.get_donation(first["id"])["remaining_ml"] == 800
        assert fx.get_donation(second["id"])["remaining_ml"] == 800


class TestDrawsAreReachableFromTheContainer:
    """A container that fed two pools is walkable from the donation side."""

    def test_the_donations_component_channel_lists_both_draws_in_created_order(self):
        """400 ml went to the pool and a second 300 ml draw followed an hour
        later; the reverse-reachability channel returns both rows in that order
        and the container keeps the 500 ml it never gave away.

        PRD: "The sub-resource list channels that do exist — a donor's questionnaires, serology panels, physician approvals and deferrals; a shipment's donations by filter; a donation's components; a pool's components; a run's readings; a lot's fills; a prescription's fills — exist purely as reverse-reachability read channels so that a client can walk from a parent to its children."
        PRD: "A donation's `remaining_ml` is thereafter always its `volume_ml` less the sum of `allocated_volume_ml` across its non-`VOIDED` components, and never goes below 0."
        PRD: "The donation must have no existing `ALLOCATED` component in any **different** pool, since a container cannot be committed to two pools at once — that is `ERR_COMPONENT_ALREADY_ALLOCATED`, and it does not prevent a second draw from the same donation into the *same* pool."

        Design: Corner/endpoints/donation_pool_components_cross_reference_lists_every_draw_in_order
        """
        fx.set_clock(CLOCK)
        bank = fx.donor_with_donation(
            index=1, volume_ml=1200, kcal_per_oz=20.0, expressed_on="2026-07-10"
        )
        pool = fx.open_pool(pool_code="POOL-0001", target_milk_class=TargetMilkClass.TERM)

        fx.draw_component(pool["id"], bank.donation["id"], 400)
        fx.set_clock("2026-08-05T09:00:00Z")
        fx.draw_component(pool["id"], bank.donation["id"], 300)

        rows, meta = validate_paginated(
            api_client.list_donation_components(bank.donation["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        A.assert_ordered_by(rows, "created_at")
        assert [row["pool_id"] for row in rows] == [pool["id"], pool["id"]]
        assert [row["allocated_volume_ml"] for row in rows] == [400, 300]
        assert rows[0]["component_kcal_per_oz"] == 20.0
        assert [row["status"] for row in rows] == [ComponentStatus.ALLOCATED] * 2
        assert all(row["donation_id"] == bank.donation["id"] for row in rows)

        donation = fx.get_donation(bank.donation["id"])
        assert donation["remaining_ml"] == 500
        assert donation["status"] == DonationStatus.ELIGIBLE
        assert fx.get_pool(pool["id"])["total_volume_ml"] == 700

        page, page_meta = validate_paginated(
            api_client.list_donation_components(
                bank.donation["id"], TECHNICIAN_HEADERS, {"limit": 1, "offset": 0}
            )
        )
        assert page_meta["total_count"] == 2
        assert page_meta["has_more"] is True
        assert len(page) == 1
        assert page[0]["allocated_volume_ml"] == 400
