"""Transitions gated on the state of a different row: publication on the
premises' permit standing, and a refund on the application's decision.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    decide_application,
    ledger_rows,
    post_notice,
    read_agreement,
    read_application,
    read_license,
    read_listing,
    read_premises,
    set_clock,
    settle_escrow,
    setup_scenario,
    validate_error,
    validate_paginated,
    verify_zoning,
)

DEPOSIT_CENTS = 2405001


def _unverified_premises_under_review():
    """An application in review whose premises has never been zoning-verified."""
    return setup_scenario(
        stage="application_under_review",
        county_overrides={"quota_licenses_total": 100, "protest_window_days": 15},
        verify_zoning_step=False,
        application_fee=173250,
    )


def test_publication_is_refused_while_the_premises_permit_is_outstanding():
    """The application cannot be published because another row is not ready.

    PRD: "The premises' `suitability_status` must be `SUITABLE` or `CONDITIONAL`,
    and its `conditional_use_permit_status` must be either `NOT_REQUIRED` or
    `GRANTED` — an outstanding, pending or denied permit blocks publication with
    `ERR_PREMISES_UNSUITABLE` even though it does not block execution."

    PRD: "The application copies `license_id` and `premises_id` off the agreement,
    lands directly in `SUBMITTED` — its `status` enumeration being `SUBMITTED`,
    `UNDER_REVIEW`, `DEFICIENT`, `POSTED`, `PROTESTED`, `APPROVED` and `DENIED`, of
    which the last two are terminal — and starts with `deficiency_round_count` of
    0, `decision` null, `decided_at` null, `accepted_by_analyst_id` null,
    `last_deficiency_codes` null, and `posting_started_at`, `posting_ends_at` and
    `protest_deadline_at` all null."

    The permit standing is still `REQUIRED_NOT_FILED`, which the suitability ladder
    reads as `CONDITIONAL` with `CUP_OUTSTANDING` — enough to execute, not enough
    to publish.

    Design: Difficulty/cross_entity_state_dependency/posting_depends_on_premises_cup_state
    """
    scenario = _unverified_premises_under_review()
    premises = read_premises(scenario["premises_id"])
    assert premises["conditional_use_permit_status"] == "REQUIRED_NOT_FILED"
    assert premises["suitability_status"] == "CONDITIONAL"
    assert premises["suitability_reason_code"] == "CUP_OUTSTANDING"

    refused = api_client.post_notice(
        scenario["application_id"], scenario["analyst_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_PREMISES_UNSUITABLE.value, 422)

    application = read_application(scenario["application_id"])
    assert application["status"] == "UNDER_REVIEW"
    assert application["posting_started_at"] is None
    assert application["posting_ends_at"] is None
    assert application["protest_deadline_at"] is None


def test_granting_the_permit_on_the_other_row_unblocks_publication():
    """Nothing about the application changes; the premises does.

    PRD: "A `RegulatorAnalyst` records the zoning conditional-use outcome by
    supplying a new `conditional_use_permit_status`, and may in the same act
    correct the surveyed facts from a field inspection by supplying any of
    `zoning_code`, `distance_to_nearest_school_feet`,
    `distance_to_nearest_church_feet` and `census_tract_undue_concentration`;
    whatever is supplied overwrites what was there, the suitability verdict and
    reason code are recomputed, and the premises' `version` advances by one."

    PRD: "Publication then writes three instants. `posting_started_at` is the
    current logical instant. `posting_ends_at` is `posting_started_at` advanced by
    the county's `posting_period_days`. `protest_deadline_at` is
    `posting_started_at` advanced by whichever is smaller of the county's
    `posting_period_days` and its `protest_window_days`, so a county that accepts
    protests for a shorter span than it publishes closes the protest door before
    the publication window ends."

    Publication at the clock's 2026-08-01 start runs 30 days to 2026-08-31, while
    the county's shorter 15-day protest window closes on 2026-08-16.

    Design: Difficulty/cross_entity_state_dependency/posting_depends_on_premises_cup_state
    """
    scenario = _unverified_premises_under_review()
    blocked = api_client.post_notice(
        scenario["application_id"], scenario["analyst_headers"]
    )
    validate_error(blocked, ApiErrorId.ERR_PREMISES_UNSUITABLE.value, 422)

    cleared = verify_zoning(scenario["premises_id"], "GRANTED")
    assert cleared["conditional_use_permit_status"] == "GRANTED"
    assert cleared["suitability_status"] == "SUITABLE"
    assert cleared["suitability_reason_code"] == "NONE"

    posted = post_notice(scenario["application_id"])
    assert posted["status"] == "POSTED"
    assert_instant_equals(
        posted["posting_started_at"], "2026-08-01T00:00:00Z", "posting_started_at"
    )
    assert_instant_equals(
        posted["posting_ends_at"], "2026-08-31T00:00:00Z", "posting_ends_at"
    )
    assert_instant_equals(
        posted["protest_deadline_at"], "2026-08-16T00:00:00Z", "protest_deadline_at"
    )
    assert posted["deficiency_round_count"] == 0
    assert posted["decision"] is None


def _posted_application_with_held_escrow():
    """A published application over an escrow of 2405001 cents."""
    return setup_scenario(
        stage="application_posted",
        county_overrides={"quota_licenses_total": 100, "protest_window_days": 15},
        application_fee=173250,
        post_notice_at="2026-08-10T00:00:00Z",
    )


def test_a_refund_is_refused_while_the_application_is_merely_posted():
    """The money dimension is `HELD` in both attempts; the other row decides.

    PRD: "A **refund** advances `HELD → REFUNDED` and requires the agreement's
    transfer application to be `DENIED`, or it is refused with
    `ERR_TRANSFER_NOT_APPROVED`."

    PRD: "Each branch has its own cross-entity dependency, its own ledger shape and
    its own cascade, and the three are mutually exclusive."

    The refused settlement writes no ledger row, so the deposit row is still the
    only one on the agreement.

    Design: Difficulty/cross_entity_state_dependency/refund_settlement_depends_on_application_decision
    """
    scenario = _posted_application_with_held_escrow()
    assert scenario["application"]["status"] == "POSTED"

    refused = api_client.escrow_settlement(
        scenario["agreement_id"],
        {"disposition": "REFUND", "memo": "buyer asks for the money back early"},
        scenario["escrow_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_TRANSFER_NOT_APPROVED.value, 409)

    agreement = read_agreement(scenario["agreement_id"])
    assert agreement["escrow_status"] == "HELD"
    assert agreement["escrow_balance_cents"] == DEPOSIT_CENTS

    rows, meta = validate_paginated(
        api_client.get_agreement_escrow_ledger(
            scenario["agreement_id"], scenario["admin_headers"]
        )
    )
    assert meta["total_count"] == 1
    assert [row["entry_type"] for row in rows] == ["DEPOSIT"]


def test_the_same_refund_succeeds_once_the_application_reaches_denied():
    """A denial on the other row is the whole difference between the two calls.

    PRD: "A denial writes `decision` of `DENIED` and `decided_at` of the current
    logical instant, and its consequences are deliberately narrow."

    PRD: "No license field, no listing field and no agreement field is touched: the
    license stays `IN_ESCROW` until the escrow officer refunds, because denial alone
    never moves the license."

    PRD: "It appends exactly one ledger row of `entry_type` `REFUND_BUYER` whose
    `amount_cents` is the negative of the whole held balance and whose
    `balance_after_cents` is 0."

    Design: Difficulty/cross_entity_state_dependency/refund_settlement_depends_on_application_decision
    """
    scenario = _posted_application_with_held_escrow()
    early = api_client.escrow_settlement(
        scenario["agreement_id"],
        {"disposition": "REFUND", "memo": "buyer asks for the money back early"},
        scenario["escrow_headers"],
    )
    validate_error(early, ApiErrorId.ERR_TRANSFER_NOT_APPROVED.value, 409)

    set_clock("2026-09-10T00:00:00Z")
    denied = decide_application(
        scenario["application_id"], "DENIED", decision_note="undue concentration"
    )
    assert denied["status"] == "DENIED"
    assert denied["decision"] == "DENIED"
    assert read_license(scenario["license_id"])["status"] == "IN_ESCROW"

    refunded = settle_escrow(
        scenario["agreement_id"], "REFUND", memo="transfer denied"
    )
    assert refunded["escrow_status"] == "REFUNDED"
    assert refunded["escrow_balance_cents"] == 0
    assert_instant_equals(refunded["settled_at"], "2026-09-10T00:00:00Z", "settled_at")
    assert refunded["agreement_status"] == "TERMINATED"
    assert refunded["county_transfer_fee_cents"] is None
    assert refunded["commission_total_cents"] is None
    assert refunded["seller_net_cents"] is None

    rows = ledger_rows(scenario["agreement_id"])
    assert len(rows) == 2
    assert rows[1]["entry_type"] == "REFUND_BUYER"
    assert rows[1]["amount_cents"] == -DEPOSIT_CENTS
    assert rows[1]["balance_after_cents"] == 0

    assert read_license(scenario["license_id"])["status"] == "ACTIVE"
    assert read_listing(scenario["listing_id"])["status"] == "ACTIVE"
