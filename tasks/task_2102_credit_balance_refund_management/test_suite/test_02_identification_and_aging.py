"""The identification sweep, credit-balance aging and the logical clock."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_credit_balance,
    assert_credit_liability_invariant,
    assert_instant_equals,
    post_txn,
    read_account,
    read_credit_balance,
    run_identify_sweep,
    seed_account,
    seed_payer,
    set_clock,
    setup_identified_credit,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["credit_analyst_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def test_swept_credit_balance_opens_in_identified_with_no_attribution_yet(api):
    """PRD §3.2: "For each candidate the service creates one credit balance row whose `account_id` is the account, whose `payer_id` is copied from that account's `primary_payer_id`, whose `credit_amount_cents` is the magnitude of the account's negative `balance_cents` frozen at this moment — the sign is inverted, so an account sitting at negative twenty thousand cents produces a credit amount of twenty thousand cents — whose `identified_at` is the current logical clock instant, and whose `status` is `IDENTIFIED`."
    PRD §3.2: "Its response reports `identified_count`, the number of rows created; `credit_balance_ids`, their ids in sweep order; and `skipped_account_count`, the number of accounts explicitly named in `account_ids` that failed to qualify as candidates."
    PRD §3.2: "The credit balance also exposes `attribution_method` and `attribution`, both null until attribution runs; `patient_portion_cents` and `payer_portion_cents`, both 0 until then; the derived `refunded_cents`, `offset_cents` and `outstanding_cents` described in §2.9; and `root_cause_confirmed`, a flag that is true exactly when at least one root-cause finding on this credit balance has `confirmed` set to true."

    Design: Corner/state_machines/credit_balance_initial_state_is_identified_with_null_attribution
    """
    set_clock("2026-08-01T00:00:00Z")
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")
    account = seed_account(payer["id"], account_number="ACCT-IN1",
                           financial_class="INPATIENT", patient_name="Ines Nagy")
    post_txn(account["id"], "CHARGE", 50_000, "SYSTEM")
    set_clock("2026-08-05T00:00:00Z")
    post_txn(account["id"], "PAYMENT", -62_000, "PATIENT")
    set_clock("2026-08-15T00:00:00Z")

    sweep = validate_success(
        api.run_identify_sweep({"account_ids": [account["id"]]}, ANALYST)
    )
    assert sweep["identified_count"] == 1
    assert sweep["skipped_account_count"] == 0

    credit_balance = read_credit_balance(sweep["credit_balance_ids"][0])
    assert_credit_balance(credit_balance)
    assert credit_balance["status"] == "IDENTIFIED"
    assert credit_balance["account_id"] == account["id"]
    assert credit_balance["payer_id"] == payer["id"]
    assert credit_balance["credit_amount_cents"] == 12_000
    assert_instant_equals(
        credit_balance["identified_at"], "2026-08-15T00:00:00Z", "identified_at"
    )
    assert credit_balance["attribution_method"] is None
    assert credit_balance["attribution"] is None
    assert credit_balance["patient_portion_cents"] == 0
    assert credit_balance["payer_portion_cents"] == 0
    assert credit_balance["refunded_cents"] == 0
    assert credit_balance["offset_cents"] == 0
    assert credit_balance["outstanding_cents"] == 12_000
    assert credit_balance["root_cause_confirmed"] is False
    assert credit_balance["aging_bucket"] == "D0_30"
    assert_credit_liability_invariant(credit_balance)

    assert read_account(account["id"])["credit_balance_cents"] == 12_000


def test_sweep_skips_an_account_that_already_carries_an_open_credit_balance(api):
    """PRD §3.2: "An account is a candidate only when all four of the following hold, evaluated in this order: it is named in `account_ids` or `account_ids` was omitted; its `status` is `OPEN` or `BAD_DEBT`, so a `CLOSED` account is skipped even when it is in credit; its `balance_cents` is at or below negative one cent, which is to say the account is genuinely in credit by at least one cent; and no credit balance already exists on that account whose `status` is `IDENTIFIED`, `UNDER_REVIEW`, `ATTRIBUTED`, `REFUND_PENDING` or `REFUNDED`."

    Design: Corner/state_machines/identify_sweep_skips_account_that_already_carries_an_open_credit_balance
    """
    scenario = setup_identified_credit(account_number="ACCT-SK1",
                                       financial_class="INPATIENT")
    account_id = scenario["account"]["id"]

    second_sweep = validate_success(
        api.run_identify_sweep({"account_ids": [account_id]}, ANALYST)
    )
    assert second_sweep["identified_count"] == 0
    assert second_sweep["skipped_account_count"] == 1

    _, meta = validate_paginated(
        api.list_credit_balances(ANALYST, params={"account_id": account_id})
    )
    assert meta["total_count"] == 1, "no second credit balance row may be created"
    assert read_account(account_id)["credit_balance_cents"] == 12_000


def test_aging_bucket_still_d0_30_at_exactly_thirty_whole_days(api):
    """PRD §3.2: "its `aging_days` is recomputed as the whole floored days from `identified_at` to the logical clock, and its `aging_bucket` is derived from that count by four edges: `D0_30` when `aging_days` is at most 30, `D31_60` when it is at most 60, `D61_90` when it is at most 90, `D91_180` when it is at most 180, and `OVER_180` beyond that."
    PRD §3.2: "The edges are inclusive on the lower bucket, so a credit exactly 30 whole days old is still `D0_30` and one 31 whole days old is `D31_60`; a credit exactly 180 whole days old is still `D91_180` and one 181 whole days old is `OVER_180`."

    Design: Difficulty/boundary_precision_check/aging_bucket_edge_exactly_thirty_days_stays_d0_30_and_thirty_one_flips
    """
    scenario = setup_identified_credit(account_number="ACCT-AG1", state_code="FL")
    credit_balance_id = scenario["credit_balance"]["id"]
    assert_instant_equals(
        scenario["credit_balance"]["identified_at"], "2026-08-15T00:00:00Z",
        "identified_at",
    )
    assert scenario["credit_balance"]["credit_amount_cents"] == 12_000

    set_clock("2026-09-14T00:00:00Z")
    at_thirty = validate_success(api.get_credit_balance(credit_balance_id, ANALYST))
    assert at_thirty["aging_days"] == 30
    assert at_thirty["aging_bucket"] == "D0_30"


def test_aging_bucket_flips_to_d31_60_one_day_past_the_edge(api):
    """PRD §3.2: "The edges are inclusive on the lower bucket, so a credit exactly 30 whole days old is still `D0_30` and one 31 whole days old is `D31_60`; a credit exactly 180 whole days old is still `D91_180` and one 181 whole days old is `OVER_180`."
    PRD §2.6: "To compute a whole-day age, take the difference between the later instant and the earlier instant, express it in seconds, divide by 86,400 and discard any fractional part."

    Design: Difficulty/boundary_precision_check/aging_bucket_edge_exactly_thirty_days_stays_d0_30_and_thirty_one_flips
    """
    scenario = setup_identified_credit(account_number="ACCT-AG1", state_code="FL")
    credit_balance_id = scenario["credit_balance"]["id"]

    set_clock("2026-09-15T00:00:00Z")
    at_thirty_one = validate_success(api.get_credit_balance(credit_balance_id, ANALYST))
    assert at_thirty_one["aging_days"] == 31
    assert at_thirty_one["aging_bucket"] == "D31_60"


def test_logical_clock_reads_its_startup_default_before_any_reposition(api):
    """PRD §2.5: "At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. Until it is explicitly moved, that instant is what the service reports and stamps; it never falls back to real wall-clock time."

    Design: Corner/cross_cutting_layers/logical_clock_startup_default_is_2026_08_01_before_any_set_call
    """
    payer = seed_payer(payer_code="COM", payer_type="COMMERCIAL")
    account = seed_account(payer["id"], account_number="ACCT-DF1",
                           financial_class="INPATIENT", patient_name="Dev Fall")
    charge = post_txn(account["id"], "CHARGE", 50_000, "SYSTEM")
    post_txn(account["id"], "PAYMENT", -62_000, "PATIENT")

    sweep = run_identify_sweep([account["id"]])
    credit_balance = read_credit_balance(sweep["credit_balance_ids"][0])

    assert_instant_equals(charge["posted_at"], "2026-08-01T00:00:00Z", "posted_at")
    assert_instant_equals(
        credit_balance["identified_at"], "2026-08-01T00:00:00Z", "identified_at"
    )
    assert credit_balance["aging_days"] == 0
    assert credit_balance["aging_bucket"] == "D0_30"
    assert_instant_equals(
        read_account(account["id"])["last_activity_at"], "2026-08-01T00:00:00Z",
        "last_activity_at",
    )


def test_pagination_bounds_are_enforced_and_the_defaults_apply(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."
    PRD §2.3: "Both must be integers; a `limit` outside the inclusive range 1 through 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/pagination_limit_outside_one_to_hundred_is_rejected
    """
    seed_payer(payer_code="COM", payer_type="COMMERCIAL")

    validate_error(
        api.list_credit_balances(ANALYST, params={"limit": 101}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
    )
    validate_error(
        api.list_credit_balances(ANALYST, params={"offset": -1}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
    )

    rows, meta = validate_paginated(api.list_credit_balances(ANALYST))
    assert rows == []
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
