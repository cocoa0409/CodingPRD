"""Integration lifecycle gating, residency lock, OCC, thresholds, injection guards
(PRD §2.6, §3.1, §3.3, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_integration,
    create_assignment,
    create_institution,
    create_instructor,
    create_lms_integration_payload,
    create_source,
    get_assignment_version,
    make_instructor_headers,
    setup_basic_scenario,
    submit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INST_ADMIN = TEST_USERS["institutional_admin_headers"]


def test_assignment_creation_requires_integration_active(api):
    """PRD §3.1: "Only an `ACTIVE` integration may receive new assignments —
    creating an assignment under a `PENDING` or `SUSPENDED` integration is
    rejected with `ERR_INTEGRATION_NOT_ACTIVE` (HTTP 409)." PRD §3.1: "moving an
    integration from `ACTIVE` to `SUSPENDED` conditionally cascades downward,
    flipping every assignment of that integration whose `accepting_state` is
    `OPEN` to `CLOSED`"

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_requires_integration_active
    """
    inst = create_institution(name="XDep U", residency_region="US")
    resp = api.create_lms_integration(
        inst["id"], create_lms_integration_payload(provider="BLACKBOARD", external_key="k13"), ADMIN
    )
    integ = validate_success(resp, expected_status=201)
    instr = create_instructor(inst["id"])

    pending = api.create_assignment(
        integ["id"],
        {"instructor_id": instr["id"], "title": "Too Early", "due_at": "2027-01-01T00:00:00Z"},
        make_instructor_headers(instr["id"]),
    )
    validate_error(pending, ApiErrorId.ERR_INTEGRATION_NOT_ACTIVE, expected_status=409)

    validate_success(api.activate_integration(integ["id"], ADMIN))
    asg = create_assignment(integ["id"], instr["id"], title="Now Fine")

    validate_success(api.suspend_integration(integ["id"], ADMIN))
    suspended = api.create_assignment(
        integ["id"],
        {"instructor_id": instr["id"], "title": "Too Late", "due_at": "2027-01-01T00:00:00Z"},
        make_instructor_headers(instr["id"]),
    )
    validate_error(suspended, ApiErrorId.ERR_INTEGRATION_NOT_ACTIVE, expected_status=409)

    fetched = validate_success(api.get_assignment(asg["id"], make_instructor_headers(instr["id"])))
    assert fetched["accepting_state"] == "CLOSED", "suspend cascades OPEN assignments to CLOSED"


def test_assignment_creation_after_reactivation_succeeds(api):
    """PRD §3.1: "Activation moves an integration from `PENDING` to `ACTIVE`,
    and the same activation also revives a `SUSPENDED` integration back to
    `ACTIVE`." PRD §3.1: "Only an `ACTIVE` integration may receive new
    assignments"

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_requires_integration_active
    """
    inst = create_institution(name="XDep2 U", residency_region="US")
    integ = validate_success(
        api.create_lms_integration(
            inst["id"], create_lms_integration_payload(provider="MOODLE", external_key="k13b"), ADMIN
        ),
        expected_status=201,
    )
    instr = create_instructor(inst["id"])
    validate_success(api.activate_integration(integ["id"], ADMIN))
    validate_success(api.suspend_integration(integ["id"], ADMIN))
    revived = validate_success(api.activate_integration(integ["id"], ADMIN))
    assert revived["status"] == "ACTIVE", "SUSPENDED -> ACTIVE reactivation"
    asg = create_assignment(integ["id"], instr["id"], title="Revived")
    assert asg["accepting_state"] == "OPEN"


def test_residency_region_patch_locked_rejected(api):
    """PRD §3.1: "Once `data_residency_locked` is true, any edit attempting to
    change `residency_region` is rejected with `ERR_RESIDENCY_LOCKED`
    (HTTP 409)."

    Design: Corner/validations/residency_region_patch_locked_rejected
    """
    inst = create_institution(name="Lock U", residency_region="US", data_residency_locked=True)
    resp = api.patch_institution(
        inst["id"],
        {"expected_institution_version": inst["version"], "residency_region": "EU"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_RESIDENCY_LOCKED, expected_status=409)
    fetched = validate_success(api.get_institution(inst["id"], ADMIN))
    assert fetched["residency_region"] == "US"
    assert fetched["version"] == inst["version"], "a rejected PATCH leaves the version unchanged"


def test_threshold_out_of_range_rejected(api):
    """PRD §3.3: "`small_match_threshold_words` (default 8, and when provided
    must lie within 1 to 32 inclusive — anything outside that range is rejected
    with `ERR_THRESHOLD_OUT_OF_RANGE`, HTTP 422)"

    Design: Corner/validations/threshold_out_of_range_rejected
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US", consent=False)
    asg_v = asg["version"]
    bad = api.patch_assignment(
        asg["id"],
        {"expected_assignment_version": asg_v, "small_match_threshold_words": 33},
        make_instructor_headers(instr["id"]),
    )
    validate_error(bad, ApiErrorId.ERR_THRESHOLD_OUT_OF_RANGE, expected_status=422)
    fetched = validate_success(api.get_assignment(asg["id"], make_instructor_headers(instr["id"])))
    assert fetched["version"] == asg_v, "version unchanged after rejection"

    ok = validate_success(
        api.patch_assignment(
            asg["id"],
            {"expected_assignment_version": asg_v, "small_match_threshold_words": 32},
            make_instructor_headers(instr["id"]),
        )
    )
    assert ok["small_match_threshold_words"] == 32, "the upper boundary is accepted"


def test_assignment_patch_stale_version_occ(api):
    """PRD §2.6: "Updating an assignment's settings (an `Instructor`-only write)
    requires `expected_assignment_version` in the payload, carrying the
    `Assignment.version` the client last observed. A mismatch with the
    assignment's current `version` is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/validations/assignment_patch_stale_version_occ
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US", consent=False)
    first = validate_success(
        api.patch_assignment(
            asg["id"],
            {"expected_assignment_version": asg["version"], "exclude_quotes": True},
            make_instructor_headers(instr["id"]),
        )
    )
    assert first["version"] == asg["version"] + 1

    stale = api.patch_assignment(
        asg["id"],
        {"expected_assignment_version": asg["version"], "exclude_bibliography": True},
        make_instructor_headers(instr["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    ok = validate_success(
        api.patch_assignment(
            asg["id"],
            {"expected_assignment_version": first["version"], "exclude_bibliography": True},
            make_instructor_headers(instr["id"]),
        )
    )
    assert ok["exclude_bibliography"] is True


def test_cross_region_comparison_rejected(api):
    """PRD §3.5: "the injected fragment is rejected with
    `ERR_CROSS_REGION_COMPARISON` (HTTP 422) unless either the source's `region`
    equals the residency region of the submission's institution, or the source
    is a `STUDENT_REPOSITORY` source backed by a `STORED` deposit with
    `GLOBAL_SHARED` scope and both institutions involved have
    `cross_institution_comparison_enabled` set"

    Design: Corner/validations/cross_region_comparison_rejected
    """
    inst, integ, instr, student, asg = setup_basic_scenario("EU")
    sub = submit(asg["id"], student["id"], "cross region body")
    src_us = create_source(inst["id"], source_type="INTERNET", uri="https://src.example/us1",
                           region="US")
    resp = api.inject_match(
        {
            "submission_id": sub["id"],
            "source_document_id": src_us["id"],
            "matched_word_count": 3,
            "match_category": "DIRECT_QUOTE",
            "offset_start": 0,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_REGION_COMPARISON, expected_status=422)
    frags, _ = validate_paginated(api.list_match_fragments_of_submission(sub["id"], INST_ADMIN))
    assert frags == [], "nothing persisted on a rejected injection"


def test_inject_against_retracted_source_rejected(api):
    """PRD §3.5: "the source must still be `ACTIVE` (a `RETRACTED` source yields
    `ERR_SOURCE_RETRACTED`, HTTP 409)"

    Design: Corner/validations/inject_against_retracted_source_rejected
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub = submit(asg["id"], student["id"], "retract source body")
    src = create_source(inst["id"], source_type="PUBLICATION", uri="https://src.example/ret")
    validate_success(api.retract_source(src["id"], ADMIN))

    resp = api.inject_match(
        {
            "submission_id": sub["id"],
            "source_document_id": src["id"],
            "matched_word_count": 4,
            "match_category": "PARAPHRASE",
            "offset_start": 0,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_SOURCE_RETRACTED, expected_status=409)
