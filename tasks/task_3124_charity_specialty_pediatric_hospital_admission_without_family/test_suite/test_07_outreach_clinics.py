"""Outreach clinics and screenings: padded-interval conflict, capacity,
clock-driven activation/expiry, conversion, and hospital suspend cascade."""
from test_helpers import (
    ApiErrorId,
    create_outreach_clinic,
    create_referral_source,
    create_screening,
    decide,
    get_clinic,
    get_screening,
    make_admin_headers,
    open_review,
    cast_vote,
    set_clock,
    setup_confirmed_clinic,
    setup_hospital_with_program,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap
# ---------------------------------------------------------------------------

def test_clinic_padded_interval_location_conflict_blocked(api, outreach_headers):
    """PRD §3.8: "Confirming a clinic runs a network-wide conflict check: no other clinic of any hospital, itself in `CONFIRMED` or `IN_PROGRESS` status, may sit within 25.0 miles (haversine) of this clinic's coordinates with an overlapping padded interval — two clinics conflict unless one's `end_date` plus a 7-day buffer falls strictly before the other's `start_date`, so intervals padded by 7 days on the end side must not interleave, and a violation is rejected with `ERR_CLINIC_LOCATION_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/clinic_padded_interval_location_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _ = setup_confirmed_clinic()  # CL1 CONFIRMED 2026-10-01..2026-10-02
    cl2 = create_outreach_clinic(
        hospital["id"], location_name="Pendleton-too-soon",
        start_date="2026-10-08T00:00:00Z", end_date="2026-10-09T00:00:00Z",
    )
    # 2026-10-02 + 7d = 2026-10-09 is NOT strictly before 2026-10-08.
    resp = api.confirm_clinic(cl2["id"], outreach_headers)
    validate_error(resp, ApiErrorId.ERR_CLINIC_LOCATION_CONFLICT.value, expected_status=409)
    assert get_clinic(cl2["id"])["status"] == "PROPOSED"


def test_clinic_padded_interval_location_conflict_allowed(api, outreach_headers):
    """PRD §3.8: "Confirming a clinic runs a network-wide conflict check: no other clinic of any hospital, itself in `CONFIRMED` or `IN_PROGRESS` status, may sit within 25.0 miles (haversine) of this clinic's coordinates with an overlapping padded interval — two clinics conflict unless one's `end_date` plus a 7-day buffer falls strictly before the other's `start_date`, so intervals padded by 7 days on the end side must not interleave, and a violation is rejected with `ERR_CLINIC_LOCATION_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/clinic_padded_interval_location_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _ = setup_confirmed_clinic()  # CL1 CONFIRMED 2026-10-01..2026-10-02
    cl3 = create_outreach_clinic(
        hospital["id"], location_name="Pendleton-ok",
        start_date="2026-10-10T00:00:00Z", end_date="2026-10-11T00:00:00Z",
    )
    # 2026-10-02 + 7d = 2026-10-09 < 2026-10-10 -> no conflict.
    confirmed = validate_success(api.confirm_clinic(cl3["id"], outreach_headers))
    assert confirmed["status"] == "CONFIRMED"


def test_screening_date_inside_closed_interval_and_capacity(api, outreach_headers):
    """PRD §3.8: "Screenings are booked against a clinic with the screened patient's `patient_full_name`, `patient_date_of_birth`, `suspected_condition_category`, and a `screening_date` that must fall inside the clinic's closed interval — a date outside the interval is rejected with `ERR_SCREENING_DATE_OUTSIDE_CLINIC` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/screening_date_inside_closed_interval_and_capacity
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_hospital
    hospital = create_hospital()
    clinic = create_outreach_clinic(hospital["id"])

    s1 = create_screening(clinic["id"], patient_full_name="S Start",
                          screening_date="2026-10-01T00:00:00Z")
    assert s1["status"] == "BOOKED"
    s2 = create_screening(clinic["id"], patient_full_name="S End",
                          screening_date="2026-10-02T00:00:00Z")
    assert s2["status"] == "BOOKED"

    late = api.create_screening(
        clinic["id"],
        {"patient_full_name": "S Late",
         "patient_date_of_birth": "2019-05-01T00:00:00Z",
         "suspected_condition_category": "ORTHOPEDIC",
         "screening_date": "2026-10-03T00:00:00Z"},
        outreach_headers,
    )
    validate_error(late, ApiErrorId.ERR_SCREENING_DATE_OUTSIDE_CLINIC.value,
                   expected_status=409)


def test_screening_capacity_rejects_third_booking(api, outreach_headers):
    """PRD §3.8: "Booking consumes capacity: if the clinic's `booked_screening_count` already equals its `screening_capacity`, the booking fails with `ERR_CLINIC_CAPACITY_REACHED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/screening_date_inside_closed_interval_and_capacity
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_hospital
    hospital = create_hospital()
    clinic = create_outreach_clinic(hospital["id"])  # capacity 2

    create_screening(clinic["id"], patient_full_name="S Start",
                     screening_date="2026-10-01T00:00:00Z")
    create_screening(clinic["id"], patient_full_name="S End",
                     screening_date="2026-10-02T00:00:00Z")
    third = api.create_screening(
        clinic["id"],
        {"patient_full_name": "S Third",
         "patient_date_of_birth": "2019-05-01T00:00:00Z",
         "suspected_condition_category": "ORTHOPEDIC",
         "screening_date": "2026-10-02T00:00:00Z"},
        outreach_headers,
    )
    validate_error(third, ApiErrorId.ERR_CLINIC_CAPACITY_REACHED.value, expected_status=409)
    assert get_clinic(clinic["id"])["booked_screening_count"] == 2


# ---------------------------------------------------------------------------
# Corner/state_machines
# ---------------------------------------------------------------------------

def test_clinic_auto_in_progress_on_clock_touch(api, outreach_headers):
    """PRD §2.4: "Setting the clock is not a passive read of a variable: it runs a clock-touch cascade across the network. Any outreach clinic in `CONFIRMED` status whose `start_date` has been reached transitions to `IN_PROGRESS`."

    Design: Corner/state_machines/clinic_auto_in_progress_on_clock_touch
    """
    set_clock("2026-09-01T00:00:00Z")
    _, clinic = setup_confirmed_clinic()

    set_clock("2026-09-30T00:00:00Z")
    assert get_clinic(clinic["id"])["status"] == "CONFIRMED"

    set_clock("2026-10-01T00:00:00Z")
    assert get_clinic(clinic["id"])["status"] == "IN_PROGRESS"


def test_screening_no_show_rebook_cycle_rechecks_capacity(api, outreach_headers):
    """PRD §3.8: "A `NO_SHOW` screening may be rebooked back to `BOOKED` with a `new_screening_date` inside the clinic interval, provided the parent clinic is `CONFIRMED` or `IN_PROGRESS` and the capacity check passes again — another booking may have taken the released slot, in which case rebooking fails with `ERR_CLINIC_CAPACITY_REACHED`."

    Design: Corner/state_machines/screening_no_show_rebook_cycle_rechecks_capacity
    """
    set_clock("2026-09-01T00:00:00Z")
    _, clinic = setup_confirmed_clinic(clinic_overrides={"screening_capacity": 1})
    sc1 = create_screening(clinic["id"], patient_full_name="Scout One",
                           screening_date="2026-10-01T00:00:00Z")
    validate_success(api.mark_screening_no_show(sc1["id"], outreach_headers))
    sc2 = create_screening(clinic["id"], patient_full_name="Scout Two",
                           patient_date_of_birth="2019-06-01T00:00:00Z",
                           screening_date="2026-10-02T00:00:00Z")

    resp = api.rebook_screening(sc1["id"], "2026-10-02T00:00:00Z", outreach_headers)
    validate_error(resp, ApiErrorId.ERR_CLINIC_CAPACITY_REACHED.value, expected_status=409)
    assert get_screening(sc1["id"])["status"] == "NO_SHOW"
    assert get_screening(sc2["id"])["status"] == "BOOKED"
    assert get_clinic(clinic["id"])["booked_screening_count"] == 1


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers
# ---------------------------------------------------------------------------

def test_scheduled_clock_touch_expires_screenings_past_deadline(api, outreach_headers):
    """PRD §2.4: "Any screening in `COMPLETED` status whose parent clinic's `conversion_deadline` has passed transitions to `EXPIRED`."

    Design: Corner/cross_cutting_layers/scheduled_clock_touch_expires_screenings_past_deadline
    """
    set_clock("2026-09-01T00:00:00Z")
    _, clinic = setup_confirmed_clinic(clinic_overrides={"screening_capacity": 3})
    sc1 = create_screening(clinic["id"], patient_full_name="Scout Expire",
                           patient_date_of_birth="2020-01-01T00:00:00Z",
                           screening_date="2026-10-01T00:00:00Z")
    set_clock("2026-10-01T00:00:00Z")
    validate_success(api.record_screening_outcome(sc1["id"], outreach_headers))

    # 2026-12-31 == conversion_deadline (2026-10-02 + 90 days): still COMPLETED.
    set_clock("2026-12-31T00:00:00Z")
    assert get_screening(sc1["id"])["status"] == "COMPLETED"

    set_clock("2027-01-01T00:00:00Z")
    assert get_screening(sc1["id"])["status"] == "EXPIRED"


def test_derived_booked_count_reconciles_across_no_show_and_rebook(api, outreach_headers):
    """PRD §3.8: "A `BOOKED` screening may instead be marked `NO_SHOW`, which releases its capacity slot by decrementing `booked_screening_count`."

    Design: Corner/cross_cutting_layers/derived_booked_count_reconciles_across_no_show_and_rebook
    """
    set_clock("2026-09-01T00:00:00Z")
    _, clinic = setup_confirmed_clinic()
    sca = create_screening(clinic["id"], patient_full_name="Scout A",
                           patient_date_of_birth="2020-01-01T00:00:00Z",
                           screening_date="2026-10-01T00:00:00Z")
    create_screening(clinic["id"], patient_full_name="Scout B",
                     patient_date_of_birth="2020-02-01T00:00:00Z",
                     screening_date="2026-10-02T00:00:00Z")
    assert get_clinic(clinic["id"])["booked_screening_count"] == 2

    validate_success(api.mark_screening_no_show(sca["id"], outreach_headers))
    assert get_clinic(clinic["id"])["booked_screening_count"] == 1

    rebooked = validate_success(api.rebook_screening(
        sca["id"], "2026-10-02T00:00:00Z", outreach_headers,
    ))
    assert rebooked["status"] == "BOOKED"
    assert rebooked["screening_date"] == "2026-10-02T00:00:00Z"
    assert get_clinic(clinic["id"])["booked_screening_count"] == 2


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade
# ---------------------------------------------------------------------------

def test_hospital_suspend_cascade_programs_clinics_screenings(api, admin_headers):
    """PRD §2.9: "Suspending a hospital suspends all of its `ACTIVE` programs in the same operation and cancels every `PROPOSED` outreach clinic the hospital sponsors, which in turn expires each of those clinics' `BOOKED` screenings."

    Design: Difficulty/transitive_cascade/hospital_suspend_cascade_programs_clinics_screenings
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_hospital, create_program
    hospital = create_hospital()
    program = create_program(hospital["id"])
    cl1 = create_outreach_clinic(hospital["id"])  # PROPOSED
    sc1 = create_screening(cl1["id"])
    cl2 = create_outreach_clinic(
        hospital["id"], location_name="Pendleton again",
        start_date="2027-01-01T00:00:00Z", end_date="2027-01-02T00:00:00Z",
    )
    from test_helpers import make_outreach_headers
    validate_success(api.confirm_clinic(cl2["id"], make_outreach_headers("op-1")))

    validate_success(api.suspend_hospital(hospital["id"], admin_headers))
    assert validate_success(api.get_hospital(hospital["id"], admin_headers))["status"] == "SUSPENDED"
    assert validate_success(api.get_program(program["id"], admin_headers))["status"] == "SUSPENDED"
    assert get_clinic(cl1["id"])["status"] == "CANCELLED_CLINIC"
    assert get_clinic(cl2["id"])["status"] == "CONFIRMED"
    assert get_screening(sc1["id"])["status"] == "EXPIRED"


def test_hospital_suspend_cascade_is_conditional_on_child_state(api, admin_headers):
    """PRD §3.1: "Suspending a hospital (only valid from `OPEN`) moves it to `SUSPENDED`, cascades all its `ACTIVE` programs to `SUSPENDED`, and cancels every `PROPOSED` outreach clinic it sponsors — expiring those clinics' `BOOKED` screenings along the way."

    Design: Difficulty/transitive_cascade/hospital_suspend_cascade_programs_clinics_screenings
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_hospital, create_program, make_outreach_headers
    hospital = create_hospital()
    create_program(hospital["id"])
    cl1 = create_outreach_clinic(hospital["id"])  # PROPOSED with a BOOKED screening
    create_screening(cl1["id"])
    cl2 = create_outreach_clinic(
        hospital["id"], location_name="Later clinic",
        start_date="2027-01-01T00:00:00Z", end_date="2027-01-02T00:00:00Z",
    )
    validate_success(api.confirm_clinic(cl2["id"], make_outreach_headers("op-1")))

    validate_success(api.suspend_hospital(hospital["id"], admin_headers))
    # The conditional cascade: only the PROPOSED clinic dies.
    assert get_clinic(cl1["id"])["status"] == "CANCELLED_CLINIC"
    assert get_clinic(cl2["id"])["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Corner/calculations + Corner/validations (conversion window & linkage)
# ---------------------------------------------------------------------------

def _setup_completed_screening_scenario():
    """Clinic (2026-10-01..2026-10-02, deadline 2026-12-31) CONFIRMED, walked to
    IN_PROGRESS, with a COMPLETED ORTHOPEDIC screening. Returns
    (hospital, program, source, clinic, screening)."""
    set_clock("2026-09-01T00:00:00Z")
    hospital, program, _ = setup_hospital_with_program()
    rs_oc = create_referral_source(
        source_type="OUTREACH_CLINIC", display_name="Pendleton Clinic",
        contact_email="clinic@example.org",
    )
    clinic = create_outreach_clinic(hospital["id"], screening_capacity=3)
    from test_helpers import make_outreach_headers
    outreach = make_outreach_headers("op-1")
    __import__("test_helpers").validate_success(
        __import__("test_helpers").api_client.confirm_clinic(clinic["id"], outreach)
    )
    screening = create_screening(
        clinic["id"], patient_full_name="Scout Conv",
        patient_date_of_birth="2020-01-01T00:00:00Z",
        screening_date="2026-10-01T00:00:00Z",
    )
    set_clock("2026-10-01T00:00:00Z")
    __import__("test_helpers").validate_success(
        __import__("test_helpers").api_client.record_screening_outcome(
            screening["id"], outreach,
        )
    )
    return hospital, program, rs_oc, clinic, screening


def test_screening_conversion_deadline_inclusive_then_expiry(api, admin_headers):
    """PRD §3.8: "When a `PatientApplication` carrying a `screening_id` is accepted, the linked screening — which must be in `COMPLETED` status — transitions automatically to `CONVERTED` and records the new application's id as `converted_application_id`, provided the logical clock has not passed the parent clinic's `conversion_deadline`; conversion at exactly the deadline succeeds, while a conversion attempt past the deadline fails with `ERR_CONVERSION_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/calculations/screening_conversion_deadline_inclusive_then_expiry
    """
    hospital, program, rs_oc, clinic, screening = _setup_completed_screening_scenario()
    from test_helpers import create_application
    application = create_application(
        rs_oc["id"], program["id"], patient_full_name="Scout Conv",
        home_latitude=45.67, home_longitude=-118.79, screening_id=screening["id"],
    )
    open_review(application["id"])
    cast_vote(application["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(application["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")

    set_clock("2026-12-31T00:00:00Z")  # exactly the conversion deadline
    accepted = decide(application["id"], decision="ACCEPT",
                      decision_reason="convert at deadline", reviewer="rcm-3")
    assert accepted["status"] == "ACCEPTED"

    converted = get_screening(screening["id"])
    assert converted["status"] == "CONVERTED"
    assert converted["converted_application_id"] == application["id"]
    assert get_clinic(clinic["id"])["conversion_deadline"] == "2026-12-31T00:00:00Z"


def test_screening_conversion_past_deadline_rejected(api, admin_headers):
    """PRD §3.8: "When a `PatientApplication` carrying a `screening_id` is accepted, the linked screening — which must be in `COMPLETED` status — transitions automatically to `CONVERTED` and records the new application's id as `converted_application_id`, provided the logical clock has not passed the parent clinic's `conversion_deadline`; conversion at exactly the deadline succeeds, while a conversion attempt past the deadline fails with `ERR_CONVERSION_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/calculations/screening_conversion_deadline_inclusive_then_expiry
    """
    hospital, program, rs_oc, clinic, screening = _setup_completed_screening_scenario()
    from test_helpers import create_application, get_application, make_reviewer_headers
    application = create_application(
        rs_oc["id"], program["id"], patient_full_name="Scout Conv",
        home_latitude=45.67, home_longitude=-118.79, screening_id=screening["id"],
    )
    open_review(application["id"])
    cast_vote(application["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(application["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")

    set_clock("2027-01-01T00:00:00Z")  # one day past the deadline
    current = get_application(application["id"])
    resp = __import__("test_helpers").api_client.decide_application(
        application["id"],
        {"decision": "ACCEPT", "decision_reason": "too late",
         "expected_application_version": current["version"]},
        make_reviewer_headers("rcm-3"),
    )
    validate_error(resp, ApiErrorId.ERR_CONVERSION_WINDOW_CLOSED.value, expected_status=409)


def test_screening_linkage_mismatch_category_or_hospital_wrong_hospital(api, intake_headers):
    """PRD §3.2: "Finally, screening linkage integrity: when `screening_id` is supplied, it must reference a screening in `COMPLETED` status belonging to a clinic sponsored by the same hospital as the applied program, and the screening's `suspected_condition_category` must equal the application's `condition_category` — a mismatch on any of those three points is `ERR_SCREENING_MISMATCH` (HTTP 422)."

    Design: Corner/validations/screening_linkage_mismatch_category_or_hospital
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_hospital, create_program
    h1, p1, _ = setup_hospital_with_program(
        hospital_overrides={"hospital_code": "H1"},
    )
    h2 = create_hospital(
        hospital_code="H2", name="Hospital Two", city="Spokane", state_code="WA",
        latitude=47.6, longitude=-117.4,
    )
    rs_oc = create_referral_source(
        source_type="OUTREACH_CLINIC", display_name="Clinic Src",
        contact_email="clinic@example.org",
    )
    from test_helpers import make_outreach_headers
    outreach = make_outreach_headers("op-1")
    cl2 = create_outreach_clinic(
        h2["id"], location_name="Boise", latitude=43.6, longitude=-116.2,
        screening_capacity=3,
    )
    validate_success(api.confirm_clinic(cl2["id"], outreach))
    sc2 = create_screening(
        cl2["id"], patient_full_name="Scout H2",
        patient_date_of_birth="2020-01-01T00:00:00Z",
        screening_date="2026-10-01T00:00:00Z",
    )
    set_clock("2026-10-01T00:00:00Z")
    validate_success(api.record_screening_outcome(sc2["id"], outreach))

    from test_helpers import create_application_payload
    payload = create_application_payload(
        rs_oc["id"], p1["id"], patient_full_name="Kid WrongHosp",
        screening_id=sc2["id"],
    )
    resp = api.create_application(payload, intake_headers)
    validate_error(resp, ApiErrorId.ERR_SCREENING_MISMATCH.value, expected_status=422)


def test_screening_linkage_mismatch_wrong_condition_category(api, intake_headers):
    """PRD §3.2: "Finally, screening linkage integrity: when `screening_id` is supplied, it must reference a screening in `COMPLETED` status belonging to a clinic sponsored by the same hospital as the applied program, and the screening's `suspected_condition_category` must equal the application's `condition_category` — a mismatch on any of those three points is `ERR_SCREENING_MISMATCH` (HTTP 422)."

    Design: Corner/validations/screening_linkage_mismatch_category_or_hospital
    """
    set_clock("2026-09-01T00:00:00Z")
    h1, p1, _ = setup_hospital_with_program()
    rs_oc = create_referral_source(
        source_type="OUTREACH_CLINIC", display_name="Clinic Src",
        contact_email="clinic@example.org",
    )
    from test_helpers import make_outreach_headers
    outreach = make_outreach_headers("op-1")
    cl1 = create_outreach_clinic(h1["id"], screening_capacity=3)
    validate_success(api.confirm_clinic(cl1["id"], outreach))
    sc1 = create_screening(
        cl1["id"], patient_full_name="Scout Burn",
        patient_date_of_birth="2020-01-01T00:00:00Z",
        suspected_condition_category="BURN",
        screening_date="2026-10-01T00:00:00Z",
    )
    set_clock("2026-10-01T00:00:00Z")
    validate_success(api.record_screening_outcome(sc1["id"], outreach))

    from test_helpers import create_application_payload
    payload = create_application_payload(
        rs_oc["id"], p1["id"], patient_full_name="Kid WrongCat",
        screening_id=sc1["id"],
    )
    resp = api.create_application(payload, intake_headers)
    validate_error(resp, ApiErrorId.ERR_SCREENING_MISMATCH.value, expected_status=422)
