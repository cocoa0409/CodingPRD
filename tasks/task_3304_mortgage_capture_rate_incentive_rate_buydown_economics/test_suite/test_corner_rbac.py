"""Corner coverage - the segregation-of-duties boundaries between roles."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import ANONYMOUS_HEADERS, BANKER_HEADERS, COMPLIANCE_HEADERS, SALES_HEADERS
from test_helpers import make_buyer_headers


def test_the_buyer_operation_set_does_not_include_writing_a_contract(api):
    """The same body sent by a buyer is refused; contract creation belongs to sales.

    PRD §2.1: "The seventh role is entity-backed. When `X-User-Role` is `Buyer`,
    `X-User-ID` is the `id` of the acting `Buyer`; ownership checks on any resource that
    references a `Buyer` compare the resource's `buyer_id` field to `X-User-ID`."
    PRD §2.1: "A request whose role is valid but is not listed among the roles authorized
    for the target operation is rejected with `ERR_FORBIDDEN` and an HTTP 403."
    Design: Corner/rbac/buyer_cannot_create_a_contract
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    world.update({"hs1": site["id"]})

    refused = api.create_contract(
        world["hs1"], f.contract_payload(world["b1"]), make_buyer_headers(world["b1"])
    )
    validate_error(refused, "ERR_FORBIDDEN", 403)


def test_the_refused_buyer_write_leaves_the_home_available(api):
    """No contract row appears and the inventory home is still on the market.

    PRD §3.4: "Creation is refused with `ERR_HOME_SITE_NOT_AVAILABLE` at HTTP 409 if the
    home site is not available, and with `ERR_COMMUNITY_SUSPENDED` at HTTP 403 if the
    community is suspended."
    PRD §3.2: "A home site begins in `home_site_status` `AVAILABLE`."
    Design: Corner/rbac/buyer_cannot_create_a_contract
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    world.update({"hs1": site["id"]})
    api.create_contract(
        world["hs1"], f.contract_payload(world["b1"]), make_buyer_headers(world["b1"])
    )

    contracts, _ = fixtures.rows(
        api.list_home_site_contracts(world["hs1"], world["sales_headers"])
    )
    assert contracts == [], f"the refused write created nothing, got {contracts}"

    reread = fixtures.read_home_site(api, world["hs1"])
    assert reread["home_site_status"] == "AVAILABLE", reread["home_site_status"]


def test_approval_is_reserved_to_the_compliance_officer(api):
    """The banker who built the deal cannot approve it under segregation of duties.

    PRD §3.4: "Approval by a `ComplianceOfficer` moves the contract from `LOCKED` to
    `APPROVED` and is a compliance gate rather than a pricing gate."
    PRD §2.1: "A request whose role is valid but is not listed among the roles authorized
    for the target operation is rejected with `ERR_FORBIDDEN` and an HTTP 403."
    Design: Corner/rbac/mortgage_banker_cannot_approve_a_contract
    """
    world = fixtures.setup_contract_with_aba(api, target_state="LOCKED")

    refused = api.approve_contract(world["ct1"], BANKER_HEADERS)
    validate_error(refused, "ERR_FORBIDDEN", 403)

    contract = fixtures.read_contract(api, world["ct1"])
    assert contract["contract_status"] == "LOCKED", (
        f"the refused approval left the deal where it was, got {contract['contract_status']}"
    )


def test_the_compliance_officer_is_the_role_that_can_approve_the_same_deal(api):
    """The identical call succeeds for the officer holding the operation exclusively.

    PRD §3.4: "Approval applies every allocation that is still `RESERVED` by moving it to
    `APPLIED`".
    PRD §2.1: "A request whose role is valid but is not listed among the roles authorized
    for the target operation is rejected with `ERR_FORBIDDEN`".
    Design: Corner/rbac/mortgage_banker_cannot_approve_a_contract
    """
    world = fixtures.setup_contract_with_aba(api, target_state="LOCKED")
    api.approve_contract(world["ct1"], BANKER_HEADERS)

    approved = get_success_data(api.approve_contract(world["ct1"], COMPLIANCE_HEADERS))
    assert approved["contract_status"] == "APPROVED", approved["contract_status"]


def test_the_anonymous_caller_cannot_read_a_sale_contract(api):
    """Anonymous holds only the community catalogue operations, so the read is refused.

    PRD §2.1: "The `Anonymous` role is the unauthenticated caller and may read the public
    community catalogue only."
    PRD §2.1: "A request whose role is valid but is not listed among the roles authorized
    for the target operation is rejected with `ERR_FORBIDDEN` and an HTTP 403."
    Design: Corner/rbac/anonymous_cannot_read_a_contract
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"]})

    # Anonymous is a declared role in the matrix, so the rejection is an authorization
    # failure rather than an authentication one.
    refused = api.get_contract(world["ct1"], ANONYMOUS_HEADERS)
    validate_error(refused, "ERR_FORBIDDEN", 403)


def test_the_denial_is_operation_specific_not_role_wide(api):
    """The same anonymous caller still reads the public community catalogue.

    PRD §2.3: "A list of the public community catalogue is readable by any caller
    including `Anonymous`".
    PRD §2.1: "The `Anonymous` role is the unauthenticated caller and may read the public
    community catalogue only."
    Design: Corner/rbac/anonymous_cannot_read_a_contract
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"]})

    api.get_contract(world["ct1"], ANONYMOUS_HEADERS)
    catalogue, meta = validate_paginated(api.list_communities(ANONYMOUS_HEADERS))
    assert meta["total_count"] == 1, (
        f"the public catalogue remains open to the unauthenticated caller, "
        f"got {meta['total_count']}"
    )
    assert len(catalogue) == 1, catalogue