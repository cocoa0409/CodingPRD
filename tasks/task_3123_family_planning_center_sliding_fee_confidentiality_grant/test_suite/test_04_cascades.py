"""Depth tests: assessment-supersede cascade and cancel-release cascade."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_tx_clinic, setup_assessed_encounter, setup_submitted_claim,
    create_patient, create_assessment, create_encounter,
    create_stock_lot, create_device_reservation,
    create_grant_report_payload,
    set_clock, get_patient, get_encounter, get_claim, get_grant_report,
    get_stock_lot,
    TEST_USERS, FPL_INCOME_H4_PCT_48, FPL_INCOME_H4_PCT_153,
    FPL_INCOME_H1_PCT_265, ENC_START, ENC_END, LARC_START, LARC_END,
    REPORT_PERIOD_START, REPORT_PERIOD_END,
)

ADMIN = TEST_USERS["grant_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
BILLING = TEST_USERS["billing_headers"]


def _setup_claimed_encounter_and_draft_report(api):
    """Tier-A patient with a CLAIMED encounter and a covering DRAFT report.

    Returns (clinic, patient, old_assessment, encounter, claim, report).
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_submitted_claim(
        clinic, income_cents=FPL_INCOME_H4_PCT_48, household_size=4,
        insurance_policy_id="POL-TC",
    )
    aff = validate_success(
        api_client.get_affiliate(clinic["affiliate"]["id"], ADMIN)
    )
    report = validate_success(
        api_client.create_grant_report(
            aff["id"],
            create_grant_report_payload(
                aff["version"], period_start=REPORT_PERIOD_START,
                period_end=REPORT_PERIOD_END, valuation_variant="FIFO",
            ),
            ADMIN,
        ),
        201,
    )
    assert report["encounter_count"] == 1
    assert report["low_income_encounter_count"] == 1
    return clinic, ctx["patient"], ctx["assessment"], ctx["encounter"], ctx["claim"], report


def test_supersede_reprices_encounter_and_recomputes_open_claim(api):
    """PRD §3.8: "**Link 2** — every encounter of the patient whose billing
    status is `UNBILLED` or `CLAIMED` re-pins its `assessment_id` to the new
    current assessment and recomputes `patient_charge_cents` under the new
    tier."
    PRD §3.8: "**Link 3** — for every re-priced encounter whose billing status
    is `CLAIMED`, the open `Claim`'s `billed_cents` is recomputed under the
    new charge".

    A new DOCUMENTED household-4 assessment at 4800000 cents (fpl 153, tier C)
    supersedes the tier-A pin: the encounter charge goes 500 -> 10000 and the
    open claim's billed_cents goes 19500 -> 10000.

    Design: Difficulty/transitive_cascade/assessment_supersede_cascades_encounter_claim_report
    """
    clinic, patient, old_asm, enc, claim, report = (
        _setup_claimed_encounter_and_draft_report(api)
    )
    patient_now = get_patient(patient["id"])
    new_asm = validate_success(
        api_client.create_assessment(
            patient["id"],
            {
                "household_size": 4,
                "annual_income_cents": FPL_INCOME_H4_PCT_153,
                "income_basis": "DOCUMENTED",
                "expected_patient_version": patient_now["version"],
            },
            FRONT_DESK,
        ),
        201,
    )
    assert new_asm["status"] == "CURRENT"
    assert new_asm["fpl_pct"] == 153
    assert new_asm["assigned_tier_code"] == "C"

    old_after = validate_success(
        api_client.get_assessment(old_asm["id"], FRONT_DESK)
    )
    assert old_after["status"] == "SUPERSEDED"

    enc_after = get_encounter(enc["id"])
    assert enc_after["assessment_id"] == new_asm["id"]
    assert enc_after["patient_charge_cents"] == 10000, (
        f"link 2 reprice under tier C: expected 10000, got "
        f"{enc_after['patient_charge_cents']}"
    )

    claim_after = get_claim(claim["id"])
    assert claim_after["billed_cents"] == 10000, (
        f"link 3 claim recompute (was 19500): expected 10000, got "
        f"{claim_after['billed_cents']}"
    )


def test_supersede_refreshes_draft_report_low_income_count(api):
    """PRD §3.8: "**Link 4** — any `DRAFT` `GrantReport` of the affiliate
    whose half-open `[period_start, period_end)` window covers a re-priced
    encounter's `scheduled_start` refreshes its aggregate fields. The
    `encounter_count` is unchanged (the encounter was already counted), but
    `low_income_encounter_count` and `device_value_cents` are re-derived
    under the new assessments."
    PRD §3.10: "`low_income_encounter_count` is the count of those encounters
    whose pinned assessment has `fpl_pct` strictly less than 100".

    The superseding assessment lifts the encounter's pin to fpl_pct 153, so
    the DRAFT report's low_income_encounter_count drops 1 -> 0 while
    encounter_count stays 1.

    Design: Difficulty/transitive_cascade/assessment_supersede_cascades_encounter_claim_report
    """
    clinic, patient, _old_asm, enc, _claim, report = (
        _setup_claimed_encounter_and_draft_report(api)
    )
    patient_now = get_patient(patient["id"])
    validate_success(
        api_client.create_assessment(
            patient["id"],
            {
                "household_size": 4,
                "annual_income_cents": FPL_INCOME_H4_PCT_153,
                "income_basis": "DOCUMENTED",
                "expected_patient_version": patient_now["version"],
            },
            FRONT_DESK,
        ),
        201,
    )
    report_after = get_grant_report(report["id"])
    assert report_after["encounter_count"] == 1, (
        "encounter_count unchanged — the encounter was already counted"
    )
    assert report_after["low_income_encounter_count"] == 0, (
        f"link 4 refresh: expected 0 (was 1), got "
        f"{report_after['low_income_encounter_count']}"
    )


def test_cancel_releases_reservation_and_restores_reserved_pool(api):
    """PRD §3.5: "Cancellation releases reservations rather than fulfilling
    them: each attached reservation in `RESERVED` moves to `RELEASED`, and
    the lot's `reserved_out` is decremented by 1 while `on_hand` is unchanged
    — the compensating invariant restores the reserved pool without removing
    any physical unit."

    Cancelling the encounter flips the reservation to RELEASED and the lot
    returns to on_hand 2 / reserved_out 0.

    Design: Difficulty/transitive_cascade/encounter_cancel_releases_reservation_into_lot
    """
    clinic = setup_tx_clinic(service_code="LARC_INSERTION",
                             full_fee_cents=50000, telehealth_eligible=False)
    ctx = setup_assessed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
        service_code="LARC_INSERTION", enc_start=LARC_START, enc_end=LARC_END,
    )
    lot = create_stock_lot(clinic["affiliate"]["id"], device_code="IUD_COPPER",
                           lot_number="LOT-C1", unit_cost_cents=15000,
                           on_hand=2, expires_on="2027-01-01")
    reservation = create_device_reservation(ctx["encounter"]["id"], lot["id"])
    assert reservation["status"] == "RESERVED"
    assert get_stock_lot(lot["id"])["reserved_out"] == 1

    cancelled = validate_success(
        api_client.cancel_encounter(ctx["encounter"]["id"], FRONT_DESK)
    )
    assert cancelled["clinical_status"] == "CANCELLED"

    res_after = validate_success(
        api_client.get_device_reservation(reservation["id"],
                                          TEST_USERS["supply_coordinator_headers"])
    )
    assert res_after["status"] == "RELEASED", (
        "reservation released by the cancel cascade"
    )
    lot_after = get_stock_lot(lot["id"])
    assert lot_after["reserved_out"] == 0
    assert lot_after["on_hand"] == 2, "on_hand unchanged by the release"


def test_cancel_does_not_consume_physical_unit(api):
    """PRD §3.5: "Cancellation releases reservations rather than fulfilling
    them: each attached reservation in `RESERVED` moves to `RELEASED`, and
    the lot's `reserved_out` is decremented by 1 while `on_hand` is
    unchanged".

    After the cancel cascade, the physical unit count is bit-identical to the
    pre-reserve value — only the reservation placeholder moved.

    Design: Difficulty/transitive_cascade/encounter_cancel_releases_reservation_into_lot
    """
    clinic = setup_tx_clinic(service_code="LARC_INSERTION",
                             full_fee_cents=50000, telehealth_eligible=False)
    ctx = setup_assessed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
        service_code="LARC_INSERTION", enc_start=LARC_START, enc_end=LARC_END,
    )
    lot = create_stock_lot(clinic["affiliate"]["id"], device_code="IUD_COPPER",
                           lot_number="LOT-C2", unit_cost_cents=15000,
                           on_hand=2, expires_on="2027-01-01")
    create_device_reservation(ctx["encounter"]["id"], lot["id"])

    validate_success(api_client.cancel_encounter(ctx["encounter"]["id"],
                                                 FRONT_DESK))
    lot_after = get_stock_lot(lot["id"])
    assert lot_after["on_hand"] == 2, (
        f"no physical unit consumed by cancellation, got on_hand "
        f"{lot_after['on_hand']}"
    )
    assert lot_after["reserved_out"] == 0
    assert (lot_after["on_hand"] - lot_after["reserved_out"]) == 2, (
        "available pool restored exactly"
    )
