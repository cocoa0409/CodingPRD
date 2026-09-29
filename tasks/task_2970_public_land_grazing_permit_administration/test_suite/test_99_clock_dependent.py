"""Tests that move the logical clock. The clock is global, forward-only and shared by the whole
suite, so every test that advances it lives in this alphabetically last module and the targets
below increase monotonically down the file."""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aums,
    assert_pct,
    make_adjudicator_headers,
    make_officer_headers,
    make_permittee_headers,
    make_specialist_headers,
    make_system_admin_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    add_use_record,
    allotment_with_pasture,
    create_allotment,
    create_aoi,
    create_closure_order,
    create_pasture,
    create_permit,
    create_permittee,
    get_allotment,
    get_aoi,
    get_closure_order,
    get_bill,
    get_permit,
    get_permittee,
    issue_aoi,
    issue_permit,
    permittee_with_base_property,
    list_bills,
    set_clock,
)


def _two_dimension_setup():
    """A 1200-AUM allotment with two 300-AUM pastures and a rotation requirement of 2, an ISSUED
    300-AUM permit running to 2030-12-31, and an ISSUED 2026 instruction whose preliminary bill of
    54,100 cents is unpaid."""
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=300,
                                 required_pasture_rotation_count=2, acres=40000)
    upper = land["pasture"]
    lower = create_pasture(land["allotment"]["id"], pasture_aum_capacity=300, sequence_order=2)
    holder = permittee_with_base_property(carrying_capacity_aums=400)
    permit = issue_permit(create_permit(
        land["allotment"]["id"], holder["permittee"]["id"], holder["base_property"]["id"],
        requested_aums=300, term_start_date="2026-01-01", term_end_date="2030-12-31")["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=300,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")
    first = add_use_record(aoi["id"], upper["id"], planned_head_count=100,
                           livestock_kind="CATTLE", planned_entry_date="2026-04-01",
                           planned_exit_date="2026-05-02")
    second = add_use_record(aoi["id"], lower["id"], planned_head_count=100,
                            livestock_kind="CATTLE", planned_entry_date="2026-05-02",
                            planned_exit_date="2026-06-01")
    assert_aums(first["planned_aums"], 103.33)
    assert_aums(second["planned_aums"], 100.00)
    issued = issue_aoi(aoi["id"])
    assert issued["aoi_status"] == "ISSUED"
    bills = [b for b in list_bills(aoi_id=aoi["id"], bill_type="PRELIMINARY_USE")
             if b["bill_status"] != "VOIDED"]
    assert len(bills) == 1
    bill = bills[0]
    assert bill["total_amount_cents"] == 54100
    assert bill["bill_status"] == "ISSUED"
    return {"allotment": land["allotment"], "permittee": holder["permittee"],
            "permit": permit, "aoi": issued, "bill": bill}


def test_advancing_the_clock_past_the_due_date_moves_only_the_billing_dimension():
    """The bill was due 2026-08-31 — the default clock date plus thirty days — and a clock set to
    2026-09-01 falls strictly after it, so the bill turns DELINQUENT, the permit's account_status
    turns DELINQUENT and the permittee is DEBT_FLAGGED, while the permit's grazing authority stays
    exactly ISSUED with no suspension_reason.

    PRD 3.6: "Every use bill is raised in `bill_status` `ISSUED` with `amount_paid_cents` of 0 and
    a `due_date` of the logical-clock date at issuance plus 30 days."
    PRD 3.6: "Delinquency is driven purely by the logical clock. When the clock advances, every
    bill in `bill_status` `ISSUED` whose `due_date` falls **strictly before** the new clock date
    and whose `total_amount_cents` still exceeds its `amount_paid_cents` moves to `bill_status`
    `DELINQUENT`; a bill whose `due_date` equals the new clock date is not yet delinquent."
    PRD 3.6: "The authorization dimension is untouched: an `ISSUED` permit stays `ISSUED` while
    becoming `DELINQUENT` on its billing axis."
    PRD 2.5: "The service does not read the host's wall clock for business purposes. It maintains a
    **logical clock**, an ISO 8601 UTC instant that begins at exactly `2026-08-01T00:00:00Z` at
    server start and thereafter moves only when a `SystemAdmin` sets it."

    Design: Difficulty/non_linear_state_machine/permit_parallel_status_dimensions
    """
    setup = _two_dimension_setup()
    assert setup["bill"]["due_date"] == "2026-08-31"
    before = get_permit(setup["permit"]["id"])
    assert before["permit_status"] == "ISSUED"
    assert before["account_status"] == "CURRENT"

    set_clock("2026-09-01T00:00:00Z")

    bill = get_bill(setup["bill"]["id"])
    assert bill["bill_status"] == "DELINQUENT"
    assert bill["amount_paid_cents"] == 0

    permit = get_permit(setup["permit"]["id"])
    assert permit["account_status"] == "DELINQUENT"
    assert permit["permit_status"] == "ISSUED", "money never moves the authorization axis"
    assert permit["suspension_reason"] is None

    permittee = get_permittee(setup["permittee"]["id"])
    assert permittee["permittee_status"] == "DEBT_FLAGGED"
    assert permittee["outstanding_balance_cents"] == 54100
    assert get_aoi(setup["aoi"]["id"])["aoi_status"] == "ISSUED"


def test_paying_the_delinquent_bill_restores_the_account_and_leaves_the_permit_issued():
    """A fresh instruction issued after the first advance carries a due date thirty days out, and
    a clock set to the day after that date turns it delinquent; paying it in full brings the bill
    to PAID, the account_status back to CURRENT and the permittee back to IN_GOOD_STANDING, and the
    permit's permit_status has never left ISSUED across either movement.

    PRD 3.6: "A successful payment increases `amount_paid_cents` by `amount_cents`, and when the
    accumulated `amount_paid_cents` reaches or exceeds `total_amount_cents` the bill moves to
    `bill_status` `PAID`."
    PRD 3.6: "when the permittee is left with no bill in `bill_status` `DELINQUENT`, every permit
    of that permittee whose `permit_status` is `PENDING_REVIEW`, `ISSUED` or `SUSPENDED` moves
    `account_status` `DELINQUENT → CURRENT`; and a permit that was `SUSPENDED` with
    `suspension_reason` `NONPAYMENT` then moves `SUSPENDED → ISSUED` with its `suspension_reason`
    cleared to null."
    PRD 2.9: "A permittee's `permittee_status` is derived from the same aggregate: it is
    `DEBT_FLAGGED` exactly when `outstanding_balance_cents` is greater than zero **and** at least
    one of the contributing bills is in `bill_status` `DELINQUENT`, and `IN_GOOD_STANDING` in every
    other case — so an unpaid bill that is not yet overdue leaves the permittee
    `IN_GOOD_STANDING`."

    Design: Difficulty/non_linear_state_machine/permit_parallel_status_dimensions
    """
    setup = _two_dimension_setup()
    day_after_due = date.fromisoformat(setup["bill"]["due_date"]) + timedelta(days=1)

    set_clock("%sT00:00:00Z" % day_after_due.isoformat())
    assert get_bill(setup["bill"]["id"])["bill_status"] == "DELINQUENT"
    delinquent = get_permit(setup["permit"]["id"])
    assert delinquent["account_status"] == "DELINQUENT"
    assert delinquent["permit_status"] == "ISSUED"
    assert get_permittee(setup["permittee"]["id"])["permittee_status"] == "DEBT_FLAGGED"

    paid = get_success_data(api_client.record_payment(
        setup["bill"]["id"], f.payment_payload(54100),
        make_permittee_headers(setup["permittee"]["id"])), 201)
    assert paid["bill_status"] == "PAID"
    assert paid["amount_paid_cents"] == 54100

    permit = get_permit(setup["permit"]["id"])
    assert permit["account_status"] == "CURRENT"
    assert permit["permit_status"] == "ISSUED"
    assert permit["suspension_reason"] is None

    permittee = get_permittee(setup["permittee"]["id"])
    assert permittee["outstanding_balance_cents"] == 0
    assert permittee["permittee_status"] == "IN_GOOD_STANDING"
    assert get_aoi(setup["aoi"]["id"])["aoi_status"] == "ISSUED"


def test_advancing_the_clock_past_a_closure_orders_end_date_expires_it_and_restores_capacity():
    """No domain call is made at all: a clock advance past the order's 2026-08-20 end date moves the
    order ACTIVE -> EXPIRED and re-runs the recomputation chain by itself, so
    stocking_adjustment_pct falls from 0.2500 back to 0.0, effective_capacity_aums returns from 600
    to the full 800, open_aums follows, the posture returns RESTRICTED -> OPEN and the allotment's
    version moves by exactly 1.

    PRD 3.10: "When the logical clock advances, every closure order in `order_status` `ACTIVE` whose
    `effective_end_date` falls **strictly before** the new clock date moves to `order_status`
    `EXPIRED` and runs the same recomputation chain — allotment posture, capacity, instruction
    authorizations, bill supersession and permittee balances."
    PRD 3.10: "Otherwise it is the **maximum** over two families of contributors: the
    `reduction_pct` of every closure order on the allotment in `order_status` `ACTIVE`, and the
    `adjustment_pct` of every permit decision on the allotment with `decision_type`
    `STOCKING_ADJUSTMENT` and `decision_status` `EFFECTIVE`."
    PRD 3.10: "The `effective_capacity_aums` becomes the `carrying_capacity_aums` multiplied by one
    minus `stocking_adjustment_pct`, floored to a whole AUM — so a 0.40 reduction on a carrying
    capacity of 1,000 AUMs yields 600, and a total closure yields 0."
    PRD 3.10: "The `allotment_status` becomes `CLOSED` when `stocking_adjustment_pct` is exactly
    1.0, `RESTRICTED` when it is strictly between 0 and 1, and `OPEN` when it is exactly 0."

    Design: Corner/state_machines/corner_clock_advance_expires_closure_order_and_restores_capacity
    """
    allotment = create_allotment(admin_unit_code="QB-128", total_permitted_aums=800,
                                 acres=22500, required_pasture_rotation_count=1)
    order = create_closure_order(
        allotment["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.25,
        effective_start_date="2026-08-05", effective_end_date="2026-08-20",
        justification="Short-duration drought reduction while forage recovers.")
    assert order["order_status"] == "ACTIVE"

    before = get_allotment(allotment["id"])
    assert_pct(before["stocking_adjustment_pct"], 0.25)
    assert before["effective_capacity_aums"] == 600  # floor(800 x 0.75)
    assert before["allotment_status"] == "RESTRICTED"
    version_before = before["version"]

    # Strictly forward of every clock position this module has already reached, and strictly after
    # the order's inclusive end date, so the order is out of force.
    set_clock("2026-11-01T00:00:00Z")

    assert get_closure_order(order["id"])["order_status"] == "EXPIRED"
    after = get_allotment(allotment["id"])
    assert_pct(after["stocking_adjustment_pct"], 0.0)
    assert after["effective_capacity_aums"] == 800
    assert after["open_aums"] == 800
    assert after["allotment_status"] == "OPEN"
    assert after["version"] == version_before + 1
    assert after["current_grazing_year"] == 2026


def test_the_clock_refuses_to_stand_still_just_as_it_refuses_to_go_back():
    """A forward move to 2026-12-01 is accepted and returns an empty data object; re-sending that very
    same instant is refused with the same 422 ERR_CLOCK_NOT_MONOTONIC as a move back to 2026-11-15,
    because the requirement is strictly-after and not on-or-after. Neither refusal moves the clock: the
    next bill raised is due 2026-12-31, thirty days after the last accepted value.

    PRD 2.5: "The setting payload carries a single field, `current_utc`, holding the new instant; the
    requested value must be strictly after the present logical clock value, and a value equal to or
    earlier than the present one is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."
    PRD 2.5: "A successful clock set returns 200 with an empty `data` object."
    PRD 2.6: "**Clock monotonicity** — `ERR_CLOCK_NOT_MONOTONIC`, HTTP 422, on the clock-setting
    operation, as described in §2.5."
    PRD 3.6: "Every use bill is raised in `bill_status` `ISSUED` with `amount_paid_cents` of 0 and a
    `due_date` of the logical-clock date at issuance plus 30 days."

    Design: Corner/validations/corner_logical_clock_must_move_strictly_forward
    """
    assert set_clock("2026-12-01T00:00:00Z") == {}, "a successful set returns an empty data object"

    validate_error(api_client.set_clock(f.clock_payload("2026-11-15T00:00:00Z"),
                                       make_system_admin_headers()),
                   ApiErrorId.ERR_CLOCK_NOT_MONOTONIC, 422)
    validate_error(api_client.set_clock(f.clock_payload("2026-12-01T00:00:00Z"),
                                       make_system_admin_headers()),
                   ApiErrorId.ERR_CLOCK_NOT_MONOTONIC, 422)

    # The only way to read the clock back is through something it derives: a bill's due date.
    setup = _two_dimension_setup()
    assert setup["bill"]["due_date"] == "2026-12-31", "30 days after the last accepted clock value"
    assert get_allotment(setup["allotment"]["id"])["current_grazing_year"] == 2026


def test_delinquency_spares_the_due_date_itself_and_bites_on_the_following_day():
    """The boundary is strict on both sides. A clock set to the bill's own due date leaves the bill
    ISSUED, the permittee IN_GOOD_STANDING and the permit CURRENT; the very next day the identical
    call flips all three at once, and the permit's grazing authority stays exactly ISSUED throughout.
    Paying in full reverses all three, so the derived standing tracks the bill's status and not merely
    the size of the balance, and the instruction that raised the bill never leaves ISSUED.

    PRD 3.6: "Every use bill is raised in `bill_status` `ISSUED` with `amount_paid_cents` of 0 and
    a `due_date` of the logical-clock date at issuance plus 30 days."
    PRD 3.6: "Delinquency is driven purely by the logical clock. When the clock advances, every
    bill in `bill_status` `ISSUED` whose `due_date` falls **strictly before** the new clock date
    and whose `total_amount_cents` still exceeds its `amount_paid_cents` moves to `bill_status`
    `DELINQUENT`; a bill whose `due_date` equals the new clock date is not yet delinquent."
    PRD 3.6: "A successful payment increases `amount_paid_cents` by `amount_cents`, and when the
    accumulated `amount_paid_cents` reaches or exceeds `total_amount_cents` the bill moves to
    `bill_status` `PAID`."
    PRD 3.6: "when the permittee is left with no bill in `bill_status` `DELINQUENT`, every permit
    of that permittee whose `permit_status` is `PENDING_REVIEW`, `ISSUED` or `SUSPENDED` moves
    `account_status` `DELINQUENT → CURRENT`; and a permit that was `SUSPENDED` with
    `suspension_reason` `NONPAYMENT` then moves `SUSPENDED → ISSUED` with its `suspension_reason`
    cleared to null."
    PRD 3.6: "The authorization dimension is untouched: an `ISSUED` permit stays `ISSUED` while
    becoming `DELINQUENT` on its billing axis."
    PRD 2.9: "A permittee's `permittee_status` is derived from the same aggregate: it is
    `DEBT_FLAGGED` exactly when `outstanding_balance_cents` is greater than zero **and** at least
    one of the contributing bills is in `bill_status` `DELINQUENT`, and `IN_GOOD_STANDING` in every
    other case — so an unpaid bill that is not yet overdue leaves the permittee
    `IN_GOOD_STANDING`."

    Design: Corner/endpoints/corner_clock_advance_marks_overdue_bills_delinquent
    """
    setup = _two_dimension_setup()
    # The server boots with its logical clock at the 2026-08-01 epoch and this test advances it
    # itself, so the bill raised at issuance falls due thirty days after that epoch.
    assert setup["bill"]["due_date"] == "2026-08-31", "thirty days after the clock at issuance"
    assert setup["bill"]["total_amount_cents"] == 54100
    assert setup["bill"]["bill_status"] == "ISSUED"
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 54100
    assert get_permittee(setup["permittee"]["id"])["permittee_status"] == "IN_GOOD_STANDING"
    assert get_permit(setup["permit"]["id"])["account_status"] == "CURRENT"

    set_clock("2026-08-31T00:00:00Z")

    assert get_bill(setup["bill"]["id"])["bill_status"] == "ISSUED", "the due date is not overdue"
    assert get_permittee(setup["permittee"]["id"])["permittee_status"] == "IN_GOOD_STANDING"
    on_the_day = get_permit(setup["permit"]["id"])
    assert on_the_day["account_status"] == "CURRENT"
    assert on_the_day["permit_status"] == "ISSUED"

    set_clock("2026-09-01T00:00:00Z")

    assert get_bill(setup["bill"]["id"])["bill_status"] == "DELINQUENT", "one day later it bites"
    assert get_permittee(setup["permittee"]["id"])["permittee_status"] == "DEBT_FLAGGED"
    overdue = get_permit(setup["permit"]["id"])
    assert overdue["account_status"] == "DELINQUENT"
    assert overdue["permit_status"] == "ISSUED", "the authorization axis never moved"

    paid = get_success_data(api_client.record_payment(
        setup["bill"]["id"], f.payment_payload(54100),
        make_permittee_headers(setup["permittee"]["id"])), 201)
    assert paid["bill_status"] == "PAID"
    assert paid["amount_paid_cents"] == 54100

    settled = get_permittee(setup["permittee"]["id"])
    assert settled["outstanding_balance_cents"] == 0
    assert settled["permittee_status"] == "IN_GOOD_STANDING"
    restored = get_permit(setup["permit"]["id"])
    assert restored["account_status"] == "CURRENT"
    assert restored["permit_status"] == "ISSUED"
    assert restored["suspension_reason"] is None
    assert get_aoi(setup["aoi"]["id"])["aoi_status"] == "ISSUED", (
        "a paid preliminary bill does not close an instruction that never reached BILLED")


def test_the_clock_belongs_to_the_system_admin_alone_and_it_is_all_the_admin_holds():
    """The exclusivity runs both ways. Each of the four operational roles is refused the clock, and the
    SystemAdmin is refused everything else — not only a write but a plain collection read and a plain
    single-resource read, which is exactly what holding no domain authority means. The admin's own set
    is proven to have landed without reading the clock back, because the endpoint returns an empty data
    object: a retreat of one second from the new instant is refused as non-monotonic, though the very
    same instant would have been a legal forward jump a moment earlier.

    PRD 2.1: "A `SystemAdmin` exists solely to drive the service's logical clock and holds no business
    authority whatsoever."
    PRD 2.5: "It maintains a **logical clock**, an ISO 8601 UTC instant that begins at exactly
    `2026-08-01T00:00:00Z` at server start and thereafter moves only when a `SystemAdmin` sets it."
    PRD 2.5: "The setting payload carries a single field, `current_utc`, holding the new instant; the
    requested value must be strictly after the present logical clock value, and a value equal to or
    earlier than the present one is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."
    PRD 2.5: "A successful clock set returns 200 with an empty `data` object."
    PRD 2.5: "Everything date-derived in this specification reads the logical clock: the calendar date
    on which a bill becomes due, the `effective_date` stamped on a decision when it takes effect, and
    each allotment's `current_grazing_year`, which is the calendar year (in UTC) of the logical clock at
    the moment of evaluation."
    PRD 2.6: "**Identity and role** — `ERR_UNAUTHORIZED`, HTTP 403, on every operation without
    exception."
    PRD 2.6: "**Clock monotonicity** — `ERR_CLOCK_NOT_MONOTONIC`, HTTP 422, on the clock-setting
    operation, as described in §2.5."
    PRD 3.1: "Its `current_grazing_year` is set to the calendar year of the logical clock."
    PRD 4: "Throughout the table, "all four operational roles" means
    `Permittee`, `RangeSpecialist`, `AuthorizedOfficer` and `AppealsAdjudicator`; `SystemAdmin` holds no
    domain authority and may call only the clock endpoint."

    Design: Corner/rbac/corner_system_admin_holds_the_clock_and_every_other_call_is_rejected
    """
    rancher = create_permittee(name="Clock Probe Ranch",
                              contact_email="clock.probe.qb181@example.com")

    # Strictly forward of every position this module has already reached, so a business role that
    # wrongly accepted it would actually move the clock rather than fail on monotonicity.
    target = "2027-02-01T00:00:00Z"
    for headers in (make_officer_headers(),
                    make_specialist_headers(),
                    make_permittee_headers(rancher["id"]),
                    make_adjudicator_headers()):
        validate_error(api_client.set_clock(f.clock_payload(target), headers),
                       ApiErrorId.ERR_UNAUTHORIZED, 403)

    admin = make_system_admin_headers()
    validate_error(api_client.create_allotment(
        f.allotment_payload(name="Admin Authored Allotment", admin_unit_code="QB-181", acres=3000,
                            total_permitted_aums=100, required_pasture_rotation_count=1), admin),
        ApiErrorId.ERR_UNAUTHORIZED, 403)
    refused_rows, refused_meta = validate_paginated(api_client.list_allotments(
        make_officer_headers(), {"admin_unit_code": "QB-181", "limit": 100}))
    assert refused_meta["total_count"] == 0, "the refused creation persisted nothing"
    assert refused_rows == []

    # An empty shared-operations list means the admin holds not even a read.
    validate_error(api_client.list_allotments(admin), ApiErrorId.ERR_UNAUTHORIZED, 403)
    validate_error(api_client.get_permittee(rancher["id"], admin),
                   ApiErrorId.ERR_UNAUTHORIZED, 403)

    assert set_clock(target) == {}, "a successful clock set returns an empty data object"

    # Nothing reads the clock back, so the proof that the set landed is that a one-second retreat from
    # the new instant is now refused, where it would have been a legal forward jump a moment earlier.
    validate_error(api_client.set_clock(f.clock_payload("2027-01-31T23:59:59Z"), admin),
                   ApiErrorId.ERR_CLOCK_NOT_MONOTONIC, 422)

    after = create_allotment(admin_unit_code="QB-182", total_permitted_aums=100, acres=3000,
                             required_pasture_rotation_count=1)
    assert after["current_grazing_year"] == 2027, "the calendar year of the logical clock"
