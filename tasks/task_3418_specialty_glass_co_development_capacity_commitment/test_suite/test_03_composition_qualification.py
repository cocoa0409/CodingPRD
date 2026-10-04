"""Compositions and qualification cycles.

Covers composition request-shape rules and per-program code uniqueness (PRD
section 3.3), the LOCKED immutability rule, the resubmission attempt cap, the
cyclic qualification machine with its one-time composition promotions, and the
retire cascade over an empty target set.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    begin_testing,
    create_composition,
    create_program,
    create_program_with_nda,
    create_qual_cycle,
    create_device_maker,
    create_locked_composition,
    execute_nda,
    factories,
    record_qual_result,
    resubmit_qual_cycle,
    validate_created,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
)

MANAGER = TEST_USERS["program_manager_headers"]


def test_create_composition_missing_required_field_returns_invalid_request():
    """PRD section 2.8: "Required fields are present, types and enum members
    are valid, `complexity_multiplier` lies within the inclusive range 1.0 to
    2.5 ... any violation yields `ERR_INVALID_REQUEST`" — a composition body
    without `composition_code` fails request-shape validation.

    Design: Corner/entities/create_composition_missing_required_field_returns_invalid_request
    """
    chain = create_program_with_nda()
    resp = api_client.create_composition(
        {"program_id": chain.program["id"], "complexity_multiplier": 1.0}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    data, meta = validate_paginated(
        api_client.list_compositions(MANAGER, {"program_id": chain.program["id"]})
    )
    assert data == []
    assert meta["total_count"] == 0


def test_composition_multiplier_out_of_range_returns_invalid_request():
    """PRD section 3.3: "a `complexity_multiplier` expressing melting
    difficulty — a number from 1.0 to 2.5 inclusive; anything outside that
    range fails with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/composition_multiplier_out_of_range_returns_invalid_request
    """
    chain = create_program_with_nda()
    resp = api_client.create_composition(
        factories.create_composition_payload(
            chain.program["id"], complexity_multiplier=2.6
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_duplicate_composition_code_returns_conflict():
    """PRD section 3.3: "The `composition_code` must be unique within its
    program; a duplicate is rejected with `ERR_COMPOSITION_CODE_CONFLICT`." The
    uniqueness scope is the program, so the same code under another program is
    accepted.

    Design: Corner/errors/duplicate_composition_code_returns_conflict
    """
    maker = create_device_maker()
    program_one = execute_nda(create_program(maker, name="Eagle"))
    create_composition(program_one, composition_code="GX-100")
    program_two = execute_nda(
        create_program(maker, name="Falcon", primary_market="AUTOMOTIVE")
    )
    resp = api_client.create_composition(
        factories.create_composition_payload(
            program_one["id"], composition_code="GX-100", complexity_multiplier=1.2
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_COMPOSITION_CODE_CONFLICT)
    other = validate_created(
        api_client.create_composition(
            factories.create_composition_payload(
                program_two["id"], composition_code="GX-100", complexity_multiplier=1.2
            ),
            MANAGER,
        )
    )
    assert other["program_id"] == program_two["id"]


def test_locked_composition_cannot_be_retired():
    """PRD section 3.3: "A `LOCKED` composition can never be retired — the
    attempt fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/locked_composition_cannot_be_retired
    """
    chain = create_program_with_nda()
    locked = create_locked_composition(chain.program, chain.maker)
    resp = api_client.retire_composition(locked.composition["id"], headers=MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    composition = get_success_data(
        api_client.get_composition(locked.composition["id"], MANAGER)
    )
    assert composition["status"] == "LOCKED"


def test_qual_cycle_third_resubmit_returns_max_attempts():
    """PRD section 3.3: "A `FAILED` cycle may be resubmitted by the program
    manager, returning it from `FAILED` to `SUBMITTED` and incrementing
    `attempt_number` by 1 — but only while `attempt_number` is below 3
    (CONST.MAX_QUAL_ATTEMPTS); attempting a resubmit at the cap fails with
    `ERR_MAX_QUAL_ATTEMPTS`."

    Design: Corner/state_machines/qual_cycle_third_resubmit_returns_max_attempts
    """
    chain = create_program_with_nda()
    composition = create_composition(chain.program)
    cycle = create_qual_cycle(composition)
    for _ in range(2):
        cycle = begin_testing(cycle, chain.maker["id"])
        cycle = record_qual_result(cycle, chain.maker["id"], "FAILED")
        cycle = resubmit_qual_cycle(cycle)
    cycle = begin_testing(cycle, chain.maker["id"])
    cycle = record_qual_result(cycle, chain.maker["id"], "FAILED")
    resp = api_client.resubmit_qual_cycle(cycle["id"], headers=MANAGER)
    validate_error(resp, ApiErrorId.ERR_MAX_QUAL_ATTEMPTS)
    cycle = get_success_data(api_client.get_qual_cycle(cycle["id"], MANAGER))
    assert cycle["attempt_number"] == 3
    assert cycle["status"] == "FAILED"


def test_retire_composition_with_no_campaigns_is_clean_noop():
    """PRD section 3.3: "The program manager may retire a composition from
    `EXPERIMENTAL`, `TUNED`, or `QUALIFIED`, moving it to `RETIRED`, terminal."
    With no campaign referencing the composition, the cascade target set is
    empty and the retire succeeds with no other mutation.

    Design: Corner/cross_cutting_layers/retire_composition_with_no_campaigns_is_clean_noop
    """
    chain = create_program_with_nda()
    composition = create_composition(chain.program)
    resp = api_client.retire_composition(composition["id"], headers=MANAGER)
    retired = validate_success(resp)
    assert retired["status"] == "RETIRED"


def test_qual_cycle_resubmission_loop():
    """PRD section 3.3: "beginning testing ... moves the cycle from
    `SUBMITTED` to `IN_TESTING`, and if the referenced composition is still
    `EXPERIMENTAL` this first contact with the test bench tunes it, moving the
    composition from `EXPERIMENTAL` to `TUNED`." PRD section 3.3: "A `PASSED`
    outcome on a `TUNED` composition qualifies it, moving the composition from
    `TUNED` to `QUALIFIED`." The FAILED -> SUBMITTED loop edge increments the
    attempt counter, and the second pass through the loop completes the cycle.

    Design: Difficulty/non_linear_state_machine/qual_cycle_resubmission_loop
    """
    chain = create_program_with_nda()
    composition = create_composition(chain.program)
    cycle = create_qual_cycle(composition)

    cycle = begin_testing(cycle, chain.maker["id"])
    assert cycle["status"] == "IN_TESTING"
    composition = get_success_data(api_client.get_composition(composition["id"], MANAGER))
    assert composition["status"] == "TUNED"

    cycle = record_qual_result(cycle, chain.maker["id"], "FAILED")
    assert cycle["status"] == "FAILED"

    cycle = resubmit_qual_cycle(cycle)
    assert cycle["status"] == "SUBMITTED"
    assert cycle["attempt_number"] == 2

    cycle = begin_testing(cycle, chain.maker["id"])
    cycle = record_qual_result(cycle, chain.maker["id"], "PASSED")
    assert cycle["status"] == "PASSED"
    composition = get_success_data(api_client.get_composition(composition["id"], MANAGER))
    assert composition["status"] == "QUALIFIED"
