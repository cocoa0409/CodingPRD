"""Role-based access control: authentication, authorization and agent scope.

Every test builds its own state through the public endpoints only; the harness
restarts the server and empties the database before each one, and the logical
clock starts at 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN_ONE,
    ANALYST_ONE,
    CONTROLLER_ONE,
    CONTROLLER_ONE_ID,
    ApiErrorId,
    api_client,
    build_user_headers,
    make_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# A syntactically valid UUID that names no row.
UNKNOWN_AGENT_ID = "00000000-0000-4000-8000-000000000000"

# Header sets that fail the priority-1 authentication check for three different
# reasons: no role, no principal, and a role outside the four declared names.
NO_ROLE_HEADERS = {"X-User-ID": "admin-1", "Content-Type": "application/json"}
NO_USER_ID_HEADERS = {"X-User-Role": "IsoAdmin", "Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = build_user_headers("auditor-1", "Auditor")

PROGRAM_ECONOMICS = {
    "buy_rate_bps": 45,
    "buy_rate_per_item_cents": 6,
    "assessment_bps": 13,
    "normalization_mode": "NET_REVENUE_SPLIT",
    "minimum_billing_mode": "NO_MINIMUM",
}


def _program_payload(name: str) -> dict:
    return {"name": name, **PROGRAM_ECONOMICS}


@pytest.mark.parametrize(
    "label, invoke",
    [
        (
            "role header absent on a write",
            lambda: api_client.create_processor_program(
                _program_payload("Headerless"), NO_ROLE_HEADERS
            ),
        ),
        (
            "user id header absent even though the role is valid",
            lambda: api_client.create_processor_program(
                _program_payload("No User Id"), NO_USER_ID_HEADERS
            ),
        ),
        (
            "role string outside the four declared roles",
            lambda: api_client.create_processor_program(
                _program_payload("Wrong Role"), UNKNOWN_ROLE_HEADERS
            ),
        ),
        (
            "header-less read of a non-existent agent",
            lambda: api_client.get_agent(UNKNOWN_AGENT_ID, NO_ROLE_HEADERS),
        ),
        (
            "header-less write whose body is also missing required fields",
            lambda: api_client.create_agent({"split_pct": 0.50}, NO_ROLE_HEADERS),
        ),
    ],
)
def test_auth_headers_are_checked_before_every_other_rule(label, invoke):
    """Authentication outranks existence, shape and authorization alike.

    "This is the very first check performed on any request, ahead of routing
    concerns such as whether the addressed resource exists."

    An unrecognised role string is treated as a missing header rather than as an
    authorization failure, a header-less read of an unknown agent never reaches
    the existence rule, and a header-less write with required fields missing
    never reaches the request-shape rule.

    Design: Corner/rbac/auth_headers_are_checked_before_every_other_rule
    """
    response = invoke()

    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value, 401)
    error = response.json()["data"]
    assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
        f"{label}: an unrecognised role is owned by the priority-1 authentication "
        "rule, not by the priority-2 authorization rule"
    )
    assert error["error_id"] != ApiErrorId.ERR_AGENT_NOT_FOUND.value, (
        f"{label}: priority 1 outranks the priority-6 existence rule"
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
        f"{label}: priority 1 outranks the priority-4 request-shape rule"
    )

    # The refused call wrote nothing: a properly authenticated create is the only
    # row in the collection afterwards.
    created = validate_success(
        api_client.create_processor_program(
            _program_payload("Properly Authenticated"), ADMIN_ONE
        ),
        201,
    )
    assert created["status"] == "ACTIVE", "a newly registered program starts ACTIVE"

    rows, meta = validate_paginated(api_client.list_processor_programs(ADMIN_ONE))
    assert meta["total_count"] == 1, (
        f"{label}: the refused call must not have created a processor program, "
        f"expected total_count 1, got {meta['total_count']}"
    )
    assert rows[0]["id"] == created["id"]


def _boarded_program_agent_merchant() -> tuple:
    """Program, top-level agent and one ACTIVE merchant, all under IsoAdmin."""
    program = validate_success(
        api_client.create_processor_program(
            _program_payload("Atlantic Net Program"), ADMIN_ONE
        ),
        201,
    )
    agent = validate_success(
        api_client.create_agent(
            {
                "name": "A1 Principal",
                "split_pct": 0.50,
                "override_pct": 0.60,
                "vesting_start_date": "2024-01-15",
            },
            ADMIN_ONE,
        ),
        201,
    )
    merchant = validate_success(
        api_client.create_merchant(
            {
                "owning_agent_id": agent["id"],
                "processor_program_id": program["id"],
                "mid": "MID-9001",
                "monthly_minimum_cents": 0,
                "per_transaction_fee_cents": 10,
                "equipment_lease_monthly_cents": 0,
                "boarded_on": "2026-04-10",
            },
            ADMIN_ONE,
        ),
        201,
    )
    validate_success(api_client.activate_merchant(merchant["id"], ADMIN_ONE))
    return program, agent, merchant


def _flat_line_payload(merchant_id: str) -> dict:
    """1,000,000 cents of volume over 100 authorizations, 45,100 cents of income."""
    return {
        "merchant_id": merchant_id,
        "transaction_count": 100,
        "sales_volume_cents": 1000000,
        "interchange_cents": 0,
        "assessments_cents": 0,
        "gross_income_cents": 45100,
    }


def _normalized_batch(program_id: str, merchant_id: str, period_month: str,
                      coverage_start: str, coverage_end: str, checksum: str) -> dict:
    batch = validate_success(
        api_client.create_residual_batch(
            {
                "processor_program_id": program_id,
                "period_month": period_month,
                "coverage_start": coverage_start,
                "coverage_end": coverage_end,
                "file_checksum": checksum,
            },
            ANALYST_ONE,
        ),
        201,
    )
    validate_success(
        api_client.create_residual_line(
            batch["id"], _flat_line_payload(merchant_id), ANALYST_ONE
        ),
        201,
    )
    return validate_success(api_client.normalize_residual_batch(batch["id"], ANALYST_ONE))


def test_role_exclusivity_across_the_money_boundary():
    """The money boundary is exclusive in both directions.

    "The `IsoAdmin` role holds every master-data write exclusively; the
    `ResidualController` role holds every ledger-posting and settlement write
    exclusively" — and "advance reads are shared only between `IsoAdmin` and
    `ResidualController`".

    Every refusal is ERR_UNAUTHORIZED and leaves the batch NORMALIZED and the
    statement DRAFT; only the ResidualController can move either one.

    Design: Corner/rbac/role_exclusivity_across_the_money_boundary
    """
    program, agent, merchant = _boarded_program_agent_merchant()
    june = _normalized_batch(
        program["id"], merchant["id"], "2026-06", "2026-06-01", "2026-07-01",
        "sha256:rb-0006",
    )
    validate_success(api_client.post_residual_batch(june["id"], CONTROLLER_ONE))
    july = _normalized_batch(
        program["id"], merchant["id"], "2026-07", "2026-07-01", "2026-08-01",
        "sha256:rb-0007",
    )
    statements, _ = validate_paginated(
        api_client.list_agent_statements(
            CONTROLLER_ONE, {"agent_id": agent["id"], "period_month": "2026-06"}
        )
    )
    assert len(statements) == 1, "the June post must have created exactly one statement"
    statement = statements[0]

    agent_headers = make_agent_headers(agent["id"])
    refusals = [
        ("analyst posting a batch",
         lambda: api_client.post_residual_batch(july["id"], ANALYST_ONE)),
        ("IsoAdmin posting a batch",
         lambda: api_client.post_residual_batch(july["id"], ADMIN_ONE)),
        ("analyst issuing a statement",
         lambda: api_client.issue_agent_statement(statement["id"], ANALYST_ONE)),
        ("Agent boarding a merchant",
         lambda: api_client.create_merchant(
             {
                 "owning_agent_id": agent["id"],
                 "processor_program_id": program["id"],
                 "mid": "MID-9099",
                 "monthly_minimum_cents": 0,
                 "per_transaction_fee_cents": 10,
                 "equipment_lease_monthly_cents": 0,
                 "boarded_on": "2026-04-10",
             },
             agent_headers,
         )),
        ("analyst listing advances",
         lambda: api_client.list_agent_advances(ANALYST_ONE, {"agent_id": agent["id"]})),
        ("controller registering a program",
         lambda: api_client.create_processor_program(
             _program_payload("Controller Program"), CONTROLLER_ONE
         )),
        ("analyst amending an agent",
         lambda: api_client.update_agent(agent["id"], {"split_pct": 0.90}, ANALYST_ONE)),
    ]

    for label, invoke in refusals:
        response = invoke()
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
        assert (
            validate_success(api_client.get_residual_batch(july["id"], ANALYST_ONE))["state"]
            == "NORMALIZED"
        ), f"{label}: the July batch must still be NORMALIZED"
        assert (
            validate_success(
                api_client.get_agent_statement(statement["id"], CONTROLLER_ONE)
            )["lifecycle_state"]
            == "DRAFT"
        ), f"{label}: the June statement must still be DRAFT"

    # No side effect survived any of the seven refusals.
    merchants, merchant_meta = validate_paginated(api_client.list_merchants(ADMIN_ONE))
    assert all(row["mid"] != "MID-9099" for row in merchants), (
        "an Agent may never board a merchant, so no row with mid MID-9099 exists"
    )
    assert merchant_meta["total_count"] == 1
    _, program_meta = validate_paginated(api_client.list_processor_programs(ADMIN_ONE))
    assert program_meta["total_count"] == 1, (
        "master data is exclusive to IsoAdmin, so the controller created no program"
    )
    assert float(
        validate_success(api_client.get_agent(agent["id"], ADMIN_ONE))["split_pct"]
    ) == pytest.approx(0.50), "the refused amendment left split_pct at 0.50"

    # The ResidualController is the only role that can cross the money boundary.
    posted = validate_success(api_client.post_residual_batch(july["id"], CONTROLLER_ONE))
    assert posted["state"] == "POSTED", "the controller's post moves the batch to POSTED"
    issued = validate_success(
        api_client.issue_agent_statement(statement["id"], CONTROLLER_ONE)
    )
    assert issued["lifecycle_state"] == "ISSUED"
    assert issued["net_payable_cents"] == 20000, (
        f"expected net_payable_cents 20000, got {issued['net_payable_cents']}"
    )


def test_agent_scope_confines_every_read_and_write_to_its_own_book():
    """An acting Agent is confined to its own book on reads, list reads and writes.

    "An acting `Agent` that addresses another agent's record, portfolio summary,
    merchant, statement, allocation or adjustment is refused with
    `ERR_AGENT_SCOPE_VIOLATION` (HTTP 403)." An unnarrowed list read is refused
    the same way: "An omitted or mismatched filter is a scope violation, not an
    empty result."

    Because actor scope sits above optimistic concurrency in the refusal order,
    proposing an adjustment against another agent's statement with an already
    stale `expected_statement_version` still reports the scope violation.

    Design: Corner/rbac/agent_scope_confines_every_read_and_write_to_its_own_book
    """
    program = validate_success(
        api_client.create_processor_program(
            _program_payload("Atlantic Net Program"), ADMIN_ONE
        ),
        201,
    )
    agents = {}
    for key, name in (("a1", "A1 Self"), ("a2", "A2 Other")):
        agents[key] = validate_success(
            api_client.create_agent(
                {
                    "name": name,
                    "split_pct": 0.50,
                    "override_pct": 0.60,
                    "vesting_start_date": "2024-01-15",
                },
                ADMIN_ONE,
            ),
            201,
        )
    merchants = {}
    for key, mid in (("a1", "MID-9001"), ("a2", "MID-9002")):
        merchant = validate_success(
            api_client.create_merchant(
                {
                    "owning_agent_id": agents[key]["id"],
                    "processor_program_id": program["id"],
                    "mid": mid,
                    "monthly_minimum_cents": 0,
                    "per_transaction_fee_cents": 10,
                    "equipment_lease_monthly_cents": 0,
                    "boarded_on": "2026-04-10",
                },
                ADMIN_ONE,
            ),
            201,
        )
        merchants[key] = validate_success(
            api_client.activate_merchant(merchant["id"], ADMIN_ONE)
        )

    batch = validate_success(
        api_client.create_residual_batch(
            {
                "processor_program_id": program["id"],
                "period_month": "2026-07",
                "coverage_start": "2026-07-01",
                "coverage_end": "2026-08-01",
                "file_checksum": "sha256:sc-0001",
            },
            ANALYST_ONE,
        ),
        201,
    )
    for key in ("a1", "a2"):
        validate_success(
            api_client.create_residual_line(
                batch["id"], _flat_line_payload(merchants[key]["id"]), ANALYST_ONE
            ),
            201,
        )
    validate_success(api_client.normalize_residual_batch(batch["id"], ANALYST_ONE))
    validate_success(api_client.post_residual_batch(batch["id"], CONTROLLER_ONE))

    own_rows, _ = validate_paginated(
        api_client.list_agent_statements(
            CONTROLLER_ONE, {"agent_id": agents["a1"]["id"], "period_month": "2026-07"}
        )
    )
    other_rows, _ = validate_paginated(
        api_client.list_agent_statements(
            CONTROLLER_ONE, {"agent_id": agents["a2"]["id"], "period_month": "2026-07"}
        )
    )
    own_statement, other_statement = own_rows[0], other_rows[0]
    own_version = own_statement["version"]
    other_version = other_statement["version"]

    # The analyst's proposal bumps A2's statement version, so ``other_version``
    # is genuinely stale by the time the acting Agent replays it.
    foreign_adjustment = validate_success(
        api_client.create_statement_adjustment(
            other_statement["id"],
            {
                "kind": "DISPUTE_CREDIT",
                "amount_cents": 100,
                "reason": "A2 issuer credit under review",
                "expected_statement_version": other_version,
            },
            ANALYST_ONE,
        ),
        201,
    )

    acting = make_agent_headers(agents["a1"]["id"])
    violations = [
        ("another agent's record",
         lambda: api_client.get_agent(agents["a2"]["id"], acting)),
        ("another agent's portfolio summary",
         lambda: api_client.get_agent_portfolio_summary(agents["a2"]["id"], acting)),
        ("another agent's statement",
         lambda: api_client.get_agent_statement(other_statement["id"], acting)),
        ("an unfiltered statement list read",
         lambda: api_client.list_agent_statements(acting)),
        ("a merchant list read filtered to another agent",
         lambda: api_client.list_merchants(acting, {"owning_agent_id": agents["a2"]["id"]})),
        ("an unfiltered allocation list read",
         lambda: api_client.list_residual_allocations(acting)),
    ]
    for label, invoke in violations:
        validate_error(invoke(), ApiErrorId.ERR_AGENT_SCOPE_VIOLATION.value, 403)

    stale_foreign_write = api_client.create_statement_adjustment(
        other_statement["id"],
        {
            "kind": "DISPUTE_CREDIT",
            "amount_cents": 500,
            "reason": "not my statement",
            "expected_statement_version": other_version,
        },
        acting,
    )
    validate_error(
        stale_foreign_write, ApiErrorId.ERR_AGENT_SCOPE_VIOLATION.value, 403
    )
    assert (
        stale_foreign_write.json()["data"]["error_id"]
        != ApiErrorId.ERR_STALE_STATEMENT_VERSION.value
    ), "actor scope is consulted before the optimistic-concurrency check"

    # The same reads and the same write succeed when narrowed to the acting agent.
    self_read = validate_success(api_client.get_agent(agents["a1"]["id"], acting))
    assert self_read["id"] == agents["a1"]["id"]
    assert self_read["vested_pct"] == 50, (
        f"expected vested_pct 50, got {self_read['vested_pct']}"
    )
    scoped_statements, statement_meta = validate_paginated(
        api_client.list_agent_statements(acting, {"agent_id": agents["a1"]["id"]})
    )
    assert statement_meta["total_count"] == 1
    assert scoped_statements[0]["id"] == own_statement["id"]
    scoped_allocations, allocation_meta = validate_paginated(
        api_client.list_residual_allocations(acting, {"agent_id": agents["a1"]["id"]})
    )
    assert allocation_meta["total_count"] == 1
    assert scoped_allocations[0]["gross_allocation_cents"] == 20000, (
        "expected gross_allocation_cents 20000, got "
        f"{scoped_allocations[0]['gross_allocation_cents']}"
    )

    own_adjustment = validate_success(
        api_client.create_statement_adjustment(
            own_statement["id"],
            {
                "kind": "DISPUTE_CREDIT",
                "amount_cents": 500,
                "reason": "issuer reversed a chargeback",
                "expected_statement_version": own_version,
            },
            acting,
        ),
        201,
    )
    assert own_adjustment["created_by_user_id"] == agents["a1"]["id"]
    assert own_adjustment["state"] == "PROPOSED"

    # A2's statement is untouched by the refused proposal.
    untouched = validate_success(
        api_client.get_agent_statement(other_statement["id"], CONTROLLER_ONE)
    )
    assert untouched["adjustment_cents"] == 0, (
        "only APPLIED adjustments move money, and the analyst's row is only PROPOSED"
    )
    assert untouched["net_payable_cents"] == 20000, (
        f"expected net_payable_cents 20000, got {untouched['net_payable_cents']}"
    )
    foreign_rows, foreign_meta = validate_paginated(
        api_client.list_statement_adjustments(
            CONTROLLER_ONE, {"statement_id": other_statement["id"]}
        )
    )
    assert foreign_meta["total_count"] == 1, (
        "the refused proposal left no adjustment row on the other agent's statement"
    )
    assert foreign_rows[0]["id"] == foreign_adjustment["id"]


def test_each_role_performs_its_own_operations_through_one_settlement():
    """All four roles walk one period end to end, each doing only its own work.

    Segregation of duties is satisfied rather than violated: "Moving an adjustment
    `UNDER_REVIEW` → `APPLIED` requires that the approving `X-User-ID` differ from
    that adjustment's `created_by_user_id`", and here the acting Agent proposed
    while the ResidualController approved.

    Design: Corner/rbac/each_role_performs_its_own_operations_through_one_settlement
    """
    program = validate_success(
        api_client.create_processor_program(
            _program_payload("Atlantic Net Program"), ADMIN_ONE
        ),
        201,
    )
    agent = validate_success(
        api_client.create_agent(
            {
                "name": "A1 Principal",
                "split_pct": 0.50,
                "override_pct": 0.60,
                "vesting_start_date": "2024-01-15",
            },
            ADMIN_ONE,
        ),
        201,
    )
    merchant = validate_success(
        api_client.create_merchant(
            {
                "owning_agent_id": agent["id"],
                "processor_program_id": program["id"],
                "mid": "MID-9001",
                "monthly_minimum_cents": 0,
                "per_transaction_fee_cents": 10,
                "equipment_lease_monthly_cents": 1000,
                "boarded_on": "2026-04-10",
            },
            ADMIN_ONE,
        ),
        201,
    )
    validate_success(api_client.activate_merchant(merchant["id"], ADMIN_ONE))

    batch = validate_success(
        api_client.create_residual_batch(
            {
                "processor_program_id": program["id"],
                "period_month": "2026-07",
                "coverage_start": "2026-07-01",
                "coverage_end": "2026-08-01",
                "file_checksum": "sha256:rw-0001",
            },
            ANALYST_ONE,
        ),
        201,
    )
    validate_success(
        api_client.create_residual_line(
            batch["id"],
            {
                "merchant_id": merchant["id"],
                "transaction_count": 100,
                "sales_volume_cents": 1000000,
                "interchange_cents": 20000,
                "assessments_cents": 1300,
                "gross_income_cents": 40000,
            },
            ANALYST_ONE,
        ),
        201,
    )
    validate_success(api_client.normalize_residual_batch(batch["id"], ANALYST_ONE))
    validate_success(api_client.post_residual_batch(batch["id"], CONTROLLER_ONE))

    rows, _ = validate_paginated(
        api_client.list_agent_statements(
            CONTROLLER_ONE, {"agent_id": agent["id"], "period_month": "2026-07"}
        )
    )
    statement_id = rows[0]["id"]
    validate_success(api_client.issue_agent_statement(statement_id, CONTROLLER_ONE))

    acting = make_agent_headers(agent["id"])
    own_view = validate_success(api_client.get_agent_statement(statement_id, acting))
    assert own_view["lifecycle_state"] == "ISSUED"
    assert own_view["direct_residual_cents"] == 6300, (
        f"expected direct_residual_cents 6300, got {own_view['direct_residual_cents']}"
    )
    assert own_view["minimum_true_up_cents"] == 0
    assert own_view["advance_recoupment_cents"] == 0
    assert own_view["net_payable_cents"] == 6300, (
        f"expected net_payable_cents 6300, got {own_view['net_payable_cents']}"
    )

    adjustment = validate_success(
        api_client.create_statement_adjustment(
            statement_id,
            {
                "kind": "DISPUTE_CREDIT",
                "amount_cents": 500,
                "reason": "issuer reversed CB-77",
                "expected_statement_version": own_view["version"],
            },
            acting,
        ),
        201,
    )
    assert adjustment["state"] == "PROPOSED"
    assert adjustment["created_by_user_id"] == agent["id"]

    reviewed = validate_success(
        api_client.review_statement_adjustment(adjustment["id"], CONTROLLER_ONE)
    )
    assert reviewed["state"] == "UNDER_REVIEW"
    asked = validate_success(
        api_client.request_info_statement_adjustment(
            adjustment["id"],
            {"info_request_note": "attach the issuer credit advice"},
            CONTROLLER_ONE,
        )
    )
    assert asked["state"] == "INFO_REQUESTED"
    assert asked["info_request_note"] == "attach the issuer credit advice"
    answered = validate_success(
        api_client.resubmit_statement_adjustment(
            adjustment["id"],
            {"reason": "issuer credit advice ICA-4411 attached"},
            acting,
        )
    )
    assert answered["state"] == "UNDER_REVIEW"
    assert answered["info_request_note"] is None, (
        "answering the question clears info_request_note"
    )
    assert answered["reason"] == "issuer credit advice ICA-4411 attached"

    applied = validate_success(
        api_client.approve_statement_adjustment(adjustment["id"], CONTROLLER_ONE)
    )
    assert applied["state"] == "APPLIED"
    assert applied["created_by_user_id"] == agent["id"]
    assert applied["approved_by_user_id"] == CONTROLLER_ONE_ID, (
        "the approver's principal must differ from the proposer's"
    )
    assert applied["approved_by_user_id"] != applied["created_by_user_id"]

    after_apply = validate_success(
        api_client.get_agent_statement(statement_id, CONTROLLER_ONE)
    )
    assert after_apply["adjustment_cents"] == 500
    assert after_apply["net_payable_cents"] == 6800, (
        f"expected net_payable_cents 6800, got {after_apply['net_payable_cents']}"
    )
    assert after_apply["lifecycle_state"] == "ISSUED"

    finalized = validate_success(
        api_client.finalize_agent_statement(statement_id, CONTROLLER_ONE)
    )
    assert finalized["lifecycle_state"] == "FINALIZED"
    settled = validate_success(
        api_client.settle_agent_statement(
            statement_id, {"paid_on": "2026-08-01"}, CONTROLLER_ONE
        )
    )
    assert settled["settlement_state"] == "SETTLED"
    assert settled["paid_on"] == "2026-08-01"

    final_agent = validate_success(api_client.get_agent(agent["id"], ADMIN_ONE))
    assert final_agent["trailing_residual_cents"] == 6300, (
        "trailing_residual_cents sums gross_after_trueup_cents, which the "
        f"adjustment never touches; got {final_agent['trailing_residual_cents']}"
    )
