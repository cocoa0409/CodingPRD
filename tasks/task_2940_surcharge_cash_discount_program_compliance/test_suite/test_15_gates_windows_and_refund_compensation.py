"""Cross-entity gates, the two opposite window conventions, and the refund
compensation that puts the surcharge ledger back exactly where it started."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_refund,
    draft_artifact,
    get_success_data,
    issue_refund,
    list_total,
    program_status_action,
    read_artifact,
    read_complaint_case,
    read_merchant,
    read_program,
    read_refund,
    read_registration,
    read_terminal,
    read_transaction,
    set_clock,
    setup_configured_terminal,
    setup_draft_program,
    setup_enforcing_surcharge_estate,
    setup_program_pending_registration,
    setup_refundable_sale,
    terminal_action,
    validate_error,
    validate_success,
    void_refund,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    CLOCK_AUG_31,
    CLOCK_DEC_31,
    CLOCK_OCT_01,
    CLOCK_SEP_01,
    CLOCK_SEP_15,
    TS_AUG_31,
    TS_SEP_01,
)
from test_helpers.fixtures import (
    ADMIN,
    OFFICER_ONE,
    activate_program,
    attest_artifact,
    decide_registration,
    effectuate_registration,
)

CLOCK_AUG_30 = "2026-08-30T00:00:00Z"
CLOCK_SEP_30 = "2026-09-30T00:00:00Z"
CLOCK_OCT_30 = "2026-10-30T00:00:00Z"
TS_SEP_30 = "2026-09-30T00:00:00.000Z"
TS_OCT_30 = "2026-10-30T00:00:00.000Z"


# --------------------------------------------------------------------------
# Activation waits on the registration, which waits on the notice period
# --------------------------------------------------------------------------
def test_activation_is_refused_while_the_registration_is_only_acknowledged(api):
    """PRD §3.7: "at least one registration of the program is in state `EFFECTIVE`, else `ERR_REGISTRATION_NOT_EFFECTIVE`"
    PRD §3.5: "The bound is inclusive: the clock being exactly at `earliest_effective_at` passes, and the clock being strictly before it is rejected with `ERR_NOTICE_PERIOD_NOT_ELAPSED`."

    Design: Difficulty/cross_entity_state_dependency/program_activation_gated_on_network_registration_reaching_effective
    """
    ctx = setup_program_pending_registration()
    program_id = ctx["program"]["id"]
    registration_id = ctx["registration"]["id"]
    decide_registration(registration_id, "ACKNOWLEDGE")
    assert read_registration(registration_id)["state"] == "ACKNOWLEDGED"

    validate_error(
        api_client.activate_program(program_id, OFFICER_ONE),
        ApiErrorId.ERR_REGISTRATION_NOT_EFFECTIVE,
    )
    assert read_program(program_id)["status"] == "PENDING_REGISTRATION"

    validate_error(
        api_client.effectuate_network_registration(registration_id, OFFICER_ONE),
        ApiErrorId.ERR_NOTICE_PERIOD_NOT_ELAPSED,
    )
    assert read_registration(registration_id)["state"] == "ACKNOWLEDGED"


def test_the_gate_opens_the_moment_the_notice_period_is_reached(api):
    """PRD §3.5: "Consider a registration submitted at the clock's startup default of `2026-08-01T00:00:00Z`: its `earliest_effective_at` is `2026-08-31T00:00:00Z`, effectuating with the clock at `2026-08-30T23:59:59Z` fails, and effectuating with the clock at exactly `2026-08-31T00:00:00Z` succeeds."
    PRD §3.5: "A `ComplianceOfficer` effectuates an acknowledged registration, moving `ACKNOWLEDGED → EFFECTIVE` and stamping `effective_at` from the logical clock, but only if the clock has reached `earliest_effective_at`."

    Design: Difficulty/cross_entity_state_dependency/program_activation_gated_on_network_registration_reaching_effective
    """
    ctx = setup_program_pending_registration()
    program_id = ctx["program"]["id"]
    registration_id = ctx["registration"]["id"]
    assert ctx["registration"]["notice_days"] == 30
    assert ctx["registration"]["earliest_effective_at"] == TS_AUG_31
    decide_registration(registration_id, "ACKNOWLEDGE")

    set_clock(CLOCK_AUG_31)
    effectuated = effectuate_registration(registration_id)
    assert effectuated["state"] == "EFFECTIVE"
    assert effectuated["effective_at"] == TS_AUG_31

    activated = activate_program(program_id)
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] == TS_AUG_31


# --------------------------------------------------------------------------
# A terminal may not enforce while its program is suspended
# --------------------------------------------------------------------------
def test_a_configured_terminal_cannot_enforce_under_a_suspended_program(api):
    """PRD §3.8: "Three cross-entity conditions are checked against the bound program: its `status` must be `ACTIVE`, else `ERR_INVALID_PROGRAM_STATE`; its `disclosure_ready` must be true, else `ERR_DISCLOSURE_INCOMPLETE`; and if its `program_type` is `SURCHARGE`, the terminal's `debit_exclusion_enabled` must be true, else `ERR_DEBIT_EXCLUSION_NOT_ENABLED`."
    PRD §3.7: "first, every `Terminal` of the program in state `ENFORCING` moves to `QUARANTINED` with `quarantine_reason` set to `PROGRAM_SUSPENDED`"

    Design: Difficulty/cross_entity_state_dependency/terminal_enforcement_gated_on_owning_program_not_being_suspended
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=0)
    merchant_id = ctx["merchant"]["id"]
    terminal = setup_configured_terminal(merchant_id, ctx["program"]["id"], "T-AZ-001")
    assert terminal["state"] == "CONFIGURED"

    program_status_action(ctx["program"]["id"], "SUSPEND", reason="network inquiry pending")
    assert read_terminal(terminal["id"])["state"] == "CONFIGURED", (
        "the suspension sweep only reaches terminals that were already enforcing"
    )

    validate_error(
        api_client.terminal_state_action(
            terminal["id"],
            {"action": "ENFORCE"},
            {"X-User-ID": merchant_id, "X-User-Role": "MerchantOperator"},
        ),
        ApiErrorId.ERR_INVALID_PROGRAM_STATE,
    )
    refreshed = read_terminal(terminal["id"])
    assert refreshed["state"] == "CONFIGURED"
    assert refreshed["quarantine_reason"] == "NONE"
    assert read_merchant(merchant_id)["enforcing_terminal_count"] == 0


def test_resuming_the_program_lets_the_same_terminal_enforce(api):
    """PRD §3.8: "**`ENFORCE`**, available to a `MerchantOperator` only, requires the terminal to be in `CONFIGURED` and moves it to `ENFORCING`."
    PRD §3.8: "On success `quarantine_reason` is reset to `NONE`, `enforcing_terminal_count` is recomputed for the merchant, and the terminal's `version` is bumped by 1."

    Design: Difficulty/cross_entity_state_dependency/terminal_enforcement_gated_on_owning_program_not_being_suspended
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=0)
    merchant_id = ctx["merchant"]["id"]
    program_id = ctx["program"]["id"]
    terminal = setup_configured_terminal(merchant_id, program_id, "T-AZ-001")
    program_status_action(program_id, "SUSPEND", reason="network inquiry pending")

    resumed = program_status_action(program_id, "RESUME")
    assert resumed["status"] == "ACTIVE"
    assert resumed["disable_reason"] == "NONE"

    enforcing = terminal_action(terminal["id"], merchant_id, "ENFORCE")
    assert enforcing["state"] == "ENFORCING"
    assert enforcing["quarantine_reason"] == "NONE"
    assert read_merchant(merchant_id)["enforcing_terminal_count"] == 1
    assert (
        list_total(
            api_client.list_terminals(
                ADMIN, params={"program_id": program_id, "state": "ENFORCING"}
            )
        )
        == 1
    )


# --------------------------------------------------------------------------
# Two opposite window conventions
# --------------------------------------------------------------------------
def test_disclosure_windows_accept_exact_adjacency(api):
    """PRD §3.6: "An attested window is **half-open**: it runs from `effective_from` inclusive up to `expires_at` exclusive."
    PRD §3.6: "Because the windows are half-open, exact adjacency is accepted: a new window beginning at the very instant an existing window ends does not intersect it and is admitted."

    Design: Difficulty/resource_temporal_overlap/disclosure_artifact_half_open_windows_accept_exact_adjacency
    """
    ctx = setup_draft_program(jurisdiction_profile="NY", legal_name="Hudson Goods Inc", mcc="5999")
    program_id = ctx["program"]["id"]
    merchant_id = ctx["merchant"]["id"]
    first = draft_artifact(program_id, merchant_id, "ENTRY_SIGNAGE")
    second = draft_artifact(program_id, merchant_id, "ENTRY_SIGNAGE")

    attested_first = attest_artifact(first["id"], CLOCK_AUG_01, CLOCK_SEP_01)
    assert attested_first["state"] == "ATTESTED"
    assert attested_first["expires_at"] == TS_SEP_01

    attested_second = attest_artifact(second["id"], CLOCK_SEP_01, CLOCK_OCT_01)
    assert attested_second["state"] == "ATTESTED", (
        "a window opening exactly where its predecessor closed does not intersect it"
    )
    assert attested_second["effective_from"] == TS_SEP_01


def test_an_intersecting_signage_window_is_refused_while_a_different_type_is_free(api):
    """PRD §3.6: "Two attested artifacts of the same program and the same `artifact_type` may not have intersecting windows, and an attestation whose requested window intersects an existing `ATTESTED` artifact's window is rejected with `ERR_DISCLOSURE_WINDOW_OVERLAP`."
    PRD §3.6: "The artifact is created in state `DRAFT` with `effective_from`, `expires_at`, `attested_at`, and `attested_by_user_id` all null, and with `expired_reason` of `NONE`."

    Design: Difficulty/resource_temporal_overlap/disclosure_artifact_half_open_windows_accept_exact_adjacency
    """
    ctx = setup_draft_program(jurisdiction_profile="NY", legal_name="Hudson Goods Inc", mcc="5999")
    program_id = ctx["program"]["id"]
    merchant_id = ctx["merchant"]["id"]
    first = draft_artifact(program_id, merchant_id, "ENTRY_SIGNAGE")
    second = draft_artifact(program_id, merchant_id, "ENTRY_SIGNAGE")
    third = draft_artifact(program_id, merchant_id, "ENTRY_SIGNAGE")
    pos = draft_artifact(program_id, merchant_id, "POS_SIGNAGE")
    attest_artifact(first["id"], CLOCK_AUG_01, CLOCK_SEP_01)
    attest_artifact(second["id"], CLOCK_SEP_01, CLOCK_OCT_01)

    validate_error(
        api_client.attest_disclosure_artifact(
            third["id"],
            {"effective_from": CLOCK_AUG_31, "expires_at": CLOCK_SEP_15},
            {"X-User-ID": "officer-2", "X-User-Role": "ComplianceOfficer"},
        ),
        ApiErrorId.ERR_DISCLOSURE_WINDOW_OVERLAP,
    )
    unchanged = read_artifact(third["id"])
    assert unchanged["state"] == "DRAFT"
    assert unchanged["attested_at"] is None
    assert unchanged["effective_from"] is None

    attested_pos = attest_artifact(pos["id"], CLOCK_AUG_01, CLOCK_SEP_01)
    assert attested_pos["state"] == "ATTESTED", (
        "a different artifact type is a different resource, so the identical window is free"
    )

    assert (
        list_total(
            api_client.list_disclosure_artifacts(
                ADMIN,
                params={
                    "program_id": program_id,
                    "artifact_type": "ENTRY_SIGNAGE",
                    "state": "ATTESTED",
                },
            )
        )
        == 2
    )
    assert (
        list_total(
            api_client.list_disclosure_artifacts(
                ADMIN, params={"program_id": program_id, "state": "ATTESTED"}
            )
        )
        == 3
    )


def test_rate_windows_refuse_adjacency_yet_never_constrain_another_brand(api):
    """PRD §3.4: "A gap of fewer than 30 days against any peer is rejected with `ERR_RATE_WINDOW_BUFFER_VIOLATION`."
    PRD §3.4: "A candidate rule is compared against every existing rule of the *same* program, the *same* `brand`, and the *same* `product_tier`; rules of another brand or another tier never constrain it."

    Design: Difficulty/resource_temporal_overlap/rate_rule_closed_windows_reject_adjacency_and_require_thirty_day_buffer
    """
    ctx = setup_draft_program(
        rate_pct=2.0, effective_from=CLOCK_AUG_01, effective_to=CLOCK_SEP_30
    )
    program_id = ctx["program"]["id"]
    program = read_program(program_id)

    validate_error(
        api_client.create_rate_rule(
            program_id,
            {
                "brand": "VISA",
                "product_tier": "ALL",
                "rate_pct": 2.0,
                "effective_from": CLOCK_OCT_01,
                "effective_to": CLOCK_DEC_31,
                "expected_program_version": program["version"],
            },
            OFFICER_ONE,
        ),
        ApiErrorId.ERR_RATE_WINDOW_BUFFER_VIOLATION,
    )

    mastercard = validate_success(
        api_client.create_rate_rule(
            program_id,
            {
                "brand": "MASTERCARD",
                "product_tier": "ALL",
                "rate_pct": 2.0,
                "effective_from": CLOCK_OCT_01,
                "effective_to": CLOCK_DEC_31,
                "expected_program_version": program["version"],
            },
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert mastercard["brand"] == "MASTERCARD"


def test_a_gap_of_exactly_thirty_days_satisfies_the_rate_buffer(api):
    """PRD §3.4: "Because the comparison is a strict "fewer than", exact adjacency fails: a candidate starting at the very instant a peer ended yields a gap of zero and is refused."
    PRD §3.4: "This is the opposite convention from the disclosure windows of §3.6, where exact adjacency is accepted — the two boundary conventions are intentionally different and must not be unified."

    Design: Difficulty/resource_temporal_overlap/rate_rule_closed_windows_reject_adjacency_and_require_thirty_day_buffer
    """
    ctx = setup_draft_program(
        rate_pct=2.0, effective_from=CLOCK_AUG_01, effective_to=CLOCK_SEP_30
    )
    program_id = ctx["program"]["id"]
    incumbent_id = ctx["rate_rule"]["id"]

    api_client.create_rate_rule(
        program_id,
        {
            "brand": "MASTERCARD",
            "product_tier": "ALL",
            "rate_pct": 2.0,
            "effective_from": CLOCK_OCT_01,
            "effective_to": CLOCK_DEC_31,
            "expected_program_version": read_program(program_id)["version"],
        },
        OFFICER_ONE,
    )

    successor = validate_success(
        api_client.create_rate_rule(
            program_id,
            {
                "brand": "VISA",
                "product_tier": "ALL",
                "rate_pct": 2.0,
                "effective_from": CLOCK_OCT_30,
                "effective_to": CLOCK_DEC_31,
                "expected_program_version": read_program(program_id)["version"],
            },
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert successor["effective_from"] == TS_OCT_30

    assert (
        list_total(
            api_client.list_rate_rules(
                OFFICER_ONE, params={"program_id": program_id, "brand": "VISA"}
            )
        )
        == 2
    )
    assert (
        list_total(api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program_id}))
        == 3
    )
    assert get_success_data(api_client.get_rate_rule(incumbent_id, OFFICER_ONE))[
        "effective_to"
    ] == TS_SEP_30, "the incumbent rule is never truncated or merged"


# --------------------------------------------------------------------------
# Refund compensation
# --------------------------------------------------------------------------
def test_a_pending_refund_moves_no_money_at_all(api):
    """PRD §3.11: "A created refund begins in state `PENDING`, with the creating officer's `X-User-ID` recorded as `created_by_user_id` and with `issued_by_user_id`, `issued_at`, and `voided_at` all null. Creation moves no ledger field whatsoever: a pending refund is an intention, not a payment."

    Design: Difficulty/compensating_invariant/refund_issue_then_void_restores_net_surcharge_ledger
    """
    ctx = setup_refundable_sale()
    sale = ctx["transaction"]
    assert sale["surcharge_amount_cents"] == 219
    assert sale["total_amount_cents"] == 10219
    assert sale["outcome"] == "APPROVED_WITH_SURCHARGE"

    refund = create_refund(ctx["complaint_case"]["id"], sale["id"], 219)
    assert refund["state"] == "PENDING"
    assert refund["created_by_user_id"] == "officer-1"
    assert refund["issued_by_user_id"] is None
    assert refund["issued_at"] is None
    assert refund["voided_at"] is None

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 219
    assert merchant["net_surcharge_collected_cents"] == 219
    assert read_transaction(sale["id"])["refunded_surcharge_cents"] == 0
    assert read_complaint_case(ctx["complaint_case"]["id"])["refund_total_cents"] == 0


def test_issuing_a_refund_lowers_only_the_net_figure(api):
    """PRD §3.11: "On success the server stamps `issued_at` from the logical clock and `issued_by_user_id` from the acting `X-User-ID`, decreases the merchant's `net_surcharge_collected_cents` by `refund_amount_cents` while leaving `gross_surcharge_collected_cents` completely unchanged, increases the sale's `refunded_surcharge_cents` by the same amount, recomputes the case's `refund_total_cents`, and bumps both the merchant's `version` and the refund's `version` by 1."
    PRD §3.11: "and `net_surcharge_cents` as `per_line_rounded_surcharge_cents` minus that refunded total."

    Design: Difficulty/compensating_invariant/refund_issue_then_void_restores_net_surcharge_ledger
    """
    ctx = setup_refundable_sale()
    sale = ctx["transaction"]
    refund = create_refund(ctx["complaint_case"]["id"], sale["id"], 219)

    issued = issue_refund(refund["id"])
    assert issued["state"] == "ISSUED"
    assert issued["issued_by_user_id"] == "officer-2"
    assert issued["created_by_user_id"] == "officer-1"
    assert issued["issued_at"] == TS_AUG_31

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 219
    assert merchant["net_surcharge_collected_cents"] == 0
    assert read_transaction(sale["id"])["refunded_surcharge_cents"] == 219
    assert read_complaint_case(ctx["complaint_case"]["id"])["refund_total_cents"] == 219

    summary = get_success_data(
        api_client.get_settlement_summary(ctx["program"]["id"], OFFICER_ONE)
    )
    assert summary["per_line_rounded_surcharge_cents"] == 219
    assert summary["refunded_surcharge_cents"] == 219
    assert summary["net_surcharge_cents"] == 0


def test_voiding_an_issued_refund_restores_the_net_ledger_exactly(api):
    """PRD §3.11: "Voiding a refund in state `ISSUED` moves it `ISSUED → VOIDED`, stamps `voided_at` from the logical clock, increases the merchant's `net_surcharge_collected_cents` by `refund_amount_cents` — restoring it precisely to its pre-issuance value — decreases the sale's `refunded_surcharge_cents` by the same amount, recomputes the case's `refund_total_cents`, and bumps both the merchant's `version` and the refund's `version` by 1."
    PRD §3.11: "A case's `refund_total_cents` is always the sum of `refund_amount_cents` over that case's refunds in state `ISSUED` — pending and voided refunds are excluded — and a sale's `refunded_surcharge_cents` is likewise the sum over the `ISSUED` refunds referencing it."

    Design: Difficulty/compensating_invariant/refund_issue_then_void_restores_net_surcharge_ledger
    """
    ctx = setup_refundable_sale()
    sale = ctx["transaction"]
    refund = create_refund(ctx["complaint_case"]["id"], sale["id"], 219)
    issue_refund(refund["id"])

    voided = void_refund(refund["id"])
    assert voided["state"] == "VOIDED"
    assert voided["voided_at"] == TS_AUG_31

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 219, (
        "the gross figure never decreases for any reason"
    )
    assert merchant["net_surcharge_collected_cents"] == 219
    assert read_transaction(sale["id"])["refunded_surcharge_cents"] == 0
    assert read_complaint_case(ctx["complaint_case"]["id"])["refund_total_cents"] == 0

    summary = get_success_data(
        api_client.get_settlement_summary(ctx["program"]["id"], OFFICER_ONE)
    )
    assert summary["refunded_surcharge_cents"] == 0
    assert summary["net_surcharge_cents"] == 219

    program = read_program(ctx["program"]["id"])
    assert program["status"] == "ACTIVE"
    assert program["network_exposure_score"] == pytest.approx(20.00, abs=0.01)
    assert read_refund(refund["id"])["state"] == "VOIDED"
