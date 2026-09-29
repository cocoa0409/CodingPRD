"""Deferrals and the retrospective recall.

The unhappy path: a reactive panel that defers a donor on its own authority and
walks forward through donations, pools, lots, fills and the charity ledger in a
single request; the closed-closed lookback window that decides which milk is
implicated; the coupling between a deferral's duration and its type; and the
strict gate on the door back in.
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
    MEDICAL_DIRECTOR_HEADERS,
    MEDICAL_DIRECTOR_ID,
)
from test_helpers.types import (
    ClinicalAcuity,
    ComponentStatus,
    DeferralReason,
    DeferralStatus,
    DeferralType,
    DispenseStatus,
    DonationStatus,
    DonorStatus,
    LotReleaseStatus,
    MilkClass,
    PatientType,
    PoolStatus,
    PrescriptionStatus,
    ProgramStatus,
    RecallScope,
    SerologyResult,
)

INTAKE_CLOCK = C.CLOCK_INTAKE
INTAKE_DATE = C.CLOCK_INTAKE_DATE
RUN_DATE = C.CLOCK_RUN_DATE


def _deferral_attempt(donor_id, **overrides):
    """Record a deferral and hand back the raw response."""
    return api_client.record_deferral(donor_id, f.deferral(**overrides), MEDICAL_DIRECTOR_HEADERS)


def _deferrals(donor_id, **params):
    response = api_client.list_deferrals(donor_id, MEDICAL_DIRECTOR_HEADERS, params or None)
    return validate_paginated(response)


def _panels(donor_id, **params):
    response = api_client.list_serology_panels(donor_id, MEDICAL_DIRECTOR_HEADERS, params or None)
    return validate_paginated(response)


def _sole_deferral(donor_id, **params):
    rows, meta = _deferrals(donor_id, **params)
    assert meta["total_count"] == 1, "exactly one deferral event should be on file"
    return rows[0]


def _fed_chain(volume_ml=450, prescribed_ml=450, coverage_pct=0.60, annual_cap_cents=100000):
    """The canonical three-donor chain, bottled into a 1200 ml released lot, with
    one subsidised fill already drawn against it."""
    chain = fx.build_chain(run={}, lots=[(12, 100)])
    program = fx.open_program(
        program_code="SUB-2026",
        name="Charitable Subsidy 2026",
        coverage_pct=coverage_pct,
        annual_cap_cents=annual_cap_cents,
    )
    prescription = fx.submit_prescription(
        prescription_code="RX-0001",
        subsidy_program_id=program["id"],
        patient_reference="NICU-BED-1",
        patient_type=PatientType.NICU_INPATIENT,
        clinical_acuity=ClinicalAcuity.CRITICAL,
        requires_preterm_milk=False,
        subsidy_required=True,
        prescribed_ml=prescribed_ml,
        needed_by_date="2026-08-20",
    )
    dispense = fx.fill_prescription(prescription["id"], chain.lots[0]["id"], volume_ml)
    return chain, program, prescription, dispense


def _component_for(pool_id, donation_id):
    rows = fx.list_pool_components(pool_id)
    matches = [row for row in rows if row["donation_id"] == donation_id]
    assert len(matches) == 1, "each canonical container was drawn exactly once"
    return matches[0]


def _three_dated_containers(donor_id):
    """One cooler holding 700 ml expressed on each of three dates: the right
    endpoint of the window under test, the left endpoint, and the day before."""
    shipment = fx.register_shipment(
        donor_id,
        tracking_code="TRK-1001",
        container_count=3,
        uses_dry_ice=False,
        declared_volume_ml=2100,
        shipped_on="2026-08-02",
    )
    fx.receive_shipment(
        shipment["id"],
        excursion_minutes=0,
        arrival_max_temp_celsius=-18.0,
        verified_volume_ml=2100,
    )
    dated = []
    for label, expressed_on in (
        ("C1", "2026-07-05"),
        ("C2", "2026-06-05"),
        ("C3", "2026-06-04"),
    ):
        dated.append(
            fx.log_container(
                shipment["id"],
                container_label=label,
                expressed_on=expressed_on,
                volume_ml=700,
                kcal_per_oz=20.0,
                milk_class=MilkClass.TERM,
            )
        )
    return shipment, dated


class TestOneReactivePanelWalksTheWholeChain:
    """A reactive marker is the one clinical result that acts on its own
    authority, and the cascade it fires does not stop at the milk."""

    def test_the_recall_reaches_the_donation_the_lot_the_fill_and_the_charity_spend(self):
        """A single REACTIVE marker permanently defers the donor, recalls her
        pasteurized donation, recalls the lot bottled from the pool that held it,
        recalls the 450 ml fill drawn from that lot, credits 1440 cents back to
        the programme and returns the order to the queue — while the pool itself,
        whose component was already consumed into bottles, is untouched.

        PRD: "From those five the server derives the panel's `panel_status` by a strict precedence: `REACTIVE` if **any** marker is `REACTIVE`; otherwise `INDETERMINATE` if **any** marker is `INDETERMINATE`; otherwise `NON_REACTIVE`. The panel's `expires_on` is 180 days after `collected_on`, and the acting director's identifier is kept as `recorded_by_user_id`."
        PRD: "Recording it permanently defers the donor — she moves to `PERMANENTLY_DEFERRED` from `APPLICANT`, `SCREENING`, `INFO_REQUESTED` or `QUALIFIED` alike — and the server authors a `DeferralEvent` on her behalf with `reason_code` `REACTIVE_SEROLOGY`, `deferral_type` `PERMANENT`, `effective_from` set to the current clock date, `deferral_days` 0, `lookback_days` 365, `recall_scope` `FULL_CHAIN` and `recorded_by_user_id` the literal string `system`."
        PRD: "Every donation of hers whose `status` is `ELIGIBLE`, `ALLOCATED` or `PASTEURIZED` and whose `expressed_on` falls inside the **closed** interval beginning `lookback_days` before `effective_from` and ending on `effective_from` itself moves to `RECALLED`, taking a `version` increment."
        PRD: "A component that is already `CONSUMED_PASTEURIZED` is left exactly where it is — its milk is already in bottles, so there is nothing to return — and its pool keeps its `PASTEURIZED` status."
        PRD: "Every `MilkLot` bottled from a `PasteurizationRun` whose pool holds an implicated component, and whose `release_status` is `HOLD`, `RELEASED` or `EXHAUSTED`, moves to `RECALLED` with a `version` increment."
        PRD: "Its `subsidy_cents` is credited back to its programme's `consumed_cents`, which may flip that programme from `EXHAUSTED` back to `OPEN`; the same amount accumulates into the event's `reversed_subsidy_cents`."
        PRD: "Crucially, the volume is **not** credited back to the lot's `dispensed_ml`: recalled milk is destroyed rather than returned to inventory, so `available_ml` on a recalled lot does not recover."
        PRD: "Any `Prescription` whose `cumulative_dispensed_ml` has dropped below its `prescribed_ml` leaves `FILLED` and returns to the queue — to `QUEUED` when its `cumulative_dispensed_ml` has reached 0 and to `PARTIALLY_FILLED` otherwise — with its `waitlist_position` recomputed along with every other position in its priority bucket, and with a `version` increment."

        Design: Difficulty/transitive_cascade/reactive_serology_five_hop_recall
        """
        chain, program, prescription, dispense = _fed_chain()
        donor = chain.donors[0]
        lot = chain.lots[0]
        A.assert_dispense(
            dispense,
            volume_ml=450,
            gross_fee_cents=2400,
            subsidy_cents=1440,
            payer_due_cents=960,
            status=DispenseStatus.DISPENSED,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=1440, status=ProgramStatus.OPEN
        )
        A.assert_prescription(
            fx.get_prescription(prescription["id"]),
            status=PrescriptionStatus.FILLED,
            cumulative_dispensed_ml=450,
            remaining_ml=0,
            waitlist_position=None,
        )

        panel = fx.record_serology(
            donor["id"], collected_on="2026-08-09", hiv_result=SerologyResult.REACTIVE
        )
        assert panel["panel_status"] == SerologyResult.REACTIVE
        assert panel["expires_on"] == A.add_days("2026-08-09", C.SEROLOGY_VALID_DAYS), (
            "the panel's own expiry is 180 days after the draw"
        )
        reactive_rows, reactive_meta = _panels(
            donor["id"], panel_status=SerologyResult.REACTIVE
        )
        assert reactive_meta["total_count"] == 1
        assert reactive_rows[0]["id"] == panel["id"]

        event = _sole_deferral(donor["id"], status=DeferralStatus.ACTIVE)
        A.assert_deferral_event(
            event,
            donor_id=donor["id"],
            reason_code=DeferralReason.REACTIVE_SEROLOGY,
            deferral_type=DeferralType.PERMANENT,
            effective_from=RUN_DATE,
            deferral_days=0,
            lookback_days=C.RAW_AGE_SHELF_DAYS,
            recall_scope=RecallScope.FULL_CHAIN,
            status=DeferralStatus.ACTIVE,
            recorded_by_user_id="system",
        )
        A.assert_recall_counters(
            event,
            recalled_donation_count=1,
            quarantined_pool_count=0,
            recalled_lot_count=1,
            recalled_dispense_count=1,
            reversed_subsidy_cents=1440,
        )
        A.assert_donor(
            fx.get_donor(donor["id"]),
            status=DonorStatus.PERMANENTLY_DEFERRED,
            temporary_deferral_count=0,
        )

        # Hop one: only the reactive donor's own container moves.
        A.assert_donation(
            fx.get_donation(chain.donations[0]["id"]), status=DonationStatus.RECALLED
        )
        for untouched in chain.donations[1:]:
            A.assert_donation(
                fx.get_donation(untouched["id"]), status=DonationStatus.PASTEURIZED
            )

        # Hop two finds the component already consumed into bottles, so no pool
        # is scrapped and none is counted.
        A.assert_pool(fx.get_pool(chain.pool["id"]), status=PoolStatus.PASTEURIZED)
        A.assert_pool_component(
            _component_for(chain.pool["id"], chain.donations[0]["id"]),
            status=ComponentStatus.CONSUMED_PASTEURIZED,
            allocated_volume_ml=800,
        )

        # Hops three and four: the bottled inventory and the fill drawn from it.
        recalled_lot = fx.get_lot(lot["id"])
        A.assert_milk_lot(
            recalled_lot,
            release_status=LotReleaseStatus.RECALLED,
            total_volume_ml=1200,
            dispensed_ml=450,
            available_ml=750,
        )
        rows = fx.list_prescription_dispenses(prescription["id"])
        assert len(rows) == 1
        A.assert_dispense(
            rows[0],
            status=DispenseStatus.RECALLED,
            volume_ml=450,
            tier_discount_pct=0.00,
            gross_fee_cents=2400,
            subsidy_cents=1440,
            payer_due_cents=960,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=0, status=ProgramStatus.OPEN
        )

        # Hop five: the order that was never actually fed goes back on the list.
        A.assert_prescription(
            fx.get_prescription(prescription["id"]),
            status=PrescriptionStatus.QUEUED,
            cumulative_dispensed_ml=0,
            remaining_ml=450,
            priority_tier=1,
            waitlist_position=1,
        )

    def test_a_fill_that_was_voided_first_leaves_the_money_hop_nothing_to_reverse(self):
        """The fourth hop moves only fills whose status is DISPENSED: when the
        450 ml fill has already been voided, the recall still reaches the donation
        and the lot but stamps recalled_dispense_count 0 and reversed_subsidy_cents
        0, and the voided row keeps both its VOIDED status and its retained fee
        figures.

        PRD: "Every `Dispense` against such a lot whose `status` is `DISPENSED` moves to `RECALLED`."
        PRD: "Every `MilkLot` bottled from a `PasteurizationRun` whose pool holds an implicated component, and whose `release_status` is `HOLD`, `RELEASED` or `EXHAUSTED`, moves to `RECALLED` with a `version` increment."
        PRD: "Crucially, the void does **not** zero `tier_discount_pct`, `gross_fee_cents`, `subsidy_cents` or `payer_due_cents`: those figures are retained on the voided row as the audit record of what was once charged."
        PRD: "Its `subsidy_cents` is credited back to its programme's `consumed_cents`, which may flip that programme from `EXHAUSTED` back to `OPEN`; the same amount accumulates into the event's `reversed_subsidy_cents`."

        Design: Difficulty/transitive_cascade/reactive_serology_five_hop_recall
        """
        chain, program, prescription, dispense = _fed_chain()
        donor = chain.donors[0]
        lot = chain.lots[0]

        A.assert_dispense(
            fx.void_dispense(dispense["id"]),
            status=DispenseStatus.VOIDED,
            gross_fee_cents=2400,
            subsidy_cents=1440,
            payer_due_cents=960,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=0, status=ProgramStatus.OPEN
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            release_status=LotReleaseStatus.RELEASED,
            dispensed_ml=0,
            available_ml=1200,
        )

        fx.record_serology(
            donor["id"], collected_on="2026-08-09", syphilis_result=SerologyResult.REACTIVE
        )

        event = _sole_deferral(donor["id"])
        A.assert_recall_counters(
            event,
            recalled_donation_count=1,
            quarantined_pool_count=0,
            recalled_lot_count=1,
            recalled_dispense_count=0,
            reversed_subsidy_cents=0,
        )
        A.assert_donation(
            fx.get_donation(chain.donations[0]["id"]), status=DonationStatus.RECALLED
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            release_status=LotReleaseStatus.RECALLED,
            total_volume_ml=1200,
            dispensed_ml=0,
            available_ml=1200,
        )
        rows = fx.list_prescription_dispenses(prescription["id"])
        assert len(rows) == 1
        A.assert_dispense(
            rows[0],
            status=DispenseStatus.VOIDED,
            gross_fee_cents=2400,
            subsidy_cents=1440,
            payer_due_cents=960,
        )
        A.assert_subsidy_program(
            fx.get_program(program["id"]), consumed_cents=0, status=ProgramStatus.OPEN
        )
        A.assert_prescription(
            fx.get_prescription(prescription["id"]),
            status=PrescriptionStatus.QUEUED,
            cumulative_dispensed_ml=0,
            remaining_ml=450,
            waitlist_position=1,
        )


class TestTheRecallLookbackIsAClosedDateWindow:
    """The recall window is a closed-closed range over expressed_on: both of its
    endpoints are inside it, and the day before the left endpoint is not."""

    def test_both_endpoints_are_recalled_and_the_day_before_is_untouched(self):
        """A 30-day lookback from 2026-07-05 spans the closed range
        [2026-06-05, 2026-07-05], so the containers expressed on 2026-07-05 and
        2026-06-05 are both recalled while the one expressed on 2026-06-04 is
        never written; DONATIONS_ONLY stops the cascade right there.

        PRD: "Every donation of hers whose `status` is `ELIGIBLE`, `ALLOCATED` or `PASTEURIZED` and whose `expressed_on` falls inside the **closed** interval beginning `lookback_days` before `effective_from` and ending on `effective_from` itself moves to `RECALLED`, taking a `version` increment."
        PRD: "A `recall_scope` of `NONE` recalls nothing; the deferral is purely forward-looking. `DONATIONS_ONLY` executes the first hop and stops. `FULL_CHAIN` executes all five."
        PRD: "A donation's `remaining_ml` is thereafter always its `volume_ml` less the sum of `allocated_volume_ml` across its non-`VOIDED` components, and never goes below 0."
        PRD: "In every one of those cases her `temporary_deferral_count` rises by 1, her `surveillance_risk_score` is recomputed against the changed deferral history, her `active_deferral_until_date` is recomputed, any recall implied by `recall_scope` runs, and her `version` increases by 1."
        PRD: "It never adds the serology penalty at all — serology is a hard precondition at qualification rather than a score term — and it discounts deferral history by age: each of the donor's temporary deferral events whose `status` is `ACTIVE` or `EXPIRED` contributes 15 points multiplied by one half raised to the power of (the whole number of calendar days from that event's `effective_from` to the current clock date, divided by 180)."
        PRD: "That donation's volume raises the donor's `lifetime_accepted_volume_ml`, which is the sum of `volume_ml` over her donations in `ELIGIBLE`, `ALLOCATED` or `PASTEURIZED`; both the donor's and the cooler's `version` increase by 1."

        Design: Difficulty/resource_temporal_overlap/deferral_lookback_closed_closed_window
        """
        fx.set_clock(INTAKE_CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-1001", full_name="Ana Ruiz", zone_code="Z2")
        A.assert_donor(donor, status=DonorStatus.QUALIFIED, screening_risk_score=50)
        shipment, dated = _three_dated_containers(donor["id"])
        right_endpoint, left_endpoint, outside = dated
        assert A.add_days("2026-07-05", -30) == "2026-06-05", (
            "the closed window runs from lookback_days before effective_from"
        )
        A.assert_donor(
            fx.get_donor(donor["id"]), lifetime_accepted_volume_ml=2100
        )

        fx.record_deferral(
            donor["id"],
            reason_code=DeferralReason.ILLNESS,
            deferral_type=DeferralType.TEMPORARY,
            effective_from="2026-07-05",
            deferral_days=60,
            lookback_days=30,
            recall_scope=RecallScope.DONATIONS_ONLY,
        )

        event = _sole_deferral(donor["id"])
        A.assert_deferral_event(
            event,
            effective_from="2026-07-05",
            deferral_days=60,
            lookback_days=30,
            recall_scope=RecallScope.DONATIONS_ONLY,
            status=DeferralStatus.ACTIVE,
            recorded_by_user_id=MEDICAL_DIRECTOR_ID,
        )
        A.assert_recall_counters(
            event,
            recalled_donation_count=2,
            quarantined_pool_count=0,
            recalled_lot_count=0,
            recalled_dispense_count=0,
            reversed_subsidy_cents=0,
        )

        A.assert_donation(
            fx.get_donation(right_endpoint["id"]),
            expressed_on="2026-07-05",
            status=DonationStatus.RECALLED,
            remaining_ml=700,
            version=2,
        )
        A.assert_donation(
            fx.get_donation(left_endpoint["id"]),
            expressed_on="2026-06-05",
            status=DonationStatus.RECALLED,
            remaining_ml=700,
            version=2,
        )
        A.assert_donation(
            fx.get_donation(outside["id"]),
            expressed_on="2026-06-04",
            status=DonationStatus.ELIGIBLE,
            remaining_ml=700,
            version=1,
        )

        A.assert_donor(
            fx.get_donor(donor["id"]),
            status=DonorStatus.TEMPORARILY_DEFERRED,
            temporary_deferral_count=1,
            active_deferral_until_date=A.add_days("2026-07-05", 60),
            surveillance_risk_score=A.expected_surveillance_score(30, [31]),
            screening_risk_score=50,
            lifetime_accepted_volume_ml=700,
        )
        assert A.expected_surveillance_score(30, [31]) == 43
        assert fx.get_shipment(shipment["id"])["verified_volume_ml"] == 2100

    def test_a_zero_day_lookback_still_recalls_the_milk_expressed_on_the_effective_date(self):
        """With lookback_days 0 the closed window degenerates to the single day
        2026-06-05, so exactly one of the three containers is recalled while the
        other two keep version 1; a PERMANENT event carries no deferral days and
        leaves active_deferral_until_date null.

        PRD: "Every donation of hers whose `status` is `ELIGIBLE`, `ALLOCATED` or `PASTEURIZED` and whose `expressed_on` falls inside the **closed** interval beginning `lookback_days` before `effective_from` and ending on `effective_from` itself moves to `RECALLED`, taking a `version` increment."
        PRD: "A `PERMANENT` deferral moves her to `PERMANENTLY_DEFERRED` from `SCREENING`, `INFO_REQUESTED`, `QUALIFIED` or `TEMPORARILY_DEFERRED`, runs the same recall, and likewise increments her `version`."
        PRD: "It is the end date of the single **most recently created** `ACTIVE` `TEMPORARY` deferral event of that donor — ordered by `created_at` descending, with the row `id` never used as a tie-break — computed as that event's `effective_from` plus its `deferral_days`, and it is null whenever the donor has no `ACTIVE` `TEMPORARY` deferral at all."

        Design: Difficulty/resource_temporal_overlap/deferral_lookback_closed_closed_window
        """
        fx.set_clock(INTAKE_CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-1001", full_name="Ana Ruiz", zone_code="Z2")
        _, dated = _three_dated_containers(donor["id"])
        later, on_the_day, earlier = dated

        fx.record_deferral(
            donor["id"],
            reason_code=DeferralReason.DONOR_REQUEST,
            deferral_type=DeferralType.PERMANENT,
            effective_from="2026-06-05",
            deferral_days=0,
            lookback_days=0,
            recall_scope=RecallScope.DONATIONS_ONLY,
        )

        event = _sole_deferral(donor["id"], deferral_type=DeferralType.PERMANENT)
        A.assert_deferral_event(
            event,
            reason_code=DeferralReason.DONOR_REQUEST,
            deferral_type=DeferralType.PERMANENT,
            effective_from="2026-06-05",
            deferral_days=0,
            lookback_days=0,
            status=DeferralStatus.ACTIVE,
        )
        A.assert_recall_counters(event, recalled_donation_count=1)

        A.assert_donation(
            fx.get_donation(on_the_day["id"]), status=DonationStatus.RECALLED, version=2
        )
        for untouched in (later, earlier):
            A.assert_donation(
                fx.get_donation(untouched["id"]), status=DonationStatus.ELIGIBLE, version=1
            )
        A.assert_donor(
            fx.get_donor(donor["id"]),
            status=DonorStatus.PERMANENTLY_DEFERRED,
            temporary_deferral_count=0,
            active_deferral_until_date=None,
            lifetime_accepted_volume_ml=1400,
        )


class TestDeferralDurationIsConstrainedAgainstItsType:
    """The two duration fields are range-checked against the deferral type, and
    that check runs before any state work."""

    def test_a_zero_day_temporary_a_five_day_permanent_and_an_overlong_lookback_are_all_refused(
        self,
    ):
        """deferral_days 0 is legal only for a PERMANENT event and illegal for a
        TEMPORARY one, the reverse pairing is refused the same way, a lookback of
        1096 days exceeds the declared range, and all three answers are
        ERR_FIELD_OUT_OF_RANGE at 422 with nothing written; a one-day TEMPORARY
        event then lands.

        PRD: "The two duration fields are constrained against the type: `deferral_days` must be exactly 0 when `deferral_type` is `PERMANENT`, and must be at least 1 when it is `TEMPORARY`. A mismatch is a range violation reported as `ERR_FIELD_OUT_OF_RANGE`, evaluated before the donor's state gate."
        PRD: "A `MedicalDirector` records one by supplying a `reason_code` from the seven values named above; a `deferral_type` of either `TEMPORARY` or `PERMANENT`; an `effective_from` date on which the deferring condition began; a `deferral_days` count between 0 and 3650; a `lookback_days` window between 0 and 1095; and a `recall_scope` of `NONE`, `DONATIONS_ONLY` or `FULL_CHAIN`."
        PRD: "Every deferral event is created with `status` `ACTIVE`, and its `recorded_by_user_id` is the acting director's identifier — or the literal string `system` for the two events the server authors on its own."
        PRD: "In every one of those cases her `temporary_deferral_count` rises by 1, her `surveillance_risk_score` is recomputed against the changed deferral history, her `active_deferral_until_date` is recomputed, any recall implied by `recall_scope` runs, and her `version` increases by 1."

        Design: Corner/validations/deferral_day_count_is_coupled_to_the_deferral_type
        """
        fx.set_clock(INTAKE_CLOCK)
        donor = fx.screened_donor(donor_code="DNR-0001", full_name="Ana Ruiz", zone_code="Z2")
        A.assert_donor(donor, status=DonorStatus.SCREENING, version=2)

        zero_day_temporary = validate_error(
            _deferral_attempt(
                donor["id"],
                reason_code=DeferralReason.ILLNESS,
                deferral_type=DeferralType.TEMPORARY,
                effective_from=INTAKE_DATE,
                deferral_days=0,
                lookback_days=0,
                recall_scope=RecallScope.NONE,
            ),
            ApiErrorId.FIELD_OUT_OF_RANGE,
            422,
        )
        five_day_permanent = validate_error(
            _deferral_attempt(
                donor["id"],
                reason_code=DeferralReason.ILLNESS,
                deferral_type=DeferralType.PERMANENT,
                effective_from=INTAKE_DATE,
                deferral_days=5,
                lookback_days=0,
                recall_scope=RecallScope.NONE,
            ),
            ApiErrorId.FIELD_OUT_OF_RANGE,
            422,
        )
        overlong_lookback = validate_error(
            _deferral_attempt(
                donor["id"],
                reason_code=DeferralReason.ILLNESS,
                deferral_type=DeferralType.TEMPORARY,
                effective_from=INTAKE_DATE,
                deferral_days=5,
                lookback_days=1096,
                recall_scope=RecallScope.NONE,
            ),
            ApiErrorId.FIELD_OUT_OF_RANGE,
            422,
        )
        assert (
            zero_day_temporary["error_id"]
            == five_day_permanent["error_id"]
            == overlong_lookback["error_id"]
            == ApiErrorId.FIELD_OUT_OF_RANGE.value
        )
        A.assert_donor(fx.get_donor(donor["id"]), status=DonorStatus.SCREENING, version=2)
        assert _deferrals(donor["id"])[1]["total_count"] == 0, "no event survived a refusal"

        accepted = validate_success(
            _deferral_attempt(
                donor["id"],
                reason_code=DeferralReason.ILLNESS,
                deferral_type=DeferralType.TEMPORARY,
                effective_from=INTAKE_DATE,
                deferral_days=1,
                lookback_days=0,
                recall_scope=RecallScope.NONE,
            ),
            201,
        )
        A.assert_deferral_event(
            accepted,
            deferral_type=DeferralType.TEMPORARY,
            deferral_days=1,
            lookback_days=0,
            recall_scope=RecallScope.NONE,
            status=DeferralStatus.ACTIVE,
            recorded_by_user_id=MEDICAL_DIRECTOR_ID,
        )
        A.assert_recall_counters(accepted)
        A.assert_donor(
            fx.get_donor(donor["id"]),
            status=DonorStatus.TEMPORARILY_DEFERRED,
            temporary_deferral_count=1,
            active_deferral_until_date=A.add_days(INTAKE_DATE, 1),
            version=3,
        )
        assert A.add_days(INTAKE_DATE, 1) == "2026-08-06"
        assert _deferrals(donor["id"])[1]["total_count"] == 1


class TestRequalificationIsStrictAboutTheLastDeferredDay:
    """The door back in opens only once the clock has moved strictly past the
    deferral's end date."""

    def test_requalify_is_refused_on_the_end_date_itself_and_succeeds_the_next_day(self):
        """A three-day deferral effective 2026-08-05 ends on 2026-08-08: on that
        exact date requalify answers ERR_DEFERRAL_STILL_ACTIVE, and only on
        2026-08-09 does it return the donor to SCREENING with a null
        active_deferral_until_date, an EXPIRED event and a surveillance score
        re-decayed to 45.

        PRD: "It advances the donor `TEMPORARILY_DEFERRED → SCREENING`, and its single additional precondition is that the current clock date be **strictly later** than her `active_deferral_until_date`; on the last deferred day itself the answer is still `ERR_DEFERRAL_STILL_ACTIVE`."
        PRD: "On success, every `ACTIVE` `TEMPORARY` deferral event of hers whose `effective_from` plus `deferral_days` falls before the current clock date is set to `EXPIRED`; her `active_deferral_until_date` is then recomputed from whatever `ACTIVE` `TEMPORARY` events remain, becoming null when none do; her `surveillance_risk_score` is recomputed against the now further-decayed history; and her `version` increases by 1."
        PRD: "It never adds the serology penalty at all — serology is a hard precondition at qualification rather than a score term — and it discounts deferral history by age: each of the donor's temporary deferral events whose `status` is `ACTIVE` or `EXPIRED` contributes 15 points multiplied by one half raised to the power of (the whole number of calendar days from that event's `effective_from` to the current clock date, divided by 180)."

        Design: Corner/validations/requalify_on_the_last_deferred_day_is_refused_and_the_next_day_succeeds
        """
        fx.set_clock(INTAKE_CLOCK)
        donor = fx.qualified_donor(donor_code="DNR-0001", full_name="Ana Ruiz", zone_code="Z2")
        fx.record_deferral(
            donor["id"],
            reason_code=DeferralReason.ILLNESS,
            deferral_type=DeferralType.TEMPORARY,
            effective_from=INTAKE_DATE,
            deferral_days=3,
            lookback_days=0,
            recall_scope=RecallScope.NONE,
        )
        A.assert_donor(
            fx.get_donor(donor["id"]),
            status=DonorStatus.TEMPORARILY_DEFERRED,
            temporary_deferral_count=1,
            active_deferral_until_date="2026-08-08",
        )

        fx.set_clock("2026-08-08T09:00:00Z")
        refusal = validate_error(
            api_client.requalify_donor(donor["id"], MEDICAL_DIRECTOR_HEADERS),
            ApiErrorId.DEFERRAL_STILL_ACTIVE,
            409,
        )
        assert refusal["error_id"] == ApiErrorId.DEFERRAL_STILL_ACTIVE.value
        A.assert_donor(
            fx.get_donor(donor["id"]),
            status=DonorStatus.TEMPORARILY_DEFERRED,
            active_deferral_until_date="2026-08-08",
        )

        fx.set_clock("2026-08-09T09:00:00Z")
        requalified = fx.requalify(donor["id"])
        A.assert_donor(
            requalified,
            status=DonorStatus.SCREENING,
            active_deferral_until_date=None,
            temporary_deferral_count=1,
            surveillance_risk_score=A.expected_surveillance_score(30, [4]),
        )
        assert A.expected_surveillance_score(30, [4]) == 45
        expired = _sole_deferral(donor["id"])
        A.assert_deferral_event(
            expired, status=DeferralStatus.EXPIRED, deferral_days=3, effective_from=INTAKE_DATE
        )
