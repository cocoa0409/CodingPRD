"""Envelope, cross-reference scoping and the immediacy of every cascade."""

from typing import Any, Dict

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_fields,
    assert_instant_equals,
    assert_plan_control_invariants,
    assert_resource_shape,
    assert_same_object,
    ids_of,
    validate_collection,
    validate_created,
    validate_empty_collection,
    validate_single,
)
from test_helpers.fixtures import EmployerContext, PlanContext
from test_helpers.test_users import (
    auditor_headers,
    employer_headers,
    regulator_headers,
    service_provider_headers,
)

# The registration is granted a day after the intent is filed, so the two
# timestamps on the row cannot be confused with one another.
REGISTRATION_CLOCK = "2026-08-02T09:00:00Z"

# Field values a client tries to dictate on an action endpoint that does not
# declare them as input.
CLIENT_SUPPLIED_REGISTRATION_NUMBER = "PPP-CLIENT-SUPPLIED"
CLIENT_SUPPLIED_BOND_CENTS = 1
FIRST_MINTED_REGISTRATION_NUMBER = "PPP-0001"

# The plan's engaged firms: recordkeeper, trustee and a third-party administrator
# that holds no statutory function at all.
ENGAGED_PROVIDER_COUNT = 3
PLAN_ALLOCATION_COUNT = 2

# The canonical timely posting, whose fan-out is read one row at a time.
BUSINESS_DAYS_ELAPSED = 5

# Two employers admitted one at a time, with reads interleaved between the writes.
PALISADE_PARTICIPANTS = 13
QUARRY_PARTICIPANTS = 15
COMBINED_PARTICIPANTS = 28
EMPLOYER_VERSION_AFTER_APPROVAL = 4


def test_an_action_endpoint_returns_the_whole_row_and_ignores_what_it_never_declared(
    api: ApiClient
):
    """
    The grant carries three keys the endpoint does not declare — a registration
    number, a status and a bond amount — and none of them reaches the row: the number
    is server-minted, the status follows the transition and the bond keeps the value
    the intent was filed with. What comes back is the entire provider, and a read
    immediately afterwards returns exactly the same object.

    "Creation endpoints respond with HTTP 201 and the created resource; read
    endpoints, list endpoints and state-transition endpoints respond with HTTP 200
    and, for the transitions, the updated resource."

    "Priority 7 is request shape — required fields present, correct types, declared
    enum members, declared integer ranges, ISO-8601 date and datetime formats, and
    pagination bounds — reported as `ERR_VALIDATION`; unknown fields in a body are
    ignored rather than rejected."

    "On success the server mints `registration_number` in the form `PPP-NNNN`, where
    `NNNN` is the one-based ordinal of this approval among all approvals, zero-padded
    to four digits and assigned in ascending order of approval, so the first firm
    admitted carries `PPP-0001` and the tenth carries `PPP-0010`; it copies
    `registration_effective_date` from the request, stamps `registered_at` from the
    logical clock, and increments the provider's `version` by one."

    "`updated_at` has the same format and is refreshed on every mutation, including
    mutations that the resource did not request itself but received as a cascaded side
    effect from a sibling or child operation."

    Design: Corner/endpoints/corner_action_endpoint_returns_full_entity_extra_field_ignored
    """
    intent = fixtures.pending_provider(api)
    assert_fields(
        intent,
        registration_status=k.PROVIDER_PENDING_REGISTRATION,
        fidelity_bond_amount_cents=k.MERIDIAN_BOND_CENTS,
        version=1,
    )
    fixtures.set_clock(api, REGISTRATION_CLOCK)

    granted = validate_single(
        api.register_plan_provider(
            intent["id"],
            f.register_provider_payload(
                registration_number=CLIENT_SUPPLIED_REGISTRATION_NUMBER,
                registration_status=k.PROVIDER_PENDING_REGISTRATION,
                fidelity_bond_amount_cents=CLIENT_SUPPLIED_BOND_CENTS,
            ),
            regulator_headers(),
        )
    )
    assert_resource_shape(granted, "PooledPlanProvider")
    assert_fields(
        granted,
        id=intent["id"],
        legal_name=k.MERIDIAN_LEGAL_NAME,
        ein=k.MERIDIAN_EIN,
        registration_status=k.PROVIDER_REGISTERED,
        registration_number=FIRST_MINTED_REGISTRATION_NUMBER,
        registration_effective_date=k.REGISTRATION_EFFECTIVE_DATE,
        fidelity_bond_amount_cents=k.MERIDIAN_BOND_CENTS,
        created_at=intent["created_at"],
        version=2,
    )
    assert granted["registration_number"] != CLIENT_SUPPLIED_REGISTRATION_NUMBER, (
        "The registration number is minted by the server, not taken from the body"
    )
    assert_instant_equals(granted["registered_at"], REGISTRATION_CLOCK, "registered_at")
    assert_instant_equals(granted["updated_at"], REGISTRATION_CLOCK, "updated_at")
    assert granted["updated_at"] != granted["created_at"], (
        "The grant is a mutation, so updated_at must have moved past created_at"
    )

    read_back = validate_single(api.get_plan_provider(intent["id"], regulator_headers()))
    assert_same_object(read_back, granted)


def test_a_cross_reference_listing_shows_only_the_rows_under_its_own_parent(
    api: ApiClient, plan: PlanContext
):
    """
    One allocation row is reachable from two parents — the plan it binds and the firm
    it names — and appears under each of them exactly once, while the sponsor's other
    plan and the firm that holds no function see nothing of it. A listing with no rows
    is a 200 carrying an empty array and a total of zero.

    "List the service providers engaged on this plan (FK reverse for
    ServiceProvider.plan_document_id)."

    "List every fiduciary role allocation on this plan, ALLOCATED and REVOKED (FK
    reverse for FiduciaryRoleAllocation.plan_document_id)."

    "List the fiduciary roles allocated to this provider (FK reverse for
    FiduciaryRoleAllocation.service_provider_id)."

    "List the plan filings this provider attested as auditor (FK reverse for
    PlanFiling.audit_firm_service_provider_id)."

    "For every list response the `meta` object carries `limit` (the effective page
    size applied), `offset` (the effective starting position applied), `total_count`
    (the number of rows matching the request before the page window is applied) and
    `has_more` (true when rows remain beyond the current window)."

    Design: Corner/endpoints/corner_cross_reference_listings_scoped_to_their_path_parent
    """
    administrator = fixtures.engage_provider(api, plan, f.tpa_payload(plan.plan_id))
    other_plan = fixtures.second_plan(api, plan)
    other_firm = fixtures.engage_provider(
        api, plan, f.recordkeeper_payload(other_plan["id"])
    )

    engaged, _ = validate_collection(
        api.list_plan_service_providers(plan.plan_id, plan.provider_headers),
        expected_total=ENGAGED_PROVIDER_COUNT,
        expected_len=ENGAGED_PROVIDER_COUNT,
        expected_has_more=False,
    )
    assert sorted(ids_of(engaged)) == sorted(
        [plan.recordkeeper_id, plan.trustee_id, administrator["id"]]
    ), f"The plan's engagement listing is mis-scoped: {ids_of(engaged)}"
    assert other_firm["id"] not in ids_of(engaged), (
        "A firm engaged on the sponsor's other plan must not appear under this plan"
    )

    on_the_plan, _ = validate_collection(
        api.list_plan_fiduciary_role_allocations(plan.plan_id, auditor_headers()),
        expected_total=PLAN_ALLOCATION_COUNT,
        expected_len=PLAN_ALLOCATION_COUNT,
        expected_has_more=False,
    )
    assert sorted(ids_of(on_the_plan)) == sorted(
        [plan.named_fiduciary_allocation["id"], plan.trustee_allocation["id"]]
    ), f"The plan's allocation listing is mis-scoped: {ids_of(on_the_plan)}"

    on_the_recordkeeper, _ = validate_collection(
        api.list_service_provider_fiduciary_role_allocations(
            plan.recordkeeper_id, plan.recordkeeper_headers
        ),
        expected_total=1,
        expected_len=1,
        expected_has_more=False,
    )
    assert ids_of(on_the_recordkeeper) == [plan.named_fiduciary_allocation["id"]], (
        f"One row with two navigable parents, got {ids_of(on_the_recordkeeper)}"
    )
    assert_same_object(
        on_the_recordkeeper[0],
        next(
            row
            for row in on_the_plan
            if row["id"] == plan.named_fiduciary_allocation["id"]
        ),
    )

    unfunctioned = api.list_service_provider_fiduciary_role_allocations(
        administrator["id"], service_provider_headers(administrator["id"])
    )
    assert unfunctioned.status_code == 200, (
        f"An empty cross-reference listing is a 200, got {unfunctioned.status_code}"
    )
    validate_empty_collection(unfunctioned)

    validate_empty_collection(
        api.list_service_provider_attested_filings(
            plan.recordkeeper_id, plan.provider_headers
        )
    )

    on_the_other_plan, _ = validate_collection(
        api.list_plan_service_providers(other_plan["id"], plan.provider_headers),
        expected_total=1,
        expected_len=1,
        expected_has_more=False,
    )
    assert ids_of(on_the_other_plan) == [other_firm["id"]], (
        f"The other plan's listing must hold only its own firm, "
        f"got {ids_of(on_the_other_plan)}"
    )


def test_a_posting_publishes_its_whole_fan_out_inside_its_own_response(
    api: ApiClient, plan: PlanContext, employer: EmployerContext, batch: Dict[str, Any]
):
    """
    One posting moves five rows, and the caller learns all of it without a second
    write: the deposit's two dimensions and both day counts are in the response, and
    the very next reads of the batch, the employer and the plan already carry the
    settled figures. Re-reading the plan through another role returns the same numbers
    and the same version, so nothing was recomputed by the act of reading.

    "On success `deposit_status` moves from `PENDING` to `POSTED`, `posted_at` is
    stamped from the logical clock, and the reference is stored."

    "`business_days_elapsed` is the number of business days strictly after the batch's
    `withholding_date` through the `deposit_date` inclusive — the withholding date
    itself never counts and the deposit date counts whenever it is a business day."

    "`late_by_business_days` is the number of business days strictly after the batch's
    `deposit_due_date` through the `deposit_date` inclusive, and it is zero whenever
    the deposit is timely."

    "Independently of the timeliness verdict, the batch advances from `VALIDATED` to
    `REMITTED`, the employer's `contribution_receivable_cents` and
    `account_balance_cents` are both recomputed — the amount leaves the receivable and
    enters the balance — and the plan document's `aggregate_receivable_cents`,
    `total_assets_cents` and `contribution_control_delta_cents` are recomputed."

    "The batch's `deposit_rule` and `deposit_due_date` are frozen at creation and are
    never recomputed, so a census restatement that later flips the employer's
    `is_small_plan` flag does not move the deadline of a batch already delivered."

    Design: Corner/consistency_model/corner_consistency_mutation_response_already_carries_every_cascade
    """
    deposit = fixtures.pending_deposit(api, employer, batch)
    posted = validate_single(
        api.post_remittance_deposit(
            deposit["id"], f.post_deposit_payload(), plan.recordkeeper_headers
        )
    )
    assert_fields(
        posted,
        id=deposit["id"],
        payroll_batch_id=batch["id"],
        amount_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_TIMELY,
        business_days_elapsed=BUSINESS_DAYS_ELAPSED,
        late_by_business_days=0,
        posting_reference=k.POSTING_REFERENCE,
    )
    assert_instant_equals(posted["posted_at"], k.DEPOSIT_CLOCK, "posted_at")

    remitted = validate_single(
        api.get_payroll_batch(batch["id"], plan.recordkeeper_headers)
    )
    assert_fields(
        remitted,
        status=k.BATCH_REMITTED,
        deposit_rule=k.DEPOSIT_RULE_SMALL_PLAN,
        deposit_due_date=k.DEPOSIT_DUE_DATE,
    )

    funded = validate_single(
        api.get_adopting_employer(employer.employer_id, employer.headers)
    )
    assert_fields(
        funded,
        account_balance_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        contribution_receivable_cents=0,
        adoption_status=k.EMPLOYER_ACTIVE,
        contribution_hold=False,
        open_correction_count=0,
    )

    plan_after = validate_single(
        api.get_plan_document(plan.plan_id, plan.provider_headers)
    )
    assert_fields(
        plan_after,
        total_assets_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        aggregate_receivable_cents=0,
        contribution_control_delta_cents=0,
    )
    assert_plan_control_invariants(plan_after)

    under_the_batch, _ = validate_collection(
        api.list_batch_remittance_deposits(batch["id"], plan.provider_headers),
        expected_total=1,
        expected_len=1,
        expected_has_more=False,
    )
    assert_same_object(under_the_batch[0], posted)

    plan_again = validate_single(api.get_plan_document(plan.plan_id, regulator_headers()))
    assert_same_object(plan_again, plan_after)


def test_a_write_by_one_role_is_visible_to_the_next_reader_and_moves_the_counters(
    api: ApiClient, plan: PlanContext
):
    """
    Two employers are admitted and approved one at a time, with a different role
    reading between every write. Admission moves the headcount immediately while the
    employer count waits for approval, each approval moves that count in the same
    instant, and the listing's total tracks every write with no lag. The versions at
    the end are exactly the number of transitions each row underwent, so no read added
    one.

    "Admission also moves the plan: the plan document's `participant_count` and its
    `cumulative_enrolled_participant_count` both increase by the admitted headcount,
    its `audit_required` flag and `headcount_control_delta` are recomputed, and its
    `version` is incremented by one."

    "On success the election moves from `SUBMITTED` to `APPROVED` with `approved_at`
    stamped from the logical clock, the employer advances from `ELECTIONS_SUBMITTED` to
    `ACTIVE` with `effective_adoption_date` set to the logical-clock calendar date, the
    plan document's `active_employer_count` is recomputed, and both the election's and
    the employer's `version` are incremented by one."

    "List results are ordered by `created_at` ascending unless a specific listing
    states otherwise, so pagination is stable across pages."

    "`version` is an integer that starts at 1 on creation and increments by exactly one
    on every mutation, again including cascaded ones."

    Design: Corner/consistency_model/corner_consistency_writes_are_visible_at_once_across_roles_and_listings
    """
    def approve_for(employer: Dict[str, Any], signatory: str) -> Dict[str, Any]:
        """Elect, submit and approve on behalf of a freshly admitted employer."""
        headers = employer_headers(employer["id"])
        election = validate_created(
            api.create_design_election(
                f.design_election_payload(employer["id"], employer["version"]), headers
            )
        )
        validate_single(
            api.submit_design_election(
                election["id"], f.submit_election_payload(signatory), headers
            )
        )
        return validate_single(
            api.approve_design_election(election["id"], plan.provider_headers)
        )

    palisade = validate_created(
        api.create_adopting_employer(
            f.adopting_employer_payload(plan.plan_id), plan.provider_headers
        )
    )
    assert_fields(
        palisade,
        adoption_status=k.EMPLOYER_APPLIED,
        participant_count=PALISADE_PARTICIPANTS,
        version=1,
    )

    seen_by_the_regulator, _ = validate_collection(
        api.list_plan_adopting_employers(plan.plan_id, regulator_headers()),
        expected_total=1,
        expected_len=1,
        expected_has_more=False,
    )
    assert ids_of(seen_by_the_regulator) == [palisade["id"]], (
        "The employer the sponsor just created must be in the regulator's next listing"
    )

    seen_by_the_auditor = validate_single(
        api.get_plan_document(plan.plan_id, auditor_headers())
    )
    assert_fields(
        seen_by_the_auditor,
        participant_count=PALISADE_PARTICIPANTS,
        cumulative_enrolled_participant_count=PALISADE_PARTICIPANTS,
        active_employer_count=0,
    )

    first_approval = approve_for(palisade, k.PALISADE_SIGNATORY)
    assert_fields(first_approval, status=k.ELECTION_APPROVED)
    after_first = validate_single(api.get_plan_document(plan.plan_id, regulator_headers()))
    assert_fields(
        after_first,
        active_employer_count=1,
        participant_count=PALISADE_PARTICIPANTS,
    )

    quarry = validate_created(
        api.create_adopting_employer(
            f.second_adopting_employer_payload(plan.plan_id), plan.provider_headers
        )
    )
    assert_fields(
        quarry,
        adoption_status=k.EMPLOYER_APPLIED,
        participant_count=QUARRY_PARTICIPANTS,
        version=1,
    )
    after_admission = validate_single(
        api.get_plan_document(plan.plan_id, regulator_headers())
    )
    assert_fields(
        after_admission,
        participant_count=COMBINED_PARTICIPANTS,
        cumulative_enrolled_participant_count=COMBINED_PARTICIPANTS,
        active_employer_count=1,
    )

    second_approval = approve_for(quarry, k.QUARRY_SIGNATORY)
    assert_fields(second_approval, status=k.ELECTION_APPROVED)
    after_second = validate_single(
        api.get_plan_document(plan.plan_id, auditor_headers())
    )
    assert_fields(
        after_second,
        active_employer_count=2,
        participant_count=COMBINED_PARTICIPANTS,
        headcount_control_delta=0,
        audit_required=False,
    )
    assert_plan_control_invariants(after_second)

    adopters, _ = validate_collection(
        api.list_plan_adopting_employers(plan.plan_id, regulator_headers()),
        expected_total=2,
        expected_len=2,
        expected_has_more=False,
    )
    assert ids_of(adopters) == [palisade["id"], quarry["id"]], (
        f"The listing is ordered by created_at ascending, got {ids_of(adopters)}"
    )
    assert_created_at_ascending(adopters)
    for row in adopters:
        assert_fields(
            row,
            adoption_status=k.EMPLOYER_ACTIVE,
            version=EMPLOYER_VERSION_AFTER_APPROVAL,
        )
