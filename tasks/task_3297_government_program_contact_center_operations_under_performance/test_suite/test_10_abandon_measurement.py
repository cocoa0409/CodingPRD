"""ABANDON measurement input-set filtering."""
from test_helpers import TEST_USERS, api_client, validate_success
from test_helpers.fixtures import (
    abandon_call,
    answer_call,
    complete_call,
    create_invoice,
    list_cure_periods,
    list_invoice_lines,
    prepare_invoice,
    register_call,
    route_call,
    setup_routable,
)


def test_abandon_rate_excludes_unresolved_calls():
    """PRD §3.9: "For `ABANDON`, the input set is all calls of the contract
    and program enqueued in the window whose status is `ANSWERED`,
    `COMPLETED`, or `ABANDONED` — `WAITING` and `ASSIGNED` calls are excluded
    because they have not resolved — and the rate is the count of `ABANDONED`
    calls divided by the size of the input set, rounded half-up to 4 decimal
    places; an empty set yields 0.0000."
    PRD §2.7: "Abandonment is a fraction carried to exactly 4 decimal places,
    round-half-up."

    Design: Corner/calculations/abandon_rate_excludes_unresolved_calls
    """
    ctx = setup_routable(metric="ABANDON", target=0.05, remedy_fee_cents=800)
    contract_id = ctx["contract"]["id"]
    agent_id = ctx["agent"]["id"]

    c1 = register_call(contract_id, enqueued_at="2026-09-05T09:00:00Z")
    c2 = register_call(contract_id, enqueued_at="2026-09-05T09:01:00Z")
    c3 = register_call(contract_id, enqueued_at="2026-09-05T09:02:00Z")
    c4 = register_call(contract_id, enqueued_at="2026-09-05T09:03:00Z")

    c1 = route_call(c1["id"])
    c1 = answer_call(c1, agent_id)
    complete_call(c1, agent_id)

    c2 = route_call(c2["id"])
    c2 = answer_call(c2, agent_id)
    complete_call(c2, agent_id)

    abandon_call(c3["id"])
    # c4 stays WAITING and must not enter the input set.

    invoice = create_invoice(contract_id)
    prepare_invoice(invoice["id"])
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] == 0.3333, "1/3, 4dp round_half_up"
    assert line["measured_value"] != 0.25
    assert line["compliant"] is False
    cures = list_cure_periods(line["id"])
    assert len(cures) == 1
    assert cures[0]["status"] == "PENDING"
