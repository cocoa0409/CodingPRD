"""Collections: AWG garnishment variants and hearing window, cross-servicing
remittances and selector fallback, action termination, and the OCC guard on
collection events."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_action,
    collect_awg,
    create_awg_action,
    create_collect_payload,
    create_cross_servicing_action_payload,
    list_debt_collection_actions,
    read_collection_action,
    read_creditor,
    read_debt,
    set_logical_clock,
    setup_active_collection_action,
    setup_creditor_with_active_debt,
    terminate_action,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["treasury_operator_headers"]


def test_awg_provisional_vs_statutory_final(api):
    """PRD §3.7: "For `AWG`, creation computes a provisional
    `projected_per_period_cents`: fifteen percent of the estimated disposable
    pay, rounded half up to whole cents, with the statutory floor deliberately
    not applied at projection time."
    PRD §3.7: "the statutory garnishment is the lesser of fifteen percent of
    that disposable pay (rounded half up to whole cents) and the disposable pay
    minus a protected weekly floor of 21,750 cents — thirty hours at the $7.25
    federal minimum wage — with that subtraction floored at zero."

    Design: Difficulty/dual_variant_calc/awg_provisional_vs_statutory_final
    """
    creditor, debt = setup_creditor_with_active_debt(
        original_amount_cents=100000, debtor_tin="222-33-4444",
        delinquent_since="2026-02-01T00:00:00Z",
    )
    action = create_awg_action(
        debt, notice_sent_at="2026-08-20T00:00:00Z",
        disposable_pay_estimate_cents=25000,
    )
    # PROVISIONAL: round_half_up(0.15 * 25000) — the floor is not applied.
    assert action["projected_per_period_cents"] == 3750

    set_logical_clock("2026-09-05T00:00:00Z")  # hearing window elapsed 09-04
    action = activate_action(action)
    collect_awg(action, debt["id"], 25000)

    # STATUTORY_FINAL: min(3750, max(0, 25000 - 21750)) == 3250 — the variants
    # diverge on the same disposable pay.
    action_now = read_collection_action(action["id"])
    assert action_now["collected_total_cents"] == 3250
    assert read_debt(debt["id"])["current_balance_cents"] == 96750
    creditor_now = read_creditor(creditor["id"])
    assert creditor_now["remitted_gross_ytd_cents"] == 3250
    # fee = round_half_up(3250 * 0.03) == 98, net 3152 (pre-event gross 0).
    assert creditor_now["remitted_net_total_cents"] == 3152


def test_awg_zero_garnishment_at_floor_rejected(api):
    """PRD §3.7: "A garnishment that computes to zero is rejected with
    `ERR_COLLECT_AMOUNT_ZERO`."
    PRD §3.7: "the statutory garnishment is the lesser of fifteen percent of
    that disposable pay (rounded half up to whole cents) and the disposable pay
    minus a protected weekly floor of 21,750 cents".

    Design: Corner/calculations/awg_zero_garnishment_at_floor_rejected
    """
    _, debt = setup_creditor_with_active_debt(
        original_amount_cents=100000, debtor_tin="222-33-4444",
        delinquent_since="2026-02-01T00:00:00Z",
    )
    action = create_awg_action(
        debt, notice_sent_at="2026-08-20T00:00:00Z",
        disposable_pay_estimate_cents=21750,
    )
    # PROVISIONAL projection rounds 3262.5 half up.
    assert action["projected_per_period_cents"] == 3263

    set_logical_clock("2026-09-05T00:00:00Z")
    action = activate_action(action)
    debt_now = read_debt(debt["id"])
    # At the floor: min(round_half_up(0.15 * 21750), max(0, 21750 - 21750)) == 0.
    resp = api.collect_collection_action(
        action["id"],
        create_collect_payload(
            debt_now["version"], disposable_pay_cents=21750
        ),
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_COLLECT_AMOUNT_ZERO)

    assert read_debt(debt["id"])["current_balance_cents"] == 100000
    action_after = read_collection_action(action["id"])
    assert action_after["status"] == "ACTIVE"
    assert action_after["collected_total_cents"] == 0


def test_awg_hearing_window_boundary_15_days(api):
    """PRD §3.7: "An `AWG` action activates only once the logical clock has
    reached at least fifteen days after its `notice_sent_at` — equality
    activates, and an earlier attempt is `ERR_AWG_HEARING_WINDOW_OPEN`."

    Design: Corner/state_machines/awg_hearing_window_boundary_15_days
    """
    _, debt = setup_creditor_with_active_debt(
        original_amount_cents=100000, debtor_tin="222-33-4444",
        delinquent_since="2026-02-01T00:00:00Z",
    )
    action = create_awg_action(
        debt, notice_sent_at="2026-09-01T00:00:00Z",
        disposable_pay_estimate_cents=30000,
    )

    set_logical_clock("2026-09-15T23:59:59Z")  # one second short of 15 days
    resp_early = api.activate_collection_action(action["id"], OPERATOR)
    validate_error(resp_early, ApiErrorId.ERR_AWG_HEARING_WINDOW_OPEN)

    set_logical_clock("2026-09-16T00:00:00Z")  # exactly notice + 15 days
    resp_ok = api.activate_collection_action(action["id"], OPERATOR)
    assert validate_success(resp_ok)["status"] == "ACTIVE"


def test_terminate_collection_action_returns_debt_to_active(api):
    """PRD §3.7: "terminating an `INITIATED` or `ACTIVE` action moves it to
    `TERMINATED` and returns the debt to `ACTIVE`, since the terminated action
    was the only open one".

    Design: Corner/state_machines/terminate_collection_action_returns_debt_to_active
    """
    _, debt = setup_creditor_with_active_debt(
        original_amount_cents=100000, debtor_tin="222-33-4444",
        delinquent_since="2026-02-01T00:00:00Z",
    )
    action = create_awg_action(debt, disposable_pay_estimate_cents=30000)
    assert read_debt(debt["id"])["status"] == "IN_COLLECTION"

    terminated = terminate_action(action)
    assert terminated["status"] == "TERMINATED"
    assert read_debt(debt["id"])["status"] == "ACTIVE"


def test_collect_over_balance_returns_422(api):
    """PRD §3.7: "For `CROSS_SERVICING`, the operator instead supplies the
    agency's `remitted_amount_cents`, which must be greater than zero and no
    more than the debt's current balance — an excess is
    `ERR_COLLECT_EXCEEDS_BALANCE` (422)".

    Design: Corner/validations/collect_over_balance_returns_422
    """
    _, debt, action = setup_active_collection_action(
        action_type="CROSS_SERVICING", debt_amount_cents=50000
    )
    debt_now = read_debt(debt["id"])
    resp = api.collect_collection_action(
        action["id"],
        create_collect_payload(
            debt_now["version"], remitted_amount_cents=60000
        ),
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_COLLECT_EXCEEDS_BALANCE)
    assert read_debt(debt["id"])["current_balance_cents"] == 50000


def test_collection_action_field_conditionals(api):
    """PRD §3.7: "`AWG` requires a `notice_sent_at` — the start of the debtor's
    hearing window — and a `disposable_pay_estimate_cents`; `CROSS_SERVICING`
    forbids both fields, and mixing them up is `ERR_INVALID_REQUEST`."

    Design: Corner/validations/collection_action_field_conditionals
    """
    _, debt = setup_creditor_with_active_debt()
    # No collection agency registered: schema validation precedes the selector.
    resp_awg = api.create_collection_action(
        debt["id"],
        {"action_type": "AWG", "disposable_pay_estimate_cents": 30000},
        OPERATOR,
    )
    validate_error(resp_awg, ApiErrorId.ERR_INVALID_REQUEST)

    resp_xs = api.create_collection_action(
        debt["id"],
        {"action_type": "CROSS_SERVICING", "notice_sent_at": "2026-09-01T00:00:00Z"},
        OPERATOR,
    )
    err = validate_error(resp_xs, ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] != "ERR_NO_COLLECTION_AGENCY_AVAILABLE"

    assert list_debt_collection_actions(debt["id"]) == []
    assert read_debt(debt["id"])["status"] == "ACTIVE"


def test_occ_collect_stale_debt_version_returns_412(api):
    """PRD §2.7: "Recording a collection
    (`POST /collection-actions/{collectionActionId}/collect`) requires the
    non-optional request field `expected_debt_version`, carrying the client's
    last observed `version` of the debt under collection. A mismatch with the
    debt's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "here too the check is purely version-based and a strictly
    sequential retry with the old version fails."

    Design: Corner/cross_cutting_layers/occ_collect_stale_debt_version_returns_412
    """
    _, debt = setup_creditor_with_active_debt(
        original_amount_cents=100000, debtor_tin="222-33-4444",
        delinquent_since="2026-02-01T00:00:00Z",
    )
    action = create_awg_action(
        debt, notice_sent_at="2026-08-20T00:00:00Z",
        disposable_pay_estimate_cents=25000,
    )
    set_logical_clock("2026-09-05T00:00:00Z")
    action = activate_action(action)

    stale_version = read_debt(debt["id"])["version"]
    first = api.collect_collection_action(
        action["id"],
        create_collect_payload(stale_version, disposable_pay_cents=25000),
        OPERATOR,
    )
    validate_success(first)

    resp_stale = api.collect_collection_action(
        action["id"],
        create_collect_payload(stale_version, disposable_pay_cents=25000),
        OPERATOR,
    )
    validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION)

    assert read_debt(debt["id"])["current_balance_cents"] == 96750
    assert read_collection_action(action["id"])["collected_total_cents"] == 3250


def test_selector_empty_pool_returns_error(api):
    """PRD §3.7: "An empty pool fails the referral outright with
    `ERR_NO_COLLECTION_AGENCY_AVAILABLE` and leaves the debt unchanged."

    Design: Corner/cross_cutting_layers/selector_empty_pool_returns_error
    """
    _, debt = setup_creditor_with_active_debt()
    resp = api.create_collection_action(
        debt["id"], create_cross_servicing_action_payload(), OPERATOR
    )
    validate_error(resp, ApiErrorId.ERR_NO_COLLECTION_AGENCY_AVAILABLE)
    assert list_debt_collection_actions(debt["id"]) == []
    assert read_debt(debt["id"])["status"] == "ACTIVE"
