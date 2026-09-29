"""Currency expiry, the half-open report period, and the publication ladder.

The grants here are all mail-in OUTERWEAR grade B acceptances of a 50000 MSRP
item by a PLUS participant: 10000 base, a 1000 mail-in bonus and a 500 loyalty
bonus make an 11500 grant, and the 180-day brand-currency policy puts a grant
issued at the 2026-08-01T00:00:00Z default clock at 2027-01-28T00:00:00Z. None of
these units is ever refurbished, so none of them needs a bay.
"""

from test_helpers import (
    ADMIN,
    MERCH,
    NON_EXISTENT_UUID,
    api_client,
    assert_credit_ledger_entry,
    assert_diversion_report,
    assert_instant,
    assert_null,
    assert_pagination_meta,
    create_customer,
    create_report,
    create_trade_in,
    fetch_customer,
    fetch_grant,
    fetch_report,
    headers_without_user_id,
    publish_report,
    run_expiry_sweep,
    set_clock,
    setup_credit_source_grant,
    setup_estate,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_diversion_report_payload

GRANT_AMOUNT = 11500
EXPIRES_AT = "2027-01-28T00:00:00Z"
ONE_SECOND_EARLIER = "2027-01-27T23:59:59Z"


def _grant_ledger_page(credit_grant_id, params=None):
    """The grant's ledger listing, as rows plus the envelope's meta."""
    return validate_paginated(
        api_client.list_credit_grant_ledger_entries(credit_grant_id, ADMIN, params)
    )


def test_the_expiry_boundary_is_inclusive_and_a_rerun_expires_nothing():
    """One second early the grant survives; at the instant itself it is swept once.

    PRD §3.9: "A `ProgramAdmin` runs the **expiry sweep**, which takes every grant
    whose `status` is `ISSUED` or `PARTIALLY_REDEEMED` and whose `expires_at` is at or
    before the logical clock — the boundary is inclusive, so a grant expiring exactly
    now is swept."
    PRD §3.9: "For each grant it appends a ledger entry with `entry_type` `EXPIRE`, an
    `amount_minor` equal to the negative of that grant's `remaining_minor`, a
    `balance_after_minor` of 0, a null `resale_order_id` and `occurred_at` from the
    logical clock; then sets `remaining_minor` to 0, moves `status` to `EXPIRED`, and
    increments the grant's version."
    PRD §3.9: "`EXHAUSTED` grants are skipped because their `remaining_minor` is
    already zero, and grants already `EXPIRED` are skipped too, which makes a repeated
    sweep idempotent — it expires nothing and reports zeros."
    PRD §3.9: "The run reports `expired_grant_count`, `expired_amount_minor` and
    `affected_customer_count`."
    PRD §2.4: "A brand-currency grant whose `expires_at` equals the logical clock is
    expired — the expiry boundary is inclusive on the expiry side, while the
    redemption-eligibility test is strict, admitting only grants whose `expires_at`
    lies strictly after the clock."

    Design: Corner/calculations/expiry_sweep_boundary_is_inclusive_and_a_rerun_expires_nothing
    """
    estate = setup_estate()
    scenario = setup_credit_source_grant(estate, loyalty_tier="PLUS")
    grant = scenario["grant"]
    assert grant["issued_amount_minor"] == GRANT_AMOUNT
    assert grant["remaining_minor"] == GRANT_AMOUNT
    assert grant["status"] == "ISSUED"
    # 180 days from the default clock.
    assert_instant(grant["expires_at"], EXPIRES_AT, "expires_at")
    issued_version = grant["version"]

    set_clock(ONE_SECOND_EARLIER)
    early = run_expiry_sweep()
    assert early["expired_grant_count"] == 0
    assert early["expired_amount_minor"] == 0
    assert early["affected_customer_count"] == 0

    survivor = fetch_grant(grant["id"])
    assert survivor["status"] == "ISSUED"
    assert survivor["remaining_minor"] == GRANT_AMOUNT
    # A grant the sweep never touched is not a mutation.
    assert survivor["version"] == issued_version

    set_clock(EXPIRES_AT)
    on_time = run_expiry_sweep()
    assert on_time["expired_grant_count"] == 1
    assert on_time["expired_amount_minor"] == GRANT_AMOUNT
    assert on_time["affected_customer_count"] == 1

    expired = fetch_grant(grant["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["remaining_minor"] == 0
    assert expired["version"] == issued_version + 1

    rows, meta = _grant_ledger_page(grant["id"])
    assert_pagination_meta(meta, 2)
    assert_credit_ledger_entry(rows[1])
    assert rows[0]["entry_type"] == "ISSUE"
    assert rows[1]["entry_type"] == "EXPIRE"
    assert rows[1]["amount_minor"] == -GRANT_AMOUNT
    assert rows[1]["balance_after_minor"] == 0
    assert_null(rows[1]["resale_order_id"], "resale_order_id")
    assert_instant(rows[1]["occurred_at"], EXPIRES_AT, "occurred_at")

    # A second sweep at the same instant has nothing left to take.
    again = run_expiry_sweep()
    assert again["expired_grant_count"] == 0
    assert again["expired_amount_minor"] == 0
    assert again["affected_customer_count"] == 0
    unchanged_rows, unchanged_meta = _grant_ledger_page(grant["id"])
    assert_pagination_meta(unchanged_meta, 2)
    assert len(unchanged_rows) == 2
    assert fetch_grant(grant["id"])["version"] == issued_version + 1
    assert fetch_customer(scenario["customer"]["id"])["credit_balance_minor"] == 0


def test_the_report_period_is_half_open_on_the_acceptance_instant():
    """23:59:59Z belongs to August, the boundary instant itself belongs to September.

    PRD §3.9: "Membership in a report's population is decided by one thing only: a
    trade-in's `accepted_at`, which must be at or after `period_start_at` and strictly
    before `period_end_at`, with the trade-in's `status` being `ACCEPTED`."
    PRD §3.9: "The report's population is then every resale unit whose originating
    trade-in is in that accepted set, and five metrics are computed over it."
    PRD §3.9: "A period must not overlap the period of any `DRAFT` or `PUBLISHED`
    report other than the row being superseded, judged on the half-open interval, and
    an overlap is refused with `ERR_REPORT_PERIOD_OVERLAP`."
    PRD §2.4: "A **markdown campaign window** and a **diversion report period**,
    delimited by `window_start_at`/`window_end_at` and `period_start_at`/`period_end_at`
    respectively, are *half-open*: the start instant is inside the window and the end
    instant is outside it."
    PRD §3.9: "`credit_liability_minor` is the unredeemed brand currency issued inside
    the period — the summed `remaining_minor` over grants whose `status` is `ISSUED` or
    `PARTIALLY_REDEEMED` and whose `issued_at` is at or after `period_start_at` and
    strictly before `period_end_at`."

    Design: Corner/calculations/diversion_period_is_half_open_on_trade_in_accepted_at
    """
    estate = setup_estate()

    set_clock("2026-08-31T23:59:59Z")
    august = setup_credit_source_grant(estate, loyalty_tier="PLUS", item_mass_grams=1300)
    assert_instant(
        august["trade_in"]["accepted_at"], "2026-08-31T23:59:59Z", "accepted_at"
    )
    assert august["trade_in"]["status"] == "ACCEPTED"
    assert august["grant"]["issued_amount_minor"] == GRANT_AMOUNT

    set_clock("2026-09-01T00:00:00Z")
    september = setup_credit_source_grant(
        estate, customer=august["customer"], item_mass_grams=1400
    )
    assert_instant(
        september["trade_in"]["accepted_at"], "2026-09-01T00:00:00Z", "accepted_at"
    )
    assert september["grant"]["issued_amount_minor"] == GRANT_AMOUNT

    # [2026-08-01, 2026-09-01) reaches the 23:59:59Z acceptance and stops there.
    august_report = create_report()
    assert_diversion_report(august_report)
    assert august_report["status"] == "DRAFT"
    assert_null(august_report["published_at"], "published_at")
    assert august_report["units_diverted_count"] == 1
    assert august_report["diverted_grams"] == 1300
    assert august_report["salvage_grams"] == 0
    assert august_report["landfill_diversion_rate_bp"] == 10000
    assert august_report["credit_liability_minor"] == GRANT_AMOUNT

    # The adjacent period starts exactly where the first one ended, which is not an
    # overlap, so it is accepted rather than refused.
    september_report = create_report(
        period_start_at="2026-09-01T00:00:00Z",
        period_end_at="2026-10-01T00:00:00Z",
    )
    assert september_report["id"] != august_report["id"]
    assert september_report["units_diverted_count"] == 1
    assert september_report["diverted_grams"] == 1400
    assert september_report["salvage_grams"] == 0
    assert september_report["landfill_diversion_rate_bp"] == 10000
    assert september_report["credit_liability_minor"] == GRANT_AMOUNT
    # Neither report ever sees the other period's mass.
    assert august_report["diverted_grams"] + september_report["diverted_grams"] == 2700


def test_overlap_publication_and_restatement_are_each_refused_in_turn():
    """The incumbent blocks a stranger's period, admits its restatement, and publishes once.

    PRD §3.9: "A period must not overlap the period of any `DRAFT` or `PUBLISHED`
    report other than the row being superseded, judged on the half-open interval, and
    an overlap is refused with `ERR_REPORT_PERIOD_OVERLAP`."
    PRD §3.9: "A report declares its half-open period through `period_start_at` and
    `period_end_at`, and may optionally name `supersedes_report_id`, the earlier
    published report this one restates; that field is null for an original report."
    PRD §3.9: "Publishing moves it from `DRAFT` to `PUBLISHED` and stamps
    `published_at` from the logical clock, incrementing its version; publishing a
    report whose status is not `DRAFT` — one already published, or one that has itself
    been superseded — is refused with `ERR_REPORT_ALREADY_PUBLISHED`."
    PRD §3.9: "Publication also carries a cross-entity effect: when the new report
    names a `supersedes_report_id`, that earlier report is moved to the terminal
    `SUPERSEDED` from whichever of `DRAFT` or `PUBLISHED` it held, and its own version
    is incremented."
    PRD §3.9: "A superseded report's computed metric fields are frozen and never
    recomputed, so the restated figures live in the new row and the historical figures
    remain readable in the old one."

    Design: Corner/errors/report_overlap_publication_and_restatement_errors_are_triggerable
    """
    estate = setup_estate()
    scenario = setup_credit_source_grant(estate, loyalty_tier="PLUS")
    assert scenario["grant"]["issued_amount_minor"] == GRANT_AMOUNT

    incumbent = create_report()
    assert incumbent["status"] == "DRAFT"
    assert_null(incumbent["supersedes_report_id"], "supersedes_report_id")
    assert incumbent["units_diverted_count"] == 1
    assert incumbent["diverted_grams"] == 1400
    assert incumbent["landfill_diversion_rate_bp"] == 10000
    assert incumbent["credit_liability_minor"] == GRANT_AMOUNT

    # [2026-08-15, 2026-09-15) partially overlaps the DRAFT [2026-08-01, 2026-09-01)
    # and supersedes nothing, so it is refused.
    validate_error(
        api_client.create_diversion_report(
            create_diversion_report_payload(
                period_start_at="2026-08-15T00:00:00Z",
                period_end_at="2026-09-15T00:00:00Z",
            ),
            ADMIN,
        ),
        "ERR_REPORT_PERIOD_OVERLAP",
        409,
    )

    published = publish_report(incumbent["id"])
    assert published["status"] == "PUBLISHED"
    assert_instant(published["published_at"], "2026-08-01T00:00:00Z", "published_at")
    assert published["version"] == incumbent["version"] + 1

    validate_error(
        api_client.publish_diversion_report(incumbent["id"], ADMIN),
        "ERR_REPORT_ALREADY_PUBLISHED",
        409,
    )

    # The identical period is admitted once it names the incumbent it restates.
    restatement = create_report(
        supersedes_report_id=incumbent["id"],
        period_start_at="2026-08-01T00:00:00Z",
        period_end_at="2026-09-01T00:00:00Z",
    )
    assert restatement["status"] == "DRAFT"
    assert restatement["supersedes_report_id"] == incumbent["id"]
    assert restatement["diverted_grams"] == 1400

    # Creating the restatement does not demote the incumbent.
    mid = fetch_report(incumbent["id"])
    assert mid["status"] == "PUBLISHED"
    assert mid["version"] == published["version"]

    republished = publish_report(restatement["id"])
    assert republished["status"] == "PUBLISHED"

    superseded = fetch_report(incumbent["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["version"] == published["version"] + 1
    # Frozen, not recomputed.
    assert superseded["diverted_grams"] == 1400
    assert superseded["units_diverted_count"] == 1
    assert superseded["credit_liability_minor"] == GRANT_AMOUNT


def test_publish_answers_the_caller_before_it_answers_the_path():
    """One unknown report id, three different answers, decided purely by the caller.

    PRD §2.11: "When a single request could fail several checks, the platform evaluates
    them in a fixed order and reports the first failure it reaches."
    PRD §2.1: "Everywhere else, a `X-User-ID` header that is absent, an empty string,
    or made up only of whitespace is treated as unauthenticated and the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "A caller who is authenticated but whose `X-User-Role` is not among the
    roles that the target endpoint admits is rejected with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."
    PRD §2.11: "**Path existence.** Every entity named by an `{id}` path segment must
    exist, resolved strictly left to right, so that the outermost missing segment is
    the one reported."
    PRD §3.9: "**Diversion reporting** is how the programme turns tracked mass into a
    published sustainability number, and only a `ProgramAdmin` may generate or publish
    one."
    PRD §2.1: "Both are required on every endpoint of the platform with a single
    exception: the logical-clock setter, `POST /recommerce/_clock/set_current_utc`, is
    a test-driving capability and performs neither authentication nor authorization."

    Design: Corner/validations/publish_rejects_unauthenticated_before_role_and_existence
    """
    # An empty X-User-ID is as unauthenticated as an absent one, and 401 outranks the
    # missing row.
    validate_error(
        api_client.publish_diversion_report(
            NON_EXISTENT_UUID, headers_without_user_id()
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )

    # A MerchandisingManager may read reports but may not publish them, and 403
    # outranks the missing row too.
    validate_error(
        api_client.publish_diversion_report(NON_EXISTENT_UUID, MERCH),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    # Only the admitted role gets as far as looking the id up.
    validate_error(
        api_client.publish_diversion_report(NON_EXISTENT_UUID, ADMIN),
        "ERR_DIVERSION_REPORT_NOT_FOUND",
        404,
    )

    # The clock setter is the one endpoint that answers an unauthenticated caller.
    echoed = validate_success(
        api_client.set_clock("2026-08-02T00:00:00Z", headers_without_user_id())
    )
    assert_instant(echoed["current_utc"], "2026-08-02T00:00:00Z", "current_utc")


def test_the_clock_starts_at_the_default_and_then_stamps_every_write():
    """Nothing reads wall time: the first row is stamped 2026-08-01 and the next one is not.

    PRD §2.4: "Nothing in this platform reads the host's wall clock."
    PRD §2.4: "Before any client has set it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real time under any
    circumstance."
    PRD §2.4: "A test-driving endpoint accepts a `current_utc` instant and moves the
    logical clock to it, echoing the value it now holds back as `current_utc`; any role
    may call it, and it is the one endpoint exempt from the header checks of §2.1."
    PRD §2.6: "Most resources — customers, condition-tier policies, brand-currency
    policies, store locations, refurbishment bays, channels, trade-ins, brand-currency
    grants, resale units, refurbishment orders, markdown campaigns, resale orders and
    diversion reports — additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation of the row, and `version`, an integer that is
    initialized to 1 when the row is created and incremented by exactly one on every
    mutation."
    PRD §3.2: "A mail-in submission gets three full weeks — twenty-one days from
    creation — because the item still has to travel; an in-store submission gets only
    two days, since the customer is standing at the counter."
    PRD §3.2: "Both are counted from the trade-in's own creation timestamp."

    Design: Corner/endpoints/logical_clock_defaults_and_then_stamps_every_write
    """
    setup_estate()
    # No clock call has been made, so the default instant is what gets stamped.
    customer = create_customer(email="ava@example.com", full_name="Ava Reyes")
    assert_instant(customer["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant(customer["updated_at"], "2026-08-01T00:00:00Z", "updated_at")
    assert customer["version"] == 1

    # Any role may move the clock, not just the ProgramAdmin.
    echoed = validate_success(
        api_client.set_clock("2026-08-05T06:30:00Z", MERCH)
    )
    assert_instant(echoed["current_utc"], "2026-08-05T06:30:00Z", "current_utc")

    trade_in = create_trade_in(customer, channel="MAIL_IN")
    assert_instant(trade_in["created_at"], "2026-08-05T06:30:00Z", "created_at")
    # Twenty-one days from creation, keeping the time of day.
    assert_instant(
        trade_in["receive_deadline_at"], "2026-08-26T06:30:00Z", "receive_deadline_at"
    )
    assert trade_in["status"] == "SUBMITTED"

    # Moving the clock rewrites nothing that already exists.
    unchanged = fetch_customer(customer["id"])
    assert_instant(unchanged["created_at"], "2026-08-01T00:00:00Z", "created_at")
    assert_instant(unchanged["updated_at"], "2026-08-01T00:00:00Z", "updated_at")
    assert unchanged["version"] == 1
