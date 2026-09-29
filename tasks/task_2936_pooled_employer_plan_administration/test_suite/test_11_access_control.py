"""Identity, role and ownership: the four outermost rungs of the rejection ladder."""

from typing import Any, Dict

import requests

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_ADOPTING_EMPLOYER_NOT_FOUND,
    ERR_DESIGN_ELECTION_NOT_FOUND,
    ERR_FIDUCIARY_ALLOCATION_NOT_FOUND,
    ERR_MISSING_AUTH_HEADERS,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PAYROLL_BATCH_NOT_FOUND,
    ERR_PLAN_DOCUMENT_NOT_FOUND,
    ERR_PLAN_FILING_NOT_FOUND,
    ERR_PLAN_PROVIDER_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_UNKNOWN_ROLE,
)
from test_helpers.assertions import (
    assert_fields,
    assert_request_meta,
    assert_same_object,
    ids_of,
    validate_collection,
    validate_created,
    validate_single,
)
from test_helpers.fixtures import EmployerContext, PlanContext
from test_helpers.test_users import (
    UNRESOLVABLE_ALLOCATION_ID,
    UNRESOLVABLE_BATCH_ID,
    UNRESOLVABLE_DEPOSIT_ID,
    UNRESOLVABLE_ELECTION_ID,
    UNRESOLVABLE_EMPLOYER_ID,
    UNRESOLVABLE_FILING_ID,
    UNRESOLVABLE_PLAN_DOCUMENT_ID,
    UNRESOLVABLE_PLAN_PROVIDER_ID,
    UNRESOLVABLE_PROVIDER_ID,
    UNRESOLVABLE_SERVICE_PROVIDER_ID,
    UNRESOLVABLE_TRANSFER_ID,
    auditor_headers,
    employer_headers,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    no_headers,
    plan_provider_headers,
    regulator_headers,
    service_provider_headers,
)
from prd_bench_local_runner.testing import validate_error

# A role name that is not one of the five, and a real role name in the wrong case.
UNKNOWN_ROLE_NAME = "PlanAuditor"
LOWER_CASED_ROLE_NAME = "regulatorops"

# A body that is malformed twice over, used to prove the body is never read for
# meaning before the caller has been identified.
MALFORMED_PAY_PERIOD_START = "not-a-date"
MALFORMED_COMPENSATION_CENTS = -1

# The names an actor reaches for when it tries to act on somebody else's row.
SELF_VALIDATION_NOTE = "Self-validated by the employer."
SELF_POSTING_REFERENCE = "SELF-POST-1"
SPOOFED_PAYROLL_REFERENCE = "QRY-SPOOF-1"
SPOOFED_DEPOSIT_REFERENCE = "QRY-SPOOF-WIRE"
CROSS_PLAN_ACKNOWLEDGMENT = "Ellery accepts the function."

# A pay period that does not touch the incumbent batch's period, so a refusal
# cannot be blamed on an overlap.
SPOOF_PAY_PERIOD_START = "2026-08-01"
SPOOF_PAY_PERIOD_END = "2026-08-15"
SPOOF_PAY_DATE = "2026-08-18"
SPOOF_WITHHOLDING_DATE = "2026-08-18"

# The second employer's own, perfectly legitimate payroll.
QUARRY_COMPENSATION_CENTS = 60000000
QUARRY_DEFERRAL_CENTS = 2700000
QUARRY_MATCH_CENTS = 2250000
QUARRY_BATCH_TOTAL_CENTS = 4950000
QUARRY_PARTICIPANT_LINES = 15

# An employer the second sponsor tries to onboard onto a plan it does not own.
BRACKENHALL_LEGAL_NAME = "Brackenhall Plastics Ltd"
BRACKENHALL_EIN = "420000049"


def _assert_error_envelope(response: requests.Response, expected_error_id: str) -> None:
    """Assert an error body carries the standard envelope and nothing else."""
    meta = assert_request_meta(response)
    body = response.json()
    assert body["response_type"] == "error", (
        f"Expected response_type 'error', got {body['response_type']!r}"
    )
    assert sorted(meta) == ["api_request_id", "api_request_timestamp"], (
        f"An error envelope's meta carries only the two request fields, got {meta}"
    )
    data = body["data"]
    assert data["error_id"] == expected_error_id, (
        f"Expected error_id {expected_error_id!r}, got {data['error_id']!r}"
    )
    assert isinstance(data["message"], str) and data["message"].strip(), (
        f"An error body must carry a human-readable message, got {data.get('message')!r}"
    )
    assert sorted(data) == ["error_id", "message"], (
        f"An error body carries no resource fields, got {sorted(data)}"
    )


def _malformed_batch_payload() -> Dict[str, Any]:
    """A payroll delivery whose body is wrong in two independent ways."""
    return f.payroll_batch_payload(
        UNRESOLVABLE_EMPLOYER_ID,
        pay_period_start=MALFORMED_PAY_PERIOD_START,
        total_eligible_compensation_cents=MALFORMED_COMPENSATION_CENTS,
    )


def test_a_request_without_a_usable_identity_never_reaches_its_target(api: ApiClient):
    """
    Missing, empty and unrecognised identities are all answered at the outermost
    layer, so the reply cannot be told apart by what the request was aimed at: a
    malformed body, an unauthorised endpoint and an unresolvable id all come back
    401 until the headers are right, and only then does the lookup happen.

    "Every request to the API must carry two headers: `X-User-ID`, identifying the
    acting principal, and `X-User-Role`, declaring the capacity in which it acts."

    "If either header is absent, or is present with an empty-string value, the
    request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401); an empty string
    counts as absent, not as a value."

    "If `X-User-Role` carries anything other than one of the five declared roles, the
    request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401)."

    "The five roles are, with exact spelling: `RegulatorOps`, `PooledPlanProvider`,
    `AdoptingEmployer`, `ServiceProvider`, and `IndependentAuditor`."

    "Priorities 1 through 4 are authentication and authorisation, in this order:
    `ERR_MISSING_AUTH_HEADERS`, `ERR_UNKNOWN_ROLE`, `ERR_UNAUTHORIZED`,
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/corner_rbac_missing_auth_header_or_unknown_role_rejected_before_everything
    """
    for headers, case in (
        (headers_with_empty_role(UNRESOLVABLE_EMPLOYER_ID), "an empty role"),
        (headers_with_empty_user_id(k.ROLE_REGULATOR_OPS), "an empty user id"),
        (headers_without_role(UNRESOLVABLE_EMPLOYER_ID), "no role header at all"),
        (headers_without_user_id(k.ROLE_REGULATOR_OPS), "no user id header at all"),
        (no_headers(), "neither identity header"),
    ):
        response = api.get_plan_provider(UNRESOLVABLE_PROVIDER_ID, headers)
        validate_error(response, ERR_MISSING_AUTH_HEADERS, expected_status=401)
        _assert_error_envelope(response, ERR_MISSING_AUTH_HEADERS)
        assert response.status_code == 401, f"{case} must be answered 401"

    unidentified_write = api.create_plan_provider(
        f.plan_provider_payload(), no_headers()
    )
    validate_error(unidentified_write, ERR_MISSING_AUTH_HEADERS, expected_status=401)

    unidentified_malformed = api.create_payroll_batch(
        _malformed_batch_payload(), headers_with_empty_role(UNRESOLVABLE_EMPLOYER_ID)
    )
    validate_error(unidentified_malformed, ERR_MISSING_AUTH_HEADERS, expected_status=401)
    _assert_error_envelope(unidentified_malformed, ERR_MISSING_AUTH_HEADERS)

    for role_name in (UNKNOWN_ROLE_NAME, LOWER_CASED_ROLE_NAME):
        response = api.create_plan_provider(
            f.plan_provider_payload(), headers_with_unknown_role(role_name)
        )
        validate_error(response, ERR_UNKNOWN_ROLE, expected_status=401)
        _assert_error_envelope(response, ERR_UNKNOWN_ROLE)

    on_a_role_exclusive_endpoint = api.file_plan_filing(
        UNRESOLVABLE_FILING_ID, headers_with_unknown_role(UNKNOWN_ROLE_NAME)
    )
    validate_error(on_a_role_exclusive_endpoint, ERR_UNKNOWN_ROLE, expected_status=401)

    resolved_at_last = api.get_plan_provider(
        UNRESOLVABLE_PROVIDER_ID, regulator_headers()
    )
    validate_error(resolved_at_last, ERR_PLAN_PROVIDER_NOT_FOUND, expected_status=404)
    _assert_error_envelope(resolved_at_last, ERR_PLAN_PROVIDER_NOT_FOUND)


def test_each_entity_family_answers_an_unknown_path_id_with_its_own_not_found(
    api: ApiClient
):
    """
    The same well-formed but unresolvable identifier produces five different error
    ids on an empty database, chosen only by the collection the path names.

    "Identifiers in a path are resolved strictly left to right, and the first
    identifier that does not resolve produces that entity's own not-found error
    before any later identifier, body field, state condition or business rule is
    considered"

    "no ownership check narrows what a `RegulatorOps` caller may reach"

    "The `error_id` is a unique, machine-readable string that identifies the specific
    error."

    Design: Corner/errors/corner_unresolvable_path_ids_return_family_specific_not_found
    """
    cases = (
        (
            api.get_fiduciary_role_allocation(
                UNRESOLVABLE_ALLOCATION_ID, regulator_headers()
            ),
            ERR_FIDUCIARY_ALLOCATION_NOT_FOUND,
        ),
        (
            api.get_adopting_employer(UNRESOLVABLE_EMPLOYER_ID, regulator_headers()),
            ERR_ADOPTING_EMPLOYER_NOT_FOUND,
        ),
        (
            api.get_design_election(UNRESOLVABLE_ELECTION_ID, regulator_headers()),
            ERR_DESIGN_ELECTION_NOT_FOUND,
        ),
        (
            api.get_payroll_batch(UNRESOLVABLE_BATCH_ID, regulator_headers()),
            ERR_PAYROLL_BATCH_NOT_FOUND,
        ),
        (
            api.get_plan_filing(UNRESOLVABLE_FILING_ID, regulator_headers()),
            ERR_PLAN_FILING_NOT_FOUND,
        ),
    )
    for response, expected_error_id in cases:
        validate_error(response, expected_error_id, expected_status=404)
        _assert_error_envelope(response, expected_error_id)

    reported = [response.json()["data"]["error_id"] for response, _ in cases]
    assert len(set(reported)) == len(cases), (
        f"Each family owns its own not-found error id, got {reported}"
    )


def test_a_write_reserved_to_one_role_is_closed_to_all_the_others(api: ApiClient):
    """
    Fourteen mutations, each reserved to a single role, are attempted by a
    syntactically valid role that is not on the endpoint's list. Every one is
    refused with the same authorisation error even though the database is empty
    and the targets do not exist, so no path-identifier or state error can leak.

    "A syntactically valid role that is not among the roles authorised for the
    requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    "Priorities 1 through 4 are authentication and authorisation, in this order:
    `ERR_MISSING_AUTH_HEADERS`, `ERR_UNKNOWN_ROLE`, `ERR_UNAUTHORIZED`,
    `ERR_NOT_RESOURCE_OWNER`. Priority 5 is path-identifier existence and priority 6
    is body foreign-key existence, both as described in §2.8."

    "A caller who is both unauthorised for the endpoint and not the owner sees
    `ERR_UNAUTHORIZED`, never `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/corner_rbac_role_exclusive_writes_cannot_be_invoked_by_other_roles
    """
    sponsor = plan_provider_headers(UNRESOLVABLE_PLAN_PROVIDER_ID)
    adopter = employer_headers(UNRESOLVABLE_EMPLOYER_ID)
    provider = service_provider_headers(UNRESOLVABLE_SERVICE_PROVIDER_ID)

    attempts = (
        ("admit a provider to the register", api.create_plan_provider(
            f.plan_provider_payload(), sponsor)),
        ("approve a registration", api.register_plan_provider(
            UNRESOLVABLE_PROVIDER_ID, f.register_provider_payload(), sponsor)),
        ("open a plan document", api.create_plan_document(
            f.plan_document_payload(UNRESOLVABLE_PLAN_PROVIDER_ID), adopter)),
        ("approve a design election", api.approve_design_election(
            UNRESOLVABLE_ELECTION_ID, adopter)),
        ("reconcile a payroll batch", api.validate_payroll_batch(
            UNRESOLVABLE_BATCH_ID,
            f.validate_batch_payload(SELF_VALIDATION_NOTE),
            adopter,
        )),
        ("post a deposit to the trust", api.post_remittance_deposit(
            UNRESOLVABLE_DEPOSIT_ID,
            f.post_deposit_payload(SELF_POSTING_REFERENCE),
            adopter,
        )),
        ("prepare an annual return", api.prepare_plan_filing(
            UNRESOLVABLE_FILING_ID, sponsor)),
        ("attest an annual return", api.attest_plan_filing(
            UNRESOLVABLE_FILING_ID,
            f.attest_filing_payload(UNRESOLVABLE_SERVICE_PROVIDER_ID),
            sponsor,
        )),
        ("file an annual return", api.file_plan_filing(
            UNRESOLVABLE_FILING_ID, sponsor)),
        ("certify the employer data", api.certify_plan_filing_employer_data(
            UNRESOLVABLE_FILING_ID, auditor_headers())),
        ("request an exit transfer", api.create_exit_transfer(
            f.exit_transfer_payload(UNRESOLVABLE_EMPLOYER_ID), sponsor)),
        ("settle an exit transfer", api.settle_exit_transfer(
            UNRESOLVABLE_TRANSFER_ID, adopter)),
        ("issue a fee disclosure", api.create_fee_disclosure(
            f.fee_disclosure_payload(UNRESOLVABLE_PLAN_DOCUMENT_ID), provider)),
        ("move the clock", api.set_clock(k.PAYROLL_CLOCK, provider)),
    )
    for description, response in attempts:
        validate_error(response, ERR_UNAUTHORIZED, expected_status=403)
        _assert_error_envelope(response, ERR_UNAUTHORIZED)
        assert response.status_code == 403, (
            f"An attempt to {description} from the wrong role must be refused 403, "
            f"got {response.status_code}"
        )

    permitted_but_absent = api.get_plan_document(
        UNRESOLVABLE_PLAN_DOCUMENT_ID, regulator_headers()
    )
    validate_error(
        permitted_but_absent, ERR_PLAN_DOCUMENT_NOT_FOUND, expected_status=404
    )


def test_a_read_open_to_several_roles_shows_all_of_them_the_same_row(
    api: ApiClient, plan: PlanContext, employer: EmployerContext, batch: Dict[str, Any],
    audit_firm: Dict[str, Any],
):
    """
    The plan document is readable by all five roles and the payroll batch by the four
    that are listed on it, and each of them is handed byte-for-byte the same resource.
    The cross-reference listings are open to their own role sets. None of these reads
    is a mutation, so the plan's version is exactly where the reads found it.

    "The Authorized Role(s) column names the roles permitted to call the endpoint; a
    caller holding a recognised role that is not listed is rejected with
    `ERR_UNAUTHORIZED`, and a caller holding a listed but entity-backed role that does
    not own the addressed resource is rejected with `ERR_NOT_RESOURCE_OWNER`."

    "it never touches employer or contribution data, though it may read every resource
    in the domain for oversight purposes"

    "Its only mutating capability is attestation, and it may read the plan document,
    its service providers, its employers, its compliance tests and its filings."

    "`version` is an integer that starts at 1 on creation and increments by exactly one
    on every mutation, again including cascaded ones."

    Design: Corner/rbac/corner_rbac_shared_reads_are_visible_to_every_listed_role
    """
    every_role = (
        ("the regulator", regulator_headers()),
        ("the sponsor", plan.provider_headers),
        ("the employer", employer.headers),
        ("the recordkeeper", plan.recordkeeper_headers),
        ("the auditor", auditor_headers()),
    )
    reference_plan = validate_single(api.get_plan_document(plan.plan_id, regulator_headers()))
    assert_fields(reference_plan, status=k.PLAN_ACTIVE)
    for description, headers in every_role:
        seen = validate_single(api.get_plan_document(plan.plan_id, headers))
        assert_same_object(seen, reference_plan)
        assert seen["id"] == plan.plan_id, f"{description} read the wrong plan document"

    reference_batch = validate_single(
        api.get_payroll_batch(batch["id"], regulator_headers())
    )
    assert_fields(reference_batch, status=k.BATCH_VALIDATED)
    for description, headers in every_role[:4]:
        seen = validate_single(api.get_payroll_batch(batch["id"], headers))
        assert_same_object(seen, reference_batch)
        assert seen["id"] == batch["id"], f"{description} read the wrong payroll batch"

    engaged, _ = validate_collection(
        api.list_plan_service_providers(plan.plan_id, auditor_headers()),
        expected_total=3,
        expected_len=3,
    )
    assert audit_firm["id"] in ids_of(engaged), (
        "The auditor's view of the plan's providers must include the audit firm"
    )

    delivered, _ = validate_collection(
        api.list_employer_payroll_batches(
            employer.employer_id, plan.recordkeeper_headers
        ),
        expected_total=1,
        expected_len=1,
    )
    assert ids_of(delivered) == [batch["id"]], (
        f"The recordkeeper must see the one delivered batch, got {ids_of(delivered)}"
    )

    after_the_reads = validate_single(
        api.get_plan_document(plan.plan_id, regulator_headers())
    )
    assert_fields(after_the_reads, version=reference_plan["version"])
    assert_same_object(after_the_reads, reference_plan)


def test_an_owner_scoped_actor_cannot_reach_across_the_ownership_boundary(
    api: ApiClient, plan: PlanContext, employer: EmployerContext,
    second_employer: EmployerContext, batch: Dict[str, Any],
):
    """
    The second employer holds a listed role on every endpoint it tries, so each
    refusal is an ownership refusal and not an authorisation one; the same is true of
    a rival sponsor reaching into this plan and of a foreign firm acknowledging this
    plan's fiduciary allocation. The boundary blocks nothing the actor owns: the
    second employer's own payroll is accepted straight away.

    "Where an entity-backed role acts on a resource that resolves to a different
    owner, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    "When `X-User-Role` is `AdoptingEmployer`, `X-User-ID` is the `id` of the acting
    `AdoptingEmployer`; ownership checks compare the employer foreign key on the
    resource — directly on elections, payroll batches and exit transfers, and
    transitively through the parent batch on remittance deposits — to `X-User-ID`."

    "a `PooledPlanProvider` caller reaches exactly the descendants of the plans whose
    `pooled_plan_provider_id` is its own `X-User-ID`"

    "Only the firm the allocation names may acknowledge, and a `ServiceProvider` caller
    whose `X-User-ID` differs from the allocation's `service_provider_id` is rejected
    with `ERR_NOT_RESOURCE_OWNER`."

    "Ownership is checked after role authorisation and before any state or business
    rule."

    Design: Corner/rbac/corner_rbac_owner_scoped_actors_cannot_reach_across_the_boundary
    """
    rival = second_employer.headers
    reaches_across = (
        ("deliver a payroll for the other employer", api.create_payroll_batch(
            f.payroll_batch_payload(
                employer.employer_id,
                pay_period_start=SPOOF_PAY_PERIOD_START,
                pay_period_end=SPOOF_PAY_PERIOD_END,
                pay_date=SPOOF_PAY_DATE,
                withholding_date=SPOOF_WITHHOLDING_DATE,
                payroll_provider_reference=SPOOFED_PAYROLL_REFERENCE,
            ),
            rival,
        )),
        ("remit against the other employer's batch", api.create_remittance_deposit(
            f.remittance_deposit_payload(
                batch["id"], deposit_reference=SPOOFED_DEPOSIT_REFERENCE
            ),
            rival,
        )),
        ("request the other employer's exit", api.create_exit_transfer(
            f.exit_transfer_payload(employer.employer_id), rival)),
        ("read the other employer's batch", api.get_payroll_batch(batch["id"], rival)),
        ("resubmit the other employer's election", api.submit_design_election(
            employer.election_id, f.submit_election_payload(), rival)),
    )

    westvale = fixtures.registered_provider(api, f.second_plan_provider_payload())
    westvale_headers = plan_provider_headers(westvale["id"])
    westvale_plan = fixtures.draft_plan(
        api, westvale, f.second_plan_document_payload(westvale["id"])
    )
    westvale_recordkeeper = fixtures.engage_provider(
        api, westvale["id"], f.recordkeeper_payload(westvale_plan["id"])
    )
    rival_sponsor = (
        ("onboard an employer onto a plan it does not sponsor",
         api.create_adopting_employer(
             f.adopting_employer_payload(
                 plan.plan_id,
                 legal_name=BRACKENHALL_LEGAL_NAME,
                 ein=BRACKENHALL_EIN,
             ),
             westvale_headers,
         )),
        ("activate a plan it does not sponsor",
         api.activate_plan_document(plan.plan_id, westvale_headers)),
        ("acknowledge a function allocated to somebody else",
         api.acknowledge_fiduciary_role_allocation(
             plan.named_fiduciary_allocation["id"],
             f.acknowledge_allocation_payload(CROSS_PLAN_ACKNOWLEDGMENT),
             service_provider_headers(westvale_recordkeeper["id"]),
         )),
    )
    for description, response in reaches_across + rival_sponsor:
        validate_error(response, ERR_NOT_RESOURCE_OWNER, expected_status=403)
        _assert_error_envelope(response, ERR_NOT_RESOURCE_OWNER)
        assert response.status_code == 403, (
            f"An attempt to {description} must be refused 403, "
            f"got {response.status_code}"
        )

    own_payroll = validate_created(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                second_employer.employer_id,
                payroll_provider_reference=k.QUARRY_PAYROLL_REFERENCE,
                total_eligible_compensation_cents=QUARRY_COMPENSATION_CENTS,
                total_deferral_cents=QUARRY_DEFERRAL_CENTS,
                total_match_cents=QUARRY_MATCH_CENTS,
                total_loan_repayment_cents=0,
                participant_line_count=QUARRY_PARTICIPANT_LINES,
            ),
            rival,
        )
    )
    assert_fields(
        own_payroll,
        adopting_employer_id=second_employer.employer_id,
        status=k.BATCH_RECEIVED,
        batch_total_cents=QUARRY_BATCH_TOTAL_CENTS,
    )

    untouched, _ = validate_collection(
        api.list_employer_payroll_batches(employer.employer_id, plan.provider_headers),
        expected_total=1,
        expected_len=1,
    )
    assert ids_of(untouched) == [batch["id"]], (
        f"The first employer must still hold exactly its own batch, "
        f"got {ids_of(untouched)}"
    )
    adopters, _ = validate_collection(
        api.list_plan_adopting_employers(plan.plan_id, regulator_headers()),
        expected_total=2,
        expected_len=2,
    )
    assert sorted(ids_of(adopters)) == sorted(
        [employer.employer_id, second_employer.employer_id]
    ), f"The rival sponsor must not have added an employer, got {ids_of(adopters)}"
