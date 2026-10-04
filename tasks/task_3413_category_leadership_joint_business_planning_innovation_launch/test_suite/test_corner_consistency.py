"""Corner queue — consistency model: a mutation is visible immediately, in the
write's own response and in the read that follows it, with no lag.

Translates the corner-design `consistency_model` instance and cites the PRD
sentences that pin the asserted rule. The version assertion is delta-pinned
(the decision adds exactly 1): the PRD pins the increment, not the counter's
initial value.
"""
from test_helpers import (
    assert_plan,
    create_plan_decide_payload,
    setup_proposed_plan,
    validate_success,
)


def test_decide_response_and_immediate_read_agree(api, manufacturer_planner_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.1: "From `PROPOSED`, only the plan's own `RetailerBuyer` may decide: a `decision` of `ACCEPT` moves the plan `PROPOSED → ACCEPTED`, while `REJECT` moves it to the terminal `REJECTED`."
    PRD §3.1: "Every successful decision increments the plan's `version`, and a decide call by the wrong party fails with `ERR_NOT_YOUR_MOVE` just as a negotiation call would."
    PRD §2.5: "`updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource."
    PRD §4: "| GET | `/jbp/plans/{id}` | Read one plan, including its `version` | All six roles |"

    The decide ACCEPT response itself shows the updated plan (ACCEPTED, version
    bumped by exactly 1), and the immediately following GET returns the
    identical state and version — no lag.

    Design: Corner/consistency_model/mutation_visible_immediately_in_read
    """
    scenario = setup_proposed_plan()
    plan = scenario["plan"]

    decided = validate_success(
        api.decide_plan(
            plan["id"], create_plan_decide_payload("ACCEPT"), scenario["buyer_headers"]
        ),
        200,
    )
    assert_plan(decided)
    assert decided["id"] == plan["id"]
    assert decided["status"] == "ACCEPTED", (
        f"the decide response itself must show ACCEPTED, got {decided['status']}"
    )
    assert decided["version"] == plan["version"] + 1, (
        f"the decision must increment the version by exactly 1: "
        f"{plan['version']} -> {decided['version']}"
    )

    reread = validate_success(api.get_plan(plan["id"], manufacturer_planner_headers), 200)
    assert_plan(reread)
    assert reread["status"] == decided["status"], (
        f"the immediate read must agree: {reread['status']} != {decided['status']}"
    )
    assert reread["version"] == decided["version"], (
        f"the immediate read must show the same version: {reread['version']} != "
        f"{decided['version']}"
    )
    assert reread["updated_at"] >= reread["created_at"], (
        "updated_at is refreshed on modification and must not precede created_at"
    )
