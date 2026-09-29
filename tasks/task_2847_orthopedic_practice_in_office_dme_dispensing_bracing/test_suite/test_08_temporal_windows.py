"""Two contended resources with deliberately different interval semantics: a
fitter's chair, whose booked interval is closed and padded by a changeover
buffer, and a patient's entitlement to one class of device, whose window is
half-open and measured in whole calendar months.
"""

from test_helpers import (
    ApiErrors,
    add_fitter,
    add_patient,
    add_product,
    assert_error,
    assert_list_meta,
    build_practice,
    insurance_coordinator_headers,
    make_dme_fitter_headers,
    read_encounter,
    read_fitter,
    set_clock,
)
from test_helpers import factories as f

COVERED = {"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}


def _two_fitters_and_a_booked_chair(api):
    """One clinic with two fitters, three reserved encounters, and the first fitter
    already holding a session from ten o'clock to half past."""
    practice = build_practice(api)
    second_fitter = add_fitter(practice, full_name="Mira Selk")
    patient_two = add_patient(practice, full_name="Joel Pike")
    patient_three = add_patient(practice, full_name="Nia Frost")
    first = practice.reserved_encounter(coverage=COVERED)
    second = practice.reserved_encounter(coverage=COVERED, patient_id=patient_two["id"])
    third = practice.reserved_encounter(coverage=COVERED, patient_id=patient_three["id"])
    booked = practice.fit(
        first, start_at="2026-08-01T10:00:00Z", end_at="2026-08-01T10:30:00Z"
    )
    assert booked["fitting_minutes"] == 30
    return practice, second_fitter, {"first": first, "second": second, "third": third}


def test_a_gap_of_exactly_the_changeover_buffer_still_conflicts(api):
    """A session starting exactly fifteen minutes after the previous one ended is
    inside the padded interval, so the chair is refused and the waiting encounter
    stays reserved.

    PRD: "The fitter's interval is **closed** and padded by a fifteen-minute
    changeover buffer on each side, so a new interval conflicts with an existing one
    when the new start is at or before the existing end plus fifteen minutes **and**
    the new end is at or after the existing start minus fifteen minutes."

    Design: Difficulty/resource_temporal_overlap/fitter_chair_closed_interval_with_fifteen_minute_changeover_buffer_rejected
    """
    practice, _second_fitter, ids = _two_fitters_and_a_booked_chair(api)

    response = api.create_fitting_record(
        ids["second"],
        f.fitting_record_payload(
            "2026-08-01T10:45:00Z", "2026-08-01T11:15:00Z", measurement_set={"waist_cm": 102}
        ),
        practice.fitter_headers,
    )

    assert_error(response, ApiErrors.FITTING_SLOT_CONFLICT, 409)
    assert read_encounter(api, ids["second"])["clinical_status"] == "RESERVED"
    assert read_fitter(api, practice.fitter_id)["fitting_minutes_booked"] == 30


def test_the_buffer_belongs_to_one_fitter_and_one_extra_minute_clears_it(api):
    """A second fitter takes the very interval the first was refused, and the first
    fitter becomes free one minute later, when the gap is strictly greater than the
    buffer.

    PRD: "The window is scoped to one fitter: two different fitters may hold
    overlapping sessions, and the conflict check considers only the acting fitter's
    own records."

    Design: Difficulty/resource_temporal_overlap/fitter_chair_closed_interval_with_fifteen_minute_changeover_buffer_rejected
    """
    practice, second_fitter, ids = _two_fitters_and_a_booked_chair(api)
    assert_error(
        api.create_fitting_record(
            ids["second"],
            f.fitting_record_payload(
                "2026-08-01T10:45:00Z", "2026-08-01T11:15:00Z", measurement_set={"waist_cm": 102}
            ),
            practice.fitter_headers,
        ),
        ApiErrors.FITTING_SLOT_CONFLICT,
        409,
    )

    other = practice.fit(
        ids["third"],
        start_at="2026-08-01T10:45:00Z",
        end_at="2026-08-01T11:15:00Z",
        fitter_id=second_fitter["id"],
        measurement_set={"waist_cm": 88},
    )
    later = practice.fit(
        ids["second"],
        start_at="2026-08-01T10:46:00Z",
        end_at="2026-08-01T11:16:00Z",
        measurement_set={"waist_cm": 102},
    )

    assert other["fitting_minutes"] == 30
    assert later["fitting_minutes"] == 30
    assert read_fitter(api, practice.fitter_id)["fitting_minutes_booked"] == 60
    assert read_fitter(api, second_fitter["id"])["fitting_minutes_booked"] == 30
    assert read_encounter(api, ids["second"])["clinical_status"] == "FITTED"
    assert read_encounter(api, ids["third"])["clinical_status"] == "FITTED"
    assert_list_meta(
        api.list_fitting_records(
            make_dme_fitter_headers(practice.fitter_id), {"fitter_id": practice.fitter_id}
        ),
        expected_total=2,
    )


def _entitlement_consumed_then_three_candidates(api):
    """A patient who took delivery of a lumbar brace six calendar months ago, with
    three fresh encounters awaiting coverage: the same patient in the same device
    class, the same patient in another class, and a different patient in the first
    class.
    """
    practice = build_practice(api, clinic={"accreditation_expires_on": "2028-12-31"})
    collar = add_product(practice, f.cervical_collar_product_payload(practice.supplier_id))
    other_patient = add_patient(practice, full_name="Joel Pike")
    delivered = practice.delivered_encounter(coverage=COVERED)
    assert read_encounter(api, delivered)["clinical_status"] == "DELIVERED"
    set_clock(api, "2027-02-01T00:00:00Z")
    same_group = practice.attested_encounter()
    other_group = practice.attested_encounter(product_id=collar["id"])
    other_patient_same_group = practice.attested_encounter(patient_id=other_patient["id"])
    return practice, delivered, same_group, other_group, other_patient_same_group


def test_the_same_patient_in_the_same_device_class_is_still_inside_the_window(api):
    """Six whole months into a sixty-month lifetime the entitlement is occupied, so
    a covered verification for the same class is refused.

    PRD: "The candidate set is every other dispensing encounter of the *same*
    patient whose `clinical_status` is `DELIVERED` and whose product shares this
    product's `same_or_similar_group`, gathered across every clinic of the practice."

    Design: Difficulty/resource_temporal_overlap/patient_lifetime_entitlement_window_is_scoped_per_patient_and_group_rejected
    """
    _practice, delivered, same_group, _other_group, _other_patient = (
        _entitlement_consumed_then_three_candidates(api)
    )

    response = api.create_coverage_verification(
        same_group, f.coverage_verification_payload(**COVERED), insurance_coordinator_headers()
    )

    assert_error(response, ApiErrors.SAME_OR_SIMILAR_CONFLICT, 409)
    assert read_encounter(api, same_group)["financial_status"] == "UNVERIFIED"
    assert read_encounter(api, delivered)["clinical_status"] == "DELIVERED"


def test_a_different_device_class_and_a_different_patient_each_have_their_own_window(api):
    """The window is keyed by the pair of patient and device class: the same patient
    in another class and another patient in the same class both verify cleanly with
    no predecessor recorded at all.

    PRD: "When the candidate set is empty, `prior_delivered_encounter_id`,
    `prior_delivered_on` and `months_since_prior_delivery` are all null and
    `same_or_similar_conflict` is false."

    Design: Difficulty/resource_temporal_overlap/patient_lifetime_entitlement_window_is_scoped_per_patient_and_group_rejected
    """
    practice, _delivered, _same_group, other_group, other_patient_same_group = (
        _entitlement_consumed_then_three_candidates(api)
    )

    for encounter_id in (other_group, other_patient_same_group):
        verification = practice.verify_coverage(encounter_id, **COVERED)
        assert verification["same_or_similar_conflict"] is False
        assert verification["prior_delivered_encounter_id"] is None
        assert verification["prior_delivered_on"] is None
        assert verification["months_since_prior_delivery"] is None
        assert read_encounter(api, encounter_id)["financial_status"] == "VERIFIED"
