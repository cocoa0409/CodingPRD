"""The one optimistic-concurrency gate and the immediacy of every derived field.

Covers PRD section 2.11 (the `expected_business_date_version` token and the
all-or-nothing refusal that follows a mismatch), PRD section 3.8 (report creation
as a snapshot that bumps the day's version) and PRD section 3.6 (an approval whose
whole cascade lands before the response is written).
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_int,
    assert_money,
    assert_money_fields,
    assert_page_meta,
    assert_row_count,
    single,
)
from test_helpers.test_users import AUDITOR, CONTROLLER, FRONT_DESK, REVENUE_MANAGER


def _day_under_settlement_review(api):
    """One rack-rate account on a day carried as far as SETTLEMENT_REVIEW."""
    fx.set_clock(api, "2026-08-02T02:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-OCC1",
        guest_name="Rune Balto",
        room_number="801",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.drive_to_settlement_review(api, bd["id"])
    return prop, bd, folio


def test_a_stale_expected_business_date_version_writes_nothing_at_all(api):
    """The token is an equality check, and a refused snapshot leaves even the day untouched.

    PRD section 3.8 makes report creation increment the day's `version`, so the value the
    first report was written against is stale the moment it lands. PRD section 2.11 then
    requires the server to compare `expected_business_date_version` against the version it
    holds and, on any difference, to reject with ERR_STALE_BUSINESS_DATE_VERSION (HTTP 412)
    while writing nothing: no report row, no supersession of the previous report, and no
    change to the day's own `version`. The comparison is equality rather than ordering, so a
    version below the current one and a version above it fail alike, and PRD section 2.11
    makes the field non-optional, so omitting it is a request-shape failure instead.

    Design: Corner/cross-cutting complexity layers/layer_optimistic_concurrency_stale_business_date_version_writes_nothing
    """
    _prop, bd, _folio = _day_under_settlement_review(api)
    recipients = ["Controller", "RevenueManager"]

    stale_version = fx.business_date_version(api, bd["id"])
    first_report = validate_success(
        api.create_revenue_report(
            f.build_revenue_report_payload(bd["id"], stale_version, recipients),
            REVENUE_MANAGER,
        ),
        expected_status=201,
    )
    assert_fields(
        validate_success(api.distribute_revenue_report(first_report["id"], REVENUE_MANAGER)),
        {"status": "DISTRIBUTED"},
    )

    fresh_version = fx.business_date_version(api, bd["id"])
    assert fresh_version != stale_version, (
        "creating a report must move the day's version away from "
        f"{stale_version}, but it still reads {fresh_version}"
    )
    assert fresh_version != 99, "the guard value 99 must not be the day's live version"

    for rejected_version in [stale_version, 0, 99]:
        validate_error(
            api.create_revenue_report(
                f.build_revenue_report_payload(bd["id"], rejected_version, recipients),
                REVENUE_MANAGER,
            ),
            E.ERR_STALE_BUSINESS_DATE_VERSION,
            expected_status=412,
        )

    rows, meta = validate_paginated(api.list_revenue_reports(REVENUE_MANAGER, business_date_id=bd["id"]))
    assert_page_meta(meta, total_count=1)
    assert_row_count(rows, 1, "revenue reports after the refusals")
    assert_fields(single(rows, "surviving report"), {"id": first_report["id"], "status": "DISTRIBUTED"})
    assert_int(
        fx.business_date_version(api, bd["id"]),
        fresh_version,
        "the day's version after the refused writes",
    )

    validate_error(
        api.create_revenue_report(
            f.without(
                f.build_revenue_report_payload(bd["id"], fresh_version, recipients),
                "expected_business_date_version",
            ),
            REVENUE_MANAGER,
        ),
        E.ERR_INVALID_REQUEST,
        expected_status=400,
    )
    assert_int(
        fx.business_date_version(api, bd["id"]),
        fresh_version,
        "the day's version after the shape failure",
    )

    second_report = validate_success(
        api.create_revenue_report(
            f.build_revenue_report_payload(bd["id"], fresh_version, recipients),
            REVENUE_MANAGER,
        ),
        expected_status=201,
    )
    assert_fields(second_report, {"status": "DRAFT"})
    assert_fields(fx.read_report(api, first_report["id"]), {"status": "SUPERSEDED"})
    assert fx.business_date_version(api, bd["id"]) > fresh_version, (
        "the accepted snapshot must consume a version of its own"
    )
    _rows, after = validate_paginated(
        api.list_revenue_reports(REVENUE_MANAGER, business_date_id=bd["id"])
    )
    assert_page_meta(after, total_count=2)


def test_one_approval_lands_its_whole_cascade_before_the_response_is_written(api):
    """Every derived consequence is already visible on the first read, and stays put.

    PRD section 3.6 carries an approved rebate straight through APPROVED to POSTED inside
    the same request, appends the ALLOWANCE line of the negated `approved_amount`,
    re-derives the credited account's totals and the day's revenue statistics, and sets the
    day's DISTRIBUTED report to SUPERSEDED. PRD section 3.8 keeps that report a frozen
    snapshot, so its figures still hold the pre-approval numbers while its status has already
    moved. Nothing here is deferred: the first read after the approval is the final answer,
    a repeat read returns the same body, and a second approval is refused
    ERR_ALLOWANCE_NOT_PENDING (HTTP 409) rather than replaying the cascade.

    Design: Corner/consistency model/consistency_immediate_every_derived_field_is_current_in_the_same_response
    """
    fx.set_clock(api, "2026-08-02T02:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(
        api,
        prop["id"],
        "2026-08-01",
        out_of_order_room_count=4,
        # The pace comparison below reads the day's stored calendar benchmark
        # (PRD 3.8): 100 * 200.00 / 400.00 == 50.00.
        benchmark_calendar_room_revenue_amount=400.00,
    )
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-IMM1",
        guest_name="Sunniva Kolstad",
        room_number="901",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.drive_to_settlement_review(api, bd["id"])
    fx.distribute_report(api, fx.create_report(api, bd["id"], ["RevenueManager"])["id"])
    fx.balance_business_date(api, bd["id"])
    fx.close_business_date(api, bd["id"])
    validate_success(api.reopen_business_date(bd["id"], CONTROLLER))
    report = fx.create_report(
        api, bd["id"], ["RevenueManager", "Controller"], pace_basis="CALENDAR_ALIGNED"
    )
    fx.distribute_report(api, report["id"])
    assert_fields(fx.read_report(api, report["id"]), {"status": "DISTRIBUTED"})
    allowance = fx.submitted_allowance(
        api,
        folio["id"],
        bd["id"],
        200.00,
        FRONT_DESK,
        reason_code="SERVICE_RECOVERY",
        narrative="Two nights of failed air conditioning.",
    )
    assert_fields(
        allowance,
        {"required_approval_role": "NightAuditor", "requested_by_user_id": "u_fd_1"},
    )

    # The single write. Everything below reads only.
    approved = validate_success(
        api.approve_allowance(allowance["id"], f.build_approve_payload(200.00), AUDITOR)
    )
    assert_fields(approved, {"status": "POSTED", "approved_by_user_id": "u_na_1"})
    assert_money(approved["approved_amount"], 200.00, "approved_amount")
    assert approved["approved_at"] is not None, "approved_at must be stamped by the approval"

    lines = validate_success(
        api.list_journal_postings(AUDITOR, allowance_id=allowance["id"])
    )
    assert_row_count(lines, 1, "ALLOWANCE lines")
    assert_fields(single(lines, "credit line"), {"charge_type": "ALLOWANCE"})
    assert_money(single(lines, "credit line")["amount"], -200.00, "the credit line amount")

    account = validate_success(api.get_folio(folio["id"], AUDITOR))
    assert_money_fields(
        account,
        {
            "charges_total_amount": 217.75,
            "credits_total_amount": -200.00,
            "balance_amount": 17.75,
        },
    )

    day = validate_success(api.get_business_date(bd["id"], AUDITOR))
    assert_money_fields(
        day,
        {
            "allowance_credit_amount": -200.00,
            "room_night_revenue_amount": 0.00,
            "room_revenue_amount": 0.00,
            "tax_revenue_amount": 17.75,
            "total_revenue_amount": 17.75,
            "adr_amount": 0.00,
            "revpar_amount": 0.00,
            "occupancy_pct": 1.04,
        },
    )
    assert_int(day["rooms_occupied_count"], 1, "rooms_occupied_count")

    frozen = validate_success(api.get_revenue_report(report["id"], REVENUE_MANAGER))
    assert_fields(frozen, {"status": "SUPERSEDED"})
    assert_money_fields(
        frozen,
        {
            "room_revenue_amount": 200.00,
            "tax_revenue_amount": 17.75,
            "outlet_revenue_amount": 0.00,
            "total_revenue_amount": 217.75,
            "adr_amount": 200.00,
            "revpar_amount": 2.08,
            "occupancy_pct": 1.04,
            "pace_index_pct": 50.00,
        },
    )

    # No convergence step: the same four reads a second time return the same bodies.
    assert validate_success(api.get_allowance(allowance["id"], AUDITOR)) == validate_success(
        api.get_allowance(allowance["id"], AUDITOR)
    ), "a second read of the rebate must return the same body"
    assert validate_success(api.get_folio(folio["id"], AUDITOR)) == account, (
        "a second read of the account must return the same body"
    )
    assert validate_success(api.get_business_date(bd["id"], AUDITOR)) == day, (
        "a second read of the operating day must return the same body"
    )
    assert validate_success(api.get_revenue_report(report["id"], REVENUE_MANAGER)) == frozen, (
        "a second read of the report must return the same body"
    )

    validate_error(
        api.approve_allowance(allowance["id"], f.build_approve_payload(200.00), AUDITOR),
        E.ERR_ALLOWANCE_NOT_PENDING,
        expected_status=409,
    )
    assert_row_count(
        validate_success(api.list_journal_postings(AUDITOR, allowance_id=allowance["id"])),
        1,
        "ALLOWANCE lines after the refused second approval",
    )
    assert validate_success(api.get_business_date(bd["id"], AUDITOR)) == day, (
        "the refused second approval must not move the day"
    )
