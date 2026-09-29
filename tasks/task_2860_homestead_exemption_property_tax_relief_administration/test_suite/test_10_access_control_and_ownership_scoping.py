"""Who may act, on whose record, and which refusal is reported first.

Four gates stand in front of every county capability, and they are consulted in
a fixed order: the caller's identity, the caller's role, the taxpayer's ownership
of the addressed row, and the separation of one operator's duty from another's.
Each gate has its own refusal, and a caller who trips two of them at once is
always told about the earlier one.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_APPEAL_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_DOCKET_NOT_FOUND,
    ERR_FRAUD_CASE_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_NOTICE_NOT_FOUND,
    ERR_PARCEL_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TAXPAYER_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
)
from test_helpers.assertions import (
    assert_claim_amounts,
    assert_grant,
    assert_parcel_decomposition,
    assert_taxpayer_ledger,
)
from test_helpers.constants import ADDR_ELM, ROLES
from test_helpers.test_users import (
    ANALYST,
    CLERK,
    HEARING_CLERK,
    INVESTIGATOR,
    NO_AUTH_HEADERS,
    REVIEWER,
    REVIEWER_2,
    REVIEWER_2_USER_ID,
    REVIEWER_USER_ID,
    UNREGISTERED_ROLE,
    make_headers,
    make_taxpayer_headers,
)


def test_each_unresolved_identifier_answers_with_its_own_entity_specific_404(api):
    """PRD §2.10 rung 6: "Path identifiers resolve, left to right —
    `ERR_PARCEL_NOT_FOUND`, `ERR_TAXPAYER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_FRAUD_CASE_NOT_FOUND`,
    `ERR_APPEAL_NOT_FOUND` or `ERR_DOCKET_NOT_FOUND`. Applies to every endpoint with
    a path parameter." PRD §2.10 rung 7 covers the referenced key: "Body foreign keys
    resolve — the same not-found family plus `ERR_PROGRAM_NOT_FOUND` and
    `ERR_NOTICE_NOT_FOUND` ... Applies to ... `POST /appeals`". PRD §2.10 rung 3 gives
    way to both: "When the addressed or referenced resource does not exist at all,
    ownership cannot be evaluated and the not-found error from rung 6 or rung 7 is
    returned instead."

    Design: Corner/errors/unknown_path_and_body_identifiers_return_not_found
    """
    fx.set_clock(api)
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())

    # Not one of these collections holds a single row.
    validate_error(
        api.get_application(NON_EXISTENT_UUID, CLERK),
        ERR_APPLICATION_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_retroactive_claim(NON_EXISTENT_UUID, CLERK),
        ERR_CLAIM_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_fraud_case(NON_EXISTENT_UUID, INVESTIGATOR),
        ERR_FRAUD_CASE_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_appeal(NON_EXISTENT_UUID, HEARING_CLERK),
        ERR_APPEAL_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_hearing_docket(NON_EXISTENT_UUID, HEARING_CLERK),
        ERR_DOCKET_NOT_FOUND,
        expected_status=404,
    )

    # The taxpayer names a notice that does not exist, so there is no row whose
    # owner could be compared against the acting account.
    response = api.create_appeal(
        f.appeal(NON_EXISTENT_UUID, grounds="The denial was issued in error."),
        make_taxpayer_headers(taxpayer["id"]),
    )
    validate_error(response, ERR_NOTICE_NOT_FOUND, expected_status=404)
    assert ERR_NOT_RESOURCE_OWNER not in response.text, (
        "a missing referenced row has no owner to compare against, so the "
        f"body-key check must answer before the ownership check: {response.text}"
    )


def test_the_same_determination_body_is_refused_for_a_clerk_and_accepted_for_a_reviewer(api):
    """PRD §2.1: "A request whose role is well formed but is not among the roles
    authorised for the addressed operation (§4 lists the authorised roles for each) is
    rejected with `ERR_UNAUTHORIZED_ROLE`." PRD §4 names `ExemptionsReviewer` as the
    only role authorised for `/exemption-applications/{id}/determine`, and
    `AssessorAnalyst` as the only role authorised for `/parcels`. PRD §2.10 rung 2: "Role authorisation for the
    addressed operation — `ERR_UNAUTHORIZED_ROLE`. Applies to every endpoint."

    Design: Corner/rbac/intake_clerk_cannot_determine_an_application
    """
    fx.set_clock(api)
    program = fx.create_program(api, f.homestead_basic_program())
    parcel = fx.create_parcel(api, f.parcel())
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())
    application = fx.submitted_application(
        api, parcel["id"], taxpayer["id"], program["id"]
    )
    fx.run_checks(api, application["id"], ["VOTER_REGISTRY"])
    under_review = validate_success(api.get_application(application["id"], CLERK))
    assert under_review["status"] == "UNDER_REVIEW", (
        f"the claim must be determinable before the role is tested, got {under_review['status']}"
    )

    # One body, sent twice; only the role of the sender changes.
    determination = f.deny_determination(
        parcel["version"], denial_reason="Occupancy was not established."
    )
    validate_error(
        api.determine_application(application["id"], determination, CLERK),
        ERR_UNAUTHORIZED_ROLE,
        expected_status=403,
    )
    validate_error(
        api.create_parcel(
            f.parcel(
                apn="P-0009",
                situs_address_normalized=ADDR_ELM,
                base_year_value_cents=20000000,
                market_value_cents=25000000,
            ),
            CLERK,
        ),
        ERR_UNAUTHORIZED_ROLE,
        expected_status=403,
    )

    unchanged = validate_success(api.get_application(application["id"], CLERK))
    assert unchanged["status"] == "UNDER_REVIEW", (
        f"the refused determination applied nothing, got {unchanged['status']}"
    )
    assert unchanged["version"] == under_review["version"], (
        "a refused determination is not a mutation, so the version must not move: "
        f"{under_review['version']} became {unchanged['version']}"
    )
    assert unchanged["determined_by_user_id"] is None, (
        f"nobody determined it, got {unchanged['determined_by_user_id']!r}"
    )

    decided = validate_success(
        api.determine_application(application["id"], determination, REVIEWER)
    )
    assert decided["status"] == "DENIED", (
        "the identical body succeeds for the authorised role, so only the role "
        f"differed: got {decided['status']}"
    )
    assert decided["determined_by_user_id"] == REVIEWER_USER_ID, (
        f"the deciding reviewer is stamped, got {decided['determined_by_user_id']!r}"
    )

    final_parcel = validate_success(api.get_parcel(parcel["id"], ANALYST))
    assert final_parcel["version"] == 1, (
        "a denial mints no grant and rewrites no value, so the parcel is still at "
        f"the version it was created with: got {final_parcel['version']}"
    )
    assert_parcel_decomposition(
        final_parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )


def test_an_account_reads_for_its_owner_and_for_staff_but_not_for_a_neighbour(api):
    """PRD §2.1: "When `X-User-Role` is `Taxpayer`, `X-User-ID` is the `id` of the
    acting `TaxpayerAccount`; ownership checks compare that value against the taxpayer
    identifier reachable from the addressed resource. Resolution is direct for a
    taxpayer account and its sub-resource reads ... When the resolved taxpayer
    identifier differs from `X-User-ID`, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`." PRD §4 admits both parties on
    `/taxpayer-accounts/{id}`, listing "IntakeClerk, ExemptionsReviewer,
    FraudInvestigator, RecoveryOfficer, Taxpayer" as its authorised roles.

    Design: Corner/rbac/taxpayer_cannot_read_another_taxpayers_account
    """
    fx.set_clock(api)
    owner = fx.create_taxpayer(api, f.taxpayer_account())
    neighbour = fx.create_taxpayer(
        api,
        f.taxpayer_account(
            full_name="NORMAN NEIGHBOR",
            date_of_birth="1960-07-22",
            ssn_last4="8765",
            mailing_address_normalized=ADDR_ELM,
        ),
    )
    assert neighbour["id"] != owner["id"], "the two households must be distinct rows"

    validate_error(
        api.get_taxpayer_account(owner["id"], make_taxpayer_headers(neighbour["id"])),
        ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )

    own_read = validate_success(
        api.get_taxpayer_account(owner["id"], make_taxpayer_headers(owner["id"]))
    )
    assert own_read["full_name"] == owner["full_name"], (
        f"the owning household reads its own account, got {own_read['full_name']!r}"
    )
    assert_taxpayer_ledger(own_read, status="GOOD_STANDING")

    staff_read = validate_success(api.get_taxpayer_account(owner["id"], REVIEWER))
    assert staff_read["full_name"] == owner["full_name"], (
        "a staff role is not ownership-bound and reads the same path, got "
        f"{staff_read['full_name']!r}"
    )
    assert staff_read["id"] == own_read["id"], (
        f"both callers must be shown the same account, got {staff_read['id']}"
    )

    # There is no row behind this identifier, so there is no owner to compare to.
    response = api.get_taxpayer_account(
        NON_EXISTENT_UUID, make_taxpayer_headers(neighbour["id"])
    )
    validate_error(response, ERR_TAXPAYER_NOT_FOUND, expected_status=404)
    assert ERR_NOT_RESOURCE_OWNER not in response.text, (
        "the path-identifier check outranks the ownership check when the row does "
        f"not exist: {response.text}"
    )


def test_the_operator_who_keyed_the_claim_cannot_determine_it_whatever_role_he_wears(api):
    """PRD §2.8: "Four hand-offs in this system are duty-separated, and in each the
    server compares the acting `X-User-ID` against an operator identifier already
    recorded on the resource. A mismatch is required; equality is rejected with
    `ERR_SEGREGATION_OF_DUTIES`." PRD §2.8 names this one: "Determination is barred to
    the intake clerk: a determination whose acting `X-User-ID` equals the
    application's `intake_user_id` is refused." PRD §3.2 explains the stamp: "That
    stamp is the duty-separation bar of §2.8: whoever keyed the application is
    thereafter disqualified from determining it."

    Design: Corner/rbac/determination_by_the_intake_clerks_own_user_id_violates_segregation_of_duties
    """
    fx.set_clock(api)
    program = fx.create_program(api, f.homestead_basic_program())
    parcel = fx.create_parcel(api, f.parcel())
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())
    fx.add_ownership(api, parcel["id"], taxpayer["id"])
    fx.inject_matching_residency(api, taxpayer["id"])

    # The keying operator acts in the clerk capacity but under his own identity.
    keying_operator = make_headers(REVIEWER_USER_ID, "IntakeClerk")
    application = validate_success(
        api.create_application(
            f.application(parcel["id"], taxpayer["id"], program["id"]), keying_operator
        ),
        expected_status=201,
    )
    assert application["intake_user_id"] == REVIEWER_USER_ID, (
        "the creating call's acting identity is recorded whatever role it wore, got "
        f"{application['intake_user_id']!r}"
    )
    validate_success(api.submit_application(application["id"], keying_operator))
    fx.run_checks(
        api, application["id"], ["VOTER_REGISTRY", "DEED_REGISTRY"], headers=REVIEWER_2
    )

    approval = f.approve_determination(parcel["version"])
    response = api.determine_application(application["id"], approval, REVIEWER)
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    assert ERR_UNAUTHORIZED_ROLE not in response.text, (
        "the caller holds an authorised role and is barred only by his identity, so "
        f"the refusal must not be the role gate: {response.text}"
    )

    barred = validate_success(api.get_application(application["id"], CLERK))
    assert barred["status"] == "UNDER_REVIEW", (
        f"the refused determination applied nothing, got {barred['status']}"
    )
    assert barred["determined_by_user_id"] is None, (
        f"and stamped nobody, got {barred['determined_by_user_id']!r}"
    )
    assert barred["resulting_grant_id"] is None, (
        f"and minted nothing, got {barred['resulting_grant_id']!r}"
    )
    untouched_parcel = validate_success(api.get_parcel(parcel["id"], ANALYST))
    assert untouched_parcel["version"] == 1, (
        f"the parcel decomposition never re-ran, got version {untouched_parcel['version']}"
    )

    # The colleague sends the identical body and it is honoured.
    decided = validate_success(
        api.determine_application(application["id"], approval, REVIEWER_2)
    )
    assert decided["status"] == "APPROVED", (
        f"a different identity may determine the claim, got {decided['status']}"
    )
    assert decided["determined_by_user_id"] == REVIEWER_2_USER_ID, (
        f"the colleague becomes the recorded decider, got {decided['determined_by_user_id']!r}"
    )

    assert_grant(
        validate_success(api.get_grant(decided["resulting_grant_id"], REVIEWER)),
        benefit_status="ACTIVE",
        benefit_amount_cents=8400000,
        applied_exempt_value_cents=8400000,
    )
    parcel_after = validate_success(api.get_parcel(parcel["id"], ANALYST))
    assert parcel_after["version"] == 2, (
        f"the approval is the parcel's second mutation, got {parcel_after['version']}"
    )
    assert_parcel_decomposition(
        parcel_after,
        assessed_value_cents=33600000,
        exempt_value_cents=8400000,
        taxable_value_cents=25200000,
        exemption_status="PARTIALLY_EXEMPT",
    )


def test_the_reviewer_who_approved_the_claim_cannot_approve_its_refund(api):
    """PRD §2.8: "Deciding a retroactive claim is barred to the reviewer who determined
    the application behind the claimed grant: the acting identifier is compared against
    the `determined_by_user_id` of that application." PRD §3.7 fixes the money the
    colleague's decision produces: "for each year, the refundable remainder multiplied
    by the refund interest rate of 400 basis points per year — four percent —
    multiplied by the number of years between that tax year and the
    `filing_tax_year`, divided by ten thousand, and rounded half up to a whole cent,
    with each year rounded before summing." PRD §2.11: "`lifetime_refund_cents`
    accumulates the `total_payable_cents` of that taxpayer's approved retroactive
    claims".

    Design: Corner/rbac/reviewer_who_determined_the_application_cannot_decide_its_retroactive_claim
    """
    world = fx.approved_homestead_world(api)
    taxpayer_id = world["taxpayer"]["id"]
    claim = fx.pending_claim(api, world["grant_id"])
    assert_claim_amounts(
        claim,
        gross_refund_cents=315000,
        offset_applied_cents=0,
        net_refund_cents=0,
        refund_interest_cents=0,
        total_payable_cents=0,
        status="PENDING",
    )

    decision = f.claim_decision("APPROVE", "Verified against the roll.")
    response = api.decide_retroactive_claim(claim["id"], decision, REVIEWER)
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    assert ERR_UNAUTHORIZED_ROLE not in response.text, (
        "the barred identity holds the authorised role, so the refusal is the "
        f"duty-separation bar: {response.text}"
    )

    still_pending = validate_success(api.get_retroactive_claim(claim["id"], REVIEWER))
    assert_claim_amounts(
        still_pending,
        net_refund_cents=0,
        total_payable_cents=0,
        status="PENDING",
    )

    # The bar is stored on the application, not on the claim, so a colleague who
    # never touched either may decide it.
    approved = validate_success(
        api.decide_retroactive_claim(claim["id"], decision, REVIEWER_2)
    )
    assert_claim_amounts(
        approved,
        gross_refund_cents=315000,
        offset_applied_cents=0,
        net_refund_cents=315000,
        refund_interest_cents=25200,
        total_payable_cents=340200,
        status="APPROVED",
    )

    account = validate_success(api.get_taxpayer_account(taxpayer_id, CLERK))
    assert_taxpayer_ledger(
        account,
        lifetime_refund_cents=340200,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=340200,
    )


def test_an_undeclared_role_is_turned_away_before_the_row_is_even_looked_up(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity in which that user is
    acting. A request missing either header, or presenting an `X-User-Role` that is not
    one of the nine roles enumerated below, is rejected with `ERR_UNAUTHENTICATED`."
    PRD §2.10 rung 1: "Header presence and role validity — `ERR_UNAUTHENTICATED`.
    Applies to every endpoint."

    Design: Corner/rbac/unregistered_role_header_is_unauthenticated
    """
    fx.set_clock(api)
    parcel = fx.create_parcel(api, f.parcel())
    assert "CountyTreasurer" not in ROLES, (
        "the caller under test must name a capacity the county does not recognise"
    )

    validate_error(
        api.get_parcel(parcel["id"], UNREGISTERED_ROLE),
        ERR_UNAUTHENTICATED,
        expected_status=401,
    )
    validate_error(
        api.get_parcel(parcel["id"], NO_AUTH_HEADERS),
        ERR_UNAUTHENTICATED,
        expected_status=401,
    )

    # The identity gate answers even though the addressed parcel does not exist.
    response = api.get_parcel(NON_EXISTENT_UUID, UNREGISTERED_ROLE)
    validate_error(response, ERR_UNAUTHENTICATED, expected_status=401)
    assert ERR_PARCEL_NOT_FOUND not in response.text, (
        "the identity gate is consulted before the row is looked up, so a missing "
        f"parcel must not be reported to an unauthenticated caller: {response.text}"
    )

    # The same path and the same parcel answer a declared role.
    readable = validate_success(api.get_parcel(parcel["id"], ANALYST))
    assert readable["apn"] == parcel["apn"], (
        f"the path and the parcel were valid throughout, got {readable['apn']!r}"
    )
    assert_parcel_decomposition(
        readable,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )
