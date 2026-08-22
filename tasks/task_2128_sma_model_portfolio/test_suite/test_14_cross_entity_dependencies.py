"""Cross-entity state dependencies: a transition that is legal on its own row
and is decided entirely by the state of a row belonging to another entity.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_distribution,
    create_distribution,
    create_fee_invoice_payload,
    get_account,
    get_success_data,
    list_trade_orders,
    make_sponsor_operator_headers,
    publish_successor_version,
    setup_account_pending_implementation,
    setup_funded_account,
    setup_platform,
    setup_written_off_account,
    validate_error,
    validate_success,
)

BILLING = TEST_USERS["billing_officer_headers"]


# --------------------------------------------------------------------------
# SponsorDistribution -> ModelVersion
# --------------------------------------------------------------------------
def _pending_distribution_on_superseded_version():
    """A distribution left PENDING on v1 while v2 is published, so the version
    it points at has slipped out of PUBLISHED underneath it."""
    env = setup_platform()
    env["distribution"] = create_distribution(
        env["sponsor"]["id"], env["model_version"]["id"]
    )
    env["model_version_v2"] = publish_successor_version(env)
    return env


def test_activation_is_refused_once_the_referenced_version_is_superseded(api):
    """PRD §3.3: "Activation is guarded across the entity boundary — the referenced version must *still* be `PUBLISHED` at the moment of activation, so a distribution left pending across an intervening publication can no longer be activated and is refused with `ERR_MODEL_VERSION_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/distribution_activate_depends_on_model_version_publication_state
    """
    env = _pending_distribution_on_superseded_version()

    response = api.activate_distribution(
        env["distribution"]["id"], make_sponsor_operator_headers(env["sponsor"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_MODEL_VERSION_NOT_PUBLISHED.value)


def test_refused_activation_leaves_the_distribution_pending_on_its_superseded_version(api):
    """PRD §3.3: "Activation belongs to the receiving sponsor and to nobody else: a `SponsorOperator` whose `X-User-ID` equals the distribution's `sponsor_id` moves it `PENDING → ACTIVE`, which stamps `activated_at` at the clock instant and advances the distribution's `version`."

    Design: Difficulty/cross_entity_state_dependency/distribution_activate_depends_on_model_version_publication_state
    """
    env = _pending_distribution_on_superseded_version()

    response = api.activate_distribution(
        env["distribution"]["id"], make_sponsor_operator_headers(env["sponsor"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_MODEL_VERSION_NOT_PUBLISHED.value)

    distribution = get_success_data(
        api.get_distribution(env["distribution"]["id"], BILLING)
    )
    assert distribution["status"] == "PENDING"
    assert distribution["activated_at"] is None

    version = get_success_data(
        api.get_model_version(env["model_version"]["id"], BILLING)
    )
    assert version["status"] == "SUPERSEDED"


# --------------------------------------------------------------------------
# FeeInvoice -> Account
# --------------------------------------------------------------------------
def _written_off_account_env():
    """An account whose only invoice was issued, declared delinquent and then
    written off, driving its billing dimension to the terminal state."""
    env = setup_funded_account()
    invoice, account = setup_written_off_account(env["account"]["id"])
    env["invoice"] = invoice
    env["account"] = account
    return env


def _second_period_invoice_response(api, account_id):
    return api.create_fee_invoice(
        create_fee_invoice_payload(
            account_id,
            period_start="2026-04-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            average_daily_value_cents=30_000_000,
        ),
        BILLING,
    )


def test_invoice_creation_is_refused_on_an_account_whose_fees_were_written_off(api):
    """PRD §2.6: "**Account not written off.** The target account has `billing_status` other than `WRITTEN_OFF`. Otherwise `ERR_ACCOUNT_WRITTEN_OFF` (409). This check guards exactly eight operations: cash deposits, transfer-in booking, implementation, drift evaluation, rebalance, reinstatement, harvest-proposal creation and fee-invoice creation."

    Design: Difficulty/cross_entity_state_dependency/invoice_creation_depends_on_account_billing_dimension
    """
    env = _written_off_account_env()

    response = _second_period_invoice_response(api, env["account"]["id"])
    validate_error(response, ApiErrorId.ERR_ACCOUNT_WRITTEN_OFF.value)


def test_refused_invoice_creation_writes_nothing_and_keeps_the_billed_total(api):
    """PRD §3.9: "Throughout all of it the account's `fees_billed_ytd_cents` is **not** reduced — a written-off fee stays billed, which is precisely what distinguishes a write-off from a void."

    Design: Difficulty/cross_entity_state_dependency/invoice_creation_depends_on_account_billing_dimension
    """
    env = _written_off_account_env()
    account_id = env["account"]["id"]

    response = _second_period_invoice_response(api, account_id)
    validate_error(response, ApiErrorId.ERR_ACCOUNT_WRITTEN_OFF.value)

    invoices = get_success_data(
        api.list_fee_invoices(BILLING, params={"account_id": account_id})
    )
    assert len(invoices) == 1

    account = get_account(account_id)
    assert account["fees_billed_ytd_cents"] == 65342
    assert account["billing_status"] == "WRITTEN_OFF"


# --------------------------------------------------------------------------
# Account -> SponsorDistribution
# --------------------------------------------------------------------------
_IMPL_SECURITIES = [
    ("ALFA", "Alfa Industrials", 10_000),
    ("BETA", "Beta Materials", 5_000),
    ("CETA", "Ceta Utilities", 2_500),
]
_IMPL_SLEEVES = [("ALFA", 5000), ("BETA", 3000), ("CETA", 2000)]
_IMPL_SUCCESSOR_SLEEVES = [("ALFA", 6000), ("BETA", 4000)]
_IMPL_POSITIONS = [
    ("ALFA", 1250, 12_500_000),
    ("BETA", 1500, 7_500_000),
    ("CETA", 1000, 2_500_000),
]


def _notified_account_without_successor_distribution():
    """The account is PENDING_IMPLEMENTATION on v2 through the publication
    fan-out, and no distribution of v2 has reached its sponsor platform yet."""
    return setup_account_pending_implementation(
        securities=_IMPL_SECURITIES,
        sleeves=_IMPL_SLEEVES,
        successor_sleeves=_IMPL_SUCCESSOR_SLEEVES,
        model_overrides={"drift_threshold_bps": 1000},
        sponsor_overrides={"implementation_lag_days": 2, "min_account_value_cents": 0},
        account_overrides={"cash_reserve_bps": 100},
        cash_cents=2_500_000,
        positions=_IMPL_POSITIONS,
        activate_successor_distribution=False,
    )


def test_implementation_is_refused_while_no_active_distribution_covers_the_clock(api):
    """PRD §3.5: "Beyond the account's own state, the operation requires a distribution in status `ACTIVE` whose sponsor is the account's sponsor and whose model version is the account's `pending_model_version_id`, and whose effective window covers the current clock instant — the clock at or after `effective_from` and strictly before `effective_until`, or at or after `effective_from` when `effective_until` is null."

    Design: Difficulty/cross_entity_state_dependency/implementation_depends_on_active_distribution_for_pending_version
    """
    env = _notified_account_without_successor_distribution()
    account_id = env["account"]["id"]

    response = api.run_implementation(
        account_id, make_sponsor_operator_headers(env["sponsor"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_DISTRIBUTION_NOT_ACTIVE.value)

    account = get_account(account_id)
    assert account["implementation_status"] == "PENDING_IMPLEMENTATION"
    assert account["pending_model_version_id"] == env["model_version_v2"]["id"]


def test_implementation_succeeds_once_the_sponsor_activates_the_distribution(api):
    """PRD §3.5: "Failing that, the request is refused with `ERR_DISTRIBUTION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/implementation_depends_on_active_distribution_for_pending_version
    """
    env = _notified_account_without_successor_distribution()
    account_id = env["account"]["id"]
    sponsor_headers = make_sponsor_operator_headers(env["sponsor"]["id"])

    validate_error(
        api.run_implementation(account_id, sponsor_headers),
        ApiErrorId.ERR_DISTRIBUTION_NOT_ACTIVE.value,
    )

    create_active_distribution(
        env["sponsor"]["id"],
        env["model_version_v2"]["id"],
        effective_from="2026-08-01T00:00:00Z",
    )

    result = validate_success(api.run_implementation(account_id, sponsor_headers), 200)
    assert result["generated_order_count"] == 3
    assert result["last_implementation_lag_days"] == 0
    assert result["implemented_late"] is False

    account = get_account(account_id)
    assert account["current_model_version_id"] == env["model_version_v2"]["id"]
    assert account["pending_model_version_id"] is None
    assert account["implementation_status"] == "SYNCED"
    assert account["last_implementation_lag_days"] == 0
    assert account["implemented_late"] is False


def test_orders_generated_after_the_distribution_is_activated(api):
    """PRD §3.5: "On success, `current_model_version_id` is set to the value of `pending_model_version_id`, which is then cleared to null; `last_implementation_lag_days` records the number of whole UTC days between `notified_at` and the current clock instant; `implemented_late` is set to true when the clock instant is strictly after `implementation_deadline` and to false otherwise; and the generator emits orders whose `source` is `IMPLEMENTATION` and whose `model_version_id` is the newly current version."

    Design: Difficulty/cross_entity_state_dependency/implementation_depends_on_active_distribution_for_pending_version
    """
    env = _notified_account_without_successor_distribution()
    account_id = env["account"]["id"]
    sponsor_headers = make_sponsor_operator_headers(env["sponsor"]["id"])

    validate_error(
        api.run_implementation(account_id, sponsor_headers),
        ApiErrorId.ERR_DISTRIBUTION_NOT_ACTIVE.value,
    )

    create_active_distribution(
        env["sponsor"]["id"],
        env["model_version_v2"]["id"],
        effective_from="2026-08-01T00:00:00Z",
    )
    validate_success(api.run_implementation(account_id, sponsor_headers), 200)

    orders = list_trade_orders(account_id=account_id, source="IMPLEMENTATION")
    assert len(orders) == 3

    ticker_of = {sec["id"]: ticker for ticker, sec in env["securities"].items()}
    assert [
        (ticker_of[o["security_id"]], o["side"], o["shares"]) for o in orders
    ] == [("ALFA", "BUY", 235), ("BETA", "BUY", 480), ("CETA", "SELL", 1000)]
