"""Published index readings, escalation-clause drafting, the bounded negotiation cycle
and clause execution with its cross-entity gates (PRD §2.4, §2.8, §2.9, §3.4).

Every test in this module translates exactly one design instance from
SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml; the trailing
``Design:`` line of each docstring names it.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_escalation_agreement,
    assert_index_reading,
    assert_instant_equals,
    assert_quote,
    counter_clause,
    draft_clause,
    execute_clause,
    issue_commitment,
    make_supplier_rep_headers,
    open_project,
    propose_clause,
    publish_reading,
    read_clause,
    read_package,
    read_project_version,
    read_quote,
    register_package,
    register_supplier,
    revise_quote,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    counter_escalation_agreement_payload,
    create_escalation_agreement_payload,
    create_index_reading_payload,
    create_purchase_commitment_payload,
    propose_escalation_agreement_payload,
)

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]
PROJECT_EXECUTIVE = TEST_USERS["project_executive_headers"]

# The logical clock's fixed startup default (PRD §2.5).
CLOCK_START = "2026-08-01T00:00:00.000Z"

# A syntactically valid UUID that names no escalation agreement.
UNKNOWN_AGREEMENT_ID = "00000000-0000-4000-8000-000000000999"


# ─── private setup helpers (not tests — no Design tag) ─────────────────────

def _setup_quoted_package(
    *,
    package_overrides=None,
    supplier_overrides=None,
    quote_overrides=None,
    readings=(("2026-07", 310.00),),
):
    """project → steel package → supplier → OPEN quote → published PPI_STEEL_MILL readings."""
    project = open_project()
    package = register_package(project["id"], **(package_overrides or {}))
    supplier = register_supplier(**(supplier_overrides or {}))
    quote = submit_quote(package["id"], supplier["id"], **(quote_overrides or {}))
    published = [publish_reading("PPI_STEEL_MILL", period, value) for period, value in readings]
    return {
        "project": project,
        "package": package,
        "supplier": supplier,
        "quote": quote,
        "readings": published,
    }


def _setup_proposed_clause(*, clause_overrides=None, **world_kwargs):
    """The world above plus a clause drafted on that quote and carried to PROPOSED."""
    world = _setup_quoted_package(**world_kwargs)
    clause = draft_clause(world["quote"]["id"], **(clause_overrides or {}))
    world["agreement"] = propose_clause(clause["id"])
    return world


def _counter(agreement_id, supplier_id, **payload_overrides):
    """Raw counter call as the quote's own SupplierRep, returning the HTTP response."""
    return api_client.counter_escalation_agreement(
        agreement_id,
        counter_escalation_agreement_payload(**payload_overrides),
        make_supplier_rep_headers(supplier_id),
    )


def _propose(agreement_id, **payload_overrides):
    """Raw propose call as the BuyoutManager, returning the HTTP response."""
    return api_client.propose_escalation_agreement(
        agreement_id, propose_escalation_agreement_payload(**payload_overrides), BUYOUT_MANAGER
    )

# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine /
#          negotiation_cycle_returns_to_proposed_and_stops_at_three_rounds
# ---------------------------------------------------------------------------

def test_negotiation_cycle_returns_to_proposed_and_increments_round_only_on_counter():
    """Three counter/propose laps walk PROPOSED → COUNTERED → PROPOSED and only the
    counter moves `round_number`, which lands on 3 with the clause back in PROPOSED.

    PRD §3.4: "A `BuyoutManager` puts terms on the table, moving the clause from `DRAFT`
    to `PROPOSED`, and this same act is also how it comes back from `COUNTERED` to
    `PROPOSED` — the cycle `PROPOSED → COUNTERED → PROPOSED` is the whole negotiation."
    PRD §3.4: "A counter must supply `cap_pct` and `contractor_share_pct`, and may supply
    `deadband_pct` and a `counter_note`; the supplied values overwrite the stored terms
    and `round_number` increments by exactly 1."
    PRD §3.4: "Either way the underlying quote must still be `OPEN`, and any of `cap_pct`,
    `contractor_share_pct`, `deadband_pct` or `proposed_terms_note` supplied with the
    proposal overwrite what was stored."

    Design: Difficulty/non_linear_state_machine/negotiation_cycle_returns_to_proposed_and_stops_at_three_rounds
    """
    world = _setup_proposed_clause(
        clause_overrides={"cap_pct": 8.0, "contractor_share_pct": 40.0, "deadband_pct": 2.0}
    )
    agreement_id = world["agreement"]["id"]
    supplier_id = world["supplier"]["id"]

    assert world["agreement"]["status"] == "PROPOSED"
    assert world["agreement"]["round_number"] == 0

    # Lap 1 — the supplier counters: status flips to COUNTERED, round 0 → 1.
    countered = validate_success(
        _counter(agreement_id, supplier_id, cap_pct=9.0, contractor_share_pct=40.0,
                 counter_note="First supplier counter"),
        200,
    )
    assert_escalation_agreement(countered)
    assert countered["status"] == "COUNTERED"
    assert countered["round_number"] == 1
    assert countered["cap_pct"] == pytest.approx(9.0)
    assert countered["contractor_share_pct"] == pytest.approx(40.0)

    # The buyout group re-proposes: back to PROPOSED, and round_number does NOT move.
    reproposed = validate_success(_propose(agreement_id, cap_pct=8.5), 200)
    assert reproposed["status"] == "PROPOSED"
    assert reproposed["round_number"] == 1
    assert reproposed["cap_pct"] == pytest.approx(8.5)
    assert reproposed["contractor_share_pct"] == pytest.approx(40.0)
    assert reproposed["deadband_pct"] == pytest.approx(2.0)

    # Lap 2.
    countered = validate_success(
        _counter(agreement_id, supplier_id, cap_pct=9.5, contractor_share_pct=40.0,
                 counter_note="Second supplier counter"),
        200,
    )
    assert countered["status"] == "COUNTERED"
    assert countered["round_number"] == 2
    assert countered["cap_pct"] == pytest.approx(9.5)

    reproposed = validate_success(_propose(agreement_id, cap_pct=8.8), 200)
    assert reproposed["status"] == "PROPOSED"
    assert reproposed["round_number"] == 2
    assert reproposed["cap_pct"] == pytest.approx(8.8)

    # Lap 3 — the third and last counter permitted while round_number is below 3.
    countered = validate_success(
        _counter(agreement_id, supplier_id, cap_pct=10.0, contractor_share_pct=40.0,
                 counter_note="Third and final supplier counter"),
        200,
    )
    assert countered["status"] == "COUNTERED"
    assert countered["round_number"] == 3
    assert countered["cap_pct"] == pytest.approx(10.0)

    # The cycle returns to PROPOSED a third time and stays at round 3.
    final = validate_success(_propose(agreement_id, cap_pct=9.0), 200)
    assert final["status"] == "PROPOSED"
    assert final["round_number"] == 3
    assert final["cap_pct"] == pytest.approx(9.0)
    assert final["contractor_share_pct"] == pytest.approx(40.0)
    assert final["counter_note"] == "Third and final supplier counter"
    assert final["baseline_index_value"] is None
    assert final["executed_at"] is None

    persisted = read_clause(agreement_id)
    assert persisted["status"] == "PROPOSED"
    assert persisted["round_number"] == 3
    assert persisted["cap_pct"] == pytest.approx(9.0)


def test_negotiation_fourth_counter_is_exhausted_and_mutates_nothing():
    """A fourth counter, attempted at `round_number` 3, is refused with
    ERR_NEGOTIATION_ROUNDS_EXHAUSTED and leaves every stored term untouched.

    PRD §3.4: "Second, the negotiation is capped at three rounds: a counter is only
    permitted while `round_number` is still below 3, and a fourth attempt is refused with
    `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` and — importantly — **no mutation whatsoever**, so
    the stored terms and `round_number` are exactly what they were before the rejected
    attempt."

    Design: Difficulty/non_linear_state_machine/negotiation_cycle_returns_to_proposed_and_stops_at_three_rounds
    """
    world = _setup_proposed_clause(
        clause_overrides={"cap_pct": 8.0, "contractor_share_pct": 40.0, "deadband_pct": 2.0}
    )
    agreement_id = world["agreement"]["id"]
    supplier_id = world["supplier"]["id"]

    counter_clause(agreement_id, supplier_id, cap_pct=9.0, contractor_share_pct=40.0,
                   counter_note="First supplier counter")
    propose_clause(agreement_id, cap_pct=8.5)
    counter_clause(agreement_id, supplier_id, cap_pct=9.5, contractor_share_pct=40.0,
                   counter_note="Second supplier counter")
    propose_clause(agreement_id, cap_pct=8.8)
    counter_clause(agreement_id, supplier_id, cap_pct=10.0, contractor_share_pct=40.0,
                   counter_note="Third and final supplier counter")
    before = propose_clause(agreement_id, cap_pct=9.0)
    assert before["round_number"] == 3
    assert before["status"] == "PROPOSED"

    validate_error(
        _counter(agreement_id, supplier_id, cap_pct=11.0, contractor_share_pct=35.0,
                 counter_note="Fourth counter that must not land"),
        ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value,
        409,
    )

    after = read_clause(agreement_id)
    assert after["status"] == "PROPOSED"
    assert after["round_number"] == 3
    assert after["cap_pct"] == pytest.approx(9.0)
    assert after["contractor_share_pct"] == pytest.approx(40.0)
    assert after["deadband_pct"] == pytest.approx(2.0)
    assert after["counter_note"] == "Third and final supplier counter"
    assert after["version"] == before["version"]
    assert_instant_equals(after["updated_at"], before["updated_at"], "EscalationAgreement.updated_at")


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / clause_execute_blocked_by_superseded_quote
# ---------------------------------------------------------------------------

def test_clause_execute_refused_when_the_underlying_quote_is_superseded():
    """The clause's own PROPOSED status is legal, yet execute is refused because the
    quote behind it went SUPERSEDED on revision — and no baseline is frozen.

    PRD §3.4: "The underlying quote must still be `OPEN` — a clause on a dead price is
    worthless, and this cross-entity gate reports `ERR_QUOTE_NOT_OPEN`."
    PRD §3.3: "it moves the addressed quote from `OPEN` to `SUPERSEDED` and creates a
    brand-new quote carrying its own `base_price`, `received_at` and `price_hold_days`,
    with `supersedes_quote_id` set to the superseded quote's identifier."
    PRD §3.4: "A new clause starts in `DRAFT` with `round_number` 0, `counter_note` null,
    `executed_at` null and `baseline_index_value` null — the baseline value stays null
    until execution."

    Design: Difficulty/cross_entity_state_dependency/clause_execute_blocked_by_superseded_quote
    """
    world = _setup_proposed_clause()
    agreement_id = world["agreement"]["id"]
    original_quote_id = world["quote"]["id"]

    revision = revise_quote(
        original_quote_id,
        world["supplier"]["id"],
        base_price=1140000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=45,
    )

    validate_error(
        api_client.execute_escalation_agreement(agreement_id, PROJECT_EXECUTIVE, {}),
        ApiErrorId.ERR_QUOTE_NOT_OPEN.value,
        409,
    )

    clause = read_clause(agreement_id)
    assert clause["status"] == "PROPOSED"
    assert clause["baseline_index_value"] is None
    assert clause["executed_at"] is None

    superseded = read_quote(original_quote_id)
    assert_quote(superseded)
    assert superseded["status"] == "SUPERSEDED"

    live = read_quote(revision["id"])
    assert live["status"] == "OPEN"
    assert live["supersedes_quote_id"] == original_quote_id

    package = read_package(world["package"]["id"])
    assert package["open_quote_count"] == 1


def test_clause_execute_freezes_the_baseline_while_the_quote_is_still_open():
    """The contrasting arm: with the very same clause on a still-OPEN quote, execute
    succeeds, freezes `baseline_index_value` from the 2026-07 reading and stamps
    `executed_at` with the logical clock.

    PRD §3.4: "Execution then freezes `baseline_index_value` from that reading's `value`,
    pinning the reference number for the rest of the clause's life so that a later
    correction to the index cannot retroactively change the baseline, and stamps
    `executed_at` with the current logical clock. `EXECUTED` is terminal."
    PRD §2.5: "the logical clock starts at exactly `2026-08-01T00:00:00Z`"

    Design: Difficulty/cross_entity_state_dependency/clause_execute_blocked_by_superseded_quote
    """
    world = _setup_proposed_clause()
    agreement_id = world["agreement"]["id"]

    executed = validate_success(
        api_client.execute_escalation_agreement(agreement_id, PROJECT_EXECUTIVE, {}), 200
    )
    assert_escalation_agreement(executed)
    assert executed["status"] == "EXECUTED"
    assert executed["baseline_index_value"] == pytest.approx(310.00)
    assert_instant_equals(executed["executed_at"], CLOCK_START, "EscalationAgreement.executed_at")

    assert read_quote(world["quote"]["id"])["status"] == "OPEN"
    assert read_package(world["package"]["id"])["open_quote_count"] == 1


# ---------------------------------------------------------------------------
# Queue B: entities /
#          immutability_index_reading_carries_no_version_and_no_write_back
# ---------------------------------------------------------------------------

def test_index_reading_carries_no_version_and_no_updated_at():
    """A published reading is append-only configuration: the created row exposes `id`
    and `created_at` only, and it reads back unchanged through the filtered listing.

    PRD §2.4: "Published index readings are the sole exception: a reading is append-only
    configuration data with no update endpoint and no delete endpoint, so it carries only
    `id` and `created_at` — it has **no** `updated_at` field and **no** `version` field at
    all."
    PRD §3.4: "Readings can be listed with filters on `index_code` and `period`."

    Design: Corner/entities/immutability_index_reading_carries_no_version_and_no_write_back
    """
    created = validate_success(
        api_client.create_index_reading(
            create_index_reading_payload(
                index_code="PPI_STEEL_MILL",
                period="2026-07",
                value=310.00,
                published_at="2026-07-15T00:00:00.000Z",
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    assert_index_reading(created)
    assert "version" not in created
    assert "updated_at" not in created

    rows, meta = validate_paginated(
        api_client.list_index_readings(
            BUYOUT_MANAGER, params={"index_code": "PPI_STEEL_MILL", "period": "2026-07"}
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["index_code"] == "PPI_STEEL_MILL"
    assert rows[0]["period"] == "2026-07"
    assert rows[0]["value"] == pytest.approx(310.00)
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#          valid_transition_propose_overwrites_terms_and_leaves_round_number_zero
# ---------------------------------------------------------------------------

def test_index_negotiation_propose_overwrites_terms_and_leaves_round_number_zero():
    """Proposing from DRAFT overwrites only the terms supplied, leaves the rest of the
    clause alone, and does not move `round_number` off 0.

    PRD §3.4: "Either way the underlying quote must still be `OPEN`, and any of `cap_pct`,
    `contractor_share_pct`, `deadband_pct` or `proposed_terms_note` supplied with the
    proposal overwrite what was stored."
    PRD §3.4: "the supplied values overwrite the stored terms and `round_number`
    increments by exactly 1."
    PRD §3.4: "A new clause starts in `DRAFT` with `round_number` 0, `counter_note` null,
    `executed_at` null and `baseline_index_value` null — the baseline value stays null
    until execution."

    Design: Corner/state_machines/valid_transition_propose_overwrites_terms_and_leaves_round_number_zero
    """
    world = _setup_quoted_package()
    drafted = draft_clause(
        world["quote"]["id"], cap_pct=8.0, contractor_share_pct=40.0, deadband_pct=2.0
    )
    assert drafted["status"] == "DRAFT"
    assert drafted["round_number"] == 0

    proposed = validate_success(
        _propose(drafted["id"], cap_pct=7.5,
                 proposed_terms_note="Reduced cap after estimating review"),
        200,
    )
    assert_escalation_agreement(proposed)
    assert proposed["status"] == "PROPOSED"
    assert proposed["cap_pct"] == pytest.approx(7.5)
    assert proposed["contractor_share_pct"] == pytest.approx(40.0)
    assert proposed["deadband_pct"] == pytest.approx(2.0)
    assert proposed["proposed_terms_note"] == "Reduced cap after estimating review"
    assert proposed["round_number"] == 0
    assert proposed["baseline_index_value"] is None
    assert proposed["executed_at"] is None

    persisted = read_clause(drafted["id"])
    assert persisted["status"] == "PROPOSED"
    assert persisted["cap_pct"] == pytest.approx(7.5)
    assert persisted["round_number"] == 0


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#          invalid_transitions_second_propose_on_an_executed_clause_rejected
# ---------------------------------------------------------------------------

def test_index_negotiation_second_propose_on_an_executed_clause_rejected():
    """`EXECUTED` is terminal, so replaying propose is ERR_INVALID_STATE_TRANSITION and
    the rejected cap is never written over the frozen clause.

    PRD §3.4: "A `BuyoutManager` puts terms on the table, moving the clause from `DRAFT`
    to `PROPOSED`, and this same act is also how it comes back from `COUNTERED` to
    `PROPOSED`"
    PRD §3.4: "`EXECUTED` is terminal."
    PRD §2.9: "The requested transition must be a declared edge out of the target row's
    current state." ... "An escalation agreement's propose, counter or execute must match
    its current status"

    Design: Corner/state_machines/invalid_transitions_second_propose_on_an_executed_clause_rejected
    """
    world = _setup_proposed_clause(
        clause_overrides={"cap_pct": 8.0, "contractor_share_pct": 40.0, "deadband_pct": 2.0}
    )
    executed = execute_clause(world["agreement"]["id"])
    assert executed["status"] == "EXECUTED"

    validate_error(
        _propose(world["agreement"]["id"], cap_pct=12.0),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        409,
    )

    clause = read_clause(world["agreement"]["id"])
    assert clause["status"] == "EXECUTED"
    assert clause["cap_pct"] == pytest.approx(8.0)
    assert clause["baseline_index_value"] == pytest.approx(310.00)
    assert_instant_equals(clause["executed_at"], CLOCK_START, "EscalationAgreement.executed_at")


# ---------------------------------------------------------------------------
# Queue B: validations /
#          violation_error_duplicate_index_reading_for_one_code_and_period
# ---------------------------------------------------------------------------

def test_index_reading_duplicate_code_and_period_pair_is_rejected():
    """Uniqueness is on the (index_code, period) PAIR: republishing steel 2026-07 is
    refused while the same period under another code and the same code under another
    period both land, and the original 310.00 is never overwritten.

    PRD §3.4: "The pair of index code and period is globally unique; a repeat is
    `ERR_DUPLICATE_INDEX_READING`."
    PRD §2.9: "an index reading's index and period pair is globally unique
    (`ERR_DUPLICATE_INDEX_READING`, 409)"
    PRD §3.4: "Readings are immutable append-only configuration: there is no revision and
    no deletion, so a correction is published as a later period rather than as an edit"

    Design: Corner/validations/violation_error_duplicate_index_reading_for_one_code_and_period
    """
    publish_reading("PPI_STEEL_MILL", "2026-07", 310.00)

    validate_error(
        api_client.create_index_reading(
            create_index_reading_payload(
                index_code="PPI_STEEL_MILL", period="2026-07", value=999.00,
                published_at="2026-07-20T00:00:00.000Z",
            ),
            BUYOUT_MANAGER,
        ),
        ApiErrorId.ERR_DUPLICATE_INDEX_READING.value,
        409,
    )

    # Same period, different index code — a distinct pair, so it is accepted.
    copper = validate_success(
        api_client.create_index_reading(
            create_index_reading_payload(
                index_code="PPI_COPPER_WIRE", period="2026-07", value=200.00,
                published_at="2026-07-15T00:00:00.000Z",
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    assert copper["index_code"] == "PPI_COPPER_WIRE"

    # Same index code, different period — also a distinct pair.
    august = validate_success(
        api_client.create_index_reading(
            create_index_reading_payload(
                index_code="PPI_STEEL_MILL", period="2026-08", value=322.00,
                published_at="2026-08-15T00:00:00.000Z",
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    assert august["period"] == "2026-08"

    rows, meta = validate_paginated(
        api_client.list_index_readings(BUYOUT_MANAGER, params={"index_code": "PPI_STEEL_MILL"})
    )
    assert meta["total_count"] == 2
    by_period = {row["period"]: row for row in rows}
    assert by_period["2026-07"]["value"] == pytest.approx(310.00)
    assert by_period["2026-08"]["value"] == pytest.approx(322.00)
    for row in rows:
        assert "version" not in row


# ---------------------------------------------------------------------------
# Queue B: validations /
#          cross_entity_validation_clause_index_code_must_match_the_package_commodity
# ---------------------------------------------------------------------------

def test_clause_index_code_must_match_the_package_commodity():
    """A copper clause drafted against a steel package is refused even though the copper
    reading exists and the quote is perfectly OPEN — the check reaches the PACKAGE.

    PRD §3.4: "The clause's `index_code` **must** equal the `commodity_index_code` of the
    package behind its quote — a copper clause on a steel package is
    `ERR_INDEX_CODE_MISMATCH`"
    PRD §2.9: "A clause's `index_code` must equal the `commodity_index_code` of its
    quote's package (`ERR_INDEX_CODE_MISMATCH`, 422)"

    Design: Corner/validations/cross_entity_validation_clause_index_code_must_match_the_package_commodity
    """
    world = _setup_quoted_package()
    publish_reading("PPI_COPPER_WIRE", "2026-07", 200.00)

    validate_error(
        api_client.create_escalation_agreement(
            create_escalation_agreement_payload(
                quote_id=world["quote"]["id"],
                index_code="PPI_COPPER_WIRE",
                baseline_index_period="2026-07",
            ),
            BUYOUT_MANAGER,
        ),
        ApiErrorId.ERR_INDEX_CODE_MISMATCH.value,
        422,
    )

    quotes, _meta = validate_paginated(
        api_client.list_quotes(
            BUYOUT_MANAGER, params={"material_package_id": world["package"]["id"]}
        )
    )
    live = next(q for q in quotes if q["id"] == world["quote"]["id"])
    assert live["status"] == "OPEN"
    assert_instant_equals(live["expires_at"], "2026-09-15T00:00:00.000Z", "Quote.expires_at")

    clauses, clause_meta = validate_paginated(
        api_client.list_escalation_agreements(
            BUYOUT_MANAGER, params={"quote_id": world["quote"]["id"]}
        )
    )
    assert clause_meta["total_count"] == 0
    assert clauses == []

    package = read_package(world["package"]["id"])
    assert package["commodity_index_code"] == "PPI_STEEL_MILL"
    assert package["status"] == "SOURCING"


# ---------------------------------------------------------------------------
# Queue B: validations /
#          violation_error_a_counter_that_moves_no_term_in_the_suppliers_favour
# ---------------------------------------------------------------------------

def test_negotiation_counter_must_move_a_term_in_the_suppliers_favour():
    """Echoing the stored terms back, and lowering the cap, are both unresponsive; only
    dropping the contractor share lands, and only that call moves `round_number` to 1.

    PRD §3.4: "First, it must be **responsive**: it has to move at least one term in the
    supplier's favour, meaning the offered `cap_pct` is strictly greater than the currently
    stored `cap_pct`, or the offered `contractor_share_pct` is strictly less than the
    currently stored `contractor_share_pct`. A counter that raises neither ceiling nor
    lowers neither share is `ERR_COUNTER_NOT_RESPONSIVE`."
    PRD §3.4: "the supplied values overwrite the stored terms and `round_number` increments
    by exactly 1."

    Design: Corner/validations/violation_error_a_counter_that_moves_no_term_in_the_suppliers_favour
    """
    world = _setup_proposed_clause(
        clause_overrides={"cap_pct": 8.0, "contractor_share_pct": 40.0, "deadband_pct": 2.0}
    )
    agreement_id = world["agreement"]["id"]
    supplier_id = world["supplier"]["id"]

    # Echoing both stored terms back moves nothing in the supplier's favour.
    validate_error(
        _counter(agreement_id, supplier_id, cap_pct=8.0, contractor_share_pct=40.0),
        ApiErrorId.ERR_COUNTER_NOT_RESPONSIVE.value,
        422,
    )
    # Lowering the cap moves a term in the CONTRACTOR's favour, so it is still unresponsive.
    validate_error(
        _counter(agreement_id, supplier_id, cap_pct=7.0, contractor_share_pct=40.0),
        ApiErrorId.ERR_COUNTER_NOT_RESPONSIVE.value,
        422,
    )

    accepted = validate_success(
        _counter(agreement_id, supplier_id, cap_pct=8.0, contractor_share_pct=35.0,
                 counter_note="We can carry a smaller contractor share"),
        200,
    )
    assert accepted["status"] == "COUNTERED"
    assert accepted["round_number"] == 1
    assert accepted["cap_pct"] == pytest.approx(8.0)
    assert accepted["contractor_share_pct"] == pytest.approx(35.0)

    persisted = read_clause(agreement_id)
    assert persisted["status"] == "COUNTERED"
    assert persisted["round_number"] == 1
    assert persisted["cap_pct"] == pytest.approx(8.0)
    assert persisted["contractor_share_pct"] == pytest.approx(35.0)


# ---------------------------------------------------------------------------
# Queue B: validations /
#          temporal_validation_price_hold_through_may_not_outlive_the_quote
# ---------------------------------------------------------------------------

def test_clause_price_hold_through_may_not_outlive_the_quote():
    """A `price_hold_through` one day past the quote's 2026-09-15 expiry is
    ERR_INVALID_REQUEST — explicitly not a storage-window error — while exact equality
    at 2026-09-15 is accepted.

    PRD §3.4: "The `price_hold_through` instant may not be later than the quote's
    `expires_at`; a clause cannot promise a firm price beyond the hold the quote itself
    grants, and that violation is reported as `ERR_INVALID_REQUEST`."
    PRD §2.9: "A clause's `price_hold_through` must be at or before the quote's
    `expires_at` — note this is reported as `ERR_INVALID_REQUEST`, not as a storage-window
    error."
    PRD §3.4: "A new clause starts in `DRAFT` with `round_number` 0"

    Design: Corner/validations/temporal_validation_price_hold_through_may_not_outlive_the_quote
    """
    world = _setup_quoted_package()
    quote_id = world["quote"]["id"]

    error = validate_error(
        api_client.create_escalation_agreement(
            create_escalation_agreement_payload(
                quote_id=quote_id, price_hold_through="2026-09-16T00:00:00.000Z"
            ),
            BUYOUT_MANAGER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    assert error["error_id"] != ApiErrorId.ERR_STORAGE_WINDOW_INVALID.value

    at_equality = validate_success(
        api_client.create_escalation_agreement(
            create_escalation_agreement_payload(
                quote_id=quote_id, price_hold_through="2026-09-15T00:00:00.000Z"
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    assert_escalation_agreement(at_equality)
    assert_instant_equals(
        at_equality["price_hold_through"],
        "2026-09-15T00:00:00.000Z",
        "EscalationAgreement.price_hold_through",
    )
    assert at_equality["status"] == "DRAFT"
    assert at_equality["round_number"] == 0

    quote = read_quote(quote_id)
    assert_instant_equals(quote["expires_at"], "2026-09-15T00:00:00.000Z", "Quote.expires_at")
    assert quote["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Queue B: errors /
#          errors_triggerable_an_unknown_agreement_id_is_a_404_before_the_occ_token_is_read
# ---------------------------------------------------------------------------

def test_unknown_agreement_id_is_a_404_before_the_occ_token_is_read():
    """A commitment create carrying BOTH a stale `expected_project_version` and an unknown
    `escalation_agreement_id` answers ERR_AGREEMENT_NOT_FOUND, never the OCC failure.

    PRD §2.8: "an `escalation_agreement_id` that names no agreement is
    `ERR_AGREEMENT_NOT_FOUND`"
    PRD §2.9: "**Body foreign-key existence.** Every foreign key in the body resolves, per
    §2.8 (404)."
    PRD §2.9: "**Version pinning.** On `POST /procurement/purchase-commitments`,
    `expected_project_version` must equal the current `version` of the project owning the
    package — otherwise `ERR_STALE_PROJECT_VERSION` (412)."

    Design: Corner/errors/errors_triggerable_an_unknown_agreement_id_is_a_404_before_the_occ_token_is_read
    """
    project = open_project()
    steel_package = register_package(project["id"], scope_code="STRUCT-STEEL-01")
    misc_package = register_package(
        project["id"],
        scope_code="STRUCT-STEEL-02",
        description="Miscellaneous metals package",
        estimated_cost=900000.00,
        fabrication_duration_days=60,
        delivery_transit_days=29,
    )
    supplier = register_supplier()
    steel_quote = submit_quote(steel_package["id"], supplier["id"], base_price=1150000.00)
    misc_quote = submit_quote(misc_package["id"], supplier["id"], base_price=880000.00)

    stale_version = read_project_version(project["id"])
    assert stale_version == 1

    # A PO against the misc-metals package takes the project to version 2, so the captured
    # token above is now stale.
    issue_commitment(project["id"], misc_quote["id"], po_number="PO-2996-0002",
                     is_early_buyout=False)
    assert read_project_version(project["id"]) == 2

    validate_error(
        api_client.get_escalation_agreement(UNKNOWN_AGREEMENT_ID, BUYOUT_MANAGER),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
        404,
    )

    error = validate_error(
        api_client.create_purchase_commitment(
            create_purchase_commitment_payload(
                quote_id=steel_quote["id"],
                expected_project_version=stale_version,
                po_number="PO-2996-0001",
                escalation_agreement_id=UNKNOWN_AGREEMENT_ID,
                is_early_buyout=False,
            ),
            BUYOUT_MANAGER,
        ),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
        404,
    )
    assert error["error_id"] != ApiErrorId.ERR_STALE_PROJECT_VERSION.value

    assert read_project_version(project["id"]) == 2
    assert read_package(steel_package["id"])["status"] == "SOURCING"
    assert read_package(misc_package["id"])["status"] == "BOUGHT_OUT"
