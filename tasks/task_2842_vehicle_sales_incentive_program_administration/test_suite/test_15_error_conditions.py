"""Error conditions of the incentive service.

Covers the entity-specific not-found codes, the composite protest path and its
terminal states, global code uniqueness across dead rows, chargeback
applicability and terminality, the batch state guards against the pay-date
check, eligibility footprint conflicts and the stair-step finalization gate.
"""
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import TEST_USERS, api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, MAX_LIMIT, SEP_01
from test_helpers.test_users import USER_AUDITOR_1, USER_FSM

# A third auditor identity, needed wherever a claim must be adjudicated by
# someone who is neither the delivery's validating auditor nor its adjudicator.
AUDITOR_3 = TEST_USERS["claims_auditor_3_headers"]

# One syntactically valid identifier that resolves to nothing.
MISSING_ID = "00000000-0000-4000-8000-0000000000aa"


# --- Entity-specific not-found codes ----------------------------------------

_NOT_FOUND_PROBES = [
    (
        "get-program",
        lambda: api_client.get_program(MISSING_ID, fx.CONTROLLER),
        "ERR_PROGRAM_NOT_FOUND",
    ),
    (
        "get-objective",
        lambda: api_client.get_objective(MISSING_ID, fx.FSM),
        "ERR_OBJECTIVE_NOT_FOUND",
    ),
    (
        "get-dealer",
        lambda: api_client.get_dealer(MISSING_ID, fx.CONTROLLER),
        "ERR_DEALER_NOT_FOUND",
    ),
    (
        "validate-delivery",
        lambda: api_client.validate_delivery(MISSING_ID, fx.VALIDATOR),
        "ERR_DELIVERY_NOT_FOUND",
    ),
    (
        "get-claim",
        lambda: api_client.get_claim(MISSING_ID, fx.VALIDATOR),
        "ERR_CLAIM_NOT_FOUND",
    ),
    (
        "recover-chargeback",
        lambda: api_client.recover_chargeback(MISSING_ID, fx.CONTROLLER),
        "ERR_CHARGEBACK_NOT_FOUND",
    ),
    (
        "get-batch",
        lambda: api_client.get_payment_batch(MISSING_ID, fx.CONTROLLER),
        "ERR_BATCH_NOT_FOUND",
    ),
]


@pytest.mark.parametrize(
    "probe,expected_error_id",
    [pytest.param(probe, expected, id=label) for label, probe, expected in _NOT_FOUND_PROBES],
)
def test_each_path_lookup_reports_its_own_not_found_code(probe, expected_error_id):
    """From an empty database the same syntactically valid identifier is offered to seven endpoints, and each answers with the not-found code of the entity its own path segment names rather than one shared generic code.

    PRD: "A missing resource yields the not-found code of the segment that failed — `ERR_PROGRAM_NOT_FOUND`, `ERR_OBJECTIVE_NOT_FOUND`, `ERR_PROTEST_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CHARGEBACK_NOT_FOUND` or `ERR_BATCH_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/every_path_lookup_reports_its_own_entity_specific_not_found_error_id
    """
    fx.set_clock(AUG_01)

    validate_error(probe(), expected_error_id)

    # Two of the seven probes are writes; neither may leave a partial row behind.
    _, program_meta = validate_paginated(api_client.list_programs(fx.CONTROLLER))
    assert program_meta["total_count"] == 0, program_meta
    _, delivery_meta = validate_paginated(api_client.list_deliveries(fx.VALIDATOR))
    assert delivery_meta["total_count"] == 0, delivery_meta
    _, claim_meta = validate_paginated(api_client.list_claims(fx.VALIDATOR))
    assert claim_meta["total_count"] == 0, claim_meta


# --- The composite protest path ---------------------------------------------


def _two_protested_objectives():
    """One stair-step program, two dealers, one objective each, one OPEN protest
    on each objective."""
    fx.set_clock(AUG_01)
    dealer_a = fx.register_dealer(
        dealer_code="CRN-D-PRA",
        name="Protest Dealer A",
        region_code="ZZPRO",
        historical_volume_units=8,
        market_opportunity_bps=0,
    )
    dealer_b = fx.register_dealer(
        dealer_code="CRN-D-PRB",
        name="Protest Dealer B",
        region_code="ZZPRO",
        historical_volume_units=8,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-X-PRO",
            name="Protest Scope Stair",
            incentive_type="DEALER_STAIR_STEP",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=0,
            budget_cents=1000000,
            stack_group="CRNPRO",
            priority_rank=434,
            tier_schedule=[
                {"tier_index": 1, "threshold_bps": 8000, "per_unit_bonus_cents": 30000}
            ],
            tier_bonus_mode="MARGINAL",
        ),
        rules=[{"region_code": "ZZPRO"}],
    )
    objective_a = fx.assign_objective(program["id"], dealer_a["id"])
    objective_b = fx.assign_objective(program["id"], dealer_b["id"])
    protest_a = fx.file_protest(
        objective_a["id"],
        dealer_a["id"],
        6,
        reason="Two units were fleet, not retail.",
    )
    protest_b = fx.file_protest(
        objective_b["id"],
        dealer_b["id"],
        7,
        reason="One unit was a demonstrator.",
    )
    a.assert_status(protest_a, "OPEN")
    a.assert_status(protest_b, "OPEN")
    a.assert_int_field(protest_a, "round_index", 1)
    return {
        "objective_a": objective_a,
        "objective_b": objective_b,
        "protest_a": protest_a,
        "protest_b": protest_b,
    }


def test_a_protest_id_is_scoped_to_the_objective_that_owns_it():
    """A real protest id resolved under a different objective is a not-found on the pair, and the correctly scoped denial that follows leaves the other dealer's objective and protest completely untouched.

    PRD: "The named protest must belong to the objective named in the path — otherwise `ERR_PROTEST_NOT_FOUND` — and must still be `OPEN`; resolving an already-resolved protest is refused with `ERR_PROTEST_ALREADY_RESOLVED`."

    Design: Corner/errors/a_protest_resolved_once_cannot_be_resolved_again_or_reached_through_another_objective
    """
    ctx = _two_protested_objectives()
    objective_a = ctx["objective_a"]
    objective_b = ctx["objective_b"]

    version_a = fx.objective_version(objective_a["id"])
    # protest_b exists, but not under objective_a: the pair must be validated.
    validate_error(
        api_client.resolve_protest(
            objective_a["id"],
            ctx["protest_b"]["id"],
            f.resolve_protest_payload("DENIED", version_a),
            fx.FSM,
        ),
        "ERR_PROTEST_NOT_FOUND",
    )

    denied = validate_success(
        api_client.resolve_protest(
            objective_a["id"],
            ctx["protest_a"]["id"],
            f.resolve_protest_payload("DENIED", version_a),
            fx.FSM,
        )
    )
    a.assert_status(denied, "DENIED")
    assert denied["resolved_by_user_id"] == USER_FSM, denied
    a.assert_null_fields(denied, ["resolved_units"])

    # A denial runs no cascade, so objective A keeps its original units and
    # falls back to the state it held before the round 1 protest.
    read_a = fx.read_objective(objective_a["id"])
    a.assert_int_field(read_a, "objective_units", objective_a["objective_units"])
    a.assert_status(read_a, "PROPOSED")
    a.assert_int_field(read_a, "protest_round", 1)

    # Dealer B was not collaterally resolved by the mis-scoped call.
    rows_b, meta_b = validate_paginated(api_client.list_protests(objective_b["id"], fx.FSM))
    a.assert_list_length(rows_b, 1, "protests of objective B")
    assert rows_b[0]["id"] == ctx["protest_b"]["id"], rows_b
    a.assert_status(rows_b[0], "OPEN")
    assert meta_b["total_count"] == 1, meta_b

    read_b = fx.read_objective(objective_b["id"])
    a.assert_int_field(read_b, "objective_units", objective_b["objective_units"])
    a.assert_status(read_b, "PROTESTED")


def test_a_resolved_protest_cannot_be_resolved_a_second_time():
    """Once a protest has been upheld it is terminal: resolving it again is refused even while the objective sits in PROTESTED under a later round, so the objective's own state cannot explain the refusal.

    PRD: "The named protest must belong to the objective named in the path — otherwise `ERR_PROTEST_NOT_FOUND` — and must still be `OPEN`; resolving an already-resolved protest is refused with `ERR_PROTEST_ALREADY_RESOLVED`."

    Design: Corner/errors/a_protest_resolved_once_cannot_be_resolved_again_or_reached_through_another_objective
    """
    ctx = _two_protested_objectives()
    objective_a = ctx["objective_a"]
    protest_a = ctx["protest_a"]

    upheld = fx.resolve_protest(objective_a["id"], protest_a["id"], "UPHELD")
    a.assert_status(upheld, "UPHELD")
    a.assert_int_field(upheld, "resolved_units", 6)
    a.assert_status(fx.read_objective(objective_a["id"]), "REVISED")

    # A second, later protest puts the objective back into PROTESTED, which is a
    # state that admits a resolve — so only the first protest's own terminality
    # can refuse the call below.
    fx.file_protest(
        objective_a["id"],
        objective_a["dealer_id"],
        5,
        reason="One further unit was a demonstrator.",
    )
    protested = fx.read_objective(objective_a["id"])
    a.assert_status(protested, "PROTESTED")
    a.assert_int_field(protested, "protest_round", 2)

    validate_error(
        api_client.resolve_protest(
            objective_a["id"],
            protest_a["id"],
            f.resolve_protest_payload("DENIED", protested["version"]),
            fx.FSM,
        ),
        "ERR_PROTEST_ALREADY_RESOLVED",
    )

    # The refusal was inert: the first protest is still UPHELD with its units.
    rows, _ = validate_paginated(api_client.list_protests(objective_a["id"], fx.FSM))
    first = next(row for row in rows if row["id"] == protest_a["id"])
    a.assert_status(first, "UPHELD")
    a.assert_int_field(first, "resolved_units", 6)
    a.assert_version(fx.read_objective(objective_a["id"]), protested["version"])


# --- Global code uniqueness --------------------------------------------------


def test_uniqueness_keys_stay_taken_by_rejected_and_cancelled_rows():
    """A REJECTED delivery still owns its VIN and a CANCELLED batch still owns its code, so both are refused on re-use, while the cancelled batch's pay period is immediately re-usable under a fresh code.

    PRD: "`program_code`, `dealer_code`, `vin` and `batch_code` are each globally unique, and each uniqueness scope includes rows that have reached a terminal state: a `program_code` is taken even by a `CLOSED` or `SUPERSEDED` program, a `vin` even by a `REJECTED` or `UNWOUND` delivery, and a `batch_code` even by a `CANCELLED` batch."

    Design: Corner/errors/code_uniqueness_is_global_and_survives_rejected_and_cancelled_rows
    """
    fx.set_clock("2026-08-06T00:00:00.000Z")
    dealer = fx.register_dealer(
        dealer_code="CRN-D-UNQ",
        name="Unique Motors",
        region_code="ZZUNQ",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    dealer_headers = make_dealer_headers(dealer["id"])
    delivery = fx.report_delivery(
        dealer["id"],
        vin="VIN2842UNQ0000001",
        msrp_cents=3100000,
        sale_date="2026-08-05T00:00:00.000Z",
        customer_region_code="ZZUNQ",
    )
    rejected = fx.reject_delivery(
        delivery["id"], fx.VALIDATOR, reason="VIN not in the build records"
    )
    a.assert_status(rejected, "REJECTED")

    batch = fx.open_batch(
        batch_code="CRN-B-UNQ",
        region_code="ZZUNQ",
        period_start=AUG_01,
        period_end="2026-08-15T00:00:00.000Z",
        scheduled_pay_date="2026-08-25T00:00:00.000Z",
    )
    cancelled = fx.cancel_batch(batch["id"], cancel_note="region reorganised")
    a.assert_status(cancelled, "CANCELLED")

    # Every other field differs, and the code alone still refuses the row.
    validate_error(
        api_client.create_dealer(
            f.create_dealer_payload(
                dealer_code="CRN-D-UNQ",
                name="Unique Motors Clone",
                region_code="ZZOTHER",
                historical_volume_units=9,
                market_opportunity_bps=500,
            ),
            fx.CONTROLLER,
        ),
        "ERR_DUPLICATE_DEALER_CODE",
    )

    validate_error(
        api_client.create_delivery(
            f.create_delivery_payload(
                dealer["id"],
                vin="VIN2842UNQ0000001",
                model_code="SDN3",
                trim_code="SPORT",
                build_date="2026-06-02T00:00:00.000Z",
                msrp_cents=3200000,
                sale_date="2026-08-06T00:00:00.000Z",
                customer_region_code="ZZUNQ",
            ),
            dealer_headers,
        ),
        "ERR_DUPLICATE_VIN",
    )

    validate_error(
        api_client.create_payment_batch(
            f.create_payment_batch_payload(
                batch_code="CRN-B-UNQ",
                region_code="ZZUNQ",
                period_start="2026-09-01T00:00:00.000Z",
                period_end="2026-09-15T00:00:00.000Z",
                scheduled_pay_date="2026-09-25T00:00:00.000Z",
            ),
            fx.CONTROLLER,
        ),
        "ERR_DUPLICATE_BATCH_CODE",
    )

    # The cancelled batch's period, unlike its code, is free again.
    reused_period = validate_success(
        api_client.create_payment_batch(
            f.create_payment_batch_payload(
                batch_code="CRN-B-UNQ-2",
                region_code="ZZUNQ",
                period_start=AUG_01,
                period_end="2026-08-15T00:00:00.000Z",
                scheduled_pay_date="2026-08-25T00:00:00.000Z",
            ),
            fx.CONTROLLER,
        ),
        201,
    )
    a.assert_status(reused_period, "OPEN")
    assert reused_period["period_start"] == "2026-08-01T00:00:00.000Z", reused_period

    # A fresh VIN under the same dealer is accepted, so the refusals above were
    # about the keys and not about the dealer.
    fresh_vin = validate_success(
        api_client.create_delivery(
            f.create_delivery_payload(
                dealer["id"],
                vin="VIN2842UNQ0000002",
                msrp_cents=3100000,
                sale_date="2026-08-05T00:00:00.000Z",
                customer_region_code="ZZUNQ",
            ),
            dealer_headers,
        ),
        201,
    )
    a.assert_status(fresh_vin, "REPORTED")


# --- Chargeback applicability and terminality --------------------------------


def test_chargeback_applicability_and_the_recovered_terminal_state():
    """A chargeback is refused from three different payment states — UNPAID before approval, UNPAID after approval and CHARGED_BACK after recovery — is accepted only while PAID, and once RECOVERED the chargeback refuses both a second recovery and a write-off.

    PRD: "The claim's `payment_status` must be `SCHEDULED` or `PAID`; a claim still `UNPAID`, or one already `CHARGED_BACK`, has nothing to recover and the attempt is refused with `ERR_CHARGEBACK_NOT_APPLICABLE`."
    PRD: "Resolving a chargeback that is not `PENDING` is refused with `ERR_CHARGEBACK_INVALID_STATE`."

    Design: Corner/errors/chargeback_applicability_and_the_recovered_terminal_state_are_both_enforced
    """
    fx.set_clock("2026-08-10T00:00:00.000Z")
    dealer = fx.register_dealer(
        dealer_code="CRN-D-CBK",
        name="Chargeback Motors",
        region_code="ZZCBK",
        historical_volume_units=5,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-X-CBK",
            name="Chargeback Cash",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=50000,
            budget_cents=1000000,
            stack_group="CRNCBK",
            priority_rank=435,
        ),
        rules=[{"region_code": "ZZCBK"}],
    )
    delivery = fx.report_delivery(
        dealer["id"],
        vin="VIN2842CBK0000001",
        build_date="2026-06-15T00:00:00.000Z",
        msrp_cents=3100000,
        sale_date="2026-08-05T00:00:00.000Z",
        customer_region_code="ZZCBK",
    )
    fx.validate_delivery(delivery["id"])
    claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 50000)
    a.assert_claim_dimensions(claim, "SUBMITTED", "UNPAID")
    batch = fx.open_batch(
        batch_code="CRN-B-CBK",
        region_code="ZZCBK",
        period_start=AUG_01,
        period_end="2026-08-15T00:00:00.000Z",
        scheduled_pay_date="2026-08-20T00:00:00.000Z",
    )

    # (1) Nobody has approved the claim yet, so there is nothing to recover.
    validate_error(
        api_client.create_chargeback(
            claim["id"], f.create_chargeback_payload("UNWOUND_DEAL"), fx.VALIDATOR
        ),
        "ERR_CHARGEBACK_NOT_APPLICABLE",
    )

    approved = fx.adjudicate_claim(claim["id"], "APPROVE")
    a.assert_money(approved, "approved_amount_cents", 50000)
    a.assert_claim_dimensions(approved, "VALIDATED", "UNPAID")

    # A third auditor asks for the opposite decision and is still refused.
    validate_error(
        api_client.adjudicate_claim(
            claim["id"],
            f.adjudicate_payload("REJECT", rejection_error_id="ERR_DUPLICATE_CLAIM"),
            AUDITOR_3,
        ),
        "ERR_CLAIM_ALREADY_ADJUDICATED",
    )

    # (2) Approval does not pay, so the applicability rule still refuses: it
    # reads payment_status, not validation_status.
    validate_error(
        api_client.create_chargeback(
            claim["id"], f.create_chargeback_payload("UNWOUND_DEAL"), fx.VALIDATOR
        ),
        "ERR_CHARGEBACK_NOT_APPLICABLE",
    )

    scheduled = fx.schedule_claims(batch["id"], [claim["id"]])
    a.assert_int_field(scheduled, "claim_count", 1)
    a.assert_money(scheduled, "total_cents", 50000)
    fx.lock_batch(batch["id"])
    # disburse_batch moves the clock to the batch's scheduled_pay_date, 2026-08-20.
    a.assert_status(fx.disburse_batch(batch["id"]), "DISBURSED")

    chargeback = validate_success(
        api_client.create_chargeback(
            claim["id"], f.create_chargeback_payload("UNWOUND_DEAL"), fx.VALIDATOR
        ),
        201,
    )
    a.assert_chargeback_shape(chargeback)
    a.assert_money(chargeback, "amount_cents", 50000)
    a.assert_status(chargeback, "PENDING")
    assert chargeback["created_by_user_id"] == USER_AUDITOR_1, chargeback

    charged_back = fx.read_claim(claim["id"])
    a.assert_claim_dimensions(charged_back, "VALIDATED", "CHARGED_BACK")
    a.assert_null_fields(charged_back, ["payment_batch_id"])

    # (3) The third distinct payment_status that refuses, which is why the rule
    # cannot be written as a single inequality against PAID.
    validate_error(
        api_client.create_chargeback(
            claim["id"], f.create_chargeback_payload("UNWOUND_DEAL"), fx.VALIDATOR
        ),
        "ERR_CHARGEBACK_NOT_APPLICABLE",
    )

    recovered = validate_success(
        api_client.recover_chargeback(chargeback["id"], fx.CONTROLLER)
    )
    a.assert_status(recovered, "RECOVERED")
    assert recovered["recovered_at"] == "2026-08-20T00:00:00.000Z", recovered

    # RECOVERED is terminal against both remaining triggers.
    validate_error(
        api_client.recover_chargeback(chargeback["id"], fx.CONTROLLER),
        "ERR_CHARGEBACK_INVALID_STATE",
    )
    validate_error(
        api_client.write_off_chargeback(
            chargeback["id"], fx.CONTROLLER, {"write_off_note": "dealer disputes the unwind"}
        ),
        "ERR_CHARGEBACK_INVALID_STATE",
    )

    rows, meta = validate_paginated(
        api_client.list_chargebacks(claim["id"], fx.CONTROLLER)
    )
    assert meta["total_count"] == 1, meta
    a.assert_list_length(rows, 1, "chargebacks")
    a.assert_status(rows[0], "RECOVERED")


# --- Batch state guards against the pay-date check ---------------------------


def test_batch_state_guard_outranks_the_pay_date_check_at_every_action():
    """An OPEN batch disbursed before its pay date violates the transition rule and the timing rule at once and reports the transition failure, then the timing boundary is probed one millisecond early and again at the exact scheduled instant.

    PRD: "Checks are evaluated in the following order, and the first failure short-circuits the request; no side effect of any kind is applied to any entity once a check fails."
    PRD: "Disbursement moves the batch `LOCKED → DISBURSED` and is refused with `ERR_BATCH_INVALID_STATE` from any other status. The logical clock must have reached the batch's `scheduled_pay_date`; a disbursement attempted while the clock is strictly earlier than that instant is refused with `ERR_PAY_DATE_NOT_REACHED`."

    Design: Corner/errors/batch_state_guards_outrank_the_pay_date_check_which_admits_the_exact_instant
    """
    fx.set_clock("2026-08-10T00:00:00.000Z")
    dealer = fx.register_dealer(
        dealer_code="CRN-D-BAT",
        name="Batch Guard Motors",
        region_code="ZZBAT",
        historical_volume_units=5,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-X-BAT",
            name="Batch Guard Cash",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=40000,
            budget_cents=500000,
            stack_group="CRNBAT",
            priority_rank=436,
        ),
        rules=[{"region_code": "ZZBAT"}],
    )
    delivery = fx.report_delivery(
        dealer["id"],
        vin="VIN2842BAT0000001",
        build_date="2026-06-10T00:00:00.000Z",
        msrp_cents=3000000,
        sale_date="2026-08-04T00:00:00.000Z",
        customer_region_code="ZZBAT",
    )
    fx.validate_delivery(delivery["id"])
    claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 40000)
    approved = fx.adjudicate_claim(claim["id"], "APPROVE")
    a.assert_money(approved, "approved_amount_cents", 40000)
    batch = fx.open_batch(
        batch_code="CRN-B-BAT",
        region_code="ZZBAT",
        period_start=AUG_01,
        period_end="2026-08-15T00:00:00.000Z",
        scheduled_pay_date="2026-08-25T00:00:00.000Z",
    )
    a.assert_status(batch, "OPEN")

    # The clock is 2026-08-10 and the batch is OPEN, so this one request breaks
    # the transition rule and the pay-date rule together.
    validate_error(
        api_client.disburse_batch(batch["id"], fx.CONTROLLER), "ERR_BATCH_INVALID_STATE"
    )

    scheduled = fx.schedule_claims(batch["id"], [claim["id"]])
    a.assert_int_field(scheduled, "claim_count", 1)
    a.assert_money(scheduled, "total_cents", 40000)
    locked = fx.lock_batch(batch["id"])
    a.assert_status(locked, "LOCKED")

    # LOCKED admits only disburse, and cancel is confined to OPEN.
    validate_error(
        api_client.lock_batch(batch["id"], fx.CONTROLLER), "ERR_BATCH_INVALID_STATE"
    )
    validate_error(
        api_client.schedule_claims(
            batch["id"], f.schedule_claims_payload([claim["id"]]), fx.CONTROLLER
        ),
        "ERR_BATCH_INVALID_STATE",
    )
    validate_error(
        api_client.cancel_batch(batch["id"], fx.CONTROLLER, {"cancel_note": "too late"}),
        "ERR_BATCH_INVALID_STATE",
    )

    # One millisecond short of the scheduled instant: the state is legitimate
    # now, so only the timing is wrong.
    fx.set_clock("2026-08-24T23:59:59.999Z")
    validate_error(
        api_client.disburse_batch(batch["id"], fx.CONTROLLER), "ERR_PAY_DATE_NOT_REACHED"
    )

    # The comparison admits the boundary instant itself.
    fx.set_clock("2026-08-25T00:00:00.000Z")
    disbursed = validate_success(api_client.disburse_batch(batch["id"], fx.CONTROLLER))
    a.assert_status(disbursed, "DISBURSED")
    assert disbursed["disbursed_at"] == "2026-08-25T00:00:00.000Z", disbursed
    a.assert_money(disbursed, "total_cents", 40000)
    a.assert_int_field(disbursed, "held_claim_count", 0)

    paid = fx.read_claim(claim["id"])
    a.assert_claim_dimensions(paid, "VALIDATED", "PAID")
    assert paid["paid_at"] == "2026-08-25T00:00:00.000Z", paid

    # DISBURSED is terminal, so the money is never paid twice.
    validate_error(
        api_client.disburse_batch(batch["id"], fx.CONTROLLER), "ERR_BATCH_INVALID_STATE"
    )
    validate_error(
        api_client.cancel_batch(batch["id"], fx.CONTROLLER, {"cancel_note": "reverse it"}),
        "ERR_BATCH_INVALID_STATE",
    )
    assert fx.read_claim(claim["id"])["paid_at"] == paid["paid_at"], "paid_at moved"


# --- Eligibility footprint conflicts ----------------------------------------


def test_footprint_conflict_keys_on_the_triple_and_the_closed_interval():
    """A one-day touch at build_date_to == build_date_from conflicts while an adjacent-but-disjoint pair does not, and a null trim_code collides only with another null trim_code rather than with every explicit trim.

    PRD: "If the row being appended matches an existing row of the **same** program on all three of `model_code`, `trim_code` and `region_code`, and its closed build-date interval intersects that existing row's closed build-date interval, the append is refused with `ERR_ELIGIBILITY_RULE_CONFLICT`."

    Design: Corner/errors/eligibility_footprint_conflict_keys_on_the_triple_and_the_closed_build_interval
    """
    fx.set_clock(AUG_01)
    program = fx.create_draft_program(
        payload=f.create_program_payload(
            program_code="CRN-X-ELG",
            name="Footprint Cash",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=30000,
            budget_cents=900000,
            stack_group="CRNELG",
            priority_rank=437,
        )
    )
    a.assert_status(program, "DRAFT")
    seed = validate_success(
        api_client.create_eligibility_rule(
            program["id"],
            f.create_eligibility_rule_payload(
                trim_code="BASE",
                region_code="ZZELG",
                build_date_from="2026-05-01T00:00:00.000Z",
                build_date_to="2026-07-31T00:00:00.000Z",
            ),
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_eligibility_rule_shape(seed)
    assert seed["trim_code"] == "BASE", seed
    a.assert_money(seed, "min_msrp_cents", 0)
    assert seed["allowed_deal_types"] == ["CASH"], seed

    # [2026-05-01, 2026-07-31] and [2026-07-31, 2026-08-31] share exactly the
    # single instant 2026-07-31, and a closed interval counts that as an
    # intersection.
    validate_error(
        api_client.create_eligibility_rule(
            program["id"],
            f.create_eligibility_rule_payload(
                trim_code="BASE",
                region_code="ZZELG",
                build_date_from="2026-07-31T00:00:00.000Z",
                build_date_to="2026-08-31T00:00:00.000Z",
                allowed_deal_types=["FINANCE"],
            ),
            fx.DESIGNER,
        ),
        "ERR_ELIGIBILITY_RULE_CONFLICT",
    )

    # One day later the intervals are adjacent but disjoint.
    disjoint = validate_success(
        api_client.create_eligibility_rule(
            program["id"],
            f.create_eligibility_rule_payload(
                trim_code="BASE",
                region_code="ZZELG",
                build_date_from="2026-08-01T00:00:00.000Z",
                build_date_to="2026-08-31T00:00:00.000Z",
                allowed_deal_types=["FINANCE"],
            ),
            fx.DESIGNER,
        ),
        201,
    )
    assert disjoint["build_date_from"] == "2026-08-01T00:00:00.000Z", disjoint

    # trim_code is part of the conflict key, over the same dates and region.
    other_trim = validate_success(
        api_client.create_eligibility_rule(
            program["id"],
            f.create_eligibility_rule_payload(
                trim_code="SPORT",
                region_code="ZZELG",
                build_date_from="2026-05-01T00:00:00.000Z",
                build_date_to="2026-07-31T00:00:00.000Z",
            ),
            fx.DESIGNER,
        ),
        201,
    )
    assert other_trim["trim_code"] == "SPORT", other_trim

    # A wildcard rule with a null trim does not conflict with the BASE rule
    # over identical dates: null is compared as a value.
    wildcard = validate_success(
        api_client.create_eligibility_rule(
            program["id"],
            f.create_eligibility_rule_payload(
                region_code="ZZELG",
                build_date_from="2026-05-01T00:00:00.000Z",
                build_date_to="2026-07-31T00:00:00.000Z",
            ),
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_null_fields(wildcard, ["trim_code"])
    assert wildcard["allowed_deal_types"] == ["CASH"], wildcard

    # A second null-trim rule whose window sits inside the first one's does
    # conflict, so null is not "matches anything".
    validate_error(
        api_client.create_eligibility_rule(
            program["id"],
            {
                "model_code": "MX5",
                "region_code": "ZZELG",
                "build_date_from": "2026-06-01T00:00:00.000Z",
                "build_date_to": "2026-06-30T00:00:00.000Z",
            },
            fx.DESIGNER,
        ),
        "ERR_ELIGIBILITY_RULE_CONFLICT",
    )

    # region_code and model_code are the other two components of the key.
    other_region = validate_success(
        api_client.create_eligibility_rule(
            program["id"],
            f.create_eligibility_rule_payload(
                trim_code="BASE",
                region_code="ZZELG2",
                build_date_from="2026-05-01T00:00:00.000Z",
                build_date_to="2026-07-31T00:00:00.000Z",
            ),
            fx.DESIGNER,
        ),
        201,
    )
    assert other_region["region_code"] == "ZZELG2", other_region

    other_model = validate_success(
        api_client.create_eligibility_rule(
            program["id"],
            f.create_eligibility_rule_payload(
                model_code="SDN3",
                trim_code="BASE",
                region_code="ZZELG",
                build_date_from="2026-05-01T00:00:00.000Z",
                build_date_to="2026-07-31T00:00:00.000Z",
            ),
            fx.DESIGNER,
        ),
        201,
    )
    assert other_model["model_code"] == "SDN3", other_model

    # The seed plus the five accepted rows; the two conflicts persisted nothing.
    rows, meta = validate_paginated(
        api_client.list_eligibility_rules(
            program["id"], fx.DESIGNER, {"limit": MAX_LIMIT}
        )
    )
    assert meta["total_count"] == 6, meta
    a.assert_list_length(rows, 6, "eligibility rules")


# --- The stair-step finalization gate ---------------------------------------


def test_a_stair_step_claim_needs_a_final_objective_every_time():
    """The same code covers a PROPOSED objective and a dealer with no objective at all, and it fires again after a successful adjudication once a fresh protest un-finalizes the objective, so FINAL is a revocable gate rather than a one-time unlock.

    PRD: "For a claim whose `claim_type` is `STAIR_STEP_BONUS`, a dealer objective matching the claim's `program_id` and `dealer_id` must exist and must be in `FINAL`; a missing objective, or one in any other status, is refused with `ERR_OBJECTIVE_NOT_FINAL`."

    Design: Corner/errors/a_stair_step_claim_needs_a_final_objective_and_finalization_is_revocable
    """
    # The clock sits close behind the sale dates so that every delivery reports
    # inside the permitted lag and can therefore be validated.
    fx.set_clock("2026-08-07T00:00:00.000Z")
    dealer_a = fx.register_dealer(
        dealer_code="CRN-D-FNA",
        name="Final Gate A",
        region_code="ZZFNL",
        historical_volume_units=5,
        market_opportunity_bps=0,
    )
    dealer_b = fx.register_dealer(
        dealer_code="CRN-D-FNB",
        name="Final Gate B",
        region_code="ZZFNL",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-X-FNL",
            name="Final Gate Stair",
            incentive_type="DEALER_STAIR_STEP",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=0,
            budget_cents=2000000,
            stack_group="CRNFNL",
            priority_rank=438,
            tier_schedule=[
                {"tier_index": 1, "threshold_bps": 8000, "per_unit_bonus_cents": 30000}
            ],
            tier_bonus_mode="MARGINAL",
        ),
        rules=[{"region_code": "ZZFNL"}],
    )
    objective_a = fx.assign_objective(program["id"], dealer_a["id"])
    a.assert_status(objective_a, "PROPOSED")
    a.assert_int_field(objective_a, "objective_units", 5)

    deliveries_a = []
    for index, (build_day, sale_day) in enumerate(
        [("01", "02"), ("02", "03"), ("03", "04"), ("04", "05"), ("05", "06")], start=1
    ):
        delivery = fx.report_delivery(
            dealer_a["id"],
            vin=f"VIN2842FNL000000{index}",
            build_date=f"2026-06-{build_day}T00:00:00.000Z",
            msrp_cents=3000000,
            sale_date=f"2026-08-{sale_day}T00:00:00.000Z",
            customer_region_code="ZZFNL",
        )
        fx.validate_delivery(delivery["id"])
        deliveries_a.append(delivery)

    delivery_b = fx.report_delivery(
        dealer_b["id"],
        vin="VIN2842FNL0000006",
        build_date="2026-06-06T00:00:00.000Z",
        msrp_cents=3000000,
        sale_date="2026-08-07T00:00:00.000Z",
        customer_region_code="ZZFNL",
    )
    fx.validate_delivery(delivery_b["id"])

    claim_a = fx.submit_claim(
        dealer_a["id"], deliveries_a[4]["id"], program["id"], 150000
    )
    assert claim_a["claim_type"] == "STAIR_STEP_BONUS", claim_a

    # The objective exists but is still PROPOSED, so its units are not frozen.
    validate_error(
        api_client.adjudicate_claim(
            claim_a["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        ),
        "ERR_OBJECTIVE_NOT_FINAL",
    )

    # Dealer B has no objective at all, which is folded into the same code.
    claim_b = fx.submit_claim(dealer_b["id"], delivery_b["id"], program["id"], 30000)
    validate_error(
        api_client.adjudicate_claim(
            claim_b["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        ),
        "ERR_OBJECTIVE_NOT_FINAL",
    )

    finalized = fx.finalize_objective(objective_a["id"])
    a.assert_status(finalized, "FINAL")
    a.assert_int_field(finalized, "objective_units", 5)
    a.assert_objective_attainment(
        finalized, achieved_units=5, attainment_bps=10000, tier_attained=1,
        payout_cents=60000,
    )
    a.assert_money(finalized, "paid_payout_cents", 0)

    approved = validate_success(
        api_client.adjudicate_claim(
            claim_a["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        )
    )
    assert approved["validation_status"] == "VALIDATED", approved
    a.assert_money(approved, "approved_amount_cents", 60000)

    # Filing a protest un-freezes an already FINAL objective.
    fx.file_protest(
        objective_a["id"],
        dealer_a["id"],
        3,
        reason="Two of the five sales were fleet units.",
    )
    protested = fx.read_objective(objective_a["id"])
    a.assert_status(protested, "PROTESTED")
    a.assert_int_field(protested, "protest_round", 1)

    # The gate closes again: an earlier success grants no standing to the next.
    claim_a2 = fx.submit_claim(
        dealer_a["id"], deliveries_a[3]["id"], program["id"], 10000
    )
    validate_error(
        api_client.adjudicate_claim(
            claim_a2["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        ),
        "ERR_OBJECTIVE_NOT_FINAL",
    )

    # The refused adjudication left the second claim exactly as it was created.
    untouched = fx.read_claim(claim_a2["id"])
    assert untouched["validation_status"] == "SUBMITTED", untouched
    assert untouched["approved_amount_cents"] == claim_a2["approved_amount_cents"], (
        claim_a2["approved_amount_cents"],
        untouched["approved_amount_cents"],
    )

    # Only the objective moved: the first claim keeps its decision and amount.
    first_claim = fx.read_claim(claim_a["id"])
    assert first_claim["validation_status"] == "VALIDATED", first_claim
    a.assert_money(first_claim, "approved_amount_cents", 60000)
