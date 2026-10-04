"""Device maker registration defaults and the Program lifecycle machine.

Covers registration defaults (PRD section 3.1), the DRAFT initial state, the
NDA gate, the qualification/freeze transitions with their deadline boundary,
and the terminal-state lockdown after termination (PRD sections 2.9 and 3.2).
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_device_maker,
    assert_program,
    begin_qualification,
    create_composition,
    create_program,
    create_program_with_nda,
    create_qualified_composition,
    execute_nda,
    factories,
    set_clock,
    terminate_program,
    validate_created,
    validate_error,
    get_success_data,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["program_manager_headers"]

FREEZE_DEADLINE = "2027-03-01T00:00:00Z"


def test_create_device_maker_with_defaults():
    """PRD section 3.1: "The maker's commercial standing, `standing_tier`, is
    one of `STANDARD`, `STRATEGIC`, or `PROBATION`; when omitted at
    registration it defaults to `STANDARD`." PRD section 3.1: "every maker
    carries an `ip_review_status`, which is `CLEAR` at registration".

    Design: Corner/entities/create_device_maker_with_defaults
    """
    resp = api_client.create_device_maker(
        factories.create_device_maker_payload(name="Acme Devices", region="US"),
        ADMIN,
    )
    maker = validate_created(resp)
    assert_device_maker(maker)
    assert maker["standing_tier"] == "STANDARD"
    assert maker["ip_review_status"] == "CLEAR"
    assert maker["version"] == 1


def test_program_starts_in_draft():
    """PRD section 3.2: "A new program starts in `DRAFT`." The NDA reference
    is stored only when the NDA is executed, and the design-freeze deadline is
    pinned only when qualification begins, so both read null on a fresh
    program.

    Design: Corner/state_machines/program_starts_in_draft
    """
    chain_maker_resp = api_client.create_device_maker(
        factories.create_device_maker_payload(), ADMIN
    )
    maker = validate_created(chain_maker_resp)
    resp = api_client.create_program(
        factories.create_program_payload(maker["id"], name="Eagle"), MANAGER
    )
    program = validate_created(resp)
    assert_program(program)
    assert program["status"] == "DRAFT"
    assert program["nda_reference"] is None
    assert program["design_freeze_date"] is None
    assert program["version"] == 1


def test_execute_nda_twice_returns_invalid_state():
    """PRD section 2.9: "A request whose trigger has no defined transition
    from the entity's current state is rejected with `ERR_INVALID_STATE`
    (HTTP 409)." Executing the NDA is defined only from DRAFT, so the second
    call from NDA_EXECUTED fails and the stored reference is untouched.

    Design: Corner/state_machines/execute_nda_twice_returns_invalid_state
    """
    chain = create_program_with_nda()  # NDA executed with reference NDA-001
    resp = api_client.execute_nda(
        chain.program["id"], factories.execute_nda_payload("NDA-001"), MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    program = get_success_data(api_client.get_program(chain.program["id"], MANAGER))
    assert program["nda_reference"] == "NDA-001"


def test_draft_program_blocks_composition_create_nda_required():
    """PRD section 3.2: "Until that has happened, no composition, commitment,
    or license may be created against the program — the attempt fails with
    `ERR_NDA_REQUIRED`."

    Design: Corner/validations/draft_program_blocks_composition_create_nda_required
    """
    chain_maker = validate_created(
        api_client.create_device_maker(factories.create_device_maker_payload(), ADMIN)
    )
    program = validate_created(
        api_client.create_program(factories.create_program_payload(chain_maker["id"]), MANAGER)
    )
    resp = api_client.create_composition(
        factories.create_composition_payload(program["id"]), MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_NDA_REQUIRED)


def test_terminated_program_rejects_lifecycle_actions():
    """PRD section 3.2: "from any of `DRAFT`, `NDA_EXECUTED`,
    `COMPOSITION_TUNING`, `QUALIFICATION`, or `DESIGN_FROZEN`, the program
    manager may terminate the program — optionally recording a `reason` —
    moving it to `TERMINATED`, also terminal." PRD section 2.9: "A request
    whose trigger has no defined transition from the entity's current state is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/terminated_program_rejects_lifecycle_actions
    """
    chain = create_program_with_nda()
    create_composition(chain.program)
    program = begin_qualification(chain.program, FREEZE_DEADLINE)
    terminate_program(program, reason="customer cancelled")
    resp = api_client.freeze_design(program["id"], headers=MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    program = get_success_data(api_client.get_program(program["id"], MANAGER))
    assert program["status"] == "TERMINATED"


def test_freeze_without_qualified_composition_returns_no_qualified():
    """PRD section 3.2: "only when at least one of the program's compositions
    has reached `QUALIFIED` or `LOCKED`, failing with
    `ERR_NO_QUALIFIED_COMPOSITION` otherwise" — an EXPERIMENTAL composition
    does not count.

    Design: Corner/errors/freeze_without_qualified_composition_returns_no_qualified
    """
    chain = create_program_with_nda()
    create_composition(chain.program)  # EXPERIMENTAL, never tested
    program = begin_qualification(chain.program, FREEZE_DEADLINE)
    resp = api_client.freeze_design(program["id"], headers=MANAGER)
    validate_error(resp, ApiErrorId.ERR_NO_QUALIFIED_COMPOSITION)
    program = get_success_data(api_client.get_program(program["id"], MANAGER))
    assert program["status"] == "QUALIFICATION"


def test_freeze_after_deadline_returns_design_freeze_passed():
    """PRD section 3.2: "Freezing the design is allowed only while the
    program is in `QUALIFICATION`, only while the logical clock is at or before
    `design_freeze_date` — the boundary instant itself is allowed, and a later
    attempt fails with `ERR_DESIGN_FREEZE_PASSED`". One second past the
    deadline is a later attempt.

    Design: Corner/validations/freeze_after_deadline_returns_design_freeze_passed
    """
    chain = create_program_with_nda()
    create_qualified_composition(chain.program, chain.maker)
    program = begin_qualification(chain.program, FREEZE_DEADLINE)
    set_clock("2027-03-01T00:00:01Z")
    resp = api_client.freeze_design(program["id"], headers=MANAGER)
    validate_error(resp, ApiErrorId.ERR_DESIGN_FREEZE_PASSED)
    program = get_success_data(api_client.get_program(program["id"], MANAGER))
    assert program["status"] == "QUALIFICATION"


def test_freeze_design_at_exact_deadline_succeeds():
    """PRD section 3.2: "only while the logical clock is at or before
    `design_freeze_date` — the boundary instant itself is allowed, and a later
    attempt fails with `ERR_DESIGN_FREEZE_PASSED`". With the clock reading
    exactly the pinned deadline and a QUALIFIED composition present, the freeze
    succeeds.

    Design: Difficulty/boundary_precision_check/freeze_design_at_exact_deadline_succeeds
    """
    chain = create_program_with_nda()
    create_qualified_composition(chain.program, chain.maker)
    program = begin_qualification(chain.program, FREEZE_DEADLINE)
    set_clock(FREEZE_DEADLINE)
    resp = api_client.freeze_design(program["id"], headers=MANAGER)
    program = get_success_data(api_client.get_program(program["id"], MANAGER))
    assert resp.status_code == 200
    assert program["status"] == "DESIGN_FROZEN"
