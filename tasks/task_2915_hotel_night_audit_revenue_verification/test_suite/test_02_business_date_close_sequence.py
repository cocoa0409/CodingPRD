"""The operating day's close sequence and the state machines around it.

Covers PRD section 3.8 (the five close-sequence steps, the revenue report, the
reopen and the month-end tie-out), PRD section 2.4 (the `version` that
increments on every mutation including server-side re-derivation) and PRD
section 2.12 (the order in which competing refusals are decided).
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_calendar_date,
    assert_empty,
    assert_fields,
    assert_int,
    assert_is_instant,
    assert_money,
    assert_money_fields,
    assert_null_fields,
    assert_row_count,
    single,
)
from test_helpers.test_users import (
    AUDITOR,
    CONTROLLER,
    FRONT_DESK,
    REVENUE_MANAGER,
    make_outlet_manager_headers,
)


def test_the_close_spine_walks_open_to_archived_one_version_per_hop(api):
    """Every hop of the declared spine moves the status once and the version once.

    PRD section 3.8 orders the five steps OPEN, ROOM_POSTING, CHARGES_SEALED,
    SETTLEMENT_REVIEW, BALANCED and CLOSED, and PRD section 3.9 archives a closed day
    through a passing period tie-out. PRD section 2.4 makes each of those a single
    mutation, so the day's `version` rises by exactly one per hop from the 1 it was
    born with. The derived statistics of PRD section 3.8 follow the room-and-tax pass,
    and the period's retention horizon of PRD section 3.9 is stamped on the way out.

    Design: Corner/state_machines/state_valid_transition_full_close_spine_walks_open_to_archived
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    period_id = bd["accounting_period_id"]
    assert_fields(bd, {"status": "OPEN"})
    assert_int(bd["version"], 1, "version at creation")
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-SPINE",
        guest_name="Rae Nolan",
        room_number="2101",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])

    posted = fx.post_room_and_tax(api, bd["id"])
    assert_fields(posted, {"status": "ROOM_POSTING"})
    assert_int(posted["version"], 2, "version after post-room-and-tax")
    assert_int(posted["rooms_occupied_count"], 1, "rooms_occupied_count")
    assert_int(posted["rooms_available_count"], 96, "rooms_available_count")
    assert_money_fields(
        posted,
        {
            "room_night_revenue_amount": 200.00,
            "tax_revenue_amount": 17.75,
            "other_room_revenue_amount": 0.00,
            "total_revenue_amount": 217.75,
            "occupancy_pct": 1.04,
            "adr_amount": 200.00,
            "revpar_amount": 2.08,
        },
    )

    sealed = fx.seal_charges(api, bd["id"])
    assert_fields(sealed, {"status": "CHARGES_SEALED"})
    assert_int(sealed["version"], 3, "version after seal-charges")
    rows = fx.list_postings(api, business_date_id=bd["id"])
    assert_row_count(rows, 2, "journal lines of the day")
    room = single([r for r in rows if r["charge_type"] == "ROOM"], "ROOM line")
    assert_int(room["night_index"], 1, "night_index")
    assert_money(room["amount"], 200.00, "the room night")
    tax = single(
        [r for r in rows if r["charge_type"] == "OCCUPANCY_TAX"], "OCCUPANCY_TAX line"
    )
    assert_money(tax["amount"], 17.75, "the provisional occupancy tax")
    assert_empty(
        [r for r in rows if r["charge_type"] == "TAX_TRUE_UP"],
        "TAX_TRUE_UP lines, since the final tax equals the provisional one",
    )

    verified = fx.verify_settlements(api, bd["id"])
    assert_fields(verified, {"status": "SETTLEMENT_REVIEW"})
    assert_int(verified["version"], 4, "version after verify-settlements")

    balanced = fx.balance_business_date(api, bd["id"])
    assert_fields(balanced, {"status": "BALANCED"})
    assert_int(balanced["version"], 5, "version after balance")

    report = fx.create_report(api, bd["id"], ["Controller", "RevenueManager"])
    fx.distribute_report(api, report["id"])

    before_close = fx.business_date_version(api, bd["id"])
    closed = fx.close_business_date(api, bd["id"])
    assert_fields(closed, {"status": "CLOSED"})
    assert_int(closed["version"], before_close + 1, "version after close")

    period = fx.tie_out_period(api, period_id, 217.75)
    assert_fields(period, {"status": "TIED_OUT"})
    assert_money_fields(
        period,
        {
            "subsystem_total_amount": 217.75,
            "gl_control_total_amount": 217.75,
            "tie_out_variance_amount": 0.00,
        },
    )
    assert_int(period["tie_out_attempt_count"], 0, "tie_out_attempt_count")
    assert_is_instant(period["tied_out_at"], "tied_out_at")
    assert_calendar_date(
        period["audit_trail_retention_until_date"],
        "2033-08-31",
        "audit_trail_retention_until_date",
    )

    archived = fx.read_business_date(api, bd["id"])
    assert_fields(archived, {"status": "ARCHIVED"})
    assert_int(archived["version"], closed["version"] + 1, "version after archival")
    assert_fields(fx.read_report(api, report["id"]), {"status": "DISTRIBUTED"})

    validate_error(
        api.create_journal_posting(
            f.build_journal_posting_payload(
                bd["id"], "MISC_CHARGE", 10.00, folio_id=folio["id"]
            ),
            AUDITOR,
        ),
        E.ERR_BUSINESS_DATE_ARCHIVED,
    )
    validate_error(
        api.tie_out_period(period_id, f.build_tie_out_payload(217.75), CONTROLLER),
        E.ERR_PERIOD_NOT_TIEABLE,
    )
    assert_int(
        fx.read_period(api, period_id)["tie_out_attempt_count"],
        0,
        "tie_out_attempt_count after the refused repeat",
    )
    validate_error(
        api.reopen_business_date(bd["id"], CONTROLLER), E.ERR_BUSINESS_DATE_ARCHIVED
    )


def test_every_declared_dimension_starts_where_the_contract_says_it_does(api):
    """Eleven dimensions across nine entities are read straight after creation.

    PRD sections 3.2 to 3.8 each declare a birth state: an operating day opens `OPEN`
    with `reopen_count` 0; a guest account is born `RESERVED` on the stay dimension and
    `UNSETTLED` on the settlement dimension at the same time; a card authorization is
    born `APPROVED` with `follow_up_status` `NOT_REQUIRED`; filed paperwork begins
    `PENDING`; a check opens `OPEN`; a shift batch is born `DECLARED` with null system
    and variance figures; an allowance begins `DRAFT`; and a revenue report is created
    `DRAFT`. PRD section 3.1 mints the accounting period implicitly from the month's
    first operating day, and it too starts `OPEN`.

    Design: Corner/state_machines/state_initial_state_every_machine_starts_where_it_is_declared_to
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    lounge = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd1 = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    period_id = bd1["accounting_period_id"]
    bd2 = fx.create_business_date(api, prop["id"], "2026-08-02", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd2["id"],
        confirmation_code="CF-INIT",
        guest_name="Sol Vega",
        room_number="2201",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CREDIT_CARD",
        scheduled_checkout_at="2026-08-03T11:00:00.000Z",
    )
    auth = fx.create_card_authorization(
        api, folio["id"], 400.00, "2026-08-01T09:00:00.000Z"
    )
    document = fx.create_authorization_document(
        api,
        prop["id"],
        doc_type="RATE_OVERRIDE",
        authorized_by_name="T. Okafor",
        document_reference="DOC-INIT-1",
        valid_from_date="2026-08-01",
        valid_to_date="2026-08-31",
        folio_id=folio["id"],
        authorized_rate_amount=200.00,
    )
    ticket = fx.create_outlet_ticket(
        api,
        lounge["id"],
        bd2["id"],
        128.00,
        ticket_number="T-INIT-1",
        settlement_type="CASH",
        opened_at="2026-08-02T18:00:00.000Z",
    )
    batch = fx.create_settlement_batch(
        api,
        bd2["id"],
        lounge["id"],
        160.48,
        shift_start_at="2026-08-02T14:00:00.000Z",
        shift_end_at="2026-08-02T22:00:00.000Z",
    )
    allowance = fx.create_allowance(
        api,
        folio["id"],
        bd2["id"],
        40.00,
        headers=AUDITOR,
        reason_code="GUEST_DISPUTE",
        narrative="Noise complaint.",
    )
    fx.drive_to_settlement_review(api, bd1["id"])

    report = validate_success(
        api.create_revenue_report(
            f.build_revenue_report_payload(
                bd1["id"], fx.business_date_version(api, bd1["id"]), ["Controller"]
            ),
            REVENUE_MANAGER,
        ),
        201,
    )
    assert_fields(report, {"status": "DRAFT"})
    assert_null_fields(report, ["distributed_at"])

    day2 = fx.read_business_date(api, bd2["id"])
    assert_fields(day2, {"status": "OPEN"})
    assert_int(day2["reopen_count"], 0, "reopen_count")

    account = fx.read_folio(api, folio["id"])
    assert_fields(
        account, {"stay_status": "RESERVED", "settlement_status": "UNSETTLED"}
    )

    held = fx.read_card_authorization(api, auth["id"])
    assert_fields(held, {"status": "APPROVED", "follow_up_status": "NOT_REQUIRED"})
    assert_null_fields(held, ["decline_code", "captured_amount", "resolved_by_user_id"])

    paperwork = fx.read_document(api, document["id"])
    assert_fields(paperwork, {"status": "PENDING"})
    assert_null_fields(paperwork, ["reviewed_by_user_id", "reviewed_at"])

    check = fx.read_ticket(api, ticket["id"])
    assert_fields(check, {"status": "OPEN"})
    assert_null_fields(check, ["transmitted_at", "closed_at", "voided_at"])

    drawer = fx.read_batch(api, batch["id"])
    assert_fields(drawer, {"status": "DECLARED"})
    assert_int(drawer["recount_round"], 0, "recount_round")
    assert_null_fields(drawer, ["system_amount", "variance_amount", "accepted_by_user_id"])

    rebate = fx.read_allowance(api, allowance["id"])
    assert_fields(rebate, {"status": "DRAFT", "required_approval_role": "NightAuditor"})
    assert_int(rebate["revision_round"], 0, "revision_round")
    assert_null_fields(
        rebate,
        ["approved_amount", "approved_by_user_id", "approved_at", "submitted_at"],
    )

    period = fx.read_period(api, period_id)
    assert_fields(period, {"status": "OPEN"})
    assert_int(period["tie_out_attempt_count"], 0, "tie_out_attempt_count")


def test_the_close_sequence_cannot_be_entered_in_the_middle(api):
    """Each out-of-order step carries its own refusal and none of them moves the day.

    PRD section 3.8 gates every close-sequence step on its own starting status:
    sealing demands `ROOM_POSTING`, verification demands `CHARGES_SEALED`, balancing
    demands `SETTLEMENT_REVIEW` or `REOPENED`, closing demands `BALANCED`, and PRD
    section 3.8 lets only a `CLOSED` day reopen. PRD section 2.4 leaves the day's
    `version` untouched by a refused call, so five rejections in a row leave it at the
    1 it was born with and the first legal step still works.

    Design: Corner/state_machines/state_invalid_transitions_close_sequence_steps_refuse_to_run_out_of_order
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)

    validate_error(api.seal_charges(bd["id"], AUDITOR), E.ERR_DATE_NOT_READY_TO_SEAL)
    validate_error(
        api.verify_settlements(bd["id"], AUDITOR), E.ERR_DATE_NOT_READY_TO_VERIFY
    )
    validate_error(
        api.balance_business_date(bd["id"], AUDITOR), E.ERR_DATE_NOT_READY_TO_BALANCE
    )
    validate_error(api.close_business_date(bd["id"], AUDITOR), E.ERR_DATE_NOT_BALANCED)
    validate_error(api.reopen_business_date(bd["id"], CONTROLLER), E.ERR_DATE_NOT_CLOSED)

    still_open = fx.read_business_date(api, bd["id"])
    assert_fields(still_open, {"status": "OPEN"})
    assert_int(still_open["version"], 1, "version after five refused triggers")

    posted = fx.post_room_and_tax(api, bd["id"])
    assert_fields(posted, {"status": "ROOM_POSTING"})
    assert_int(posted["version"], 2, "version after the first legal step")


def test_a_second_room_and_tax_pass_is_refused_and_double_posts_nothing(api):
    """The guard is on the day's status, so the run cannot be replayed onto itself.

    PRD section 3.8 drives the room-and-tax pass `OPEN → ROOM_POSTING` and refuses a
    day that is not `OPEN` with ERR_BUSINESS_DATE_NOT_OPEN (HTTP 409). Because the
    refusal happens before anything is written, the account still carries exactly the
    one room night and its tax that the first pass posted — 217.75, not 435.50 — and
    PRD section 2.4 leaves the day at the version the first pass produced. The same
    guard shape repeats one hop later on sealing.

    Design: Corner/state_machines/state_idempotency_second_post_room_and_tax_is_refused_and_posts_nothing
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-IDEM",
        guest_name="Nia Roche",
        room_number="2301",
        nights_count=2,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-03T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd["id"])

    validate_error(
        api.post_room_and_tax(bd["id"], AUDITOR), E.ERR_BUSINESS_DATE_NOT_OPEN
    )

    rows = fx.list_postings(api, folio_id=folio["id"])
    assert_row_count(rows, 2, "journal lines of the account")
    room = single([r for r in rows if r["charge_type"] == "ROOM"], "ROOM line")
    assert_money(room["amount"], 200.00, "the room night")
    assert_int(room["night_index"], 1, "night_index")
    tax = single(
        [r for r in rows if r["charge_type"] == "OCCUPANCY_TAX"], "OCCUPANCY_TAX line"
    )
    assert_money(tax["amount"], 17.75, "the occupancy tax")

    account = fx.read_folio(api, folio["id"])
    assert_money_fields(
        account, {"charges_total_amount": 217.75, "balance_amount": 217.75}
    )

    day = fx.read_business_date(api, bd["id"])
    assert_int(day["version"], 2, "version after the refused replay")
    assert_money(day["room_night_revenue_amount"], 200.00, "room_night_revenue_amount")

    sealed = fx.seal_charges(api, bd["id"])
    assert_fields(sealed, {"status": "CHARGES_SEALED"})
    validate_error(api.seal_charges(bd["id"], AUDITOR), E.ERR_DATE_NOT_READY_TO_SEAL)


def test_a_cancelled_reservation_accepts_no_further_stay_transition(api):
    """CANCELLED is terminal on the stay dimension and is never converted to a no-show.

    PRD section 3.5 lets a reservation leave `RESERVED` by cancellation only when its
    `balance_amount` is exactly 0.00, and both arrival and a second cancellation then
    demand `RESERVED` on pain of ERR_FOLIO_NOT_RESERVED (HTTP 409) while departure
    demands `IN_HOUSE` on pain of ERR_FOLIO_NOT_IN_HOUSE. PRD section 3.5 also states
    that a cancelled account is skipped by every later room-and-tax run, so the no-show
    conversion of PRD section 3.3 passes it by and it feeds no statistic.

    Design: Corner/state_machines/state_terminal_state_lockdown_cancelled_folio_accepts_nothing_further
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-TERM",
        guest_name="Ivo Baptiste",
        room_number="2401",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    validate_success(api.cancel_folio(folio["id"], FRONT_DESK))

    validate_error(api.check_in(folio["id"], FRONT_DESK), E.ERR_FOLIO_NOT_RESERVED)
    validate_error(api.cancel_folio(folio["id"], FRONT_DESK), E.ERR_FOLIO_NOT_RESERVED)
    validate_error(
        api.check_out(folio["id"], f.build_check_out_payload(bd["id"]), FRONT_DESK),
        E.ERR_FOLIO_NOT_IN_HOUSE,
    )

    account = fx.read_folio(api, folio["id"])
    assert_fields(
        account, {"stay_status": "CANCELLED", "settlement_status": "UNSETTLED"}
    )
    assert_int(account["version"], 2, "version after the cancellation alone")

    day = fx.post_room_and_tax(api, bd["id"])
    assert_fields(day, {"status": "ROOM_POSTING"})
    assert_fields(fx.read_folio(api, folio["id"]), {"stay_status": "CANCELLED"})
    assert_int(day["rooms_occupied_count"], 0, "rooms_occupied_count")
    assert_money(day["total_revenue_amount"], 0.00, "total_revenue_amount")


def test_closing_the_day_demands_a_distributed_report_not_merely_a_drafted_one(api):
    """The same close call flips from refused to accepted purely on the report's status.

    PRD section 3.8 refuses a `BALANCED` day with no `DISTRIBUTED` report of its own
    using ERR_REPORT_NOT_DISTRIBUTED (HTTP 409) — the numbers must have been published
    to somebody first — and PRD section 2.4 leaves the day's version untouched by the
    refusal. Distribution itself demands `DRAFT` on pain of ERR_REPORT_NOT_DRAFT
    (HTTP 409) and refuses an empty `recipient_role_list` with
    ERR_DISTRIBUTION_LIST_EMPTY (HTTP 422), so no report can satisfy the close
    precondition without an audience.

    Design: Corner/state_machines/state_precondition_enforcement_close_demands_a_distributed_report
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    fx.drive_to_settlement_review(api, bd["id"])
    fx.balance_business_date(api, bd["id"])
    report = fx.create_report(api, bd["id"], ["Controller"])
    assert_fields(report, {"status": "DRAFT"})

    before = fx.read_business_date(api, bd["id"])
    validate_error(
        api.close_business_date(bd["id"], AUDITOR), E.ERR_REPORT_NOT_DISTRIBUTED
    )
    after = fx.read_business_date(api, bd["id"])
    assert_fields(after, {"status": "BALANCED"})
    assert_int(after["version"], before["version"], "version after the refused close")

    distributed = fx.distribute_report(api, report["id"])
    assert_fields(distributed, {"status": "DISTRIBUTED"})
    assert_is_instant(distributed["distributed_at"], "distributed_at")

    closed = fx.close_business_date(api, bd["id"])
    assert_fields(closed, {"status": "CLOSED"})
    assert_int(closed["version"], after["version"] + 1, "version after the close")

    validate_error(
        api.distribute_revenue_report(report["id"], REVENUE_MANAGER),
        E.ERR_REPORT_NOT_DRAFT,
    )

    other = fx.create_business_date(api, prop["id"], "2026-08-02", out_of_order_room_count=4)
    fx.drive_to_settlement_review(api, other["id"])
    fx.balance_business_date(api, other["id"])
    other_report = fx.create_report(api, other["id"], ["Controller"])
    validate_error(
        api.distribute_revenue_report(
            other_report["id"], REVENUE_MANAGER, {"recipient_role_list": []}
        ),
        E.ERR_DISTRIBUTION_LIST_EMPTY,
    )
    assert_fields(fx.read_report(api, other_report["id"]), {"status": "DRAFT"})


def test_one_decline_fires_three_side_effects_on_three_different_rows(api):
    """The parallel dimension, the account's hold and the day's counter all move at once.

    PRD section 3.7 declares that recording a decline drives the authorization
    `APPROVED → DECLINED` and, beyond the status change, forces `follow_up_status` from
    `NOT_REQUIRED` to `PENDING`, sets the owning account's `settlement_hold` true — which
    blocks its departure with ERR_DECLINED_AUTH_UNRESOLVED (HTTP 409) — and recomputes
    the day's `declined_authorization_count` upwards, which PRD section 3.8 then turns
    into a refusal to balance. Declining posts no money at all, and because the status
    dimension really left `APPROVED`, a capture is refused with
    ERR_AUTHORIZATION_NOT_APPROVED.

    Design: Corner/state_machines/state_side_effect_execution_decline_holds_the_folio_and_blocks_the_date
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-SIDE",
        guest_name="Kit Amaro",
        room_number="2501",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CREDIT_CARD",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    auth = fx.create_card_authorization(
        api, folio["id"], 500.00, "2026-08-01T08:00:00.000Z"
    )
    fx.post_room_and_tax(api, bd["id"])

    declined = validate_success(
        api.decline_card_authorization(
            auth["id"], f.build_decline_payload("INSUFFICIENT_FUNDS"), FRONT_DESK
        )
    )
    assert_fields(
        declined,
        {
            "status": "DECLINED",
            "decline_code": "INSUFFICIENT_FUNDS",
            "follow_up_status": "PENDING",
        },
    )

    assert_fields(fx.read_folio(api, folio["id"]), {"settlement_hold": True})
    assert_int(
        fx.read_business_date(api, bd["id"])["declined_authorization_count"],
        1,
        "declined_authorization_count",
    )
    assert_row_count(
        fx.list_postings(api, folio_id=folio["id"]),
        2,
        "journal lines of the account, because declining posts no money",
    )

    validate_error(
        api.check_out(folio["id"], f.build_check_out_payload(bd["id"]), FRONT_DESK),
        E.ERR_DECLINED_AUTH_UNRESOLVED,
    )
    validate_error(
        api.capture_card_authorization(
            auth["id"], f.build_capture_payload(100.00, bd["id"]), AUDITOR
        ),
        E.ERR_AUTHORIZATION_NOT_APPROVED,
    )

    fx.seal_charges(api, bd["id"])
    reviewed = fx.verify_settlements(api, bd["id"])
    assert_fields(reviewed, {"status": "SETTLEMENT_REVIEW"})
    validate_error(
        api.balance_business_date(bd["id"], AUDITOR), E.ERR_DECLINED_AUTH_UNRESOLVED
    )
    stuck = fx.read_business_date(api, bd["id"])
    assert_fields(stuck, {"status": "SETTLEMENT_REVIEW"})
    assert_int(stuck["version"], reviewed["version"], "version after the refused balance")


def test_the_follow_up_dimension_walks_on_while_the_status_stays_declined(api):
    """PENDING to CONTACTED to RESOLVED clears the hold; `status` never leaves DECLINED.

    PRD section 3.7 makes the two dimensions of a card authorization genuinely
    independent: `CONTACT` drives `PENDING → CONTACTED` and stores the note while
    leaving the account held; `RESOLVE` drives `CONTACTED → RESOLVED` but only once the
    account carries at least one `PAYMENT` line, else
    ERR_FOLLOW_UP_NO_REPLACEMENT_TENDER (HTTP 409); and once resolved the hold clears,
    the day's `declined_authorization_count` falls and the day can balance. `RESOLVED`
    is terminal on its own dimension, so a further `ESCALATE` is refused with
    ERR_FOLLOW_UP_NOT_CONTACTED, and `status` reads `DECLINED` throughout.

    Design: Corner/state_machines/state_parallel_follow_up_dimension_advances_while_status_stays_declined
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-PARA",
        guest_name="Mira Devi",
        room_number="2601",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CREDIT_CARD",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    auth = fx.create_card_authorization(
        api, folio["id"], 500.00, "2026-08-01T08:00:00.000Z"
    )
    fx.post_room_and_tax(api, bd["id"])
    validate_success(
        api.decline_card_authorization(
            auth["id"], f.build_decline_payload("INSUFFICIENT_FUNDS"), FRONT_DESK
        )
    )
    validate_success(
        api.follow_up_card_authorization(
            auth["id"],
            f.build_follow_up_payload("CONTACT", follow_up_note="Guest reached by phone."),
            FRONT_DESK,
        )
    )

    validate_error(
        api.follow_up_card_authorization(
            auth["id"], f.build_follow_up_payload("RESOLVE"), FRONT_DESK
        ),
        E.ERR_FOLLOW_UP_NO_REPLACEMENT_TENDER,
    )
    contacted = fx.read_card_authorization(api, auth["id"])
    assert_fields(
        contacted,
        {
            "follow_up_status": "CONTACTED",
            "follow_up_note": "Guest reached by phone.",
            "status": "DECLINED",
        },
    )

    get_success_data(
        api.post_payment(
            folio["id"], f.build_payment_payload(bd["id"], 217.75), FRONT_DESK
        )
    )
    paid = fx.read_folio(api, folio["id"])
    assert_money(paid["balance_amount"], 0.00, "balance_amount")
    assert_fields(paid, {"settlement_status": "SETTLED", "settlement_hold": True})

    resolved = validate_success(
        api.follow_up_card_authorization(
            auth["id"], f.build_follow_up_payload("RESOLVE"), FRONT_DESK
        )
    )
    assert_fields(resolved, {"follow_up_status": "RESOLVED", "status": "DECLINED"})
    assert_fields(fx.read_folio(api, folio["id"]), {"settlement_hold": False})
    assert_int(
        fx.read_business_date(api, bd["id"])["declined_authorization_count"],
        0,
        "declined_authorization_count",
    )

    fx.seal_charges(api, bd["id"])
    fx.verify_settlements(api, bd["id"])
    balanced = fx.balance_business_date(api, bd["id"])
    assert_fields(balanced, {"status": "BALANCED"})

    validate_error(
        api.follow_up_card_authorization(
            auth["id"], f.build_follow_up_payload("ESCALATE"), FRONT_DESK
        ),
        E.ERR_FOLLOW_UP_NOT_CONTACTED,
    )
    assert_fields(
        fx.read_card_authorization(api, auth["id"]),
        {"follow_up_status": "RESOLVED", "status": "DECLINED"},
    )


def test_closing_a_room_charge_check_charges_the_account_it_names(api):
    """The check's computed total, not its gross, crosses into the guest account.

    PRD section 3.4 composes a check as gross, then service charge, then a taxable base
    of the two, then tax on that base, then the large-party discount — 200.00 grossing
    36.00 of service on a 236.00 base taxed 14.75, with no discount because the base is
    under the 472.00 threshold, for a total of 250.75. PRD section 3.4 then appends an
    `OUTLET_TRANSFER` line of exactly that total with `source_channel` `OUTLET_POS`,
    re-derives the named account's money by PRD section 3.7, and raises the day's
    `closed_outlet_ticket_count` and `outlet_revenue_amount` while leaving room revenue
    alone. A second close is refused with ERR_TICKET_NOT_OPEN, and PRD section 2.10
    keeps one outlet's manager out of another outlet's checks.

    Design: Corner/state_machines/state_cross_entity_closing_a_room_charge_ticket_charges_the_folio
    """
    fx.set_clock(api, "2026-08-01T20:15:00.000Z")
    prop = fx.create_property(api)
    grill = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="GRILL",
        outlet_name="Harbor Grill",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    lounge = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-XE1",
        guest_name="Xan Duval",
        room_number="2701",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
        credit_limit_amount=900.00,
    )
    fx.check_in(api, folio["id"])
    ticket = fx.create_outlet_ticket(
        api,
        grill["id"],
        bd["id"],
        200.00,
        ticket_number="T-XE-1",
        settlement_type="ROOM_CHARGE",
        opened_at="2026-08-01T19:00:00.000Z",
        room_charge_folio_id=folio["id"],
    )

    closed = validate_success(
        api.close_outlet_ticket(
            ticket["id"],
            make_outlet_manager_headers(grill["id"]),
            f.build_close_ticket_payload("2026-08-01T20:15:00.000Z"),
        )
    )
    assert_fields(closed, {"status": "CLOSED"})
    assert_is_instant(closed["closed_at"], "closed_at")
    assert_money_fields(
        closed,
        {
            "service_charge_amount": 36.00,
            "taxable_base_amount": 236.00,
            "tax_amount": 14.75,
            "large_party_discount_amount": 0.00,
            "total_amount": 250.75,
        },
    )

    transfer = single(
        fx.list_postings(api, outlet_ticket_id=ticket["id"]), "OUTLET_TRANSFER line"
    )
    assert_fields(
        transfer,
        {
            "charge_type": "OUTLET_TRANSFER",
            "folio_id": folio["id"],
            "source_channel": "OUTLET_POS",
        },
    )
    assert_money(transfer["amount"], 250.75, "the transfer")

    account = fx.read_folio(api, folio["id"])
    assert_money_fields(
        account,
        {
            "charges_total_amount": 250.75,
            "credits_total_amount": 0.00,
            "balance_amount": 250.75,
        },
    )
    assert_fields(account, {"settlement_status": "UNSETTLED"})

    day = fx.read_business_date(api, bd["id"])
    assert_int(day["closed_outlet_ticket_count"], 1, "closed_outlet_ticket_count")
    assert_money_fields(
        day, {"outlet_revenue_amount": 250.75, "room_night_revenue_amount": 0.00}
    )

    validate_error(
        api.close_outlet_ticket(
            ticket["id"],
            make_outlet_manager_headers(grill["id"]),
            f.build_close_ticket_payload("2026-08-01T20:15:00.000Z"),
        ),
        E.ERR_TICKET_NOT_OPEN,
    )
    assert_money(
        fx.read_folio(api, folio["id"])["balance_amount"], 250.75, "balance_amount"
    )

    other = fx.create_outlet_ticket(
        api,
        grill["id"],
        bd["id"],
        120.00,
        ticket_number="T-XE-2",
        settlement_type="CASH",
        opened_at="2026-08-01T19:30:00.000Z",
    )
    validate_error(
        api.close_outlet_ticket(
            other["id"],
            make_outlet_manager_headers(lounge["id"]),
            f.build_close_ticket_payload("2026-08-01T20:15:00.000Z"),
        ),
        E.ERR_OUTLET_SCOPE_VIOLATION,
    )
    assert_fields(fx.read_ticket(api, other["id"]), {"status": "OPEN"})


def test_both_legs_of_a_deposit_movement_return_the_control_total_to_zero(api):
    """A one-sided leg pushes the control figure off zero; the matching leg cancels it.

    PRD section 3.8 defines the day's `ledger_control_amount` as the rounded sum of
    every `LEDGER_TRANSFER` and `DEPOSIT_APPLIED` line of the day, counting both the
    guest-account side and the ledger-account side, and refuses to balance a day whose
    control figure is not exactly 0.00 with ERR_LEDGERS_OUT_OF_BALANCE (HTTP 409). PRD
    section 3.7 derives a ledger account's `current_balance_amount` from its own
    postings rather than from anything the client stores, and makes a reversal of the
    guest-account leg push the control figure off zero again while leaving the ledger
    account alone — the figure tracks live postings, not a running counter.

    Design: Corner/state_machines/state_ledger_sync_deposit_application_keeps_the_control_total_at_zero
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    deposit_account = fx.create_ledger_account(
        api,
        prop["id"],
        "ADVANCE_DEPOSIT",
        account_code="AD-100",
        gl_account_code="2340",
        opening_balance_amount=0.00,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-LS1",
        guest_name="Yara Nunes",
        room_number="2801",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
        credit_limit_amount=900.00,
    )
    fx.check_in(api, folio["id"])
    fx.post_journal_line(
        api,
        bd["id"],
        "MISC_CHARGE",
        300.00,
        folio_id=folio["id"],
        memo="Banquet deposit consumed",
    )
    folio_leg = fx.post_journal_line(
        api,
        bd["id"],
        "DEPOSIT_APPLIED",
        -300.00,
        folio_id=folio["id"],
        memo="Apply advance deposit - folio leg",
    )
    assert_money(
        fx.read_business_date(api, bd["id"])["ledger_control_amount"],
        -300.00,
        "ledger_control_amount with only the guest-account leg posted",
    )

    validate_success(
        api.create_journal_posting(
            f.build_journal_posting_payload(
                bd["id"],
                "DEPOSIT_APPLIED",
                300.00,
                ledger_account_id=deposit_account["id"],
                memo="Apply advance deposit - ledger leg",
            ),
            AUDITOR,
        ),
        201,
    )
    assert_money(
        fx.read_business_date(api, bd["id"])["ledger_control_amount"],
        0.00,
        "ledger_control_amount once both legs have landed",
    )
    assert_money(
        fx.read_ledger_account(api, deposit_account["id"])["current_balance_amount"],
        300.00,
        "current_balance_amount",
    )

    account = fx.read_folio(api, folio["id"])
    assert_money_fields(
        account,
        {
            "charges_total_amount": 300.00,
            "credits_total_amount": -300.00,
            "balance_amount": 0.00,
        },
    )
    assert_fields(account, {"settlement_status": "SETTLED"})

    assert_row_count(
        fx.list_postings(api, ledger_account_id=deposit_account["id"]),
        1,
        "lines indexed to the ledger account",
    )
    assert_row_count(
        fx.list_postings(api, folio_id=folio["id"]),
        2,
        "lines indexed to the guest account",
    )

    validate_success(api.reverse_journal_posting(folio_leg["id"], CONTROLLER), 201)
    assert_money(
        fx.read_business_date(api, bd["id"])["ledger_control_amount"],
        300.00,
        "ledger_control_amount after the guest-account leg is reversed",
    )
    assert_money(
        fx.read_ledger_account(api, deposit_account["id"])["current_balance_amount"],
        300.00,
        "current_balance_amount, untouched by the guest-side reversal",
    )

    fx.post_room_and_tax(api, bd["id"])
    fx.seal_charges(api, bd["id"])
    fx.verify_settlements(api, bd["id"])
    validate_error(
        api.balance_business_date(bd["id"], AUDITOR), E.ERR_LEDGERS_OUT_OF_BALANCE
    )
    assert_fields(fx.read_business_date(api, bd["id"]), {"status": "SETTLEMENT_REVIEW"})



def test_reopening_supersedes_the_live_report_and_leaves_the_dead_one_alone(api):
    """The cascade is conditional on the child's own status, and terminal children are skipped.

    PRD section 3.8 states that a reopen raises `reopen_count`, sets every `DRAFT` or
    `DISTRIBUTED` report of the day to `SUPERSEDED`, and recomputes the period's
    `subsystem_total_amount` so the day no longer contributes. PRD section 2.9 makes
    `SUPERSEDED` terminal, so a report already superseded by a newer one is not touched
    again and its `version` does not move. PRD section 3.8 then requires the reopened day
    to be re-balanced and to acquire a fresh distributed report before it may close, and
    PRD section 3.9 refuses a tie-out while any day of the period is not `CLOSED` or
    `ARCHIVED`.

    Design: Corner/state_machines/state_conditional_cascade_reopen_supersedes_only_live_reports
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    period_id = bd["accounting_period_id"]
    fx.drive_to_settlement_review(api, bd["id"])
    fx.balance_business_date(api, bd["id"])
    report_a = fx.create_report(api, bd["id"], ["Controller"])
    report_b = fx.create_report(api, bd["id"], ["Controller", "RevenueManager"])
    fx.distribute_report(api, report_b["id"])
    fx.close_business_date(api, bd["id"])

    dead = fx.read_report(api, report_a["id"])
    assert_fields(dead, {"status": "SUPERSEDED"})
    assert_fields(fx.read_report(api, report_b["id"]), {"status": "DISTRIBUTED"})

    reopened = validate_success(api.reopen_business_date(bd["id"], CONTROLLER))
    assert_fields(reopened, {"status": "REOPENED"})
    assert_int(reopened["reopen_count"], 1, "reopen_count")

    assert_fields(fx.read_report(api, report_b["id"]), {"status": "SUPERSEDED"})
    assert fx.read_report(api, report_a["id"]) == dead, (
        "an already-SUPERSEDED report must not be re-superseded or version-bumped, got "
        f"{fx.read_report(api, report_a['id'])!r}"
    )

    assert_money(
        fx.read_period(api, period_id)["subsystem_total_amount"],
        0.00,
        "subsystem_total_amount once the day stopped contributing",
    )
    validate_error(
        api.tie_out_period(period_id, f.build_tie_out_payload(0.00), CONTROLLER),
        E.ERR_PERIOD_HAS_OPEN_DATES,
    )

    validate_error(api.close_business_date(bd["id"], AUDITOR), E.ERR_DATE_NOT_BALANCED)
    fx.balance_business_date(api, bd["id"])
    validate_error(
        api.close_business_date(bd["id"], AUDITOR), E.ERR_REPORT_NOT_DISTRIBUTED
    )
    report_c = fx.create_report(api, bd["id"], ["Controller"])
    fx.distribute_report(api, report_c["id"])
    closed_again = fx.close_business_date(api, bd["id"])
    assert_fields(closed_again, {"status": "CLOSED"})
