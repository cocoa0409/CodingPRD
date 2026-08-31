"""Traffic dispositions, the preemption cascade and the audit checkpoint."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_rebate_entry,
    assert_station_posture,
    charge_order,
    hourly_spots,
    list_rebates,
    preempt_spot,
    read_file_entry,
    read_order,
    read_spot,
    read_station,
    run_audit_sweep,
    set_clock,
    setup_issue_order,
    setup_station_with_two_overdue_adjustments,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TRAFFIC = TEST_USERS["traffic_scheduler_headers"]
AIRED = {"disposition": "AIRED"}


def test_prepay_spot_cannot_air_before_the_money_arrives(api):
    """PRD §3.6: "When the order's `payment_terms` are `PREPAY`, its settlement state
    must already read `PAID`, or the airing is refused with `ERR_ORDER_NOT_PAID` (HTTP
    409) — a prepay order genuinely may not run before the money arrives."
    PRD §3.6: "The transition `SCHEDULED → AIRED` stamps the spot's `aired_at` with the
    logical clock."

    Design: Corner/validations/prepay_spot_cannot_air_before_payment_and_airs_once_paid
    """
    built = setup_issue_order(
        call_sign="WPPY-TV",
        market_code="DMA-133",
        station_overrides={
            "licensee_name": "Prepay Gate Broadcasting",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1, air_date="2026-08-10"),
        accept=True,
    )
    order, advertiser, spot = built["order"], built["advertiser"], built["spots"][0]
    set_clock("2026-08-10T12:00:00Z")

    validate_error(
        api.set_spot_disposition(spot["id"], AIRED, TRAFFIC), ApiErrorId.ERR_ORDER_NOT_PAID
    )

    charge_order(order["id"], advertiser["id"], 100000)

    aired = validate_success(api.set_spot_disposition(spot["id"], AIRED, TRAFFIC))
    assert aired["status"] == "AIRED"

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["status"] == "COMPLETED", "no spot remains SCHEDULED after the airing"
    assert refreshed["first_air_at"] == "2026-08-10T12:00:00.000Z"


def test_spot_cannot_air_before_its_air_date_has_arrived(api):
    """PRD §3.6: "And the spot's `air_date` must be on or before the date portion of the
    logical clock; a spot marked aired before its date has arrived is refused with
    `ERR_SPOT_AIR_DATE_NOT_REACHED` (HTTP 409)."

    Design: Corner/validations/airing_a_spot_before_its_air_date_rejected_as_not_reached
    """
    built = setup_issue_order(
        call_sign="WEAR-TV",
        market_code="DMA-134",
        station_overrides={
            "licensee_name": "Early Air Media",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1),
        charge_amount_cents=100000,
    )
    order, advertiser, spot = built["order"], built["advertiser"], built["spots"][0]

    validate_error(
        api.set_spot_disposition(spot["id"], AIRED, TRAFFIC),
        ApiErrorId.ERR_SPOT_AIR_DATE_NOT_REACHED,
    )

    unchanged = read_spot(spot["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["aired_at"] is None

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["status"] == "ACCEPTED"
    assert refreshed["first_air_at"] is None


def test_order_auto_completes_when_the_last_scheduled_spot_airs(api):
    """PRD §3.6: "If this is the order's first airing — recognisable because
    `first_air_at` is still null — the order advances `ACCEPTED → RUNNING` and stamps
    `first_air_at` with the logical clock. If, after this airing, no spot on the order
    remains `SCHEDULED`, the order advances `RUNNING → COMPLETED`."

    Design: Corner/state_machines/order_auto_completes_when_the_last_scheduled_spot_airs
    """
    built = setup_issue_order(
        call_sign="WCMP-TV",
        market_code="DMA-110",
        station_overrides={
            "licensee_name": "Completion Media LLC",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(2, air_date="2026-08-10"),
        charge_amount_cents=200000,
    )
    order, advertiser = built["order"], built["advertiser"]
    first, second = built["spots"]
    set_clock("2026-08-10T12:00:00Z")

    validate_success(api.set_spot_disposition(first["id"], AIRED, TRAFFIC))
    midway = read_order(order["id"], advertiser["id"])
    assert midway["status"] == "RUNNING"
    assert midway["first_air_at"] == "2026-08-10T12:00:00.000Z"

    validate_success(api.set_spot_disposition(second["id"], AIRED, TRAFFIC))
    completed = read_order(order["id"], advertiser["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["gross_charge_cents"] == 200000
    assert read_spot(first["id"])["status"] == "AIRED"
    assert read_spot(second["id"])["status"] == "AIRED"


def test_spot_sold_from_a_fixed_rate_class_cannot_be_preempted(api):
    """PRD §3.6: "A spot may only be preempted when its rate class carries `preemptible`
    true; a spot sold from a fixed class is refused with
    `ERR_RATE_CLASS_NOT_PREEMPTIBLE` (HTTP 409)."
    PRD §3.3: "`PRIME` is the premium and multiplies by 2.25."

    Design: Corner/state_machines/preempting_a_fixed_rate_class_spot_rejected_as_not_preemptible
    """
    built = setup_issue_order(
        call_sign="WFIX-TV",
        market_code="DMA-109",
        station_overrides={
            "licensee_name": "Fixed Rate Broadcasting",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        rate_class_overrides={
            "class_code": "RC-PR",
            "daypart": "PRIME",
            "preemptible": False,
            "preemption_priority": 0,
            "posted_rate_cents": 100000,
        },
        spots=[
            {
                "air_date": "2026-08-20",
                "start_offset_seconds": 0,
                "duration_seconds": 30,
                "program_code": "PR-1",
            }
        ],
        accept=True,
    )
    order, advertiser, spot = built["order"], built["advertiser"], built["spots"][0]

    validate_error(
        api.set_spot_disposition(
            spot["id"],
            {"disposition": "PREEMPTED", "preemption_reason": "Breaking news override"},
            TRAFFIC,
        ),
        ApiErrorId.ERR_RATE_CLASS_NOT_PREEMPTIBLE,
    )

    untouched = read_spot(spot["id"])
    assert untouched["status"] == "SCHEDULED"
    assert untouched["charged_rate_cents"] == 225000

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["gross_charge_cents"] == 225000
    assert refreshed["payment_status"] == "INVOICED"


def test_preempted_spot_leaves_the_spot_count_and_lifts_every_survivor(api):
    """PRD §3.6: "The second hop, caused by the first, recomputes the order's
    `spot_count` — which no longer counts the preempted spot — and therefore reselects
    the volume tier and reprices every remaining `SCHEDULED` or `AIRED` spot at that
    reselected tier before recomputing `gross_charge_cents`, `agency_commission_cents`
    and `net_due_cents`."
    PRD §3.4: "Every spot on the order that is `PREEMPTED` or `CANCELLED` has both its
    `charged_rate_cents` and its `unit_equivalent_rate_cents` forced to zero."

    Design: Corner/cross_cutting_complexity_layers/preempted_spot_is_excluded_from_the_derived_spot_count_and_charge
    """
    built = setup_issue_order(
        call_sign="WDRV-TV",
        market_code="DMA-145",
        station_overrides={
            "licensee_name": "Derived Field Media",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        rate_class_overrides={
            "class_code": "RC-AM",
            "daypart": "MORNING",
            "preemptible": True,
            "preemption_priority": 3,
            "posted_rate_cents": 12345,
        },
        spots=hourly_spots(5, prefix="AM"),
        accept=True,
    )
    order, advertiser = built["order"], built["advertiser"]
    first, second = built["spots"][0], built["spots"][1]
    assert order["gross_charge_cents"] == 35185

    validate_success(
        api.set_spot_disposition(
            first["id"],
            {"disposition": "PREEMPTED", "preemption_reason": "Breaking news override"},
            TRAFFIC,
        )
    )

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["spot_count"] == 4
    assert refreshed["gross_charge_cents"] == 29628, (
        "dropping out of the 5 percent tier raises every survivor to 7407"
    )
    assert refreshed["payment_status"] == "INVOICED"

    preempted = read_spot(first["id"])
    assert preempted["charged_rate_cents"] == 0
    assert preempted["unit_equivalent_rate_cents"] == 0
    assert read_spot(second["id"])["charged_rate_cents"] == 7407

    _rows, meta = validate_paginated(api.list_rebates(ADMIN, params={"order_id": order["id"]}))
    assert meta["total_count"] == 0, "nothing had been paid, so no refund is owed"


def test_rebate_ledger_entries_are_append_only_and_never_edited(api):
    """PRD §2.4: "The one exception is the rebate ledger. A `RebateLedgerEntry` is an
    immutable accounting record: it carries only `id` and `created_at`, and both
    `updated_at` and `version` are absent from it entirely."
    PRD §3.6: "Each entry names the `order_id` it was written against, the
    `luc_determination_id` of the determination that produced it — null when the
    `reason` is `SPOT_PREEMPTED` or `ORDER_CANCELLED` — the `amount_cents` owed at the
    instant it was written, the `reason` that produced it, and `occurred_at`, the
    logical-clock instant it was written."
    PRD §3.6: "Entries are never modified or deleted once written, which is why they
    carry no version of their own."

    Design: Corner/entities/rebate_ledger_entry_is_append_only_and_reachable_only_by_reverse_lookup
    """
    built = setup_issue_order(
        call_sign="WLED-TV",
        market_code="DMA-104",
        station_overrides={
            "licensee_name": "Ledger Broadcasting LLC",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        rate_class_overrides={
            "class_code": "RC-AM",
            "daypart": "MORNING",
            "preemptible": True,
            "preemption_priority": 3,
            "posted_rate_cents": 12345,
        },
        spots=hourly_spots(3, prefix="AM"),
        charge_amount_cents=22221,
    )
    order, advertiser = built["order"], built["advertiser"]
    first, second = built["spots"][0], built["spots"][1]

    preempt_spot(first["id"], "Breaking news override")
    written = list_rebates(order_id=order["id"])
    assert len(written) == 1
    assert_rebate_entry(written[0])
    first_entry_id = written[0]["id"]
    assert written[0]["amount_cents"] == 7407
    assert written[0]["reason"] == "SPOT_PREEMPTED"
    assert written[0]["luc_determination_id"] is None

    preempt_spot(second["id"], "Weather cut-in")

    reread = validate_success(api.get_rebate(first_entry_id, ADMIN))
    assert reread["amount_cents"] == 7407, "the earlier entry is never rewritten"
    assert reread["reason"] == "SPOT_PREEMPTED"
    assert_rebate_entry(reread)

    all_entries = list_rebates(order_id=order["id"])
    assert [entry["amount_cents"] for entry in all_entries] == [7407, 7407]
    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["rebate_total_cents"] == 14814
    assert refreshed["gross_charge_cents"] == 7407


def test_audit_sweep_moves_past_due_entries_to_overdue_and_freezes_the_station(api):
    """PRD §3.9: "Step one sweeps the public file. Every entry on the station still
    `PENDING` whose `due_at` the logical clock has passed moves `PENDING → OVERDUE`,
    processed in ascending `created_at` order; each such move decrements
    `pending_file_entry_count` by one and increments `overdue_file_entry_count` by one,
    and each in turn causes the station's `compliance_posture` to be recomputed from the
    new overdue count."
    PRD §3.1: "If that larger number is 2 or more, the posture is `FROZEN`."

    Design: Difficulty/transitive_cascade/audit_sweep_overdue_entries_freeze_posture_and_suspend_unpaid_order
    """
    built = setup_station_with_two_overdue_adjustments(call_sign="WSWP-TV")
    station = built["station"]
    first_adjustment, second_adjustment = built["adjustment_entries"]

    swept = run_audit_sweep(station["id"])

    assert read_file_entry(first_adjustment["id"])["posting_status"] == "OVERDUE"
    assert read_file_entry(second_adjustment["id"])["posting_status"] == "OVERDUE"
    assert read_file_entry(built["accepted_entry"]["id"])["posting_status"] == "POSTED"

    assert swept["overdue_file_entry_count"] == 2
    assert swept["pending_file_entry_count"] == 0
    assert swept["compliance_posture"] == "FROZEN"
    assert_station_posture(swept)


def test_frozen_posture_suspends_the_unpaid_accepted_order_at_the_checkpoint(api):
    """PRD §3.9: "Step five applies a frozen posture to live business. If step four left
    the posture at `FROZEN`, every order on the station sitting in `ACCEPTED` whose
    settlement state is anything other than `PAID` moves `ACCEPTED → SUSPENDED`."
    PRD §3.6: "The third hop, caused by the second, compares money: take `paid_cents`,
    subtract `refunded_cents`, subtract the new `net_due_cents`, and if that figure
    exceeds the `rebate_total_cents` already on the ledger, write one rebate ledger
    entry against the order with `reason` `SPOT_PREEMPTED` and `amount_cents` equal to
    the excess — the difference between that figure and the existing
    `rebate_total_cents`, never the whole figure — then refresh `rebate_total_cents` to
    the new figure and advance the settlement dimension `PAID → REFUND_DUE`."

    Design: Difficulty/transitive_cascade/audit_sweep_overdue_entries_freeze_posture_and_suspend_unpaid_order
    """
    built = setup_station_with_two_overdue_adjustments(call_sign="WSW2-TV")
    station, order, advertiser = built["station"], built["order"], built["advertiser"]

    before = read_order(order["id"], advertiser["id"])
    assert before["status"] == "ACCEPTED"
    assert before["payment_status"] == "REFUND_DUE"

    run_audit_sweep(station["id"])

    suspended = read_order(order["id"], advertiser["id"])
    assert suspended["status"] == "SUSPENDED", (
        "the posture flip suspends the station's unpaid accepted order"
    )
    assert suspended["payment_status"] == "REFUND_DUE"
    assert suspended["gross_charge_cents"] == 7407
    assert suspended["rebate_total_cents"] == 14814
    assert read_station(station["id"])["compliance_posture"] == "FROZEN"
