"""The content gates that stand in front of each hop of a repair, and the refusals
the shop hears when it tries to move a car that is not ready.

Committing an estimate that has no priced labor on it, staging a car whose bumper
cover has not been bought yet, sending a body-shop job to the paint booth with a
part still sitting in its box, releasing a vehicle whose paperwork still shows an
unresolved supply problem, and answering an insurer with a partial cheque that is
not actually partial: each is refused here, and each story ends with the same call
succeeding once the gate it tripped has been satisfied.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ESTIMATOR_HEADERS,
    PARTS_MANAGER_HEADERS,
    SHOP_ADMIN_HEADERS,
    TECHNICIAN_HEADERS,
    make_insurer_adjuster_headers,
)

# A deductible of 25,000 cents keeps the owner's share on these orders below the
# 50,000-cent consent threshold, so the posture stays OPEN and every refusal in
# this file is the content gate under test rather than a money freeze.
_SMALL_DEDUCTIBLE = {"deductible_cents": 25000}

# The 4.5-hour body operation the requirements use in their own worked pass:
# 4.5 hours at an effective 6,000 cents is 27,000, and four percent of that is a
# 1,080-cent supplies fee, so the frozen estimate reads 28,080 cents.
_LOCKED_PRE_TAX_CENTS = 28080

_PART_LIST_PRICE_CENTS = 30000
_PART_QUOTE_CENTS = 20000
_PROMISED_ETA = "2026-08-05T00:00:00Z"


def _advance(api, order_id, to_stage):
    """The technician's stage hop, returned raw so a refusal can be read off it."""
    return api.advance_stage(order_id, f.stage_advance_payload(to_stage), TECHNICIAN_HEADERS)


def _ordered_body_part(api, world, vendor_id):
    """One OEM part on the world's body operation, walked as far as ORDERED."""
    part = fx.add_parts_line(
        api,
        world["line_ids"][0],
        list_price_cents=_PART_LIST_PRICE_CENTS,
        qty=1,
    )
    fx.quote_part(api, part["id"], vendor_id, _PART_QUOTE_CENTS)
    fx.accept_price(api, part["id"])
    return fx.place_parts_order(api, part["id"], _PROMISED_ETA)


def test_a_lock_without_priced_labor_and_a_staging_hop_with_an_unbought_part_are_refused(api):
    """An unpriced estimate cannot be committed, and a car with a part still on the shelf cannot be staged.

    PRD: "At least one labor line on the order must be `DRAFT`, or the lock is refused with `ERR_NO_ESTIMATE_LINES`."
    PRD: "Into `PARTS_STAGED` from `ESTIMATE_LOCKED`: no parts line on the order may still be at `PLANNED`, `QUOTED`, `COUNTERED` or `PRICE_LOCKED` — every part is either ordered or off the estimate — or the hop is refused with `ERR_PARTS_NOT_PROCURED`."
    Design: Corner/errors/lock_and_parts_staging_gates_are_rejected
    """
    # Order A is blueprinted off a teardown finding, but nobody wrote a labor line.
    world_a = fx.blueprinted_world(api, order_overrides=_SMALL_DEDUCTIBLE)
    before_a = fx.read_order(api, world_a["order_id"])
    A.assert_stage(before_a, C.STAGE_BLUEPRINTED)

    validate_error(
        api.lock_estimate(world_a["order_id"], None, ESTIMATOR_HEADERS),
        ApiErrorId.NO_ESTIMATE_LINES.value,
        422,
    )

    after_a = fx.read_order(api, world_a["order_id"])
    A.assert_stage(after_a, C.STAGE_BLUEPRINTED)
    A.assert_version(after_a, before_a["version"], "repair order A")

    # Order B is fully priced and locked, but carries a part still at PLANNED.
    world_b = fx.locked_world(api, order_overrides=_SMALL_DEDUCTIBLE)
    A.assert_stage(world_b["order"], C.STAGE_ESTIMATE_LOCKED)
    A.assert_cents(
        world_b["order"]["pre_tax_total_cents"], _LOCKED_PRE_TAX_CENTS, "pre_tax_total_cents"
    )

    vendor = fx.create_vendor(api)
    part = fx.add_parts_line(
        api, world_b["line_ids"][0], list_price_cents=_PART_LIST_PRICE_CENTS, qty=1
    )
    A.assert_parts_line_state(
        part, procurement_status="PLANNED", authorization_status=C.AUTH_INSURER_ALLOWED
    )

    before_b = fx.read_order(api, world_b["order_id"])
    validate_error(
        _advance(api, world_b["order_id"], C.STAGE_PARTS_STAGED),
        ApiErrorId.PARTS_NOT_PROCURED.value,
        422,
    )

    # The refusal left the frozen estimate exactly where the lock had put it.
    after_b = fx.read_order(api, world_b["order_id"])
    A.assert_stage(after_b, C.STAGE_ESTIMATE_LOCKED)
    A.assert_cents(after_b["pre_tax_total_cents"], _LOCKED_PRE_TAX_CENTS, "pre_tax_total_cents")
    A.assert_version(after_b, before_b["version"], "repair order B")

    # Quoting and freezing the price is still not buying the part.
    fx.quote_part(api, part["id"], vendor["id"], _PART_QUOTE_CENTS)
    priced = fx.accept_price(api, part["id"])
    A.assert_parts_line_state(priced, procurement_status="PRICE_LOCKED")
    validate_error(
        _advance(api, world_b["order_id"], C.STAGE_PARTS_STAGED),
        ApiErrorId.PARTS_NOT_PROCURED.value,
        422,
    )

    # Once the part is actually on order, the identical hop is admitted.
    ordered = fx.place_parts_order(api, part["id"], _PROMISED_ETA)
    A.assert_parts_line_state(ordered, procurement_status="ORDERED")
    staged = validate_success(_advance(api, world_b["order_id"], C.STAGE_PARTS_STAGED))
    A.assert_stage(staged, C.STAGE_PARTS_STAGED)


def test_the_repair_hop_needs_a_stall_and_the_paint_hop_needs_the_part_on_the_car(api):
    """A car cannot enter repair with no stall booked, and cannot reach the paint booth with a part still in its box.

    PRD: "Into `REPAIR` from `PARTS_STAGED`: at least one booking on the order with `stage` `REPAIR` and `status` `SCHEDULED` must exist, or the hop is refused with `ERR_NO_STAGE_ASSIGNMENT`."
    PRD: "Into `REFINISH_CALIBRATION` from `REPAIR`: no parts line may still be at `ORDERED` or `RECEIVED` — everything bought is on the car or has been sent back — or the hop is refused with `ERR_PARTS_NOT_INSTALLED`; and every procedure record on the order whose `operation_scope` is `STRUCTURAL` must have `adherence_documented` true, or the hop is refused with `ERR_PROCEDURE_ADHERENCE_MISSING`; and at least one booking with `stage` `REFINISH_CALIBRATION` and `status` `SCHEDULED` must exist, or the hop is refused with `ERR_NO_STAGE_ASSIGNMENT`."
    PRD: "Constraint satisfaction, in this order: supplier quantity cap (`ERR_VENDOR_QTY_CAP_EXCEEDED`), stall window conflict (`ERR_STALL_WINDOW_CONFLICT`), calibration bay capacity (`ERR_CALIBRATION_BAY_CAPACITY_EXCEEDED`), supplement round limit (`ERR_SUPPLEMENT_ROUND_LIMIT`), at least one teardown finding (`ERR_NO_TEARDOWN_FINDINGS`), at least one draft labor line (`ERR_NO_ESTIMATE_LINES`), parts procured (`ERR_PARTS_NOT_PROCURED`), parts installed or returned (`ERR_PARTS_NOT_INSTALLED`), a scheduled stall booking for the stage being entered (`ERR_NO_STAGE_ASSIGNMENT`), return quantity in range (`ERR_INVALID_RETURN_QUANTITY`), receive and install quantities in range (`ERR_INVALID_RECEIVE_QUANTITY`), counter strictly lower (`ERR_COUNTER_NOT_LOWER`), revised quote from the same supplier (`ERR_VENDOR_MISMATCH`), parts line authorized for money (`ERR_CUSTOMER_CONSENT_REQUIRED`), original-equipment upgrade actually applicable (`ERR_OEM_UPGRADE_NOT_APPLICABLE`), latest inspection passed (`ERR_QC_NOT_PASSED`), no open parts delay (`ERR_OPEN_PARTS_DELAY`), partial amount strictly inside the request (`ERR_INVALID_PARTIAL_AMOUNT`), and a supplement behind any post-lock labor line (`ERR_SUPPLEMENT_REQUIRED`)."
    Design: Corner/errors/repair_and_refinish_gates_are_rejected
    """
    fx.set_clock(api, C.CLOCK_DEFAULT)
    body_stall = fx.create_stall(api, name="Body P", stall_type="BODY")
    paint_stall = fx.create_stall(api, name="Paint P", stall_type="PAINT")

    world = fx.locked_world(api, order_overrides=_SMALL_DEDUCTIBLE)
    vendor = fx.create_vendor(api, name="Harbour Honda")
    part = _ordered_body_part(api, world, vendor["id"])
    A.assert_parts_line_state(part, procurement_status="ORDERED")

    staged = fx.advance_stage(api, world["order_id"], C.STAGE_PARTS_STAGED)
    A.assert_stage(staged, C.STAGE_PARTS_STAGED)

    # Nothing has been booked, so there is nowhere to put the car.
    validate_error(
        _advance(api, world["order_id"], C.STAGE_REPAIR),
        ApiErrorId.NO_STAGE_ASSIGNMENT.value,
        422,
    )
    A.assert_stage(fx.read_order(api, world["order_id"]), C.STAGE_PARTS_STAGED)

    booking = fx.book_stall(
        api, world["order_id"], body_stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200
    )
    A.assert_count(booking["occupied_minutes"], 240, "occupied_minutes")
    A.assert_count(
        fx.read_stall(api, body_stall["id"])["booked_minutes"], 240, "booked_minutes"
    )
    in_repair = validate_success(_advance(api, world["order_id"], C.STAGE_REPAIR))
    A.assert_stage(in_repair, C.STAGE_REPAIR)

    # The part has landed but is not on the car, and no paint stall is booked
    # either: the parts gate is the earlier rung, so it is the one that answers.
    received = fx.receive_part(api, part["id"], 1)
    A.assert_parts_line_state(received, procurement_status="RECEIVED")
    rows, meta = fx.page(
        api.list_stage_assignments(
            TECHNICIAN_HEADERS,
            {"repair_order_id": world["order_id"], "stall_id": paint_stall["id"]},
        )
    )
    A.assert_page(meta, total_count=0)
    assert rows == []
    validate_error(
        _advance(api, world["order_id"], C.STAGE_REFINISH_CALIBRATION),
        ApiErrorId.PARTS_NOT_INSTALLED.value,
        422,
    )

    # Booking the paint stall does not help: the same code comes back.
    fx.book_stall(
        api,
        world["order_id"],
        paint_stall["id"],
        C.STAGE_REFINISH_CALIBRATION,
        fx.T1300,
        fx.T1500,
    )
    validate_error(
        _advance(api, world["order_id"], C.STAGE_REFINISH_CALIBRATION),
        ApiErrorId.PARTS_NOT_INSTALLED.value,
        422,
    )
    A.assert_stage(fx.read_order(api, world["order_id"]), C.STAGE_REPAIR)

    # Fitted to the car, the part clears the gate and the hop is accepted.
    installed = fx.install_part(api, part["id"])
    A.assert_parts_line_state(installed, procurement_status="INSTALLED")
    refinishing = validate_success(
        _advance(api, world["order_id"], C.STAGE_REFINISH_CALIBRATION)
    )
    A.assert_stage(refinishing, C.STAGE_REFINISH_CALIBRATION)


def test_delivery_waits_first_for_a_passing_inspection_and_then_for_the_supply_problem_to_close(api):
    """A finished car is held back by an unresolved parts delay even after its inspection passes.

    PRD: "When the `condition` is anything other than `CORRECT`, nothing is closed; instead a new delay event is opened against the line with `reason` `INCORRECT_PART`, so the order's `open_parts_delay_count` stays raised."
    PRD: "It requires the stage to be `READY_FOR_QC`, the `authorization_posture` to be `OPEN` (else `ERR_AUTHORIZATION_POSTURE_BLOCKED`), the inspection on the order with the highest `sequence_number` to have `result` `PASS` (else `ERR_QC_NOT_PASSED` — an earlier pass followed by a later fail does not qualify), and the order's `open_parts_delay_count` to be exactly 0 (else `ERR_OPEN_PARTS_DELAY`)."
    Design: Corner/errors/delivery_gates_are_rejected_before_qc_and_on_an_open_delay
    """
    fx.set_clock(api, C.CLOCK_DEFAULT)
    body_stall = fx.create_stall(api, name="Body Q", stall_type="BODY")
    paint_stall = fx.create_stall(api, name="Paint Q", stall_type="PAINT")

    world = fx.locked_world(api, order_overrides=_SMALL_DEDUCTIBLE)
    order_id = world["order_id"]
    vendor = fx.create_vendor(api, name="Harbour Honda")
    part = _ordered_body_part(api, world, vendor["id"])

    fx.advance_stage(api, order_id, C.STAGE_PARTS_STAGED)
    fx.book_stall(api, order_id, body_stall["id"], C.STAGE_REPAIR, fx.T0800, fx.T1200)
    fx.advance_stage(api, order_id, C.STAGE_REPAIR)

    # The wrong part turns up, which opens a supply interruption nobody closes.
    received = fx.receive_part(api, part["id"], 1, condition="INCORRECT")
    A.assert_parts_line_state(received, procurement_status="RECEIVED")
    A.assert_count(
        fx.read_order(api, order_id)["open_parts_delay_count"], 1, "open_parts_delay_count"
    )

    # It is fitted anyway, so the rest of the walk to the inspection bay is legal.
    fx.install_part(api, part["id"])
    fx.book_stall(
        api,
        order_id,
        paint_stall["id"],
        C.STAGE_REFINISH_CALIBRATION,
        fx.T1300,
        fx.T1500,
    )
    fx.advance_stage(api, order_id, C.STAGE_REFINISH_CALIBRATION)
    waiting = fx.advance_stage(api, order_id, C.STAGE_READY_FOR_QC)
    A.assert_stage(waiting, C.STAGE_READY_FOR_QC)
    A.assert_posture(waiting, C.POSTURE_OPEN)

    # With no inspection on file at all, the release is refused for the missing pass.
    validate_error(
        api.deliver_repair_order(order_id, None, SHOP_ADMIN_HEADERS),
        ApiErrorId.QC_NOT_PASSED.value,
        409,
    )

    inspection = fx.file_qc_inspection(api, order_id, True, 0, scan_report_ref="SCAN-9058")
    assert inspection["result"] == "PASS", (
        f"a clean checklist with no codes must pass, got {inspection['result']}"
    )
    A.assert_count(inspection["sequence_number"], 1, "sequence_number")

    # The inspection passed, so this second refusal is not a quality problem.
    validate_error(
        api.deliver_repair_order(order_id, None, SHOP_ADMIN_HEADERS),
        ApiErrorId.OPEN_PARTS_DELAY.value,
        409,
    )

    held = fx.read_order(api, order_id)
    A.assert_stage(held, C.STAGE_READY_FOR_QC)
    A.assert_null(held["delivered_at"], "delivered_at")
    A.assert_count(held["open_parts_delay_count"], 1, "open_parts_delay_count")

    events, meta = fx.page(api.list_order_parts_delay_events(order_id, PARTS_MANAGER_HEADERS))
    A.assert_page(meta, total_count=1)
    event = events[0]
    assert event["parts_line_id"] == part["id"]
    assert event["reason"] == "INCORRECT_PART", (
        f"an incorrect receipt opens an INCORRECT_PART delay, got {event['reason']}"
    )
    A.assert_instant(event["opened_at"], C.CLOCK_DEFAULT, "opened_at")
    A.assert_null(event["closed_at"], "closed_at")
    A.assert_null(event["delay_minutes"], "delay_minutes")


def test_a_partial_on_either_endpoint_a_closed_supplement_and_the_round_ceiling_are_refused(api):
    """A partial cheque must land strictly inside the request, and only an information request can be answered.

    PRD: "**`PARTIAL`** moves the supplement from `SUBMITTED` to `PARTIAL` and requires an `approved_amount_cents` that is strictly greater than zero and strictly less than the `requested_amount_cents`; an amount of zero, a negative amount, or an amount at or above the request is refused with `ERR_INVALID_PARTIAL_AMOUNT`, as is an `APPROVE` or `DENY` decision that carries an amount at all."
    PRD: "The supplement's `status` must be `INFO_REQUESTED`, or the resubmission is refused with `ERR_SUPPLEMENT_NOT_OPEN`."
    PRD: "The supplement's `round_count` must be strictly less than the order's insurer program's `supplement_round_limit`, or the resubmission is refused with `ERR_SUPPLEMENT_ROUND_LIMIT` — with the default limit of 3, a supplement can be submitted, re-submitted and re-submitted once more, and the fourth attempt is refused."
    Design: Corner/errors/supplement_decision_missteps_are_rejected
    """
    # Order A sits under a program that keeps the default limit of three rounds.
    world_a = fx.locked_world(api, order_overrides=_SMALL_DEDUCTIBLE)
    adjuster_a = make_insurer_adjuster_headers(world_a["insurer_id"])
    supplement_a = fx.raise_supplement(
        api, world_a["order_id"], reason_code="HIDDEN_DAMAGE", requested_amount_cents=50000
    )
    assert supplement_a["status"] == "SUBMITTED"
    A.assert_count(supplement_a["round_count"], 1, "round_count")

    # Zero, the request itself and a cent above it are all outside the open interval.
    for amount in (0, 50000, 50001):
        validate_error(
            api.decide_supplement(
                supplement_a["id"],
                f.supplement_decision_payload("PARTIAL", approved_amount_cents=amount),
                adjuster_a,
            ),
            ApiErrorId.INVALID_PARTIAL_AMOUNT.value,
            422,
        )
        untouched = fx.read_supplement(api, supplement_a["id"])
        assert untouched["status"] == "SUBMITTED", (
            f"a refused PARTIAL of {amount} must leave the supplement SUBMITTED, "
            f"got {untouched['status']}"
        )
        A.assert_null(untouched["approved_amount_cents"], "approved_amount_cents")
        A.assert_null(untouched["decided_at"], "decided_at")
        A.assert_count(untouched["round_count"], 1, "round_count")
        A.assert_cents(untouched["requested_amount_cents"], 50000, "requested_amount_cents")

    # A resubmission answers an information request and nothing else.
    validate_error(
        api.resubmit_supplement(
            supplement_a["id"], f.supplement_resubmit_payload(45000), ESTIMATOR_HEADERS
        ),
        ApiErrorId.SUPPLEMENT_NOT_OPEN.value,
        409,
    )

    # Sent back for photographs, the same resubmission is welcome under a limit of three.
    asked = fx.decide_supplement(
        api,
        supplement_a["id"],
        world_a["insurer_id"],
        "REQUEST_INFO",
        note="Send the teardown photographs.",
    )
    assert asked["status"] == "INFO_REQUESTED"
    A.assert_null(asked["decided_at"], "decided_at")
    answered = fx.resubmit_supplement(api, supplement_a["id"], 45000)
    assert answered["status"] == "SUBMITTED"
    A.assert_count(answered["round_count"], 2, "round_count")
    A.assert_cents(answered["requested_amount_cents"], 45000, "requested_amount_cents")

    # Once the adjuster has answered for good, the negotiation is closed again.
    approved = fx.decide_supplement(api, supplement_a["id"], world_a["insurer_id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    A.assert_cents(approved["approved_amount_cents"], 45000, "approved_amount_cents")
    validate_error(
        api.resubmit_supplement(
            supplement_a["id"], f.supplement_resubmit_payload(40000), ESTIMATOR_HEADERS
        ),
        ApiErrorId.SUPPLEMENT_NOT_OPEN.value,
        409,
    )

    # Order B's program allows a single round, so its first answer is over the ceiling.
    world_b = fx.locked_world(
        api,
        insurer_overrides={"supplement_round_limit": 1},
        order_overrides=_SMALL_DEDUCTIBLE,
    )
    supplement_b = fx.raise_supplement(
        api, world_b["order_id"], reason_code="HIDDEN_DAMAGE", requested_amount_cents=50000
    )
    fx.decide_supplement(
        api,
        supplement_b["id"],
        world_b["insurer_id"],
        "REQUEST_INFO",
        note="Send the teardown photographs.",
    )
    validate_error(
        api.resubmit_supplement(
            supplement_b["id"], f.supplement_resubmit_payload(45000), ESTIMATOR_HEADERS
        ),
        ApiErrorId.SUPPLEMENT_ROUND_LIMIT.value,
        422,
    )
    frozen = fx.read_supplement(api, supplement_b["id"])
    assert frozen["status"] == "INFO_REQUESTED"
    A.assert_count(frozen["round_count"], 1, "round_count")
    A.assert_cents(frozen["requested_amount_cents"], 50000, "requested_amount_cents")
