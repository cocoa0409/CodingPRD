"""RBAC corners: authentication before role, and role before everything else.

Every test here translates one instance of the CORNER design index's ``rbac``
section, and each of those instances is a *precedence* claim as much as a
permission claim. PRD section 2.5 puts authentication at tier 1, role
authorisation at tier 2 and identity resolution at tier 3, all of them above
path existence at tier 4 and state legality at tier 11 -- so a forbidden role is
refused with ``ERR_UNAUTHORIZED`` even when the target does not exist or sits in
a state that would refuse the operation anyway.
"""

from types import SimpleNamespace

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ROLE_IDENTITY_MISMATCH,
    ERR_SECTION_SELF_APPROVAL,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import ids_of
from test_helpers.test_users import (
    BOND_COUNSEL_DRAFTER_HEADERS,
    BOND_COUNSEL_DRAFTER_ID,
    BOND_COUNSEL_REVIEWER_HEADERS,
    BOND_COUNSEL_REVIEWER_ID,
    COMPLIANCE_HEADERS,
    COMPLIANCE_OFFICER_ID,
    RATING_ANALYST_HEADERS,
    headers_empty_role,
    headers_empty_user_id,
    headers_missing_role,
    headers_missing_user_id,
    headers_no_credentials,
    make_advisor_headers,
    make_issuer_official_headers,
    make_underwriter_headers,
)
from test_helpers.types import (
    DealStatus,
    EnhancementStatus,
    FirmType,
    MemberRole,
    MemberStatus,
    ReviewStatus,
    SaleMethod,
    UndertakingStatus,
    UserRole,
)

# PRD section 2.1: "If either header is absent or blank, the request is rejected
# with ERR_UNAUTHENTICATED (HTTP 401)." Five ways a credential pair can breach
# tier 1 of the ladder, all of them below the role check at tier 2.
CREDENTIAL_DEFECTS = {
    "no_credentials": lambda: headers_no_credentials(),
    "missing_user_id": lambda: headers_missing_user_id(UserRole.COMPLIANCE_OFFICER),
    "missing_role": lambda: headers_missing_role(COMPLIANCE_OFFICER_ID),
    "blank_user_id": lambda: headers_empty_user_id(UserRole.COMPLIANCE_OFFICER),
    "blank_role": lambda: headers_empty_role(COMPLIANCE_OFFICER_ID),
}

# PRD section 4 names `ComplianceOfficer` alone on POST /bond-offerings/firms, so
# the two Firm-backed roles and an opaque role stand in for the denied cohort.
FIRM_REGISTRATION_DENIED_ROLES = (
    UserRole.MUNICIPAL_ADVISOR,
    UserRole.ISSUER_OFFICIAL,
    UserRole.RATING_ANALYST,
)

# PRD section 4 names `Underwriter` alone on POST /bond-offerings/deals/{id}/price.
PRICING_DENIED_ROLES = (UserRole.MUNICIPAL_ADVISOR, UserRole.COMPLIANCE_OFFICER)

# PRD section 4 names `MunicipalAdvisor` alone on the maturity schedule.
SCHEDULE_DENIED_ROLES = (UserRole.UNDERWRITER, UserRole.ISSUER_OFFICIAL)


def _headers_for_role(ctx, role):
    """Headers for ``role`` in ``ctx``; entity-backed roles resolve to their own row.

    PRD section 2.1 makes `IssuerOfficial`, `MunicipalAdvisor` and `Underwriter`
    entity-backed, so their headers can only be built from a persisted row, while
    the three opaque roles carry fixed identifiers.
    """
    if role == UserRole.ISSUER_OFFICIAL:
        return make_issuer_official_headers(ctx.issuer_id)
    if role == UserRole.MUNICIPAL_ADVISOR:
        return make_advisor_headers(ctx.advisor_firm_id)
    if role == UserRole.UNDERWRITER:
        return make_underwriter_headers(ctx.underwriter_firm_id)
    if role == UserRole.BOND_COUNSEL:
        return BOND_COUNSEL_DRAFTER_HEADERS
    if role == UserRole.RATING_ANALYST:
        return RATING_ANALYST_HEADERS
    return COMPLIANCE_HEADERS


def _advisor_firm_and_issuer(client):
    """One MUNICIPAL_ADVISOR firm and one issuer, so entity-backed roles resolve.

    The advisory firm is deliberately the only `Firm` on file, which is what makes
    the closing count of exactly one firm a falsifiable assertion.
    """
    advisor_firm = fx.register_advisor_firm(client)
    issuer = fx.register_issuer(client)
    return SimpleNamespace(
        advisor_firm_id=advisor_firm["id"],
        issuer_id=issuer["id"],
    )


def _firm_body():
    """A perfectly valid UNDERWRITER registration body, so only the role can be at fault."""
    return f.firm_payload(FirmType.UNDERWRITER)


@pytest.mark.parametrize("defect", sorted(CREDENTIAL_DEFECTS))
def test_firm_registration_without_credentials_is_unauthenticated(client, defect):
    """PRD 2.1: "If either header is absent or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_header_is_rejected_before_the_role_check
    """
    response = client.create_firm(_firm_body(), CREDENTIAL_DEFECTS[defect]())
    error = validate_error(response, ERR_UNAUTHENTICATED)
    # Tier 1 sits strictly above tier 2, so a ComplianceOfficer-only endpoint
    # must not report the role failure that a credential-less call also has.
    assert error["error_id"] != ERR_UNAUTHORIZED

    firms, meta = validate_paginated(client.list_firms(COMPLIANCE_HEADERS))
    assert firms == []
    assert meta["total_count"] == 0


def test_an_authenticated_but_forbidden_role_is_unauthorized(client):
    """PRD 2.1: "If both headers are present but the declared role is not among the roles authorised for the target endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/missing_auth_header_is_rejected_before_the_role_check
    """
    response = client.create_firm(_firm_body(), BOND_COUNSEL_DRAFTER_HEADERS)
    error = validate_error(response, ERR_UNAUTHORIZED)
    assert error["error_id"] != ERR_UNAUTHENTICATED

    firms, meta = validate_paginated(client.list_firms(COMPLIANCE_HEADERS))
    assert firms == []
    assert meta["total_count"] == 0


def test_the_compliance_officer_registers_the_same_firm(client):
    """PRD 3.1: "Registering a firm is reserved to a `ComplianceOfficer` and captures the firm's registered `name` (one to one hundred sixty characters, not blank), its `firm_type` — one of `UNDERWRITER`, `MUNICIPAL_ADVISOR`, or `DUAL_REGISTERED` — and its `msrb_registration_id`, exactly six uppercase alphanumeric characters that must be unique across every firm in the system."

    Design: Corner/rbac/missing_auth_header_is_rejected_before_the_role_check
    """
    body = _firm_body()
    firm = validate_success(client.create_firm(body, COMPLIANCE_HEADERS), 201)
    assert firm["msrb_registration_id"] == body["msrb_registration_id"]
    assert firm["firm_type"] == FirmType.UNDERWRITER

    firms, meta = validate_paginated(client.list_firms(COMPLIANCE_HEADERS))
    assert meta["total_count"] == 1
    assert ids_of(firms) == [firm["id"]]


@pytest.mark.parametrize("role", FIRM_REGISTRATION_DENIED_ROLES)
def test_firm_registration_is_refused_to_every_other_role(client, role):
    """PRD 2.5: "**Role authorisation.** The declared role appears in the endpoint's authorised-role list, on every authenticated endpoint. Otherwise `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/firm_registration_is_exclusive_to_the_compliance_officer
    """
    ctx = _advisor_firm_and_issuer(client)

    # Every rejected caller is a resolvable principal: the advisor and the issuer
    # name persisted rows, so tier 3 cannot be what refuses them.
    response = client.create_firm(_firm_body(), _headers_for_role(ctx, role))
    validate_error(response, ERR_UNAUTHORIZED)

    firms, meta = validate_paginated(client.list_firms(COMPLIANCE_HEADERS))
    assert meta["total_count"] == 1
    assert ids_of(firms) == [ctx.advisor_firm_id]


@pytest.mark.parametrize("role", PRICING_DENIED_ROLES)
def test_pricing_is_refused_to_non_underwriters_before_the_state_check(
    client, draft_deal, role
):
    """PRD 3.8: "Pricing is the single largest write in the system: it is taken by an `Underwriter`, it is the point at which underwriter compensation becomes a disclosed number under MSRB Rule G-17, and it runs five calculations in a pinned order."

    Design: Corner/rbac/pricing_is_exclusive_to_the_underwriter_before_any_state_check
    """
    ctx = draft_deal
    before = fx.read_deal(client, ctx.deal_id, ctx.issuer_headers)
    assert before["status"] == DealStatus.DRAFT

    # A DRAFT deal is not priceable either, but tier 2 outranks tier 11, so the
    # role failure is the only thing the caller may observe.
    response = client.price_deal(
        ctx.deal_id, f.negotiated_pricing_payload(), _headers_for_role(ctx, role)
    )
    validate_error(response, ERR_UNAUTHORIZED)

    after = fx.read_deal(client, ctx.deal_id, ctx.issuer_headers)
    assert after["status"] == DealStatus.DRAFT
    assert after["gross_spread_total_usd"] is None
    assert after["version"] == before["version"]


def test_opening_a_missing_period_reports_the_role_not_the_absence(client, draft_deal):
    """PRD 2.5: "Requests are validated in a fixed sixteen-tier ladder, and **only the first violated tier is reported**."

    Design: Corner/rbac/pricing_is_exclusive_to_the_underwriter_before_any_state_check
    """
    ctx = draft_deal

    # Opening a book belongs to the `Underwriter` alone, and the path names no
    # row at all: tier 2 answers before tier 4 ever looks the identifier up.
    response = client.open_order_period(NON_EXISTENT_UUID, None, ctx.advisor_headers)
    validate_error(response, ERR_UNAUTHORIZED)


def test_award_is_refused_to_the_underwriter(client, draft_deal):
    """PRD 3.9: "Award is taken by an `IssuerOfficial` and moves the deal from `PRICED` to `AWARDED`."

    Design: Corner/rbac/award_and_cancel_are_exclusive_to_the_issuer_official
    """
    ctx = draft_deal
    before = fx.read_deal(client, ctx.deal_id, ctx.issuer_headers)

    response = client.award_deal(ctx.deal_id, None, ctx.underwriter_headers)
    validate_error(response, ERR_UNAUTHORIZED)

    after = fx.read_deal(client, ctx.deal_id, ctx.issuer_headers)
    assert after["status"] == DealStatus.DRAFT
    assert after["version"] == before["version"]


def test_cancellation_is_refused_to_the_compliance_officer(client, draft_deal):
    """PRD 3.9: "Cancellation is taken by an `IssuerOfficial` supplying a `cancellation_reason`, and it is available from `DRAFT`, `STRUCTURING`, `PRICING_COMPETITIVE`, `PRICING_NEGOTIATED`, and `PRICED`."

    Design: Corner/rbac/award_and_cancel_are_exclusive_to_the_issuer_official
    """
    ctx = draft_deal
    before = fx.read_deal(client, ctx.deal_id, ctx.issuer_headers)

    # The deal really is in a cancellable state, so nothing but the role stands
    # between this request and the unwinding cascade.
    response = client.cancel_deal(
        ctx.deal_id,
        f.cancellation_payload("Compliance attempted an issuer decision"),
        COMPLIANCE_HEADERS,
    )
    validate_error(response, ERR_UNAUTHORIZED)

    after = fx.read_deal(client, ctx.deal_id, ctx.issuer_headers)
    assert after["status"] == DealStatus.DRAFT
    assert after["cancellation_reason"] is None
    assert after["version"] == before["version"]


def test_committing_an_enhancement_is_refused_to_the_advisor(client, draft_deal):
    """PRD 3.3: "Committing is the `IssuerOfficial`'s decision to buy the enhancement, and it moves the proposal from `PROPOSED` to `COMMITTED`."

    Design: Corner/rbac/award_and_cancel_are_exclusive_to_the_issuer_official
    """
    ctx = draft_deal
    enhancement = fx.propose_enhancement(
        client, ctx.deal_id, [ctx.tranche_ids[0]], ctx.advisor_headers
    )
    assert enhancement["status"] == EnhancementStatus.PROPOSED

    response = client.commit_credit_enhancement(
        enhancement["id"], None, ctx.advisor_headers
    )
    validate_error(response, ERR_UNAUTHORIZED)

    enhancements, meta = validate_paginated(
        client.list_deal_credit_enhancements(ctx.deal_id, COMPLIANCE_HEADERS)
    )
    assert meta["total_count"] == 1
    assert enhancements[0]["status"] == EnhancementStatus.PROPOSED
    assert enhancements[0]["version"] == enhancement["version"]


def test_activating_an_undertaking_is_refused_to_bond_counsel(client, draft_deal):
    """PRD 3.4: "Activating one is an `IssuerOfficial` act: the undertaking must be in `DRAFT`, or the request is refused with `ERR_UNDERTAKING_INVALID_STATE`, and the deal must not be `CLOSED` or `CANCELLED`, or it is refused with `ERR_DEAL_INVALID_STATE`."

    Design: Corner/rbac/award_and_cancel_are_exclusive_to_the_issuer_official
    """
    ctx = draft_deal
    undertaking = fx.draft_undertaking(client, ctx.deal_id, ctx.counsel_headers)
    assert undertaking["status"] == UndertakingStatus.DRAFT

    # The drafter of the undertaking is not its activator: both of the state
    # preconditions in the quoted sentence hold, and the role still refuses.
    response = client.activate_undertaking(
        undertaking["id"], None, BOND_COUNSEL_DRAFTER_HEADERS
    )
    validate_error(response, ERR_UNAUTHORIZED)

    undertakings, meta = validate_paginated(
        client.list_deal_undertakings(ctx.deal_id, COMPLIANCE_HEADERS)
    )
    assert meta["total_count"] == 1
    assert undertakings[0]["status"] == UndertakingStatus.DRAFT
    assert undertakings[0]["version"] == undertaking["version"]


def _deal_with_seated_senior_manager(client):
    """A DRAFT deal carrying no maturities yet, with the underwriting firm seated.

    The seat matters: it makes the `Underwriter` a fully entitled actor on this
    deal under PRD section 2.1, so a refusal to add a maturity can only come from
    the endpoint's role list and not from ownership.
    """
    ctx = fx.draft_deal(client, tranches=False)
    ctx.senior_member = fx.seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.advisor_headers,
        MemberRole.SENIOR_MANAGER,
    )
    assert ctx.senior_member["status"] == MemberStatus.ACTIVE
    return ctx


@pytest.fixture
def seated_draft_deal(client):
    """A DRAFT deal with no maturities and one ACTIVE SENIOR_MANAGER seat."""
    return _deal_with_seated_senior_manager(client)


@pytest.mark.parametrize("role", SCHEDULE_DENIED_ROLES)
def test_only_the_advisor_may_add_a_maturity(client, seated_draft_deal, role):
    """PRD 3.2: "Only a `MunicipalAdvisor` may add maturities."

    Design: Corner/rbac/structuring_the_schedule_is_exclusive_to_the_municipal_advisor
    """
    ctx = seated_draft_deal

    response = client.create_maturity_tranche(
        ctx.deal_id, f.canonical_tranche_1_payload(), _headers_for_role(ctx, role)
    )
    validate_error(response, ERR_UNAUTHORIZED)

    tranches, meta = validate_paginated(
        client.list_deal_maturity_tranches(ctx.deal_id, ctx.advisor_headers)
    )
    assert tranches == []
    assert meta["total_count"] == 0


def test_the_advisor_adds_the_identical_maturity(client, seated_draft_deal):
    """PRD 2.1: "A `MunicipalAdvisor` may act only on a deal whose `municipal_advisor_firm_id` equals `X-User-ID`."

    Design: Corner/rbac/structuring_the_schedule_is_exclusive_to_the_municipal_advisor
    """
    ctx = seated_draft_deal
    body = f.canonical_tranche_1_payload()

    tranche = validate_success(
        client.create_maturity_tranche(ctx.deal_id, body, ctx.advisor_headers), 201
    )
    assert tranche["sequence_number"] == body["sequence_number"]
    assert tranche["principal_amount_usd"] == body["principal_amount_usd"]

    tranches, meta = validate_paginated(
        client.list_deal_maturity_tranches(ctx.deal_id, ctx.advisor_headers)
    )
    assert meta["total_count"] == 1
    assert ids_of(tranches) == [tranche["id"]]

    # The advisor's write lands on the maturity, not on the deal's par counter:
    # PRD section 3.2 fills `par_amount_usd` only when the structure is submitted.
    deal = fx.read_deal(client, ctx.deal_id, ctx.issuer_headers)
    assert deal["status"] == DealStatus.DRAFT
    assert deal["par_amount_usd"] == 0


def test_submitting_the_structure_is_refused_to_the_underwriter(
    client, seated_draft_deal
):
    """PRD 3.2: "Submitting the structure is the `MunicipalAdvisor`'s act of freezing the schedule, and it advances the deal from `DRAFT` to `STRUCTURING`."

    Design: Corner/rbac/structuring_the_schedule_is_exclusive_to_the_municipal_advisor
    """
    ctx = seated_draft_deal
    fx.add_tranche(client, ctx.deal_id, ctx.advisor_headers, f.canonical_tranche_1_payload())
    before = fx.read_deal(client, ctx.deal_id, ctx.issuer_headers)

    # One 5,000,000 maturity against a 10,000,000 authorisation would also fail
    # the fiscal footing check at tier 16; the role failure at tier 2 wins.
    response = client.submit_structure(ctx.deal_id, None, ctx.underwriter_headers)
    validate_error(response, ERR_UNAUTHORIZED)

    after = fx.read_deal(client, ctx.deal_id, ctx.issuer_headers)
    assert after["status"] == DealStatus.DRAFT
    assert after["par_amount_usd"] == 0
    assert after["version"] == before["version"]


def test_the_issuer_official_designates_the_sale_method(client, structuring_deal):
    """PRD 3.6: "Choosing `COMPETITIVE` moves the deal from `STRUCTURING` to `PRICING_COMPETITIVE` and models a public bid: the issuer publishes a notice of sale, bidders bid, and there is no pre-formed syndicate."

    Design: Corner/rbac/sale_method_designation_is_shared_by_the_advisor_and_the_issuer
    """
    ctx = structuring_deal
    assert ctx.deal["status"] == DealStatus.STRUCTURING

    deal = validate_success(
        client.designate_sale_method(
            ctx.deal_id, f.sale_method_payload(SaleMethod.COMPETITIVE), ctx.issuer_headers
        ),
        200,
    )
    assert deal["status"] == DealStatus.PRICING_COMPETITIVE
    assert deal["sale_method"] == SaleMethod.COMPETITIVE
    assert deal["requires_notice_of_sale"] is True


def test_the_advisor_designates_the_sale_method(client, structuring_deal):
    """PRD 3.6: "Designating the sale method is the branching decision of the whole transaction and is taken by a `MunicipalAdvisor` or an `IssuerOfficial` on a deal in `STRUCTURING`."

    Design: Corner/rbac/sale_method_designation_is_shared_by_the_advisor_and_the_issuer
    """
    ctx = structuring_deal

    deal = validate_success(
        client.designate_sale_method(
            ctx.deal_id, f.sale_method_payload(SaleMethod.COMPETITIVE), ctx.advisor_headers
        ),
        200,
    )
    assert deal["status"] == DealStatus.PRICING_COMPETITIVE
    assert deal["sale_method"] == SaleMethod.COMPETITIVE


def test_the_underwriter_may_not_designate_the_sale_method(client, structuring_deal):
    """PRD 2.1: "If both headers are present but the declared role is not among the roles authorised for the target endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/sale_method_designation_is_shared_by_the_advisor_and_the_issuer
    """
    ctx = structuring_deal

    # The same body the advisor and the issuer are both allowed to send.
    response = client.designate_sale_method(
        ctx.deal_id, f.sale_method_payload(SaleMethod.COMPETITIVE), ctx.underwriter_headers
    )
    validate_error(response, ERR_UNAUTHORIZED)

    after = fx.read_deal(client, ctx.deal_id, ctx.issuer_headers)
    assert after["status"] == DealStatus.STRUCTURING
    assert after["sale_method"] == SaleMethod.UNDETERMINED
    assert after["version"] == ctx.deal["version"]


# Three ways a `MunicipalAdvisor` header can fail before any maturity is written:
# the first two at tier 3 (identity resolution) and the third at tier 8 (actor
# ownership), all three reporting the same error id.
BAD_ADVISOR_IDENTITIES = ("wrong_firm_type", "unknown_identifier", "unrelated_advisor_firm")


def _bad_advisor_headers(ctx, defect):
    """A `MunicipalAdvisor` header that either cannot resolve or does not own the deal."""
    if defect == "wrong_firm_type":
        return make_advisor_headers(ctx.underwriter_firm_id)
    if defect == "unknown_identifier":
        return make_advisor_headers(NON_EXISTENT_UUID)
    return make_advisor_headers(fx.register_advisor_firm(ctx.client)["id"])


@pytest.mark.parametrize("defect", BAD_ADVISOR_IDENTITIES)
def test_the_advisor_must_resolve_and_own_the_deal(client, defect):
    """PRD 2.1: "Ownership of deal-scoped work is checked separately from role membership and also reports `ERR_ROLE_IDENTITY_MISMATCH`."

    Design: Corner/rbac/entity_backed_roles_must_resolve_and_own_the_deal
    """
    ctx = fx.draft_deal(client, tranches=False)

    # A firm identifier that names no row does not fall through to a 404: tier 3
    # answers before tier 4, and the unrelated advisory firm is refused at tier 8.
    response = client.create_maturity_tranche(
        ctx.deal_id, f.canonical_tranche_1_payload(), _bad_advisor_headers(ctx, defect)
    )
    validate_error(response, ERR_ROLE_IDENTITY_MISMATCH)

    tranches, meta = validate_paginated(
        client.list_deal_maturity_tranches(ctx.deal_id, ctx.advisor_headers)
    )
    assert tranches == []
    assert meta["total_count"] == 0


def test_the_engaged_advisor_writes_the_maturity(client):
    """PRD 2.5: "**Identity resolution.** On every endpoint whose authorised-role list contains an entity-backed role, `X-User-ID` resolves to an existing `Issuer` (for `IssuerOfficial`) or to an existing `Firm` whose `firm_type` admits the declared role (for `MunicipalAdvisor` and `Underwriter`). Otherwise `ERR_ROLE_IDENTITY_MISMATCH`."

    Design: Corner/rbac/entity_backed_roles_must_resolve_and_own_the_deal
    """
    ctx = fx.draft_deal(client, tranches=False)

    tranche = validate_success(
        client.create_maturity_tranche(
            ctx.deal_id, f.canonical_tranche_1_payload(), ctx.advisor_headers
        ),
        201,
    )

    tranches, meta = validate_paginated(
        client.list_deal_maturity_tranches(ctx.deal_id, ctx.advisor_headers)
    )
    assert meta["total_count"] == 1
    assert ids_of(tranches) == [tranche["id"]]


def _two_underwriter_deal(client):
    """A DRAFT deal with no syndicate and a second, unrelated underwriting firm."""
    ctx = fx.draft_deal(client, tranches=False)
    ctx.other_underwriter_firm = fx.register_underwriter_firm(client)
    ctx.other_underwriter_firm_id = ctx.other_underwriter_firm["id"]
    ctx.other_underwriter_headers = make_underwriter_headers(ctx.other_underwriter_firm_id)
    return ctx


@pytest.fixture
def two_underwriter_deal(client):
    """A DRAFT deal with an empty syndicate and two eligible underwriting firms."""
    return _two_underwriter_deal(client)


def _senior_seat_payload(firm_id):
    """A SENIOR_MANAGER seat at sixty percent of liability and takedown, rank one."""
    return f.syndicate_member_payload(firm_id, MemberRole.SENIOR_MANAGER, 60.0000, 60.0000, 1)


def _co_manager_seat_payload(firm_id):
    """A CO_MANAGER seat at forty percent of liability and takedown, rank two."""
    return f.syndicate_member_payload(firm_id, MemberRole.CO_MANAGER, 40.0000, 40.0000, 2)


def test_an_unseated_underwriter_may_not_seat_another_firm(client, two_underwriter_deal):
    """PRD 2.1: "An `Underwriter` may act only on a deal on which the firm named by `X-User-ID` holds a `SyndicateMember` row with `status` `ACTIVE`, with two carve-outs: on a deal whose `sale_method` is `COMPETITIVE`, any firm that is not suspended and whose `firm_type` admits the `Underwriter` role may act, because a competitive sale has no pre-sale syndicate; and when adding a syndicate member, an as-yet unseated `Underwriter` may add its own firm, that is, a request whose `firm_id` equals `X-User-ID`."

    Design: Corner/rbac/an_unseated_underwriter_may_add_only_its_own_firm_to_the_syndicate
    """
    ctx = two_underwriter_deal

    # The bootstrap carve-out is narrow: the acting firm may seat itself, so a
    # request naming any other firm falls back to the ACTIVE-seat requirement.
    response = client.create_syndicate_member(
        ctx.deal_id,
        _senior_seat_payload(ctx.underwriter_firm_id),
        ctx.other_underwriter_headers,
    )
    validate_error(response, ERR_ROLE_IDENTITY_MISMATCH)

    members, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, COMPLIANCE_HEADERS)
    )
    assert members == []
    assert meta["total_count"] == 0


def test_an_unseated_underwriter_seats_its_own_firm(client, two_underwriter_deal):
    """PRD 3.6: "A new seat has `status` `ACTIVE` and `takedown_credit_usd` zero, and its `liability_par_usd` is set immediately when the deal's `par_amount_usd` is already known — that is, once the structure has been submitted; otherwise it starts at zero and is filled in when the structure is submitted."

    Design: Corner/rbac/an_unseated_underwriter_may_add_only_its_own_firm_to_the_syndicate
    """
    ctx = two_underwriter_deal

    member = validate_success(
        client.create_syndicate_member(
            ctx.deal_id,
            _senior_seat_payload(ctx.underwriter_firm_id),
            ctx.underwriter_headers,
        ),
        201,
    )
    assert member["firm_id"] == ctx.underwriter_firm_id
    assert member["member_role"] == MemberRole.SENIOR_MANAGER
    assert member["status"] == MemberStatus.ACTIVE

    members, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, COMPLIANCE_HEADERS)
    )
    assert meta["total_count"] == 1
    assert ids_of(members) == [member["id"]]


def test_a_seated_underwriter_seats_the_second_firm(client, two_underwriter_deal):
    """PRD 3.6: "Seating an underwriting firm on a deal is available to an `Underwriter` or a `MunicipalAdvisor` and supplies the `firm_id` of the firm being seated, a `member_role` of `SENIOR_MANAGER`, `CO_MANAGER`, or `SELLING_GROUP`, a `liability_pct` share of the underwriting liability, a `takedown_share_pct` share of the syndicate takedown pot, and a `priority_rank` used only for reporting order."

    Design: Corner/rbac/an_unseated_underwriter_may_add_only_its_own_firm_to_the_syndicate
    """
    ctx = two_underwriter_deal
    senior = fx.seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.underwriter_headers,
        MemberRole.SENIOR_MANAGER,
        liability_pct=60.0000,
        takedown_share_pct=60.0000,
        priority_rank=1,
    )

    # Now that the senior manager holds an ACTIVE seat it acts on the deal in its
    # own right, so it may seat a firm other than itself.
    co_manager = validate_success(
        client.create_syndicate_member(
            ctx.deal_id,
            _co_manager_seat_payload(ctx.other_underwriter_firm_id),
            ctx.underwriter_headers,
        ),
        201,
    )
    assert co_manager["firm_id"] == ctx.other_underwriter_firm_id
    assert co_manager["member_role"] == MemberRole.CO_MANAGER
    assert co_manager["status"] == MemberStatus.ACTIVE

    members, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, COMPLIANCE_HEADERS)
    )
    assert meta["total_count"] == 2
    assert sorted(ids_of(members)) == sorted([senior["id"], co_manager["id"]])


def _drafted_section(client):
    """A DRAFTING official statement carrying one section authored by the drafter."""
    ctx = fx.with_drafting_statement(fx.draft_deal(client))
    ctx.section = fx.add_section(
        client, ctx.statement_id, f.section_payload(), BOND_COUNSEL_DRAFTER_HEADERS
    )
    ctx.section_id = ctx.section["id"]
    assert ctx.section["authored_by_user_id"] == BOND_COUNSEL_DRAFTER_ID
    assert ctx.section["review_status"] == ReviewStatus.DRAFT
    assert ctx.section["approved_by_user_id"] is None
    return ctx


@pytest.fixture
def drafted_section(client):
    """A statement in DRAFTING with one DRAFT section authored by the drafting counsel."""
    return _drafted_section(client)


def test_an_author_may_not_approve_their_own_section(client, drafted_section):
    """PRD 3.4: "And the approving `X-User-ID` must differ from the section's `authored_by_user_id`, or the request is refused with `ERR_SECTION_SELF_APPROVAL`."

    Design: Corner/rbac/a_section_author_may_not_approve_their_own_section
    """
    ctx = drafted_section

    # `BondCounsel` is an authorised role on this endpoint, so the refusal is the
    # Rule G-17 conduct rule at tier 12, not the role check at tier 2.
    response = client.approve_section(ctx.section_id, None, BOND_COUNSEL_DRAFTER_HEADERS)
    error = validate_error(response, ERR_SECTION_SELF_APPROVAL)
    assert error["error_id"] != ERR_UNAUTHORIZED

    after = validate_success(
        client.get_os_section(ctx.section_id, BOND_COUNSEL_REVIEWER_HEADERS), 200
    )
    assert after["review_status"] == ReviewStatus.DRAFT
    assert after["approved_by_user_id"] is None
    assert after["version"] == ctx.section["version"]


def test_a_second_counsel_approves_the_section(client, drafted_section):
    """PRD 2.8: "When a section of an official statement is approved, the approving `X-User-ID` must differ from the `authored_by_user_id` recorded on that section when it was created."

    Design: Corner/rbac/a_section_author_may_not_approve_their_own_section
    """
    ctx = drafted_section

    approved = validate_success(
        client.approve_section(ctx.section_id, None, BOND_COUNSEL_REVIEWER_HEADERS), 200
    )
    assert approved["review_status"] == ReviewStatus.APPROVED
    assert approved["authored_by_user_id"] == BOND_COUNSEL_DRAFTER_ID
    assert approved["approved_by_user_id"] == BOND_COUNSEL_REVIEWER_ID
    assert approved["version"] == ctx.section["version"] + 1


def _scheduled_book(client, negotiated_deal):
    """A negotiated deal carrying one SCHEDULED institutional order period."""
    ctx = negotiated_deal
    ctx.period = fx.schedule_order_period(client, ctx.deal_id, ctx.advisor_headers)
    ctx.period_id = ctx.period["id"]
    return ctx


def test_the_rating_analyst_reads_the_deal_but_not_the_order_book(
    client, negotiated_deal
):
    """PRD 2.5: "**Role authorisation.** The declared role appears in the endpoint's authorised-role list, on every authenticated endpoint. Otherwise `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/the_rating_analyst_cannot_read_the_order_book
    """
    ctx = _scheduled_book(client, negotiated_deal)

    # Section 4 grants the analyst the deal, the maturity and the order period.
    deal = validate_success(client.get_deal(ctx.deal_id, RATING_ANALYST_HEADERS), 200)
    assert deal["status"] == DealStatus.PRICING_NEGOTIATED
    tranche = validate_success(
        client.get_maturity_tranche(ctx.tranche_ids[0], RATING_ANALYST_HEADERS), 200
    )
    assert tranche["deal_id"] == ctx.deal_id
    period = validate_success(
        client.get_order_period(ctx.period_id, RATING_ANALYST_HEADERS), 200
    )
    assert period["deal_id"] == ctx.deal_id

    # The order book itself is not among the analyst's grants, and the book being
    # empty is no defence: tier 2 answers before anything is read.
    response = client.list_period_orders(ctx.period_id, RATING_ANALYST_HEADERS)
    validate_error(response, ERR_UNAUTHORIZED)


def test_the_compliance_officer_reads_the_empty_order_book(client, negotiated_deal):
    """PRD 2.3: "`total_count` reports the number of rows matching the request's filters before the pagination window is applied, and `has_more` is true exactly when rows matching the filters remain beyond the returned window."

    Design: Corner/rbac/the_rating_analyst_cannot_read_the_order_book
    """
    ctx = _scheduled_book(client, negotiated_deal)

    orders, meta = validate_paginated(
        client.list_period_orders(ctx.period_id, COMPLIANCE_HEADERS)
    )
    assert orders == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
