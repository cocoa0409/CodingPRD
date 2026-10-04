"""Optimistic concurrency and derived-field reconciliation on version-carrying writes."""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    get_success_data,
    get_program,
    get_staff,
    get_facility,
    setup_program,
    setup_program_and_facility,
    setup_program_facility_department,
    create_conversion_batch,
    create_facility,
    create_department,
    create_credentialed_trainer_payload,
    create_optimization_item_payload,
    create_staff_payload,
    set_clock,
    DIRECTOR,
    ANALYST,
    BUILD_ANALYST,
    CONVERSION,
    TRAINING,
    OPTIMIZATION,
)


# ===========================================================================
# c_stale_facility_version_on_batch_create_returns_412
# ===========================================================================

def test_staging_a_batch_against_a_stale_facility_version_is_refused(api, conversion_headers):
    """PRD §2.7: "Staging a legacy data-conversion load against a facility
    requires `expected_facility_version` carrying the client's last observed
    `version` of that `Facility`, and a mismatch yields `ERR_STALE_VERSION`."
    PRD §2.7: "The framing is a stale-read guard, not an overlapping-writer
    mechanic: the client is prevented from acting on a parent whose state has
    legitimately moved on since it last read it."

    Design: Corner/cross_cutting_complexity_layers/c_stale_facility_version_on_batch_create_returns_412
    """
    prog, fac = setup_program_and_facility()
    stale_version = fac["version"]
    create_conversion_batch(
        fac["id"], payload_class="ORDERS", attempt_epoch=0,
        source_count=500, reconciled_count=500,
        expected_facility_version=stale_version,
    )

    refused = api_client.create_conversion_batch(
        fac["id"],
        {
            "payload_class": "BALANCES", "attempt_epoch": 0,
            "source_count": 500, "reconciled_count": 500,
            "expected_facility_version": stale_version,
        },
        conversion_headers,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_the_refused_stale_batch_create_leaves_the_batch_count_alone(api, conversion_headers):
    """PRD §2.7: "when that observed version does not match the parent's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "Data conversion runs in batches, one per `payload_class` —
    `PATIENT_DEMOGRAPHICS`, `APPOINTMENTS`, `ORDERS` or `BALANCES`".

    Design: Corner/cross_cutting_complexity_layers/c_stale_facility_version_on_batch_create_returns_412
    """
    prog, fac = setup_program_and_facility()
    stale_version = fac["version"]
    create_conversion_batch(
        fac["id"], payload_class="ORDERS", attempt_epoch=0,
        source_count=500, reconciled_count=500,
        expected_facility_version=stale_version,
    )
    validate_success(api_client.get_facility(fac["id"], ANALYST), 200)
    fresh_version = get_facility(fac["id"], ANALYST)["version"]

    api_client.create_conversion_batch(
        fac["id"],
        {
            "payload_class": "BALANCES", "attempt_epoch": 0,
            "source_count": 500, "reconciled_count": 500,
            "expected_facility_version": stale_version,
        },
        conversion_headers,
    )
    validate_success(api_client.create_conversion_batch(
        fac["id"],
        {
            "payload_class": "BALANCES", "attempt_epoch": 0,
            "source_count": 500, "reconciled_count": 500,
            "expected_facility_version": fresh_version,
        },
        conversion_headers,
    ), 201)

    rows, meta = validate_paginated(
        api_client.list_facility_batches(fac["id"], conversion_headers)
    )
    assert meta["total_count"] == 2


# ===========================================================================
# c_stale_program_version_on_optimization_create_returns_412
# ===========================================================================

def test_raising_an_optimization_item_against_a_stale_program_version_is_refused(api, director_headers):
    """PRD §2.7: "Raising an optimization backlog item against a program requires
    `expected_ehr_implementation_version` carrying the client's last observed
    `version` of that `EhrImplementation`, again with `ERR_STALE_VERSION`; epoch
    advances and department-tree mutations change the program between reads, so
    the stale client view must re-read before scheduling work."
    PRD §2.7: "epoch advances and department-tree mutations change the program
    between reads, so the stale client view must re-read before scheduling work."

    Design: Corner/cross_cutting_complexity_layers/c_stale_program_version_on_optimization_create_returns_412
    """
    set_clock()
    prog = setup_program()
    fac = create_facility(prog["id"])
    dept = create_department(fac["id"])

    advanced = validate_success(api_client.advance_epoch(prog["id"], director_headers), 200)
    fresh_version = advanced["version"]
    stale_version = fresh_version - 1

    refused = api_client.create_optimization_item(
        create_optimization_item_payload(
            dept["id"], stale_version, title="Stale attempt", effort_points=5
        ),
        OPTIMIZATION,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_the_fresh_program_version_admits_the_same_optimization_item(api, director_headers):
    """PRD §2.7: "Raising an optimization backlog item against a program requires
    `expected_ehr_implementation_version` carrying the client's last observed
    `version` of that `EhrImplementation`, again with `ERR_STALE_VERSION`; epoch
    advances and department-tree mutations change the program between reads, so
    the stale client view must re-read before scheduling work."
    PRD §2.7: "Only these three operations take a version field of this kind."

    Design: Corner/cross_cutting_complexity_layers/c_stale_program_version_on_optimization_create_returns_412
    """
    set_clock()
    prog = setup_program()
    fac = create_facility(prog["id"])
    dept = create_department(fac["id"])

    advanced = validate_success(api_client.advance_epoch(prog["id"], director_headers), 200)
    fresh_version = advanced["version"]

    created = validate_success(api_client.create_optimization_item(
        create_optimization_item_payload(dept["id"], fresh_version, effort_points=5),
        OPTIMIZATION,
    ), 201)
    assert created["status"] == "NEW"


# ===========================================================================
# c_stale_staff_version_on_trainer_create_returns_412
# ===========================================================================

def test_a_second_trainer_record_built_on_a_stale_staff_version_is_refused(api, training_headers):
    """PRD §2.7: "Starting a trainer certification record against a staff member
    requires `expected_staff_version` carrying the client's last observed
    `version` of that `Staff`, with the same rejection; this matters because a
    prior certification or proficiency write legitimately changes the staffer's
    readiness".
    PRD §3.4: "A `TrainingCoordinator` starts a trainer record against a staff
    member by supplying the `application_code` the person will teach, their
    `certification_level`, the `observation_hours` they have accumulated under
    proctoring, and the staff version guard described in §2.7, which also
    increments the staff member's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/c_stale_staff_version_on_trainer_create_returns_412
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Ivan Petrov"),
        training_headers,
    ))
    stale_version = staff["version"]
    get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            stale_version, application_code="CLN", observation_hours=8
        ),
        training_headers,
    ))

    refused = api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            stale_version, application_code="CLN-ADV", certification_level="ADVANCED",
            observation_hours=12,
        ),
        training_headers,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_the_refused_stale_trainer_create_leaves_one_record_on_file(api, training_headers):
    """PRD §2.7: "when that observed version does not match the parent's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "The record begins in `PENDING_OBSERVATION`."

    Design: Corner/cross_cutting_complexity_layers/c_stale_staff_version_on_trainer_create_returns_412
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Ivan Petrov"),
        training_headers,
    ))
    stale_version = staff["version"]
    get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(stale_version),
        training_headers,
    ))
    api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            stale_version, application_code="CLN-ADV", certification_level="ADVANCED",
            observation_hours=12,
        ),
        training_headers,
    )

    rows, meta = validate_paginated(
        api_client.list_staff_trainers(staff["id"], training_headers)
    )
    assert meta["total_count"] == 1


# ===========================================================================
# c_program_version_increments_on_child_creation
# ===========================================================================

def test_a_facility_registration_is_reflected_in_the_program_read(api, director_headers):
    """PRD §3.1: "A newly created program is in `PLANNING` status, its
    `current_epoch_index` is 0, and its `readiness_posture` is `OPEN`."
    PRD §2.9: "Monetary-adjacent computed values — `readiness_score` and its
    optimistic sibling, ... — are published to two decimal places."

    Registering a facility leaves the program in `PLANNING` with an `OPEN`
    posture, and the derived score the program publishes stays inside its clamped
    range rather than becoming an unallocated placeholder.

    Design: Corner/cross_cutting_complexity_layers/c_program_version_increments_on_child_creation
    """
    prog = setup_program()
    before = get_program(prog["id"], director_headers)
    assert before["status"] == "PLANNING"
    assert before["readiness_posture"] == "OPEN"

    validate_success(api_client.create_facility(
        prog["id"],
        {
            "name": "Cascade Valley North", "facility_type": "AMBULATORY",
            "bed_count": 0, "rollout_wave": 2, "conversion_scope": "SCHEDULING_ONLY",
        },
        director_headers,
    ), 201)

    after = get_program(prog["id"], director_headers)
    assert after["status"] == "PLANNING"
    assert after["current_epoch_index"] == 0
    assert 0.00 <= after["readiness_score"] <= 100.00
    assert after["readiness_score"] == pytest.approx(before["readiness_score"], abs=0.01), (
        "a facility with no defect load changes nothing in the scoring set"
    )


def test_the_ambulatory_facility_is_the_only_child_registered(api, director_headers):
    """PRD §3.2: "an ambulatory site carries a `bed_count` of 0."
    PRD §3.2: "A facility joins the program through an `ImplementationDirector`
    who supplies its `name`, its `facility_type`, its `bed_count`, its
    `rollout_wave` and its `conversion_scope`."

    Design: Corner/cross_cutting_complexity_layers/c_program_version_increments_on_child_creation
    """
    prog = setup_program()
    created = validate_success(api_client.create_facility(
        prog["id"],
        {
            "name": "Cascade Valley North", "facility_type": "AMBULATORY",
            "bed_count": 0, "rollout_wave": 2, "conversion_scope": "SCHEDULING_ONLY",
        },
        director_headers,
    ), 201)
    assert created["bed_count"] == 0

    rows, meta = validate_paginated(api_client.list_program_facilities(prog["id"], director_headers))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == created["id"]