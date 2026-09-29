"""Depth scenarios over the non-linear state machines and the transitive cascades:
the kiln run's two independent dimensions, the capped design revision loop, the
four-hop revocation chain and the three-hop re-quarantine withdrawal.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount
from test_helpers.test_users import (
    ENGINEER_HEADERS,
    LAB_HEADERS,
    LOGISTICS_HEADERS,
    OPERATOR_HEADERS,
    QUALITY_HEADERS,
)


# ---------------------------------------------------------------------------
# non_linear_state_machine
# ---------------------------------------------------------------------------
def test_kiln_run_quality_cycles_while_the_process_dimension_stays_completed(api):
    """A completed run walks PENDING_LAB -> QUARANTINED -> PENDING_LAB -> RELEASED ->
    QUARANTINED purely on laboratory readings of 1.62, 1.40 and 1.70 against a 1.50
    ceiling, while process_state stays COMPLETED for every hop and the clinker silo's
    unreleased tonnage follows the quality dimension up and down.

    PRD: "The pair forms a retest loop: quality can oscillate `PENDING_LAB →
    QUARANTINED → PENDING_LAB` as many times as the laboratory reports, while the
    process dimension stays exactly where it was."

    Design: Difficulty/non_linear_state_machine/kiln_run_quality_dimension_cycles_while_process_dimension_stays_completed
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])
    run = fx.create_completed_run(
        api,
        env["kiln"]["id"],
        pile["id"],
        env["clinker_silo"]["id"],
        env["fuels"]["gas"]["id"],
        45.00,
    )
    run_id = run["id"]
    assert run["process_state"] == "COMPLETED"
    assert run["quality_state"] == "PENDING_LAB"
    assert_amount(run["clinker_tonnes"], 583.78, "clinker_tonnes")

    # Reading one: out of specification, so the quality dimension falls.
    failing = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.62, kiln_run_id=run_id), LAB_HEADERS
        ),
        201,
    )
    assert failing["in_spec"] is False
    assert_amount(failing["spec_max"], 1.50, "spec_max")

    quarantined = validate_success(api.get_kiln_run(run_id, QUALITY_HEADERS))
    assert quarantined["quality_state"] == "QUARANTINED"
    assert quarantined["process_state"] == "COMPLETED"
    assert_amount(quarantined["free_lime_pct"], 1.62, "free_lime_pct")

    # Reading two: back in specification, so the cycle closes.
    passing = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.40, kiln_run_id=run_id), LAB_HEADERS
        ),
        201,
    )
    assert passing["in_spec"] is True

    retested = validate_success(api.get_kiln_run(run_id, QUALITY_HEADERS))
    assert retested["quality_state"] == "PENDING_LAB"
    assert retested["process_state"] == "COMPLETED"

    released = validate_success(api.release_clinker(run_id, QUALITY_HEADERS))
    assert released["quality_state"] == "RELEASED"
    assert released["process_state"] == "COMPLETED"

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], QUALITY_HEADERS))
    assert_amount(silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(silo["available_tonnes"], 583.78, "available_tonnes")

    # Reading three: a failure on an already released run re-quarantines it.
    requarantine = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.70, kiln_run_id=run_id), LAB_HEADERS
        ),
        201,
    )
    assert requarantine["in_spec"] is False

    withdrawn = validate_success(api.get_kiln_run(run_id, QUALITY_HEADERS))
    assert withdrawn["quality_state"] == "QUARANTINED"
    assert withdrawn["process_state"] == "COMPLETED"
    assert_amount(withdrawn["free_lime_pct"], 1.70, "free_lime_pct")

    after = validate_success(api.get_silo(env["clinker_silo"]["id"], QUALITY_HEADERS))
    assert_amount(after["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(after["unreleased_tonnes"], 583.78, "unreleased_tonnes")
    assert_amount(after["available_tonnes"], 0.00, "available_tonnes")

    # The process dimension never re-opens, whatever quality does.
    validate_error(
        api.light_kiln_run(run_id, OPERATOR_HEADERS),
        ApiErrorId.ERR_INVALID_RUN_STATE.value,
    )


def test_design_revision_cycle_is_capped_at_three_rounds(api):
    """Three full DRAFT -> SUBMITTED -> REVISION_REQUESTED -> DRAFT loops are accepted and
    leave revision_count at 3; the fourth revision request is refused with
    ERR_REVISION_LIMIT_EXCEEDED, the design stays SUBMITTED, and approval then succeeds.

    PRD: "A design is allowed three completed revision rounds: the request is permitted
    only while `revision_count` is strictly less than 3, so the fourth request on the same
    design is refused with `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/design_revision_cycle_is_capped_at_three_rounds_then_rejected
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    materials = fx.create_raw_materials(api)
    design = fx.create_draft_design(api, plant["id"], materials, code="D3")
    design_id = design["id"]
    assert design["status"] == "DRAFT"
    assert design["revision_count"] == 0

    amendments = (
        ({"target_sm": 2.40}, "raise the silica modulus"),
        ({"target_am": 2.45}, "check the alumina modulus"),
        ({"pile_lsf_tolerance": 2.00}, "tighten the pile tolerance"),
    )
    for round_index, (patch, reason) in enumerate(amendments, start=1):
        submitted = validate_success(api.submit_design(design_id, ENGINEER_HEADERS))
        assert submitted["status"] == "SUBMITTED"

        requested = validate_success(
            api.request_design_revision(
                design_id, {"revision_reason": reason}, QUALITY_HEADERS
            )
        )
        assert requested["status"] == "REVISION_REQUESTED"
        assert requested["revision_count"] == round_index
        assert requested["revision_reason"] == reason

        amended = validate_success(api.patch_design(design_id, patch, ENGINEER_HEADERS))
        assert amended["status"] == "DRAFT"
        assert amended["revision_count"] == round_index

    resubmitted = validate_success(api.submit_design(design_id, ENGINEER_HEADERS))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 3

    validate_error(
        api.request_design_revision(
            design_id, {"revision_reason": "one more look"}, QUALITY_HEADERS
        ),
        ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value,
        409,
    )

    unmoved = validate_success(api.get_design(design_id, QUALITY_HEADERS))
    assert unmoved["status"] == "SUBMITTED"
    assert unmoved["revision_count"] == 3

    approved = validate_success(api.approve_design(design_id, QUALITY_HEADERS))
    assert approved["status"] == "APPROVED"
    assert approved["revision_count"] == 3


# ---------------------------------------------------------------------------
# transitive_cascade
# ---------------------------------------------------------------------------
def test_certificate_revocation_cascades_four_hops_to_the_customer_ledger(api):
    """Revoking the issued certificate decertifies the batch, blocks its cement silo,
    cancels the reserved loadout order with the silo's block reason, and only then walks
    the customer's ledger back down to 0.00; the physical stock is untouched throughout.

    PRD: "The chain therefore runs from certificate to batch to silo to order to customer,
    and every row it touches has its `version` incremented."

    Design: Difficulty/transitive_cascade/certificate_revocation_cascades_four_hops_to_the_customer_ledger
    """
    env = fx.certificate_chain(api)
    batch_id = env["batch"]["id"]
    silo_id = env["cement_silo"]["id"]
    order_id = env["order"]["id"]
    customer_id = env["customer"]["id"]

    before_batch = validate_success(api.get_cement_batch(batch_id, QUALITY_HEADERS))
    assert before_batch["status"] == "CERTIFIED"
    assert_amount(
        before_batch["certified_tonnes_allocated"], 574.72, "certified_tonnes_allocated"
    )

    before_silo = validate_success(api.get_silo(silo_id, QUALITY_HEADERS))
    assert before_silo["status"] == "OPEN"
    assert_amount(before_silo["tonnes_on_hand"], 574.72, "tonnes_on_hand")
    assert_amount(before_silo["reserved_tonnes"], 120.00, "reserved_tonnes")
    assert_amount(before_silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(before_silo["available_tonnes"], 454.72, "available_tonnes")

    before_order = validate_success(api.get_loadout_order(order_id, LOGISTICS_HEADERS))
    assert before_order["status"] == "RESERVED"

    before_customer = validate_success(api.get_customer(customer_id, LOGISTICS_HEADERS))
    assert_amount(
        before_customer["open_reserved_tonnes"], 120.00, "open_reserved_tonnes"
    )

    revoked = validate_success(
        api.revoke_mill_certificate(
            env["certificate"]["id"],
            {"revoke_reason": "customer complaint on 28-day strength"},
            QUALITY_HEADERS,
        )
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoke_reason"] == "customer complaint on 28-day strength"

    # Hop one: the batch.
    after_batch = validate_success(api.get_cement_batch(batch_id, QUALITY_HEADERS))
    assert after_batch["status"] == "DECERTIFIED"
    assert_amount(
        after_batch["certified_tonnes_allocated"], 0.00, "certified_tonnes_allocated"
    )

    # Hops two and three: the silo and the order it was carrying.
    after_silo = validate_success(api.get_silo(silo_id, QUALITY_HEADERS))
    assert after_silo["status"] == "BLOCKED"
    assert after_silo["block_reason"] == "DECERTIFIED_CEMENT"
    assert_amount(after_silo["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(after_silo["tonnes_on_hand"], 574.72, "tonnes_on_hand")

    after_order = validate_success(api.get_loadout_order(order_id, LOGISTICS_HEADERS))
    assert after_order["status"] == "CANCELLED_BY_QUALITY"
    assert after_order["void_reason"] == "DECERTIFIED_CEMENT"
    assert_amount(after_order["loaded_tonnes"], 0.00, "loaded_tonnes")

    # Hop four: the customer ledger.
    after_customer = validate_success(api.get_customer(customer_id, LOGISTICS_HEADERS))
    assert_amount(after_customer["open_reserved_tonnes"], 0.00, "open_reserved_tonnes")

    # The cancelled order is terminal, so its own state gate answers first.
    validate_error(
        api.start_loading(order_id, LOGISTICS_HEADERS),
        ApiErrorId.ERR_INVALID_ORDER_STATE.value,
    )


def test_requarantine_withdrawal_cascades_three_hops_into_the_plant_posture(api):
    """A failing free-lime reading on an already released run pushes 583.78 tonnes back
    into unreleased stock, which strands the PLANNED 500.00 tonne batch at FEED_SHORT with
    its reservation released, which in turn drives the plant to CONSTRAINED; grinding that
    batch is then refused.

    PRD: "**Hop two**, caused by hop one now that availability no longer covers what was
    promised: every cement batch on that silo whose `status` is `PLANNED` and whose
    `clinker_tonnes_drawn` exceeds the silo's recomputed `available_tonnes` moves to
    `feed_state` `FEED_SHORT` and has its reservation released, so the silo's
    `reserved_tonnes` shrinks by that batch's `clinker_tonnes_drawn`; the batches are
    walked in `created_at` ascending order."

    Design: Difficulty/transitive_cascade/requarantine_withdrawal_cascades_three_hops_into_plant_production_posture
    """
    env = fx.released_clinker_environment(api)
    silo_id = env["clinker_silo"]["id"]
    batch = fx.create_planned_batch(
        api, env["plant_id"], silo_id, env["cement_silo"]["id"], clinker_tonnes_drawn=500.00
    )
    batch_id = batch["id"]

    before_silo = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert_amount(before_silo["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(before_silo["reserved_tonnes"], 500.00, "reserved_tonnes")
    assert_amount(before_silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(before_silo["available_tonnes"], 83.78, "available_tonnes")
    assert batch["feed_state"] == "FEED_READY"

    before_plant = validate_success(api.get_plant(env["plant_id"], ENGINEER_HEADERS))
    assert before_plant["production_posture"] == "NORMAL"

    withdrawal = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.62, kiln_run_id=env["run"]["id"]),
            LAB_HEADERS,
        ),
        201,
    )
    assert withdrawal["in_spec"] is False
    assert_amount(withdrawal["spec_max"], 1.50, "spec_max")

    run = validate_success(api.get_kiln_run(env["run"]["id"], QUALITY_HEADERS))
    assert run["quality_state"] == "QUARANTINED"
    assert run["process_state"] == "COMPLETED"
    assert_amount(run["free_lime_pct"], 1.62, "free_lime_pct")

    # Hop one and hop two together leave the silo fully encumbered and unreserved.
    after_silo = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert_amount(after_silo["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(after_silo["unreleased_tonnes"], 583.78, "unreleased_tonnes")
    assert_amount(after_silo["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(after_silo["available_tonnes"], 0.00, "available_tonnes")

    # Hop two: the feed dimension moves while the status dimension does not.
    after_batch = validate_success(api.get_cement_batch(batch_id, ENGINEER_HEADERS))
    assert after_batch["feed_state"] == "FEED_SHORT"
    assert after_batch["status"] == "PLANNED"

    # Hop three: the plant's posture.
    after_plant = validate_success(api.get_plant(env["plant_id"], ENGINEER_HEADERS))
    assert after_plant["production_posture"] == "CONSTRAINED"

    validate_error(
        api.start_grinding(batch_id, OPERATOR_HEADERS),
        ApiErrorId.ERR_BATCH_FEED_SHORT.value,
        409,
    )


def test_a_second_release_walks_the_withdrawal_cascade_back_in_reverse(api):
    """Once a passing reading returns the run to PENDING_LAB and the manager releases it
    again, the release cascade restores exactly what the withdrawal took: the stranded
    batch is FEED_READY, its 500.00 tonne reservation is re-taken and the plant is NORMAL.

    PRD: "**Hop two**, caused by hop one now that the silo has genuine availability: every
    cement batch drawing on that silo whose `feed_state` is `FEED_SHORT` is walked in
    `created_at` ascending order, and each one whose `clinker_tonnes_drawn` is no greater
    than the silo's *current* `available_tonnes` returns to `feed_state` `FEED_READY` and
    re-reserves its draw — the silo's `reserved_tonnes` grows by that batch's
    `clinker_tonnes_drawn` and `available_tonnes` is recomputed after each batch, so an
    early large batch can consume the headroom a later small one would otherwise have
    used."

    Design: Difficulty/transitive_cascade/requarantine_withdrawal_cascades_three_hops_into_plant_production_posture
    """
    env = fx.released_clinker_environment(api)
    silo_id = env["clinker_silo"]["id"]
    run_id = env["run"]["id"]
    batch = fx.create_planned_batch(
        api, env["plant_id"], silo_id, env["cement_silo"]["id"], clinker_tonnes_drawn=500.00
    )
    batch_id = batch["id"]

    fx.record_free_lime(api, run_id, 1.62)
    stranded = fx.data_of(api.get_cement_batch(batch_id, ENGINEER_HEADERS))
    assert stranded["feed_state"] == "FEED_SHORT"

    fx.record_free_lime(api, run_id, 1.40)
    retested = validate_success(api.get_kiln_run(run_id, QUALITY_HEADERS))
    assert retested["quality_state"] == "PENDING_LAB"

    released = validate_success(api.release_clinker(run_id, QUALITY_HEADERS))
    assert released["quality_state"] == "RELEASED"

    restored_batch = validate_success(api.get_cement_batch(batch_id, ENGINEER_HEADERS))
    assert restored_batch["feed_state"] == "FEED_READY"
    assert restored_batch["status"] == "PLANNED"

    restored_silo = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert_amount(restored_silo["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(restored_silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(restored_silo["reserved_tonnes"], 500.00, "reserved_tonnes")
    assert_amount(restored_silo["available_tonnes"], 83.78, "available_tonnes")

    restored_plant = validate_success(api.get_plant(env["plant_id"], ENGINEER_HEADERS))
    assert restored_plant["production_posture"] == "NORMAL"

    validate_success(api.start_grinding(batch_id, OPERATOR_HEADERS))
