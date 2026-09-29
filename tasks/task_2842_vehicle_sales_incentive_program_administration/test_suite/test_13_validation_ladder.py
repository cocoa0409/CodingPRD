"""Request-screening ladder: which check speaks when a request breaks several rules.

Every test in this module builds its whole precondition chain from scratch,
because the server (and its logical clock) is restarted before each test.
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, BUILD_FROM, BUILD_TO, SEP_01
from test_helpers.test_users import (
    USER_AUDITOR_1,
    USER_AUDITOR_2,
    USER_CONTROLLER,
    make_headers,
    make_incentive_controller_headers,
    make_program_designer_headers,
)

# Instants used by these scenarios, each a full ISO 8601 UTC instant with three
# fractional-second digits.
AUG_05 = "2026-08-05T00:00:00.000Z"
AUG_06 = "2026-08-06T00:00:00.000Z"
AUG_10 = "2026-08-10T00:00:00.000Z"
AUG_15 = "2026-08-15T00:00:00.000Z"
AUG_20 = "2026-08-20T00:00:00.000Z"
AUG_25 = "2026-08-25T00:00:00.000Z"
AUG_31_END = "2026-08-31T00:00:00.000Z"
SEP_15 = "2026-09-15T00:00:00.000Z"
JUN_01 = "2026-06-01T00:00:00.000Z"

# Well-formed identifiers that name no row at all.
GHOST_BATCH_ID = "00000000-0000-4000-8000-00000000f001"
GHOST_CLAIM_ID = "00000000-0000-4000-8000-00000000f002"
GHOST_PROGRAM_ID = "00000000-0000-4000-8000-00000000f003"

# A request carrying neither X-User-ID nor X-User-Role.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def _cash_program_payload(program_code, name, priority_rank, **overrides):
    """A CUSTOMER_CASH program payload with every money field named explicitly."""
    payload = {
        "program_code": program_code,
        "name": name,
        "incentive_type": "CUSTOMER_CASH",
        "effective_from": AUG_01,
        "effective_to": SEP_01,
        "per_unit_amount_cents": 100000,
        "budget_cents": 1000000,
        "stack_group": "GEN",
        "priority_rank": priority_rank,
        "accrual_method": "UNIT_BASED",
    }
    payload.update(overrides)
    return payload


def _rule_payload(region_code, **overrides):
    payload = {
        "model_code": "MX5",
        "region_code": region_code,
        "build_date_from": BUILD_FROM,
        "build_date_to": BUILD_TO,
        "allowed_deal_types": ["CASH"],
    }
    payload.update(overrides)
    return payload


def test_program_creation_ladder_walks_role_then_shape_then_uniqueness():
    """One payload wrong in three ways at once reports the role failure, then the
    shape failure, then the duplicate code, and only the repaired payload persists.

    PRD: "Checks are evaluated in the following order, and the first failure
    short-circuits the request; no side effect of any kind is applied to any
    entity once a check fails."
    PRD: "**Global uniqueness** — `program_code`, `dealer_code`, `vin` and
    `batch_code` are each globally unique, and each uniqueness scope includes
    rows that have reached a terminal state: a `program_code` is taken even by a
    `CLOSED` or `SUPERSEDED` program, a `vin` even by a `REJECTED` or `UNWOUND`
    delivery, and a `batch_code` even by a `CANCELLED` batch."

    Design: Corner/validations/program_creation_ladder_walks_role_then_shape_then_uniqueness
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-LAD",
        name="Ladder Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    incumbent = validate_success(
        api_client.create_program(
            _cash_program_payload("CRN-V-LAD", "Ladder Incumbent", 409,
                                  stack_group="CRNLAD"),
            fx.DESIGNER,
        ),
        201,
    )

    # Deliberately wrong three ways over: the Dealer role may not create a
    # program, per_unit_amount_cents is missing, and the code is already taken.
    broken = {
        "program_code": "CRN-V-LAD",
        "name": "Ladder Attempt A",
        "incentive_type": "CUSTOMER_CASH",
        "effective_from": AUG_01,
        "effective_to": SEP_01,
        "budget_cents": 1000000,
        "stack_group": "CRNLAD",
        "priority_rank": 410,
    }
    role_error = validate_error(
        api_client.create_program(broken, make_dealer_headers(dealer["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert set(role_error) == {"error_id", "message"}, (
        f"an error payload carries only error_id and message, got {sorted(role_error)}"
    )
    assert role_error["message"].strip(), "the error message must be human readable"

    shape_attempt = dict(broken, name="Ladder Attempt B")
    validate_error(
        api_client.create_program(shape_attempt, fx.DESIGNER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    dupe_attempt = dict(broken, name="Ladder Attempt C", per_unit_amount_cents=100000)
    validate_error(
        api_client.create_program(dupe_attempt, fx.DESIGNER),
        ApiErrorId.ERR_DUPLICATE_PROGRAM_CODE.value,
        409,
    )

    repaired = dict(dupe_attempt, program_code="CRN-V-LAD-2", name="Ladder Attempt D")
    created = validate_success(api_client.create_program(repaired, fx.DESIGNER), 201)
    a.assert_status(created, "DRAFT")
    a.assert_version(created, 1)

    rows, meta = validate_paginated(api_client.list_programs(fx.DESIGNER))
    a.assert_ids_equal(rows, [incumbent["id"], created["id"]], "programs")
    assert meta["total_count"] == 2, (
        f"the three refused attempts must leave no program behind, got {meta!r}"
    )


def test_path_resources_resolve_before_body_foreign_keys():
    """A bogus batch id with an equally bogus claim id reports the batch, and only
    once the path resolves does the body foreign key speak.

    PRD: "**Path existence** — every resource named in the URL path exists,
    resolved strictly left to right: the program before its eligibility rule, the
    objective before its protest, the batch before the claims it is asked to
    schedule."
    PRD: "**Body foreign keys** — every foreign key carried in the request body
    resolves to an existing row: the `delivery_id` and `program_id` of a claim,
    the `dealer_id` of an objective, the `program_b_id` of a stackability edge,
    every id inside `claim_ids`, and a program's `supersedes_program_id`."

    Design: Corner/validations/path_resources_resolve_before_body_foreign_keys_so_a_bogus_batch_is_not_found
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-PTH",
        name="Path Order Motors",
        region_code="NORTH",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=_cash_program_payload("CRN-V-PTH", "Path Order Cash", 411,
                                      stack_group="CRNPTH"),
        rules=[_rule_payload("NORTH")],
    )
    fx.set_clock(AUG_06)
    delivery = fx.report_delivery(
        dealer["id"], msrp_cents=3100000, sale_date=AUG_05,
        customer_region_code="NORTH",
    )
    fx.validate_delivery(delivery["id"])
    claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 100000)
    fx.adjudicate_claim(claim["id"])
    batch = fx.open_batch(
        batch_code="CRN-B-PTH",
        region_code="NORTH",
        period_start=AUG_01,
        period_end=AUG_15,
        scheduled_pay_date=AUG_25,
    )

    validate_error(
        api_client.schedule_claims(
            GHOST_BATCH_ID, f.schedule_claims_payload([GHOST_CLAIM_ID]), fx.CONTROLLER
        ),
        ApiErrorId.ERR_BATCH_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.schedule_claims(
            batch["id"], f.schedule_claims_payload([GHOST_CLAIM_ID]), fx.CONTROLLER
        ),
        ApiErrorId.ERR_CLAIM_NOT_FOUND.value,
        404,
    )

    untouched = fx.read_batch(batch["id"])
    a.assert_int_field(untouched, "claim_count", 0)
    a.assert_money(untouched, "total_cents", 0)

    scheduled = validate_success(
        api_client.schedule_claims(
            batch["id"], f.schedule_claims_payload([claim["id"]]), fx.CONTROLLER
        )
    )
    a.assert_status(scheduled, "OPEN")
    a.assert_int_field(scheduled, "claim_count", 1)
    a.assert_money(scheduled, "total_cents", 100000)


def test_approval_role_gate_precedes_segregation_of_duties():
    """At both dual-control sites the wrong role is refused before the identity
    check speaks, and the same principal is then refused purely for acting twice.

    PRD: "**Authorization** — the acting role appears in the called endpoint's
    authorized-role list, else `ERR_UNAUTHORIZED` (403)."
    PRD: "**Segregation of duties** — on `POST /incentives/programs/{id}/approve`
    the caller's `X-User-ID` differs from the program's `submitted_by_user_id`,
    and on `POST /incentives/claims/{id}/adjudicate` the caller's `X-User-ID`
    differs from the delivery's `validated_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/validations/approval_role_gate_precedes_segregation_of_duties_at_both_dual_control_sites
    """
    dual_designer = make_program_designer_headers("u-dual-1")
    dual_controller = make_incentive_controller_headers("u-dual-1")

    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-SOD",
        name="Dual Control Motors",
        region_code="EAST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = validate_success(
        api_client.create_program(
            _cash_program_payload("CRN-V-SOD", "Dual Control Cash", 412,
                                  stack_group="CRNSOD"),
            dual_designer,
        ),
        201,
    )
    validate_success(
        api_client.create_eligibility_rule(
            program["id"], _rule_payload("EAST"), dual_designer
        ),
        201,
    )
    submitted = validate_success(api_client.submit_program(program["id"], dual_designer))
    assert submitted["submitted_by_user_id"] == "u-dual-1"
    a.assert_status(submitted, "PENDING_APPROVAL")

    # Site one: program approval.
    validate_error(
        api_client.approve_program(program["id"], dual_designer),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.approve_program(program["id"], dual_controller),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    approved = validate_success(api_client.approve_program(program["id"], fx.CONTROLLER))
    a.assert_status(approved, "ACTIVE")
    assert approved["approved_by_user_id"] == USER_CONTROLLER

    fx.set_clock(AUG_06)
    delivery = fx.report_delivery(
        dealer["id"], msrp_cents=3100000, sale_date=AUG_05,
        customer_region_code="EAST",
    )
    validated = fx.validate_delivery(delivery["id"])
    assert validated["validated_by_user_id"] == USER_AUDITOR_1
    claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 100000)

    # Site two: claim adjudication, anchored on the delivery's validating auditor.
    validate_error(
        api_client.adjudicate_claim(
            claim["id"], f.adjudicate_payload("APPROVE"),
            make_incentive_controller_headers(USER_AUDITOR_1),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.adjudicate_claim(
            claim["id"], f.adjudicate_payload("APPROVE"), fx.VALIDATOR
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    adjudicated = validate_success(
        api_client.adjudicate_claim(
            claim["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        )
    )
    assert adjudicated["adjudicated_by_user_id"] == USER_AUDITOR_2
    assert adjudicated["validation_status"] == "VALIDATED"


def test_dealer_ownership_outranks_an_unresolvable_program_in_the_claim_body():
    """A dealer claiming another dealer's delivery learns only that it is not
    theirs, even when the body also names a program that does not exist.

    PRD: "**Dealer ownership** — when the acting role is `Dealer`, `X-User-ID`
    equals the `dealer_id` of the resource being created or acted on, which means
    the delivery's `dealer_id` on `POST /incentives/deliveries`, the claimed
    delivery's `dealer_id` on `POST /incentives/claims`, and the objective's
    `dealer_id` on `POST /incentives/objectives/{id}/protests`, else
    `ERR_DEALER_MISMATCH` (403)."
    PRD: "`dealer_id` is copied from the delivery at creation and is never
    re-derived afterwards, even if the delivery is later touched."

    Design: Corner/validations/dealer_ownership_outranks_an_unresolvable_program_in_the_claim_body
    """
    fx.set_clock(AUG_01)
    dealer_a = fx.register_dealer(
        dealer_code="CRN-D-OWNA",
        name="Owner A Motors",
        region_code="SOUTH",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    dealer_b = fx.register_dealer(
        dealer_code="CRN-D-OWNB",
        name="Owner B Motors",
        region_code="SOUTH",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=_cash_program_payload("CRN-V-OWN", "Ownership Cash", 413,
                                      stack_group="CRNOWN"),
        rules=[_rule_payload("SOUTH")],
    )
    fx.set_clock(AUG_06)
    delivery_b = fx.report_delivery(
        dealer_b["id"], msrp_cents=3100000, sale_date=AUG_05,
        customer_region_code="SOUTH",
    )
    fx.validate_delivery(delivery_b["id"])
    version = fx.program_version(program["id"])

    headers_a = make_dealer_headers(dealer_a["id"])
    validate_error(
        api_client.create_claim(
            f.create_claim_payload(delivery_b["id"], GHOST_PROGRAM_ID, 100000, version),
            headers_a,
        ),
        ApiErrorId.ERR_DEALER_MISMATCH.value,
        403,
    )
    validate_error(
        api_client.create_claim(
            f.create_claim_payload(delivery_b["id"], program["id"], 100000, version),
            headers_a,
        ),
        ApiErrorId.ERR_DEALER_MISMATCH.value,
        403,
    )
    validate_error(
        api_client.create_delivery(
            f.create_delivery_payload(
                dealer_b["id"], msrp_cents=3100000, sale_date=AUG_05,
                customer_region_code="SOUTH",
            ),
            headers_a,
        ),
        ApiErrorId.ERR_DEALER_MISMATCH.value,
        403,
    )

    owned = validate_success(
        api_client.create_claim(
            f.create_claim_payload(delivery_b["id"], program["id"], 100000, version),
            make_dealer_headers(dealer_b["id"]),
        ),
        201,
    )
    assert owned["dealer_id"] == dealer_b["id"], (
        "the claim's dealer_id is copied from the delivery, not from the caller"
    )

    rows, meta = validate_paginated(
        api_client.list_claims(fx.ADJUDICATOR, {"dealer_id": dealer_a["id"]})
    )
    a.assert_list_length(rows, 0, "claims of dealer A")
    assert meta["total_count"] == 0, f"dealer A must own no claim, got {meta!r}"


def test_budget_headroom_admits_the_claim_landing_exactly_on_budget():
    """Two claims land committed_cents exactly on budget_cents and are approved,
    and the third is refused at adjudication while its claim row survives.

    PRD: "If the program's `committed_cents` plus this claim's newly computed
    `approved_amount_cents` would rise above the program's `budget_cents`, the
    approval is refused with `ERR_PROGRAM_BUDGET_EXHAUSTED` (HTTP 402) and
    nothing is written."
    PRD: "And because budget headroom (rung 31) is the last rung of all, a claim
    that would exhaust the program's funding is only reported as such after every
    structural, ownership and eligibility question has been answered."

    Design: Corner/validations/budget_headroom_admits_the_claim_landing_exactly_on_budget_and_refuses_the_next_cent
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-BDG",
        name="Budget Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=_cash_program_payload("CRN-V-BDG", "Budget Cash", 414,
                                      budget_cents=200000, stack_group="CRNBDG"),
        rules=[_rule_payload("WEST")],
    )
    fx.set_clock(AUG_06)
    deliveries = []
    for _ in range(3):
        delivery = fx.report_delivery(
            dealer["id"], msrp_cents=3100000, sale_date=AUG_05,
            customer_region_code="WEST",
        )
        fx.validate_delivery(delivery["id"])
        deliveries.append(delivery)

    # Each claim alone is only half the budget, so the rule bites collectively.
    for delivery in deliveries[:2]:
        claim = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 100000)
        approved = validate_success(
            api_client.adjudicate_claim(
                claim["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
            )
        )
        assert approved["validation_status"] == "VALIDATED"

    at_cap = fx.read_spend_summary(program["id"])
    a.assert_money(at_cap, "committed_cents", 200000)
    a.assert_money(at_cap, "budget_remaining_cents", 0)

    third = validate_success(
        api_client.create_claim(
            f.create_claim_payload(
                deliveries[2]["id"], program["id"], 100000,
                fx.program_version(program["id"]),
            ),
            make_dealer_headers(dealer["id"]),
        ),
        201,
    )
    assert third["validation_status"] == "SUBMITTED", (
        "claim creation is not budget-checked, so the third claim is accepted"
    )

    validate_error(
        api_client.adjudicate_claim(
            third["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        ),
        ApiErrorId.ERR_PROGRAM_BUDGET_EXHAUSTED.value,
        402,
    )

    after = fx.read_claim(third["id"])
    assert after["validation_status"] == "SUBMITTED", (
        "the refused adjudication left the claim neither VALIDATED nor REJECTED"
    )
    a.assert_money(fx.read_spend_summary(program["id"]), "committed_cents", 200000)


def test_capped_total_stack_edges_require_a_cap_that_allowed_edges_must_omit():
    """cap_amount_cents is required exactly when the mode is CAPPED_TOTAL, and the
    unordered pair admits one row that both endpoints can see.

    PRD: "`cap_amount_cents` carries the combined ceiling in cents for the pair
    and is required exactly when `mode` is `CAPPED_TOTAL`; in the other two modes
    it must be null."
    PRD: "Declaring an edge whose `program_b_id` equals the path program, or
    declaring a second edge over a pair that an edge already joins, is refused
    with `ERR_INVALID_STACK_EDGE`."

    Design: Corner/validations/capped_total_stack_edges_require_a_cap_amount_that_allowed_edges_must_omit
    """
    fx.set_clock(AUG_01)
    program_p = fx.create_draft_program(
        payload=_cash_program_payload("CRN-V-EDGP", "Edge Program P", 415,
                                      stack_group="CRNEDG")
    )
    program_q = fx.create_draft_program(
        payload=_cash_program_payload(
            "CRN-V-EDGQ", "Edge Program Q", 416,
            incentive_type="LEASE_SUPPORT", per_unit_amount_cents=50000,
            stack_group="CRNEDG",
        )
    )

    validate_error(
        api_client.create_stackability_constraint(
            program_p["id"],
            {"program_b_id": program_q["id"], "mode": "CAPPED_TOTAL"},
            fx.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_stackability_constraint(
            program_p["id"],
            {"program_b_id": program_q["id"], "mode": "ALLOWED",
             "cap_amount_cents": 500000},
            fx.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_stackability_constraint(
            program_p["id"],
            {"program_b_id": program_p["id"], "mode": "FORBIDDEN"},
            fx.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_STACK_EDGE.value,
        409,
    )

    edge = validate_success(
        api_client.create_stackability_constraint(
            program_p["id"],
            {"program_b_id": program_q["id"], "mode": "CAPPED_TOTAL",
             "cap_amount_cents": 500000},
            fx.DESIGNER,
        ),
        201,
    )
    assert edge["mode"] == "CAPPED_TOTAL"
    a.assert_money(edge, "cap_amount_cents", 500000)
    assert edge["program_a_id"] == program_p["id"]
    assert edge["program_b_id"] == program_q["id"]

    validate_error(
        api_client.create_stackability_constraint(
            program_q["id"],
            {"program_b_id": program_p["id"], "mode": "FORBIDDEN"},
            fx.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_STACK_EDGE.value,
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_stackability_constraints(program_q["id"], fx.DESIGNER)
    )
    a.assert_list_length(rows, 1, "edges touching Q")
    assert rows[0]["mode"] == "CAPPED_TOTAL"
    a.assert_money(rows[0], "cap_amount_cents", 500000)
    assert meta["total_count"] == 1, (
        f"the three refused declarations created no row, got {meta!r}"
    )


def test_program_overlap_is_deferred_from_draft_authoring_to_submission():
    """A fully colliding program may be authored without complaint; only the
    submission refuses it, and closing the incumbent lets the same submit through.

    PRD: "The check looks for another program that is in `PENDING_APPROVAL` or
    `ACTIVE`, carries the same `incentive_type`, has an effective window that
    intersects this program's half-open window, and has an eligibility footprint
    that intersects this program's footprint — meaning some pair of footprint rows
    shares a `model_code`, has overlapping trim scope, shares a `region_code`, and
    has intersecting closed build-date intervals."
    PRD: "This is the system's one genuine design cycle: a program may be
    submitted, revised and re-submitted without limit, and each re-submission
    re-runs the overlap check against the world as it stands at that moment rather
    than against the world at first submission."

    Design: Corner/validations/program_overlap_is_deferred_from_draft_authoring_to_submission
    """
    fx.set_clock(AUG_01)
    incumbent = fx.create_active_program(
        payload=_cash_program_payload("CRN-V-OVLA", "Overlap Incumbent", 417,
                                      stack_group="CRNOVL"),
        rules=[_rule_payload("NORTH")],
    )
    a.assert_status(incumbent, "ACTIVE")

    challenger = validate_success(
        api_client.create_program(
            _cash_program_payload(
                "CRN-V-OVLB", "Overlap Challenger", 418,
                effective_from=AUG_15, effective_to=SEP_15,
                per_unit_amount_cents=120000, stack_group="CRNOVL",
            ),
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_status(challenger, "DRAFT")
    challenger_rule = validate_success(
        api_client.create_eligibility_rule(
            challenger["id"],
            _rule_payload("NORTH", build_date_from=JUN_01,
                          build_date_to=AUG_31_END),
            fx.DESIGNER,
        ),
        201,
    )
    assert challenger_rule["id"], "authoring a colliding footprint row is admitted"
    version_before_submit = fx.program_version(challenger["id"])

    validate_error(
        api_client.submit_program(challenger["id"], fx.DESIGNER),
        ApiErrorId.ERR_PROGRAM_WINDOW_OVERLAP.value,
        409,
    )
    after_failure = fx.read_program(challenger["id"])
    a.assert_status(after_failure, "DRAFT")
    a.assert_version(after_failure, version_before_submit)

    closed = fx.close_program(incumbent["id"], closure_note="making room for the challenger")
    a.assert_status(closed, "CLOSED")

    resubmitted = validate_success(
        api_client.submit_program(challenger["id"], fx.DESIGNER)
    )
    a.assert_status(resubmitted, "PENDING_APPROVAL")


def test_shape_bounds_accept_equal_endpoints_and_refuse_a_zero_length_window():
    """The one strict bound of the shape check refuses a zero-length program
    window, while the three inclusive bounds accept equal endpoints.

    PRD: "**Payload shape** — on every creating or acting endpoint: all required
    fields present, every enum value a declared member, every integer inside its
    declared range, every instant a parseable ISO 8601 UTC value with three
    fractional digits, `effective_to` strictly greater than `effective_from`,
    `build_date_to` greater than or equal to `build_date_from`, `period_end`
    greater than or equal to `period_start`, `scheduled_pay_date` greater than or
    equal to `period_end`, `cap_amount_cents` non-null exactly when `mode` is
    `CAPPED_TOTAL` and null in every other mode, and `tier_schedule` strictly
    ascending in both `tier_index` and `threshold_bps`."

    Design: Corner/validations/shape_bounds_accept_equal_inclusive_endpoints_and_refuse_a_zero_length_program_window
    """
    fx.set_clock(AUG_01)

    validate_error(
        api_client.create_program(
            _cash_program_payload("CRN-V-BND1", "Zero Length Window", 419,
                                  effective_to=AUG_01, stack_group="CRNBND"),
            fx.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_program(
            _cash_program_payload("CRN-V-BND2", "Bad Enum Program", 420,
                                  incentive_type="CUSTOMER_CASHBACK",
                                  stack_group="CRNBND"),
            fx.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api_client.create_program(
            _cash_program_payload(
                "CRN-V-BND3", "Bad Tier Ladder", 421,
                incentive_type="DEALER_STAIR_STEP", per_unit_amount_cents=0,
                stack_group="CRNBND",
                tier_schedule=[
                    {"tier_index": 1, "threshold_bps": 9000,
                     "per_unit_bonus_cents": 20000},
                    {"tier_index": 2, "threshold_bps": 9000,
                     "per_unit_bonus_cents": 40000},
                ],
                tier_bonus_mode="MARGINAL",
            ),
            fx.DESIGNER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    # One millisecond is a legal window, so the refusal above was about equality.
    program = validate_success(
        api_client.create_program(
            _cash_program_payload("CRN-V-BND4", "One Millisecond Window", 422,
                                  effective_to="2026-08-01T00:00:00.001Z",
                                  stack_group="CRNBND"),
            fx.DESIGNER,
        ),
        201,
    )
    assert program["effective_from"] == AUG_01
    assert program["effective_to"] == "2026-08-01T00:00:00.001Z"

    rule = validate_success(
        api_client.create_eligibility_rule(
            program["id"],
            _rule_payload("ZZBND", build_date_from=JUN_01, build_date_to=JUN_01),
            fx.DESIGNER,
        ),
        201,
    )
    assert rule["build_date_from"] == JUN_01
    assert rule["build_date_to"] == JUN_01

    batch = validate_success(
        api_client.create_payment_batch(
            f.create_payment_batch_payload(
                batch_code="CRN-B-BND", region_code="ZZBND",
                period_start=AUG_10, period_end=AUG_10, scheduled_pay_date=AUG_10,
            ),
            fx.CONTROLLER,
        ),
        201,
    )
    a.assert_status(batch, "OPEN")
    a.assert_int_field(batch, "claim_count", 0)

    for entity, field in (
        (program, "effective_from"), (program, "effective_to"),
        (rule, "build_date_from"), (rule, "build_date_to"),
        (batch, "period_start"), (batch, "period_end"),
        (batch, "scheduled_pay_date"),
    ):
        value = entity[field]
        assert is_iso8601_timestamp(value), f"{field} is not an ISO 8601 instant: {value!r}"
        assert value.endswith("Z") and value[-5] == ".", (
            f"{field} must carry exactly three fractional digits, got {value!r}"
        )


def test_an_unknown_role_header_is_unauthenticated_while_a_wrong_role_is_unauthorized():
    """Absent headers and an undeclared role are both unauthenticated, while a
    declared role missing from the endpoint's list is unauthorized.

    PRD: "If either header is absent, or if `X-User-Role` is not one of the five
    role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401). If both headers are present and well-formed but the named role does not
    appear in the authorized-role list of the endpoint being called (§4), the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/validations/an_unknown_role_header_is_unauthenticated_while_a_known_but_wrong_role_is_unauthorized
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-AUTH",
        name="Auth Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_draft_program(
        payload=_cash_program_payload("CRN-V-AUTH", "Auth Program", 423,
                                      stack_group="CRNAUTH")
    )

    ghost_role = make_headers("u-ghost-1", "RegionalAnalyst")
    role_only = {"X-User-Role": "ProgramDesigner", "Content-Type": "application/json"}

    validate_error(
        api_client.get_program(program["id"], NO_AUTH_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api_client.get_program(program["id"], ghost_role),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api_client.get_program(program["id"], role_only),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api_client.list_programs(make_dealer_headers(dealer["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.create_dealer(
            f.create_dealer_payload(
                dealer_code="CRN-D-AUTH2", name="Auth Motors Two",
                region_code="WEST", historical_volume_units=1,
                market_opportunity_bps=0,
            ),
            ghost_role,
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    # The single-program read does admit a Dealer, so the 401s above cannot be
    # explained away by the endpoint refusing dealers.
    read = validate_success(
        api_client.get_program(program["id"], make_dealer_headers(dealer["id"]))
    )
    assert read["id"] == program["id"]


def test_duplicate_claim_check_looks_past_rejected_and_charged_back_predecessors():
    """The same delivery/program pairing is claimable again after a rejected and
    after a charged-back predecessor, but one live claim refuses the next one.

    PRD: "Then duplication: no other claim on the same pairing of `delivery_id`
    and `program_id` may exist whose `validation_status` is anything other than
    `REJECTED` and whose `payment_status` is anything other than `CHARGED_BACK` —
    a second live claim on the same pairing is refused with `ERR_DUPLICATE_CLAIM`,
    while a pairing whose earlier claim was rejected or charged back is free to be
    claimed again."

    Design: Corner/validations/duplicate_claim_check_looks_past_rejected_and_charged_back_predecessors
    """
    fx.set_clock(AUG_01)
    dealer = fx.register_dealer(
        dealer_code="CRN-D-DUP",
        name="Duplicate Motors",
        region_code="ZZDUP",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload=_cash_program_payload("CRN-V-DUP", "Duplicate Cash", 424,
                                      stack_group="CRNDUP"),
        rules=[_rule_payload("ZZDUP")],
    )
    fx.set_clock(AUG_06)
    delivery = fx.report_delivery(
        dealer["id"], msrp_cents=3100000, sale_date=AUG_05,
        customer_region_code="ZZDUP",
    )
    fx.validate_delivery(delivery["id"])
    batch = fx.open_batch(
        batch_code="CRN-B-DUP",
        region_code="ZZDUP",
        period_start=AUG_01,
        period_end=AUG_15,
        scheduled_pay_date=AUG_20,
    )
    dealer_headers = make_dealer_headers(dealer["id"])

    first = fx.submit_claim(dealer["id"], delivery["id"], program["id"], 100000)
    rejected = validate_success(
        api_client.adjudicate_claim(
            first["id"],
            f.adjudicate_payload("REJECT", rejection_error_id="ERR_NO_ELIGIBLE_PROGRAM"),
            fx.ADJUDICATOR,
        )
    )
    assert rejected["validation_status"] == "REJECTED"
    assert rejected["rejection_error_id"] == "ERR_NO_ELIGIBLE_PROGRAM"

    # A REJECTED predecessor leaves the pairing claimable.
    second = validate_success(
        api_client.create_claim(
            f.create_claim_payload(
                delivery["id"], program["id"], 100000,
                fx.program_version(program["id"]),
            ),
            dealer_headers,
        ),
        201,
    )
    assert second["validation_status"] == "SUBMITTED"
    approved = validate_success(
        api_client.adjudicate_claim(
            second["id"], f.adjudicate_payload("APPROVE"), fx.ADJUDICATOR
        )
    )
    a.assert_money(approved, "approved_amount_cents", 100000)
    a.assert_claim_dimensions(approved, "VALIDATED", "UNPAID")

    # One live claim on the pairing is enough to refuse the third submission.
    validate_error(
        api_client.create_claim(
            f.create_claim_payload(
                delivery["id"], program["id"], 100000,
                fx.program_version(program["id"]),
            ),
            dealer_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_CLAIM.value,
        409,
    )

    scheduled = fx.schedule_claims(batch["id"], [second["id"]])
    a.assert_int_field(scheduled, "claim_count", 1)
    a.assert_status(fx.lock_batch(batch["id"]), "LOCKED")
    fx.set_clock(AUG_20)
    a.assert_status(
        validate_success(api_client.disburse_batch(batch["id"], fx.CONTROLLER)),
        "DISBURSED",
    )

    chargeback = validate_success(
        api_client.create_chargeback(
            second["id"], f.create_chargeback_payload("UNWOUND_DEAL"), fx.VALIDATOR
        ),
        201,
    )
    a.assert_status(chargeback, "PENDING")
    assert chargeback["reason"] == "UNWOUND_DEAL"
    a.assert_money(chargeback, "amount_cents", 100000)
    assert fx.read_claim(second["id"])["payment_status"] == "CHARGED_BACK"

    # A CHARGED_BACK predecessor satisfies the other half of the filter.
    fourth = validate_success(
        api_client.create_claim(
            f.create_claim_payload(
                delivery["id"], program["id"], 100000,
                fx.program_version(program["id"]),
            ),
            dealer_headers,
        ),
        201,
    )
    assert fourth["validation_status"] == "SUBMITTED"

    rows, meta = validate_paginated(
        api_client.list_claims(fx.VALIDATOR, {"delivery_id": delivery["id"]})
    )
    a.assert_ids_equal(rows, [first["id"], second["id"], fourth["id"]], "claims")
    assert meta["total_count"] == 3, (
        f"the refused submission created no row; the rule filters, it never "
        f"deletes, got {meta!r}"
    )
