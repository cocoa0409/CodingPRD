"""Cross-entity state dependencies: a deliverable submit requires its cycle to
be OPEN; a clean-room query requires its grant to be APPROVED."""

from test_helpers import (
    account_with_contract,
    create_cycle,
    create_deliverable,
    create_grant,
    create_ready_report,
    get_success_data,
    ingest_category_households,
    make_data_steward_headers,
    read_grant,
    set_clock,
    validate_error,
)
from test_helpers import ApiErrorId, factories
from test_helpers.test_users import TEST_USERS

SCIENTIST = TEST_USERS["insights_scientist_headers"]


def _deliverable_world(api):
    """READY report, cycle (open_at 2026-09-06), PLANNED deliverable due 2026-09-15."""
    world = account_with_contract(api, name="Lambda Lemons", scope_category="SNACKS", scope_brands=["ACME"])
    ingest_category_households(api, 20, "d")
    report = create_ready_report(api, world["contract"]["id"], world["analyst_headers"])
    cycle = create_cycle(api)
    deliverable = create_deliverable(api, cycle["id"], world["contract"]["id"], report["id"])
    return world, report, cycle, deliverable


def test_deliverable_submit_before_cycle_open_rejected(api):
    """At the default clock the cycle is still SCHEDULED, so the submit fails.

    PRD: "the cycle must be `OPEN` at submission time (the lazy auto-open applies first; a still-`SCHEDULED` cycle fails with `ERR_CYCLE_NOT_OPEN`)"
    Design: Difficulty/cross_entity_state_dependency/deliverable_submit_requires_cycle_open
    """
    _, _, _, deliverable = _deliverable_world(api)
    resp = api.submit_deliverable(deliverable["id"], SCIENTIST)
    validate_error(resp, ApiErrorId.CYCLE_NOT_OPEN.value, 409)


def test_deliverable_submit_succeeds_once_cycle_auto_opens(api):
    """Advancing the clock to open_at lets the cycle open and the submit land SUBMITTED, on time.

    PRD: "A `LineReviewCycle` in `SCHEDULED` moves to `OPEN` once the logical clock reaches its `open_at` instant (see §3.7)."
    PRD: "Submission moves the deliverable to `SUBMITTED` and evaluates timeliness: if the logical clock is later than `due_at`, the deliverable's `is_late` flag is set to true and the funding contract's `compliance_score` decreases by ten points"
    Design: Difficulty/cross_entity_state_dependency/deliverable_submit_requires_cycle_open
    """
    _, _, _, deliverable = _deliverable_world(api)
    validate_error(api.submit_deliverable(deliverable["id"], SCIENTIST), ApiErrorId.CYCLE_NOT_OPEN.value, 409)
    set_clock(api, "2026-09-06T00:00:00Z")
    submitted = get_success_data(api.submit_deliverable(deliverable["id"], SCIENTIST))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["is_late"] is False


def _requested_grant_world(api):
    """Contract plus a grant still in REQUESTED."""
    world = account_with_contract(api, name="Mu Melons")
    grant = create_grant(api, world["account"]["id"])
    return world, grant


def test_query_on_requested_grant_rejected(api):
    """A query against a grant that has not been approved cannot execute.

    PRD: "The grant must be `APPROVED` (else `ERR_GRANT_NOT_QUERYABLE`)"
    Design: Difficulty/cross_entity_state_dependency/query_requires_grant_approved
    """
    world, grant = _requested_grant_world(api)
    resp = api.submit_query(
        grant["id"],
        factories.query_payload(dataset_joins=["SALES"], estimated_rows=1000),
        world["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.GRANT_NOT_QUERYABLE.value, 409)


def test_query_after_approval_executes_and_debits_budget(api):
    """After approval the identical query executes at cost one, leaving 99 of 100 remaining.

    PRD: "The row volume is converted to row units by dividing `estimated_rows` by one thousand and rounding up to a whole unit."
    PRD: "if `result_rows` is at least twenty, the query lands in `EXECUTED`, the grant's `query_budget_consumed` increases by `query_cost`, and a `QUERY_EXECUTED` audit event is written."
    Design: Difficulty/cross_entity_state_dependency/query_requires_grant_approved
    """
    world, grant = _requested_grant_world(api)
    validate_error(
        api.submit_query(
            grant["id"],
            factories.query_payload(dataset_joins=["SALES"], estimated_rows=1000),
            world["analyst_headers"],
        ),
        ApiErrorId.GRANT_NOT_QUERYABLE.value,
        409,
    )
    get_success_data(api.approve_grant(grant["id"], make_data_steward_headers("steward-ce2")))
    query = get_success_data(api.submit_query(
        grant["id"],
        factories.query_payload(dataset_joins=["SALES"], estimated_rows=1000),
        world["analyst_headers"],
    ))
    assert query["status"] == "EXECUTED"
    assert query["query_cost"] == 1
    observed = read_grant(api, grant["id"])
    assert observed["query_budget_remaining"] == 99
