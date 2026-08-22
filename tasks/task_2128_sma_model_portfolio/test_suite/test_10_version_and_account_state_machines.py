"""Non-linear state machines: the cyclic model-version review loop, and the
two independent state dimensions carried on one account row."""
from test_helpers import (
    COMPLIANCE_USER_ID,
    MANAGER_2_USER_ID,
    MANAGER_USER_ID,
    TEST_USERS,
    create_invoice,
    create_model,
    create_securities,
    create_draft_version,
    get_account,
    get_model_version,
    make_compliance_officer_headers,
    make_portfolio_manager_headers,
    reject_model_version_payload,
    set_sleeves,
    setup_funded_account,
    sleeves_payload,
    submit_version,
    suspend_account,
    validate_success,
)

BILLING = TEST_USERS["billing_officer_headers"]

REJECTION_NOTE = "Concentration in ALFA exceeds the mandate"

PERIOD_START = "2026-01-01T00:00:00Z"
PERIOD_END = "2026-04-01T00:00:00Z"
AVERAGE_DAILY_VALUE_CENTS = 30_000_000


def _version_pending_approval():
    """One model version whose ALFA 6000 / BETA 4000 sleeves sum to 10000,
    submitted by pm-1 and therefore sitting in PENDING_APPROVAL."""
    securities = create_securities(
        [("ALFA", "Alfa Industrials", 10_000), ("BETA", "Beta Materials", 5_000)]
    )
    model = create_model(strategy_code="CORE")
    version = create_draft_version(
        model["id"], [("ALFA", 6000), ("BETA", 4000)], securities
    )
    submit_version(version["id"], MANAGER_USER_ID)
    return {"securities": securities, "model": model, "model_version": version}


def _reject(api, model_version_id):
    return validate_success(
        api.reject_model_version(
            model_version_id,
            reject_model_version_payload(REJECTION_NOTE),
            make_compliance_officer_headers(COMPLIANCE_USER_ID),
        ),
        200,
    )


def _suspended_account_with_draft_invoice():
    """An account holding 2,500,000c of cash whose implementation dimension has
    been frozen, plus one DRAFT invoice over a 90-day period."""
    env = setup_funded_account(
        securities=[("ALFA", "Alfa Industrials", 10_000)],
        sleeves=[("ALFA", 10000)],
        sponsor_overrides={"revenue_share_bps": 3333},
        model_overrides={"base_fee_bps": 90},
        cash_cents=2_500_000,
    )
    env["account"] = suspend_account(env["account"]["id"])
    env["invoice"] = create_invoice(
        env["account"]["id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        average_daily_value_cents=AVERAGE_DAILY_VALUE_CENTS,
    )
    return env


def test_rejection_returns_the_version_to_draft_and_clears_the_submitter(api):
    """PRD §3.2: "Rejection is the mirror branch and closes the revision cycle `DRAFT → PENDING_APPROVAL → DRAFT`: it moves the version back to `DRAFT`, records the reviewer's supplied text as `rejection_note`, and clears `submitted_by_user_id` back to null so that the revised draft may be resubmitted by anyone at all, including the original author."

    Design: Difficulty/non_linear_state_machine/model_version_reject_closes_draft_cycle_and_resubmits
    """
    env = _version_pending_approval()
    model_version_id = env["model_version"]["id"]
    assert get_model_version(model_version_id)["status"] == "PENDING_APPROVAL"

    data = _reject(api, model_version_id)

    assert data["status"] == "DRAFT"
    assert data["rejection_note"] == REJECTION_NOTE
    assert data["submitted_by_user_id"] is None

    stored = get_model_version(model_version_id)
    assert stored["status"] == "DRAFT"
    assert stored["rejection_note"] == REJECTION_NOTE
    assert stored["submitted_by_user_id"] is None


def test_sleeves_become_editable_again_the_moment_the_version_returns_to_draft(api):
    """PRD §3.2: "Sleeves become editable again the moment the version returns to `DRAFT`."
    PRD §3.2: "A sleeve edit is only reachable while the version is in `DRAFT`; after each edit the platform recomputes `sleeve_count` as the length of the array and `total_target_weight_bps` as the sum of the sleeve targets, and advances the version's `version` by one."

    Design: Difficulty/non_linear_state_machine/model_version_reject_closes_draft_cycle_and_resubmits
    """
    env = _version_pending_approval()
    model_version_id = env["model_version"]["id"]
    securities = env["securities"]
    _reject(api, model_version_id)

    data = validate_success(
        api.replace_sleeves(
            model_version_id,
            sleeves_payload(
                [
                    {
                        "security_id": securities["ALFA"]["id"],
                        "target_weight_bps": 5000,
                    },
                    {
                        "security_id": securities["BETA"]["id"],
                        "target_weight_bps": 5000,
                    },
                ]
            ),
            make_portfolio_manager_headers(MANAGER_USER_ID),
        ),
        200,
    )

    assert data["status"] == "DRAFT"
    assert data["sleeve_count"] == 2
    assert data["total_target_weight_bps"] == 10000

    stored = get_model_version(model_version_id)
    assert stored["sleeve_count"] == 2
    assert stored["total_target_weight_bps"] == 10000


def test_the_same_row_traverses_the_submit_edge_again_under_a_new_submitter(api):
    """PRD §3.2: "Submission moves the version `DRAFT → PENDING_APPROVAL` and is performed by a `PortfolioManager`."
    PRD §3.2: "A successful submission records the acting `X-User-ID` as `submitted_by_user_id`, clears any `rejection_note` left over from a prior review round back to null, and advances the version's `version`."
    PRD §3.2: "A `PortfolioManager` opens a new version by naming the owning `model_id`; the platform assigns a `version_number` equal to the strategy's `version_count` plus one, starts the version in status `DRAFT`, and advances both the strategy's `version_count` and the strategy's own `version`."

    Design: Difficulty/non_linear_state_machine/model_version_reject_closes_draft_cycle_and_resubmits
    """
    env = _version_pending_approval()
    model_version_id = env["model_version"]["id"]
    securities = env["securities"]
    _reject(api, model_version_id)
    set_sleeves(
        model_version_id, [("ALFA", 5000), ("BETA", 5000)], securities
    )

    data = validate_success(
        api.submit_model_version(
            model_version_id, make_portfolio_manager_headers(MANAGER_2_USER_ID)
        ),
        200,
    )

    assert data["status"] == "PENDING_APPROVAL"
    assert data["submitted_by_user_id"] == MANAGER_2_USER_ID
    assert data["version_number"] == 1

    stored = get_model_version(model_version_id)
    assert stored["status"] == "PENDING_APPROVAL"
    assert stored["submitted_by_user_id"] == MANAGER_2_USER_ID
    assert stored["version_number"] == 1
    assert stored["id"] == model_version_id


def test_freezing_the_implementation_dimension_leaves_billing_free_to_advance(api):
    """PRD §3.4: "Suspension is reachable from `SYNCED`, from `DRIFTED` and from `PENDING_IMPLEMENTATION`, and drives `implementation_status` to `SUSPENDED` while leaving the billing dimension completely untouched — a suspended account keeps being invoiced."
    PRD §3.9: "Issuing it moves it `DRAFT → ISSUED`, stamps `issued_at`, adds its `gross_fee_cents` to the account's `fees_billed_ytd_cents`, and drives the account's billing dimension `CURRENT → INVOICED`; it requires the account's `billing_status` to be `CURRENT`, failing which it is refused with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/account_billing_and_implementation_dimensions_move_independently
    """
    env = _suspended_account_with_draft_invoice()
    account_id = env["account"]["id"]

    frozen = get_account(account_id)
    assert frozen["implementation_status"] == "SUSPENDED"
    assert frozen["billing_status"] == "CURRENT"

    invoice = validate_success(
        api.issue_fee_invoice(env["invoice"]["id"], BILLING), 200
    )
    assert invoice["status"] == "ISSUED"

    after_issue = get_account(account_id)
    assert after_issue["billing_status"] == "INVOICED"
    assert after_issue["implementation_status"] == "SUSPENDED"


def test_payment_returns_billing_to_current_while_the_freeze_holds(api):
    """PRD §2.9: "`implementation_status` tracks the account's relationship to its model and takes the values `PENDING_IMPLEMENTATION`, `SYNCED`, `DRIFTED` and `SUSPENDED`, starting at `SYNCED`. `billing_status` tracks the account's relationship to its fees and takes the values `CURRENT`, `INVOICED`, `DELINQUENT` and `WRITTEN_OFF`, starting at `CURRENT`. Neither dimension is a substate of the other."
    PRD §3.9: "**Payment** moves the invoice `ISSUED → PAID`, stamps `paid_at`, debits the account's `cash_cents` by `gross_fee_cents` — refusing with `ERR_INSUFFICIENT_CASH` when the cash will not cover it — and returns the billing dimension to `CURRENT` from either `INVOICED` or `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/account_billing_and_implementation_dimensions_move_independently
    """
    env = _suspended_account_with_draft_invoice()
    account_id = env["account"]["id"]
    validate_success(api.issue_fee_invoice(env["invoice"]["id"], BILLING), 200)

    invoice = validate_success(api.pay_fee_invoice(env["invoice"]["id"], BILLING), 200)
    assert invoice["status"] == "PAID"

    after_payment = get_account(account_id)
    assert after_payment["billing_status"] == "CURRENT"
    assert after_payment["implementation_status"] == "SUSPENDED"
    assert after_payment["cash_cents"] == 2434658


def test_the_gross_fee_stays_billed_year_to_date_across_the_payment(api):
    """PRD §3.9: "`gross_fee_cents` is the sum of those three already-rounded numbers."
    PRD §3.9: "Across that lifecycle the account's `fees_billed_ytd_cents` is, at every instant, the sum of `gross_fee_cents` over exactly those of its invoices currently in status `ISSUED`, `PAID` or `WRITTEN_OFF`."
    PRD §3.9: "Payment deliberately leaves `fees_billed_ytd_cents` untouched: the fee was billed when it was issued, and paying it does not un-bill it."

    Design: Difficulty/non_linear_state_machine/account_billing_and_implementation_dimensions_move_independently
    """
    env = _suspended_account_with_draft_invoice()
    account_id = env["account"]["id"]

    assert env["invoice"]["gross_fee_cents"] == 65342

    validate_success(api.issue_fee_invoice(env["invoice"]["id"], BILLING), 200)
    after_issue = get_account(account_id)
    assert after_issue["fees_billed_ytd_cents"] == 65342

    validate_success(api.pay_fee_invoice(env["invoice"]["id"], BILLING), 200)
    after_payment = get_account(account_id)
    assert after_payment["fees_billed_ytd_cents"] == 65342
    assert after_payment["implementation_status"] == "SUSPENDED"
