"""Issuing the purchase order and countersigning it: po_number uniqueness, one live PO
per package, clause attachability and quote match, the fiscal ceiling and the refusal
ladder (PRD §2.7, §2.8, §2.9, §3.1, §3.2, §3.5).

Every test in this module translates exactly one design instance from
SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml; the trailing
``Design:`` line of each docstring names it.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_purchase_commitment,
    assert_quote,
    build_buyout_scenario,
    countersign_commitment,
    draft_clause,
    execute_clause,
    issue_commitment,
    open_project,
    propose_clause,
    publish_reading,
    read_clause,
    read_commitment,
    read_package,
    read_project,
    read_project_version,
    read_quote,
    read_supplier,
    register_package,
    register_supplier,
    set_clock,
    submit_quote,
    suspend_supplier,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_purchase_commitment_payload

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]
PROJECT_EXECUTIVE = TEST_USERS["project_executive_headers"]

# A syntactically valid UUID that names no row at all.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000999"

# Only the 2026-07 baseline reading is needed by these scenarios.
BASELINE_READINGS = (("2026-07", 310.00),)


# ─── private setup helpers (not tests — no Design tag) ─────────────────────

def _setup_pending_commitment(*, clause_stage="EXECUTED", readings=BASELINE_READINGS, **kwargs):
    """Steel package → OPEN quote → clause at `clause_stage` → PENDING PO with it attached."""
    return build_buyout_scenario(
        readings=readings,
        clause_stage=clause_stage,
        attach_clause=True,
        issue=True,
        countersign=False,
        commitment_overrides={"is_early_buyout": False},
        **kwargs,
    )


def _setup_two_quotes_on_one_package():
    """One steel package carrying two OPEN quotes from two different suppliers.

    Price-hold overlap is scoped per package AND supplier, so both quotes coexist.
    """
    project = open_project()
    package = register_package(project["id"])
    first_supplier = register_supplier()
    first_quote = submit_quote(package["id"], first_supplier["id"], base_price=1150000.00)
    publish_reading("PPI_STEEL_MILL", "2026-07", 310.00)
    second_supplier = register_supplier(legal_name="Northline Steel Mills")
    second_quote = submit_quote(package["id"], second_supplier["id"], base_price=1120000.00)
    return {
        "project": project,
        "package": package,
        "first_supplier": first_supplier,
        "first_quote": first_quote,
        "second_supplier": second_supplier,
        "second_quote": second_quote,
    }


def _create_commitment(quote_id, project_id=None, *, version=None, **payload_overrides):
    """Raw commitment create; pins `version`, or the project's freshly read version."""
    if version is None:
        version = read_project_version(project_id)
    payload = create_purchase_commitment_payload(
        quote_id=quote_id, expected_project_version=version, **payload_overrides
    )
    return api_client.create_purchase_commitment(payload, BUYOUT_MANAGER)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / commit_blocked_by_clause_not_executed
# ---------------------------------------------------------------------------

def test_countersign_blocked_while_the_attached_clause_is_only_proposed():
    """Attaching a PROPOSED clause is legal at create time, yet countersigning is refused
    with ERR_ESCALATION_NOT_EXECUTED and nothing on either row moves.

    PRD §3.5: "An attached clause must be in `PROPOSED`, `COUNTERED` or `EXECUTED`;
    attaching a `LAPSED` clause is `ERR_AGREEMENT_NOT_ATTACHABLE`, and note that the clause
    need *not* yet be executed at this point — execution is only required later, to
    countersign."
    PRD §3.5: "If a clause is attached, that clause must by now be `EXECUTED`, otherwise
    `ERR_ESCALATION_NOT_EXECUTED`; a commitment with no clause attached skips this gate
    entirely."
    PRD §3.5: "The new row starts with `commitment_status` `PENDING` and `delivery_posture`
    `SCHEDULED`, with `released_for_fab_at`, `delivered_at`, `escalation_index_period` and
    `cancellation_reason` all null, `escalation_variant` `NONE` and `escalation_accrued` 0."

    Design: Difficulty/cross_entity_state_dependency/commit_blocked_by_clause_not_executed
    """
    scenario = _setup_pending_commitment(clause_stage="PROPOSED")
    commitment_id = scenario["commitment"]["id"]

    validate_error(
        api_client.commit_purchase_commitment(commitment_id, PROJECT_EXECUTIVE, {}),
        ApiErrorId.ERR_ESCALATION_NOT_EXECUTED.value,
        409,
    )

    commitment = read_commitment(commitment_id)
    assert_purchase_commitment(commitment)
    assert commitment["commitment_status"] == "PENDING"
    assert commitment["escalation_agreement_id"] == scenario["agreement"]["id"]
    assert commitment["escalation_variant"] == "NONE"
    assert commitment["escalation_accrued"] == pytest.approx(0.00)

    assert read_quote(scenario["quote"]["id"])["status"] == "OPEN"
    assert read_clause(scenario["agreement"]["id"])["status"] == "PROPOSED"
    assert read_package(scenario["package"]["id"])["status"] == "BOUGHT_OUT"


def test_countersign_allowed_once_the_attached_clause_reaches_executed():
    """The contrasting arm: executing that very clause is the only change needed, and the
    same countersignature then succeeds and converts the quote.

    PRD §3.5: "If a clause is attached, that clause must by now be `EXECUTED`, otherwise
    `ERR_ESCALATION_NOT_EXECUTED`"
    PRD §3.5: "Countersigning belongs to the `ProjectExecutive`, and it is what makes the
    order contractually binding: `commitment_status` moves from `PENDING` to `COMMITTED`."
    PRD §3.5: "On success the quote itself moves from `OPEN` to `CONVERTED`, which removes
    it from the package's `open_quote_count`, and the project's `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/commit_blocked_by_clause_not_executed
    """
    scenario = _setup_pending_commitment(clause_stage="PROPOSED")
    commitment_id = scenario["commitment"]["id"]

    executed = execute_clause(scenario["agreement"]["id"])
    assert executed["status"] == "EXECUTED"

    committed = validate_success(
        api_client.commit_purchase_commitment(commitment_id, PROJECT_EXECUTIVE, {}), 200
    )
    assert_purchase_commitment(committed)
    assert committed["commitment_status"] == "COMMITTED"
    assert committed["escalation_agreement_id"] == scenario["agreement"]["id"]

    assert read_quote(scenario["quote"]["id"])["status"] == "CONVERTED"
    assert read_package(scenario["package"]["id"])["open_quote_count"] == 0


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / commit_blocked_by_suspended_supplier
# ---------------------------------------------------------------------------

def test_countersign_blocked_by_a_supplier_suspended_after_the_po_was_cut():
    """The clause IS executed and the quote IS open, yet countersigning is refused because
    the mill behind the quote was suspended after the PO was cut.

    PRD §3.5: "The quote's supplier must be `ACTIVE`, otherwise `ERR_SUPPLIER_NOT_ACTIVE`."
    PRD §3.2: "A `ProjectExecutive` may suspend one by supplying a `reason`, which sets
    `status` to `SUSPENDED` and records that text in `suspension_reason`; existing
    commitments are left entirely untouched, but no new commitment may be countersigned
    against a suspended supplier's quote."
    PRD §3.1: "`committed_total_cost` is the sum, over the project's commitments whose
    `commitment_status` is `COMMITTED` or `CLOSED`, of each commitment's
    `committed_base_cost` plus its `escalation_accrued`; commitments that are `PENDING`,
    `CANCELLED` or `VOIDED` contribute nothing."

    Design: Difficulty/cross_entity_state_dependency/commit_blocked_by_suspended_supplier
    """
    scenario = _setup_pending_commitment(
        clause_stage="EXECUTED", readings=(("2026-07", 310.00), ("2026-08", 322.00))
    )
    commitment_id = scenario["commitment"]["id"]

    suspend_supplier(scenario["supplier"]["id"], reason="Mill entered receivership")

    validate_error(
        api_client.commit_purchase_commitment(commitment_id, PROJECT_EXECUTIVE, {}),
        ApiErrorId.ERR_SUPPLIER_NOT_ACTIVE.value,
        409,
    )

    supplier = read_supplier(scenario["supplier"]["id"])
    assert supplier["status"] == "SUSPENDED"
    assert supplier["suspension_reason"] == "Mill entered receivership"

    commitment = read_commitment(commitment_id)
    assert commitment["commitment_status"] == "PENDING"
    assert read_quote(scenario["quote"]["id"])["status"] == "OPEN"

    clause = read_clause(scenario["agreement"]["id"])
    assert clause["status"] == "EXECUTED"
    assert clause["baseline_index_value"] == pytest.approx(310.00)

    assert read_project(scenario["project"]["id"])["committed_total_cost"] == pytest.approx(0.00)


def test_suspension_leaves_an_already_countersigned_commitment_untouched():
    """The contrasting arm: the gate guards only the countersignature, so a suspension
    landing after a successful commit leaves that COMMITTED order exactly as it was.

    PRD §3.2: "existing commitments are left entirely untouched, but no new commitment may
    be countersigned against a suspended supplier's quote."
    PRD §3.5: "On success the quote itself moves from `OPEN` to `CONVERTED`, which removes
    it from the package's `open_quote_count`, and the project's `version` increments by 1."
    PRD §3.1: "`committed_total_cost` is the sum, over the project's commitments whose
    `commitment_status` is `COMMITTED` or `CLOSED`, of each commitment's
    `committed_base_cost` plus its `escalation_accrued`"

    Design: Difficulty/cross_entity_state_dependency/commit_blocked_by_suspended_supplier
    """
    scenario = _setup_pending_commitment(
        clause_stage="EXECUTED", readings=(("2026-07", 310.00), ("2026-08", 322.00))
    )
    commitment_id = scenario["commitment"]["id"]

    committed = countersign_commitment(commitment_id)
    assert committed["commitment_status"] == "COMMITTED"

    suspend_supplier(scenario["supplier"]["id"], reason="Mill entered receivership")

    after = read_commitment(commitment_id)
    assert after["commitment_status"] == "COMMITTED"
    assert after["committed_base_cost"] == pytest.approx(1150000.00)
    assert read_quote(scenario["quote"]["id"])["status"] == "CONVERTED"
    assert read_supplier(scenario["supplier"]["id"])["status"] == "SUSPENDED"
    assert read_project(scenario["project"]["id"])["committed_total_cost"] == pytest.approx(
        1150000.00
    )


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict /
#          expired_quote_state_check_beats_buyout_overrun_fiscal_check
# ---------------------------------------------------------------------------

def test_buyout_expired_quote_state_check_beats_the_overrun_fiscal_check():
    """One create violates both the own-state rule and the fiscal ceiling — the quote is
    EXPIRED and 150000.00 overruns a 100000.00 estimate — and the answer must be
    ERR_QUOTE_NOT_OPEN.

    PRD §3.5: "When a quote is both expired *and* over that ceiling, the answer is
    `ERR_QUOTE_NOT_OPEN`."
    PRD §2.9: "When a commitment is attempted against an expired quote whose `base_price`
    *also* overruns the package estimate, the own-state check wins and the answer is
    `ERR_QUOTE_NOT_OPEN`, never `ERR_BUYOUT_OVERRUN_EXCEEDED`."
    PRD §3.1: "when its last `OPEN` quote lapses it becomes `SOURCING_STALLED`"

    Design: Difficulty/priority_pair_validation_conflict/expired_quote_state_check_beats_buyout_overrun_fiscal_check
    """
    project = open_project()
    package = register_package(
        project["id"],
        scope_code="MISC-METALS-01",
        description="Miscellaneous metals package",
        estimated_cost=100000.00,
    )
    supplier = register_supplier()
    quote = submit_quote(
        package["id"],
        supplier["id"],
        base_price=150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=10,
    )

    # The clock lands exactly on expires_at; the hold is half-open, so the quote lapses.
    set_clock("2026-08-11T00:00:00.000Z")
    version_before = read_project_version(project["id"])

    error = validate_error(
        _create_commitment(
            quote["id"],
            version=version_before,
            po_number="PO-2996-0011",
            is_early_buyout=False,
        ),
        ApiErrorId.ERR_QUOTE_NOT_OPEN.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_BUYOUT_OVERRUN_EXCEEDED.value

    assert read_quote(quote["id"])["status"] == "EXPIRED"

    stalled = read_package(package["id"])
    assert stalled["status"] == "SOURCING_STALLED"
    assert stalled["open_quote_count"] == 0

    rows, meta = validate_paginated(
        api_client.list_purchase_commitments(BUYOUT_MANAGER, params={"quote_id": quote["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_project_version(project["id"]) == version_before


def test_buyout_overrun_fires_once_the_quote_is_still_open():
    """The isolating arm: with the clock left at its startup default the quote is still
    OPEN, so the very same 150000.00-against-100000.00 create reaches the fiscal ceiling.

    PRD §3.5: "the quote's `base_price` may not exceed the package's `estimated_cost` by
    more than fifteen percent — that is, a price above one-and-fifteen-hundredths times the
    current estimate is `ERR_BUYOUT_OVERRUN_EXCEEDED`."
    PRD §2.9: "**Fiscal ceilings, evaluated last.** A quote's `base_price` may not exceed
    its package's `estimated_cost` by more than the permitted buyout overrun
    (`ERR_BUYOUT_OVERRUN_EXCEEDED`, 422)."

    Design: Difficulty/priority_pair_validation_conflict/expired_quote_state_check_beats_buyout_overrun_fiscal_check
    """
    project = open_project()
    package = register_package(
        project["id"],
        scope_code="MISC-METALS-01",
        description="Miscellaneous metals package",
        estimated_cost=100000.00,
    )
    supplier = register_supplier()
    quote = submit_quote(
        package["id"],
        supplier["id"],
        base_price=150000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=10,
    )
    version_before = read_project_version(project["id"])

    validate_error(
        _create_commitment(
            quote["id"],
            version=version_before,
            po_number="PO-2996-0011",
            is_early_buyout=False,
        ),
        ApiErrorId.ERR_BUYOUT_OVERRUN_EXCEEDED.value,
        422,
    )

    assert read_quote(quote["id"])["status"] == "OPEN"
    still_sourcing = read_package(package["id"])
    assert still_sourcing["status"] == "SOURCING"
    assert still_sourcing["open_quote_count"] == 1

    _rows, meta = validate_paginated(
        api_client.list_purchase_commitments(BUYOUT_MANAGER, params={"quote_id": quote["id"]})
    )
    assert meta["total_count"] == 0
    assert read_project_version(project["id"]) == version_before


# ---------------------------------------------------------------------------
# Queue B: entities / not_found_get_purchase_commitment_with_an_unknown_uuid
# ---------------------------------------------------------------------------

def test_buyout_get_purchase_commitment_with_an_unknown_uuid_is_404():
    """A syntactically valid UUID matching no commitment row answers with the
    commitment-specific 404 code inside an error envelope, and mints nothing.

    PRD §2.8: "a missing purchase commitment `ERR_COMMITMENT_NOT_FOUND`"
    PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope
    format" ... "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/not_found_get_purchase_commitment_with_an_unknown_uuid
    """
    project = open_project()
    register_package(project["id"])

    response = api_client.get_purchase_commitment(UNKNOWN_UUID, BUYOUT_MANAGER)
    error = validate_error(response, ApiErrorId.ERR_COMMITMENT_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"
    assert error["error_id"] == "ERR_COMMITMENT_NOT_FOUND"

    rows, meta = validate_paginated(api_client.list_purchase_commitments(BUYOUT_MANAGER))
    assert meta["total_count"] == 0
    assert rows == []


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#          idempotency_second_commit_on_a_committed_commitment_rejected
# ---------------------------------------------------------------------------

def test_buyout_second_countersignature_on_a_committed_po_is_rejected():
    """Replaying commit on a row already COMMITTED is ERR_INVALID_STATE_TRANSITION — not
    ERR_QUOTE_NOT_OPEN, even though the quote is now CONVERTED — and nothing moves twice.

    PRD §3.5: "The commitment must still be `PENDING`; a second countersignature is
    `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.5: "On success the quote itself moves from `OPEN` to `CONVERTED`, which removes
    it from the package's `open_quote_count`, and the project's `version` increments by 1."
    PRD §2.4: "A project's `version` increments by exactly 1 only on the five events that
    genuinely enlarge or unwind a commitment: issuing a purchase commitment, countersigning
    it, cancelling it, releasing its material for fabrication, and accepting its delivery."

    Design: Corner/state_machines/idempotency_second_commit_on_a_committed_commitment_rejected
    """
    scenario = build_buyout_scenario(
        readings=BASELINE_READINGS,
        clause_stage="EXECUTED",
        attach_clause=True,
        issue=True,
        countersign=True,
        commitment_overrides={"is_early_buyout": False},
    )
    commitment_id = scenario["commitment"]["id"]
    assert read_project(scenario["project"]["id"])["version"] == 3

    error = validate_error(
        api_client.commit_purchase_commitment(commitment_id, PROJECT_EXECUTIVE, {}),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_QUOTE_NOT_OPEN.value

    assert read_commitment(commitment_id)["commitment_status"] == "COMMITTED"
    assert read_quote(scenario["quote"]["id"])["status"] == "CONVERTED"

    project = read_project(scenario["project"]["id"])
    assert project["committed_total_cost"] == pytest.approx(1150000.00)
    assert project["version"] == 3


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#          side_effect_execution_commit_converts_the_quote_and_bumps_project_version
# ---------------------------------------------------------------------------

def test_buyout_countersign_converts_the_quote_and_bumps_project_version():
    """Every declared side effect of the commit edge fires in one request: the quote flips
    to CONVERTED, the project moves from version 2 to 3, and the roll-ups follow.

    PRD §3.5: "Countersigning belongs to the `ProjectExecutive`, and it is what makes the
    order contractually binding: `commitment_status` moves from `PENDING` to `COMMITTED`."
    PRD §3.5: "On success the quote itself moves from `OPEN` to `CONVERTED`, which removes
    it from the package's `open_quote_count`, and the project's `version` increments by 1."
    PRD §3.5: "`committed_base_cost` is copied from the quote's `base_price` at this instant
    and is immune to any subsequent revision of that quote, and `material_package_id` is
    copied from the quote rather than supplied by the caller."
    PRD §3.1: "`committed_total_cost` is the sum, over the project's commitments whose
    `commitment_status` is `COMMITTED` or `CLOSED`, of each commitment's
    `committed_base_cost` plus its `escalation_accrued`"
    PRD §3.1: "`buyout_variance` is the full-programme figure: `estimated_total_cost`
    across every package, less `committed_total_cost`, rounded half up to 2 decimal places.
    `bought_out_variance` is the apples-to-apples figure: the sum of `estimated_cost`
    restricted to packages whose status is `BOUGHT_OUT` or `CLOSED`, less the same
    `committed_total_cost`, rounded the same way."

    Design: Corner/state_machines/side_effect_execution_commit_converts_the_quote_and_bumps_project_version
    """
    scenario = _setup_pending_commitment(clause_stage="EXECUTED")
    commitment_id = scenario["commitment"]["id"]
    assert read_project(scenario["project"]["id"])["version"] == 2

    committed = validate_success(
        api_client.commit_purchase_commitment(commitment_id, PROJECT_EXECUTIVE, {}), 200
    )
    assert_purchase_commitment(committed)
    assert committed["commitment_status"] == "COMMITTED"
    assert committed["committed_base_cost"] == pytest.approx(1150000.00)
    assert committed["material_package_id"] == scenario["package"]["id"]

    assert read_quote(scenario["quote"]["id"])["status"] == "CONVERTED"

    package = read_package(scenario["package"]["id"])
    assert package["open_quote_count"] == 0
    assert package["status"] == "BOUGHT_OUT"

    project = read_project(scenario["project"]["id"])
    assert project["version"] == 3
    assert project["committed_total_cost"] == pytest.approx(1150000.00)
    assert project["escalation_contingency_committed"] == pytest.approx(0.00)
    assert project["buyout_variance"] == pytest.approx(50000.00)
    assert project["bought_out_variance"] == pytest.approx(50000.00)


# ---------------------------------------------------------------------------
# Queue B: validations /
#          violation_error_duplicate_po_number_is_global_across_projects
# ---------------------------------------------------------------------------

def test_buyout_duplicate_po_number_is_global_across_projects():
    """Re-using PO-2996-0001 on a *different* project's package is still a duplicate, even
    with a correct OCC token, and the second project advances nothing.

    PRD §3.5: "A `BuyoutManager` issues one by naming the `quote_id` being bought out, a
    `po_number` of 1 to 40 characters that must be globally unique compared case-sensitively
    (`ERR_DUPLICATE_PO_NUMBER` otherwise)"
    PRD §2.9: "a commitment's `po_number` is globally unique (`ERR_DUPLICATE_PO_NUMBER`,
    409)"
    PRD §3.1: "commitments that are `PENDING`, `CANCELLED` or `VOIDED` contribute nothing."

    Design: Corner/validations/violation_error_duplicate_po_number_is_global_across_projects
    """
    first_project = open_project()
    first_package = register_package(first_project["id"])
    supplier = register_supplier()
    first_quote = submit_quote(first_package["id"], supplier["id"], base_price=1150000.00)

    second_project = open_project(
        name="Lakeside Clinic Addition",
        contract_number="GC-2996-B",
        escalation_contingency_budget=200000.00,
    )
    second_package = register_package(
        second_project["id"],
        scope_code="STRUCT-STEEL-01",
        description="Steel frame for the clinic addition",
        estimated_cost=450000.00,
    )
    second_quote = submit_quote(second_package["id"], supplier["id"], base_price=430000.00)

    first_commitment = issue_commitment(
        first_project["id"], first_quote["id"], po_number="PO-2996-0001", is_early_buyout=False
    )
    second_version = read_project_version(second_project["id"])

    validate_error(
        _create_commitment(
            second_quote["id"],
            version=second_version,
            po_number="PO-2996-0001",
            is_early_buyout=False,
        ),
        ApiErrorId.ERR_DUPLICATE_PO_NUMBER.value,
        409,
    )

    kept = read_commitment(first_commitment["id"])
    assert kept["po_number"] == "PO-2996-0001"
    assert kept["commitment_status"] == "PENDING"

    project = read_project(second_project["id"])
    assert project["version"] == second_version
    assert project["committed_total_cost"] == pytest.approx(0.00)
    assert read_package(second_package["id"])["status"] == "SOURCING"


# ---------------------------------------------------------------------------
# Queue B: validations /
#          violation_error_package_already_carries_a_pending_commitment
# ---------------------------------------------------------------------------

def test_buyout_package_already_carrying_a_pending_commitment_refuses_a_second_po():
    """The at-most-one rule counts PENDING as well as COMMITTED, so a second buyout from a
    competing supplier's OPEN quote is refused even though the first PO is not committed.

    PRD §3.5: "The package may not already carry another commitment whose
    `commitment_status` is `PENDING` or `COMMITTED` — one live purchase order per package,
    and a second is `ERR_PACKAGE_ALREADY_COMMITTED`."
    PRD §2.9: "a package may carry at most one commitment that is `PENDING` or `COMMITTED`
    (`ERR_PACKAGE_ALREADY_COMMITTED`, 409)"
    PRD §2.9: "a new quote's price-hold interval may not overlap a live interval for the
    same package and supplier (`ERR_PRICE_HOLD_OVERLAP`, 409)"

    Design: Corner/validations/violation_error_package_already_carries_a_pending_commitment
    """
    world = _setup_two_quotes_on_one_package()

    issue_commitment(
        world["project"]["id"],
        world["first_quote"]["id"],
        po_number="PO-2996-0001",
        is_early_buyout=False,
    )
    version_after_first = read_project_version(world["project"]["id"])

    validate_error(
        _create_commitment(
            world["second_quote"]["id"],
            version=version_after_first,
            po_number="PO-2996-0002",
            is_early_buyout=False,
        ),
        ApiErrorId.ERR_PACKAGE_ALREADY_COMMITTED.value,
        409,
    )

    second_quote = read_quote(world["second_quote"]["id"])
    assert_quote(second_quote)
    assert second_quote["status"] == "OPEN"

    package = read_package(world["package"]["id"])
    assert package["open_quote_count"] == 2
    assert package["status"] == "BOUGHT_OUT"

    project = read_project(world["project"]["id"])
    assert project["version"] == version_after_first
    assert project["committed_total_cost"] == pytest.approx(0.00)


# ---------------------------------------------------------------------------
# Queue B: validations /
#          cross_entity_validation_a_clause_from_another_quote_is_a_mismatch
# ---------------------------------------------------------------------------

def test_buyout_a_clause_from_another_quote_is_an_agreement_quote_mismatch():
    """Attachability passes because the clause is EXECUTED; what fires is the referential
    check, because the clause hangs off the *other* supplier's quote.

    PRD §3.5: "An attached clause must also belong to the very quote being bought out: a
    clause whose own `quote_id` differs from the supplied `quote_id` is
    `ERR_AGREEMENT_QUOTE_MISMATCH`."
    PRD §2.9: "A clause attached at commitment creation must reference the very quote being
    bought out (`ERR_AGREEMENT_QUOTE_MISMATCH`, 422)."
    PRD §3.4: "Execution then freezes `baseline_index_value` from that reading's `value`"

    Design: Corner/validations/cross_entity_validation_a_clause_from_another_quote_is_a_mismatch
    """
    world = _setup_two_quotes_on_one_package()
    agreement = execute_clause(propose_clause(draft_clause(world["first_quote"]["id"])["id"])["id"])
    assert agreement["status"] == "EXECUTED"

    version_before = read_project_version(world["project"]["id"])

    validate_error(
        _create_commitment(
            world["second_quote"]["id"],
            version=version_before,
            po_number="PO-2996-0001",
            escalation_agreement_id=agreement["id"],
            is_early_buyout=False,
        ),
        ApiErrorId.ERR_AGREEMENT_QUOTE_MISMATCH.value,
        422,
    )

    clause = read_clause(agreement["id"])
    assert clause["quote_id"] == world["first_quote"]["id"]
    assert clause["status"] == "EXECUTED"
    assert clause["baseline_index_value"] == pytest.approx(310.00)

    package = read_package(world["package"]["id"])
    assert package["status"] == "SOURCING"
    assert package["open_quote_count"] == 2
    assert read_project_version(world["project"]["id"]) == version_before


# ---------------------------------------------------------------------------
# Queue B: validations /
#          priority_ordering_lapsed_clause_attachability_beats_the_quote_mismatch_check
# ---------------------------------------------------------------------------

def test_buyout_lapsed_clause_attachability_beats_the_quote_mismatch_check():
    """The attached clause is BOTH lapsed and owned by another quote; the cross-entity
    state gate outranks the referential check, so the answer is
    ERR_AGREEMENT_NOT_ATTACHABLE.

    PRD §3.5: "An attached clause must be in `PROPOSED`, `COUNTERED` or `EXECUTED`;
    attaching a `LAPSED` clause is `ERR_AGREEMENT_NOT_ATTACHABLE`"
    PRD §2.9: "**Cross-entity state gates,** evaluated only once the target row's own state
    is legal, and all carrying HTTP 409." ... "Attaching a clause at commitment creation
    requires that clause to be `PROPOSED`, `COUNTERED` or `EXECUTED`
    (`ERR_AGREEMENT_NOT_ATTACHABLE`)."
    PRD §2.5: "Hop one expires price holds: every quote still `OPEN` whose `expires_at` is
    at or before the supplied instant becomes `EXPIRED`, processed in `created_at` ascending
    order. Hop two lapses negotiations: every escalation agreement attached to a quote that
    just expired, and whose own status is `DRAFT`, `PROPOSED` or `COUNTERED`, becomes
    `LAPSED`."
    PRD §3.3: "New quotes start `OPEN` with `supersedes_quote_id` null, and their arrival is
    what lifts a package out of `IDENTIFIED` or revives it from `SOURCING_STALLED`"

    Design: Corner/validations/priority_ordering_lapsed_clause_attachability_beats_the_quote_mismatch_check
    """
    project = open_project()
    package = register_package(project["id"])
    first_supplier = register_supplier()
    first_quote = submit_quote(package["id"], first_supplier["id"], base_price=1150000.00)
    publish_reading("PPI_STEEL_MILL", "2026-07", 310.00)
    agreement = propose_clause(draft_clause(first_quote["id"])["id"])
    assert agreement["status"] == "PROPOSED"

    # Hop 1 expires the quote and hop 2 lapses the clause hanging off it.
    set_clock("2026-09-20T00:00:00.000Z")

    second_supplier = register_supplier(legal_name="Northline Steel Mills")
    second_quote = submit_quote(
        package["id"],
        second_supplier["id"],
        base_price=1120000.00,
        received_at="2026-09-20T00:00:00.000Z",
        price_hold_days=45,
    )
    version_before = read_project_version(project["id"])

    error = validate_error(
        _create_commitment(
            second_quote["id"],
            version=version_before,
            po_number="PO-2996-0001",
            escalation_agreement_id=agreement["id"],
            is_early_buyout=False,
        ),
        ApiErrorId.ERR_AGREEMENT_NOT_ATTACHABLE.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_AGREEMENT_QUOTE_MISMATCH.value

    lapsed = read_clause(agreement["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed["executed_at"] is None

    assert read_quote(first_quote["id"])["status"] == "EXPIRED"

    live = read_quote(second_quote["id"])
    assert live["status"] == "OPEN"
    assert_instant_equals(live["expires_at"], "2026-11-04T00:00:00.000Z", "Quote.expires_at")

    revived = read_package(package["id"])
    assert revived["status"] == "SOURCING"
    assert revived["open_quote_count"] == 1
    assert read_project_version(project["id"]) == version_before


# ---------------------------------------------------------------------------
# Queue B: endpoints /
#          cross_reference_link_one_create_ties_a_quote_a_clause_and_a_package_together
# ---------------------------------------------------------------------------

def test_buyout_create_ties_a_quote_a_clause_and_a_package_together():
    """One create copies rather than re-derives: `committed_base_cost` comes from the
    quote's `base_price`, `material_package_id` is taken from the quote, and
    `requires_storage_arrangement` mirrors the declared `is_early_buyout`.

    PRD §3.5: "`committed_base_cost` is copied from the quote's `base_price` at this instant
    and is immune to any subsequent revision of that quote, and `material_package_id` is
    copied from the quote rather than supplied by the caller."
    PRD §3.5: "the server mirrors that declaration into `requires_storage_arrangement`,
    which always equals `is_early_buyout`."
    PRD §3.5: "The new row starts with `commitment_status` `PENDING` and `delivery_posture`
    `SCHEDULED`"
    PRD §3.5: "The addressed package leaves `SOURCING` — or `SOURCING_STALLED`, since a
    stalled package can still be bought out from a quote created after the stall, provided
    that quote is `OPEN` — and becomes `BOUGHT_OUT`. The owning project's `version`
    increments by 1"
    PRD §3.1: "commitments that are `PENDING`, `CANCELLED` or `VOIDED` contribute nothing."

    Design: Corner/endpoints/cross_reference_link_one_create_ties_a_quote_a_clause_and_a_package_together
    """
    project = open_project()
    package = register_package(project["id"])
    supplier = register_supplier()
    quote = submit_quote(package["id"], supplier["id"], base_price=1150000.00)
    publish_reading("PPI_STEEL_MILL", "2026-07", 310.00)
    agreement = propose_clause(draft_clause(quote["id"])["id"])

    version_before = read_project_version(project["id"])
    assert version_before == 1

    commitment = validate_success(
        _create_commitment(
            quote["id"],
            version=version_before,
            po_number="PO-2996-0001",
            escalation_agreement_id=agreement["id"],
            is_early_buyout=True,
        ),
        201,
    )
    assert_purchase_commitment(commitment)
    assert commitment["quote_id"] == quote["id"]
    assert commitment["escalation_agreement_id"] == agreement["id"]
    assert commitment["material_package_id"] == package["id"]
    assert commitment["committed_base_cost"] == pytest.approx(1150000.00)
    assert commitment["is_early_buyout"] is True
    assert commitment["requires_storage_arrangement"] is True
    assert commitment["commitment_status"] == "PENDING"
    assert commitment["delivery_posture"] == "SCHEDULED"

    bought_out = read_package(package["id"])
    assert bought_out["status"] == "BOUGHT_OUT"
    assert bought_out["open_quote_count"] == 1

    after = read_project(project["id"])
    assert after["version"] == 2
    assert after["committed_total_cost"] == pytest.approx(0.00)
