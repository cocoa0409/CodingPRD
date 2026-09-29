"""Breadth coverage of the two error families that every entity shares: the fifteen distinct
not-found codes a path identifier can raise, and the per-entity invalid-state codes a
transition attempted from the wrong state must raise.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_int
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    ENV_HEADERS,
    LAB_HEADERS,
    OPERATOR_HEADERS,
    QUALITY_HEADERS,
)

# The identifier the design probes with: well-formed, and owned by no row of any entity.
PROBE_ID = "11111111-1111-1111-1111-111111111111"

NOT_FOUND_PROBES = (
    ("get_plant", ApiErrorId.ERR_PLANT_NOT_FOUND),
    ("get_raw_material", ApiErrorId.ERR_RAW_MATERIAL_NOT_FOUND),
    ("get_fuel", ApiErrorId.ERR_FUEL_NOT_FOUND),
    ("get_customer", ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
    ("get_design", ApiErrorId.ERR_DESIGN_NOT_FOUND),
    ("get_pile", ApiErrorId.ERR_PILE_NOT_FOUND),
    ("get_burn_test", ApiErrorId.ERR_BURN_TEST_NOT_FOUND),
    ("get_kiln", ApiErrorId.ERR_KILN_NOT_FOUND),
    ("get_kiln_run", ApiErrorId.ERR_KILN_RUN_NOT_FOUND),
    ("get_outage", ApiErrorId.ERR_OUTAGE_NOT_FOUND),
    ("get_silo", ApiErrorId.ERR_SILO_NOT_FOUND),
    ("get_cement_batch", ApiErrorId.ERR_BATCH_NOT_FOUND),
    ("get_lab_test", ApiErrorId.ERR_LAB_TEST_NOT_FOUND),
    ("get_mill_certificate", ApiErrorId.ERR_CERTIFICATE_NOT_FOUND),
    ("get_loadout_order", ApiErrorId.ERR_ORDER_NOT_FOUND),
)


def _reference_layer(api):
    """The canonical chain — plant, catalogue, design, pile, run, silos, batch, laboratory
    tests, customer, certificate and order — plus a requested burn test and a planned October
    outage, so that every one of the fifteen collections holds at least one row while the
    probed identifier still belongs to none of them."""
    fx.reset_clock(api)
    env = fx.certificate_chain(api)
    env["burn_test"] = fx.data_of(
        api.create_burn_test(
            f.burn_test_payload(env["plant_id"], env["fuels"]["rdf"]["id"]), ENV_HEADERS
        )
    )
    env["outage"] = fx.data_of(
        api.create_outage(
            f.outage_payload(
                env["kiln"]["id"],
                "2026-10-01T00:00:00Z",
                "2026-10-03T00:00:00Z",
                scope="REFRACTORY",
            ),
            ENGINEER_HEADERS,
        )
    )
    rows, meta = validate_paginated(
        api.list_lab_tests(LAB_HEADERS, params={"cement_batch_id": env["batch"]["id"]})
    )
    assert meta["total_count"] == 2, "the qualified batch carries a Blaine and a strength row"
    env["lab_test"] = rows[0]
    return env


# ---------------------------------------------------------------------------
# errors: fifteen entities, fifteen not-found identifiers
# ---------------------------------------------------------------------------
def test_every_entity_path_answers_with_its_own_not_found_code(api):
    """One unknown identifier is offered to all fifteen single-row reads in turn, and each must
    name the entity that was missing rather than a generic not-found: an implementation with one
    shared code satisfies one probe and fails fourteen. Every real row of the same entity is
    still readable at the same moment, so nothing here is a blanket 404.

    PRD: "Path identifiers are nevertheless validated left to right: an identifier that does not
    resolve to an existing row of its expected entity yields that entity's own not-found error
    with HTTP 404 before any body field is examined."

    Design: Corner/errors/every_entity_id_path_returns_its_own_not_found
    """
    env = _reference_layer(api)
    assert len({code for _reader, code in NOT_FOUND_PROBES}) == 15, (
        "the fifteen entities must not share a code"
    )

    for reader, code in NOT_FOUND_PROBES:
        validate_error(
            getattr(api, reader)(PROBE_ID, ADMIN_HEADERS), code.value, 404
        )

    existing = (
        ("get_plant", env["plant_id"]),
        ("get_raw_material", env["materials"]["limestone"]["id"]),
        ("get_fuel", env["fuels"]["gas"]["id"]),
        ("get_customer", env["customer"]["id"]),
        ("get_design", env["design"]["id"]),
        ("get_pile", env["pile"]["id"]),
        ("get_burn_test", env["burn_test"]["id"]),
        ("get_kiln", env["kiln"]["id"]),
        ("get_kiln_run", env["run"]["id"]),
        ("get_outage", env["outage"]["id"]),
        ("get_silo", env["clinker_silo"]["id"]),
        ("get_cement_batch", env["batch"]["id"]),
        ("get_lab_test", env["lab_test"]["id"]),
        ("get_mill_certificate", env["certificate"]["id"]),
        ("get_loadout_order", env["order"]["id"]),
    )
    for reader, row_id in existing:
        found = validate_success(getattr(api, reader)(row_id, ADMIN_HEADERS))
        assert found["id"] == row_id, reader


def test_a_malformed_identifier_and_another_entitys_identifier_are_the_same_404(api):
    """Neither an id that could never have been minted nor an id that was minted for a different
    collection is allowed to escape the not-found answer: 'not-a-uuid' is not a shape error and a
    plant's id on the silo path is not a silo. The collections themselves keep answering
    normally, so the refusals are about the addressed row and nothing wider.

    PRD: "On every endpoint carrying a path identifier: the identifier resolves to an existing
    row of the expected entity, else that entity's own not-found error (404)."

    Design: Corner/errors/every_entity_id_path_returns_its_own_not_found
    """
    env = _reference_layer(api)

    for malformed in ("not-a-uuid", "0", "11111111-1111-1111-1111-11111111111"):
        validate_error(
            api.get_silo(malformed, ADMIN_HEADERS),
            ApiErrorId.ERR_SILO_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_kiln_run(malformed, ADMIN_HEADERS),
            ApiErrorId.ERR_KILN_RUN_NOT_FOUND.value,
            404,
        )

    # Real identifiers, offered on the wrong collection.
    validate_error(
        api.get_silo(env["plant_id"], ADMIN_HEADERS),
        ApiErrorId.ERR_SILO_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_plant(env["clinker_silo"]["id"], ADMIN_HEADERS),
        ApiErrorId.ERR_PLANT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_kiln_run(env["batch"]["id"], ADMIN_HEADERS),
        ApiErrorId.ERR_KILN_RUN_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_mill_certificate(env["order"]["id"], ADMIN_HEADERS),
        ApiErrorId.ERR_CERTIFICATE_NOT_FOUND.value,
        404,
    )

    rows, meta = validate_paginated(
        api.list_silos(ADMIN_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 2
    assert {row["material_kind"] for row in rows} == {"CLINKER", "CEMENT"}


def test_a_not_found_body_carries_an_identifier_a_message_and_no_row_data(api):
    """A 404 is a full error envelope, never a bare status: the `meta` holds exactly the two
    request fields, `data` holds a machine-readable code beside a human-readable sentence, and no
    fragment of the entity that was looked for leaks out of it.

    PRD: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/errors/every_entity_id_path_returns_its_own_not_found
    """
    _env = _reference_layer(api)

    for reader, code in NOT_FOUND_PROBES:
        response = getattr(api, reader)(PROBE_ID, ADMIN_HEADERS)
        error = validate_error(response, code.value, 404)
        body = response.json()

        assert body["response_type"] == "error"
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, reader
        assert body["meta"]["api_request_id"].startswith("req_"), reader

        assert error["error_id"] == code.value
        assert isinstance(error["message"], str)
        assert error["message"].strip() != "", f"{reader} returned an empty message"
        for leaked in ("id", "version", "status", "created_at"):
            assert leaked not in error, f"the {code.value} body leaks {leaked}"


# ---------------------------------------------------------------------------
# errors: rule 60 speaks with the subject entity's own voice — a design
# ---------------------------------------------------------------------------
def _approved_design(api):
    """Plant, catalogue and one design walked DRAFT -> SUBMITTED -> APPROVED."""
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    env["design"] = fx.create_approved_design(api, env["plant_id"], env["materials"])
    assert env["design"]["status"] == "APPROVED"
    return env


def test_an_approved_design_cannot_be_submitted_a_second_time(api):
    """Submission is a `DRAFT`-only act, so the design that has already been through review
    refuses it — and refuses it as a conflict on the design, not as a bad request. The identical
    call on a sibling still in `DRAFT` goes through, which is what makes the refusal about state.

    PRD: "Submission moves the design `DRAFT → SUBMITTED` and is available only while the design
    is in `DRAFT`; attempting it from any other state is refused with `ERR_INVALID_DESIGN_STATE`."

    Design: Corner/errors/each_lifecycle_rejects_a_transition_from_the_wrong_state
    """
    env = _approved_design(api)
    design_id = env["design"]["id"]
    before = validate_success(api.get_design(design_id, ENGINEER_HEADERS))

    validate_error(
        api.submit_design(design_id, ENGINEER_HEADERS),
        ApiErrorId.ERR_INVALID_DESIGN_STATE.value,
        409,
    )

    after = validate_success(api.get_design(design_id, ENGINEER_HEADERS))
    assert after == before, "a refused transition must not touch the row"
    assert after["status"] == "APPROVED"

    sibling = fx.create_draft_design(
        api, env["plant_id"], env["materials"], code="D3"
    )
    assert sibling["status"] == "DRAFT"
    submitted = validate_success(api.submit_design(sibling["id"], ENGINEER_HEADERS))
    assert submitted["status"] == "SUBMITTED"


def test_an_approved_design_refuses_a_second_approval_and_a_late_revision_request(api):
    """Two more transitions land on the same closed door and both must answer with the design's
    own conflict code. The revision request is the telling one: its own counter gate sits lower
    down the ladder, so `revision_count` must still read 0 afterwards — an implementation that
    incremented first and validated second would have banked the round.

    PRD: "On every transition endpoint: the subject's current state is a legal originating state
    for the requested transition, else that entity's own invalid-state error (409) —
    `ERR_INVALID_DESIGN_STATE`, `ERR_INVALID_PILE_STATE`, `ERR_INVALID_BURN_TEST_STATE`,
    `ERR_INVALID_RUN_STATE`, `ERR_INVALID_OUTAGE_STATE`, `ERR_INVALID_BATCH_STATE`,
    `ERR_INVALID_CERTIFICATE_STATE` or `ERR_INVALID_ORDER_STATE`."

    Design: Corner/errors/each_lifecycle_rejects_a_transition_from_the_wrong_state
    """
    env = _approved_design(api)
    design_id = env["design"]["id"]
    before = validate_success(api.get_design(design_id, QUALITY_HEADERS))
    assert_int(before["revision_count"], 0, "revision_count")

    validate_error(
        api.approve_design(design_id, QUALITY_HEADERS),
        ApiErrorId.ERR_INVALID_DESIGN_STATE.value,
        409,
    )
    validate_error(
        api.request_design_revision(
            design_id, {"revision_reason": "late second thoughts"}, QUALITY_HEADERS
        ),
        ApiErrorId.ERR_INVALID_DESIGN_STATE.value,
        409,
    )

    after = validate_success(api.get_design(design_id, QUALITY_HEADERS))
    assert after["status"] == "APPROVED"
    assert_int(after["revision_count"], 0, "revision_count")
    assert after["revision_reason"] is None
    assert after["version"] == before["version"]
    assert after["approved_by_user_id"] == before["approved_by_user_id"]


# ---------------------------------------------------------------------------
# errors: the same rule, now in the burn test's voice
# ---------------------------------------------------------------------------
def _requested_burn_test(api):
    """A trial burn for the plant's RDF, sitting in `REQUESTED` with nothing measured."""
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    env["burn_test"] = fx.data_of(
        api.create_burn_test(
            f.burn_test_payload(env["plant_id"], env["fuels"]["rdf"]["id"]), ENV_HEADERS
        )
    )
    assert env["burn_test"]["status"] == "REQUESTED"
    assert env["burn_test"]["valid_from"] is None
    assert env["burn_test"]["valid_until"] is None
    return env


def test_a_requested_trial_burn_cannot_have_its_result_recorded_before_it_starts(api):
    """The measurements are perfectly well-formed, and are refused anyway because the burn has
    not begun: the answer is the burn test's own 409, not a 400 about the body. Starting the burn
    and re-posting the identical payload then works, which is the proof.

    PRD: "Starting a trial burn that is not `REQUESTED`, or recording a result on one that is not
    `IN_PROGRESS`, is refused with `ERR_INVALID_BURN_TEST_STATE`."

    Design: Corner/errors/each_lifecycle_rejects_a_transition_from_the_wrong_state
    """
    env = _requested_burn_test(api)
    burn_test_id = env["burn_test"]["id"]
    result = f.burn_result_payload()

    validate_error(
        api.record_burn_test_result(burn_test_id, result, LAB_HEADERS),
        ApiErrorId.ERR_INVALID_BURN_TEST_STATE.value,
        409,
    )
    untouched = validate_success(api.get_burn_test(burn_test_id, ENV_HEADERS))
    assert untouched["status"] == "REQUESTED"
    assert untouched["result_recorded_by_user_id"] is None
    assert untouched["version"] == env["burn_test"]["version"]

    started = validate_success(api.start_burn_test(burn_test_id, LAB_HEADERS))
    assert started["status"] == "IN_PROGRESS"

    recorded = validate_success(
        api.record_burn_test_result(burn_test_id, result, LAB_HEADERS)
    )
    assert recorded["status"] == "RESULT_RECORDED"
    assert recorded["stack_compliant"] is True

    # And now the reverse: starting is a REQUESTED-only act.
    validate_error(
        api.start_burn_test(burn_test_id, LAB_HEADERS),
        ApiErrorId.ERR_INVALID_BURN_TEST_STATE.value,
        409,
    )


def test_a_trial_burn_cannot_be_adjudicated_before_its_result_is_on_file(api):
    """Adjudication is refused from `REQUESTED` and again from `IN_PROGRESS`, and both refusals
    are the state conflict rather than a complaint about the decision: rule 60 sits above the
    substantive checks on `stack_compliant` and on the authorized ceiling, so neither can be
    reached here. Nothing is minted by the refusals — no permit dates appear.

    PRD: "Adjudication is the `EnvironmentalOfficer`'s exclusive act and is available only from
    `RESULT_RECORDED`."

    Design: Corner/errors/each_lifecycle_rejects_a_transition_from_the_wrong_state
    """
    env = _requested_burn_test(api)
    burn_test_id = env["burn_test"]["id"]
    verdict = f.adjudication_payload("AUTHORIZED", 25.00)

    validate_error(
        api.adjudicate_burn_test(burn_test_id, verdict, ENV_HEADERS),
        ApiErrorId.ERR_INVALID_BURN_TEST_STATE.value,
        409,
    )

    started = validate_success(api.start_burn_test(burn_test_id, LAB_HEADERS))
    assert started["status"] == "IN_PROGRESS"
    validate_error(
        api.adjudicate_burn_test(burn_test_id, verdict, ENV_HEADERS),
        ApiErrorId.ERR_INVALID_BURN_TEST_STATE.value,
        409,
    )

    still_open = validate_success(api.get_burn_test(burn_test_id, ENV_HEADERS))
    assert still_open["status"] == "IN_PROGRESS"
    assert still_open["valid_from"] is None
    assert still_open["valid_until"] is None

    validate_success(
        api.record_burn_test_result(burn_test_id, f.burn_result_payload(), LAB_HEADERS)
    )
    authorized = validate_success(
        api.adjudicate_burn_test(burn_test_id, verdict, ENV_HEADERS)
    )
    assert authorized["status"] == "AUTHORIZED"
    assert_amount(
        authorized["authorized_max_tsr_pct"], 25.00, "authorized_max_tsr_pct"
    )


# ---------------------------------------------------------------------------
# errors: and once more in the outage's voice
# ---------------------------------------------------------------------------
def test_a_planned_outage_refuses_both_starting_and_completion(api):
    """A planned outage has to be approved before anything else can happen to it, so starting it
    and completing it are both conflicts on the outage — and the two stamps stay null, which is
    what shows nothing partial was applied. Approval is accepted from exactly this state, and
    completion is still refused from `APPROVED` because only an `IN_PROGRESS` outage may finish.

    PRD: "`COMPLETED` is the outage's terminal state; approving, starting or completing an outage
    from any state other than the one named above is refused with `ERR_INVALID_OUTAGE_STATE`."

    Design: Corner/errors/each_lifecycle_rejects_a_transition_from_the_wrong_state
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    outage = fx.data_of(
        api.create_outage(
            f.outage_payload(
                env["kiln"]["id"],
                "2026-10-01T00:00:00Z",
                "2026-10-03T00:00:00Z",
                scope="REFRACTORY",
            ),
            ENGINEER_HEADERS,
        )
    )
    assert outage["status"] == "PLANNED"

    validate_error(
        api.complete_outage(
            outage["id"], {"refractory_replaced": True}, ENGINEER_HEADERS
        ),
        ApiErrorId.ERR_INVALID_OUTAGE_STATE.value,
        409,
    )
    validate_error(
        api.start_outage(outage["id"], ENGINEER_HEADERS),
        ApiErrorId.ERR_INVALID_OUTAGE_STATE.value,
        409,
    )

    unmoved = validate_success(api.get_outage(outage["id"], ENGINEER_HEADERS))
    assert unmoved["status"] == "PLANNED"
    assert unmoved["started_at"] is None
    assert unmoved["completed_at"] is None
    assert unmoved["refractory_replaced"] is False
    assert unmoved["version"] == outage["version"]

    kiln = validate_success(api.get_kiln(env["kiln"]["id"], OPERATOR_HEADERS))
    assert kiln["availability_state"] == "AVAILABLE"

    approved = validate_success(api.approve_outage(outage["id"], ADMIN_HEADERS))
    assert approved["status"] == "APPROVED"

    validate_error(
        api.complete_outage(
            outage["id"], {"refractory_replaced": True}, ENGINEER_HEADERS
        ),
        ApiErrorId.ERR_INVALID_OUTAGE_STATE.value,
        409,
    )


# ---------------------------------------------------------------------------
# errors: a subject of the right kind can still be in the wrong state
# ---------------------------------------------------------------------------
def test_a_scheduled_run_is_not_a_testable_subject_until_it_has_been_lit(api):
    """The kind gate is satisfied — a free-lime test does name a kiln run — and the request is
    still refused, because a run that has never been fired has no clinker to sample. That makes
    this a 409 on the subject's state and not the 422 the kind gate would have raised, and no
    laboratory row survives the attempt. The identical call against the completed run is accepted.

    PRD: "The subject must also be in a testable condition: a kiln run under a `FREE_LIME` test
    must have `process_state` of `BURNING` or `COMPLETED`, and a cement batch under a `BLAINE` or
    `COMPRESSIVE_STRENGTH_28D` test must have `status` exactly `GROUND`; otherwise the request is
    refused with `ERR_LAB_SUBJECT_STATE_INVALID`."

    Design: Corner/errors/a_lab_test_on_an_untestable_subject_is_rejected
    """
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)
    scheduled = fx.create_scheduled_run(
        api,
        env["kiln"]["id"],
        env["pile"]["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T12:00:00Z",
    )
    assert scheduled["process_state"] == "SCHEDULED"

    validate_error(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.20, kiln_run_id=scheduled["id"]),
            LAB_HEADERS,
        ),
        ApiErrorId.ERR_LAB_SUBJECT_STATE_INVALID.value,
        409,
    )

    _rows, meta = validate_paginated(
        api.list_lab_tests(LAB_HEADERS, params={"kiln_run_id": scheduled["id"]})
    )
    assert meta["total_count"] == 0

    unmoved = validate_success(api.get_kiln_run(scheduled["id"], OPERATOR_HEADERS))
    assert unmoved["process_state"] == "SCHEDULED"
    assert unmoved["quality_state"] == "PENDING_LAB"

    accepted = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.20, kiln_run_id=env["run"]["id"]),
            LAB_HEADERS,
        ),
        201,
    )
    assert accepted["test_type"] == "FREE_LIME"
    assert accepted["kiln_run_id"] == env["run"]["id"]


def test_a_planned_batch_refuses_both_of_its_cement_measurements(api):
    """Neither of the two cement measurements can be taken off a batch whose cement has not been
    milled yet, and both refusals carry the same code — `GROUND` is the only testable batch
    status. The two qualification branches must therefore still read `PENDING` afterwards, and
    grinding the very same batch turns the refused Blaine reading into an accepted one.

    PRD: "On recording a laboratory test, else `ERR_LAB_SUBJECT_STATE_INVALID` (409)."

    Design: Corner/errors/a_lab_test_on_an_untestable_subject_is_rejected
    """
    fx.reset_clock(api)
    env = fx.released_clinker_environment(api)
    batch = fx.create_planned_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )
    assert batch["status"] == "PLANNED"

    for test_type, value in (("BLAINE", 400), ("COMPRESSIVE_STRENGTH_28D", 30.0)):
        validate_error(
            api.create_lab_test(
                f.lab_test_payload(test_type, value, cement_batch_id=batch["id"]),
                LAB_HEADERS,
            ),
            ApiErrorId.ERR_LAB_SUBJECT_STATE_INVALID.value,
            409,
        )

    _rows, meta = validate_paginated(
        api.list_lab_tests(LAB_HEADERS, params={"cement_batch_id": batch["id"]})
    )
    assert meta["total_count"] == 0

    unmoved = validate_success(api.get_cement_batch(batch["id"], ENGINEER_HEADERS))
    assert unmoved["status"] == "PLANNED"
    assert unmoved["strength_branch_state"] == "PENDING"
    assert unmoved["fineness_branch_state"] == "PENDING"
    assert unmoved["version"] == batch["version"]

    validate_success(api.start_grinding(batch["id"], OPERATOR_HEADERS))
    ground = validate_success(api.finish_grinding(batch["id"], OPERATOR_HEADERS))
    assert ground["status"] == "GROUND"

    accepted = validate_success(
        api.create_lab_test(
            f.lab_test_payload("BLAINE", 400, cement_batch_id=batch["id"]),
            LAB_HEADERS,
        ),
        201,
    )
    assert accepted["cement_batch_id"] == batch["id"]
    assert accepted["in_spec"] is True
