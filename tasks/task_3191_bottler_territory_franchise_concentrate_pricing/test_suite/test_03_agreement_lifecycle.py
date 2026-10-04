"""Bottler agreement lifecycle: activation gates, cycles, termination."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_error,
    validate_success,
    get_success_data,
    set_clock_default,
    create_brand_owner,
    create_territory,
    create_draft_agreement,
    create_product_line,
    create_price_index,
    activate_agreement,
    seed_active_agreement,
    create_cpo,
    ops_headers,
)

PA = TEST_USERS["platform_admin_headers"]
BOA = TEST_USERS["brand_owner_admin_headers"]


def test_agreement_activate_twice_rejected(api):
    """PRD §3.1: "A `PlatformAdmin` activates a `DRAFT` agreement; the
    activation is rejected with `ERR_AGREEMENT_ALREADY_ACTIVE` if the agreement
    is in any state other than `DRAFT`."

    Design: Corner/state_machines/agreement_activate_twice_rejected
    """
    env = seed_active_agreement()
    ag_id = env["agreement"]["id"]
    assert env["agreement"]["version"] == 2  # created at 1, activation bumps to 2
    r = api_client.activate_agreement(ag_id, PA)
    validate_error(r, ApiErrorId.ERR_AGREEMENT_ALREADY_ACTIVE.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_agreement(ag_id, PA))
    assert after["version"] == 2, "rejected activate must not advance version"
    assert after["status"] == "ACTIVE"


def test_second_active_agreement_in_territory_rejected(api):
    """PRD §2.9: "A territory may host at most one franchise agreement in
    `ACTIVE` status at any moment. Activating a draft agreement while another
    agreement for the same territory is already `ACTIVE` is rejected with
    `ERR_TERRITORY_HAS_ACTIVE_AGREEMENT` (HTTP 409)."

    Design: Corner/state_machines/second_active_agreement_in_territory_rejected
    """
    env = seed_active_agreement()
    ter_id = env["territory"]["id"]
    ag2 = create_draft_agreement(
        ter_id,
        bottler_name="Rival Bottling",
        marketing_accrual_basis="NET_REVENUE",
        service_budget_cents=500000,
    )
    r = api_client.activate_agreement(ag2["id"], PA)
    validate_error(r, ApiErrorId.ERR_TERRITORY_HAS_ACTIVE_AGREEMENT.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_agreement(ag2["id"], PA))
    assert after["status"] == "DRAFT"


def test_activate_without_index_fails_line_obligation(api):
    """PRD §3.1: "Activation enforces the line obligation check: for every
    `ACTIVE` product line of the territory's brand owner whose `is_mandatory`
    is true, at least one concentrate price index must already exist for that
    brand — otherwise the activation fails with `ERR_LINE_OBLIGATION_UNMET`
    (HTTP 422), on the reasoning that a mandatory line cannot be priced without
    an index."

    Design: Corner/state_machines/activate_without_index_fails_line_obligation
    """
    set_clock_default()
    bo = create_brand_owner()
    create_product_line(bo["id"], is_mandatory=True)  # mandatory line, no index rows
    ter = create_territory(bo["id"])
    ag = create_draft_agreement(ter["id"])
    r = api_client.activate_agreement(ag["id"], PA)
    validate_error(r, ApiErrorId.ERR_LINE_OBLIGATION_UNMET.value)
    assert r.status_code == 422
    after = get_success_data(api_client.get_agreement(ag["id"], PA))
    assert after["status"] == "DRAFT"


def test_terminate_with_open_cpo_rejected(api):
    """PRD §3.1: "**Termination** moves an `ACTIVE` agreement to `TERMINATED`,
    but only while the agreement has no concentrate purchase order still in
    `PLACED` fulfillment; termination returns the territory to `OPEN`."
    PRD §2.7: "(4) state checks confirming the target entity is in a state from
    which the requested transition is defined (this priority level covers
    `ERR_INVALID_STATE`, ...)".

    Design: Corner/state_machines/terminate_with_open_cpo_rejected
    """
    env = seed_active_agreement()
    ag_id = env["agreement"]["id"]
    create_cpo(env)  # PLACED CPO
    r = api_client.terminate_agreement(ag_id, BOA)
    validate_error(r, ApiErrorId.ERR_INVALID_STATE.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_agreement(ag_id, PA))
    assert after["status"] == "ACTIVE"


def test_terminated_agreement_suspend_rejected_terminal(api):
    """PRD §2.7: "Any action attempted on an entity already in a terminal state
    is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) where no more specific
    state error applies."
    PRD §3.1: "Both `TERMINATED` and `REFRANCHISED` are terminal states for an
    agreement."

    Design: Corner/state_machines/terminated_agreement_suspend_rejected_terminal
    """
    env = seed_active_agreement()
    ag_id = env["agreement"]["id"]
    ter_id = env["territory"]["id"]
    r = api_client.terminate_agreement(ag_id, BOA)
    assert r.status_code == 200
    r = api_client.suspend_agreement(ag_id, BOA)
    validate_error(r, ApiErrorId.ERR_ALREADY_TERMINAL.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_agreement(ag_id, PA))
    assert after["status"] == "TERMINATED"
    ter = get_success_data(api_client.get_territory(ter_id, PA))
    assert ter["status"] == "OPEN"
