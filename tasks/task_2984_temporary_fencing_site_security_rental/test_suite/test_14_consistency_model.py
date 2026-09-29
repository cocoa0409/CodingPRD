"""Nothing in this API lags: every derived figure is visible immediately.

Covers the immediate-consistency guarantee of PRD §1 and PRD §2.10 across the
five-hop install cascade of PRD §3.6 and the derived closure-corridor aggregate
of PRD §3.4.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_integer,
    assert_invoice_rollup,
)

CLOCK_AUG_10 = "2026-08-10T00:00:00Z"


def test_every_derived_value_is_visible_in_the_same_response_that_caused_it(api):
    """PRD §1: the system "enforces the relationships between them synchronously —
    every derived figure a request touches is recomputed inside that same request, so
    the response body a caller receives is already consistent with the change it just
    made", and PRD §2.10: "There is no deferred settlement, no background sweep and no
    eventual consistency." Repeating a read therefore yields the same data.

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_same_response_that_caused_it
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Foundry Road Phase Yard",
            "address_line": "402 Foundry Road",
            "site_condition": C.CONDITION_SOIL,
        },
    )
    account_id = world["account"]["id"]
    panel_id = world["panel"]["id"]
    municipality_id = world["municipality"]["id"]

    dock_street = FX.add_jobsite(
        world,
        api,
        site_label="Dock Street North",
        address_line="8 Dock Street",
        site_condition=C.CONDITION_ASPHALT,
        requires_sidewalk_closure=True,
    )
    permit = FX.seed_permit(api, dock_street["id"], closure_linear_feet=300)
    submitted = FX.submit_permit(api, permit["id"])
    assert submitted["status"] == C.PERMIT_SUBMITTED

    state = FX.seed_scheduled_install(
        api,
        world,
        linear_feet=500,
        dispatch_clock=C.CLOCK_AUG_01,
        scheduled_start="2026-08-03T08:00:00Z",
    )
    contract_id = state["contract"]["id"]
    scheduled_version = state["install"]["version"]

    completed = validate_success(
        api.complete_work_order(
            state["install"]["id"], F.complete_payload(500), U.DISPATCH_COORDINATOR
        )
    )

    # The write's own response already carries every field it just set.
    assert completed["status"] == C.WO_COMPLETED
    assert completed["completed_by_user_id"] == U.DISPATCH_COORDINATOR_ID
    assert_integer(completed["completed_linear_feet"], 500, "completed_linear_feet")
    assert_integer(completed["version"], scheduled_version + 1, "version")

    # The four rows the completion cascaded into are final on the first read after it.
    contract = FX.read_contract(api, contract_id)
    assert contract["lifecycle_status"] == C.LIFECYCLE_ACTIVE
    assert contract["billing_status"] == C.BILLING_CURRENT
    assert_instant(contract["billing_anchor_utc"], C.CLOCK_AUG_01, "billing_anchor_utc")
    assert_integer(contract["deployed_linear_feet"], 500, "deployed_linear_feet")

    product = FX.read_product(api, panel_id)
    assert_integer(product["deployed_count"], 50, "deployed_count")
    assert_integer(product["reserved_count"], 0, "reserved_count")
    assert_integer(product["available_count"], 350, "available_count")

    invoices = FX.invoices_for(api, contract_id)
    assert len(invoices) == 1, invoices
    assert invoices[0]["invoice_kind"] == C.KIND_MOBILIZATION
    assert invoices[0]["status"] == C.INVOICE_ISSUED
    assert_invoice_rollup(invoices[0], subtotal=78500, tax=6987, late_fee=0, total=85487)

    account = FX.read_account(api, account_id)
    assert_cents(account["open_balance_cents"], 85487, "open_balance_cents")

    FX.set_clock(api, CLOCK_AUG_10)
    decided = validate_success(
        api.decide_permit(
            permit["id"],
            F.decision_payload(C.DECISION_APPROVE, reviewer_note="closure cleared"),
            U.MUNICIPAL_LIAISON,
        )
    )
    assert decided["status"] == C.PERMIT_APPROVED
    assert_instant(decided["decided_at_utc"], CLOCK_AUG_10, "decided_at_utc")

    # The derived aggregate includes the application the instant the answer returned.
    first_read = FX.read_municipality(api, municipality_id)
    assert_integer(
        first_read["committed_closure_linear_feet"],
        300,
        "committed_closure_linear_feet",
    )

    second_read = FX.read_municipality(api, municipality_id)
    assert second_read == first_read, (first_read, second_read)
