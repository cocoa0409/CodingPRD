"""Who may act, and who may act on which row.

Authority in this domain is cut two ways. The endpoint gate is a role
comparison: a role absent from an endpoint's authorised list never reaches the
body at all. Segregation of duties is a *user id* comparison layered on top of
it, so a caller in exactly the right role is still refused when the id it
carries is the one already recorded on the row it wants to dispose of. The
`PracticePhysician` role sits outside both patterns, because its identity is an
entity: the physician's own `Physician` id.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import PRECEDENCE_RANK, ApiErrorId
from test_helpers.constants import (
    CLEARANCE_CLEARED,
    CLEARANCE_PENDING,
    DEAL_STATUS_DILIGENCE,
    DEAL_STATUS_SOURCING,
    DEFAULT_CLOCK_INSTANT,
    DOMAIN_BY_TASK_CODE,
    EMPLOYMENT_EMPLOYED,
    EMPLOYMENT_OFFERED,
    EMPLOYMENT_PROSPECTIVE,
    OPINION_STATUS_ACCEPTED,
    OPINION_STATUS_DRAFT,
    OPINION_STATUS_REJECTED,
    OPINION_STATUS_SUBMITTED,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_EXECUTED,
    PLAN_STATUS_SUBMITTED,
    POSTURE_BLOCKED,
    STANDARD_PLAN_PERCENTILE,
    TASK_COMPLIANCE_TRAINING,
    TASK_REVENUE_CYCLE_GO_LIVE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
    TASK_STATUS_WAIVED,
    USER_COMPLIANCE_OFFICER,
    USER_COMPLIANCE_OFFICER_ALT,
    USER_VALUATION_ANALYST,
    USER_VALUATION_ANALYST_ALT,
)
from test_helpers.fixtures import (
    COMPENSATION_DESIGNER,
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_ALT,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    VALUATION_ANALYST,
    advance_deal_status,
    approved_plan,
    board_review_deal,
    create_acquisition,
    create_payer_contract,
    create_physician,
    create_plan,
    create_task,
    diligence_deal,
    file_market_fmv,
    read_acquisition,
    read_task,
    second_physician,
    set_clearance,
    set_task_status,
    submit_opinion,
    submit_plan,
)
from test_helpers.test_users import (
    make_compliance_officer_headers,
    make_practice_physician_headers,
    make_valuation_analyst_headers,
)

TRAINING_DUE_ON = "2026-10-25"
GO_LIVE_DUE_ON = "2026-10-28"
WAIVER_REASON = "Training deferred to the system-wide October cohort"
SELF_REVIEW_NOTE = "Reviewing my own work"
ACCEPT_NOTE = "Market approach accepted"
APPROVE_NOTE = "Approving compensation against the opinion I accepted"


# ---------------------------------------------------------------------------
# Authoring a valuation is closed to the role that owns the deal
# ---------------------------------------------------------------------------


def test_the_deal_lead_that_owns_the_deal_may_not_file_a_valuation_opinion(api: ApiClient):
    """Three roles are turned away from the analyst's create endpoint.

    PRD: "A `DealLead` may neither author nor accept a valuation, and may not
    approve compensation."

    PRD: "If both headers are well formed but the named role is not authorised
    for the endpoint being called, the request is rejected with
    `ERR_FORBIDDEN_ROLE` and HTTP 403; because that gate runs before the request
    body is parsed, a caller in a forbidden role never learns whether its
    payload was well formed."

    Design: Corner/rbac/deal_lead_cannot_author_a_valuation_opinion
    """
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    before = read_acquisition(api, acquisition_id)
    payload = f.market_fmv_payload(acquisition_id, before["version"])

    refused = api.create_valuation_opinion(payload, DEAL_LEAD)
    validate_error(refused, ApiErrorId.FORBIDDEN_ROLE, 403)

    for other_role in (COMPLIANCE_OFFICER, COMPENSATION_DESIGNER):
        validate_error(
            api.create_valuation_opinion(payload, other_role),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )

    a.assert_total_count(
        api.list_valuation_opinions({"acquisition_id": acquisition_id}, DEAL_LEAD), 0
    )

    after = read_acquisition(api, acquisition_id)
    a.assert_version_unchanged(before, after)


def test_the_analyst_files_the_identical_body_and_carries_it_to_submitted(api: ApiClient):
    """The body the deal lead was refused is accepted from the analyst.

    PRD: "A `ValuationAnalyst` files one by supplying the `acquisition_id`, the
    `expected_acquisition_version` the analyst last observed, the
    `opinion_type`, the `method`, the valuation date as `effective_on`, an
    `independence_attested` flag, and whichever numeric inputs the chosen method
    requires."

    PRD: "On success the server increments the acquisition's `version` by 1."

    Design: Corner/rbac/deal_lead_cannot_author_a_valuation_opinion
    """
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    before = read_acquisition(api, acquisition_id, VALUATION_ANALYST)
    payload = f.market_fmv_payload(acquisition_id, before["version"])

    created = validate_success(
        api.create_valuation_opinion(payload, VALUATION_ANALYST), 201
    )
    a.assert_status(created, OPINION_STATUS_DRAFT)
    assert created["prepared_by_user_id"] == USER_VALUATION_ANALYST

    after = read_acquisition(api, acquisition_id, VALUATION_ANALYST)
    a.assert_version_bumped_by(before, after)

    submitted = validate_success(
        api.set_valuation_opinion_status(
            created["id"],
            f.opinion_status_payload(OPINION_STATUS_SUBMITTED),
            VALUATION_ANALYST,
        )
    )
    a.assert_status(submitted, OPINION_STATUS_SUBMITTED)

    a.assert_total_count(
        api.list_valuation_opinions({"acquisition_id": acquisition_id}, DEAL_LEAD), 1
    )


# ---------------------------------------------------------------------------
# Segregation of duties on the opinion: a user id comparison, not a role one
# ---------------------------------------------------------------------------


def test_an_officer_reusing_the_preparers_user_id_cannot_dispose_of_the_opinion(
    api: ApiClient,
):
    """Both dispositions are closed to the id that prepared the draft.

    PRD: "First, the `ComplianceOfficer` who accepts or rejects a valuation
    opinion must be a different user id from the one recorded in that opinion's
    `prepared_by_user_id`."

    PRD: "On acceptance the caller's `X-User-ID` is stored in
    `accepted_by_user_id`, which is the field the compensation-approval
    segregation check later reads."

    Design: Corner/rbac/officer_sharing_the_preparers_user_id_cannot_accept_the_opinion
    """
    deal = diligence_deal(api)
    opinion = file_market_fmv(api, deal["acquisition"]["id"])
    submit_opinion(api, opinion["id"])
    wearing_the_preparers_id = make_compliance_officer_headers(USER_VALUATION_ANALYST)

    for target_status in (OPINION_STATUS_ACCEPTED, OPINION_STATUS_REJECTED):
        refused = api.set_valuation_opinion_status(
            opinion["id"],
            f.opinion_status_payload(target_status, review_note=SELF_REVIEW_NOTE),
            wearing_the_preparers_id,
        )
        validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
        stalled = get_success_data(
            api.get_valuation_opinion(opinion["id"], COMPLIANCE_OFFICER)
        )
        a.assert_status(stalled, OPINION_STATUS_SUBMITTED)
        a.assert_fields_null(stalled, "accepted_by_user_id")

    accepted = validate_success(
        api.set_valuation_opinion_status(
            opinion["id"],
            f.opinion_status_payload(OPINION_STATUS_ACCEPTED, review_note=ACCEPT_NOTE),
            COMPLIANCE_OFFICER,
        )
    )
    a.assert_status(accepted, OPINION_STATUS_ACCEPTED)
    assert accepted["accepted_by_user_id"] == USER_COMPLIANCE_OFFICER


def test_only_the_analyst_who_prepared_a_draft_may_submit_it(api: ApiClient):
    """The preparer-side half of the same separation, under its own code.

    PRD: "Separately, and with its own code, a valuation opinion may only be
    submitted for review by the analyst who prepared it: the caller's
    `X-User-ID` must equal `prepared_by_user_id`, and a mismatch is
    `ERR_NOT_PLAN_OWNER`."

    Design: Corner/rbac/officer_sharing_the_preparers_user_id_cannot_accept_the_opinion
    """
    deal = diligence_deal(api)
    draft = file_market_fmv(api, deal["acquisition"]["id"])
    assert draft["prepared_by_user_id"] == USER_VALUATION_ANALYST

    second_analyst = make_valuation_analyst_headers(USER_VALUATION_ANALYST_ALT)
    refused = api.set_valuation_opinion_status(
        draft["id"], f.opinion_status_payload(OPINION_STATUS_SUBMITTED), second_analyst
    )
    validate_error(refused, ApiErrorId.NOT_PLAN_OWNER, 403)

    untouched = get_success_data(api.get_valuation_opinion(draft["id"], VALUATION_ANALYST))
    a.assert_status(untouched, OPINION_STATUS_DRAFT)
    assert untouched["prepared_by_user_id"] == USER_VALUATION_ANALYST

    submitted = submit_opinion(api, draft["id"])
    a.assert_status(submitted, OPINION_STATUS_SUBMITTED)


# ---------------------------------------------------------------------------
# Three dimensions of one row, three different roles
# ---------------------------------------------------------------------------


def test_the_integration_manager_may_not_move_the_deal_status_dimension(api: ApiClient):
    """The operational role cannot touch the workflow dimension.

    PRD: "The **workflow dimension** is `deal_status`, taking the values
    `SOURCING`, `DILIGENCE`, `BOARD_REVIEW`, `SIGNED`, `CLOSED`, and
    `ABANDONED`. A new acquisition begins in `SOURCING`; `CLOSED` and
    `ABANDONED` are terminal. This dimension is driven exclusively by a
    `DealLead`."

    Design: Corner/rbac/integration_manager_cannot_move_the_deal_status
    """
    acquisition = create_acquisition(api)
    create_physician(api, acquisition["id"])
    before = read_acquisition(api, acquisition["id"])
    assert before["deal_status"] == DEAL_STATUS_SOURCING

    refused = api.set_acquisition_status(
        acquisition["id"],
        f.acquisition_status_payload(DEAL_STATUS_DILIGENCE),
        INTEGRATION_MANAGER,
    )
    validate_error(refused, ApiErrorId.FORBIDDEN_ROLE, 403)

    after = read_acquisition(api, acquisition["id"])
    assert after["deal_status"] == DEAL_STATUS_SOURCING
    assert after["readiness_posture"] == POSTURE_BLOCKED
    a.assert_version_unchanged(before, after)

    moved = advance_deal_status(api, acquisition["id"], DEAL_STATUS_DILIGENCE)
    assert moved["deal_status"] == DEAL_STATUS_DILIGENCE


def test_each_deal_dimension_answers_to_the_role_that_owns_it(api: ApiClient):
    """The regulatory dimension is closed to the deal lead, and the manager keeps its own grants.

    PRD: "The **regulatory dimension** is `compliance_clearance`, taking the
    values `PENDING`, `CLEARED`, `FLAGGED`, and `SUSPENDED`. A new acquisition
    begins in `PENDING`, and this dimension has no terminal state — a suspended
    deal can always be brought back. It is driven exclusively by a
    `ComplianceOfficer`, and it also moves by cascade when a compensation plan
    lands on compliance hold."

    PRD: "An `IntegrationManager` runs the operational integration: payer
    contracts and their novation, re-credentialing packages, chart migration
    batches, staff transition offers, billing conversions, the day-one
    checklist, and post-close performance reporting."

    Design: Corner/rbac/integration_manager_cannot_move_the_deal_status
    """
    acquisition = create_acquisition(api)
    create_physician(api, acquisition["id"])
    assert acquisition["compliance_clearance"] == CLEARANCE_PENDING

    refused = api.set_compliance_clearance(
        acquisition["id"], f.compliance_clearance_payload(CLEARANCE_CLEARED), DEAL_LEAD
    )
    validate_error(refused, ApiErrorId.FORBIDDEN_ROLE, 403)
    assert read_acquisition(api, acquisition["id"])["compliance_clearance"] == (
        CLEARANCE_PENDING
    )

    cleared = set_clearance(api, acquisition["id"], CLEARANCE_CLEARED)
    assert cleared["compliance_clearance"] == CLEARANCE_CLEARED

    task = create_task(
        api,
        acquisition["id"],
        task_code=TASK_COMPLIANCE_TRAINING,
        is_blocking=True,
        due_on=TRAINING_DUE_ON,
    )
    a.assert_status(task, TASK_STATUS_OPEN)
    # The grant is asserted, not the body shape: PRD describes the clock reply two
    # incompatible ways — §2.6 "sets the clock to an arbitrary instant supplied as
    # `to_iso8601` and returns the new value as `current_utc`" against §4 "Setting
    # the logical clock returns HTTP 200 with an empty `data` object" — so `data`
    # is not uniquely determined and only the 2xx is a fair assertion.
    validate_success(api.set_clock(DEFAULT_CLOCK_INSTANT, INTEGRATION_MANAGER))


# ---------------------------------------------------------------------------
# The physician's readable set is enumerated, not blanket
# ---------------------------------------------------------------------------


def test_the_acquired_physician_is_closed_out_of_the_payer_contracts(api: ApiClient):
    """A role that reads its own packages is refused the contracts they point at.

    PRD: "A `PracticePhysician` is the acquired physician acting for themselves;
    they may execute an approved compensation plan addressed to them and read
    their own records, and nothing else."

    PRD: "When `X-User-Role` is `PracticePhysician`, `X-User-ID` is the `id` of
    the acting `Physician` row; ownership checks on any resource that references
    a `Physician` compare that resource's physician foreign key to `X-User-ID`."

    Design: Corner/rbac/practice_physician_cannot_list_the_payer_contracts
    """
    acquisition = create_acquisition(api)
    physician = create_physician(api, acquisition["id"])
    contract = create_payer_contract(api, acquisition["id"])
    provider = make_practice_physician_headers(physician["id"])
    assert provider["X-User-ID"] == physician["id"]

    validate_error(
        api.list_payer_contracts({"acquisition_id": acquisition["id"]}, provider),
        ApiErrorId.FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api.get_payer_contract(contract["id"], provider), ApiErrorId.FORBIDDEN_ROLE, 403
    )
    validate_error(
        api.create_payer_contract(
            f.payer_contract_payload(acquisition["id"], payer_name="Sunrise Medicaid Plan"),
            provider,
        ),
        ApiErrorId.FORBIDDEN_ROLE,
        403,
    )

    own_packages = validate_success(
        api.list_credentialing_packages({"acquisition_id": acquisition["id"]}, provider)
    )
    assert isinstance(own_packages, list)

    for authorised_reader in (INTEGRATION_MANAGER, COMPLIANCE_OFFICER):
        rows = a.assert_total_count(
            api.list_payer_contracts(
                {"acquisition_id": acquisition["id"]}, authorised_reader
            ),
            1,
        )
        a.assert_contains_id(rows, contract["id"])


# ---------------------------------------------------------------------------
# One checklist row, three different grants
# ---------------------------------------------------------------------------


def test_either_the_deal_lead_or_the_integration_manager_may_add_a_checklist_line(
    api: ApiClient,
):
    """Creation is shared between two roles, and moving the line is not one of them.

    PRD: "Either an `IntegrationManager` or a `DealLead` adds one, naming the
    `acquisition_id`, the `task_code`, and the `due_on` date by which the line
    must be complete, and optionally setting `is_blocking`, which defaults to
    true."

    PRD: "Starting a line, `OPEN → IN_PROGRESS`, is available to an
    `IntegrationManager` and to a `ComplianceOfficer`, has no precondition, and
    recomputes the posture."

    Design: Corner/rbac/readiness_task_creation_is_shared_but_waiving_is_exclusive
    """
    acquisition = create_acquisition(api)
    create_physician(api, acquisition["id"])

    task_a = validate_success(
        api.create_readiness_task(
            f.readiness_task_payload(
                acquisition["id"],
                task_code=TASK_COMPLIANCE_TRAINING,
                is_blocking=True,
                due_on=TRAINING_DUE_ON,
            ),
            DEAL_LEAD,
        ),
        201,
    )
    task_b = validate_success(
        api.create_readiness_task(
            f.readiness_task_payload(
                acquisition["id"],
                task_code=TASK_REVENUE_CYCLE_GO_LIVE,
                is_blocking=False,
                due_on=GO_LIVE_DUE_ON,
            ),
            INTEGRATION_MANAGER,
        ),
        201,
    )
    a.assert_status(task_a, TASK_STATUS_OPEN)
    a.assert_status(task_b, TASK_STATUS_OPEN)
    assert task_a["domain"] == DOMAIN_BY_TASK_CODE[TASK_COMPLIANCE_TRAINING]
    assert task_b["domain"] == DOMAIN_BY_TASK_CODE[TASK_REVENUE_CYCLE_GO_LIVE]
    assert task_a["is_blocking"] is True
    assert task_b["is_blocking"] is False

    refused = api.set_readiness_task_status(
        task_b["id"], f.task_status_payload(TASK_STATUS_IN_PROGRESS), DEAL_LEAD
    )
    validate_error(refused, ApiErrorId.FORBIDDEN_ROLE, 403)
    a.assert_status(read_task(api, task_b["id"], DEAL_LEAD), TASK_STATUS_OPEN)

    started = set_task_status(api, task_b["id"], TASK_STATUS_IN_PROGRESS)
    a.assert_status(started, TASK_STATUS_IN_PROGRESS)


def test_waiving_a_line_stores_the_officers_id_and_needs_a_justification(api: ApiClient):
    """The waiver's own precondition, on a line the deal lead opened.

    PRD: "Both carry the identical precondition that the request supplies a
    non-empty `waiver_justification` — whitespace alone is not a justification,
    and its absence is `ERR_WAIVER_JUSTIFICATION_REQUIRED` — and both perform the
    identical side effects of storing that `waiver_justification`, storing the
    caller's `X-User-ID` in `verified_by_user_id`, and recomputing the posture."

    Design: Corner/rbac/readiness_task_creation_is_shared_but_waiving_is_exclusive
    """
    acquisition = create_acquisition(api)
    create_physician(api, acquisition["id"])
    task = create_task(
        api,
        acquisition["id"],
        DEAL_LEAD,
        task_code=TASK_COMPLIANCE_TRAINING,
        is_blocking=True,
        due_on=TRAINING_DUE_ON,
    )

    unjustified = api.set_readiness_task_status(
        task["id"], f.task_status_payload(TASK_STATUS_WAIVED), COMPLIANCE_OFFICER
    )
    validate_error(unjustified, ApiErrorId.WAIVER_JUSTIFICATION_REQUIRED, 422)
    stalled = read_task(api, task["id"])
    a.assert_status(stalled, TASK_STATUS_OPEN)
    a.assert_fields_null(stalled, "verified_by_user_id", "waiver_justification")

    waived = validate_success(
        api.set_readiness_task_status(
            task["id"],
            f.task_status_payload(TASK_STATUS_WAIVED, waiver_justification=WAIVER_REASON),
            COMPLIANCE_OFFICER,
        )
    )
    a.assert_status(waived, TASK_STATUS_WAIVED)
    assert waived["verified_by_user_id"] == USER_COMPLIANCE_OFFICER
    assert waived["waiver_justification"] == WAIVER_REASON


# ---------------------------------------------------------------------------
# The transitive separation: the officer behind the price cannot bless the pay
# ---------------------------------------------------------------------------


def test_the_officer_who_accepted_the_pinned_valuation_may_not_approve_the_plan(
    api: ApiClient,
):
    """The bar is keyed to one pinned opinion, and the other officer is free.

    PRD: "Second, the `ComplianceOfficer` user id recorded in the pinned fair
    market value opinion's `accepted_by_user_id` may not approve any compensation
    plan on that same acquisition."

    PRD: "On approval the caller's `X-User-ID` is stored in
    `approved_by_user_id`, the linked physician's `employment_status` is
    recomputed to `OFFERED`, and any other compensation plan for the same
    `physician_id` that is currently in `EXECUTED` is set to `SUPERSEDED` — a
    physician may hold only one live executed arrangement."

    Design: Corner/rbac/officer_who_accepted_the_pinned_opinion_cannot_approve_the_plan
    """
    deal = board_review_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    physician_id = deal["physician"]["id"]
    plan = create_plan(api, acquisition_id, physician_id)
    submit_plan(api, plan["id"])

    refused = api.set_compensation_plan_status(
        plan["id"],
        f.plan_status_payload(PLAN_STATUS_APPROVED, review_note=APPROVE_NOTE),
        COMPLIANCE_OFFICER,
    )
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

    stalled = get_success_data(api.get_compensation_plan(plan["id"], COMPLIANCE_OFFICER))
    a.assert_status(stalled, PLAN_STATUS_SUBMITTED)
    assert stalled["returned_count"] == 0
    a.assert_fields_null(stalled, "approved_by_user_id")

    pinned = get_success_data(
        api.get_valuation_opinion(deal["fmv"]["id"], COMPLIANCE_OFFICER)
    )
    assert pinned["is_pinned"] is True
    assert pinned["accepted_by_user_id"] == USER_COMPLIANCE_OFFICER

    before = get_success_data(api.get_physician(physician_id, DEAL_LEAD))
    assert before["employment_status"] == EMPLOYMENT_PROSPECTIVE

    approved = validate_success(
        api.set_compensation_plan_status(
            plan["id"],
            f.plan_status_payload(PLAN_STATUS_APPROVED, review_note=APPROVE_NOTE),
            COMPLIANCE_OFFICER_ALT,
        )
    )
    a.assert_status(approved, PLAN_STATUS_APPROVED)
    assert approved["approved_by_user_id"] == USER_COMPLIANCE_OFFICER_ALT
    a.assert_percentage_equals(approved["benchmark_percentile"], STANDARD_PLAN_PERCENTILE)

    after = get_success_data(api.get_physician(physician_id, DEAL_LEAD))
    assert after["employment_status"] == EMPLOYMENT_OFFERED


def test_the_barred_officer_keeps_its_other_duties_on_the_same_acquisition(api: ApiClient):
    """One approval is closed to co-1; the rest of the officer's mandate is not.

    PRD: "A `ComplianceOfficer` is the regulatory gate: it accepts or rejects
    valuation opinions, approves compensation plans, moves the acquisition's
    regulatory clearance dimension, waives readiness checklist lines, and places
    executed plans on compliance hold — while authoring nothing itself."

    Design: Corner/rbac/officer_who_accepted_the_pinned_opinion_cannot_approve_the_plan
    """
    deal = board_review_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    plan = create_plan(api, acquisition_id, deal["physician"]["id"])
    submit_plan(api, plan["id"])

    refused = api.set_compensation_plan_status(
        plan["id"], f.plan_status_payload(PLAN_STATUS_APPROVED), COMPLIANCE_OFFICER
    )
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES, 403)

    cleared = set_clearance(api, acquisition_id, CLEARANCE_CLEARED, COMPLIANCE_OFFICER)
    assert cleared["compliance_clearance"] == CLEARANCE_CLEARED

    task = create_task(
        api,
        acquisition_id,
        INTEGRATION_MANAGER,
        task_code=TASK_COMPLIANCE_TRAINING,
        is_blocking=True,
        due_on=TRAINING_DUE_ON,
    )
    waived = validate_success(
        api.set_readiness_task_status(
            task["id"],
            f.task_status_payload(TASK_STATUS_WAIVED, waiver_justification=WAIVER_REASON),
            COMPLIANCE_OFFICER,
        )
    )
    a.assert_status(waived, TASK_STATUS_WAIVED)
    assert waived["verified_by_user_id"] == USER_COMPLIANCE_OFFICER


# ---------------------------------------------------------------------------
# The entity-backed identity: ownership is compared, not looked up
# ---------------------------------------------------------------------------


def test_a_physician_cannot_countersign_a_colleagues_arrangement(api: ApiClient):
    """The right role and the wrong row: two acquired physicians, one plan.

    PRD: "Concretely, when a physician executes a compensation plan, the server
    resolves `X-User-ID` to a `Physician` and requires it to equal the plan's
    `physician_id`; a mismatch is `ERR_NOT_PLAN_OWNER` with HTTP 403."

    PRD: "On execution `executed_at` is stamped with the current logical instant
    and the physician's `employment_status` is recomputed to `EMPLOYED`."

    Design: Corner/rbac/physician_cannot_execute_another_physicians_plan
    """
    deal = board_review_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    physician_a = deal["physician"]
    physician_b = second_physician(api, acquisition_id)
    assert physician_a["id"] != physician_b["id"]

    plan = approved_plan(api, acquisition_id, physician_a["id"])
    a.assert_status(plan, PLAN_STATUS_APPROVED)

    colleague = make_practice_physician_headers(physician_b["id"])
    refused = api.set_compensation_plan_status(
        plan["id"], f.plan_status_payload(PLAN_STATUS_EXECUTED), colleague
    )
    validate_error(refused, ApiErrorId.NOT_PLAN_OWNER, 403)

    stalled = get_success_data(api.get_compensation_plan(plan["id"], COMPLIANCE_OFFICER))
    a.assert_status(stalled, PLAN_STATUS_APPROVED)
    a.assert_fields_null(stalled, "executed_at")
    assert (
        get_success_data(api.get_physician(physician_a["id"], DEAL_LEAD))[
            "employment_status"
        ]
        == EMPLOYMENT_OFFERED
    )
    assert (
        get_success_data(api.get_physician(physician_b["id"], DEAL_LEAD))[
            "employment_status"
        ]
        == EMPLOYMENT_PROSPECTIVE
    )

    owner = make_practice_physician_headers(physician_a["id"])
    executed = validate_success(
        api.set_compensation_plan_status(
            plan["id"], f.plan_status_payload(PLAN_STATUS_EXECUTED), owner
        )
    )
    a.assert_status(executed, PLAN_STATUS_EXECUTED)
    a.assert_instant_equals(executed["executed_at"], DEFAULT_CLOCK_INSTANT, "executed_at")
    assert (
        get_success_data(api.get_physician(physician_a["id"], DEAL_LEAD))[
            "employment_status"
        ]
        == EMPLOYMENT_EMPLOYED
    )
    assert (
        get_success_data(api.get_physician(physician_b["id"], DEAL_LEAD))[
            "employment_status"
        ]
        == EMPLOYMENT_PROSPECTIVE
    )


def test_a_role_outside_the_plan_status_grant_is_refused_before_the_ownership_check(
    api: ApiClient,
):
    """Two roles absent from the endpoint's list never reach the ownership comparison.

    PRD: "Only the physician can execute."

    PRD: "2. **Role gate** — the caller's `X-User-Role` appears in the endpoint's
    authorised list, on every endpoint. Otherwise `ERR_FORBIDDEN_ROLE` (403)."

    PRD: "12. **Record ownership**, on `POST /valuation-opinions/{opinionId}/status`
    and `POST /compensation-plans/{planId}/status`. Otherwise
    `ERR_NOT_PLAN_OWNER` (403)."

    Design: Corner/rbac/physician_cannot_execute_another_physicians_plan
    """
    assert (
        PRECEDENCE_RANK[ApiErrorId.FORBIDDEN_ROLE]
        < PRECEDENCE_RANK[ApiErrorId.NOT_PLAN_OWNER]
    )
    deal = board_review_deal(api)
    physician = deal["physician"]
    plan = approved_plan(api, deal["acquisition"]["id"], physician["id"])

    for outsider in (DEAL_LEAD, INTEGRATION_MANAGER):
        validate_error(
            api.set_compensation_plan_status(
                plan["id"], f.plan_status_payload(PLAN_STATUS_EXECUTED), outsider
            ),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )

    still = get_success_data(api.get_compensation_plan(plan["id"], COMPLIANCE_OFFICER))
    a.assert_status(still, PLAN_STATUS_APPROVED)
    a.assert_fields_null(still, "executed_at")

    executed = validate_success(
        api.set_compensation_plan_status(
            plan["id"],
            f.plan_status_payload(PLAN_STATUS_EXECUTED),
            make_practice_physician_headers(physician["id"]),
        )
    )
    a.assert_status(executed, PLAN_STATUS_EXECUTED)
    a.assert_instant_equals(executed["executed_at"], DEFAULT_CLOCK_INSTANT, "executed_at")
