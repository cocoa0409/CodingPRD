"""
Thresholds tested one unit and one second either side of the boundary.

The disease-activity verdict flips at exactly 300 micrometres, and the clinician's
daily capacity window includes an encounter exactly twenty-four hours old.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, assert_immutable_entity_fields, assert_vial_counters
from test_helpers import factories as f
from test_helpers.test_users import specialist_headers


# ==========================================================================
# disease_activity_cst_threshold_inclusive_at_300_um
# ==========================================================================


def _quiet_study(depth, thickness):
    """Read one study with no fluid and no haemorrhage at the given thickness."""
    return depth.imaging(
        clinician_id=depth.cl1["id"],
        patient_id=depth.pt4["id"],
        eye="OS",
        study_datetime=depth.CLOCK,
        central_subfield_thickness_um=thickness,
        intraretinal_fluid=False,
        subretinal_fluid=False,
        new_hemorrhage=False,
    )


def test_299_micrometres_is_quiescent_while_exactly_300_is_active(depth):
    """
    Two otherwise identical studies one micrometre apart land on opposite sides of
    the verdict.

    The PRD states the rule and then states the boundary case in the same
    paragraph: "The verdict is `ACTIVE` when the central subfield thickness is at
    least 300 micrometres, or intraretinal fluid is present, or subretinal fluid is
    present, or a new haemorrhage is present — any one of those four conditions
    suffices. When none of the four holds, the verdict is `QUIESCENT`. The
    thickness threshold is inclusive at 300: a reading of 299 micrometres with no
    fluid and no haemorrhage is `QUIESCENT`, while a reading of exactly 300
    micrometres with no fluid and no haemorrhage is `ACTIVE`."  Nothing else may
    intrude: "Nothing outside the study being created participates in the verdict —
    no prior study, no plan history, no drug attribute."

    Design: Difficulty/boundary_precision_check/disease_activity_cst_threshold_inclusive_at_300_um
    """
    below = _quiet_study(depth, 299)
    at = _quiet_study(depth, 300)

    assert below["central_subfield_thickness_um"] == 299
    assert below["disease_activity"] == "QUIESCENT"
    assert at["central_subfield_thickness_um"] == 300
    assert at["disease_activity"] == "ACTIVE"


def test_one_micrometre_above_the_threshold_is_active_and_the_read_is_stamped_and_frozen(
    depth,
):
    """
    A 301-micrometre study is `ACTIVE`, is stamped with the acting specialist and
    carries none of the mutability fields.

    The PRD forbids the client from nominating the interpreter — "The acting
    specialist's own identifier is stamped onto the study as
    `interpreted_by_clinician_id`; a client may not nominate the interpreter" — and
    forbids editing the row at all: "Because a study is an immutable observation it
    is never edited after creation, and as §2.4 establishes it therefore carries
    neither `updated_at` nor `version`."  The verdict itself is not negotiable
    either: "The study's `disease_activity` verdict is computed by the server and a
    client-supplied value is ignored outright."

    Design: Difficulty/boundary_precision_check/disease_activity_cst_threshold_inclusive_at_300_um
    """
    response = depth.api.create_imaging_study(
        f.imaging_payload(
            patient_id=depth.pt4["id"],
            eye="OS",
            study_datetime=depth.CLOCK,
            central_subfield_thickness_um=301,
            intraretinal_fluid=False,
            subretinal_fluid=False,
            new_hemorrhage=False,
            disease_activity="QUIESCENT",
        ),
        specialist_headers(depth.cl1["id"]),
    )
    study = validate_success(response, 201)

    assert study["central_subfield_thickness_um"] == 301
    assert study["disease_activity"] == "ACTIVE"
    assert study["interpreted_by_clinician_id"] == depth.cl1["id"]
    assert_immutable_entity_fields(study)


# ==========================================================================
# capacity_window_closed_at_exactly_twenty_four_hours
# ==========================================================================


def _two_open_access_plans(depth):
    """
    Activate one reference-product plan for each of the two open-access patients and
    book the first patient's encounter, returning both plans and that encounter.
    """
    depth.pol_np_ref
    depth.lot_ref
    plans = []
    for patient, thickness in ((depth.pt3, 402), (depth.pt4, 388)):
        study = depth.imaging(
            clinician_id=depth.cl1["id"],
            patient_id=patient["id"],
            eye="OD",
            study_datetime=depth.CLOCK,
            central_subfield_thickness_um=thickness,
            intraretinal_fluid=True,
        )
        plan = depth.plan(
            clinician_id=depth.cl1["id"],
            patient_id=patient["id"],
            drug_id=depth.drug_ref["id"],
            eye="OD",
        )
        activated = depth.activate_plan(
            plan["id"], clinician_id=depth.cl1["id"], baseline_imaging_study_id=study["id"]
        )
        plans.append((activated, study))

    (first_plan, first_study), (second_plan, second_study) = plans
    first_encounter = depth.encounter(
        clinician_id=depth.cl3["id"],
        treatment_plan_id=first_plan["id"],
        imaging_study_id=first_study["id"],
        encounter_datetime="2026-08-02T09:00:00Z",
        expected_treatment_plan_version=first_plan["version"],
    )
    depth.set_clock("2026-08-03T12:00:00Z")
    return first_plan, first_encounter, second_plan, second_study


def test_an_encounter_exactly_twenty_four_hours_back_still_consumes_capacity(depth):
    """
    A booking placed exactly 86400 seconds after the clinician's only other
    encounter is refused, because the lower endpoint of the window is included.

    The PRD is explicit about both ends: "The server takes a twenty-four-hour window
    that is **closed at both ends** and measured from the requested
    `encounter_datetime` rather than from the logical clock: it runs from that
    instant moved back twenty-four hours through that instant itself. ... An
    existing encounter sitting exactly twenty-four hours before the requested
    instant is *inside* the window and consumes capacity; one at twenty-four hours
    and one second before it is outside."  The clinician's cap is 1, and the window
    of a 2026-08-03T09:00:00Z request opens at 2026-08-02T09:00:00Z where the
    earlier encounter sits.

    Design: Difficulty/boundary_precision_check/capacity_window_closed_at_exactly_twenty_four_hours
    """
    _, _, second_plan, second_study = _two_open_access_plans(depth)

    response = depth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=second_plan["id"],
            imaging_study_id=second_study["id"],
            encounter_datetime="2026-08-03T09:00:00Z",
            expected_treatment_plan_version=second_plan["version"],
        ),
        specialist_headers(depth.cl3["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CLINICIAN_DAY_CAPACITY_EXCEEDED, 409)


def test_one_second_past_the_window_the_same_booking_is_accepted(depth):
    """
    Moving the same request one second later puts the earlier encounter outside the
    window, and the booking succeeds with a fresh reservation.

    The PRD's own boundary sentence supplies the contrast — "one at twenty-four
    hours and one second before it is outside" — and the accepted booking is a
    plan's first, so both lineage fields stay empty: "`previous_encounter_id` is set
    to whatever the plan's `last_encounter_id` was at the moment of creation, and is
    null for a plan's first encounter ... `interval_days_from_previous` records the
    whole days between that previous encounter's `encounter_datetime` and this one's,
    and is likewise null for a first encounter."  Its vial moves "`IN_STOCK →
    RESERVED` with `reserved_for_encounter_id` naming this encounter", leaving two of
    the lot's five vials reserved and three on the shelf.

    Design: Difficulty/boundary_precision_check/capacity_window_closed_at_exactly_twenty_four_hours
    """
    _, first_encounter, second_plan, second_study = _two_open_access_plans(depth)

    response = depth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=second_plan["id"],
            imaging_study_id=second_study["id"],
            encounter_datetime="2026-08-03T09:00:01Z",
            expected_treatment_plan_version=second_plan["version"],
        ),
        specialist_headers(depth.cl3["id"]),
    )
    booked = validate_success(response, 201)

    assert booked["status"] == "DRAFT"
    assert booked["previous_encounter_id"] is None
    assert booked["interval_days_from_previous"] is None

    vial = depth.read_vial(booked["vial_id"])
    assert vial["status"] == "RESERVED"
    assert vial["reserved_for_encounter_id"] == booked["id"]

    untouched = depth.read_encounter(first_encounter["id"])
    assert untouched["status"] == "DRAFT"

    lot = depth.read_lot(depth.lot_ref["id"])
    assert_vial_counters(lot, vials_reserved=2, vials_on_hand=3)
