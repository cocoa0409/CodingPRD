"""State gates that cross from one entity into a child collection or a sibling."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    ANALYST,
    CUSTOMER_SERVICE,
    OPERATOR,
    create_customer,
    create_ppa,
    get_ppa,
    get_site,
    issue_allowance,
    set_clock,
    setup_active_ppa,
    setup_draft_ppa,
    setup_terminated_ppa,
)


def test_a_site_with_no_live_contract_has_nothing_to_suspend():
    """PRD §2.5: "A facility may be suspended only while its posture is currently `SITE_ACTIVE` and only while
    at least one of its contracts is in `PPA_ACTIVE` — a site with no live contract has nothing
    to suspend."

    Design: Difficulty/cross_entity_state_dependency/freeze_rejected_when_site_has_no_active_ppa
    """
    set_clock()
    site = validate_success_site()
    assert site["status"] == "SITE_ACTIVE"
    assert site["active_ppa_count"] == 0

    response = api_client.freeze_site(site["id"], OPERATOR, "CUSTOMER_REQUEST")

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    after = get_site(site["id"])
    assert after["status"] == "SITE_ACTIVE", "the posture must be untouched"
    assert after["active_ppa_count"] == 0


def test_a_site_holding_only_a_drafted_contract_is_still_refused_a_freeze():
    """PRD §3.2: "A freshly drafted contract sits in `PPA_DRAFT`".

    Design: Difficulty/cross_entity_state_dependency/freeze_rejected_when_site_has_no_active_ppa
    """
    ctx = setup_draft_ppa()
    assert ctx["ppa"]["state"] == "PPA_DRAFT"
    assert get_site(ctx["site_id"])["active_ppa_count"] == 0

    response = api_client.freeze_site(ctx["site_id"], OPERATOR, "CUSTOMER_REQUEST")

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_site(ctx["site_id"])["status"] == "SITE_ACTIVE"


def test_renewing_a_terminated_contract_is_refused_while_the_offer_is_unaccepted():
    """PRD §3.8: "declining moves `RENEWAL_OFFERED` to `RENEWAL_DECLINED`".
    PRD §3.8: "A `SiteOperator` then renews a terminated contract, which requires the customer to be
    `CUSTOMER_ACTIVE`, the customer's `renewal_stage` to be `RENEWAL_ACCEPTED` and the site to be
    `SITE_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/renew_rejected_while_renewal_stage_is_offered_not_accepted
    """
    ctx = setup_terminated_ppa()
    assert ctx["ppa"]["state"] == "PPA_TERMINATED"
    assert ctx["customer"]["renewal_stage"] == "RENEWAL_OFFERED"

    response = api_client.renew_ppa(ctx["ppa_id"], OPERATOR)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_ppa(ctx["ppa_id"])["state"] == "PPA_TERMINATED"


def test_the_same_renewal_is_admitted_once_the_customer_accepts_the_offer():
    """PRD §3.8: "acceptance moves `RENEWAL_OFFERED` to `RENEWAL_ACCEPTED`".

    Design: Difficulty/cross_entity_state_dependency/renew_rejected_while_renewal_stage_is_offered_not_accepted
    """
    ctx = setup_terminated_ppa()
    validate_success(api_client.accept_renewal(ctx["customer_id"], CUSTOMER_SERVICE))

    renewed = validate_success(api_client.renew_ppa(ctx["ppa_id"], OPERATOR))

    assert renewed["state"] == "PPA_ACTIVE", (
        f"the renewal is the only way back out of the terminal state; got {renewed['state']}"
    )
    assert renewed["state_entered_at"] is not None


def test_a_contract_cannot_be_renewed_from_the_offered_stage_twice_over():
    """PRD §3.8: "An
    accept or decline requested while the customer's `renewal_stage` is not `RENEWAL_OFFERED` is
    refused with `ERR_RENEWAL_STAGE_INVALID` (HTTP 409) — the review dimension admits no shortcuts
    past the offer."

    Design: Difficulty/cross_entity_state_dependency/renew_rejected_while_renewal_stage_is_offered_not_accepted
    """
    ctx = setup_terminated_ppa()
    validate_success(api_client.accept_renewal(ctx["customer_id"], CUSTOMER_SERVICE))

    response = api_client.accept_renewal(ctx["customer_id"], CUSTOMER_SERVICE)

    validate_error(response, ApiErrorId.ERR_RENEWAL_STAGE_INVALID)


def test_a_contract_that_has_never_transferred_carries_the_as_built_basis():
    """PRD §3.8: "A contract that has never been transferred carries the
    `contract_basis` value `PPA_BASIS_AS_BUILT`, which is also the value its `contract_basis`
    takes by default when it is drafted".

    Design: Difficulty/cross_entity_state_dependency/transfer_rejected_on_a_suspended_site
    """
    ctx = setup_active_ppa()
    assert ctx["ppa"]["contract_basis"] == "PPA_BASIS_AS_BUILT"
    assert ctx["ppa"]["transfer_stage"] == "TRANSFER_NONE", (
        "transfer_stage moves independently of state and starts unblocked"
    )


def test_issuing_an_allowance_against_a_contract_with_nothing_to_credit_is_refused():
    """PRD §3.6: "at least one accrual at that contract must be sitting in
    `ACCRUAL_OPEN`, and a contract whose ledger is fully reconciled refuses the issuance with
    `ERR_NO_ELIGIBLE_ACCRUAL` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/allowance_issue_rejected_on_a_draft_contract
    """
    ctx = setup_draft_ppa()
    ppa = get_ppa(ctx["ppa_id"])

    response = api_client.issue_allowance(
        ctx["ppa_id"],
        ANALYST,
        {
            "allowance_kind": "CAPACITY_ALLOWANCE",
            "amount_cents": 185000,
            "expected_ppa_version": ppa["version"],
        },
    )

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_ACCRUAL)
    rows = validate_success(api_client.list_allowances(ctx["ppa_id"], ANALYST))
    data = rows["data"] if isinstance(rows, dict) and "data" in rows else rows
    assert data == [], "no ALLOWANCE_ISSUED row may exist to apply"
    assert get_ppa(ctx["ppa_id"])["state"] == "PPA_DRAFT"


def test_an_allowance_is_issued_once_the_contract_has_an_open_accrual():
    """PRD §3.6: "An issued allowance sits in `ALLOWANCE_ISSUED` with its
    `applied_direction` null, and it has no effect on any balance until it is applied."

    Design: Difficulty/cross_entity_state_dependency/allowance_issue_rejected_on_a_draft_contract
    """
    ctx = setup_active_ppa()
    from test_helpers.fixtures import post_accrual

    post_accrual(ctx["ppa_id"], ctx["site_id"], amount_cents=100000)

    allowance = issue_allowance(ctx["ppa_id"], amount_cents=185000)

    assert allowance["lifecycle_state"] == "ALLOWANCE_ISSUED"
    assert allowance["applied_direction"] is None


# --- small local helper ------------------------------------------------------
def validate_success_site():
    from test_helpers import api_client as client
    from test_helpers.fixtures import create_site

    return create_site()