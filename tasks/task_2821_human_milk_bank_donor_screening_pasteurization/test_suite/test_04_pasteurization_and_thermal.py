"""Pasteurization: the half-open pasteurizer slot, the datalogger curve, the
longest certified hold, the three independent run dimensions, bottling identity,
the three shelf-life ceilings and the destructive failed-culture cascade.

Every run in this module stands on a committed pool assembled from containers
logged against accepted coolers, because that is the only documented route milk
takes to a pasteurizer. Runs are scheduled on named machines and, where a test
needs two runs at once, on two different machines, so the slot rule is exercised
deliberately rather than incidentally.
"""

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
    QA_OFFICER_ID,
    QA_RELEASER_HEADERS,
    QA_RELEASER_ID,
    TECHNICIAN_HEADERS,
    TECHNICIAN_ID,
)
from test_helpers.types import (
    ComponentStatus,
    CultureStatus,
    DonationStatus,
    LotReleaseStatus,
    MilkClass,
    PoolStatus,
    ReleaseEligibility,
    RunStatus,
    ShipmentStatus,
    TargetMilkClass,
    ThermalStatus,
)

INTAKE_CLOCK = C.CLOCK_INTAKE          # "2026-08-05T08:00:00Z"
INTAKE_DATE = C.CLOCK_INTAKE_DATE      # "2026-08-05"
RUN_CLOCK = C.CLOCK_RUN                # "2026-08-10T10:05:00Z"
RUN_DATE = C.CLOCK_RUN_DATE            # "2026-08-10"

# A curve whose longest certified hold is exactly 1800 seconds, and the same
# curve one second short of it.
HOLD_1800 = ((0, 63.0), (600, 63.5), (1200, 64.0), (1800, 63.2))
HOLD_1799 = ((0, 63.0), (600, 63.5), (1200, 64.0), (1799, 63.2))


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


def _canonical_chain(third_container=None, **chain):
    """The canonical three-donor TERM pool of 2100 ml at 20.14 kcal/oz, with the
    third container optionally re-specified so a shelf-life ceiling can bind."""
    containers = [dict(spec) for spec in fx.CANONICAL_CONTAINERS]
    if third_container:
        containers[2].update(third_container)
    return fx.build_chain(containers=containers, **chain)


def _uniform_chain(volume_each=700, kcal_per_oz=20.0, expressed_on="2026-07-10", **chain):
    """Three donors, one container each, all carrying the same assay so the
    pool's projection is exactly `kcal_per_oz`."""
    donors = [fx.donor_spec(index + 1) for index in range(3)]
    containers = [
        fx.container_spec(
            index + 1,
            index,
            volume_each,
            kcal_per_oz=kcal_per_oz,
            expressed_on=expressed_on,
        )
        for index in range(3)
    ]
    return fx.build_chain(donors=donors, containers=containers, **chain)


def _two_committed_pools(volume_each=500):
    """Three donors, each shipping two single-container coolers, drawn into two
    committed TERM pools of `volume_each` times three millilitres apiece."""
    fx.set_clock(INTAKE_CLOCK)
    first_draws = []
    second_draws = []
    for index in range(1, 4):
        donor = _qualified_donor(index)
        for slot, bucket in ((1, first_draws), (2, second_draws)):
            cooler = fx.accepted_cooler(
                donor["id"],
                tracking_code=f"TRK-{index * 2 + slot:04d}",
                declared_volume_ml=volume_each,
                verified_volume_ml=volume_each,
            )
            bucket.append(
                fx.log_container(
                    cooler["id"],
                    container_label=f"C{slot}",
                    expressed_on="2026-07-10",
                    volume_ml=volume_each,
                    kcal_per_oz=20.0,
                    milk_class=MilkClass.TERM,
                )
            )

    pools = []
    for sequence, draws in ((1, first_draws), (2, second_draws)):
        pool = fx.open_pool(
            pool_code=f"POOL-{sequence:04d}", target_milk_class=TargetMilkClass.TERM
        )
        for donation in draws:
            fx.draw_component(pool["id"], donation["id"], volume_each)
        pools.append(fx.commit_pool(pool["id"]))
    return pools


class TestLotShelfLifeIsTheEarliestOfThreeCeilings:
    """Shelf life is a nested minimum over a pasteurization ceiling, a raw-age
    ceiling and a receipt ceiling, all measured over the same contributing set."""

    def test_one_year_old_container_short_dates_the_lot_the_run_bottles(self):
        """The pool's third container was expressed on 2025-08-20, so the
        raw-age ceiling falls on 2026-08-20 — ten days after pasteurization —
        and beats a pasteurization ceiling of 2027-02-06 and a receipt ceiling
        of 2027-04-02.

        PRD: "Shelf life is the earliest of three independent ceilings, and all three are measured over the same **contributing set**: the components of the run's pool whose `status` is `ALLOCATED` or `CONSUMED_PASTEURIZED`, which is to say every component that survived to bottling, including those an earlier lot of the same run has already marked consumed."
        PRD: "The first ceiling is the pasteurization ceiling: the calendar date of the run's `completed_at` plus 180 days. The second is the raw-age ceiling: the **earliest** `expressed_on` among the donations behind the contributing components, plus 365 days. The third is the receipt ceiling: the **earliest** calendar date of `received_at` among the coolers those donations arrived in, plus 240 days. The lot's `expiration_date` is the earliest of those three dates."
        PRD: "Its `lot_code` is a deterministic string assembled from three segments joined by hyphens: the run's pasteurization date rendered as eight digits in year-month-day order, then the pool's `pool_sequence` zero-padded to three digits, then the `lot_sequence` zero-padded to two digits."

        Design: Difficulty/combinatorial_formula/lot_expiration_nested_min_three_ceilings
        """
        chain = _canonical_chain(
            third_container={"expressed_on": "2025-08-20"},
            run={},
            lots=[(21, 100)],
            culture=None,
            release=False,
        )
        A.assert_pool(
            chain.pool,
            status=PoolStatus.PASTEURIZED,
            total_volume_ml=2100,
            distinct_donor_count=3,
            projected_kcal_per_oz=20.14,
            bottled_volume_ml=2100,
        )

        pasteurization_ceiling = A.add_days(RUN_DATE, C.PASTEURIZATION_SHELF_DAYS)
        raw_age_ceiling = A.add_days("2025-08-20", C.RAW_AGE_SHELF_DAYS)
        receipt_ceiling = A.add_days(INTAKE_DATE, C.RECEIPT_SHELF_DAYS)
        assert (pasteurization_ceiling, raw_age_ceiling, receipt_ceiling) == (
            "2027-02-06",
            "2026-08-20",
            "2027-04-02",
        )

        lot = fx.get_lot(chain.lots[0]["id"])
        A.assert_milk_lot(
            lot,
            lot_code="20260810-001-01",
            lot_sequence=1,
            total_volume_ml=2100,
            available_ml=2100,
            dispensed_ml=0,
            kcal_per_oz=20.14,
            milk_class=MilkClass.TERM,
            pasteurization_date=RUN_DATE,
            release_status=LotReleaseStatus.HOLD,
            version=1,
        )
        assert lot["expiration_date"] == raw_age_ceiling == "2026-08-20"
        assert lot["expiration_date"] != pasteurization_ceiling
        assert lot["expiration_date"] == A.expected_expiration_date(
            chain.run["completed_at"], "2025-08-20", INTAKE_DATE
        )

    def test_a_late_pasteurization_lets_the_receipt_ceiling_bind_for_both_lots(self):
        """The same coolers pasteurized on 2026-11-01 push the pasteurization
        ceiling out to 2027-04-30, so the receipt ceiling of 2027-04-02 becomes
        the earliest of the three — and the run's second lot inherits it,
        differing from the first only in the trailing lot-code segment.

        PRD: "The first ceiling is the pasteurization ceiling: the calendar date of the run's `completed_at` plus 180 days. The second is the raw-age ceiling: the **earliest** `expressed_on` among the donations behind the contributing components, plus 365 days. The third is the receipt ceiling: the **earliest** calendar date of `received_at` among the coolers those donations arrived in, plus 240 days. The lot's `expiration_date` is the earliest of those three dates."
        PRD: "Because the contributing set does not shrink as a run is bottled repeatedly, a run's second lot inherits exactly the same three ceilings as its first — and a single very old container in the pool short-dates every lot of the run no matter how fresh the pasteurization was."
        PRD: "Because every lot of one run shares that run's `completed_at`, sibling lots of the same run differ only in the trailing two-digit segment."

        Design: Difficulty/combinatorial_formula/lot_expiration_nested_min_three_ceilings
        """
        chain = _canonical_chain(
            run={"scheduled_start_at": "2026-11-01T09:00:00Z"},
            run_clock="2026-11-01T10:05:00Z",
            lots=[(10, 100), (11, 100)],
            culture=None,
            release=False,
        )

        pasteurization_ceiling = A.add_days("2026-11-01", C.PASTEURIZATION_SHELF_DAYS)
        raw_age_ceiling = A.add_days("2026-07-05", C.RAW_AGE_SHELF_DAYS)
        receipt_ceiling = A.add_days(INTAKE_DATE, C.RECEIPT_SHELF_DAYS)
        assert (pasteurization_ceiling, raw_age_ceiling, receipt_ceiling) == (
            "2027-04-30",
            "2027-07-05",
            "2027-04-02",
        )

        first = fx.get_lot(chain.lots[0]["id"])
        second = fx.get_lot(chain.lots[1]["id"])
        A.assert_milk_lot(
            first,
            lot_code="20261101-001-01",
            lot_sequence=1,
            total_volume_ml=1000,
            expiration_date=receipt_ceiling,
            pasteurization_date="2026-11-01",
            kcal_per_oz=20.14,
        )
        A.assert_milk_lot(
            second,
            lot_code="20261101-001-02",
            lot_sequence=2,
            total_volume_ml=1100,
            expiration_date=receipt_ceiling,
            pasteurization_date="2026-11-01",
            kcal_per_oz=20.14,
        )
        assert first["expiration_date"] == second["expiration_date"] == "2027-04-02"
        assert first["lot_code"][:-2] == second["lot_code"][:-2]
        A.assert_pool(chain.pool, status=PoolStatus.PASTEURIZED, bottled_volume_ml=2100)
        A.assert_run(chain.run, run_status=RunStatus.BOTTLED)


class TestRunCarriesThreeIndependentDimensions:
    """`run_status`, `thermal_status` and `culture_status` each move on their own
    schedule, and `release_eligibility` is the derived verdict over two of them."""

    def test_a_culture_recorded_after_bottling_flips_eligibility_without_moving_the_run(self):
        """The bottled run sits at PASSED / NOT_COLLECTED / BLOCKED. Recording a
        no-growth culture moves only the microbiology dimension, so eligibility
        becomes ELIGIBLE while `run_status` stays BOTTLED.

        PRD: "`release_eligibility` is `ELIGIBLE` if and only if `thermal_status` is `PASSED` **and** `culture_status` is `PASSED`, and `BLOCKED` in every other combination — including the very common case of a thermally passed run whose culture is still `NOT_COLLECTED`."
        PRD: "Both are stamped on the run along with `culture_recorded_by_user_id`, and the verdict is a single threshold: `culture_status` becomes `FAILED` when `culture_cfu_per_ml` is 10 or more, and `PASSED` otherwise."
        PRD: "The run's `run_status` is untouched by the culture, which is why this is a `COMPLETED → COMPLETED` (or `BOTTLED → BOTTLED`) transition on the physical dimension."

        Design: Difficulty/non_linear_state_machine/run_three_parallel_dimensions
        """
        chain = _canonical_chain(run={}, lots=[(21, 100)], culture=None, release=False)

        A.assert_run(
            chain.run,
            run_status=RunStatus.BOTTLED,
            thermal_status=ThermalStatus.PASSED,
            culture_status=CultureStatus.NOT_COLLECTED,
            release_eligibility=ReleaseEligibility.BLOCKED,
            longest_hold_seconds=1800,
            peak_celsius=64.0,
            reading_count=4,
            version=7,
        )
        assert chain.run["culture_recorded_by_user_id"] is None

        cultured = validate_success(
            api_client.record_culture(
                chain.run["id"], f.culture(0, C.NO_GROWTH_ORGANISM), QA_OFFICER_HEADERS
            )
        )
        A.assert_run(
            cultured,
            run_status=RunStatus.BOTTLED,
            thermal_status=ThermalStatus.PASSED,
            culture_status=CultureStatus.PASSED,
            release_eligibility=ReleaseEligibility.ELIGIBLE,
            culture_cfu_per_ml=0,
            culture_organism=C.NO_GROWTH_ORGANISM,
            culture_recorded_by_user_id=QA_OFFICER_ID,
            longest_hold_seconds=1800,
            peak_celsius=64.0,
            version=8,
        )

        lot = fx.get_lot(chain.lots[0]["id"])
        A.assert_milk_lot(
            lot,
            lot_code="20260810-001-01",
            release_status=LotReleaseStatus.HOLD,
            available_ml=2100,
            version=1,
        )

    def test_the_same_three_dimensions_advance_in_the_other_order(self):
        """Cultured first and bottled second, the run passes through
        COMPLETED / PASSED / PASSED / ELIGIBLE before the physical dimension
        moves, and the bottling does not disturb the verdict.

        PRD: "Those first four state fields are the run's **three independent dimensions plus their derived verdict**: `run_status` tracks physical progress, `thermal_status` tracks temperature/time verification, `culture_status` tracks microbiology, and each evolves on its own schedule."
        PRD: "The post-pasteurization culture is a `QualityAssuranceOfficer`'s record and is admitted while the run's `run_status` is `COMPLETED` or `BOTTLED`, provided its `culture_status` is still `NOT_COLLECTED`; a second culture on the same run is refused with `ERR_RUN_STATE_INVALID`."
        PRD: "On success `released_at` is stamped with the clock instant, `released_by_user_id` with the acting officer's `X-User-ID`, and the lot's `version` increases by 1."

        Design: Difficulty/non_linear_state_machine/run_three_parallel_dimensions
        """
        chain = _canonical_chain(run={}, culture=None)
        A.assert_run(
            chain.run,
            run_status=RunStatus.COMPLETED,
            thermal_status=ThermalStatus.PASSED,
            culture_status=CultureStatus.NOT_COLLECTED,
            release_eligibility=ReleaseEligibility.BLOCKED,
            version=6,
        )

        cultured = fx.record_culture(chain.run["id"], 0, C.NO_GROWTH_ORGANISM)
        A.assert_run(
            cultured,
            run_status=RunStatus.COMPLETED,
            thermal_status=ThermalStatus.PASSED,
            culture_status=CultureStatus.PASSED,
            release_eligibility=ReleaseEligibility.ELIGIBLE,
            culture_recorded_by_user_id=QA_OFFICER_ID,
            version=7,
        )

        lot = fx.bottle_lot(chain.run["id"], 21, 100)
        A.assert_milk_lot(lot, release_status=LotReleaseStatus.HOLD, version=1)
        A.assert_run(
            fx.get_run(chain.run["id"]),
            run_status=RunStatus.BOTTLED,
            release_eligibility=ReleaseEligibility.ELIGIBLE,
            version=8,
        )

        released = validate_success(
            api_client.release_milk_lot(lot["id"], QA_RELEASER_HEADERS)
        )
        A.assert_milk_lot(
            released,
            release_status=LotReleaseStatus.RELEASED,
            released_by_user_id=QA_RELEASER_ID,
            available_ml=2100,
            version=2,
        )
        A.assert_instant_equals(released["released_at"], RUN_CLOCK, "released_at")


class TestFailedCultureDestroysTheWholeChain:
    """A failed culture is the bank's most destructive single event: four hops,
    each caused by the one before it, all inside the one request."""

    def test_a_contaminated_plate_walks_the_cascade_from_the_lot_to_the_coolers(self):
        """250 CFU/ml of Staphylococcus aureus blocks eligibility, discards the
        lot with its volume frozen, scraps the pool for culture with its
        components consumed-lost, and discards all three donations — while the
        donors keep the reimbursement they were already credited.

        PRD: "The first hop is the verdict itself: `culture_status` becomes `FAILED`, which forces `release_eligibility` to `BLOCKED`."
        PRD: "Because eligibility became blocked, the second hop moves every `MilkLot` of that run whose `release_status` is `HOLD`, `RELEASED` or `EXHAUSTED` to `DISCARDED`, freezing each lot's `available_ml` at whatever value it then held and incrementing each lot's `version`."
        PRD: "Because every lot of the run is now `DISCARDED`, the third hop moves the run's `Pool` — from `COMMITTED` or `PASTEURIZED` — to `SCRAPPED_CULTURE` and moves every one of that pool's components whose `status` is `ALLOCATED` or `CONSUMED_PASTEURIZED` to `CONSUMED_LOST`, with the pool's `version` incremented."
        PRD: "Because those components became `CONSUMED_LOST`, the fourth hop moves each of their donations whose `status` is not already `RECALLED` to `DISCARDED` and sets that donation's `remaining_ml` to 0, with a `version` increment — after which any cooler all of whose containers are now terminal bubbles up to `CLOSED` per §2.8."
        PRD: "`SCRAPPED_CULTURE` is emphatically **not** the same outcome as `SCRAPPED`: no volume is returned to any donation, because the milk has been heat-treated and then found contaminated."

        Design: Difficulty/transitive_cascade/failed_culture_four_hop_destruction
        """
        chain = _canonical_chain(run={}, lots=[(21, 100)], culture=None, release=False)
        balance_before = fx.donor_balance(chain.donors[0]["id"])
        assert balance_before == A.expected_reimbursement_cents("Z2", 1, False, 0) == 2125

        A.assert_pool(chain.pool, status=PoolStatus.PASTEURIZED, bottled_volume_ml=2100)
        A.assert_run(
            chain.run,
            run_status=RunStatus.BOTTLED,
            thermal_status=ThermalStatus.PASSED,
            culture_status=CultureStatus.NOT_COLLECTED,
        )

        failed = validate_success(
            api_client.record_culture(
                chain.run["id"], f.culture(250, "STAPH_AUREUS"), QA_OFFICER_HEADERS
            )
        )
        A.assert_run(
            failed,
            run_status=RunStatus.BOTTLED,
            thermal_status=ThermalStatus.PASSED,
            culture_status=CultureStatus.FAILED,
            release_eligibility=ReleaseEligibility.BLOCKED,
            culture_cfu_per_ml=250,
            culture_organism="STAPH_AUREUS",
            culture_recorded_by_user_id=QA_OFFICER_ID,
        )

        lot = fx.get_lot(chain.lots[0]["id"])
        A.assert_milk_lot(
            lot,
            release_status=LotReleaseStatus.DISCARDED,
            available_ml=2100,
            dispensed_ml=0,
            version=2,
        )

        pool = fx.get_pool(chain.pool["id"])
        A.assert_pool(pool, status=PoolStatus.SCRAPPED_CULTURE, bottled_volume_ml=2100)

        components = fx.list_pool_components(pool["id"])
        assert len(components) == 3
        assert [row["status"] for row in components] == [ComponentStatus.CONSUMED_LOST] * 3

        for donation in chain.donations:
            row = fx.get_donation(donation["id"])
            A.assert_donation(row, status=DonationStatus.DISCARDED, remaining_ml=0)

        for shipment in chain.shipments:
            assert fx.get_shipment(shipment["id"])["status"] == ShipmentStatus.CLOSED

        assert fx.donor_balance(chain.donors[0]["id"]) == balance_before

    def test_a_plate_one_colony_short_of_the_threshold_destroys_nothing(self):
        """Nine colony-forming units per millilitre is a PASSED culture, so the
        first hop never fires and none of the three hops behind it do either:
        the lot stays in HOLD, the pool stays PASTEURIZED and every donation
        keeps its pasteurized status.

        PRD: "Both are stamped on the run along with `culture_recorded_by_user_id`, and the verdict is a single threshold: `culture_status` becomes `FAILED` when `culture_cfu_per_ml` is 10 or more, and `PASSED` otherwise."
        PRD: "The first hop is the verdict itself: `culture_status` becomes `FAILED`, which forces `release_eligibility` to `BLOCKED`."
        PRD: "The run itself advances `COMPLETED → BOTTLED`. The pool advances `COMMITTED → PASTEURIZED`, and every one of its components still `ALLOCATED` becomes `CONSUMED_PASTEURIZED`, which in turn advances each donation `ALLOCATED → PASTEURIZED` once all of that donation's components are `CONSUMED_PASTEURIZED` and its `remaining_ml` has reached 0."

        Design: Difficulty/transitive_cascade/failed_culture_four_hop_destruction
        """
        chain = _canonical_chain(run={}, lots=[(21, 100)], culture=None, release=False)

        passed = validate_success(
            api_client.record_culture(
                chain.run["id"], f.culture(C.CULTURE_FAIL_CFU_PER_ML - 1, "NONE"), QA_OFFICER_HEADERS
            )
        )
        A.assert_run(
            passed,
            run_status=RunStatus.BOTTLED,
            thermal_status=ThermalStatus.PASSED,
            culture_status=CultureStatus.PASSED,
            release_eligibility=ReleaseEligibility.ELIGIBLE,
            culture_cfu_per_ml=9,
        )

        A.assert_milk_lot(
            fx.get_lot(chain.lots[0]["id"]),
            release_status=LotReleaseStatus.HOLD,
            available_ml=2100,
            version=1,
        )
        A.assert_pool(
            fx.get_pool(chain.pool["id"]),
            status=PoolStatus.PASTEURIZED,
            bottled_volume_ml=2100,
        )
        components = fx.list_pool_components(chain.pool["id"])
        assert [row["status"] for row in components] == [ComponentStatus.CONSUMED_PASTEURIZED] * 3
        for donation in chain.donations:
            A.assert_donation(
                fx.get_donation(donation["id"]),
                status=DonationStatus.PASTEURIZED,
                remaining_ml=0,
            )


class TestThermalHoldBoundaryIsExactlyEighteenHundredSeconds:
    """The thermal verdict turns on a whole-second comparison: 1800 passes and
    1799 fails, and the failed run never reaches the bottling arithmetic."""

    def test_one_second_short_of_the_hold_fails_the_identical_curve(self):
        """Two runs on the same committed pool, on two different machines, see
        the same four in-band readings; the second one's last sample arrives at
        offset 1799 instead of 1800.

        PRD: "`thermal_status` becomes `PASSED` when `longest_hold_seconds` is 1800 seconds or more, and `FAILED` otherwise."
        PRD: "Either way the run advances `IN_PROGRESS → COMPLETED` — physical progress does not depend on the thermal verdict — `peak_celsius` reflects the maximum `celsius` over the run's samples, `completed_at` is stamped with the clock instant, `completed_by_user_id` with the acting technician's `X-User-ID`, `release_eligibility` is recomputed, and the run's `version` increases by 1."

        Design: Difficulty/boundary_precision_check/thermal_hold_exact_1800_seconds
        """
        chain = _canonical_chain(run=None)
        A.assert_pool(chain.pool, status=PoolStatus.COMMITTED, total_volume_ml=2100)

        fx.set_clock(RUN_CLOCK)
        on_bound = fx.schedule_run(chain.pool["id"], pasteurizer_id="PAST-01")
        short = fx.schedule_run(chain.pool["id"], pasteurizer_id="PAST-02")

        fx.add_readings(on_bound["id"], HOLD_1800)
        fx.add_readings(short["id"], HOLD_1799)

        on_bound = fx.complete_run(on_bound["id"])
        short = fx.complete_run(short["id"])

        assert A.expected_longest_hold_seconds(HOLD_1800) == 1800
        assert A.expected_longest_hold_seconds(HOLD_1799) == 1799
        A.assert_run(
            on_bound,
            pasteurizer_id="PAST-01",
            run_status=RunStatus.COMPLETED,
            thermal_status=ThermalStatus.PASSED,
            longest_hold_seconds=C.THERMAL_PASS_HOLD_SECONDS,
            peak_celsius=64.0,
            reading_count=4,
            completed_by_user_id=TECHNICIAN_ID,
            version=6,
        )
        A.assert_run(
            short,
            pasteurizer_id="PAST-02",
            run_status=RunStatus.COMPLETED,
            thermal_status=ThermalStatus.FAILED,
            longest_hold_seconds=1799,
            peak_celsius=64.0,
            reading_count=4,
            completed_by_user_id=TECHNICIAN_ID,
            version=6,
        )
        A.assert_instant_equals(on_bound["completed_at"], RUN_CLOCK, "completed_at")
        A.assert_instant_equals(short["completed_at"], RUN_CLOCK, "completed_at")

    def test_the_run_one_second_short_cannot_be_bottled_at_all(self):
        """A bottling request that both names a thermally failed run and asks
        for far more milk than the pool holds reports the state gate, because a
        failed run never reaches the volume arithmetic — while the run that held
        the full 1800 seconds bottles the pool.

        PRD: "Bottling is the technician's act of turning a heat-treated pool into addressable inventory, and it is admitted only while the run's `thermal_status` is `PASSED`; a thermally failed run is refused at the state gate with `ERR_RUN_STATE_INVALID` and never reaches the volume arithmetic."
        PRD: "**Bottling a lot** enforces the run's state gate — which is where a thermally failed run is refused — before the pool-volume ceiling (`ERR_BOTTLING_EXCEEDS_POOL_VOLUME`)."

        Design: Difficulty/boundary_precision_check/thermal_hold_exact_1800_seconds
        """
        chain = _canonical_chain(run=None)
        fx.set_clock(RUN_CLOCK)
        on_bound = fx.schedule_run(chain.pool["id"], pasteurizer_id="PAST-01")
        short = fx.schedule_run(chain.pool["id"], pasteurizer_id="PAST-02")
        fx.add_readings(on_bound["id"], HOLD_1800)
        fx.add_readings(short["id"], HOLD_1799)
        fx.complete_run(on_bound["id"])
        fx.complete_run(short["id"])

        refused = validate_error(
            api_client.bottle_lot(short["id"], f.milk_lot(200, 250), TECHNICIAN_HEADERS),
            ApiErrorId.RUN_STATE_INVALID.value,
            409,
        )
        assert refused["error_id"] != ApiErrorId.BOTTLING_EXCEEDS_POOL_VOLUME.value

        lot = validate_success(
            api_client.bottle_lot(on_bound["id"], f.milk_lot(21, 100), TECHNICIAN_HEADERS), 201
        )
        A.assert_milk_lot(
            lot,
            lot_code="20260810-001-01",
            total_volume_ml=2100,
            release_status=LotReleaseStatus.HOLD,
        )
        A.assert_run(fx.get_run(short["id"]), run_status=RunStatus.COMPLETED, reading_count=4)

        still_refused = validate_error(
            api_client.bottle_lot(short["id"], f.milk_lot(1, 20), TECHNICIAN_HEADERS),
            ApiErrorId.RUN_STATE_INVALID.value,
            409,
        )
        assert still_refused["error_id"] == ApiErrorId.RUN_STATE_INVALID.value
        rows, meta = validate_paginated(
            api_client.list_milk_lots(QA_RELEASER_HEADERS, {"run_id": short["id"]})
        )
        assert meta["total_count"] == 0 and rows == []


class TestLotReleaseReadsItsOwnRunsEligibility:
    """Releasing a lot is guarded across an entity boundary: the gate is the
    eligibility of the run that produced that very lot."""

    def test_an_uncultured_run_blocks_its_lot_until_the_plate_is_read(self):
        """The bottled lot cannot be released while its run's culture is still
        NOT_COLLECTED; recording a no-growth culture makes the run eligible and
        the very same request then succeeds.

        PRD: "A `QualityAssuranceOfficer` releases it, moving it `HOLD → RELEASED`, and the release is guarded across an entity boundary: the lot's own run must sit at `release_eligibility` `ELIGIBLE`, meaning both `thermal_status` and `culture_status` are `PASSED`. A run whose culture is still `NOT_COLLECTED` is not eligible, and the refusal is `ERR_RUN_NOT_RELEASE_ELIGIBLE`."
        PRD: "On success `released_at` is stamped with the clock instant, `released_by_user_id` with the acting officer's `X-User-ID`, and the lot's `version` increases by 1."

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_run_release_eligible
        """
        chain = _canonical_chain(run={}, lots=[(21, 100)], culture=None, release=False)
        lot_id = chain.lots[0]["id"]
        A.assert_run(
            chain.run,
            thermal_status=ThermalStatus.PASSED,
            culture_status=CultureStatus.NOT_COLLECTED,
            release_eligibility=ReleaseEligibility.BLOCKED,
        )

        validate_error(
            api_client.release_milk_lot(lot_id, QA_RELEASER_HEADERS),
            ApiErrorId.RUN_NOT_RELEASE_ELIGIBLE.value,
            409,
        )
        blocked = fx.get_lot(lot_id)
        A.assert_milk_lot(
            blocked, release_status=LotReleaseStatus.HOLD, available_ml=2100, version=1
        )
        assert blocked["released_at"] is None
        assert blocked["released_by_user_id"] is None

        cultured = fx.record_culture(chain.run["id"], 0, C.NO_GROWTH_ORGANISM)
        assert cultured["release_eligibility"] == ReleaseEligibility.ELIGIBLE

        released = validate_success(api_client.release_milk_lot(lot_id, QA_RELEASER_HEADERS))
        A.assert_milk_lot(
            released,
            release_status=LotReleaseStatus.RELEASED,
            released_by_user_id=QA_RELEASER_ID,
            available_ml=2100,
            version=2,
        )
        A.assert_instant_equals(released["released_at"], RUN_CLOCK, "released_at")

    def test_one_runs_culture_does_not_unlock_another_runs_lot(self):
        """Two pools are pasteurized on two machines and both are bottled, but
        only the first run's culture is recorded. The first lot releases; the
        second is refused, because eligibility is read from its own run.

        PRD: "A `QualityAssuranceOfficer` releases it, moving it `HOLD → RELEASED`, and the release is guarded across an entity boundary: the lot's own run must sit at `release_eligibility` `ELIGIBLE`, meaning both `thermal_status` and `culture_status` are `PASSED`. A run whose culture is still `NOT_COLLECTED` is not eligible, and the refusal is `ERR_RUN_NOT_RELEASE_ELIGIBLE`."
        PRD: "**Releasing a lot** enforces the lot's state gate, then the run's release eligibility (`ERR_RUN_NOT_RELEASE_ELIGIBLE`), then segregation of duties (`ERR_SOD_RELEASE_CONFLICT`)."

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_run_release_eligible
        """
        first_pool, second_pool = _two_committed_pools(500)
        fx.set_clock(RUN_CLOCK)
        first_run = fx.schedule_run(first_pool["id"], pasteurizer_id="PAST-01")
        second_run = fx.schedule_run(second_pool["id"], pasteurizer_id="PAST-02")
        fx.add_readings(first_run["id"], HOLD_1800)
        fx.add_readings(second_run["id"], HOLD_1800)
        fx.complete_run(first_run["id"])
        fx.complete_run(second_run["id"])

        first_lot = fx.bottle_lot(first_run["id"], 15, 100)
        second_lot = fx.bottle_lot(second_run["id"], 15, 100)
        assert first_lot["lot_code"] == "20260810-001-01"
        assert second_lot["lot_code"] == "20260810-002-01"

        fx.record_culture(first_run["id"], 0, C.NO_GROWTH_ORGANISM)
        assert fx.get_run(first_run["id"])["release_eligibility"] == ReleaseEligibility.ELIGIBLE
        assert fx.get_run(second_run["id"])["release_eligibility"] == ReleaseEligibility.BLOCKED

        validate_error(
            api_client.release_milk_lot(second_lot["id"], QA_RELEASER_HEADERS),
            ApiErrorId.RUN_NOT_RELEASE_ELIGIBLE.value,
            409,
        )
        A.assert_milk_lot(
            fx.get_lot(second_lot["id"]), release_status=LotReleaseStatus.HOLD, version=1
        )

        released = validate_success(
            api_client.release_milk_lot(first_lot["id"], QA_RELEASER_HEADERS)
        )
        A.assert_milk_lot(
            released,
            release_status=LotReleaseStatus.RELEASED,
            released_by_user_id=QA_RELEASER_ID,
            total_volume_ml=1500,
            available_ml=1500,
            version=2,
        )


class TestSchedulingRequiresACommittedPool:
    """Scheduling reads the pool's state before it reads the machine's diary."""

    def test_a_balanced_but_uncommitted_pool_cannot_be_loaded(self):
        """The pool is balanced at 2100 ml from three donors but has never been
        committed, so scheduling is refused and no run row is created; the
        commit makes the identical request succeed.

        PRD: "The pool must be `COMMITTED`; any other pool state is refused as `ERR_POOL_STATE_INVALID`."
        PRD: "A new run is born in `SCHEDULED` at `version` 1, with `thermal_status` `PENDING`, `culture_status` `NOT_COLLECTED`, `release_eligibility` `BLOCKED`, `reading_count` 0, and null `longest_hold_seconds`, `peak_celsius`, `completed_at`, `completed_by_user_id`, `culture_cfu_per_ml`, `culture_organism` and `culture_recorded_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/run_schedule_requires_pool_committed
        """
        chain = _canonical_chain(commit=False)
        A.assert_pool(
            chain.pool,
            status=PoolStatus.BALANCED,
            total_volume_ml=2100,
            distinct_donor_count=3,
            projected_kcal_per_oz=20.14,
        )

        fx.set_clock(RUN_CLOCK)
        validate_error(
            api_client.create_run(
                f.pasteurization_run(chain.pool["id"]), TECHNICIAN_HEADERS
            ),
            ApiErrorId.POOL_STATE_INVALID.value,
            409,
        )
        _rows, meta = validate_paginated(
            api_client.list_runs(TECHNICIAN_HEADERS, {"pool_id": chain.pool["id"]})
        )
        assert meta["total_count"] == 0

        committed = fx.commit_pool(chain.pool["id"])
        assert committed["status"] == PoolStatus.COMMITTED

        run = validate_success(
            api_client.create_run(
                f.pasteurization_run(chain.pool["id"]), TECHNICIAN_HEADERS
            ),
            201,
        )
        A.assert_run(
            run,
            pool_id=chain.pool["id"],
            pasteurizer_id="PAST-01",
            cycle_minutes=60,
            run_status=RunStatus.SCHEDULED,
            thermal_status=ThermalStatus.PENDING,
            culture_status=CultureStatus.NOT_COLLECTED,
            release_eligibility=ReleaseEligibility.BLOCKED,
            reading_count=0,
            version=1,
        )
        for field in (
            "longest_hold_seconds",
            "peak_celsius",
            "completed_at",
            "completed_by_user_id",
            "culture_cfu_per_ml",
            "culture_organism",
            "culture_recorded_by_user_id",
        ):
            assert run[field] is None, f"a new run should carry a null {field}"

    def test_neither_a_draft_pool_nor_a_scrapped_one_can_be_loaded(self):
        """A 1200-millilitre draft pool is refused at the state gate, and after
        it is scrapped — a terminal state — the same request is refused again.

        PRD: "The pool must be `COMMITTED`; any other pool state is refused as `ERR_POOL_STATE_INVALID`."
        PRD: "The pool lands in `SCRAPPED` — a terminal state, alongside `PASTEURIZED` and `SCRAPPED_CULTURE` — and its `version` increases by 1."
        PRD: "And because the state gate precedes every safety, temporal and quantity rule, an operation attempted against a terminal row never reaches the interesting rules at all."

        Design: Difficulty/cross_entity_state_dependency/run_schedule_requires_pool_committed
        """
        chain = _uniform_chain(volume_each=400, commit=False)
        A.assert_pool(
            chain.pool,
            status=PoolStatus.DRAFT,
            total_volume_ml=1200,
            distinct_donor_count=3,
            projected_kcal_per_oz=20.0,
        )

        fx.set_clock(RUN_CLOCK)
        validate_error(
            api_client.create_run(f.pasteurization_run(chain.pool["id"]), TECHNICIAN_HEADERS),
            ApiErrorId.POOL_STATE_INVALID.value,
            409,
        )

        scrapped = fx.scrap_pool(chain.pool["id"])
        A.assert_pool(
            scrapped,
            status=PoolStatus.SCRAPPED,
            total_volume_ml=0,
            distinct_donor_count=0,
            projected_kcal_per_oz=None,
        )

        validate_error(
            api_client.create_run(f.pasteurization_run(chain.pool["id"]), TECHNICIAN_HEADERS),
            ApiErrorId.POOL_STATE_INVALID.value,
            409,
        )
        _rows, meta = validate_paginated(
            api_client.list_runs(TECHNICIAN_HEADERS, {"pool_id": chain.pool["id"]})
        )
        assert meta["total_count"] == 0


class TestPasteurizerSlotIsHalfOpenAroundTheCleaningBuffer:
    """A machine is occupied for its cycle plus a fifteen-minute cleaning buffer,
    and the interval's ending instant is free."""

    def test_the_buffer_end_is_free_one_minute_before_it_is_not_and_the_next_machine_is(self):
        """A run at 09:00 with a 60-minute cycle occupies PAST-01 until 10:15.
        10:14 on that machine is refused, 10:14 on PAST-02 is admitted, and
        10:15 on PAST-01 — the open endpoint — is admitted.

        PRD: "A run occupies its machine for its cycle **plus** a fifteen-minute cleaning buffer, so its occupied interval begins at `scheduled_start_at` and ends `cycle_minutes` plus 15 minutes later."
        PRD: "That interval is **half-open**: the ending instant itself is not occupied, so a run that starts exactly when a previous run's buffer ends is permitted."
        PRD: "A new run whose interval overlaps the interval of any other run on the same `pasteurizer_id` whose `run_status` is `SCHEDULED`, `IN_PROGRESS`, `COMPLETED` or `BOTTLED` is refused with `ERR_PASTEURIZER_SLOT_CONFLICT`; a `VOIDED` run occupies nothing, which is precisely why scrapping a pool frees the slot."

        Design: Difficulty/resource_temporal_overlap/pasteurizer_half_open_slot_with_cleaning_buffer
        """
        chain = _canonical_chain(run=None)
        fx.set_clock("2026-08-10T08:00:00Z")
        incumbent = fx.schedule_run(
            chain.pool["id"],
            pasteurizer_id="PAST-01",
            scheduled_start_at="2026-08-10T09:00:00Z",
            cycle_minutes=60,
        )
        assert A.occupied_interval_end("2026-08-10T09:00:00Z", 60) == A.parse_instant(
            "2026-08-10T10:15:00Z"
        )

        validate_error(
            api_client.create_run(
                f.pasteurization_run(
                    chain.pool["id"],
                    pasteurizer_id="PAST-01",
                    scheduled_start_at="2026-08-10T10:14:00Z",
                ),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.PASTEURIZER_SLOT_CONFLICT.value,
            409,
        )

        other_machine = validate_success(
            api_client.create_run(
                f.pasteurization_run(
                    chain.pool["id"],
                    pasteurizer_id="PAST-02",
                    scheduled_start_at="2026-08-10T10:14:00Z",
                ),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        A.assert_run(
            other_machine, pasteurizer_id="PAST-02", run_status=RunStatus.SCHEDULED, version=1
        )
        A.assert_instant_equals(
            other_machine["scheduled_start_at"], "2026-08-10T10:14:00Z", "scheduled_start_at"
        )

        on_the_endpoint = validate_success(
            api_client.create_run(
                f.pasteurization_run(
                    chain.pool["id"],
                    pasteurizer_id="PAST-01",
                    scheduled_start_at="2026-08-10T10:15:00Z",
                ),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        A.assert_run(
            on_the_endpoint, pasteurizer_id="PAST-01", run_status=RunStatus.SCHEDULED, version=1
        )
        A.assert_instant_equals(
            on_the_endpoint["scheduled_start_at"], "2026-08-10T10:15:00Z", "scheduled_start_at"
        )

        A.assert_run(
            fx.get_run(incumbent["id"]), run_status=RunStatus.SCHEDULED, reading_count=0, version=1
        )
        _rows, meta = validate_paginated(
            api_client.list_runs(TECHNICIAN_HEADERS, {"pasteurizer_id": "PAST-01"})
        )
        assert meta["total_count"] == 2
        A.assert_pool(fx.get_pool(chain.pool["id"]), status=PoolStatus.COMMITTED)

    def test_an_earlier_run_may_end_where_the_incumbent_begins_and_a_void_frees_the_slot(self):
        """A candidate whose own buffer ends exactly at 09:00 fits in front of
        the 09:00 incumbent, one that ends at 09:15 does not, and scrapping the
        incumbent's pool voids its run and hands the 09:00 slot back.

        PRD: "That interval is **half-open**: the ending instant itself is not occupied, so a run that starts exactly when a previous run's buffer ends is permitted."
        PRD: "A new run whose interval overlaps the interval of any other run on the same `pasteurizer_id` whose `run_status` is `SCHEDULED`, `IN_PROGRESS`, `COMPLETED` or `BOTTLED` is refused with `ERR_PASTEURIZER_SLOT_CONFLICT`; a `VOIDED` run occupies nothing, which is precisely why scrapping a pool frees the slot."
        PRD: "Any `PasteurizationRun` of that pool whose `run_status` is `SCHEDULED` or `IN_PROGRESS` moves to `VOIDED`, which frees its occupied interval on the pasteurizer so a later run may take the slot."

        Design: Difficulty/resource_temporal_overlap/pasteurizer_half_open_slot_with_cleaning_buffer
        """
        first_pool, second_pool = _two_committed_pools(500)
        fx.set_clock("2026-08-10T07:00:00Z")
        incumbent = fx.schedule_run(
            first_pool["id"],
            pasteurizer_id="PAST-01",
            scheduled_start_at="2026-08-10T09:00:00Z",
            cycle_minutes=60,
        )

        validate_error(
            api_client.create_run(
                f.pasteurization_run(
                    second_pool["id"],
                    pasteurizer_id="PAST-01",
                    scheduled_start_at="2026-08-10T08:30:00Z",
                    cycle_minutes=30,
                ),
                TECHNICIAN_HEADERS,
            ),
            ApiErrorId.PASTEURIZER_SLOT_CONFLICT.value,
            409,
        )

        in_front = validate_success(
            api_client.create_run(
                f.pasteurization_run(
                    second_pool["id"],
                    pasteurizer_id="PAST-01",
                    scheduled_start_at="2026-08-10T08:00:00Z",
                    cycle_minutes=45,
                ),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        assert A.occupied_interval_end("2026-08-10T08:00:00Z", 45) == A.parse_instant(
            "2026-08-10T09:00:00Z"
        )
        A.assert_run(in_front, run_status=RunStatus.SCHEDULED, cycle_minutes=45, version=1)

        scrapped = fx.scrap_pool(first_pool["id"])
        assert scrapped["status"] == PoolStatus.SCRAPPED
        A.assert_run(fx.get_run(incumbent["id"]), run_status=RunStatus.VOIDED)

        reclaimed = validate_success(
            api_client.create_run(
                f.pasteurization_run(
                    second_pool["id"],
                    pasteurizer_id="PAST-01",
                    scheduled_start_at="2026-08-10T09:00:00Z",
                    cycle_minutes=60,
                ),
                TECHNICIAN_HEADERS,
            ),
            201,
        )
        A.assert_run(reclaimed, run_status=RunStatus.SCHEDULED, version=1)

        _rows, meta = validate_paginated(
            api_client.list_runs(TECHNICIAN_HEADERS, {"pasteurizer_id": "PAST-01"})
        )
        assert meta["total_count"] == 3
        _scheduled, scheduled_meta = validate_paginated(
            api_client.list_runs(
                TECHNICIAN_HEADERS,
                {"pasteurizer_id": "PAST-01", "run_status": RunStatus.SCHEDULED},
            )
        )
        assert scheduled_meta["total_count"] == 2


class TestTemperatureReadingIsAnImmutableEventRecord:
    """A chart reading is written once and never updated: the only write path is
    the append endpoint, and the row exposes no mutation counter."""

    def test_the_chart_rows_carry_a_derived_flag_and_no_version(self):
        """Two samples are on file, one inside the holding band and one below
        it. The list returns both in ascending offset order with their derived
        `qualifies` flags and the recording technician, and — as an
        immutable-by-design event record — neither row carries `updated_at` or
        `version`.

        PRD: "Six resources are immutable-by-design records of a single event and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from their representations: `HealthHistoryQuestionnaire`, `SerologyPanel`, `PhysicianApproval`, `PoolComponent`, `TemperatureReading` and `DeferralEvent`."
        PRD: "Datalogger samples arrive one at a time from the technician, each carrying an `offset_seconds` between 0 and 14400 measured from the start of the heating cycle and a `celsius` bath temperature between 0.0 and 90.0 recorded to one decimal place, with the acting technician kept as `recorded_by_user_id`."
        PRD: "A run's temperature readings: `offset_seconds` ascending."

        Design: Corner/entities/temperature_reading_is_immutable_and_exposes_no_version
        """
        chain = _canonical_chain(run={}, readings=[(0, 63.0), (600, 62.0)], complete=False)

        rows, meta = validate_paginated(
            api_client.list_readings(chain.run["id"], TECHNICIAN_HEADERS)
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
        A.assert_ordered_by(rows, "offset_seconds")
        A.assert_reading(
            rows[0],
            offset_seconds=0,
            celsius=63.0,
            qualifies=True,
            recorded_by_user_id=TECHNICIAN_ID,
        )
        A.assert_reading(
            rows[1],
            offset_seconds=600,
            celsius=62.0,
            qualifies=False,
            recorded_by_user_id=TECHNICIAN_ID,
        )
        for row in rows:
            assert "version" not in row
            assert "updated_at" not in row
        assert A.reading_qualifies(62.0) is False
        assert A.reading_qualifies(63.0) is True

        A.assert_run(
            fx.get_run(chain.run["id"]),
            run_status=RunStatus.IN_PROGRESS,
            reading_count=2,
            peak_celsius=63.0,
            thermal_status=ThermalStatus.PENDING,
        )


class TestCompletingARunStoresEveryVerificationOutput:
    """One complete call applies the whole thermal side effect at once."""

    def test_the_four_reading_curve_lands_all_of_the_completion_fields(self):
        """Every gap in the curve is exactly ten minutes, which the closed bound
        admits, so the certified segment spans the full 1800 seconds and the run
        stores the verdict, the peak, the stamp and the acting technician —
        while eligibility stays blocked on the uncollected culture.

        PRD: "Either way the run advances `IN_PROGRESS → COMPLETED` — physical progress does not depend on the thermal verdict — `peak_celsius` reflects the maximum `celsius` over the run's samples, `completed_at` is stamped with the clock instant, `completed_by_user_id` with the acting technician's `X-User-ID`, `release_eligibility` is recomputed, and the run's `version` increases by 1."
        PRD: "`thermal_status` becomes `PASSED` when `longest_hold_seconds` is 1800 seconds or more, and `FAILED` otherwise."
        PRD: "`release_eligibility` is `ELIGIBLE` if and only if `thermal_status` is `PASSED` **and** `culture_status` is `PASSED`, and `BLOCKED` in every other combination — including the very common case of a thermally passed run whose culture is still `NOT_COLLECTED`."

        Design: Corner/state_machines/run_complete_stores_every_thermal_verification_output
        """
        chain = _canonical_chain(run={}, readings=HOLD_1800, complete=False)
        A.assert_run(chain.run, run_status=RunStatus.IN_PROGRESS, reading_count=4, version=5)

        completed = validate_success(api_client.complete_run(chain.run["id"], TECHNICIAN_HEADERS))
        A.assert_run(
            completed,
            run_status=RunStatus.COMPLETED,
            longest_hold_seconds=A.expected_longest_hold_seconds(HOLD_1800),
            thermal_status=ThermalStatus.PASSED,
            peak_celsius=64.0,
            reading_count=4,
            completed_by_user_id=TECHNICIAN_ID,
            culture_status=CultureStatus.NOT_COLLECTED,
            release_eligibility=ReleaseEligibility.BLOCKED,
            version=6,
        )
        assert completed["longest_hold_seconds"] == 1800
        A.assert_instant_equals(completed["completed_at"], RUN_CLOCK, "completed_at")
        A.assert_pool(fx.get_pool(chain.pool["id"]), status=PoolStatus.COMMITTED)


class TestUnmonitoredGapBreaksTheCertifiedSegment:
    """A gap of more than ten minutes cannot be certified even when the samples
    on both sides of it are in band."""

    def test_a_single_601_second_gap_restarts_the_hold_at_the_later_sample(self):
        """Five in-band samples span 2401 seconds, but the first gap is 601
        seconds long, so the certified segment opens at 601 and the longest hold
        is 1800 — not the 2401 an implementation that ignored the gap would
        report.

        PRD: "Otherwise, if this sample's `offset_seconds` minus the `offset_seconds` of the sample **immediately preceding it in the walk** is greater than 600 seconds, the segment is restarted at this sample's offset — an unmonitored gap of more than ten minutes cannot be certified even when the samples on both sides of it qualify — and the longest hold is not updated in that step."
        PRD: "After the last sample, the surviving longest hold is stored as `longest_hold_seconds`, a whole number of seconds; the longest hold is therefore a property of the worst dip in the curve, not of the total time spent in band."

        Design: Corner/calculations/thermal_gap_of_601_seconds_restarts_the_hold_segment
        """
        curve = ((0, 63.0), (601, 63.4), (1201, 63.6), (1801, 63.8), (2401, 64.0))
        chain = _uniform_chain(run={}, readings=curve, complete=False)

        completed = fx.complete_run(chain.run["id"])
        assert A.expected_longest_hold_seconds(curve) == 2401 - 601 == 1800
        A.assert_run(
            completed,
            run_status=RunStatus.COMPLETED,
            reading_count=5,
            longest_hold_seconds=1800,
            thermal_status=ThermalStatus.PASSED,
            peak_celsius=64.0,
            release_eligibility=ReleaseEligibility.BLOCKED,
        )
        assert completed["longest_hold_seconds"] != 2401

        _rows, meta = validate_paginated(
            api_client.list_readings(chain.run["id"], TECHNICIAN_HEADERS, {"qualifies": "true"})
        )
        assert meta["total_count"] == 5


class TestHoldingBandIsClosedAtBothEnds:
    """62.5 and 65.0 both qualify; 62.4 and 65.1 do not."""

    def test_the_band_edges_qualify_and_the_neighbours_outside_them_do_not(self):
        """A curve of 62.4, 62.5, 65.0, 65.1 and 63.0 leaves one certified
        segment from 600 to 1200 seconds, so the hold is 600 seconds and the run
        fails thermally — while `peak_celsius` still reports the 65.1 reading
        that did not qualify.

        PRD: "Each sample's `qualifies` flag is derived at write time and is true exactly when its `celsius` lies inside the **closed** holding band from 62.5 through 65.0 degrees."
        PRD: "For each sample in turn: if the sample does not qualify, the current segment is discarded and no segment is open."
        PRD: "Each sample raises the run's `reading_count` by 1, refreshes `peak_celsius` to the maximum `celsius` across the run's samples, and increments the run's `version` by 1."

        Design: Corner/calculations/thermal_band_is_closed_at_62_5_and_65_0
        """
        chain = _uniform_chain(run={}, readings=[], complete=False)
        curve = ((0, 62.4), (600, 62.5), (1200, 65.0), (1800, 65.1), (2400, 63.0))
        expected_flags = (False, True, True, False, True)
        for (offset, celsius), qualifies in zip(curve, expected_flags):
            row = fx.add_reading(chain.run["id"], offset, celsius)
            A.assert_reading(row, offset_seconds=offset, celsius=celsius, qualifies=qualifies)
            assert A.reading_qualifies(celsius) is qualifies

        completed = fx.complete_run(chain.run["id"])
        A.assert_run(
            completed,
            run_status=RunStatus.COMPLETED,
            reading_count=5,
            longest_hold_seconds=A.expected_longest_hold_seconds(curve),
            thermal_status=ThermalStatus.FAILED,
            peak_celsius=65.1,
            release_eligibility=ReleaseEligibility.BLOCKED,
        )
        assert completed["longest_hold_seconds"] == 600

        rows, meta = validate_paginated(
            api_client.list_readings(chain.run["id"], QA_OFFICER_HEADERS, {"qualifies": "true"})
        )
        assert meta["total_count"] == 3
        assert [row["offset_seconds"] for row in rows] == [600, 1200, 2400]


class TestRunWriteGuardLadder:
    """The run's state gate outranks the reading-count rule, which outranks the
    strictly-increasing offset rule."""

    def test_state_then_reading_count_then_offset_sequence_then_state_again(self):
        """Completing a scheduled run reports the state gate, not the missing
        readings. One sample later the same call reports the reading count, a
        repeated offset is refused on sequence, and once the run is completed
        both a second completion and a further sample fall back to the state
        gate.

        PRD: "**Completing a run** enforces the run's state gate before the minimum-readings rule (`ERR_RUN_READINGS_INSUFFICIENT`)."
        PRD: "**Appending a reading** enforces the input ranges, then the run's state gate (`ERR_RUN_STATE_INVALID`), then the strictly-increasing offset rule (`ERR_READING_SEQUENCE_INVALID`)."
        PRD: "A sample's `offset_seconds` must be strictly greater than the `offset_seconds` of **every** sample already recorded for that run; an equal or lower offset is refused with `ERR_READING_SEQUENCE_INVALID`."
        PRD: "The first sample moves the run `SCHEDULED → IN_PROGRESS`; every later sample is admitted as the `IN_PROGRESS → IN_PROGRESS` self-loop."

        Design: Corner/validations/run_write_guard_ladder_state_then_reading_count_then_offset_sequence
        """
        chain = _uniform_chain(volume_each=1200, run={}, readings=[], complete=False)
        A.assert_pool(
            fx.get_pool(chain.pool["id"]),
            status=PoolStatus.COMMITTED,
            total_volume_ml=3600,
            distinct_donor_count=3,
            projected_kcal_per_oz=20.0,
        )
        run_id = chain.run["id"]

        too_early = validate_error(
            api_client.complete_run(run_id, TECHNICIAN_HEADERS),
            ApiErrorId.RUN_STATE_INVALID.value,
            409,
        )
        assert too_early["error_id"] != ApiErrorId.RUN_READINGS_INSUFFICIENT.value

        fx.add_reading(run_id, 0, 63.0)
        A.assert_run(
            fx.get_run(run_id), run_status=RunStatus.IN_PROGRESS, reading_count=1
        )

        validate_error(
            api_client.complete_run(run_id, TECHNICIAN_HEADERS),
            ApiErrorId.RUN_READINGS_INSUFFICIENT.value,
            409,
        )
        validate_error(
            api_client.append_reading(run_id, f.temperature_reading(0, 63.5), TECHNICIAN_HEADERS),
            ApiErrorId.READING_SEQUENCE_INVALID.value,
            409,
        )

        for offset, celsius in ((600, 63.2), (1200, 63.4), (1800, 63.1)):
            fx.add_reading(run_id, offset, celsius)

        completed = validate_success(api_client.complete_run(run_id, TECHNICIAN_HEADERS))
        A.assert_run(
            completed,
            run_status=RunStatus.COMPLETED,
            thermal_status=ThermalStatus.PASSED,
            longest_hold_seconds=1800,
            peak_celsius=63.4,
            reading_count=4,
            completed_by_user_id=TECHNICIAN_ID,
            culture_status=CultureStatus.NOT_COLLECTED,
            release_eligibility=ReleaseEligibility.BLOCKED,
            version=6,
        )
        A.assert_instant_equals(completed["completed_at"], RUN_CLOCK, "completed_at")

        validate_error(
            api_client.complete_run(run_id, TECHNICIAN_HEADERS),
            ApiErrorId.RUN_STATE_INVALID.value,
            409,
        )
        validate_error(
            api_client.append_reading(
                run_id, f.temperature_reading(2400, 63.0), TECHNICIAN_HEADERS
            ),
            ApiErrorId.RUN_STATE_INVALID.value,
            409,
        )

        rows, meta = validate_paginated(api_client.list_readings(run_id, TECHNICIAN_HEADERS))
        assert meta["total_count"] == 4
        assert [row["offset_seconds"] for row in rows] == [0, 600, 1200, 1800]


class TestBottlingHeadroomCountsEarlierLotsOfTheRun:
    """The volume ceiling is the pool's volume less what earlier lots of the same
    run already took."""

    def test_two_lots_exhaust_the_pool_and_a_third_is_refused(self):
        """A 3000-millilitre lot and then a 600-millilitre lot exactly drain a
        3600-millilitre pool, and one more bottle is refused. The second lot
        inherits the first lot's expiration date and differs only in the
        trailing lot-code segment.

        PRD: "Their product is the lot's `total_volume_ml`, and it may not exceed the pool's `total_volume_ml` less the pool's `bottled_volume_ml` — that is, the milk the pool still holds after accounting for whatever earlier lots of the same run already took. Exceeding it is `ERR_BOTTLING_EXCEEDS_POOL_VOLUME`."
        PRD: "Each new lot is born in `HOLD` with `dispensed_ml` 0 and `available_ml` equal to its `total_volume_ml`, and it freezes three values from the pool and run that produced it: `kcal_per_oz` copied from the pool's `projected_kcal_per_oz`, `milk_class` copied from the pool's `target_milk_class`, and `pasteurization_date` taken as the calendar date component of the run's `completed_at`."
        PRD: "A second or later lot of the same run is admitted as the `BOTTLED → BOTTLED` self-loop: it creates a further lot with the next `lot_sequence`, recomputes the pool's `bottled_volume_ml` and increments the pool's `version`, but performs no pool or component state change at all, because the pool is already `PASTEURIZED` and its components are already `CONSUMED_PASTEURIZED`."

        Design: Corner/validations/bottling_a_third_lot_beyond_the_pool_volume_counts_earlier_lots_of_the_run
        """
        chain = _uniform_chain(volume_each=1200, run={}, culture=None)
        A.assert_run(chain.run, run_status=RunStatus.COMPLETED, thermal_status=ThermalStatus.PASSED)

        expiration = A.expected_expiration_date(
            chain.run["completed_at"], "2026-07-10", INTAKE_DATE
        )
        assert expiration == A.add_days(RUN_DATE, C.PASTEURIZATION_SHELF_DAYS) == "2027-02-06"

        first = validate_success(
            api_client.bottle_lot(chain.run["id"], f.milk_lot(30, 100), TECHNICIAN_HEADERS), 201
        )
        A.assert_milk_lot(
            first,
            lot_code="20260810-001-01",
            lot_sequence=1,
            total_volume_ml=3000,
            available_ml=3000,
            dispensed_ml=0,
            expiration_date=expiration,
            pasteurization_date=RUN_DATE,
            kcal_per_oz=20.0,
            milk_class=MilkClass.TERM,
            release_status=LotReleaseStatus.HOLD,
            version=1,
        )

        second = validate_success(
            api_client.bottle_lot(chain.run["id"], f.milk_lot(6, 100), TECHNICIAN_HEADERS), 201
        )
        A.assert_milk_lot(
            second,
            lot_code="20260810-001-02",
            lot_sequence=2,
            total_volume_ml=600,
            available_ml=600,
            expiration_date=expiration,
            release_status=LotReleaseStatus.HOLD,
            version=1,
        )

        validate_error(
            api_client.bottle_lot(chain.run["id"], f.milk_lot(1, 100), TECHNICIAN_HEADERS),
            ApiErrorId.BOTTLING_EXCEEDS_POOL_VOLUME.value,
            409,
        )

        A.assert_pool(
            fx.get_pool(chain.pool["id"]),
            status=PoolStatus.PASTEURIZED,
            bottled_volume_ml=3600,
            total_volume_ml=3600,
            version=7,
        )
        A.assert_run(fx.get_run(chain.run["id"]), run_status=RunStatus.BOTTLED)

        _rows, meta = validate_paginated(
            api_client.list_milk_lots(QA_RELEASER_HEADERS, {"run_id": chain.run["id"]})
        )
        assert meta["total_count"] == 2
        for donation in chain.donations:
            A.assert_donation(
                fx.get_donation(donation["id"]),
                status=DonationStatus.PASTEURIZED,
                remaining_ml=0,
            )
