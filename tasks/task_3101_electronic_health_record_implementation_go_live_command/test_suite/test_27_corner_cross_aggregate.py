"""Cross-aggregate compensation, release allocation and program-level gating."""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    get_success_data,
    get_facility,
    get_program,
    setup_program,
    setup_program_and_facility,
    setup_program_facility_department,
    create_conversion_batch,
    create_optimization_item,
    create_interface_channel,
    set_clock,
    DIRECTOR,
    ANALYST,
    BUILD_ANALYST,
    CONVERSION,
    INTERFACE,
    OPTIMIZATION,
    TRAINING,
)


# ===========================================================================
# c_conversion_batch_rollback_reverses_patient_count
# ===========================================================================

def test_loading_a_patient_batch_raises_the_facility_converted_patient_count(api, conversion_headers, analyst_headers):
    """PRD §3.2: "Loading a batch credits the facility: a `PATIENT_DEMOGRAPHICS`
    load adds its `reconciled_count` to `converted_patient_count`".
    PRD §3.2: "Reports read four facility-level measures: `converted_patient_count`,
    the conserved count of active patients loaded and not rolled back".

    Design: Corner/endpoints/c_conversion_batch_rollback_reverses_patient_count
    """
    prog, fac = setup_program_and_facility()
    batch = create_conversion_batch(
        fac["id"], payload_class="PATIENT_DEMOGRAPHICS", attempt_epoch=0,
        source_count=1000, reconciled_count=990,
        expected_facility_version=fac["version"],
    )
    get_success_data(api_client.begin_batch_validation(batch["id"], conversion_headers))
    loaded = validate_success(api_client.load_batch(batch["id"], conversion_headers), 200)
    assert loaded["status"] == "LOADED"

    facility = get_facility(fac["id"], analyst_headers)
    assert facility["converted_patient_count"] == 990


def test_rolling_the_batch_back_reverses_the_credited_patient_count(api, conversion_headers, analyst_headers):
    """PRD §3.2: "Rolling back may be done from `LOADED` or from `RECONCILED`; it
    subtracts `reconciled_count` from `converted_patient_count` — so a load
    followed by a rollback leaves the count where it began".
    PRD §3.2: "`FAILED` and `ROLLED_BACK` as its other terminal outcomes".

    Design: Corner/endpoints/c_conversion_batch_rollback_reverses_patient_count
    """
    prog, fac = setup_program_and_facility()
    batch = create_conversion_batch(
        fac["id"], payload_class="PATIENT_DEMOGRAPHICS", attempt_epoch=0,
        source_count=1000, reconciled_count=990,
        expected_facility_version=fac["version"],
    )
    get_success_data(api_client.begin_batch_validation(batch["id"], conversion_headers))
    get_success_data(api_client.load_batch(batch["id"], conversion_headers))

    rolled = validate_success(api_client.rollback_batch(batch["id"], conversion_headers), 200)
    assert rolled["status"] == "ROLLED_BACK"

    facility = get_facility(fac["id"], analyst_headers)
    assert facility["converted_patient_count"] == 0, (
        "the load and its compensating rollback net to the pre-load count"
    )


# ===========================================================================
# c_optimization_waterfall_overflows_large_item_to_next_epoch
# ===========================================================================

def test_a_full_epoch_capacity_admits_its_exact_consumer(api, director_headers, optimization_headers):
    """PRD §3.11: "Each epoch offers a release capacity of 30 points."
    PRD §3.11: "The head of that queue is offered the capacity of the epoch named
    by the scheduling request's `target_epoch` — the 30-point budget less the
    `effort_points` already committed by items already `SCHEDULED` for that same
    epoch."

    A 30-point item consumes the whole epoch exactly, so it is scheduled into the
    epoch it asked for.

    Design: Corner/endpoints/c_optimization_waterfall_overflows_large_item_to_next_epoch
    """
    set_clock()
    prog = setup_program()
    fac = get_success_data(api_client.create_facility(prog["id"], {
        "name": "Northline Memorial", "facility_type": "ACUTE_CARE", "bed_count": 240,
        "rollout_wave": 1, "conversion_scope": "FULL_RECORD",
    }, DIRECTOR))
    dept = get_success_data(api_client.create_department(fac["id"], {
        "department_code": "LAB", "application_scope": ["LAB"], "required_staff_count": 1,
    }, BUILD_ANALYST))
    advanced = validate_success(api_client.advance_epoch(prog["id"], director_headers), 200)

    big = validate_success(api_client.create_optimization_item(
        {
            "department_id": dept["id"], "title": "Big release", "effort_points": 30,
            "expected_ehr_implementation_version": advanced["version"],
        },
        optimization_headers,
    ), 201)
    get_success_data(api_client.triage_optimization_item(big["id"], optimization_headers))
    scheduled = validate_success(
        api_client.schedule_optimization_item(big["id"], {"target_epoch": 1}, optimization_headers), 200
    )
    assert scheduled["scheduled_epoch"] == 1, "30 points exactly consumes the 30-point capacity"


def test_an_item_that_no_longer_fits_overflows_to_the_following_epoch(api, director_headers, optimization_headers):
    """PRD §3.11: "An item whose effort fits within what remains is scheduled into
    the requested epoch; an item that overflows rather than fits is scheduled into
    the following epoch instead, so it lands at the next release rather than being
    refused."
    PRD §3.11: "The consequence of smallest-first ordering is visible whenever a
    large request precedes a small one: the large item overflows to the next epoch
    while the small item, raised later, fits into the current one."

    With epoch 1 fully consumed by the 30-point item, an 8-point item targeted at
    epoch 1 overflows to epoch 2 rather than being refused.

    Design: Corner/endpoints/c_optimization_waterfall_overflows_large_item_to_next_epoch
    """
    set_clock()
    prog = setup_program()
    fac = get_success_data(api_client.create_facility(prog["id"], {
        "name": "Northline Memorial", "facility_type": "ACUTE_CARE", "bed_count": 240,
        "rollout_wave": 1, "conversion_scope": "FULL_RECORD",
    }, DIRECTOR))
    dept = get_success_data(api_client.create_department(fac["id"], {
        "department_code": "LAB", "application_scope": ["LAB"], "required_staff_count": 1,
    }, BUILD_ANALYST))
    advanced = validate_success(api_client.advance_epoch(prog["id"], director_headers), 200)

    big = validate_success(api_client.create_optimization_item(
        {
            "department_id": dept["id"], "title": "Big release", "effort_points": 30,
            "expected_ehr_implementation_version": advanced["version"],
        },
        optimization_headers,
    ), 201)
    get_success_data(api_client.triage_optimization_item(big["id"], optimization_headers))
    validate_success(
        api_client.schedule_optimization_item(big["id"], {"target_epoch": 1}, optimization_headers), 200
    )

    current = get_program(prog["id"], director_headers)
    small = validate_success(api_client.create_optimization_item(
        {
            "department_id": dept["id"], "title": "Small release", "effort_points": 8,
            "expected_ehr_implementation_version": current["version"],
        },
        optimization_headers,
    ), 201)
    get_success_data(api_client.triage_optimization_item(small["id"], optimization_headers))
    small_scheduled = validate_success(
        api_client.schedule_optimization_item(small["id"], {"target_epoch": 1}, optimization_headers), 200
    )

    assert small_scheduled["scheduled_epoch"] == 2, "the 8-point item overflows epoch 1"
    assert small_scheduled["status"] == "SCHEDULED"


# ===========================================================================
# c_finalize_validation_blocked_by_unvalidated_channel
# ===========================================================================

def test_finalizing_validation_with_a_channel_short_of_validated_is_refused(api, director_headers, interface_headers, analyst_headers):
    """PRD §3.6: "No facility may be granted cutover readiness, no program may
    finalize its validation phase, and no cutover step may complete while any
    interface channel of the program remains short of `VALIDATED`; the refusal
    carries `ERR_CHANNEL_NOT_VALIDATED` (HTTP 422)."
    PRD §3.1: "Moving from build into validation is stricter about the build
    estate: every non-archived system build item belonging to the program must be
    in `BUILD_COMPLETE`, `IN_TESTING` or `VALIDATION_COMPLETE` — none may remain
    in `DRAFT`, `IN_BUILD` or `BUILD_REJECTED`."

    Design: Corner/endpoints/c_finalize_validation_blocked_by_unvalidated_channel
    """
    set_clock()
    prog = setup_program()
    fac = get_success_data(api_client.create_facility(prog["id"], {
        "name": "Northline Memorial", "facility_type": "ACUTE_CARE", "bed_count": 240,
        "rollout_wave": 1, "conversion_scope": "FULL_RECORD",
    }, DIRECTOR))
    channel = create_interface_channel(prog["id"])
    assert fac["status"] == "SITE_REGISTERED"
    assert channel["status"] == "DEFINED"

    validate_success(api_client.start_build(prog["id"], director_headers), 200)
    started = validate_success(api_client.start_validation(prog["id"], director_headers), 200)
    assert started["status"] == "VALIDATION_IN_PROGRESS"

    refused = api_client.finalize_validation(prog["id"], director_headers)
    validate_error(refused, ApiErrorId.ERR_CHANNEL_NOT_VALIDATED, expected_status=422)


def test_the_unvalidated_channel_stays_defined_after_the_refused_finalization(api, director_headers, interface_headers):
    """PRD §3.6: "This is the mechanism by which a single unproven laboratory feed
    holds an entire enterprise release at the gate, which is exactly the intent."
    PRD §3.6: "A new channel begins in `DEFINED` with `validated_message_count`
    and `rejected_message_count` both at 0."

    Design: Corner/endpoints/c_finalize_validation_blocked_by_unvalidated_channel
    """
    set_clock()
    prog = setup_program()
    fac = get_success_data(api_client.create_facility(prog["id"], {
        "name": "Northline Memorial", "facility_type": "ACUTE_CARE", "bed_count": 240,
        "rollout_wave": 1, "conversion_scope": "FULL_RECORD",
    }, DIRECTOR))
    channel = create_interface_channel(prog["id"])
    assert fac["status"] == "SITE_REGISTERED"
    validate_success(api_client.start_build(prog["id"], director_headers), 200)
    validate_success(api_client.start_validation(prog["id"], director_headers), 200)
    api_client.finalize_validation(prog["id"], director_headers)

    read = validate_success(api_client.get_interface_channel(channel["id"], interface_headers), 200)
    assert read["status"] == "DEFINED"

    program = get_program(prog["id"], director_headers)
    assert program["status"] == "VALIDATION_IN_PROGRESS"


# ===========================================================================
# c_staff_self_referential_preceptor_link_is_queryable
# ===========================================================================

def test_a_mentee_registered_under_a_preceptor_is_found_by_the_reverse_lookup(api, training_headers):
    """PRD §3.4: "The `preceptor_staff_id` is a self-referential mentorship link
    to another staff member's `id`; it is left empty for a chain root, so
    mentorship chains are traversable by repeated lookup."
    PRD §3.4: "The `preceptor_staff_id` is a self-referential mentorship link
    to another staff member's `id`; it is left empty for a chain root, so
    mentorship chains are traversable by repeated lookup."

    Design: Corner/endpoints/c_staff_self_referential_preceptor_link_is_queryable
    """
    prog, fac, dept = setup_program_facility_department()
    preceptor = get_success_data(api_client.create_staff(
        prog["id"],
        {"full_name": "Mentor Ines", "staff_type": "PROVIDER",
         "primary_facility_id": fac["id"], "department_id": dept["id"],
         "hired_on": "2025-06-01T00:00:00Z"},
        training_headers,
    ))
    mentee = get_success_data(api_client.create_staff(
        prog["id"],
        {"full_name": "Mentee Jonas", "staff_type": "NURSE",
         "primary_facility_id": fac["id"], "department_id": dept["id"],
         "preceptor_staff_id": preceptor["id"], "hired_on": "2026-01-01T00:00:00Z"},
        training_headers,
    ))

    rows, meta = validate_paginated(api_client.list_staffs(
        training_headers, params={"preceptor_staff_id": preceptor["id"]}
    ))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == mentee["id"]
    assert rows[0]["preceptor_staff_id"] == preceptor["id"]


def test_a_mentee_who_precepts_nobody_returns_no_mentees_of_their_own(api, training_headers):
    """PRD §3.4: "it is left empty for a chain root, so mentorship chains are
    traversable by repeated lookup."
    PRD §2.8: "A filter that is omitted imposes no constraint."

    Design: Corner/endpoints/c_staff_self_referential_preceptor_link_is_queryable
    """
    prog, fac, dept = setup_program_facility_department()
    preceptor = get_success_data(api_client.create_staff(
        prog["id"],
        {"full_name": "Mentor Ines", "staff_type": "PROVIDER",
         "primary_facility_id": fac["id"], "department_id": dept["id"],
         "hired_on": "2025-06-01T00:00:00Z"},
        training_headers,
    ))
    mentee = get_success_data(api_client.create_staff(
        prog["id"],
        {"full_name": "Mentee Jonas", "staff_type": "NURSE",
         "primary_facility_id": fac["id"], "department_id": dept["id"],
         "preceptor_staff_id": preceptor["id"], "hired_on": "2026-01-01T00:00:00Z"},
        training_headers,
    ))

    rows, meta = validate_paginated(api_client.list_staffs(
        training_headers, params={"preceptor_staff_id": mentee["id"]}
    ))
    assert meta["total_count"] == 0, "the mentee precepts no one"