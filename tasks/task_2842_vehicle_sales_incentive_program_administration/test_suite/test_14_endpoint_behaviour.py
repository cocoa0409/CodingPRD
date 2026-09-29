"""Endpoint behaviour of the incentive service.

Covers the one field-mutating dealer write, the all-or-nothing claim attachment
call, the computed spend projection, the stackability cross-reference link, the
clock-gated repricing action, the two non-repeatable action endpoints and the
declared pagination bounds.
"""
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    AUG_01,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MIN_LIMIT,
    SEP_01,
)

# The syntactically valid identifier that resolves to nothing in an empty
# database, reused wherever a dangling reference has to be probed.
MISSING_ID = "00000000-0000-4000-8000-00000000f004"
MISSING_PROGRAM_ID = "00000000-0000-4000-8000-00000000f005"


def test_dealer_status_write_round_trips_through_all_three_standings():
    """The dealer standing write walks ACTIVE -> SUSPENDED -> TERMINATED -> ACTIVE, bumping version once per accepted write, refusing an undeclared value and never touching the money fields.

    PRD: "Dealer standing is a three-valued lever — `ACTIVE`, `SUSPENDED` or `TERMINATED` — that the controller sets by supplying a `status` and, optionally, an explanatory `note`; the change increments the dealer's `version` by 1."

    Design: Corner/endpoints/dealer_status_write_is_the_only_mutating_crud_endpoint_and_round_trips
    """
    fx.set_clock(AUG_01)

    created = validate_success(
        api_client.create_dealer(
            f.create_dealer_payload(
                dealer_code="CRN-D-CRUD",
                name="Crud Motors",
                region_code="WEST",
                historical_volume_units=6,
                market_opportunity_bps=1500,
            ),
            fx.CONTROLLER,
        ),
        201,
    )
    a.assert_dealer_shape(created)
    a.assert_status(created, "ACTIVE")
    a.assert_dealer_money(created, paid_cents=0, open_chargeback_cents=0)
    a.assert_version(created, 1)
    dealer_id = created["id"]

    # The read adds nothing and changes nothing: it returns what was written.
    read_back = validate_success(api_client.get_dealer(dealer_id, fx.DESIGNER))
    assert read_back["dealer_code"] == "CRN-D-CRUD"
    a.assert_int_field(read_back, "historical_volume_units", 6)
    a.assert_bps(read_back, "market_opportunity_bps", 1500)
    a.assert_status(read_back, created["status"])

    suspended = validate_success(
        api_client.set_dealer_status(
            dealer_id,
            f.set_dealer_status_payload("SUSPENDED", note="audit hold"),
            fx.CONTROLLER,
        )
    )
    a.assert_status(suspended, "SUSPENDED")
    a.assert_version(suspended, 2)

    # The note is optional, so omitting it on this write is equally fine.
    terminated = validate_success(
        api_client.set_dealer_status(
            dealer_id, f.set_dealer_status_payload("TERMINATED"), fx.CONTROLLER
        )
    )
    a.assert_status(terminated, "TERMINATED")
    a.assert_version(terminated, 3)

    # TERMINATED is not terminal on a dealer: the lever is freely re-settable.
    reinstated = validate_success(
        api_client.set_dealer_status(
            dealer_id,
            f.set_dealer_status_payload("ACTIVE", note="reinstated"),
            fx.CONTROLLER,
        )
    )
    a.assert_status(reinstated, "ACTIVE")
    a.assert_version(reinstated, 4)
    a.assert_dealer_money(reinstated, paid_cents=0, open_chargeback_cents=0)

    validate_error(
        api_client.set_dealer_status(
            dealer_id, f.set_dealer_status_payload("REVOKED"), fx.CONTROLLER
        ),
        "ERR_INVALID_REQUEST",
    )

    final = validate_success(api_client.get_dealer(dealer_id, fx.VALIDATOR))
    a.assert_status(final, "ACTIVE")
    a.assert_version(final, reinstated["version"])
    a.assert_dealer_money(final, paid_cents=0, open_chargeback_cents=0)


def test_schedule_claims_is_a_no_op_when_one_named_claim_is_unusable():
    """A three-element claim_ids array holding one unresolvable id, and then one still-SUBMITTED claim, is refused entirely: the batch stays empty, both good claims stay UNPAID and no version moves.

    PRD: "A named claim that fails either half of that condition is refused with `ERR_CLAIM_NOT_VALIDATED` and **the whole call is a no-op**: no claim in the list is attached, no total is recomputed, and no version moves."

    Design: Corner/endpoints/schedule_claims_is_transactional_so_one_bad_id_rejects_the_whole_request
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-BULK",
        name="Bulk Motors",
        region_code="ZZBULK",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-E-BULK",
            name="Bulk Cash",
            per_unit_amount_cents=100000,
            budget_cents=1000000,
            stack_group="CRNBULK",
            priority_rank=425,
        ),
        rules=[{"region_code": "ZZBULK"}],
    )

    fx.set_clock("2026-08-06T00:00:00.000Z")
    deliveries = []
    for _ in range(3):
        delivery = fx.report_delivery(
            dealer["id"],
            msrp_cents=3100000,
            sale_date="2026-08-05T00:00:00.000Z",
            customer_region_code="ZZBULK",
        )
        fx.validate_delivery(delivery["id"])
        deliveries.append(delivery)

    claim_1 = fx.submit_claim(dealer["id"], deliveries[0]["id"], program["id"], 100000)
    fx.adjudicate_claim(claim_1["id"])
    claim_2 = fx.submit_claim(dealer["id"], deliveries[1]["id"], program["id"], 100000)
    fx.adjudicate_claim(claim_2["id"])
    # The third claim is deliberately left un-adjudicated.
    claim_3 = fx.submit_claim(dealer["id"], deliveries[2]["id"], program["id"], 100000)

    batch = validate_success(
        api_client.create_payment_batch(
            f.create_payment_batch_payload(
                batch_code="CRN-B-BULK",
                region_code="ZZBULK",
                period_start=AUG_01,
                period_end="2026-08-15T00:00:00.000Z",
                scheduled_pay_date="2026-08-25T00:00:00.000Z",
            ),
            fx.CONTROLLER,
        ),
        201,
    )
    a.assert_int_field(batch, "claim_count", 0)
    a.assert_money(batch, "total_cents", 0)
    a.assert_version(batch, 1)

    # The bad element sits in the middle, so the two good ids ahead of and
    # behind it would be applied first by any partial implementation.
    validate_error(
        api_client.schedule_claims(
            batch["id"],
            f.schedule_claims_payload([claim_1["id"], MISSING_ID, claim_2["id"]]),
            fx.CONTROLLER,
        ),
        "ERR_CLAIM_NOT_FOUND",
    )
    after_missing = fx.read_batch(batch["id"])
    a.assert_int_field(after_missing, "claim_count", 0)
    a.assert_money(after_missing, "total_cents", 0)
    a.assert_version(after_missing, batch["version"])
    first_claim = fx.read_claim(claim_1["id"])
    a.assert_claim_dimensions(first_claim, "VALIDATED", "UNPAID")
    a.assert_null_fields(first_claim, ["payment_batch_id"])

    validate_error(
        api_client.schedule_claims(
            batch["id"],
            f.schedule_claims_payload([claim_1["id"], claim_3["id"], claim_2["id"]]),
            fx.CONTROLLER,
        ),
        "ERR_CLAIM_NOT_VALIDATED",
    )
    after_state = fx.read_batch(batch["id"])
    a.assert_int_field(after_state, "claim_count", 0)
    a.assert_money(after_state, "total_cents", 0)
    a.assert_claim_dimensions(fx.read_claim(claim_2["id"]), "VALIDATED", "UNPAID")

    accepted = validate_success(
        api_client.schedule_claims(
            batch["id"],
            f.schedule_claims_payload([claim_1["id"], claim_2["id"]]),
            fx.CONTROLLER,
        )
    )
    a.assert_int_field(accepted, "claim_count", 2)
    a.assert_money(accepted, "total_cents", 200000)
    a.assert_version(accepted, 2)


def test_spend_summary_only_projects_the_program_and_its_claims():
    """The spend summary reports the program's own stored counters plus the one derived figure budget_remaining_cents, agrees with the program row and the claim and accrual listings, and reading it twice changes nothing.

    PRD: "It returns the `program_id` it describes, the program's `claimed_units`, `committed_cents`, `paid_cents`, `accrued_budget_cents`, `per_unit_spend_cents` and `residual_impact_bps`, and one derived figure not stored on the program itself: `budget_remaining_cents`, the program's `budget_cents` minus its `committed_cents`."

    Design: Corner/endpoints/spend_summary_is_a_pure_projection_of_the_program_and_its_claims
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-SUM",
        name="Summary Motors",
        region_code="ZZSUM",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-E-SUM",
            name="Summary Cash",
            per_unit_amount_cents=100000,
            budget_cents=1000000,
            stack_group="CRNSUM",
            priority_rank=426,
        ),
        rules=[{"region_code": "ZZSUM"}],
    )

    fx.set_clock("2026-08-06T00:00:00.000Z")
    claims = []
    for _ in range(2):
        delivery = fx.report_delivery(
            dealer["id"],
            msrp_cents=3100000,
            sale_date="2026-08-05T00:00:00.000Z",
            customer_region_code="ZZSUM",
        )
        fx.validate_delivery(delivery["id"])
        claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 100000)
        fx.adjudicate_claim(claim["id"])
        claims.append(claim)

    # Exactly one of the two approved claims is carried through to PAID, so
    # committed_cents and paid_cents must differ in the projection.
    batch = fx.open_batch(
        batch_code="CRN-B-SUM",
        region_code="ZZSUM",
        period_start=AUG_01,
        period_end="2026-08-15T00:00:00.000Z",
        scheduled_pay_date="2026-08-20T00:00:00.000Z",
    )
    fx.schedule_claims(batch["id"], [claims[0]["id"]])
    fx.lock_batch(batch["id"])
    fx.disburse_batch(batch["id"])

    accrual = validate_success(
        api_client.run_accrual(
            program["id"], f.run_accrual_payload("2026-08"), fx.CONTROLLER
        ),
        201,
    )
    a.assert_accrual_shape(accrual)
    a.assert_money(accrual, "accrued_cents", 194500)

    summary = validate_success(api_client.get_spend_summary(program["id"], fx.CONTROLLER))
    a.assert_spend_summary(
        summary,
        program_id=program["id"],
        claimed_units=2,
        committed_cents=200000,
        paid_cents=100000,
        accrued_budget_cents=194500,
        per_unit_spend_cents=100000,
        residual_impact_bps=0,
        budget_remaining_cents=800000,
    )

    # Every projected figure except budget_remaining_cents is stored on the
    # program row itself and must agree with it.
    program_row = fx.read_program(program["id"])
    a.assert_program_money(
        program_row, committed_cents=200000, paid_cents=100000, claimed_units=2
    )
    a.assert_money(program_row, "accrued_budget_cents", 194500)
    a.assert_money(program_row, "per_unit_spend_cents", 100000)
    a.assert_bps(program_row, "residual_impact_bps", 0)

    rows, meta = validate_paginated(
        api_client.list_claims(fx.VALIDATOR, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 2, meta
    assert sum(row["approved_amount_cents"] for row in rows) == 200000, rows

    accrual_rows, accrual_meta = validate_paginated(
        api_client.list_accruals(program["id"], fx.DESIGNER)
    )
    assert accrual_meta["total_count"] == 1, accrual_meta
    a.assert_money(accrual_rows[0], "accrued_cents", 194500)

    # A projection is a read: asking a second time, as another role, is inert.
    again = validate_success(api_client.get_spend_summary(program["id"], fx.DESIGNER))
    assert again == summary, (summary, again)
    a.assert_version(fx.read_program(program["id"]), program_row["version"])


def test_stack_edge_needs_both_of_its_programs_to_exist():
    """A stackability edge is refused with the program not-found code whether the missing program is the path segment or the body reference, and the one accepted edge is a single undirected row visible from both endpoints.

    PRD: "**Body foreign keys** — every foreign key carried in the request body resolves to an existing row: the `delivery_id` and `program_id` of a claim, the `dealer_id` of an objective, the `program_b_id` of a stackability edge, every id inside `claim_ids`, and a program's `supersedes_program_id`."

    Design: Corner/endpoints/stack_edge_with_an_unknown_partner_program_is_not_found
    """
    fx.set_clock(AUG_01)
    program_r = fx.create_draft_program(
        payload=f.create_program_payload(
            program_code="CRN-E-LNKR",
            name="Link Cash R",
            per_unit_amount_cents=100000,
            budget_cents=1000000,
            stack_group="CRNLNK",
            priority_rank=427,
        )
    )
    program_s = fx.create_draft_program(
        payload=f.create_program_payload(
            program_code="CRN-E-LNKS",
            name="Link Finance S",
            incentive_type="FINANCE_SUBVENTION",
            per_unit_amount_cents=50000,
            budget_cents=1000000,
            stack_group="CRNLNK",
            priority_rank=428,
        )
    )

    # The path program is the one that does not exist.
    validate_error(
        api_client.create_stackability_constraint(
            MISSING_PROGRAM_ID,
            f.create_stackability_constraint_payload(program_s["id"]),
            fx.DESIGNER,
        ),
        "ERR_PROGRAM_NOT_FOUND",
    )
    # The body reference is the one that does not exist.
    validate_error(
        api_client.create_stackability_constraint(
            program_r["id"],
            f.create_stackability_constraint_payload(MISSING_PROGRAM_ID),
            fx.DESIGNER,
        ),
        "ERR_PROGRAM_NOT_FOUND",
    )

    edge = validate_success(
        api_client.create_stackability_constraint(
            program_r["id"],
            f.create_stackability_constraint_payload(program_s["id"], "ALLOWED"),
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_stack_constraint_shape(edge)
    assert edge["program_a_id"] == program_r["id"], edge
    assert edge["program_b_id"] == program_s["id"], edge
    assert edge["mode"] == "ALLOWED", edge
    a.assert_null_fields(edge, ["cap_amount_cents"])

    from_r, meta_r = validate_paginated(
        api_client.list_stackability_constraints(program_r["id"], fx.DESIGNER)
    )
    a.assert_list_length(from_r, 1, "edges touching R")
    a.assert_ids_equal(from_r, [edge["id"]], "edges touching R")
    assert meta_r["total_count"] == 1, meta_r

    # The same single row is reachable from the other endpoint of the pair.
    from_s, meta_s = validate_paginated(
        api_client.list_stackability_constraints(program_s["id"], fx.DESIGNER)
    )
    a.assert_list_length(from_s, 1, "edges touching S")
    a.assert_ids_equal(from_s, [edge["id"]], "edges touching S")
    assert meta_s["total_count"] == 1, meta_s


def test_repricing_is_refused_before_and_after_the_effective_window():
    """The same PROSPECTIVE repricing is refused at 2026-07-25, accepted at 2026-08-01 and refused again at 2026-09-01 while the program stays ACTIVE throughout, so only the clock explains the three outcomes.

    PRD: "The program must be `ACTIVE` and the logical clock must lie inside the program's half-open effective window, at or after `effective_from` and strictly before `effective_to`; a repricing of a non-active program, or one attempted outside that window, is refused with `ERR_REPRICING_WINDOW_CLOSED`."

    Design: Corner/endpoints/repricing_is_a_conditional_action_allowed_only_inside_the_live_window
    """
    fx.set_clock("2026-07-25T00:00:00.000Z")
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-E-RPW",
            name="Repricing Window Cash",
            effective_from=AUG_01,
            effective_to=SEP_01,
            per_unit_amount_cents=100000,
            budget_cents=1000000,
            stack_group="CRNRPW",
            priority_rank=429,
        ),
        rules=[{"region_code": "ZZRPW"}],
    )
    a.assert_status(program, "ACTIVE")

    early = fx.read_program(program["id"])
    a.assert_status(early, "ACTIVE")
    validate_error(
        api_client.create_repricing(
            program["id"],
            f.create_repricing_payload("PROSPECTIVE", 110000, early["version"]),
            fx.DESIGNER,
        ),
        "ERR_REPRICING_WINDOW_CLOSED",
    )

    fx.set_clock(AUG_01)
    inside = fx.read_program(program["id"])
    # The refusal above wrote nothing, so the version is still the one just read.
    a.assert_version(inside, early["version"])
    accepted = validate_success(
        api_client.create_repricing(
            program["id"],
            f.create_repricing_payload("PROSPECTIVE", 110000, inside["version"]),
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_repricing_shape(accepted)
    assert accepted["mode"] == "PROSPECTIVE", accepted
    a.assert_money(accepted, "previous_per_unit_amount_cents", 100000)
    a.assert_money(accepted, "new_per_unit_amount_cents", 110000)
    a.assert_int_field(accepted, "affected_claim_count", 0)
    a.assert_money(accepted, "net_adjustment_cents", 0)

    # 2026-09-01 is effective_to itself and the window is half-open.
    fx.set_clock(SEP_01)
    late = fx.read_program(program["id"])
    a.assert_status(late, "ACTIVE")
    a.assert_money(late, "per_unit_amount_cents", 110000)
    validate_error(
        api_client.create_repricing(
            program["id"],
            f.create_repricing_payload("PROSPECTIVE", 130000, late["version"]),
            fx.DESIGNER,
        ),
        "ERR_REPRICING_WINDOW_CLOSED",
    )

    rows, meta = validate_paginated(
        api_client.list_repricings(program["id"], fx.CONTROLLER)
    )
    a.assert_list_length(rows, 1, "repricing events")
    assert meta["total_count"] == 1, meta
    a.assert_money(rows[0], "new_per_unit_amount_cents", 110000)


def test_an_accrual_month_and_a_finalization_each_run_only_once():
    """A second accrual for 2026-08 is refused on the (program, period) key while 2026-09 still succeeds, a malformed month is a shape failure, and re-finalizing a FINAL objective is refused on its own state instead.

    PRD: "At most one accrual entry may exist per program and period: a second run for the same pairing is refused with `ERR_ACCRUAL_PERIOD_ALREADY_RUN`."
    PRD: "Finalizing from any other status is refused with `ERR_OBJECTIVE_INVALID_STATE`, and finalization additionally requires that no protest of this objective is still `OPEN`."

    Design: Corner/endpoints/an_accrual_month_runs_once_and_a_finalized_objective_cannot_be_refinalized
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-ACT",
        name="Action Motors",
        region_code="ZZACT",
        historical_volume_units=10,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-E-ACT",
            name="Action Stair",
            incentive_type="DEALER_STAIR_STEP",
            effective_from=AUG_01,
            effective_to="2026-10-01T00:00:00.000Z",
            per_unit_amount_cents=0,
            budget_cents=1000000,
            stack_group="CRNACT",
            priority_rank=430,
            tier_schedule=[
                {"tier_index": 1, "threshold_bps": 8000, "per_unit_bonus_cents": 30000}
            ],
            tier_bonus_mode="MARGINAL",
        ),
        rules=[{"region_code": "ZZACT"}],
    )
    objective = fx.assign_objective(program["id"], dealer["id"])
    a.assert_objective_shape(objective)
    a.assert_status(objective, "PROPOSED")

    # No delivery has been validated, so every month accrues zero — and a zero
    # accrual is still a row, which is what the second August call collides with.
    first_august = validate_success(
        api_client.run_accrual(
            program["id"], f.run_accrual_payload("2026-08"), fx.CONTROLLER
        ),
        201,
    )
    assert first_august["period_month"] == "2026-08", first_august
    assert first_august["entry_type"] == "ACCRUAL", first_august
    a.assert_money(first_august, "accrued_cents", 0)

    validate_error(
        api_client.run_accrual(
            program["id"], f.run_accrual_payload("2026-08"), fx.CONTROLLER
        ),
        "ERR_ACCRUAL_PERIOD_ALREADY_RUN",
    )

    # A different month on the same program is untouched by that key collision.
    september = validate_success(
        api_client.run_accrual(
            program["id"], f.run_accrual_payload("2026-09"), fx.CONTROLLER
        ),
        201,
    )
    assert september["id"] != first_august["id"], (first_august, september)
    assert september["period_month"] == "2026-09", september
    a.assert_money(september, "accrued_cents", 0)

    # "2026-8" is not an accepted spelling of the month that was already run.
    validate_error(
        api_client.run_accrual(
            program["id"], f.run_accrual_payload("2026-8"), fx.CONTROLLER
        ),
        "ERR_INVALID_REQUEST",
    )

    finalized = validate_success(api_client.finalize_objective(objective["id"], fx.FSM))
    a.assert_status(finalized, "FINAL")

    validate_error(
        api_client.finalize_objective(objective["id"], fx.FSM),
        "ERR_OBJECTIVE_INVALID_STATE",
    )
    after = fx.read_objective(objective["id"])
    a.assert_status(after, "FINAL")
    a.assert_version(after, finalized["version"])

    rows, meta = validate_paginated(
        api_client.list_accruals(program["id"], fx.CONTROLLER, {"entry_type": "ACCRUAL"})
    )
    a.assert_list_length(rows, 2, "accrual entries")
    assert meta["total_count"] == 2, meta
    assert rows[0]["period_month"] == "2026-08", rows


def _three_listable_programs():
    """Three programs, so a page size of 1 genuinely truncates the listing."""
    fx.set_clock(AUG_01)
    return [
        fx.create_draft_program(
            payload=f.create_program_payload(
                program_code=code,
                name=name,
                per_unit_amount_cents=100000,
                budget_cents=1000000,
                stack_group="CRNPG",
                priority_rank=rank,
            )
        )["id"]
        for code, name, rank in (
            ("CRN-E-PG1", "Page Program One", 431),
            ("CRN-E-PG2", "Page Program Two", 432),
            ("CRN-E-PG3", "Page Program Three", 433),
        )
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
    ids=["limit-below-minimum", "limit-above-maximum", "negative-offset"],
)
def test_list_endpoint_refuses_a_page_window_outside_the_declared_bounds(params):
    """A page size of 0 or 101, and a negative offset, are each rejected as malformed rather than being silently clamped to the nearest legal value.

    PRD: "A `limit` or `offset` outside those bounds, or one that is not an integer, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/list_endpoints_refuse_a_limit_outside_the_declared_one_to_one_hundred_range
    """
    _three_listable_programs()
    validate_error(
        api_client.list_programs(fx.CONTROLLER, params), "ERR_INVALID_REQUEST"
    )


def test_list_endpoint_accepts_the_bounds_and_defaults_to_ten():
    """A page size of 1 truncates to one row while reporting total_count 3 and has_more true; a page size of 100 and the omitted default of 10 both return all three rows and start at the same row.

    PRD: "`limit` controls the page size: it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum accepted value is 100."

    Design: Corner/endpoints/list_endpoints_refuse_a_limit_outside_the_declared_one_to_one_hundred_range
    """
    program_ids = _three_listable_programs()

    one_row, one_meta = validate_paginated(
        api_client.list_programs(fx.CONTROLLER, {"limit": MIN_LIMIT})
    )
    a.assert_list_length(one_row, 1, "programs at limit 1")
    assert one_meta["total_count"] == 3, one_meta
    assert one_meta["has_more"] is True, one_meta
    assert one_meta["limit"] == MIN_LIMIT, one_meta

    hundred_rows, hundred_meta = validate_paginated(
        api_client.list_programs(fx.CONTROLLER, {"limit": MAX_LIMIT})
    )
    a.assert_ids_equal(hundred_rows, program_ids, "programs at limit 100")
    assert hundred_meta["total_count"] == 3, hundred_meta
    assert hundred_meta["has_more"] is False, hundred_meta
    assert hundred_meta["limit"] == MAX_LIMIT, hundred_meta

    # Omitting limit is not a request for an unbounded page: it is a page of 10.
    default_rows, default_meta = validate_paginated(api_client.list_programs(fx.CONTROLLER))
    a.assert_ids_equal(default_rows, program_ids, "programs at the default limit")
    assert default_meta["total_count"] == 3, default_meta
    assert default_meta["has_more"] is False, default_meta
    assert default_meta["limit"] == DEFAULT_LIMIT, default_meta

    # The ordering is stable across page sizes, so page 1 starts at the same row.
    assert one_row[0]["id"] == hundred_rows[0]["id"] == default_rows[0]["id"], (
        one_row[0]["id"],
        hundred_rows[0]["id"],
        default_rows[0]["id"],
    )
