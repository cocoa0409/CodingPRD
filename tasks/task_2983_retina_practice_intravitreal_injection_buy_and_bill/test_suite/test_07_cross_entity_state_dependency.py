"""
Gates whose answer lives on a different aggregate.

A plan cannot resume while an adverse event filed against one of its encounters
is still open, and a vial cannot be selected once its parent lot has reached its
expiry instant even though the vial itself is still on the shelf.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_vial_counters,
    validate_list,
)
from test_helpers import factories as f
from test_helpers.test_users import specialist_headers


# ==========================================================================
# plan_resume_gated_on_the_adverse_event_state_of_another_aggregate
# ==========================================================================


def _suspended_plan_with_an_open_event(depth):
    """Document the injection, file an event against it and suspend the plan."""
    depth.enc1_documented
    event = depth.adverse_event(
        clinician_id=depth.cl1["id"],
        injection_encounter_id=depth.enc1["id"],
        event_type="ENDOPHTHALMITIS",
        onset_datetime="2026-08-01T18:00:00Z",
        severity="MODERATE",
    )
    suspended = validate_success(
        depth.api.suspend_treatment_plan(
            depth.plan1["id"],
            f.plan_suspend_payload(suspension_reason="PATIENT_REQUEST"),
            specialist_headers(depth.cl1["id"]),
        ),
        200,
    )
    assert suspended["status"] == "SUSPENDED"
    return event


def test_resumption_is_refused_while_the_event_is_reported_and_while_it_is_investigated(
    depth,
):
    """
    Both open states of the adverse event block the plan's resume, and the event
    itself is reportable on the routine thirty-day clock from onset.

    The gate reads another aggregate: "It is blocked while any adverse event linked
    to one of the plan's encounters is still `REPORTED` or `UNDER_INVESTIGATION` —
    that rejection is `ERR_OPEN_ADVERSE_EVENT` (HTTP 409)."  The event's own figures
    come from filing: "`days_post_injection` is written as the whole days from the
    encounter's `encounter_datetime` to `onset_datetime`, truncated downward" — nine
    hours is 0 days — and an endophthalmitis case inside the window is reportable
    with "`fda_report_due_date` is `onset_datetime` plus fifteen days for a `SEVERE`
    event and plus thirty days for any other severity".  Opening the investigation
    "moving `REPORTED → UNDER_INVESTIGATION` and changing nothing but `status` and
    `updated_at`" does not lift the block.

    Design: Difficulty/cross_entity_state_dependency/plan_resume_gated_on_the_adverse_event_state_of_another_aggregate
    """
    event = _suspended_plan_with_an_open_event(depth)

    assert event["status"] == "REPORTED"
    assert event["days_post_injection"] == 0
    assert event["reportable"] is True
    assert_instant_equals(
        event["fda_report_due_date"], "2026-08-31T18:00:00Z", "fda_report_due_date"
    )

    validate_error(
        depth.api.resume_treatment_plan(
            depth.plan1["id"], {}, specialist_headers(depth.cl1["id"])
        ),
        ApiErrorId.ERR_OPEN_ADVERSE_EVENT,
        409,
    )

    investigating = depth.start_investigation(event["id"])
    assert investigating["status"] == "UNDER_INVESTIGATION"

    validate_error(
        depth.api.resume_treatment_plan(
            depth.plan1["id"], {}, specialist_headers(depth.cl1["id"])
        ),
        ApiErrorId.ERR_OPEN_ADVERSE_EVENT,
        409,
    )


def test_an_unrelated_adjudication_releases_the_gate_and_reschedules_from_the_clock(
    depth,
):
    """
    Once the event is adjudicated unrelated the plan resumes into maintenance, dated
    from the logical clock rather than from the injection.

    The unrelated branch is inert — "An `outcome` of `UNRELATED` moves the event to
    `ADJUDICATED_UNRELATED` and fires **nothing else**: the treatment plan is left
    exactly as it was, no vial is released, no authorization is recomputed, and the
    lot's `related_endophthalmitis_count` is not touched" — but it does close the
    event, and only `REPORTED` or `UNDER_INVESTIGATION` block a resume.  The resume
    itself is pinned: "On success, `suspension_reason` is cleared to null and
    `next_due_date` becomes the logical clock advanced by the plan's
    `current_interval_days` in whole days", so a clock of 2026-08-01 with the
    loading interval of 28 days gives 2026-08-29.  The documented injection is
    untouched by any of it.

    Design: Difficulty/cross_entity_state_dependency/plan_resume_gated_on_the_adverse_event_state_of_another_aggregate
    """
    event = _suspended_plan_with_an_open_event(depth)
    depth.start_investigation(event["id"])
    adjudicated = depth.adjudicate(event["id"], clinician_id=depth.cl2["id"], outcome="UNRELATED")
    assert adjudicated["status"] == "ADJUDICATED_UNRELATED"

    resumed = validate_success(
        depth.api.resume_treatment_plan(
            depth.plan1["id"], {}, specialist_headers(depth.cl1["id"])
        ),
        200,
    )

    assert resumed["status"] == "MAINTENANCE"
    assert resumed["suspension_reason"] is None
    assert resumed["injections_administered"] == 1
    assert resumed["current_interval_days"] == 28
    assert_instant_equals(resumed["next_due_date"], "2026-08-29T00:00:00Z", "next_due_date")

    lot = depth.read_lot(depth.lot_ref["id"])
    assert lot["related_endophthalmitis_count"] == 0
    assert_vial_counters(lot, vials_administered=1, vials_on_hand=4)


# ==========================================================================
# vial_eligibility_keyed_on_parent_lot_expiry_while_the_vial_stays_in_stock
# ==========================================================================

SHORT_DATED_EXPIRY = "2026-08-15T00:00:00Z"


def _short_dated_lot_and_plan(depth):
    """
    Book a lot that expires on 15 August, activate an open-access plan against the
    same product, reserve and then release a vial, and move the clock to the expiry
    instant.  Returns the lot, the plan, the voided encounter and a fresh study.
    """
    depth.pol_np_ref
    lot = depth.lot(
        drug_id=depth.drug_ref["id"],
        lot_number="RX-2205",
        expiration_date=SHORT_DATED_EXPIRY,
        received_date="2026-07-01T00:00:00Z",
        unit_acquisition_cost_cents=132000,
        vials_received=5,
    )
    early_study = depth.imaging(
        clinician_id=depth.cl1["id"],
        patient_id=depth.pt3["id"],
        eye="OD",
        study_datetime=depth.CLOCK,
        central_subfield_thickness_um=402,
        intraretinal_fluid=True,
    )
    plan = depth.plan(
        clinician_id=depth.cl1["id"],
        patient_id=depth.pt3["id"],
        drug_id=depth.drug_ref["id"],
        eye="OD",
    )
    activated = depth.activate_plan(
        plan["id"], clinician_id=depth.cl1["id"], baseline_imaging_study_id=early_study["id"]
    )
    early_encounter = depth.encounter(
        clinician_id=depth.cl1["id"],
        treatment_plan_id=plan["id"],
        imaging_study_id=early_study["id"],
        encounter_datetime="2026-08-01T09:00:00Z",
        expected_treatment_plan_version=activated["version"],
    )
    validate_success(
        depth.api.void_injection_encounter(
            early_encounter["id"],
            f.void_payload(void_reason="Patient deferred treatment at the chair"),
            specialist_headers(depth.cl1["id"]),
        ),
        200,
    )
    depth.set_clock(SHORT_DATED_EXPIRY)
    fresh_study = depth.imaging(
        clinician_id=depth.cl1["id"],
        patient_id=depth.pt3["id"],
        eye="OD",
        study_datetime=SHORT_DATED_EXPIRY,
        central_subfield_thickness_um=415,
        intraretinal_fluid=True,
    )
    return lot, plan, early_encounter, fresh_study


def test_a_lot_expiring_exactly_at_the_clock_makes_its_in_stock_vials_ineligible(
    depth, tech
):
    """
    Every vial of the lot is `IN_STOCK` and the lot is still `AVAILABLE`, yet the
    booking is refused because the lot's expiry instant has been reached.

    Eligibility is keyed on the parent, not the vial: "The eligible pool is every
    vial whose own status is `IN_STOCK`, whose lot's status is `AVAILABLE`, whose
    lot's `drug_id` is the encounter's `effective_drug_id`, and whose lot's
    `expiration_date` is strictly after the logical clock — a lot expiring at
    exactly the clock instant is excluded", and "An empty pool is
    `ERR_NO_ELIGIBLE_VIAL` (HTTP 409)".  The earlier booking released its vial when
    it was voided — "The vial moves `RESERVED → IN_STOCK`" — so nothing has left the
    shelf, and the carrying read still values all five: 660000 cents of capital held
    45 days accrues 660000 * 0.2 * 45 / 365 = 16273.97..., which rounds to 16274.

    Design: Difficulty/cross_entity_state_dependency/vial_eligibility_keyed_on_parent_lot_expiry_while_the_vial_stays_in_stock
    """
    lot, plan, early_encounter, fresh_study = _short_dated_lot_and_plan(depth)

    assert depth.read_encounter(early_encounter["id"])["status"] == "VOIDED"

    rows, _ = validate_list(depth.api.list_vials(tech, f.page_params(drug_lot_id=lot["id"], limit=100)))
    assert len(rows) == 5
    assert {row["status"] for row in rows} == {"IN_STOCK"}

    current = depth.read_plan(plan["id"])
    response = depth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=plan["id"],
            imaging_study_id=fresh_study["id"],
            encounter_datetime="2026-08-15T09:00:00Z",
            expected_treatment_plan_version=current["version"],
        ),
        specialist_headers(depth.cl1["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_VIAL, 409)

    still_available = depth.read_lot(lot["id"])
    assert still_available["status"] == "AVAILABLE"
    assert_vial_counters(still_available, vials_on_hand=5, vials_reserved=0)

    exposure = validate_success(
        depth.api.get_drug_lot_exposure(lot["id"], tech, f.exposure_params(basis="CARRYING")), 200
    )
    assert exposure["days_held"] == 45
    assert exposure["unconsumed_vials"] == 5
    assert exposure["unconsumed_value_cents"] == 660000
    assert exposure["exposure_cents"] == 16274


def test_the_sweep_is_what_finally_moves_the_lot_and_its_vials_to_expired(depth, tech):
    """
    The sweep run at the same instant expires the lot, expires all five vials and
    stamps the accrual the read alone never persisted.

    The sweep's own rule is inclusive at the boundary: "Any lot whose status is
    `AVAILABLE` and whose `expiration_date` is at or before the logical clock moves
    `AVAILABLE → EXPIRED`, every vial of that lot still in `IN_STOCK` moves to
    `EXPIRED`, `vials_on_hand` and `vials_expired` are recomputed".  It also writes
    what the exposure read would not: "For each visited lot the carrying accrual
    described above is recomputed and *persisted* into `carrying_cost_accrued_cents`
    — this endpoint is the only writer of that field ... and `last_swept_at` is set
    to the logical clock."  The summary reports "`lots_expired` counts the lots that
    moved to `EXPIRED` on this run, `vials_expired` counts the vials that moved to
    `EXPIRED` on this run".

    Design: Difficulty/cross_entity_state_dependency/vial_eligibility_keyed_on_parent_lot_expiry_while_the_vial_stays_in_stock
    """
    lot, _, _, _ = _short_dated_lot_and_plan(depth)

    summary = validate_success(depth.api.run_expiration_sweep({}, tech), 200)
    assert summary["lots_swept"] == 1
    assert summary["lots_expired"] == 1
    assert summary["vials_expired"] == 5
    assert_instant_equals(summary["swept_at"], SHORT_DATED_EXPIRY, "swept_at")

    swept = depth.read_lot(lot["id"])
    assert swept["status"] == "EXPIRED"
    assert_instant_equals(swept["last_swept_at"], SHORT_DATED_EXPIRY, "last_swept_at")
    assert_vial_counters(swept, vials_expired=5, vials_on_hand=0)
