"""Dispensing: the nine-step fee, the discount tier read before the split, the
ordered safety gauntlet, the bank-wide neonatal reserve, the subsidy ledger and
the allocation cycle's deterministic waterfall.

Every lot here is bottled from a committed pool and released by a second quality
officer, because only a RELEASED lot may be drawn on. Orders are written by
u-presc-1 and filled by u-pharm-1, so the segregation-of-duties comparison a
fill makes between the two identities is always satisfied and never the reason
a request fails.
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
    PHARMACIST_HEADERS,
    PHARMACIST_ID,
    PRESCRIBER_HEADERS,
    PRESCRIBER_ID,
    QA_RELEASER_HEADERS,
    QA_RELEASER_ID,
)
from test_helpers.types import (
    ClinicalAcuity,
    DispenseStatus,
    LotReleaseStatus,
    MilkClass,
    PatientType,
    PrescriptionStatus,
    ProgramStatus,
)

INTAKE_CLOCK = C.CLOCK_INTAKE          # "2026-08-05T08:00:00Z"
INTAKE_DATE = C.CLOCK_INTAKE_DATE      # "2026-08-05"
RUN_CLOCK = C.CLOCK_RUN                # "2026-08-10T10:05:00Z"
RUN_DATE = C.CLOCK_RUN_DATE            # "2026-08-10"

# Every chain below is pasteurized on 2026-08-10 from milk expressed on
# 2026-07-10 and received on 2026-08-05, so the earliest of the three shelf-life
# ceilings is always the pasteurization one.
SHELF_LIFE_DATE = "2027-02-06"


def _uniform_chain(
    volume_each=1200,
    donor_count=3,
    kcal_per_oz=20.0,
    expressed_on="2026-07-10",
    **chain,
):
    """`donor_count` donors, one container each, all carrying the same assay so
    the pool's projected nutrition is exactly `kcal_per_oz`."""
    donors = [fx.donor_spec(index + 1) for index in range(donor_count)]
    containers = [
        fx.container_spec(
            index + 1,
            index,
            volume_each,
            kcal_per_oz=kcal_per_oz,
            expressed_on=expressed_on,
        )
        for index in range(donor_count)
    ]
    return fx.build_chain(donors=donors, containers=containers, **chain)


def _released_chain(lot_ml=1200, bottle_volume_ml=100, lots=None, **chain):
    """A thermally passing, culture-cleared run whose lots are bottled and
    released. The clock is left at the run's completion instant."""
    return _uniform_chain(
        run={},
        lots=lots or [(lot_ml // bottle_volume_ml, bottle_volume_ml)],
        **chain,
    )


def _canonical_chain(third_container=None, **chain):
    """The canonical three-donor TERM pool of 2100 ml at 20.14 kcal/oz, with the
    third container optionally re-specified so a shelf-life ceiling can bind."""
    containers = [dict(spec) for spec in fx.CANONICAL_CONTAINERS]
    if third_container:
        containers[2].update(third_container)
    return fx.build_chain(containers=containers, **chain)


def _order(
    code,
    prescribed_ml,
    patient_type=PatientType.NICU_INPATIENT,
    acuity=ClinicalAcuity.CRITICAL,
    needed_by_date="2026-09-01",
    **overrides,
):
    """One order submitted by u-presc-1."""
    return fx.submit_prescription(
        prescription_code=code,
        patient_reference=code,
        patient_type=patient_type,
        clinical_acuity=acuity,
        prescribed_ml=prescribed_ml,
        needed_by_date=needed_by_date,
        **overrides,
    )


def _fill_attempt(prescription_id, lot_id, volume_ml, expected_lot_version=None):
    """A fill request that is allowed to fail, carrying the lot's live
    concurrency token unless the caller pins an older one."""
    version = (
        expected_lot_version if expected_lot_version is not None else fx.lot_version(lot_id)
    )
    return api_client.create_dispense(
        prescription_id, f.dispense(lot_id, volume_ml, version), PHARMACIST_HEADERS
    )


def _prescription_dispenses(prescription_id, **params):
    return validate_paginated(
        api_client.list_prescription_dispenses(
            prescription_id, PHARMACIST_HEADERS, params or None
        )
    )


def _lot_dispenses(lot_id, **params):
    return validate_paginated(
        api_client.list_lot_dispenses(lot_id, PHARMACIST_HEADERS, params or None)
    )


def _volume_by_lot(rows):
    """The fills of one prescription keyed by the lot they drew from, which is
    how a cycle's draws are compared without leaning on any row order."""
    return {row["lot_id"]: row["volume_ml"] for row in rows}


class TestTheDiscountTierIsReadBeforeTheFillIsApplied:
    """Step two of the fee sequence reads the order's cumulative volume as it
    stood before the current draw, so the fill that crosses a break is still
    priced at the tier below it."""

    def test_two_earlier_fills_leave_the_third_below_the_first_discount_break(self):
        """One thousand millilitres and then eight hundred leave the order's
        cumulative volume at 1800, so the 300 ml fill that carries it to 2100 is
        still priced at 0.00 and costs 1440 cents rather than the 1368 a tier
        read after the addition would have produced.

        PRD: "**Step one:** the billable unit count is `volume_ml` divided by 100 and rounded **up** to the next whole unit, so 450 millilitres is 5 units and 500 millilitres is exactly 5."
        PRD: "**Step two:** the discount tier is read from the order's `cumulative_dispensed_ml` **as it stands before this fill** — 0.00 when that prior volume is strictly below 2000 millilitres, 0.05 when it is strictly below 5000, and 0.12 otherwise — and the chosen fraction is stored on the fill as `tier_discount_pct`. Reading the tier after adding the current volume would produce a different and incorrect fee."
        PRD: "**Step nine:** `payer_due_cents` is `gross_fee_cents` less `subsidy_cents`."
        PRD: "The lot's `dispensed_ml` rises by `volume_ml` and its `available_ml` falls correspondingly, moving it `RELEASED → EXHAUSTED` when `available_ml` reaches exactly 0, with a `version` increment."

        Design: Difficulty/combinatorial_formula/dispense_fee_tier_read_before_split
        """
        chain = _canonical_chain(run={}, lots=[(21, 100)])
        lot = chain.lots[0]
        A.assert_milk_lot(
            lot,
            lot_code="20260810-001-01",
            total_volume_ml=2100,
            available_ml=2100,
            kcal_per_oz=20.14,
            release_status=LotReleaseStatus.RELEASED,
            expiration_date=SHELF_LIFE_DATE,
        )

        program = fx.open_program(
            program_code="SUB-2026", coverage_pct=0.60, annual_cap_cents=100000
        )
        order = _order(
            "RX-0002",
            2100,
            needed_by_date="2026-08-20",
            subsidy_program_id=program["id"],
            subsidy_required=True,
        )

        first = fx.fill_prescription(order["id"], lot["id"], 1000)
        A.assert_dispense(
            first,
            volume_ml=1000,
            tier_discount_pct=0.00,
            gross_fee_cents=4800,
            subsidy_cents=2880,
            payer_due_cents=1920,
            status=DispenseStatus.DISPENSED,
            version=1,
        )
        second = fx.fill_prescription(order["id"], lot["id"], 800)
        A.assert_dispense(
            second,
            volume_ml=800,
            tier_discount_pct=0.00,
            gross_fee_cents=3840,
            subsidy_cents=2304,
            payer_due_cents=1536,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=5184, status=ProgramStatus.OPEN
        )
        assert fx.get_prescription(order["id"])["cumulative_dispensed_ml"] == 1800

        third = fx.fill_prescription(order["id"], lot["id"], 300)
        assert third["tier_discount_pct"] == 0.00, "1800 ml of prior volume is below 2000"
        A.assert_dispense(
            third,
            volume_ml=300,
            gross_fee_cents=1440,
            subsidy_cents=864,
            payer_due_cents=576,
            allocation_cycle_sequence=None,
            dispensed_by_user_id=PHARMACIST_ID,
        )
        assert third["gross_fee_cents"] != 1368, (
            "1368 cents is the fee a tier read after adding this fill would charge"
        )
        assert third["gross_fee_cents"] == A.expected_gross_fee_cents(
            300, 1800, PatientType.NICU_INPATIENT
        )

        A.assert_prescription(
            fx.get_prescription(order["id"]),
            cumulative_dispensed_ml=2100,
            remaining_ml=0,
            status=PrescriptionStatus.FILLED,
            waitlist_position=None,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=6048, status=ProgramStatus.OPEN
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            dispensed_ml=2100,
            available_ml=0,
            release_status=LotReleaseStatus.EXHAUSTED,
        )
        rows, meta = _prescription_dispenses(order["id"])
        assert meta["total_count"] == 3
        assert sum(row["gross_fee_cents"] for row in rows) == 4800 + 3840 + 1440

    def test_the_five_thousand_millilitre_break_is_read_the_same_way(self):
        """Four thousand nine hundred millilitres put the order into the 0.05
        band and no further: the next 200 ml fill is charged 912 cents on the
        pre-fill volume of 4900, not the 845 that reading 5100 would give, and
        only the fill after it reaches 0.12.

        PRD: "**Step two:** the discount tier is read from the order's `cumulative_dispensed_ml` **as it stands before this fill** — 0.00 when that prior volume is strictly below 2000 millilitres, 0.05 when it is strictly below 5000, and 0.12 otherwise — and the chosen fraction is stored on the fill as `tier_discount_pct`. Reading the tier after adding the current volume would produce a different and incorrect fee."
        PRD: "**Step five:** `gross_fee_cents` is the sum of base and handling multiplied by one minus the tier fraction, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/dispense_fee_tier_read_before_split
        """
        chain = _released_chain(lot_ml=6000, donor_count=5)
        lot = chain.lots[0]
        A.assert_pool(chain.pool, total_volume_ml=6000, distinct_donor_count=5)
        A.assert_milk_lot(lot, total_volume_ml=6000, available_ml=6000, kcal_per_oz=20.00)

        order = _order("RX-0005", 6000)

        first = fx.fill_prescription(order["id"], lot["id"], 4900)
        A.assert_dispense(
            first,
            volume_ml=4900,
            tier_discount_pct=0.00,
            gross_fee_cents=23520,
            subsidy_cents=0,
            payer_due_cents=23520,
        )

        second = fx.fill_prescription(order["id"], lot["id"], 200)
        A.assert_dispense(
            second,
            volume_ml=200,
            tier_discount_pct=0.05,
            gross_fee_cents=912,
            subsidy_cents=0,
            payer_due_cents=912,
        )
        assert second["gross_fee_cents"] != 845, (
            "845 cents is what the 0.12 tier would charge, and 5100 ml is a "
            "post-fill volume this fill may not see"
        )

        third = fx.fill_prescription(order["id"], lot["id"], 900)
        A.assert_dispense(
            third,
            volume_ml=900,
            tier_discount_pct=0.12,
            gross_fee_cents=3802,
            subsidy_cents=0,
            payer_due_cents=3802,
        )
        assert third["gross_fee_cents"] == A.expected_gross_fee_cents(
            900, 5100, PatientType.NICU_INPATIENT
        ), "4320 cents discounted by 0.12 rounds half up to 3802"

        A.assert_prescription(
            fx.get_prescription(order["id"]),
            cumulative_dispensed_ml=6000,
            remaining_ml=0,
            status=PrescriptionStatus.FILLED,
            waitlist_position=None,
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            dispensed_ml=6000,
            available_ml=0,
            release_status=LotReleaseStatus.EXHAUSTED,
        )


class TestShortDatedMilkIsRefusedBeforeTheSubsidyLedgerIsConsulted:
    """Two independent objections stand against the same fill: the lot is out of
    date and the program cannot afford the subsidy. The gauntlet reports the
    temporal one, because the date checks sit above the fiscal gates."""

    def test_a_short_dated_lot_is_refused_before_the_cap_that_could_not_pay(self):
        """A single container expressed on 2025-08-20 short-dates the lot to
        2026-08-20; with the clock at 2026-08-25 the fill is refused with
        ERR_LOT_EXPIRED and never reaches the 1000-cent cap that could not have
        covered its 1440-cent uncapped subsidy.

        PRD: "The gauntlet the request runs is ordered, and every step is observable, so a request that violates several rules at once reports only the earliest."
        PRD: "Then two date checks in fixed order — the lot's `expiration_date` must be on or after the clock date (`ERR_LOT_EXPIRED`), and only then the order's `needed_by_date` must be on or after the clock date (`ERR_PRESCRIPTION_PAST_NEEDED_BY`)."
        PRD: "Every milk lot whose `release_status` is `HOLD` and whose `expiration_date` has fallen strictly behind the new clock date becomes `EXPIRED`, while `RELEASED` and `EXHAUSTED` lots are deliberately left alone and refused at fill time instead."

        Design: Difficulty/priority_pair_validation_conflict/temporal_over_fiscal_on_dispense
        """
        chain = _canonical_chain(
            third_container={"expressed_on": "2025-08-20"}, run={}, lots=[(21, 100)]
        )
        lot = chain.lots[0]
        assert lot["expiration_date"] == A.add_days("2025-08-20", C.RAW_AGE_SHELF_DAYS)
        assert lot["expiration_date"] == "2026-08-20"

        fx.set_clock("2026-08-25T09:00:00Z")
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            release_status=LotReleaseStatus.RELEASED,
            available_ml=2100,
            dispensed_ml=0,
            expiration_date="2026-08-20",
        )

        program = fx.open_program(
            program_code="SUB-0002", coverage_pct=0.60, annual_cap_cents=1000
        )
        order = _order(
            "RX-0003",
            500,
            needed_by_date="2026-09-30",
            subsidy_program_id=program["id"],
            subsidy_required=True,
        )

        gross = A.expected_gross_fee_cents(500, 0, PatientType.NICU_INPATIENT)
        assert A.expected_uncapped_subsidy_cents(gross, 0.60) == 1440 > 1000, (
            "the fiscal gate would have refused this fill too, had it been reached"
        )

        refused = validate_error(
            _fill_attempt(order["id"], lot["id"], 500),
            ApiErrorId.LOT_EXPIRED.value,
            409,
        )
        assert refused["error_id"] != ApiErrorId.SUBSIDY_CAP_EXCEEDED.value

        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            available_ml=2100,
            dispensed_ml=0,
            release_status=LotReleaseStatus.RELEASED,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=0, status=ProgramStatus.OPEN
        )
        A.assert_prescription(
            fx.get_prescription(order["id"]),
            status=PrescriptionStatus.QUEUED,
            cumulative_dispensed_ml=0,
            remaining_ml=500,
            version=1,
        )
        rows, meta = _prescription_dispenses(order["id"])
        assert (rows, meta["total_count"]) == ([], 0)

    def test_the_cap_that_hid_behind_the_expiry_bites_once_the_lot_is_in_date(self):
        """With the clock left at 2026-08-10 the same lot passes the date check
        and the fiscal gate becomes visible: an order demanding its subsidy is
        refused with 402 because a partial subsidy is a rejection, while an order
        that merely permits one is filled with the subsidy clipped to the
        1000-cent headroom.

        PRD: "The two fiscal gates apply only when the order's `subsidy_required` flag is true, and only then. The linked program must exist and be `OPEN`, else `ERR_SUBSIDY_PROGRAM_EXHAUSTED`; and the program's remaining headroom, its `annual_cap_cents` less its `consumed_cents`, must be at least the full uncapped subsidy this fill would generate, else `ERR_SUBSIDY_CAP_EXCEEDED`. Both are reported with HTTP 402."
        PRD: "For such an order a partial subsidy is a rejection rather than a discount. When `subsidy_required` is false the same shortfall is not an error at all: the fill proceeds and the subsidy is simply clipped to the headroom."

        Design: Difficulty/priority_pair_validation_conflict/temporal_over_fiscal_on_dispense
        """
        chain = _canonical_chain(
            third_container={"expressed_on": "2025-08-20"}, run={}, lots=[(21, 100)]
        )
        lot = chain.lots[0]
        assert lot["expiration_date"] == "2026-08-20" >= RUN_DATE

        program = fx.open_program(
            program_code="SUB-0002", coverage_pct=0.60, annual_cap_cents=1000
        )
        strict = _order(
            "RX-0003",
            500,
            needed_by_date="2026-09-30",
            subsidy_program_id=program["id"],
            subsidy_required=True,
        )
        refused = validate_error(
            _fill_attempt(strict["id"], lot["id"], 500),
            ApiErrorId.SUBSIDY_CAP_EXCEEDED.value,
            402,
        )
        assert refused["error_id"] != ApiErrorId.LOT_EXPIRED.value

        permissive = _order(
            "RX-0004",
            500,
            needed_by_date="2026-09-30",
            subsidy_program_id=program["id"],
            subsidy_required=False,
        )
        filled = fx.fill_prescription(permissive["id"], lot["id"], 500)
        A.assert_dispense(
            filled,
            volume_ml=500,
            gross_fee_cents=2400,
            subsidy_cents=1000,
            payer_due_cents=1400,
            status=DispenseStatus.DISPENSED,
        )
        assert filled["subsidy_cents"] == A.expected_subsidy_cents(2400, 0.60, 1000)

        A.assert_subsidy_program(
            fx.get_program(program["id"]),
            consumed_cents=1000,
            status=ProgramStatus.EXHAUSTED,
        )
        A.assert_prescription(
            fx.get_prescription(strict["id"]),
            status=PrescriptionStatus.QUEUED,
            cumulative_dispensed_ml=0,
        )
        A.assert_prescription(
            fx.get_prescription(permissive["id"]),
            status=PrescriptionStatus.FILLED,
            cumulative_dispensed_ml=500,
            remaining_ml=0,
            waitlist_position=None,
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            available_ml=1600,
            dispensed_ml=500,
            release_status=LotReleaseStatus.RELEASED,
        )


class TestVoidingAFillPutsEveryLedgerBack:
    """A void is the compensating action for a fill: the milk, the charity money
    and the order's place in the queue all return, while the four priced figures
    stay on the voided row as the audit record."""

    def test_the_round_trip_restores_the_lot_the_program_and_the_queue(self):
        """A 500 ml fill priced 2400/1440/960 moves three ledgers; voiding it
        returns the lot to 2100 ml, the program to 0 consumed and the order to
        QUEUED at waitlist position 1, and a second void is refused.

        PRD: "The void moves the fill `DISPENSED → VOIDED` and reverses all three ledgers: the lot's `dispensed_ml` is credited back by `volume_ml`, raising `available_ml` and returning the lot `EXHAUSTED → RELEASED` when volume comes back; the program's `consumed_cents` is credited back by `subsidy_cents`, returning it `EXHAUSTED → OPEN` once it falls strictly below the cap; and the order's `cumulative_dispensed_ml` is lowered, its `remaining_ml` raised, and its status recomputed to `QUEUED` when `cumulative_dispensed_ml` has returned to exactly 0 and to `PARTIALLY_FILLED` otherwise — which is how a `FILLED` order re-enters the waitlist."
        PRD: "Crucially, the void does **not** zero `tier_discount_pct`, `gross_fee_cents`, `subsidy_cents` or `payer_due_cents`: those figures are retained on the voided row as the audit record of what was once charged."
        PRD: "Voiding is the compensating action, available to a `DispensingPharmacist` while the fill's `status` is `DISPENSED`; a fill already `VOIDED` or `RECALLED` cannot be voided again and is refused with `ERR_DISPENSE_STATE_INVALID`, and a fill whose lot has been recalled cannot be voided at all, because the recall cascade has already accounted for it."

        Design: Difficulty/compensating_invariant/subsidy_ledger_money_conservation_on_dispense_void
        """
        chain = _canonical_chain(run={}, lots=[(21, 100)])
        lot = chain.lots[0]
        program = fx.open_program(
            program_code="SUB-2026", coverage_pct=0.60, annual_cap_cents=100000
        )
        order = _order(
            "RX-0004",
            500,
            needed_by_date="2026-09-30",
            subsidy_program_id=program["id"],
            subsidy_required=True,
        )

        fill = fx.fill_prescription(order["id"], lot["id"], 500)
        A.assert_dispense(
            fill,
            volume_ml=500,
            tier_discount_pct=0.00,
            gross_fee_cents=2400,
            subsidy_cents=1440,
            payer_due_cents=960,
            status=DispenseStatus.DISPENSED,
            allocation_cycle_sequence=None,
            dispensed_by_user_id=PHARMACIST_ID,
            prescription_id=order["id"],
            lot_id=lot["id"],
            version=1,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=1440, status=ProgramStatus.OPEN
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            available_ml=1600,
            dispensed_ml=500,
            release_status=LotReleaseStatus.RELEASED,
        )
        A.assert_prescription(
            fx.get_prescription(order["id"]),
            status=PrescriptionStatus.FILLED,
            cumulative_dispensed_ml=500,
            remaining_ml=0,
            waitlist_position=None,
        )

        voided = fx.void_dispense(fill["id"])
        A.assert_dispense(
            voided,
            status=DispenseStatus.VOIDED,
            volume_ml=500,
            tier_discount_pct=0.00,
            gross_fee_cents=2400,
            subsidy_cents=1440,
            payer_due_cents=960,
        )
        assert voided["gross_fee_cents"] == voided["subsidy_cents"] + voided["payer_due_cents"]

        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=0, status=ProgramStatus.OPEN
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            available_ml=2100,
            dispensed_ml=0,
            release_status=LotReleaseStatus.RELEASED,
        )
        A.assert_prescription(
            fx.get_prescription(order["id"]),
            status=PrescriptionStatus.QUEUED,
            cumulative_dispensed_ml=0,
            remaining_ml=500,
            waitlist_position=1,
        )

        validate_error(
            api_client.void_dispense(fill["id"], PHARMACIST_HEADERS),
            ApiErrorId.DISPENSE_STATE_INVALID.value,
            409,
        )
        rows, meta = _prescription_dispenses(order["id"], status=DispenseStatus.VOIDED)
        assert meta["total_count"] == 1 and rows[0]["id"] == fill["id"]

    def test_a_void_reopens_a_program_that_the_fill_had_exhausted(self):
        """A fill landing exactly on a 1440-cent cap exhausts the program and
        empties the lot; the void returns both, and the identical fill can then
        be made again and priced from scratch at the same figures.

        PRD: "`EXHAUSTED` is not terminal: a voided fill that frees capacity returns the program to `OPEN`."
        PRD: "Thereafter `consumed_cents` is by definition the sum of `subsidy_cents` over every fill with `status` `DISPENSED` whose prescription names this program, and `status` is `OPEN` while `consumed_cents` is strictly below `annual_cap_cents` and `EXHAUSTED` once it reaches or passes it."
        PRD: "The invariant that `gross_fee_cents` equals `subsidy_cents` plus `payer_due_cents` holds after every fill by construction."

        Design: Difficulty/compensating_invariant/subsidy_ledger_money_conservation_on_dispense_void
        """
        chain = _released_chain(lot_ml=500, volume_each=500)
        lot = chain.lots[0]
        A.assert_pool(chain.pool, total_volume_ml=1500, bottled_volume_ml=500)

        program = fx.open_program(
            program_code="SUB-0001", coverage_pct=0.60, annual_cap_cents=1440
        )
        order = _order("RX-0006", 500, subsidy_program_id=program["id"], subsidy_required=True)

        fill = fx.fill_prescription(order["id"], lot["id"], 500)
        A.assert_dispense(
            fill, gross_fee_cents=2400, subsidy_cents=1440, payer_due_cents=960
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]),
            consumed_cents=1440,
            status=ProgramStatus.EXHAUSTED,
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            available_ml=0,
            dispensed_ml=500,
            release_status=LotReleaseStatus.EXHAUSTED,
        )

        fx.void_dispense(fill["id"])
        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=0, status=ProgramStatus.OPEN
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            available_ml=500,
            total_volume_ml=500,
            dispensed_ml=0,
            release_status=LotReleaseStatus.RELEASED,
        )
        A.assert_prescription(
            fx.get_prescription(order["id"]),
            status=PrescriptionStatus.QUEUED,
            cumulative_dispensed_ml=0,
            remaining_ml=500,
            waitlist_position=1,
        )

        again = fx.fill_prescription(order["id"], lot["id"], 500)
        A.assert_dispense(
            again,
            tier_discount_pct=0.00,
            gross_fee_cents=2400,
            subsidy_cents=1440,
            payer_due_cents=960,
            status=DispenseStatus.DISPENSED,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]),
            consumed_cents=1440,
            status=ProgramStatus.EXHAUSTED,
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            available_ml=0,
            release_status=LotReleaseStatus.EXHAUSTED,
        )
        rows, meta = _prescription_dispenses(order["id"])
        assert meta["total_count"] == 2
        assert {row["status"] for row in rows} == {
            DispenseStatus.VOIDED,
            DispenseStatus.DISPENSED,
        }
        live, live_meta = _prescription_dispenses(
            order["id"], status=DispenseStatus.DISPENSED
        )
        assert live_meta["total_count"] == 1 and live[0]["id"] == again["id"]


class TestAnOrderIsBornWithItsDeclaredDefaults:
    """The two optional flags and the program link are server-side defaults, and
    the tier and the waitlist rank are derived on the way in."""

    def test_a_minimal_order_lands_every_declared_default(self):
        """A body carrying neither flag nor program comes back with
        requires_preterm_milk and subsidy_required false, no program, tier 1,
        waitlist position 1 and version 1.

        PRD: "an optional `subsidy_program_id` naming an existing program, which when omitted means no subsidy applies at all"
        PRD: "an optional `requires_preterm_milk` flag defaulting to false; an optional `subsidy_required` flag defaulting to false; a `prescribed_ml` volume from 50 to 12000; and a `needed_by_date` calendar date."
        PRD: "The `priority_tier` is derived, not supplied, from the pair of enumerations: tier 1 for a `NICU_INPATIENT` patient at `CRITICAL` acuity, tier 2 for a `NICU_INPATIENT` patient at `STANDARD` acuity, and tier 3 for any `OUTPATIENT` patient, whose acuity is therefore irrelevant to rank."
        PRD: "The order is born `QUEUED` with `cumulative_dispensed_ml` 0, `remaining_ml` equal to `prescribed_ml`, `prescriber_user_id` stamped from the submitting operator's `X-User-ID`, and `version` 1."

        Design: Corner/entities/prescription_create_applies_declared_optional_defaults
        """
        fx.set_clock(INTAKE_CLOCK)
        payload = f.prescription(
            prescription_code="RX-0001",
            patient_reference="NICU-A1",
            patient_type=PatientType.NICU_INPATIENT,
            clinical_acuity=ClinicalAcuity.CRITICAL,
            prescribed_ml=500,
            needed_by_date="2026-12-01",
        )
        assert "requires_preterm_milk" not in payload
        assert "subsidy_required" not in payload
        assert "subsidy_program_id" not in payload

        order = validate_success(
            api_client.create_prescription(payload, PRESCRIBER_HEADERS), 201
        )
        A.assert_prescription(
            order,
            prescription_code="RX-0001",
            patient_reference="NICU-A1",
            patient_type=PatientType.NICU_INPATIENT,
            clinical_acuity=ClinicalAcuity.CRITICAL,
            prescribed_ml=500,
            needed_by_date="2026-12-01",
            requires_preterm_milk=False,
            subsidy_required=False,
            subsidy_program_id=None,
            priority_tier=1,
            cumulative_dispensed_ml=0,
            remaining_ml=500,
            waitlist_position=1,
            status=PrescriptionStatus.QUEUED,
            prescriber_user_id=PRESCRIBER_ID,
            version=1,
        )
        A.assert_prescription(fx.get_prescription(order["id"]), waitlist_position=1, version=1)


class TestTheTierBreakAtExactlyTwoThousandMillilitres:
    """Two thousand millilitres of prior volume is not strictly below 2000, so
    the fill that follows it is the first to be discounted."""

    def test_a_two_thousand_millilitre_prior_volume_lands_on_the_five_percent_tier(self):
        """A 2000 ml fill is charged the undiscounted 9600 cents; the 500 ml that
        follows it is charged 2280, which is 2400 less five per cent, and the
        program's coverage applies to both even though the order does not demand
        a subsidy.

        PRD: "**Step three:** the base charge is the unit count multiplied by 480 cents."
        PRD: "**Step two:** the discount tier is read from the order's `cumulative_dispensed_ml` **as it stands before this fill** — 0.00 when that prior volume is strictly below 2000 millilitres, 0.05 when it is strictly below 5000, and 0.12 otherwise — and the chosen fraction is stored on the fill as `tier_discount_pct`. Reading the tier after adding the current volume would produce a different and incorrect fee."
        PRD: "**Step six:** the coverage fraction is the program's `coverage_pct` when a program is linked and its `status` is `OPEN`, and zero in every other case — no program linked, or a linked program that is `EXHAUSTED`."

        Design: Corner/calculations/dispense_fee_tier_boundary_at_exactly_2000_prior_ml
        """
        chain = _released_chain(lot_ml=3000)
        lot = chain.lots[0]
        A.assert_milk_lot(
            lot,
            lot_code="20260810-001-01",
            total_volume_ml=3000,
            available_ml=3000,
            kcal_per_oz=20.00,
            expiration_date=SHELF_LIFE_DATE,
            milk_class=MilkClass.TERM,
        )

        program = fx.open_program(
            program_code="SUB-0001", coverage_pct=0.60, annual_cap_cents=100000
        )
        order = _order(
            "RX-0001", 2500, subsidy_program_id=program["id"], subsidy_required=False
        )

        first = fx.fill_prescription(order["id"], lot["id"], 2000)
        A.assert_dispense(
            first,
            volume_ml=2000,
            tier_discount_pct=0.00,
            gross_fee_cents=9600,
            subsidy_cents=5760,
            payer_due_cents=3840,
            allocation_cycle_sequence=None,
        )
        second = fx.fill_prescription(order["id"], lot["id"], 500)
        A.assert_dispense(
            second,
            volume_ml=500,
            tier_discount_pct=0.05,
            gross_fee_cents=2280,
            subsidy_cents=1368,
            payer_due_cents=912,
        )
        assert second["gross_fee_cents"] == A.expected_gross_fee_cents(
            500, 2000, PatientType.NICU_INPATIENT
        )

        A.assert_prescription(
            fx.get_prescription(order["id"]),
            cumulative_dispensed_ml=2500,
            remaining_ml=0,
            status=PrescriptionStatus.FILLED,
            waitlist_position=None,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=7128, status=ProgramStatus.OPEN
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            dispensed_ml=2500,
            available_ml=500,
            release_status=LotReleaseStatus.RELEASED,
        )


class TestTheCycleDrainsTierOneBeforeTheReserveStopsTierThree:
    """The reserve is re-measured before every draw, so a tier-1 order that eats
    the bank down to the floor leaves the tier-3 order behind it nothing."""

    def test_the_tier_one_draw_eats_the_spare_the_outpatient_order_needed(self):
        """One cycle over a single 3600 ml lot fills the 1200 ml tier-1 order and
        gives the 500 ml outpatient order nothing at all, because 2400 ml less
        the 3000 ml reserve floors at zero.

        PRD: "Those prescriptions form three buckets by `priority_tier`, and the buckets are drained strictly in order — tier 1 first, then tier 2, then tier 3 — with no bucket touched until the bucket above it can absorb no further milk."
        PRD: "For tier 1 and tier 2 that permitted volume is the lot's whole `available_ml`. For tier 3 it is additionally clipped by the bank-wide neonatal reserve: before **every** individual draw the cycle re-measures the total `available_ml` across every lot whose `release_status` is `RELEASED` — including lots this prescription itself cannot use — subtracts 3000 millilitres, floors the result at 0, and takes the lesser of that spare volume and the lot's own `available_ml`."
        PRD: "A computed draw of 0 is not an error inside a cycle: that lot is skipped and the walk continues."

        Design: Corner/calculations/allocation_cycle_tier1_drains_before_the_nicu_reserve_wall_stops_tier3
        """
        chain = _released_chain(lot_ml=3600)
        lot = chain.lots[0]
        A.assert_bank_available_ml(fx.list_milk_lots(), 3600)

        nicu = _order("RX-0001", 1200)
        outpatient = _order(
            "RX-0002",
            500,
            patient_type=PatientType.OUTPATIENT,
            acuity=ClinicalAcuity.STANDARD,
            needed_by_date="2026-08-25",
        )

        fx.run_allocation_cycle()

        rows, meta = _prescription_dispenses(nicu["id"])
        assert meta["total_count"] == 1
        A.assert_dispense(
            rows[0],
            volume_ml=1200,
            tier_discount_pct=0.00,
            gross_fee_cents=5760,
            subsidy_cents=0,
            payer_due_cents=5760,
            allocation_cycle_sequence=1,
            dispensed_by_user_id=PHARMACIST_ID,
            status=DispenseStatus.DISPENSED,
            lot_id=lot["id"],
        )
        A.assert_prescription(
            fx.get_prescription(nicu["id"]),
            status=PrescriptionStatus.FILLED,
            cumulative_dispensed_ml=1200,
            remaining_ml=0,
            waitlist_position=None,
            priority_tier=1,
        )

        assert max(0, 2400 - C.NICU_RESERVE_ML) == 0, "the reserve leaves no spare volume"
        starved, starved_meta = _prescription_dispenses(outpatient["id"])
        assert (starved, starved_meta["total_count"]) == ([], 0)
        A.assert_prescription(
            fx.get_prescription(outpatient["id"]),
            status=PrescriptionStatus.QUEUED,
            cumulative_dispensed_ml=0,
            remaining_ml=500,
            waitlist_position=1,
            priority_tier=3,
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            dispensed_ml=1200,
            available_ml=2400,
            release_status=LotReleaseStatus.RELEASED,
        )


class TestTheDispenseGuardLadder:
    """Milk class, then the order's own outstanding volume, then the lot's: the
    three refusals arrive in the declared order against one released lot."""

    def test_class_then_prescription_remaining_then_lot_available(self):
        """A preterm-only order is refused on the TERM lot's class; an order for
        2100 ml against 2000 outstanding is refused on its own remaining volume
        before the lot is consulted; 1500 ml is then refused on the lot's 1200;
        and the exact 1200 ml fill is priced at 5760 cents.

        PRD: "Then suitability: when the order's `requires_preterm_milk` is true the lot's `milk_class` must be exactly `PRETERM`, and a `TERM` or `MIXED` lot is refused with `ERR_LOT_MILK_CLASS_UNSUITABLE`; when the flag is false any class is acceptable."
        PRD: "Then two volume ceilings, again in fixed order: `volume_ml` may not exceed the order's `remaining_ml` (`ERR_DISPENSE_EXCEEDS_PRESCRIPTION_REMAINING`), and then may not exceed the lot's `available_ml` (`ERR_DISPENSE_EXCEEDS_LOT_AVAILABLE`)."
        PRD: "it moves `QUEUED → PARTIALLY_FILLED` when the fill leaves volume outstanding"

        Design: Corner/validations/dispense_guard_ladder_milk_class_then_prescription_remaining_then_lot_available
        """
        chain = _released_chain(lot_ml=1200)
        lot = chain.lots[0]
        assert lot["milk_class"] == MilkClass.TERM

        preterm_only = _order("RX-1001", 1200, requires_preterm_milk=True)
        flexible = _order(
            "RX-1002", 2000, acuity=ClinicalAcuity.STANDARD, requires_preterm_milk=False
        )

        validate_error(
            _fill_attempt(preterm_only["id"], lot["id"], 1200),
            ApiErrorId.LOT_MILK_CLASS_UNSUITABLE.value,
            409,
        )
        validate_error(
            _fill_attempt(flexible["id"], lot["id"], 2100),
            ApiErrorId.DISPENSE_EXCEEDS_PRESCRIPTION_REMAINING.value,
            409,
        )
        on_the_lot = validate_error(
            _fill_attempt(flexible["id"], lot["id"], 1500),
            ApiErrorId.DISPENSE_EXCEEDS_LOT_AVAILABLE.value,
            409,
        )
        assert (
            on_the_lot["error_id"]
            != ApiErrorId.DISPENSE_EXCEEDS_PRESCRIPTION_REMAINING.value
        ), "1500 ml is inside the order's 2000 ml but beyond the lot's 1200"

        fill = fx.fill_prescription(flexible["id"], lot["id"], 1200)
        A.assert_dispense(
            fill,
            volume_ml=1200,
            tier_discount_pct=0.00,
            gross_fee_cents=5760,
            subsidy_cents=0,
            payer_due_cents=5760,
            allocation_cycle_sequence=None,
            dispensed_by_user_id=PHARMACIST_ID,
            status=DispenseStatus.DISPENSED,
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            dispensed_ml=1200,
            available_ml=0,
            release_status=LotReleaseStatus.EXHAUSTED,
        )
        A.assert_prescription(
            fx.get_prescription(flexible["id"]),
            cumulative_dispensed_ml=1200,
            remaining_ml=800,
            status=PrescriptionStatus.PARTIALLY_FILLED,
            waitlist_position=1,
            priority_tier=2,
        )
        A.assert_prescription(
            fx.get_prescription(preterm_only["id"]),
            status=PrescriptionStatus.QUEUED,
            cumulative_dispensed_ml=0,
            priority_tier=1,
            waitlist_position=1,
        )
        rows, meta = _prescription_dispenses(flexible["id"])
        assert meta["total_count"] == 1 and rows[0]["id"] == fill["id"]


class TestTheNeonatalReserveIsABankWideAggregate:
    """The reserve counts every released millilitre in the bank, so its refusal
    has nothing to do with how much the addressed lot holds."""

    def test_a_twenty_millilitre_outpatient_draw_is_refused_at_the_floor(self):
        """Against a single 3600 ml lot a 700 ml outpatient fill is refused
        because it would leave 2900; the identical 700 ml NICU fill is not
        subject to the check at all; and afterwards even 20 ml is still refused
        against a lot holding 2900.

        PRD: "The next gate is the neonatal reserve. When the order's `priority_tier` is 3, the bank must still hold at least 3000 millilitres of `available_ml` summed across **all** `RELEASED` lots after this fill would be applied; otherwise the fill is refused with `ERR_NICU_RESERVE_PROTECTED`."
        PRD: "Because the reserve is a bank-wide aggregate rather than a per-lot floor, a twenty-millilitre outpatient fill against a lot holding two litres is still refused when the bank as a whole is close to the floor, and no tier-1 or tier-2 fill is ever subject to the check."
        PRD: "**Step four:** a handling charge of 350 cents is added only when the order's `patient_type` is `OUTPATIENT`, and is zero for `NICU_INPATIENT`."

        Design: Corner/validations/outpatient_fill_refused_by_the_bank_wide_nicu_reserve_however_small
        """
        chain = _released_chain(lot_ml=3600)
        lot = chain.lots[0]
        A.assert_bank_available_ml(fx.list_milk_lots(), 3600)

        outpatient = _order(
            "RX-2001",
            700,
            patient_type=PatientType.OUTPATIENT,
            acuity=ClinicalAcuity.STANDARD,
        )
        nicu = _order("RX-2002", 700)

        assert 3600 - 700 < C.NICU_RESERVE_ML
        validate_error(
            _fill_attempt(outpatient["id"], lot["id"], 700),
            ApiErrorId.NICU_RESERVE_PROTECTED.value,
            409,
        )

        fill = fx.fill_prescription(nicu["id"], lot["id"], 700)
        A.assert_dispense(
            fill,
            volume_ml=700,
            gross_fee_cents=3360,
            subsidy_cents=0,
            payer_due_cents=3360,
            status=DispenseStatus.DISPENSED,
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            dispensed_ml=700,
            available_ml=2900,
            release_status=LotReleaseStatus.RELEASED,
        )
        A.assert_prescription(
            fx.get_prescription(nicu["id"]),
            status=PrescriptionStatus.FILLED,
            remaining_ml=0,
            waitlist_position=None,
        )
        A.assert_bank_available_ml(fx.list_milk_lots(), 2900)

        validate_error(
            _fill_attempt(outpatient["id"], lot["id"], 20),
            ApiErrorId.NICU_RESERVE_PROTECTED.value,
            409,
        )
        A.assert_prescription(
            fx.get_prescription(outpatient["id"]),
            status=PrescriptionStatus.QUEUED,
            cumulative_dispensed_ml=0,
            priority_tier=3,
            waitlist_position=1,
        )
        starved, starved_meta = _prescription_dispenses(outpatient["id"])
        assert (starved, starved_meta["total_count"]) == ([], 0)
        rows, meta = _lot_dispenses(lot["id"])
        assert meta["total_count"] == 1 and rows[0]["id"] == fill["id"]


class TestAProgramThatLandsExactlyOnItsCap:
    """Exhausting a program is not the end of its usefulness: it stops paying,
    and what that means depends on whether the order demanded a subsidy."""

    def test_a_fill_that_spends_the_last_cent_then_behaves_two_different_ways(self):
        """A 100 ml fill on a 288-cent cap consumes it exactly and flips the
        program to EXHAUSTED; the next order that demands a subsidy is refused
        with 402, while an order on the same program that merely permits one is
        filled at coverage zero and pays the whole 480 cents.

        PRD: "The program's `consumed_cents` rises by `subsidy_cents`, flipping it `OPEN → EXHAUSTED` once the cap is reached or passed, with a `version` increment."
        PRD: "The two fiscal gates apply only when the order's `subsidy_required` flag is true, and only then. The linked program must exist and be `OPEN`, else `ERR_SUBSIDY_PROGRAM_EXHAUSTED`; and the program's remaining headroom, its `annual_cap_cents` less its `consumed_cents`, must be at least the full uncapped subsidy this fill would generate, else `ERR_SUBSIDY_CAP_EXCEEDED`. Both are reported with HTTP 402."
        PRD: "**Step six:** the coverage fraction is the program's `coverage_pct` when a program is linked and its `status` is `OPEN`, and zero in every other case — no program linked, or a linked program that is `EXHAUSTED`."

        Design: Corner/validations/subsidy_program_exhausts_exactly_at_its_cap_and_then_behaves_two_different_ways
        """
        chain = _released_chain(lot_ml=1200)
        lot = chain.lots[0]
        program = fx.open_program(
            program_code="SUB-0001",
            name="Community Milk Fund",
            coverage_pct=0.60,
            annual_cap_cents=288,
        )
        A.assert_subsidy_program(program, consumed_cents=0, status=ProgramStatus.OPEN, version=1)

        demanding = _order(
            "RX-3001", 200, subsidy_program_id=program["id"], subsidy_required=True
        )
        also_demanding = _order(
            "RX-3002", 100, subsidy_program_id=program["id"], subsidy_required=True
        )
        permissive = _order(
            "RX-3003",
            100,
            acuity=ClinicalAcuity.STANDARD,
            subsidy_program_id=program["id"],
            subsidy_required=False,
        )

        assert (
            A.expected_uncapped_subsidy_cents(480, 0.60) == program["annual_cap_cents"] == 288
        ), "the uncapped subsidy equals the whole headroom, so nothing is clipped"
        first = fx.fill_prescription(demanding["id"], lot["id"], 100)
        A.assert_dispense(
            first,
            volume_ml=100,
            tier_discount_pct=0.00,
            gross_fee_cents=480,
            subsidy_cents=288,
            payer_due_cents=192,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]),
            consumed_cents=288,
            status=ProgramStatus.EXHAUSTED,
        )

        validate_error(
            _fill_attempt(also_demanding["id"], lot["id"], 100),
            ApiErrorId.SUBSIDY_PROGRAM_EXHAUSTED.value,
            402,
        )
        A.assert_prescription(
            fx.get_prescription(also_demanding["id"]),
            status=PrescriptionStatus.QUEUED,
            cumulative_dispensed_ml=0,
        )

        unsubsidised = fx.fill_prescription(permissive["id"], lot["id"], 100)
        A.assert_dispense(
            unsubsidised,
            volume_ml=100,
            tier_discount_pct=0.00,
            gross_fee_cents=480,
            subsidy_cents=0,
            payer_due_cents=480,
            status=DispenseStatus.DISPENSED,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]),
            consumed_cents=288,
            status=ProgramStatus.EXHAUSTED,
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            dispensed_ml=200,
            available_ml=1000,
            release_status=LotReleaseStatus.RELEASED,
        )
        A.assert_prescription(
            fx.get_prescription(demanding["id"]),
            status=PrescriptionStatus.PARTIALLY_FILLED,
            remaining_ml=100,
        )
        A.assert_prescription(
            fx.get_prescription(permissive["id"]),
            status=PrescriptionStatus.FILLED,
            remaining_ml=0,
            waitlist_position=None,
        )


class TestFillTimeGuardsOnTheOrderAndTheLot:
    """A needed-by date behind the clock is only caught at fill time, a cancelled
    order is caught by its state gate, and a released lot cannot be released
    twice."""

    def test_a_back_dated_order_a_cancelled_order_and_a_second_release_are_refused(self):
        """An order written with needed_by 2026-08-05 while the clock reads
        2026-08-10 is accepted and only refused when filled; an order whose
        needed-by equals the clock date is filled; cancelling twice and filling a
        cancelled order both report the prescription's state gate; and releasing
        the lot again reports the lot's.

        PRD: "Then two date checks in fixed order — the lot's `expiration_date` must be on or after the clock date (`ERR_LOT_EXPIRED`), and only then the order's `needed_by_date` must be on or after the clock date (`ERR_PRESCRIPTION_PAST_NEEDED_BY`)."
        PRD: "A `Prescriber` may cancel an order whose `status` is `QUEUED` or `PARTIALLY_FILLED`, moving it to `CANCELLED`; any other status is refused with `ERR_PRESCRIPTION_STATE_INVALID`. Cancellation clears `waitlist_position` to null, renumbers the bucket and increments `version` by 1; beyond the role gate no further identity comparison is imposed on it."
        PRD: "Then the prescription's `status` must be `QUEUED` or `PARTIALLY_FILLED`, else `ERR_PRESCRIPTION_STATE_INVALID`."
        PRD: "**Releasing a lot** enforces the lot's state gate, then the run's release eligibility (`ERR_RUN_NOT_RELEASE_ELIGIBLE`), then segregation of duties (`ERR_SOD_RELEASE_CONFLICT`)."

        Design: Corner/validations/fill_time_guards_reject_a_back_dated_order_a_cancelled_order_and_a_second_release
        """
        chain = _released_chain(lot_ml=1200)
        lot = chain.lots[0]

        back_dated = _order("RX-5001", 200, needed_by_date="2026-08-05")
        A.assert_prescription(
            back_dated, status=PrescriptionStatus.QUEUED, needed_by_date="2026-08-05", version=1
        )
        on_the_day = _order("RX-5002", 200, needed_by_date=RUN_DATE)
        doomed = _order("RX-5003", 200, needed_by_date="2026-09-01")

        refused = validate_error(
            _fill_attempt(back_dated["id"], lot["id"], 100),
            ApiErrorId.PRESCRIPTION_PAST_NEEDED_BY.value,
            409,
        )
        assert refused["error_id"] != ApiErrorId.PRESCRIPTION_STATE_INVALID.value
        A.assert_prescription(
            fx.get_prescription(back_dated["id"]), status=PrescriptionStatus.QUEUED
        )

        fill = fx.fill_prescription(on_the_day["id"], lot["id"], 100)
        A.assert_dispense(
            fill,
            volume_ml=100,
            gross_fee_cents=480,
            subsidy_cents=0,
            payer_due_cents=480,
        )
        A.assert_prescription(
            fx.get_prescription(on_the_day["id"]),
            status=PrescriptionStatus.PARTIALLY_FILLED,
            remaining_ml=100,
        )

        cancelled = fx.cancel_prescription(doomed["id"])
        # RX-5003 is on its third version: born at 1, then bumped when the fill
        # of RX-5002 dropped that order's `remaining_ml` and renumbered the
        # tier-1 bucket underneath it (a derived-field-only mutation still
        # increments, PRD 2.4), and now again by the cancellation itself.
        A.assert_prescription(
            cancelled,
            status=PrescriptionStatus.CANCELLED,
            waitlist_position=None,
            version=3,
        )
        validate_error(
            api_client.cancel_prescription(doomed["id"], PRESCRIBER_HEADERS),
            ApiErrorId.PRESCRIPTION_STATE_INVALID.value,
            409,
        )
        validate_error(
            _fill_attempt(doomed["id"], lot["id"], 100),
            ApiErrorId.PRESCRIPTION_STATE_INVALID.value,
            409,
        )
        validate_error(
            api_client.release_milk_lot(lot["id"], QA_RELEASER_HEADERS),
            ApiErrorId.LOT_STATE_INVALID.value,
            409,
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            available_ml=1100,
            release_status=LotReleaseStatus.RELEASED,
            released_by_user_id=QA_RELEASER_ID,
        )

        # The two live tier-1 orders are ranked created_at ascending and then by
        # remaining volume descending, which puts the untouched 200 ml order
        # ahead of the one already partly filled either way.
        A.assert_prescription(
            fx.get_prescription(back_dated["id"]), waitlist_position=1, priority_tier=1
        )
        A.assert_prescription(
            fx.get_prescription(on_the_day["id"]), waitlist_position=2, priority_tier=1
        )
        rows, meta = validate_paginated(
            api_client.list_prescriptions(
                PRESCRIBER_HEADERS, {"status": PrescriptionStatus.CANCELLED}
            )
        )
        assert meta["total_count"] == 1
        assert [row["prescription_code"] for row in rows] == ["RX-5003"]


class TestTheConcurrencyParentOfAFillIsTheLot:
    """The token a fill carries belongs to the lot, and the lot's version moves
    once per accepted fill — so a replayed token is refused."""

    def test_the_replayed_token_is_refused_and_the_fresh_one_lands_the_same_draw(self):
        """The first 300 ml draw is accepted on the lot's live version; replaying
        that same version is refused with 412 and draws no milk and prices no
        fee; the re-read version lands an identical 300 ml draw.

        PRD: "Creating a fill against a prescription requires `expected_lot_version` to equal the current `version` of the `MilkLot` named by `lot_id` — note that the concurrency parent here is the lot, not the prescription — and is otherwise rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a pharmacist from committing a volume decision taken against an `available_ml` snapshot that a prior fill, a void or an allocation cycle has already changed."
        PRD: "Thereafter a lot's `dispensed_ml` is the sum of `volume_ml` across the fills against it whose `status` is `DISPENSED`, and its `available_ml` is its `total_volume_ml` less that figure."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_lot_version_refuses_the_second_fill_then_the_fresh_version_lands_it
        """
        chain = _released_chain(lot_ml=1200)
        lot = chain.lots[0]
        order = _order("RX-8201", 1200)

        first_version = fx.lot_version(lot["id"])
        first = validate_success(
            _fill_attempt(order["id"], lot["id"], 300, expected_lot_version=first_version), 201
        )
        A.assert_dispense(
            first,
            volume_ml=300,
            gross_fee_cents=1440,
            subsidy_cents=0,
            payer_due_cents=1440,
        )

        validate_error(
            _fill_attempt(order["id"], lot["id"], 300, expected_lot_version=first_version),
            ApiErrorId.STALE_VERSION.value,
            412,
        )
        after_first = fx.get_lot(lot["id"])
        assert after_first["version"] == first_version + 1
        A.assert_milk_lot(after_first, available_ml=900, dispensed_ml=300)

        second = validate_success(
            _fill_attempt(
                order["id"], lot["id"], 300, expected_lot_version=after_first["version"]
            ),
            201,
        )
        A.assert_dispense(second, volume_ml=300, gross_fee_cents=1440, tier_discount_pct=0.00)

        after_second = fx.get_lot(lot["id"])
        assert after_second["version"] == first_version + 2
        A.assert_milk_lot(
            after_second,
            available_ml=600,
            dispensed_ml=600,
            release_status=LotReleaseStatus.RELEASED,
        )
        rows, meta = _prescription_dispenses(order["id"])
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}
        assert all(
            row["status"] == DispenseStatus.DISPENSED
            and row["allocation_cycle_sequence"] is None
            for row in rows
        )
        A.assert_prescription(
            fx.get_prescription(order["id"]),
            cumulative_dispensed_ml=600,
            remaining_ml=600,
            status=PrescriptionStatus.PARTIALLY_FILLED,
            waitlist_position=1,
        )


class TestTheCycleBreaksAnExpirationTieOnTheEmptierLot:
    """Two lots of one run share an expiration date, so first-expiring-first-out
    cannot separate them and the next key, available volume ascending, decides."""

    def test_a_shared_expiration_date_sends_the_cycle_to_the_smaller_lot_first(self):
        """Both lots of the run expire on 2027-02-06, so the 500 ml order is
        filled from the 600 ml lot rather than the 1200 ml one; the next cycle
        drains that smaller lot to zero before touching the larger, which a
        lot-code-first selector would have reversed.

        PRD: "Those lots are consumed first-expiring-first-out: `expiration_date` ascending, then `available_ml` ascending, then `lot_code` ascending. The secondary key means that among two lots dated the same day the emptier one is drained first, which retires nearly-empty lots rather than fragmenting fresh ones."
        PRD: "For each prescription in turn the cycle walks its eligible lots in that order, stopping as soon as the order's `remaining_ml` reaches 0 or as soon as it has drawn from three distinct lots — three is the hard per-prescription, per-cycle lot cap, and an order needing more milk than three lots can give simply waits for the next cycle."
        PRD: "each created fill carries `allocation_cycle_sequence` stamped with the cycle's monotonic counter, which is what distinguishes machine-allocated volume from hand-dispensed volume in the audit trail"

        Design: Corner/cross_cutting_complexity_layers/selector_policy_fefo_tie_is_broken_by_smaller_available_volume_before_lot_code
        """
        chain = _released_chain(lots=[(12, 100), (6, 100)])
        larger, smaller = chain.lots[0], chain.lots[1]
        A.assert_milk_lot(
            larger,
            lot_code="20260810-001-01",
            total_volume_ml=1200,
            expiration_date=SHELF_LIFE_DATE,
        )
        A.assert_milk_lot(
            smaller,
            lot_code="20260810-001-02",
            total_volume_ml=600,
            expiration_date=SHELF_LIFE_DATE,
        )
        assert larger["expiration_date"] == smaller["expiration_date"]
        assert larger["lot_code"] < smaller["lot_code"]

        first_order = _order("RX-8301", 500)
        fx.run_allocation_cycle()

        rows, meta = _prescription_dispenses(first_order["id"])
        assert meta["total_count"] == 1
        A.assert_dispense(
            rows[0],
            lot_id=smaller["id"],
            volume_ml=500,
            gross_fee_cents=2400,
            allocation_cycle_sequence=1,
        )
        assert rows[0]["lot_id"] != larger["id"], (
            "the 600 ml lot is drained before the 1200 ml lot on an expiration tie"
        )
        A.assert_prescription(
            fx.get_prescription(first_order["id"]),
            status=PrescriptionStatus.FILLED,
            cumulative_dispensed_ml=500,
            remaining_ml=0,
            waitlist_position=None,
        )
        A.assert_milk_lot(fx.get_lot(smaller["id"]), available_ml=100, dispensed_ml=500)
        A.assert_milk_lot(fx.get_lot(larger["id"]), available_ml=1200, dispensed_ml=0)

        second_order = _order("RX-8302", 800)
        fx.run_allocation_cycle()

        rows, meta = _prescription_dispenses(second_order["id"])
        assert meta["total_count"] == 2
        assert _volume_by_lot(rows) == {smaller["id"]: 100, larger["id"]: 700}
        assert len(_volume_by_lot(rows)) <= C.ALLOCATION_LOT_CAP_PER_PRESCRIPTION
        by_lot = {row["lot_id"]: row for row in rows}
        A.assert_dispense(
            by_lot[smaller["id"]], volume_ml=100, gross_fee_cents=480, allocation_cycle_sequence=2
        )
        A.assert_dispense(
            by_lot[larger["id"]], volume_ml=700, gross_fee_cents=3360, allocation_cycle_sequence=2
        )

        A.assert_milk_lot(
            fx.get_lot(smaller["id"]),
            available_ml=0,
            dispensed_ml=600,
            release_status=LotReleaseStatus.EXHAUSTED,
        )
        A.assert_milk_lot(
            fx.get_lot(larger["id"]),
            available_ml=500,
            dispensed_ml=700,
            release_status=LotReleaseStatus.RELEASED,
        )
        A.assert_prescription(
            fx.get_prescription(second_order["id"]),
            status=PrescriptionStatus.FILLED,
            cumulative_dispensed_ml=800,
            remaining_ml=0,
            waitlist_position=None,
        )


class TestCancellingRenumbersOnlyItsOwnBucket:
    """Waitlist positions are ranked inside a tier bucket, so closing a tier-3
    order renumbers tier 3 and leaves tier 1 alone."""

    def test_the_middle_outpatient_order_closes_and_its_bucket_renumbers(self):
        """Three outpatient orders and one NICU order sit on an empty bank;
        cancelling the second outpatient order clears its position, renumbers the
        survivors 1 and 2, and leaves the NICU order at position 1 of its own
        bucket.

        PRD: "`waitlist_position` is a bucket-local rank, not a bank-wide one: within the set of prescriptions sharing this order's `priority_tier` whose `status` is `QUEUED` or `PARTIALLY_FILLED`, rows are ordered by `created_at` ascending, then by `remaining_ml` descending, then by `prescription_code` ascending, and each is given its 1-based position in that order."
        PRD: "Two tier-1 orders and two tier-3 orders therefore both produce positions 1 and 2 — the number alone says nothing about how soon milk arrives. A prescription in any terminal status carries `waitlist_position` null."
        PRD: "Cancellation clears `waitlist_position` to null, renumbers the bucket and increments `version` by 1; beyond the role gate no further identity comparison is imposed on it."

        Design: Corner/endpoints/prescription_cancel_action_recomputes_only_its_own_tier_bucket
        """
        fx.set_clock(INTAKE_CLOCK)
        outpatient_one = _order(
            "RX-7001",
            500,
            patient_type=PatientType.OUTPATIENT,
            acuity=ClinicalAcuity.STANDARD,
        )
        outpatient_two = _order(
            "RX-7002",
            500,
            patient_type=PatientType.OUTPATIENT,
            acuity=ClinicalAcuity.STANDARD,
        )
        outpatient_three = _order(
            "RX-7003",
            500,
            patient_type=PatientType.OUTPATIENT,
            acuity=ClinicalAcuity.STANDARD,
        )
        nicu = _order("RX-7004", 500)
        A.assert_prescription(nicu, priority_tier=1, waitlist_position=1)
        A.assert_prescription(outpatient_three, priority_tier=3, waitlist_position=3)

        cancelled = fx.cancel_prescription(outpatient_two["id"])
        A.assert_prescription(
            cancelled,
            status=PrescriptionStatus.CANCELLED,
            waitlist_position=None,
            version=2,
        )

        A.assert_prescription(
            fx.get_prescription(outpatient_one["id"]),
            waitlist_position=1,
            priority_tier=3,
            status=PrescriptionStatus.QUEUED,
        )
        A.assert_prescription(
            fx.get_prescription(outpatient_three["id"]),
            waitlist_position=2,
            priority_tier=3,
            status=PrescriptionStatus.QUEUED,
        )
        A.assert_prescription(
            fx.get_prescription(nicu["id"]), waitlist_position=1, priority_tier=1
        )

        queued, queued_meta = validate_paginated(
            api_client.list_prescriptions(
                PRESCRIBER_HEADERS,
                {"priority_tier": 3, "status": PrescriptionStatus.QUEUED},
            )
        )
        assert queued_meta["total_count"] == 2
        assert [row["prescription_code"] for row in queued] == ["RX-7001", "RX-7003"]
        closed, closed_meta = validate_paginated(
            api_client.list_prescriptions(
                PRESCRIBER_HEADERS, {"status": PrescriptionStatus.CANCELLED}
            )
        )
        assert closed_meta["total_count"] == 1
        assert closed[0]["prescription_code"] == "RX-7002"


class TestOneCycleFillsTierOneAndLeavesATierThreeRemainder:
    """A cycle prices each draw exactly as a manual fill would, and a second
    cycle over the same state is entitled to create nothing at all."""

    def test_the_outpatient_order_gets_only_the_spare_above_the_reserve(self):
        """One cycle over 4600 ml fills the 1200 ml tier-1 order outright and
        gives the tier-3 order the 400 ml of spare above the reserve, charged
        2270 cents including the outpatient handling fee; a second cycle sees no
        spare and creates no fill.

        PRD: "Every draw creates a fill exactly as a manual fill would, priced independently through the nine steps of §3.9 and applying the same ledger consequences to the lot, the subsidy program and the prescription."
        PRD: "**Step four:** a handling charge of 350 cents is added only when the order's `patient_type` is `OUTPATIENT`, and is zero for `NICU_INPATIENT`."
        PRD: "Waitlist positions are **not** renumbered after each individual fill during a cycle; they are recomputed exactly once, at the end of the cycle, across every prescription still `QUEUED` or `PARTIALLY_FILLED`, using the same bucket and within-bucket ordering."

        Design: Corner/endpoints/allocation_cycle_bulk_run_fills_tier_one_then_leaves_a_tier_three_remainder
        """
        chain = _released_chain(lot_ml=4600, donor_count=4)
        lot = chain.lots[0]
        A.assert_pool(chain.pool, total_volume_ml=4800, distinct_donor_count=4)
        A.assert_milk_lot(lot, total_volume_ml=4600, available_ml=4600)
        A.assert_bank_available_ml(fx.list_milk_lots(), 4600)

        nicu = _order("RX-6001", 1200)
        outpatient = _order(
            "RX-6002",
            500,
            patient_type=PatientType.OUTPATIENT,
            acuity=ClinicalAcuity.STANDARD,
        )
        version_before = fx.lot_version(lot["id"])

        fx.run_allocation_cycle()

        nicu_rows, nicu_meta = _prescription_dispenses(nicu["id"])
        assert nicu_meta["total_count"] == 1
        A.assert_dispense(
            nicu_rows[0],
            volume_ml=1200,
            tier_discount_pct=0.00,
            gross_fee_cents=5760,
            subsidy_cents=0,
            payer_due_cents=5760,
            allocation_cycle_sequence=1,
        )
        out_rows, out_meta = _prescription_dispenses(outpatient["id"])
        assert out_meta["total_count"] == 1
        A.assert_dispense(
            out_rows[0],
            volume_ml=400,
            gross_fee_cents=2270,
            subsidy_cents=0,
            payer_due_cents=2270,
            allocation_cycle_sequence=1,
        )
        assert out_rows[0]["gross_fee_cents"] == A.expected_gross_fee_cents(
            400, 0, PatientType.OUTPATIENT
        ), "four billable units at 480 plus the 350-cent outpatient handling fee"

        A.assert_prescription(
            fx.get_prescription(nicu["id"]),
            status=PrescriptionStatus.FILLED,
            remaining_ml=0,
            waitlist_position=None,
        )
        A.assert_prescription(
            fx.get_prescription(outpatient["id"]),
            status=PrescriptionStatus.PARTIALLY_FILLED,
            cumulative_dispensed_ml=400,
            remaining_ml=100,
            waitlist_position=1,
        )
        after_first_cycle = fx.get_lot(lot["id"])
        A.assert_milk_lot(
            after_first_cycle,
            dispensed_ml=1600,
            available_ml=3000,
            release_status=LotReleaseStatus.RELEASED,
        )
        assert after_first_cycle["version"] == version_before + 2, (
            "one version increment per created fill"
        )

        fx.run_allocation_cycle()

        assert max(0, 3000 - C.NICU_RESERVE_ML) == 0
        rows, meta = _lot_dispenses(lot["id"])
        assert meta["total_count"] == 2, "the second cycle creates no fill"
        after_second_cycle = fx.get_lot(lot["id"])
        A.assert_milk_lot(after_second_cycle, available_ml=3000, dispensed_ml=1600)
        assert after_second_cycle["version"] == after_first_cycle["version"]
        A.assert_prescription(
            fx.get_prescription(outpatient["id"]),
            status=PrescriptionStatus.PARTIALLY_FILLED,
            remaining_ml=100,
        )


class TestAvailableVolumeIsAComputedRead:
    """available_ml is never stored: it is the lot's total less what has been
    dispensed, recomputed on every read, and it is what flips the lot in and out
    of EXHAUSTED."""

    def test_a_full_draw_exhausts_the_lot_and_the_void_brings_it_back(self):
        """A 1200 ml fill takes the lot to available_ml 0 and EXHAUSTED; voiding
        that fill returns it to 1200 and RELEASED while total_volume_ml never
        moves and the voided row keeps its 5760-cent figures.

        PRD: "Thereafter a lot's `dispensed_ml` is the sum of `volume_ml` across the fills against it whose `status` is `DISPENSED`, and its `available_ml` is its `total_volume_ml` less that figure. A lot moves `RELEASED → EXHAUSTED` when `available_ml` reaches 0 and back `EXHAUSTED → RELEASED` when returned volume raises it above 0, both per §2.8."
        PRD: "Crucially, the void does **not** zero `tier_discount_pct`, `gross_fee_cents`, `subsidy_cents` or `payer_due_cents`: those figures are retained on the voided row as the audit record of what was once charged."

        Design: Corner/endpoints/milk_lot_available_ml_is_a_computed_read_that_flips_exhausted_and_back
        """
        chain = _released_chain(lot_ml=1200)
        lot = chain.lots[0]
        order = _order("RX-8001", 1200)

        before = fx.get_lot(lot["id"])
        A.assert_milk_lot(
            before,
            lot_code="20260810-001-01",
            total_volume_ml=1200,
            available_ml=1200,
            dispensed_ml=0,
            kcal_per_oz=20.0,
            expiration_date=SHELF_LIFE_DATE,
            release_status=LotReleaseStatus.RELEASED,
        )

        fill = validate_success(
            _fill_attempt(order["id"], lot["id"], 1200, expected_lot_version=before["version"]),
            201,
        )
        A.assert_dispense(
            fill,
            volume_ml=1200,
            gross_fee_cents=5760,
            subsidy_cents=0,
            payer_due_cents=5760,
        )
        emptied = fx.get_lot(lot["id"])
        A.assert_milk_lot(
            emptied,
            total_volume_ml=1200,
            available_ml=0,
            dispensed_ml=1200,
            release_status=LotReleaseStatus.EXHAUSTED,
        )

        voided = fx.void_dispense(fill["id"])
        A.assert_dispense(
            voided,
            status=DispenseStatus.VOIDED,
            gross_fee_cents=5760,
            payer_due_cents=5760,
            subsidy_cents=0,
        )
        restored = fx.get_lot(lot["id"])
        A.assert_milk_lot(
            restored,
            total_volume_ml=1200,
            available_ml=1200,
            dispensed_ml=0,
            release_status=LotReleaseStatus.RELEASED,
        )
        A.assert_prescription(
            fx.get_prescription(order["id"]),
            cumulative_dispensed_ml=0,
            remaining_ml=1200,
            status=PrescriptionStatus.QUEUED,
            waitlist_position=1,
        )
        rows, meta = validate_paginated(
            api_client.list_milk_lots(
                QA_RELEASER_HEADERS, {"release_status": LotReleaseStatus.RELEASED}
            )
        )
        assert meta["total_count"] == 1 and rows[0]["id"] == lot["id"]
