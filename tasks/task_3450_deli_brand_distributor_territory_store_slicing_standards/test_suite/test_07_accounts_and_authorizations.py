"""Account proposals, channel policy, and product authorizations (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    approve_account,
    create_account_payload,
    create_authorization,
    create_distributor,
    create_product,
    create_service_visit_payload,
    get_success_data,
    make_distributor_rep_headers,
    propose_account,
    review_account,
    setup_active_distributor,
    setup_approved_account,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["brand_admin_headers"]


def test_under_review_account_rejects_service_visit(api):
    """PRD §2.9: "Creating a service visit or a delivery against an account — or
    drafting a promo program for one — requires the account's `approval_status` to
    be `APPROVED`, else `ERR_ACCOUNT_NOT_APPROVED`."

    Visit scheduling depends on the account's approval state: while the proposal is
    still UNDER_REVIEW the visit is rejected.

    Design: Difficulty/cross_entity_state_dependency/service_visit_requires_account_approved
    """
    net = setup_active_distributor()
    account = propose_account(net["distributor"], net["territory"])
    assert account["approval_status"] == "UNDER_REVIEW"
    resp = api.create_service_visit(
        create_service_visit_payload(
            account["id"],
            window_start="2026-09-02T09:00:00Z", window_end="2026-09-02T10:00:00Z"),
        make_distributor_rep_headers(net["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_APPROVED)


def test_approved_account_accepts_service_visit(api):
    """PRD §2.9: "Creating a service visit or a delivery against an account — or
    drafting a promo program for one — requires the account's `approval_status` to
    be `APPROVED`, else `ERR_ACCOUNT_NOT_APPROVED`." and PRD §3.6: "The visit's
    `status` begins `SCHEDULED`".

    Once the account is approved the identical visit is scheduled.

    Design: Difficulty/cross_entity_state_dependency/service_visit_requires_account_approved
    """
    net = setup_active_distributor()
    account = propose_account(net["distributor"], net["territory"])
    approve_account(account["id"])
    resp = api.create_service_visit(
        create_service_visit_payload(
            account["id"],
            window_start="2026-09-02T09:00:00Z", window_end="2026-09-02T10:00:00Z"),
        make_distributor_rep_headers(net["distributor"]["id"]),
    )
    visit = validate_success(resp, expected_status=201)
    assert visit["status"] == "SCHEDULED"


def test_review_of_unknown_account_is_not_found(api):
    """PRD §2.10: "The server resolves every referenced identifier — the path's `id`
    first, then body identifiers — in left-to-right order, and rejects the request
    with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond
    to an existing resource, without evaluating any later identifier or any business
    rule."

    A well-formed but unknown account id in the review path resolves to 404.

    Design: Corner/entities/account_review_unknown_id_returns_not_found
    """
    resp = api.review_account(NON_EXISTENT_UUID, "APPROVE", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_proposal_with_unknown_territory_is_not_found(api):
    """PRD §2.10: "The server resolves every referenced identifier — the path's `id`
    first, then body identifiers — in left-to-right order, and rejects the request
    with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond
    to an existing resource, without evaluating any later identifier or any business
    rule."

    A body foreign key that does not resolve yields 404, not a business error.

    Design: Corner/entities/account_create_with_unknown_territory_returns_not_found
    """
    net = setup_active_distributor()
    resp = api.create_account(
        create_account_payload(NON_EXISTENT_UUID, name="Store X"),
        make_distributor_rep_headers(net["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_approval_authorizes_requested_catalog(api):
    """PRD §3.2: "Approval stamps `approved_at` with the current time and immediately
    authorizes the account's pending catalog: every product authorization of the
    account still in `REQUESTED` moves to `AUTHORIZED`." and "when the account is
    already `APPROVED` the authorization is born `AUTHORIZED`, and otherwise it
    begins as `REQUESTED` and waits for the account's approval."

    The authorization created while the account is UNDER_REVIEW is REQUESTED; the
    approval bubbles it up to AUTHORIZED.

    Design: Corner/state_machines/account_approval_bubbles_requested_authorizations
    """
    net = setup_active_distributor()
    product = create_product(code="P1", name="Item")
    account = propose_account(net["distributor"], net["territory"])
    authorization = create_authorization(account["id"], product["id"])
    assert authorization["status"] == "REQUESTED", (
        "born REQUESTED while the account is UNDER_REVIEW"
    )
    approve_account(account["id"])
    authorization = get_success_data(
        api.get_authorization(authorization["id"], ADMIN))
    assert authorization["status"] == "AUTHORIZED"


def test_revoked_authorization_rejects_further_revoke(api):
    """PRD §3.2: "Finally, an authorization in `AUTHORIZED` or `SUSPENDED` can be
    revoked outright, either by a `BrandAdmin` or by the confirmed-incident cascade
    of §3.8, moving it to the terminal `REVOKED`." and PRD §2.8: "an entity already
    in a terminal state (`TERMINATED`, `REJECTED`, `CLOSED`, `SETTLED`, `RECALLED`,
    `EXHAUSTED`, `CONFIRMED`, `DELIVERED`, `PULLED_ON_TIME`, `PULLED_LATE`,
    `FORCE_PULLED`, `DECOMMISSIONED`, `EXPIRED`, `REVOKED`) rejects every further
    transition with `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/revoked_authorization_rejects_further_transitions
    """
    ctx = setup_approved_account()
    product = create_product(code="P1", name="Item")
    authorization = create_authorization(ctx["account"]["id"], product["id"])
    assert authorization["status"] == "AUTHORIZED"
    revoked = validate_success(api.revoke_authorization(authorization["id"], ADMIN))
    assert revoked["status"] == "REVOKED"
    resp = api.revoke_authorization(authorization["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_rejected_account_is_terminal(api):
    """PRD §3.2: "A `decision` of `REJECT` moves the account `UNDER_REVIEW` →
    `REJECTED`, which is terminal." and PRD §2.8: "an entity already in a terminal
    state (`TERMINATED`, `REJECTED`, `CLOSED`, `SETTLED`, `RECALLED`, `EXHAUSTED`,
    `CONFIRMED`, `DELIVERED`, `PULLED_ON_TIME`, `PULLED_LATE`, `FORCE_PULLED`,
    `DECOMMISSIONED`, `EXPIRED`, `REVOKED`) rejects every further transition with
    `ERR_ALREADY_TERMINAL`."

    A REJECTED account cannot be re-reviewed or approved.

    Design: Corner/state_machines/rejected_account_is_terminal
    """
    net = setup_active_distributor()
    account = propose_account(net["distributor"], net["territory"])
    review_account(account["id"], "REJECT")
    resp = api.review_account(account["id"], "APPROVE", ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_reinstate_restores_account_suspend_authorizations(api):
    """PRD §3.2: "Reinstatement moves `SUSPENDED` → `APPROVED` and restores exactly
    those authorizations that were suspended by the account cascade — those with
    `suspension_source` of `ACCOUNT_SUSPEND` return to `AUTHORIZED` with
    `suspension_source` reset to `NONE`, while authorizations suspended by an
    incident (source `INCIDENT`) remain suspended."

    The reinstatement compensates the suspension cascade exactly.

    Design: Corner/state_machines/account_reinstate_restores_only_account_suspend_auths
    """
    ctx = setup_approved_account()
    product = create_product(code="P1", name="Item")
    authorization = create_authorization(ctx["account"]["id"], product["id"])
    validate_success(api.suspend_account(ctx["account"]["id"], ADMIN))
    mid = get_success_data(api.get_authorization(authorization["id"], ADMIN))
    assert mid["status"] == "SUSPENDED"
    assert mid["suspension_source"] == "ACCOUNT_SUSPEND"

    account = validate_success(api.reinstate_account(ctx["account"]["id"], ADMIN))
    assert account["approval_status"] == "APPROVED"
    restored = get_success_data(api.get_authorization(authorization["id"], ADMIN))
    assert restored["status"] == "AUTHORIZED"
    assert restored["suspension_source"] == "NONE"


def test_mass_channels_refused_at_review(api):
    """PRD §3.2: "the brand refuses supply to the mass channels, so an account whose
    `channel` is `MASS_MERCHANT` or `CLUB_STORE` can never be approved and is
    rejected with `ERR_CHANNEL_REFUSED`".

    Both refused channels fail APPROVE while the accounts remain UNDER_REVIEW.

    Design: Corner/validations/mass_channels_refused_at_review
    """
    net = setup_active_distributor()
    mass = propose_account(net["distributor"], net["territory"],
                           name="Big Box", channel="MASS_MERCHANT")
    club = propose_account(net["distributor"], net["territory"],
                           name="Club Co", channel="CLUB_STORE")
    resp = api.review_account(mass["id"], "APPROVE", ADMIN)
    validate_error(resp, ApiErrorId.ERR_CHANNEL_REFUSED)
    resp = api.review_account(club["id"], "APPROVE", ADMIN)
    validate_error(resp, ApiErrorId.ERR_CHANNEL_REFUSED)
    for account in (mass, club):
        current = get_success_data(api.get_account(account["id"], ADMIN))
        assert current["approval_status"] == "UNDER_REVIEW", (
            "a refused approval leaves the account UNDER_REVIEW"
        )


def test_channel_restricted_product_only_for_independent_grocer(api):
    """PRD §3.2: "Channel restriction is enforced at creation: a
    `channel_restricted` product may be authorized only for an `INDEPENDENT_GROCER`
    account, and any other pairing is refused with
    `ERR_PRODUCT_CHANNEL_RESTRICTED`."

    The same restricted product fails for a CONVENIENCE account and is born
    AUTHORIZED for an approved INDEPENDENT_GROCER account.

    Design: Corner/validations/channel_restricted_product_only_for_independent
    """
    net = setup_active_distributor()
    product = create_product(code="P1", name="Reserve Item", channel_restricted=True)
    convenience = propose_account(net["distributor"], net["territory"],
                                  name="C-Store", channel="CONVENIENCE")
    approve_account(convenience["id"])
    independent = propose_account(net["distributor"], net["territory"],
                                  name="Indy", channel="INDEPENDENT_GROCER")
    approve_account(independent["id"])

    resp = api.create_authorization(
        {"account_id": convenience["id"], "product_id": product["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_CHANNEL_RESTRICTED)

    authorization = validate_success(api.create_authorization(
        {"account_id": independent["id"], "product_id": product["id"]}, ADMIN),
        expected_status=201)
    assert authorization["status"] == "AUTHORIZED"


def test_proposal_in_foreign_territory_rejected(api):
    """PRD §3.2: "The account's `distributor_id` is set from the caller's `X-User-ID`,
    and the named territory must be effectively `GRANTED` to that proposing
    distributor at proposal time, else the proposal is refused with
    `ERR_TERRITORY_VIOLATION`."

    Territory exclusivity: a distributor cannot propose an account in a territory
    granted to a different distributor.

    Design: Corner/validations/proposal_in_foreign_territory_rejected
    """
    net = setup_active_distributor()
    other = create_distributor(code="D2", name="Dist Two")
    resp = api.create_account(
        create_account_payload(net["territory"]["id"], name="Poach Store"),
        make_distributor_rep_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_VIOLATION)
