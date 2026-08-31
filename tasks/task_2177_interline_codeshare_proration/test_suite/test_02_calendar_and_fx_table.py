"""The clearing-house calendar and the FX quote ledger."""

from test_helpers import (
    ApiErrorId,
    OPERATOR,
    assert_append_only_row,
    assert_exchange_rate,
    assert_period,
    create_exchange_rate_payload,
    create_period_payload,
    new_exchange_rate,
    new_period,
    read_period,
    set_clock,
    validate_error,
    validate_success,
)


def test_settlement_currency_defaults_to_usd_when_omitted(api):
    """PRD §3.3: "A `ClearinghouseOperator` opens a settlement period with a `period_code`
    label such as "2026-08-P1", an inclusive `period_start` instant, an exclusive `period_end`
    instant strictly after it, a `submission_deadline` after which a submitted invoice
    attracts a penalty, a `rate_fixing_date` naming the instant whose FX quotes will be used
    at close, and optionally a `settlement_currency` in which every clearing-house balance for
    the period is expressed, defaulting to `USD`."
    PRD §3.3: "The period opens in `OPEN` status with `cleared_invoice_count` at zero and both
    `closed_at` and `settled_at` null."

    Design: Corner/entities/settlement_currency_defaults_to_usd_when_omitted
    """
    payload = create_period_payload()
    payload.pop("settlement_currency")

    period = validate_success(api.create_period(payload, OPERATOR), 201)
    assert_period(period)
    assert period["settlement_currency"] == "USD", (
        f"omitted settlement_currency must default to USD, got {period['settlement_currency']}"
    )
    assert period["status"] == "OPEN"
    assert period["cleared_invoice_count"] == 0
    assert period["closed_at"] is None
    assert period["settled_at"] is None


def test_settling_an_open_period_is_refused(api):
    """PRD §3.7: "Attempting to settle a period that is not `CLOSED` is refused with
    `ERR_PERIOD_NOT_CLOSED`."
    PRD §2.7: "**Period closed.** For settlement, the period is `CLOSED`; for an audit-sample
    draw, the named period is `CLOSED` or `SETTLED` — otherwise `ERR_PERIOD_NOT_CLOSED` (409).
    Applies to settlement-period settle and audit-sample draw."

    Design: Corner/state_machines/settling_an_open_period_returns_period_not_closed
    """
    period = new_period()

    resp = api.settle_period(period["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED.value)

    unchanged = read_period(period["id"])
    assert unchanged["status"] == "OPEN"
    assert unchanged["settled_at"] is None
    assert unchanged["version"] == 1, "a refused settle bumps nothing"


def test_exchange_rate_row_carries_no_updated_at_and_no_version(api):
    """PRD §2.4: "Two record types are append-only ledger entries and are never mutated after
    they are written: `ExchangeRate` and `ProrationRun`. These two carry `id` and `created_at`
    only — they have no `updated_at` field and no `version` field at all, and neither field
    should appear in their representations."

    Design: Corner/entities/exchange_rate_row_is_immutable_and_carries_no_version
    """
    payload = create_exchange_rate_payload(
        from_currency="EUR",
        to_currency="USD",
        effective_date="2026-08-05T00:00:00Z",
        rate_scaled=1085000,
    )
    rate = validate_success(api.create_exchange_rate(payload, OPERATOR), 201)

    assert_append_only_row(rate)
    assert_exchange_rate(rate)
    assert rate["from_currency"] == "EUR"
    assert rate["to_currency"] == "USD"
    assert rate["rate_scaled"] == 1085000
    assert "version" not in rate, "an append-only quote must not expose version"
    assert "updated_at" not in rate, "an append-only quote must not expose updated_at"


def test_duplicate_ordered_pair_and_date_quote_is_refused(api):
    """PRD §3.3: "No two quotes may share the same `from_currency`, `to_currency` and
    `effective_date` combination; a duplicate is refused with `ERR_DUPLICATE_EXCHANGE_RATE`."
    PRD §3.3: "Each quote names an ordered pair of `from_currency` and `to_currency`, which
    must differ, an `effective_date` instant from which it is the prevailing rate, and a
    strictly positive `rate_scaled` holding the rate multiplied by one million."

    Design: Corner/validations/duplicate_exchange_rate_triple_returns_error
    """
    first = new_exchange_rate(
        from_currency="EUR", to_currency="USD",
        effective_date="2026-08-05T00:00:00Z", rate_scaled=1085000,
    )

    resp = api.create_exchange_rate(
        create_exchange_rate_payload(
            from_currency="EUR", to_currency="USD",
            effective_date="2026-08-05T00:00:00Z", rate_scaled=1120000,
        ),
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXCHANGE_RATE.value)

    # The pair is ordered, so the mirrored quote for the same instant is a different row.
    mirrored = validate_success(
        api.create_exchange_rate(
            create_exchange_rate_payload(
                from_currency="USD", to_currency="EUR",
                effective_date="2026-08-05T00:00:00Z", rate_scaled=920000,
            ),
            OPERATOR,
        ),
        201,
    )
    assert mirrored["id"] != first["id"]
    assert mirrored["rate_scaled"] == 920000


# --------------------------------------------------------------------------- #
# Half-open settlement-period windows
# --------------------------------------------------------------------------- #
def test_back_to_back_settlement_periods_are_legal(api):
    """PRD §3.3: "Against every other period whose `status` is `OPEN` or `CLOSED`, a collision
    exists when the candidate's `period_start` is strictly before the other's `period_end`
    **and** the other's `period_start` is strictly before the candidate's `period_end`."
    PRD §3.3: "Sharing a boundary instant is therefore legal — back-to-back periods where one
    ends exactly where the next begins are the normal clearing-house calendar, not a conflict.
    A genuine intersection is refused with `ERR_PERIOD_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/settlement_period_windows_are_half_open_so_shared_boundary_is_legal
    """
    set_clock("2026-08-10T00:00:00Z")
    new_period(
        period_code="2026-08-P1",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
    )

    resp = api.create_period(
        create_period_payload(
            period_code="2026-09-P1",
            period_start="2026-09-01T00:00:00Z",
            period_end="2026-10-01T00:00:00Z",
            submission_deadline="2026-10-05T00:00:00Z",
            rate_fixing_date="2026-10-06T00:00:00Z",
        ),
        OPERATOR,
    )
    adjacent = validate_success(resp, 201)
    assert adjacent["status"] == "OPEN", (
        "a period starting at the incumbent's exclusive period_end is not a collision"
    )
    assert adjacent["period_code"] == "2026-09-P1"


def test_properly_intersecting_settlement_period_is_refused(api):
    """PRD §3.3: "Sharing a boundary instant is therefore legal — back-to-back periods where
    one ends exactly where the next begins are the normal clearing-house calendar, not a
    conflict. A genuine intersection is refused with `ERR_PERIOD_WINDOW_OVERLAP`."
    PRD §2.7: "**Period window overlap.** Half-open interval rule, detailed in §3.3 —
    otherwise `ERR_PERIOD_WINDOW_OVERLAP` (409). Applies to settlement-period creation."

    Design: Difficulty/resource_temporal_overlap/settlement_period_windows_are_half_open_so_shared_boundary_is_legal
    """
    set_clock("2026-08-10T00:00:00Z")
    august = new_period(
        period_code="2026-08-P1",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
    )
    september = new_period(
        period_code="2026-09-P1",
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z",
        submission_deadline="2026-10-05T00:00:00Z",
        rate_fixing_date="2026-10-06T00:00:00Z",
    )

    resp = api.create_period(
        create_period_payload(
            period_code="2026-08-P2",
            period_start="2026-08-15T00:00:00Z",
            period_end="2026-09-15T00:00:00Z",
            submission_deadline="2026-09-20T00:00:00Z",
            rate_fixing_date="2026-09-21T00:00:00Z",
        ),
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_WINDOW_OVERLAP.value)

    assert read_period(august["id"])["status"] == "OPEN"
    assert read_period(september["id"])["status"] == "OPEN"
