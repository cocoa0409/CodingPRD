"""Do-not-pay screening: flag/hold/release cascades, the dual payment axes,
the execute cross-axis gate, and closed-interval window conflicts."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_payment,
    create_active_policy,
    create_do_not_pay_record_payload,
    create_dnp_record,
    create_payment_file,
    execute_payment,
    read_payment,
    register_payee,
    remove_dnp_record,
    set_logical_clock,
    setup_evaluated_payment,
    validate_error,
)

OPERATOR = TEST_USERS["treasury_operator_headers"]


def test_dnp_record_creation_depth2(api):
    """PRD §3.9: "creation immediately cascades across the payment population:
    every not-yet-executed payment whose payee TIN the record now matches is
    flagged — a `VERIFIED` payment is forced to `HELD` with `integrity_status`
    `FLAGGED`".
    PRD §3.9: "Every `HELD` payment whose payee TIN no longer matches any
    remaining `ACTIVE` record at the current clock returns to `VERIFIED` with
    `integrity_status` restored to `CLEAR`".

    Design: Difficulty/transitive_cascade/dnp_record_creation_depth2
    """
    set_logical_clock()
    payee = register_payee(tin="111-22-3333")
    create_active_policy("VENDOR", "FULL")
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 25000, "VENDOR")
    assert payment["processing_status"] == "VERIFIED"
    assert payment["integrity_status"] == "CLEAR"

    record = create_dnp_record("111-22-3333", list_source="DEATH_MASTER_FILE")
    held = read_payment(payment["id"])
    assert held["integrity_status"] == "FLAGGED"
    assert held["processing_status"] == "HELD"

    remove_dnp_record(record)
    released = read_payment(payment["id"])
    assert released["integrity_status"] == "CLEAR"
    assert released["processing_status"] == "VERIFIED"


def test_payment_parallel_dimensions(api):
    """PRD §3.9: "an `EVALUATED` payment is flagged but stays `EVALUATED`, free
    to be re-evaluated yet barred from execution until cleared."
    PRD §3.4: "a do-not-pay hit on a `VERIFIED` payment forces it to `HELD`,
    and execution is gated on `CLEAR`."

    Design: Difficulty/non_linear_state_machine/payment_parallel_dimensions
    """
    ns = setup_evaluated_payment(amount_cents=40000, debt_amount_cents=50000)
    payment = ns["payment"]
    assert payment["processing_status"] == "EVALUATED"

    record = create_dnp_record("111-22-3333")
    flagged = read_payment(payment["id"])
    # The flag crosses axes; the processing axis does not move from EVALUATED.
    assert flagged["integrity_status"] == "FLAGGED"
    assert flagged["processing_status"] == "EVALUATED"

    resp = api.execute_payment(payment["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_DNP_FLAGGED_PAYMENT)

    remove_dnp_record(record)
    cleared = read_payment(payment["id"])
    assert cleared["integrity_status"] == "CLEAR"
    assert cleared["processing_status"] == "EVALUATED"

    execute_payment(payment)
    executed = read_payment(payment["id"])
    assert executed["processing_status"] == "EXECUTED"
    assert executed["total_offset_cents"] == 40000
    assert executed["disbursed_cents"] == 0


def test_execute_state_vs_dnp_safety(api):
    """PRD §2.8: "Every request is validated against an ordered cascade of
    eleven tiers, and the first failing tier produces the response, masking
    anything later."
    PRD §2.8 (tier 7): "The attempted transition is defined for the resource's
    current state — terminal states included — and OCC version equality holds
    where §2.7 applies — otherwise `ERR_INVALID_STATE`,
    `ERR_PAYMENT_NOT_EXECUTABLE`, `ERR_OFFSET_NOT_APPLIED`, or
    `ERR_APPEAL_LIMIT_REACHED` (409), or `ERR_STALE_VERSION` (412)."
    PRD §2.8 (tier 8): "Due-process attestation, the pre-offset notice window,
    the garnishment hearing window, and payment integrity — otherwise
    `ERR_DUE_PROCESS_NOT_COMPLETED`, `ERR_NOTICE_WINDOW_NOT_ELAPSED`,
    `ERR_AWG_HEARING_WINDOW_OPEN`, or `ERR_DNP_FLAGGED_PAYMENT` (409)."

    Design: Difficulty/priority_pair_validation_conflict/execute_state_vs_dnp_safety
    """
    set_logical_clock()
    payee = register_payee(tin="111-22-3333")
    create_active_policy("VENDOR", "FULL")
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 25000, "VENDOR")
    create_dnp_record("111-22-3333", list_source="DEBARMENT_LIST")

    held = read_payment(payment["id"])
    assert held["processing_status"] == "HELD"
    assert held["integrity_status"] == "FLAGGED"

    # Both the state gate (not EVALUATED) and the integrity gate (FLAGGED) are
    # violated; the earlier state tier wins.
    resp = api.execute_payment(payment["id"], OPERATOR)
    err = validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_EXECUTABLE)
    assert err["error_id"] != "ERR_DNP_FLAGGED_PAYMENT"

    after = read_payment(payment["id"])
    assert after["processing_status"] == "HELD"
    assert after["total_offset_cents"] == 0


def test_dnp_record_closed_interval_touching(api):
    """PRD §2.11: "Two records for the same `tin` and `list_source` may not have
    overlapping intervals, and intervals that merely touch count as overlapping;
    a conflicting creation is rejected with `ERR_DNP_WINDOW_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/dnp_record_closed_interval_touching
    """
    set_logical_clock()
    create_dnp_record(
        "999-88-7777",
        list_source="SAM_EXCLUSION",
        window=("2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"),
    )

    # Touching the incumbent's inclusive end conflicts.
    resp_touch = api.create_do_not_pay_record(
        create_do_not_pay_record_payload(
            "999-88-7777",
            list_source="SAM_EXCLUSION",
            effective_from="2026-06-01T00:00:00Z",
            effective_until="2026-12-01T00:00:00Z",
        ),
        OPERATOR,
    )
    validate_error(resp_touch, ApiErrorId.ERR_DNP_WINDOW_OVERLAP)

    # Starting strictly after the incumbent's end is accepted.
    later = create_dnp_record(
        "999-88-7777",
        list_source="SAM_EXCLUSION",
        window=("2026-06-02T00:00:00Z", "2026-12-01T00:00:00Z"),
    )
    assert later["status"] == "ACTIVE"

    # The conflict key is (tin, list_source): another source overlaps freely.
    other_source = create_dnp_record(
        "999-88-7777",
        list_source="DEATH_MASTER_FILE",
        window=("2026-03-01T00:00:00Z", "2026-09-01T00:00:00Z"),
    )
    assert other_source["status"] == "ACTIVE"
