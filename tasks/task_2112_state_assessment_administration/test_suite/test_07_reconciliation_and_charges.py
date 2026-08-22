"""Closing lots out: the chain replay against the district's own declaration,
the per-lot replacement charge and the district's waiver band."""
from test_helpers import (
    ApiErrorId,
    assert_lot_conservation,
    create_reconciliation_payload,
    deliver_lot_to_school,
    find_system_report_for_lot,
    create_transition_payload,
    make_district_coordinator_headers,
    make_officer_headers,
    move_report_as_officer,
    read_district,
    read_lot,
    read_window,
    reconcile_lot,
    return_to_district,
    setup_lot_awaiting_reconciliation,
    setup_program,
    setup_two_lots_awaiting_reconciliation,
    validate_error,
    validate_success,
)


def test_chain_replay_and_declared_ledger_disagree_by_the_recorded_delta(api):
    """PRD §3.5: "From them the system writes `declared_accounted_count` as the
    sum of the returned and destroyed declarations, `chain_vs_declared_delta` as
    `chain_accounted_count` minus `declared_accounted_count`, `missing_count` as
    `quantity_shipped` minus `declared_accounted_count` with any negative result
    treated as 0, and `seal_broken_count` as the declared broken-seal figure,
    and it stamps `reconciled_at` from the logical clock."
    PRD §3.5: "When the replay finishes, the four bucket fields are written from
    the replay's final state, and `chain_accounted_count` is set to the district
    bucket plus the destroyed bucket — the booklets the paper trail says are
    back in responsible hands."

    Design: Difficulty/dual_variant_calc/lot_chain_replay_vs_declared_ledger_diverges_on_material_lot
    """
    ctx = setup_lot_awaiting_reconciliation(
        district_code="NG-0002", school_code="BM-01", lot_code="LOT-B1",
        lot_quantity=10, seal_start=4000, max_concurrent_seats=40,
        window_overrides={"name": "Fall MATH G6-8", "subject": "MATH",
                          "grade_band": "G6_8"})
    assert ctx["lot"]["chain_accounted_count"] == 10

    settled = validate_success(api.reconcile_material_lot(
        ctx["lot"]["id"], create_reconciliation_payload(7, 0, 0),
        make_district_coordinator_headers(ctx["district"]["id"])))

    assert settled["chain_accounted_count"] == 10, (
        "the chain still says all ten booklets came back")
    assert settled["declared_accounted_count"] == 7, (
        "the declaration says the district only holds seven")
    assert settled["chain_vs_declared_delta"] == 3
    assert settled["missing_count"] == 3
    assert settled["quantity_at_district"] == 10
    assert settled["quantity_at_school"] == 0
    assert settled["quantity_in_sessions"] == 0
    assert_lot_conservation(settled)


def test_a_mismatched_declaration_lands_the_lot_in_discrepant_with_a_charge(api):
    """PRD §3.5: "If any one of those three is non-zero, the lot moves
    `RETURNED_PENDING → DISCREPANT` and four things follow in order. First, the
    lot's `replacement_charge_cents` is computed."
    PRD §3.5: "Each missing booklet costs 1250 cents — twelve dollars and fifty
    cents — and that unit cost is multiplied by a security factor that depends
    on whether seals were disturbed: a factor of 1.25 when the lot's
    `seal_broken_count` is 0, and a factor of 1.75 when it is greater than 0,
    since a broken seal means the state must assume the content itself was
    exposed."
    PRD §3.5: "The lot's `replacement_charge_cents` is therefore `missing_count`
    multiplied by 1250 and then by the applicable factor, rounded half up to
    whole cents at that point."

    Design: Difficulty/dual_variant_calc/lot_chain_replay_vs_declared_ledger_diverges_on_material_lot
    """
    ctx = setup_lot_awaiting_reconciliation(
        district_code="NG-0002", school_code="BM-01", lot_code="LOT-B1",
        lot_quantity=10, seal_start=4000, max_concurrent_seats=40,
        window_overrides={"name": "Fall MATH G6-8", "subject": "MATH",
                          "grade_band": "G6_8"})

    settled = validate_success(api.reconcile_material_lot(
        ctx["lot"]["id"], create_reconciliation_payload(7, 0, 0),
        make_district_coordinator_headers(ctx["district"]["id"])))

    assert settled["status"] == "DISCREPANT"
    assert settled["missing_count"] == 3
    assert settled["replacement_charge_cents"] == 4688, (
        "3 x 1250 x 1.25 = 4687.5 rounds half up to 4688")
    assert settled["seal_broken_count"] == 0
    assert settled["reconciled_at"] == "2026-09-01T08:00:00.000Z"


def test_each_lot_charge_is_rounded_before_the_district_roll_up(api):
    """PRD §3.5: "The lot's `replacement_charge_cents` is therefore
    `missing_count` multiplied by 1250 and then by the applicable factor,
    rounded half up to whole cents at that point."
    PRD §2.9: "Money is handled entirely in integer cents. Charges are rounded
    half up to whole cents **once per material lot**, and only the
    already-rounded per-lot amounts are summed into a district total."

    Design: Difficulty/combinatorial_formula/replacement_charge_rounded_per_lot_then_summed_mode_b
    """
    ctx = setup_two_lots_awaiting_reconciliation(
        district_code="NG-0004", school_code="DH-01", lot_quantity=10,
        max_concurrent_seats=40,
        window_overrides={"name": "Fall SCI G6-8", "subject": "SCIENCE",
                          "grade_band": "G6_8"})

    first = reconcile_lot(ctx["lot_one"]["id"], ctx["district"]["id"], 7, 0, 0)
    second = reconcile_lot(ctx["lot_two"]["id"], ctx["district"]["id"], 7, 0, 0)

    assert first["replacement_charge_cents"] == 4688
    assert second["replacement_charge_cents"] == 4688
    assert first["missing_count"] == 3
    assert second["missing_count"] == 3


def test_district_total_sums_rounded_lot_charges_and_applies_the_waiver(api):
    """PRD §3.5: "Only after each lot has been rounded to whole cents are the
    lots summed: a district's `replacement_charge_total_cents` is the sum of
    `replacement_charge_cents` across every one of its lots whose status is
    `DISCREPANT` and whose `charge_reversed` is false, and its
    `open_discrepancy_count` is how many lots are in that same filtered set."
    PRD §3.5: "Rounding order is part of the contract, not a detail — summing
    the unrounded products and rounding once at the end produces a different
    total and is wrong."
    PRD §3.5: "The gross is `replacement_charge_total_cents`, and the waiver
    band is selected **from that gross**, never from the post-waiver net: a
    gross below 5000 cents earns no waiver, a gross of at least 5000 cents but
    below 20000 cents earns a waiver of 10 percent, and a gross of 20000 cents
    or more earns a waiver of 20 percent."

    Design: Difficulty/combinatorial_formula/replacement_charge_rounded_per_lot_then_summed_mode_b
    """
    ctx = setup_two_lots_awaiting_reconciliation(
        district_code="NG-0004", school_code="DH-01", lot_quantity=10,
        max_concurrent_seats=40,
        window_overrides={"name": "Fall SCI G6-8", "subject": "SCIENCE",
                          "grade_band": "G6_8"})
    reconcile_lot(ctx["lot_one"]["id"], ctx["district"]["id"], 7, 0, 0)
    reconcile_lot(ctx["lot_two"]["id"], ctx["district"]["id"], 7, 0, 0)

    district = validate_success(api.get_district(
        ctx["district"]["id"],
        make_district_coordinator_headers(ctx["district"]["id"])))

    assert district["replacement_charge_total_cents"] == 9376, (
        "4688 + 4688; summing the unrounded 4687.5 products would give 9375")
    assert district["replacement_charge_total_cents"] != 9375
    assert district["security_assessment_cents"] == 8438, (
        "a gross of 9376 sits in the 10 percent band: 9376 - 938")
    assert district["open_discrepancy_count"] == 2


def test_a_broken_seal_swaps_in_the_higher_security_factor(api):
    """PRD §3.5: "Each missing booklet costs 1250 cents — twelve dollars and
    fifty cents — and that unit cost is multiplied by a security factor that
    depends on whether seals were disturbed: a factor of 1.25 when the lot's
    `seal_broken_count` is 0, and a factor of 1.75 when it is greater than 0,
    since a broken seal means the state must assume the content itself was
    exposed."
    PRD §3.5: "The waiver amount is the gross multiplied by the applicable
    percentage, rounded half up to whole cents once, and
    `security_assessment_cents` is the gross minus that waiver amount, with the
    subtraction exact."

    Design: Corner/calculations/broken_seal_multiplier_raises_the_replacement_charge
    """
    ctx = setup_program(district_code="NG-1019", school_code="FB-01",
                        lot_code="LOT-X2", seal_start=3600,
                        max_concurrent_seats=40, open_the_window=False,
                        window_overrides={"name": "Fall MATH G6-8",
                                          "subject": "MATH",
                                          "grade_band": "G6_8"})
    deliver_lot_to_school(ctx)
    return_to_district(ctx["lot"]["id"], ctx["school"]["id"], 10, sealed_count=8)

    settled = validate_success(api.reconcile_material_lot(
        ctx["lot"]["id"], create_reconciliation_payload(7, 0, 2),
        make_district_coordinator_headers(ctx["district"]["id"])))

    assert settled["status"] == "DISCREPANT"
    assert settled["missing_count"] == 3
    assert settled["seal_broken_count"] == 2
    assert settled["replacement_charge_cents"] == 6563, (
        "3 x 1250 x 1.75 = 6562.5 rounds half up to 6563")

    district = read_district(ctx["district"]["id"])
    assert district["replacement_charge_total_cents"] == 6563
    assert district["security_assessment_cents"] == 5907, (
        "a gross of 6563 earns the 10 percent waiver of 656")


def test_waiver_band_is_read_off_the_gross_not_the_net(api):
    """PRD §3.5: "The district's `security_assessment_cents` is derived
    immediately afterwards, from the roll-up and from nothing else. The gross is
    `replacement_charge_total_cents`, and the waiver band is selected **from
    that gross**, never from the post-waiver net: a gross below 5000 cents earns
    no waiver, a gross of at least 5000 cents but below 20000 cents earns a
    waiver of 10 percent, and a gross of 20000 cents or more earns a waiver of
    20 percent."
    PRD §3.5: "Reading the band off the net would push a district that sits just
    above a band edge down into the lower band and change the answer; that
    reading is explicitly rejected."

    Design: Corner/calculations/waiver_tier_is_selected_from_gross_charge_not_from_the_net_assessment
    """
    ctx = setup_lot_awaiting_reconciliation(
        district_code="NG-1020", school_code="GK-01", lot_code="LOT-X3",
        lot_quantity=20, seal_start=3700, max_concurrent_seats=40,
        window_overrides={"name": "Fall MATH G9-12", "subject": "MATH"})

    settled = reconcile_lot(ctx["lot"]["id"], ctx["district"]["id"], 7, 0, 0)
    assert settled["missing_count"] == 13
    assert settled["replacement_charge_cents"] == 20313, (
        "13 x 1250 x 1.25 = 20312.5 rounds half up to 20313")

    district = read_district(ctx["district"]["id"])
    assert district["replacement_charge_total_cents"] == 20313
    assert district["security_assessment_cents"] == 16250, (
        "a gross of 20313 sits in the 20 percent band: 20313 - 4063")
    assert district["security_assessment_cents"] != 18282, (
        "reading the band off the net would give the 10 percent answer")


def test_reconciling_a_lot_still_out_at_the_school_is_refused(api):
    """PRD §3.5: "Reconciliation closes a lot out and is the moment the paper
    trail is compared with the district's own count. Only the owning
    `DistrictTestCoordinator` may run it, and only against a lot whose status is
    `RETURNED_PENDING`; any other status is
    `ERR_LOT_NOT_AWAITING_RECONCILIATION`."

    Design: Corner/validations/reconciling_a_lot_that_is_still_in_distribution_is_rejected
    """
    ctx = setup_program(district_code="NG-1033", school_code="SU-01",
                        lot_code="LOT-V5", seal_start=4900,
                        max_concurrent_seats=40, open_the_window=False,
                        window_overrides={"name": "Fall ELA G6-8",
                                          "grade_band": "G6_8"})
    deliver_lot_to_school(ctx)

    response = api.reconcile_material_lot(
        ctx["lot"]["id"], create_reconciliation_payload(10, 0, 0),
        make_district_coordinator_headers(ctx["district"]["id"]))
    validate_error(response,
                   ApiErrorId.ERR_LOT_NOT_AWAITING_RECONCILIATION.value, 409)

    untouched = read_lot(ctx["lot"]["id"])
    assert untouched["status"] == "IN_DISTRIBUTION"
    assert untouched["declared_accounted_count"] is None
    assert untouched["reconciled_at"] is None


def test_discrepant_reconciliation_bills_the_district_before_any_dismissal(api):
    """PRD §3.5: "If any one of those three is non-zero, the lot moves
    `RETURNED_PENDING → DISCREPANT` and four things follow in order. First, the
    lot's `replacement_charge_cents` is computed. Second, the owning district's
    `replacement_charge_total_cents`, `security_assessment_cents`, and
    `open_discrepancy_count` are recomputed."
    PRD §3.5: "The lot's `replacement_charge_cents` is therefore `missing_count`
    multiplied by 1250 and then by the applicable factor, rounded half up to
    whole cents at that point."
    PRD §3.5: "The waiver amount is the gross multiplied by the applicable
    percentage, rounded half up to whole cents once, and
    `security_assessment_cents` is the gross minus that waiver amount, with the
    subtraction exact."

    Design: Difficulty/compensating_invariant/dismissed_breach_report_reverses_district_charge_ledger_to_zero
    """
    ctx = setup_lot_awaiting_reconciliation(
        district_code="NG-0018", school_code="RH-01", lot_code="LOT-R1",
        lot_quantity=10, seal_start=2000, max_concurrent_seats=40,
        window_overrides={"name": "Fall MATH G3-5", "subject": "MATH",
                          "grade_band": "G3_5", "min_participation_pct": 0.0})

    settled = reconcile_lot(ctx["lot"]["id"], ctx["district"]["id"], 6, 0, 0)
    assert settled["missing_count"] == 4
    assert settled["replacement_charge_cents"] == 6250, (
        "4 x 1250 x 1.25 = 6250 exactly")

    district = read_district(ctx["district"]["id"])
    assert district["replacement_charge_total_cents"] == 6250
    assert district["security_assessment_cents"] == 5625, (
        "a gross of 6250 earns the 10 percent waiver of 625")
    assert district["open_discrepancy_count"] == 1


def test_dismissing_the_system_breach_report_reverses_the_charge(api):
    """PRD §3.7: "A disposition of `DISMISSED` carries no preconditions and
    finds no fault. It stamps `adjudicated_at` from the logical clock. If the
    report names a `material_lot_id` — that is, if it was the system's own
    report about a discrepant lot — the lot's `charge_reversed` flag is set to
    true, which drops that lot out of the district's ledger entirely, and the
    owning district's `replacement_charge_total_cents`,
    `security_assessment_cents`, and `open_discrepancy_count` are all recomputed
    on the reduced set."
    PRD §3.5: "The lot's `replacement_charge_cents` is therefore `missing_count`
    multiplied by 1250 and then by the applicable factor, rounded half up to
    whole cents at that point."
    PRD §3.7: "The window's `security_hold` is true exactly when that count is
    greater than zero, and false otherwise."

    Design: Difficulty/compensating_invariant/dismissed_breach_report_reverses_district_charge_ledger_to_zero
    """
    ctx = setup_lot_awaiting_reconciliation(
        district_code="NG-0018", school_code="RH-01", lot_code="LOT-R1",
        lot_quantity=10, seal_start=2000, max_concurrent_seats=40,
        window_overrides={"name": "Fall MATH G3-5", "subject": "MATH",
                          "grade_band": "G3_5", "min_participation_pct": 0.0})
    reconcile_lot(ctx["lot"]["id"], ctx["district"]["id"], 6, 0, 0)
    system_report, _ = find_system_report_for_lot(ctx["lot"]["id"])

    move_report_as_officer(system_report["id"], "UNDER_REVIEW")
    adjudicated = validate_success(api.transition_irregularity_report(
        system_report["id"],
        create_transition_payload(
            "ADJUDICATED", disposition="DISMISSED",
            note="Booklets located in the vault; count error only."),
        make_officer_headers()))

    assert adjudicated["disposition"] == "DISMISSED"

    lot = read_lot(ctx["lot"]["id"])
    assert lot["charge_reversed"] is True
    assert lot["status"] == "DISCREPANT", "DISCREPANT is terminal for the lot"
    assert lot["replacement_charge_cents"] == 6250, (
        "the lot's own charge is preserved for audit")

    district = read_district(ctx["district"]["id"])
    assert district["replacement_charge_total_cents"] == 0
    assert district["security_assessment_cents"] == 0
    assert district["open_discrepancy_count"] == 0

    window = read_window(ctx["window"]["id"])
    assert window["open_breach_count"] == 0
    assert window["security_hold"] is False
