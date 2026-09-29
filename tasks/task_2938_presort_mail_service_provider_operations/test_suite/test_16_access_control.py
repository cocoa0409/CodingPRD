"""Who may act, who may not, and whose records they may reach.

Authority in this API is settled by two headers, and the four things they decide
are exercised separately here: whether the caller is identified at all, whether
the role is permitted on the endpoint addressed, whether an entity-backed mail
owner is inside its own tenancy, and whether the human closing a statement is a
different human from the one who filed it. Each denial is checked for its own
code and its own status, and for having written nothing at all.
"""

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
    ERR_CLIENT_SCOPE_VIOLATION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_batch_ledger,
    assert_field_values,
    assert_job_state,
    assert_permit_funds,
    assert_row_count,
    assert_statement_figures,
)
from test_helpers.constants import FIXTURE_CLOCK_UTC, ROLE_BUREAU_ADMIN
from test_helpers.test_users import (
    ACCEPTANCE_CLERK,
    ACCEPTANCE_CLERK_USER_ID,
    BUREAU_ADMIN,
    NO_HEADERS,
    POSTAGE_MANAGER,
    POSTAGE_MANAGER_USER_ID,
    PRESORT_OPERATOR,
    headers_empty_role,
    headers_empty_user_id,
    headers_missing_role,
    headers_missing_user_id,
    make_acceptance_clerk_headers,
    make_client_contact_headers,
)


class TestExclusiveOperationsPerRole:
    """The happy path spans four roles and no one of them can drive it alone."""

    def test_each_role_runs_its_own_surface_of_the_mailing(self, api):
        """Onboarding, production, postage and acceptance are four separate hands.

        "A `PresortOperator` runs the production floor — address hygiene and move
        update, pooling jobs into commingle batches, building trays and pallets,
        closing sortation, and booking and dispatching drop shipments. A
        `PostageManager` owns postage and money: opening and funding permit accounts,
        changing permit account status, and preparing, submitting, revising and
        voiding postage statements, plus issuing client invoices and recording
        payments. An `AcceptanceClerk` represents the postal acceptance unit:
        recording verification findings, closing verification with an accept or a
        return, receiving the deposit at the dock, and recording the delivery scan."
        The audit trail is written from the acting identity: "Filing sets
        `submitted_by_user_id` to the acting `X-User-ID`", and for a finding "The
        clerk's `X-User-ID` is stamped into `assessed_by_user_id`".

        Design: Corner/rbac/exclusive_operations_each_role_runs_its_own_surface
        """
        world = fx.build_submitted_world(api)

        filed = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert_statement_figures(
            filed,
            status="SUBMITTED",
            declared_postage_cents=fx.POOLED_POSTAGE_CENTS,
            adjustment_cents=0,
            verified_postage_cents=0,
            verification_error_count=0,
        )
        assert filed["submitted_by_user_id"] == POSTAGE_MANAGER_USER_ID

        finding = validate_success(
            api.create_finding(
                world.statement_id,
                f.finding_payload(finding_type="SHORT_PAID", affected_piece_count=120),
                ACCEPTANCE_CLERK,
            ),
            expected_status=201,
        )
        assert finding["id"]
        assert_field_values(
            finding,
            {
                "finding_type": "SHORT_PAID",
                "affected_piece_count": 120,
                "assessed_by_user_id": ACCEPTANCE_CLERK_USER_ID,
            },
        )

        annotated = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert annotated["verification_error_count"] == 1
        assert annotated["status"] == "SUBMITTED"
        assert annotated["submitted_by_user_id"] == POSTAGE_MANAGER_USER_ID

        listed, meta = validate_paginated(
            api.list_findings(world.statement_id, BUREAU_ADMIN)
        )
        assert_row_count(listed, 1, "verification findings")
        assert meta["total_count"] == 1
        assert listed[0]["id"] == finding["id"]


def _build_role_denial_world(api):
    """Client RBAC1 with an ACTIVE permit account, one hygiene-cleared 1000-piece
    LETTERS job, and one OPEN LETTERS batch with nothing in it yet."""
    world = fx.World()
    fx.set_clock(api, FIXTURE_CLOCK_UTC)
    account = fx.setup_client_with_permit(
        api,
        name="Role Test Mail",
        client_code="RBAC1",
        permit_number="PI-420420",
        payment_method="METER",
    )
    world.client = account.client
    world.client_id = account.client_id
    world.permit = account.permit
    world.permit_id = account.permit_id
    world.facility = fx.setup_facility(api)
    world.facility_id = world.facility["id"]
    cleared = fx.setup_cleared_job(
        api, world.client_id, world.permit_id, declared_piece_count=1000
    )
    world.job = cleared.job
    world.job_id = cleared.job_id
    world.batch = fx.create_batch(api, f.commingle_batch_payload(world.facility_id))
    world.batch_id = world.batch["id"]
    return world


def _admin_closes_sortation(api, world):
    return api.sort_batch(world.batch_id, BUREAU_ADMIN)


def _operator_opens_a_permit_account(api, world):
    return api.create_permit_account(
        f.permit_account_payload(
            world.client_id, permit_number="PI-430430", payment_method="METER"
        ),
        PRESORT_OPERATOR,
    )


def _clerk_pools_a_job(api, world):
    return api.add_batch_member(
        world.batch_id, f.batch_member_payload(world.job_id), ACCEPTANCE_CLERK
    )


def _postage_manager_suspends_a_client(api, world):
    return api.set_client_status(
        world.client_id,
        f.client_status_payload("SUSPENDED", reason="not my job"),
        POSTAGE_MANAGER,
    )


CROSS_ROLE_DENIALS = [
    ("bureau_admin_closing_sortation", _admin_closes_sortation),
    ("presort_operator_opening_a_permit_account", _operator_opens_a_permit_account),
    ("acceptance_clerk_pooling_a_job", _clerk_pools_a_job),
    ("postage_manager_suspending_a_client", _postage_manager_suspends_a_client),
]


class TestCrossRoleOperationsAreUnauthorized:
    """Role checks are per endpoint, and seniority buys nothing."""

    @pytest.mark.parametrize(
        "case_name, attempt",
        CROSS_ROLE_DENIALS,
        ids=[row[0] for row in CROSS_ROLE_DENIALS],
    )
    def test_a_role_outside_the_endpoints_list_is_refused(self, api, case_name, attempt):
        """Each of these four callers holds a real role, just not this endpoint's.

        "Five roles exist, and their names are spelled exactly as follows:
        `ClientContact`, `PresortOperator`, `PostageManager`, `AcceptanceClerk`, and
        `BureauAdmin`. If `X-User-Role` holds any string outside that set of five, or
        holds one of the five but that role is not among the roles authorized for the
        endpoint being addressed, the request is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)." There is no hierarchy to fall back on: "`BureauAdmin` does not
        run production, postage or acceptance actions."

        Design: Corner/rbac/denial_cross_role_exclusive_operations_are_unauthorized
        """
        world = _build_role_denial_world(api)

        validate_error(attempt(api, world), ERR_UNAUTHORIZED, expected_status=403)

    def test_the_role_check_precedes_every_state_and_business_rule(self, api):
        """An empty batch would fail sortation anyway, but not with this code.

        "**Role recognized and permitted** — `X-User-Role` is one of the five declared
        roles and that role appears in the target endpoint's authorized role list.
        Violation: `ERR_UNAUTHORIZED` (403). Applies to every endpoint." The order is
        binding: "The server therefore evaluates checks in one fixed, strictly
        ascending order and returns the error of the **first** rule violated; no later
        rule can mask an earlier one, and no earlier rule can be skipped because a
        later one also fails." Sortation's own gate would otherwise speak here,
        because "a batch whose `member_job_count` or `container_count` is 0 is refused
        with `ERR_BATCH_HAS_NO_CONTAINERS`".

        Design: Corner/rbac/denial_cross_role_exclusive_operations_are_unauthorized
        """
        world = _build_role_denial_world(api)

        for _case_name, attempt in CROSS_ROLE_DENIALS:
            validate_error(attempt(api, world), ERR_UNAUTHORIZED, expected_status=403)

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert batch["status"] == "OPEN"
        assert_batch_ledger(
            batch, member_job_count=0, total_piece_count=0, container_count=0
        )

        accounts, meta = validate_paginated(
            api.list_client_permit_accounts(world.client_id, POSTAGE_MANAGER)
        )
        assert_row_count(accounts, 1, "permit accounts")
        assert meta["total_count"] == 1
        assert accounts[0]["permit_number"] == "PI-420420"

        job = validate_success(api.get_mail_job(world.job_id, PRESORT_OPERATOR))
        assert_job_state(job, status="HYGIENE_CLEARED", accepted_piece_count=1000)
        assert job["commingle_batch_id"] is None

        client = validate_success(api.get_client(world.client_id, BUREAU_ADMIN))
        assert client["status"] == "ACTIVE"
        assert client["suspension_reason"] is None


class TestSegregationOfDutiesOnTheFilingIdentity:
    """The clerk who signs a statement off must be a different human."""

    def test_the_filer_cannot_annotate_or_close_their_own_statement(self, api):
        """Holding both roles does not let one identity do both jobs.

        "The acceptance unit exists to check the bureau's own work, so the system
        enforces that the human who files a postage statement can never be the human
        who signs it off. When a finding is recorded against a statement, or when
        verification is closed, the acting `X-User-ID` is compared to the statement's
        `submitted_by_user_id`; if they are equal, the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The role check is separate and comes
        first: only an `AcceptanceClerk` may perform either action at all, and only a
        `PostageManager` can have filed the statement — but a bureau where one person
        holds both roles must still use two distinct user identifiers."

        Design: Corner/rbac/segregation_of_duties_filer_cannot_verify_own_statement
        """
        world = fx.build_submitted_world(api)
        the_filer_wearing_the_clerks_hat = make_acceptance_clerk_headers(
            POSTAGE_MANAGER_USER_ID
        )

        validate_error(
            api.create_finding(
                world.statement_id,
                f.finding_payload(finding_type="SHORT_PAID", affected_piece_count=120),
                the_filer_wearing_the_clerks_hat,
            ),
            ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )
        after_finding = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert after_finding["verification_error_count"] == 0
        listed, meta = validate_paginated(
            api.list_findings(world.statement_id, BUREAU_ADMIN)
        )
        assert_row_count(listed, 0, "verification findings")
        assert meta["total_count"] == 0

        validate_error(
            api.verify_postage_statement(
                world.statement_id,
                f.verify_payload("ACCEPT"),
                the_filer_wearing_the_clerks_hat,
            ),
            ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )
        still_open = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert_statement_figures(
            still_open,
            status="SUBMITTED",
            declared_postage_cents=fx.POOLED_POSTAGE_CENTS,
            adjustment_cents=0,
            verified_postage_cents=0,
            verification_error_count=0,
        )
        assert still_open["verified_by_user_id"] is None
        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit,
            balance_cents=fx.HOUSE_FUNDING_CENTS - fx.POOLED_POSTAGE_CENTS,
            reserved_cents=fx.POOLED_POSTAGE_CENTS,
        )

    def test_a_second_identity_in_the_same_role_closes_it(self, api):
        """The rule compares identities, so a colleague's user id passes.

        "An `AcceptanceClerk` closes verification on a statement in `SUBMITTED` by
        supplying an `outcome` of either `ACCEPT` or `RETURN`. The acting `X-User-ID`
        must differ from `submitted_by_user_id`. All three branches set
        `verified_by_user_id` to the acting `X-User-ID`". With no findings recorded,
        "When the outcome is `ACCEPT` and the pinned walk resolves `adjustment_cents`
        to exactly 0, the statement moves `SUBMITTED → ACCEPTED_CLEAN`."

        Design: Corner/rbac/segregation_of_duties_filer_cannot_verify_own_statement
        """
        world = fx.build_submitted_world(api)

        validate_error(
            api.verify_postage_statement(
                world.statement_id,
                f.verify_payload("ACCEPT"),
                make_acceptance_clerk_headers(POSTAGE_MANAGER_USER_ID),
            ),
            ERR_SEGREGATION_OF_DUTIES,
            expected_status=403,
        )

        closed = validate_success(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("ACCEPT"), ACCEPTANCE_CLERK
            )
        )
        assert_statement_figures(
            closed,
            status="ACCEPTED_CLEAN",
            declared_postage_cents=fx.POOLED_POSTAGE_CENTS,
            adjustment_cents=0,
            verified_postage_cents=fx.POOLED_POSTAGE_CENTS,
            verification_error_count=0,
        )
        assert closed["verified_by_user_id"] == ACCEPTANCE_CLERK_USER_ID
        assert closed["submitted_by_user_id"] == POSTAGE_MANAGER_USER_ID

        reread = validate_success(
            api.get_postage_statement(world.statement_id, BUREAU_ADMIN)
        )
        assert reread["verified_by_user_id"] == ACCEPTANCE_CLERK_USER_ID
        assert reread["submitted_by_user_id"] == POSTAGE_MANAGER_USER_ID


def _build_two_tenant_world(api):
    """Clients SELFC and RIVAL, each with its own ACTIVE permit account, where
    RIVAL owns one tendered 900-piece LETTERS job and SELFC owns nothing."""
    world = fx.World()
    fx.set_clock(api, FIXTURE_CLOCK_UTC)
    mine = fx.setup_client_with_permit(
        api,
        name="Self Serve Mailing",
        client_code="SELFC",
        permit_number="PI-440440",
        payment_method="METER",
    )
    theirs = fx.setup_client_with_permit(
        api,
        name="Rival Direct Mail",
        client_code="RIVAL",
        permit_number="PI-450450",
        payment_method="METER",
    )
    world.self_id = mine.client_id
    world.self_permit_id = mine.permit_id
    world.rival_id = theirs.client_id
    world.rival_permit_id = theirs.permit_id
    world.rival_job = fx.create_mail_job(
        api,
        f.mail_job_payload(
            world.rival_id, world.rival_permit_id, declared_piece_count=900
        ),
    )
    world.rival_job_id = world.rival_job["id"]
    return world


class TestClientContactStaysInsideItsOwnTenancy:
    """The same read succeeds for one's own client and is refused for another's."""

    def test_a_mail_owner_reads_its_own_record_and_not_its_rivals(self, api):
        """One identity, one client, and the addressed id decides the answer.

        "When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting
        `Client`; ownership checks on any resource that references a `Client` compare
        the resource's client foreign-key field to `X-User-ID`. Concretely, a
        `ClientContact` may read a client record, its permit-account list, its
        mail-job list, its invoice list and its service-level index only when the
        addressed client `id` equals `X-User-ID`". "Any violation is rejected with
        `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/denial_client_contact_cannot_reach_another_clients_records
        """
        world = _build_two_tenant_world(api)
        me = make_client_contact_headers(world.self_id)

        own = validate_success(api.get_client(world.self_id, me))
        assert own["client_code"] == "SELFC"
        assert own["id"] == world.self_id

        validate_error(
            api.get_client(world.rival_id, me),
            ERR_CLIENT_SCOPE_VIOLATION,
            expected_status=403,
        )
        validate_error(
            api.list_client_mail_jobs(world.rival_id, me),
            ERR_CLIENT_SCOPE_VIOLATION,
            expected_status=403,
        )
        validate_error(
            api.list_client_permit_accounts(world.rival_id, me),
            ERR_CLIENT_SCOPE_VIOLATION,
            expected_status=403,
        )

    def test_the_scope_reaches_through_a_jobs_owner_and_through_a_request_body(
        self, api
    ):
        """Tenancy is resolved from the resource, not from the path shape.

        A `ClientContact` "may read a mail job, that job's hygiene runs and that job's
        standalone postage estimate only when the job's `client_id` equals
        `X-User-ID`; and may tender a new mail job only when the `client_id` in the
        request body equals `X-User-ID`. Any violation is rejected with
        `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403)." The rung is declared over both
        shapes: "**Client scope** — a `ClientContact` acts only within its own client,
        as described in §2.1. Violation: `ERR_CLIENT_SCOPE_VIOLATION` (403). Applies
        to `GET /clients/{id}`, `GET /clients/{id}/mail-jobs`,
        `GET /clients/{id}/permit-accounts`, `GET /clients/{id}/invoices`,
        `GET /clients/{id}/service-level`, `GET /mail-jobs/{id}`,
        `GET /mail-jobs/{id}/postage-estimate`, `GET /mail-jobs/{id}/hygiene-runs` and
        `POST /mail-jobs`."

        Design: Corner/rbac/denial_client_contact_cannot_reach_another_clients_records
        """
        world = _build_two_tenant_world(api)
        me = make_client_contact_headers(world.self_id)

        validate_error(
            api.get_mail_job(world.rival_job_id, me),
            ERR_CLIENT_SCOPE_VIOLATION,
            expected_status=403,
        )
        validate_error(
            api.get_postage_estimate(world.rival_job_id, me),
            ERR_CLIENT_SCOPE_VIOLATION,
            expected_status=403,
        )
        validate_error(
            api.create_mail_job(
                f.mail_job_payload(
                    world.rival_id,
                    world.rival_permit_id,
                    declared_piece_count=100,
                    declared_weight_oz_per_piece=1.0,
                ),
                me,
            ),
            ERR_CLIENT_SCOPE_VIOLATION,
            expected_status=403,
        )

        rival_jobs, meta = validate_paginated(
            api.list_client_mail_jobs(world.rival_id, POSTAGE_MANAGER)
        )
        assert_row_count(rival_jobs, 1, "the rival's mail jobs")
        assert meta["total_count"] == 1
        assert rival_jobs[0]["id"] == world.rival_job_id
        assert rival_jobs[0]["declared_piece_count"] == 900


NOHDR_CLIENT = f.client_payload(
    name="No Headers Mail",
    client_code="NOHDR",
    service_fee_rate_per_thousand_cents=1000,
)

BOTH_HEADERS_BLANK = {
    "X-User-ID": "",
    "X-User-Role": "",
    "Content-Type": "application/json",
}

BLANK_IDENTITIES = [
    ("role_header_absent", headers_missing_role()),
    ("user_id_header_absent", headers_missing_user_id(ROLE_BUREAU_ADMIN)),
    ("role_header_blank", headers_empty_role()),
    ("user_id_header_blank", headers_empty_user_id(ROLE_BUREAU_ADMIN)),
    ("both_headers_absent", NO_HEADERS),
    ("both_headers_blank", BOTH_HEADERS_BLANK),
]


class TestUnidentifiedCallersAreRefusedFirst:
    """A blank identity is an absent one, and it is settled before anything else."""

    @pytest.mark.parametrize(
        "case_name, headers",
        BLANK_IDENTITIES,
        ids=[row[0] for row in BLANK_IDENTITIES],
    )
    def test_an_absent_or_blank_identity_header_is_unauthenticated(
        self, api, case_name, headers
    ):
        """Neither header may be missing and neither may be blank.

        "If either header is absent, empty, or consists only of whitespace, the request
        is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A header containing only
        spaces or tabs counts as absent; it is not treated as a valid identifier. This
        check runs before anything else, including body parsing and path resolution."

        Design: Corner/rbac/unauthenticated_missing_or_whitespace_only_identity_headers
        """
        validate_error(
            api.create_client(NOHDR_CLIENT, headers),
            ERR_UNAUTHENTICATED,
            expected_status=401,
        )

    def test_a_blank_role_is_not_an_unrecognized_role(self, api):
        """401 and not 403: the blank is missing, not merely wrong.

        "**Headers present** — `X-User-Role` and `X-User-ID` are both present and
        non-empty, treating a whitespace-only header as absent. Violation:
        `ERR_UNAUTHENTICATED` (401). Applies to every endpoint." Only afterwards does
        the ladder ask "**Role recognized and permitted** — `X-User-Role` is one of the
        five declared roles and that role appears in the target endpoint's authorized
        role list. Violation: `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

        Design: Corner/rbac/unauthenticated_missing_or_whitespace_only_identity_headers
        """
        validate_error(
            api.create_client(NOHDR_CLIENT, headers_empty_role()),
            ERR_UNAUTHENTICATED,
            expected_status=401,
        )
        validate_error(
            api.create_client(NOHDR_CLIENT, headers_missing_role()),
            ERR_UNAUTHENTICATED,
            expected_status=401,
        )

    def test_the_identity_check_precedes_path_resolution_and_body_parsing(self, api):
        """An unknown id and a malformed body both stay hidden behind the 401.

        "This check runs before anything else, including body parsing and path
        resolution." The ladder makes the ordering binding: "The server therefore
        evaluates checks in one fixed, strictly ascending order and returns the error
        of the **first** rule violated; no later rule can mask an earlier one, and no
        earlier rule can be skipped because a later one also fails." Both of the rungs
        being suppressed here would otherwise speak: "**Request shape** — the body
        parses, contains every field the endpoint requires ... Violation:
        `ERR_INVALID_REQUEST` (400)", and "**Path identifiers resolve** — every
        identifier in the URL path resolves to an existing row".

        Design: Corner/rbac/unauthenticated_missing_or_whitespace_only_identity_headers
        """
        validate_error(
            api.get_client(NON_EXISTENT_UUID, BOTH_HEADERS_BLANK),
            ERR_UNAUTHENTICATED,
            expected_status=401,
        )
        validate_error(
            api.create_client({"client_code": "NOHDR"}, BOTH_HEADERS_BLANK),
            ERR_UNAUTHENTICATED,
            expected_status=401,
        )

    def test_none_of_the_refused_calls_wrote_a_client(self, api):
        """The client code is still free afterwards, so nothing was persisted.

        Registration takes "a short operator-facing `client_code` of 2 to 16 characters
        drawn only from uppercase letters and digits, which must be globally unique
        across all clients; a collision is rejected with `ERR_DUPLICATE_CLIENT_CODE`."
        Had any refused call landed, this one could not: "**Client code uniqueness** —
        the supplied `client_code` is not already held by another `Client`. Violation:
        `ERR_DUPLICATE_CLIENT_CODE` (409). Applies to `POST /clients`." A fresh row is
        recognisable: "A newly registered client opens in `ACTIVE` status with
        `suspension_reason` null".

        Design: Corner/rbac/unauthenticated_missing_or_whitespace_only_identity_headers
        """
        for _case_name, headers in BLANK_IDENTITIES:
            validate_error(
                api.create_client(NOHDR_CLIENT, headers),
                ERR_UNAUTHENTICATED,
                expected_status=401,
            )
        validate_error(
            api.create_client({"client_code": "NOHDR"}, BOTH_HEADERS_BLANK),
            ERR_UNAUTHENTICATED,
            expected_status=401,
        )

        created = validate_success(
            api.create_client(NOHDR_CLIENT, BUREAU_ADMIN), expected_status=201
        )
        assert_field_values(
            created,
            {
                "client_code": "NOHDR",
                "name": "No Headers Mail",
                "status": "ACTIVE",
            },
        )
        assert created["suspension_reason"] is None
