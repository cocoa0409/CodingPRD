"""Breadth coverage of the cement batch's grinding gates and fork-join qualification, and of
the certificate and silo transitions that withdraw promises already made.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_instant_equals
from test_helpers.test_users import (
    ADMIN_HEADERS,
    LAB_HEADERS,
    LOGISTICS_HEADERS,
    OPERATOR_HEADERS,
    QUALITY_HEADERS,
)


# ---------------------------------------------------------------------------
# invalid_transitions: grinding is not restartable
# ---------------------------------------------------------------------------
def test_starting_grinding_again_on_a_ground_batch_draws_no_second_charge(api):
    """The refusal is what protects the inventory: a second start-grinding would draw another
    500.00 tonnes out of the clinker silo, so it is refused and both silos are left exactly
    as the first grind left them.

    PRD: "Starting grinding on a batch that is not `PLANNED`, or finishing grinding on one
    that is not `GRINDING`, is refused with `ERR_INVALID_BATCH_STATE`."

    Design: Corner/state_machines/starting_grinding_twice_on_a_ground_batch_is_rejected
    """
    env = fx.released_clinker_environment(api)
    batch = fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )
    assert batch["status"] == "GROUND"

    validate_error(
        api.start_grinding(batch["id"], OPERATOR_HEADERS),
        ApiErrorId.ERR_INVALID_BATCH_STATE.value,
        409,
    )

    unchanged = validate_success(api.get_cement_batch(batch["id"], QUALITY_HEADERS))
    assert unchanged["status"] == "GROUND"
    assert_instant_equals(
        unchanged["grinding_started_at"], "2026-08-01T12:00:00Z", "grinding_started_at"
    )
    assert_instant_equals(unchanged["ground_at"], "2026-08-01T12:00:00Z", "ground_at")

    clinker = validate_success(api.get_silo(env["clinker_silo"]["id"], QUALITY_HEADERS))
    assert_amount(clinker["tonnes_on_hand"], 83.78, "tonnes_on_hand")
    assert_amount(clinker["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(clinker["available_tonnes"], 83.78, "available_tonnes")

    cement = validate_success(api.get_silo(env["cement_silo"]["id"], QUALITY_HEADERS))
    assert_amount(cement["tonnes_on_hand"], 574.72, "tonnes_on_hand")
    assert_amount(cement["unreleased_tonnes"], 574.72, "unreleased_tonnes")
    assert_amount(cement["available_tonnes"], 0.00, "available_tonnes")


# ---------------------------------------------------------------------------
# precondition_enforcement: the join needs both branches
# ---------------------------------------------------------------------------
def test_one_passing_branch_leaves_the_batch_ground_and_the_cement_unreleased(api):
    """A passing Blaine result moves only the fineness dimension; the cement becomes sellable
    only when the strength branch closes the join too.

    PRD: "The join fires only when the *second* of the two branches reaches `PASSED`: the
    batch then moves `GROUND → QUALIFIED`, stamps `qualified_at`, increments its `version`,
    and its cement becomes sellable — the cement silo's `unreleased_tonnes` shrinks by
    `cement_tonnes`, its `available_tonnes` is recomputed and its `version` increments."

    Design: Corner/state_machines/batch_stays_ground_until_the_second_lab_branch_passes
    """
    env = fx.released_clinker_environment(api)
    batch = fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )
    assert batch["fineness_branch_state"] == "PENDING"
    assert batch["strength_branch_state"] == "PENDING"

    fx.record_blaine(api, batch["id"], 400)

    half = validate_success(api.get_cement_batch(batch["id"], QUALITY_HEADERS))
    assert half["fineness_branch_state"] == "PASSED"
    assert half["strength_branch_state"] == "PENDING"
    assert half["status"] == "GROUND"
    assert half["qualified_at"] is None

    holding = validate_success(api.get_silo(env["cement_silo"]["id"], QUALITY_HEADERS))
    assert_amount(holding["tonnes_on_hand"], 574.72, "tonnes_on_hand")
    assert_amount(holding["unreleased_tonnes"], 574.72, "unreleased_tonnes")
    assert_amount(holding["available_tonnes"], 0.00, "available_tonnes")

    fx.record_strength(api, batch["id"], 30.0)

    qualified = validate_success(api.get_cement_batch(batch["id"], QUALITY_HEADERS))
    assert qualified["status"] == "QUALIFIED"
    assert qualified["strength_branch_state"] == "PASSED"
    assert_instant_equals(
        qualified["qualified_at"], "2026-08-01T12:00:00Z", "qualified_at"
    )

    released = validate_success(api.get_silo(env["cement_silo"]["id"], QUALITY_HEADERS))
    assert_amount(released["tonnes_on_hand"], 574.72, "tonnes_on_hand")
    assert_amount(released["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(released["available_tonnes"], 574.72, "available_tonnes")


# ---------------------------------------------------------------------------
# side_effect_execution: a failing branch short-circuits the join
# ---------------------------------------------------------------------------
def test_a_failing_strength_result_rejects_the_batch_with_its_reason(api):
    """27.9 MPa is below the TYPE_IL minimum, so the join is short-circuited straight to
    REJECTED and the reason names the branch that failed.

    PRD: "The batch moves `GROUND → REJECTED`, its `rejection_reason` is set to
    `STRENGTH_OUT_OF_SPEC` when the strength branch failed or `FINENESS_OUT_OF_SPEC` when the
    fineness branch failed, and its `version` increments."

    Design: Corner/state_machines/failing_strength_branch_rejects_the_batch_and_strands_its_cement
    """
    env = fx.released_clinker_environment(api)
    batch = fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )
    fx.record_blaine(api, batch["id"], 400)

    failing = validate_success(
        api.create_lab_test(
            f.lab_test_payload(
                "COMPRESSIVE_STRENGTH_28D", 27.9, cement_batch_id=batch["id"]
            ),
            LAB_HEADERS,
        ),
        201,
    )
    assert failing["in_spec"] is False

    rejected = validate_success(api.get_cement_batch(batch["id"], QUALITY_HEADERS))
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "STRENGTH_OUT_OF_SPEC"
    assert rejected["strength_branch_state"] == "FAILED"
    assert rejected["fineness_branch_state"] == "PASSED"
    assert rejected["qualified_at"] is None


def test_rejected_cement_stays_stranded_and_a_later_good_result_does_not_revive_it(api):
    """The tonnes stay counted as unreleased for good, so availability never recovers and a
    subsequent in-specification strength result cannot even be recorded against the batch.

    PRD: "`REJECTED` is terminal, and its inventory consequence is permanent: the batch's
    cement stays counted in the cement silo's `unreleased_tonnes` for good, so it is never
    sellable and never certifiable."

    Design: Corner/state_machines/failing_strength_branch_rejects_the_batch_and_strands_its_cement
    """
    env = fx.released_clinker_environment(api)
    batch = fx.create_ground_batch(
        api, env["plant_id"], env["clinker_silo"]["id"], env["cement_silo"]["id"]
    )
    fx.record_blaine(api, batch["id"], 400)
    fx.record_strength(api, batch["id"], 27.9)

    stranded = validate_success(api.get_silo(env["cement_silo"]["id"], QUALITY_HEADERS))
    assert_amount(stranded["tonnes_on_hand"], 574.72, "tonnes_on_hand")
    assert_amount(stranded["unreleased_tonnes"], 574.72, "unreleased_tonnes")
    assert_amount(stranded["available_tonnes"], 0.00, "available_tonnes")

    # The later good result cannot even be booked: PRD 3.7 requires "a cement batch under a
    # BLAINE or COMPRESSIVE_STRENGTH_28D test must have status exactly GROUND", and this batch
    # is terminally REJECTED, so the laboratory subject-state rung refuses the recording.
    validate_error(
        api.create_lab_test(
            f.lab_test_payload("COMPRESSIVE_STRENGTH_28D", 30.0, cement_batch_id=batch["id"]),
            LAB_HEADERS,
        ),
        ApiErrorId.ERR_LAB_SUBJECT_STATE_INVALID.value,
        409,
    )

    still_rejected = validate_success(api.get_cement_batch(batch["id"], QUALITY_HEADERS))
    assert still_rejected["status"] == "REJECTED"
    assert still_rejected["rejection_reason"] == "STRENGTH_OUT_OF_SPEC"
    assert still_rejected["qualified_at"] is None

    after = validate_success(api.get_silo(env["cement_silo"]["id"], QUALITY_HEADERS))
    assert_amount(after["unreleased_tonnes"], 574.72, "unreleased_tonnes")
    assert_amount(after["available_tonnes"], 0.00, "available_tonnes")


# ---------------------------------------------------------------------------
# idempotency: a second issue neither moves the row nor re-applies the ledger
# ---------------------------------------------------------------------------
def test_a_second_issue_on_an_issued_certificate_is_refused(api):
    """The refusal has to leave the allocation alone: a handler that were idempotent on
    status but not on the ledger would double 574.72 into 1149.44 on a batch that only ever
    made 574.72 tonnes.

    PRD: "Issuing from any state other than `DRAFT` is refused with
    `ERR_INVALID_CERTIFICATE_STATE`."

    Design: Corner/state_machines/second_issue_on_an_issued_certificate_is_rejected
    """
    env = fx.qualified_cement_environment(api, strength_value=30.0)
    customer = fx.create_customer(api)
    draft = fx.create_draft_certificate(
        api, env["batch"]["id"], customer["id"], 574.72
    )

    issued = validate_success(api.issue_mill_certificate(draft["id"], QUALITY_HEADERS))
    assert issued["status"] == "ISSUED"
    assert issued["issued_by_user_id"] == QUALITY_HEADERS["X-User-ID"]
    assert_instant_equals(issued["issued_at"], "2026-08-01T12:00:00Z", "issued_at")
    assert issued["version"] == 2

    validate_error(
        api.issue_mill_certificate(draft["id"], QUALITY_HEADERS),
        ApiErrorId.ERR_INVALID_CERTIFICATE_STATE.value,
        409,
    )

    unchanged = validate_success(api.get_mill_certificate(draft["id"], QUALITY_HEADERS))
    assert unchanged["status"] == "ISSUED"
    assert_instant_equals(unchanged["issued_at"], "2026-08-01T12:00:00Z", "issued_at")
    assert unchanged["version"] == 2

    batch = validate_success(api.get_cement_batch(env["batch"]["id"], QUALITY_HEADERS))
    assert batch["status"] == "CERTIFIED"
    assert_amount(
        batch["certified_tonnes_allocated"], 574.72, "certified_tonnes_allocated"
    )


# ---------------------------------------------------------------------------
# terminal_state_lockdown: REVOKED fires the chain exactly once
# ---------------------------------------------------------------------------
def test_a_revoked_certificate_cannot_be_revoked_a_second_time(api):
    """The second attempt stores nothing and fires no further hop: the first revocation's
    reason survives on the certificate and on the silo it blocked.

    PRD: "It requires the certificate to be `ISSUED`, else `ERR_INVALID_CERTIFICATE_STATE`,
    takes a `revoke_reason`, and moves the certificate `ISSUED → REVOKED` while stamping
    `revoked_at` from the logical clock; `revoked_at` is null while a certificate is `DRAFT`
    or `ISSUED`."

    Design: Corner/state_machines/revoked_certificate_cannot_be_revoked_a_second_time
    """
    env = fx.certificate_chain(api)
    certificate_id = env["certificate"]["id"]
    assert env["certificate"]["status"] == "ISSUED"
    assert env["certificate"]["revoked_at"] is None

    revoked = validate_success(
        api.revoke_mill_certificate(
            certificate_id, {"revoke_reason": "CUSTOMER_COMPLAINT"}, QUALITY_HEADERS
        )
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoke_reason"] == "CUSTOMER_COMPLAINT"
    assert_instant_equals(revoked["revoked_at"], "2026-08-01T12:00:00Z", "revoked_at")

    validate_error(
        api.revoke_mill_certificate(
            certificate_id, {"revoke_reason": "SECOND_ATTEMPT"}, QUALITY_HEADERS
        ),
        ApiErrorId.ERR_INVALID_CERTIFICATE_STATE.value,
        409,
    )

    unchanged = validate_success(api.get_mill_certificate(certificate_id, QUALITY_HEADERS))
    assert unchanged["status"] == "REVOKED"
    assert unchanged["revoke_reason"] == "CUSTOMER_COMPLAINT"
    assert_instant_equals(unchanged["revoked_at"], "2026-08-01T12:00:00Z", "revoked_at")

    batch = validate_success(api.get_cement_batch(env["batch"]["id"], QUALITY_HEADERS))
    assert batch["status"] == "DECERTIFIED"
    assert_amount(
        batch["certified_tonnes_allocated"], 0.00, "certified_tonnes_allocated"
    )

    silo = validate_success(api.get_silo(env["cement_silo"]["id"], QUALITY_HEADERS))
    assert silo["status"] == "BLOCKED"
    assert silo["block_reason"] == "DECERTIFIED_CEMENT"


# ---------------------------------------------------------------------------
# side_effect_execution: blocking a cement silo withdraws its promises
# ---------------------------------------------------------------------------
def test_blocking_a_cement_silo_cancels_its_open_loadout_orders(api):
    """A direct block runs the same withdrawal the revocation path runs: the reserved order
    is cancelled carrying the silo's own block reason, the reservation is released, and the
    customer's open ledger comes back to zero.

    PRD: "When a `CEMENT` silo is blocked, every loadout order on it whose `status` is
    `RESERVED` or `LOADING` moves to `CANCELLED_BY_QUALITY` with its `void_reason` set to the
    silo's `block_reason`, the silo's `reserved_tonnes` is reduced by each cancelled order's
    `tonnes`, and each affected customer's `open_reserved_tonnes` is recomputed downward."

    Design: Corner/state_machines/blocking_a_cement_silo_cancels_its_open_loadout_orders
    """
    env = fx.certificate_chain(api)
    silo_id = env["cement_silo"]["id"]

    blocked = validate_success(
        api.patch_silo(
            silo_id,
            {"status": "BLOCKED", "block_reason": "SILO_INSPECTION"},
            ADMIN_HEADERS,
        )
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["block_reason"] == "SILO_INSPECTION"

    order = validate_success(api.get_loadout_order(env["order"]["id"], LOGISTICS_HEADERS))
    assert order["status"] == "CANCELLED_BY_QUALITY"
    assert order["void_reason"] == "SILO_INSPECTION"
    assert_amount(order["loaded_tonnes"], 0.00, "loaded_tonnes")

    silo = validate_success(api.get_silo(silo_id, LOGISTICS_HEADERS))
    assert_amount(silo["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(silo["tonnes_on_hand"], 574.72, "tonnes_on_hand")
    assert_amount(silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(silo["available_tonnes"], 574.72, "available_tonnes")

    customer = validate_success(
        api.get_customer(env["customer"]["id"], LOGISTICS_HEADERS)
    )
    assert_amount(customer["open_reserved_tonnes"], 0.00, "open_reserved_tonnes")
    assert_amount(customer["lifetime_loaded_tonnes"], 0.00, "lifetime_loaded_tonnes")

    # The blocked silo takes no new promises, and the cancelled order is terminal.
    certificate = fx.data_of(
        api.get_mill_certificate(env["certificate"]["id"], LOGISTICS_HEADERS)
    )
    validate_error(
        api.create_loadout_order(
            f.loadout_order_payload(
                env["customer"]["id"],
                silo_id,
                env["certificate"]["id"],
                certificate["version"],
                window_start="2026-08-06T06:00:00Z",
                window_end="2026-08-06T08:00:00Z",
                tonnes=100.00,
            ),
            LOGISTICS_HEADERS,
        ),
        ApiErrorId.ERR_SILO_BLOCKED.value,
        409,
    )
    validate_error(
        api.start_loading(env["order"]["id"], LOGISTICS_HEADERS),
        ApiErrorId.ERR_INVALID_ORDER_STATE.value,
        409,
    )
