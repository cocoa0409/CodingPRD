"""Who may act, who may not, and which of the two answers a refusal carries.

PRD 2.1 runs three independent gates in a fixed order - authentication, then the
endpoint's role list, then the ownership walk that only the entity-backed
GroupContact role can fail - and PRD 4 is the authority on which roles each
endpoint lists.
"""

from test_helpers import (
    ACCOUNTING_CLERK,
    CONTRACT_ADMIN,
    NO_AUTH_HEADERS,
    RESERVATIONS_AGENT,
    REVENUE_MANAGER,
    SALES_MANAGER,
    UNDECLARED_ROLE_HEADERS,
    ApiErrorId,
    BlockBillingStatus,
    BlockInventoryStatus,
    ContractStatus,
    LeadStatus,
    QuoteStatus,
    assert_group_account,
    assert_group_contract,
    assert_lead,
    assert_rate_quote,
    assert_room_block,
    factories as F,
    make_group_contact_headers,
    master_block_of,
    read_lead,
    reset_clock,
    seed_accepted_quote,
    seed_account,
    seed_proposed_quote,
    seed_signed_contract,
    validate_error,
    validate_success,
)


def test_an_exclusive_operation_refuses_every_chair_but_its_own(api):
    """Three single-role endpoints probed from the wrong chair, then the right one.

    PRD 4 gives each of these operations exactly one authorized role - inventory
    seeding to RevenueManager, lead capture to SalesManager, and papering an
    accepted quote to ContractAdmin - and PRD 2.1 matches the header against that
    list once authentication has passed, rejecting an unlisted role with
    ERR_UNAUTHORIZED. PRD 2.8 puts that gate at priority 2, above both existence
    at priority 5 and body validation at priority 3, so a perfectly valid payload
    from the wrong role is still a 403 and never a 400 or a 404. The two controls
    are what prove the refusals are about the chair and not about the request:
    the identical inventory day and the identical contract body succeed a moment
    later under their declared roles.

    Design: Corner/rbac/a_role_outside_the_endpoint_list_is_refused_while_the_listed_roles_pass
    """
    world = seed_accepted_quote(api)
    december = F.inventory_day_payload(
        "2026-12-01", transient_demand_rooms=300, historical_pickup_rooms=290
    )

    validate_error(
        api.create_inventory_day(december, RESERVATIONS_AGENT),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_lead(
            F.lead_payload(world["account_id"], program_name="Wrong Chair"),
            ACCOUNTING_CLERK,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_contract(F.contract_payload(world["quote_id"]), SALES_MANAGER),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    validate_success(api.create_inventory_day(december, REVENUE_MANAGER), 201)
    assert_group_contract(
        validate_success(
            api.create_contract(F.contract_payload(world["quote_id"]), CONTRACT_ADMIN),
            201,
        ),
        status=ContractStatus.DRAFT,
    )


def test_no_badge_and_an_invented_badge_are_both_unauthenticated(api):
    """Priority 1 separates having no credentials from having unknown ones.

    PRD 2.1 requires both headers on "every request to the service - without
    exception, including read-only requests" and rejects with ERR_UNAUTHENTICATED
    when "either header is absent, blank, or if X-User-Role names anything outside
    the seven roles enumerated below". GeneralManager is not one of the seven, so
    it is a 401 and not the 403 that a declared-but-unlisted role earns - an
    implementation that resolves an unknown role to a default, or that answers 403
    for a missing header, confuses the two gates. PRD 2.8 also puts this check
    "before request-schema parsing", so the body is never even read.

    Design: Corner/rbac/an_absent_or_unknown_role_header_is_unauthenticated_not_unauthorized
    """
    reset_clock(api)

    validate_error(
        api.create_account(F.account_payload(name="Anonymous Co"), NO_AUTH_HEADERS),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.create_account(
            F.account_payload(name="Invented Role Co"), UNDECLARED_ROLE_HEADERS
        ),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.list_inventory_days(UNDECLARED_ROLE_HEADERS),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )


def test_a_client_contact_may_only_reach_the_rows_of_its_own_organization(api):
    """A real but foreign account id is a 403, and the owner's identical call works.

    PRD 2.1 makes GroupContact "the one exception and it is entity-backed": its
    X-User-ID is a GroupAccount id, and ownership checks "resolve that resource
    back to its owning account and compare the result to X-User-ID", a rate quote
    resolving "through its lead_id to that lead's account_id". A mismatch is
    "rejected with ERR_UNAUTHORIZED (HTTP 403) - not with a 404", which is exactly
    what the decoy organization tests, since it is a real row and its id resolves
    perfectly well. PRD 2.8 applies the same gate to "every read a GroupContact
    performs". The owning contact's acceptance then runs the whole cascade of PRD
    3.4 and carries the lead to WON, proving the walk is per-row rather than a
    blanket ban on the role.

    Design: Corner/rbac/a_group_contact_may_only_touch_its_own_accounts_rows
    """
    world = seed_proposed_quote(api)
    decoy = seed_account(api, name="Decoy Logistics")
    impostor = make_group_contact_headers(decoy["id"])

    validate_error(
        api.accept_rate_quote(world["quote_id"], impostor),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.counter_rate_quote(
            world["quote_id"],
            F.counter_payload(countered_base_rate_cents=22000),
            impostor,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.get_rate_quote(world["quote_id"], impostor),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    assert_rate_quote(
        validate_success(
            api.accept_rate_quote(world["quote_id"], world["group_contact"])
        ),
        status=QuoteStatus.ACCEPTED,
    )
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.WON)


def test_a_shared_operation_is_open_to_the_second_role_on_its_list_too(api):
    """Account creation from either declared chair, and one block read from four.

    PRD 4 lists account registration for both SalesManager and RevenueManager, and
    the single-block read for six roles, so testing anything other than the first
    name on each list is what catches an implementation that hard-codes it. The
    master block minted by the countersignature cascade of PRD 3.5 carries "name
    set to MASTER, is_master true, inventory_status SETUP and billing_status
    UNBILLED", and every one of these callers must see the same row: the owning
    GroupContact reaches it by the ownership walk of PRD 2.1, which resolves a
    block "through its contract_id and then along the same contract chain".

    Design: Corner/rbac/shared_operations_are_open_to_every_declared_role
    """
    world = seed_signed_contract(api)
    master_id = master_block_of(api, world["contract_id"])["id"]

    for actor, name in (
        (SALES_MANAGER, "Created By Sales"),
        (REVENUE_MANAGER, "Created By Revenue"),
    ):
        assert_group_account(
            validate_success(
                api.create_account(F.account_payload(name=name), actor), 201
            ),
            name=name,
            version=1,
        )

    assert_room_block(
        validate_success(api.get_room_block(master_id, RESERVATIONS_AGENT)),
        inventory_status=BlockInventoryStatus.SETUP,
    )
    assert_room_block(
        validate_success(api.get_room_block(master_id, ACCOUNTING_CLERK)),
        billing_status=BlockBillingStatus.UNBILLED,
    )
    assert_room_block(
        validate_success(api.get_room_block(master_id, world["group_contact"])),
        name="MASTER",
        is_master=True,
    )
