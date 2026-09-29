"""Drafting, routing, deciding and superseding role eligibility classifications."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_classification,
    classification_decision_payload,
    classification_payload,
    draft_classification,
    get_success_data,
    list_all,
    read_employee,
    set_status,
    setup_cycle_team_employee,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import HRBP, MANAGER


def _one_team_and_one_unclassified_employee():
    """Clock, cycle, team T-A and one ACTIVE unclassified employee E-1001."""
    return setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-CLS", "days_in_office_floor": 2},
        team_overrides={"team_code": "T-A", "expected_days_in_office_per_week": 3,
                        "headcount_planned": 12},
        employee_overrides={"employee_number": "E-1001"},
    )


def test_01_approval_recomputes_the_current_class_and_supersedes_the_prior_row():
    """Two approvals in sequence hand the class over and retire the older row.

    PRD 3.3: "Every role in the company is eventually classified as one of three
    eligibility classes — `FULLY_REMOTE`, `HYBRID` or `ONSITE_REQUIRED` — and until
    a classification has been approved the employee is treated as
    `ONSITE_REQUIRED`."
    PRD 3.3: "At the same moment the server sets `supersedes_classification_id` to
    the `id` of the employee's current `APPROVED` classification — the one the
    current-class selector below would pick — or to null when the employee has
    none."
    PRD 3.3: "An `APPROVE` decision moves the row `PENDING_MANAGER → APPROVED`,
    stores `decided_by_user_id`, and sets off four further effects: the
    classification named by `supersedes_classification_id`, when it is not null,
    transitions `APPROVED → SUPERSEDED` and its own `version` advances; the
    employee's `current_eligibility_class` is recomputed; the employee's
    `non_compliance_pressure`, `compliance_state` and `escalation_stage` are
    recomputed, because the severity multiplier that scales shortfall into pressure
    is keyed on the eligibility class and has just changed; and the
    classification's `version` advances."

    Design: Corner/entities/classification_approval_recomputes_the_class_and_supersedes_the_prior_row
    """
    staged = _one_team_and_one_unclassified_employee()
    employee = staged["employee"]

    first = draft_classification(
        employee, requested_class="HYBRID", effective_from="2026-09-01"
    )
    assert_classification(first)
    assert first["state"] == "DRAFT"
    assert first["created_by_user_id"] == "hrbp-1"
    assert first["decided_by_user_id"] is None
    assert first["supersedes_classification_id"] is None, (
        "the employee holds no APPROVED classification yet"
    )
    assert read_employee(employee["id"])["current_eligibility_class"] == "ONSITE_REQUIRED"

    pending = validate_success(api_client.submit_classification(first["id"], HRBP))
    assert pending["state"] == "PENDING_MANAGER"
    assert read_employee(employee["id"])["current_eligibility_class"] == "ONSITE_REQUIRED", (
        "a routed but undecided draft grants nothing"
    )

    approved = validate_success(
        api_client.decide_classification(
            first["id"], classification_decision_payload("APPROVE"), MANAGER
        )
    )
    assert approved["state"] == "APPROVED"
    assert approved["decided_by_user_id"] == "mgr-1"
    assert read_employee(employee["id"])["current_eligibility_class"] == "HYBRID"

    second = draft_classification(
        read_employee(employee["id"]),
        requested_class="FULLY_REMOTE",
        effective_from="2026-10-01",
        justification_code="TALENT_RETENTION",
    )
    assert second["supersedes_classification_id"] == first["id"], (
        "the new draft names the row it would retire"
    )
    validate_success(api_client.submit_classification(second["id"], HRBP))
    second_approved = validate_success(
        api_client.decide_classification(
            second["id"], classification_decision_payload("APPROVE"), MANAGER
        )
    )
    assert second_approved["state"] == "APPROVED"
    assert validate_success(
        api_client.get_classification(first["id"], HRBP)
    )["state"] == "SUPERSEDED"
    assert read_employee(employee["id"])["current_eligibility_class"] == "FULLY_REMOTE"

    rows, meta = list_all(
        api_client.list_classifications,
        HRBP,
        {"supersedes_classification_id": first["id"]},
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]


def test_02_submit_and_decision_are_each_refused_a_second_time():
    """Each action endpoint names the state it demanded, not the state the row is in.

    PRD 3.3: "That step requires the row to still be in `DRAFT`, or it is refused
    with `ERR_CLASSIFICATION_NOT_DRAFT` (HTTP 409); it requires the employee to
    still be `ACTIVE`, or it is refused with `ERR_EMPLOYEE_NOT_ACTIVE`; and it
    requires the parent cycle to be `OPEN`, as §2.9 sets out."
    PRD 3.3: "The row must be in `PENDING_MANAGER`, or the call is refused with
    `ERR_CLASSIFICATION_NOT_PENDING` (409) — which is also what a second decision
    on an already-`APPROVED` row receives."

    Design: Corner/state_machines/classification_submit_and_decision_are_not_idempotent
    """
    staged = _one_team_and_one_unclassified_employee()
    employee = staged["employee"]
    classification = draft_classification(employee, requested_class="HYBRID")

    validate_error(
        api_client.decide_classification(
            classification["id"], classification_decision_payload("APPROVE"), MANAGER
        ),
        ApiErrorId.ERR_CLASSIFICATION_NOT_PENDING.value,
        409,
    )

    routed = validate_success(api_client.submit_classification(classification["id"], HRBP))
    assert routed["state"] == "PENDING_MANAGER"

    validate_error(
        api_client.submit_classification(classification["id"], HRBP),
        ApiErrorId.ERR_CLASSIFICATION_NOT_DRAFT.value,
        409,
    )
    still_pending = validate_success(
        api_client.get_classification(classification["id"], HRBP)
    )
    assert still_pending["state"] == "PENDING_MANAGER"
    assert still_pending["version"] == routed["version"], (
        "the refused resubmit wrote nothing"
    )

    approved = validate_success(
        api_client.decide_classification(
            classification["id"],
            classification_decision_payload("APPROVE", "approved"),
            MANAGER,
        )
    )
    assert approved["state"] == "APPROVED"
    assert approved["decided_by_user_id"] == "mgr-1"
    assert read_employee(employee["id"])["current_eligibility_class"] == "HYBRID"

    validate_error(
        api_client.decide_classification(
            classification["id"], classification_decision_payload("REVISE"), MANAGER
        ),
        ApiErrorId.ERR_CLASSIFICATION_NOT_PENDING.value,
        409,
    )
    assert read_employee(employee["id"])["current_eligibility_class"] == "HYBRID", (
        "a second decision cannot re-open an approved row"
    )
    validate_error(
        api_client.submit_classification(classification["id"], HRBP),
        ApiErrorId.ERR_CLASSIFICATION_NOT_DRAFT.value,
        409,
    )


def test_03_a_revised_draft_returns_to_draft_and_the_same_row_is_approved_later():
    """REVISE is the loop-back edge, and the loop has no one-shot limit.

    PRD 3.3: "A `REVISE` decision sends the row back along the revert edge
    `PENDING_MANAGER → DRAFT`, storing `decided_by_user_id` and the supplied
    `decision_note` and advancing `version`; the draft may then be resubmitted, so
    `DRAFT → PENDING_MANAGER → DRAFT` is a legitimate loop with no bound on its
    length."
    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation of that row, including mutations a
    cascade performs rather than the caller."

    Design: Corner/state_machines/classification_revise_sends_the_row_back_to_draft_and_it_can_be_resubmitted
    """
    staged = _one_team_and_one_unclassified_employee()
    employee = staged["employee"]
    classification = draft_classification(
        employee,
        requested_class="FULLY_REMOTE",
        justification_code="TALENT_RETENTION",
        effective_from="2026-09-01",
    )
    created_version = classification["version"]

    validate_success(api_client.submit_classification(classification["id"], HRBP))
    revised = validate_success(
        api_client.decide_classification(
            classification["id"],
            classification_decision_payload(
                "REVISE", "justification code needs a business case attached"
            ),
            MANAGER,
        )
    )
    assert revised["state"] == "DRAFT", "REVISE is a loop-back, not a dead state"
    assert revised["decision_note"] == (
        "justification code needs a business case attached"
    )
    assert revised["decided_by_user_id"] == "mgr-1"
    assert read_employee(employee["id"])["current_eligibility_class"] == "ONSITE_REQUIRED", (
        "a revised row grants nothing"
    )

    resubmitted = validate_success(
        api_client.submit_classification(classification["id"], HRBP)
    )
    assert resubmitted["state"] == "PENDING_MANAGER", (
        "the same row traverses DRAFT to PENDING_MANAGER a second time"
    )
    approved = validate_success(
        api_client.decide_classification(
            classification["id"],
            classification_decision_payload("APPROVE", "business case attached"),
            MANAGER,
        )
    )
    assert approved["state"] == "APPROVED"
    assert read_employee(employee["id"])["current_eligibility_class"] == "FULLY_REMOTE"
    assert approved["version"] == created_version + 4, (
        "submit, revise, submit and approve are four mutations of the same row"
    )
    assert approved["supersedes_classification_id"] is None

    rows, meta = list_all(
        api_client.list_classifications,
        HRBP,
        {"employee_id": employee["id"], "state": "APPROVED"},
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == classification["id"]


def test_04_the_author_of_a_draft_may_not_record_its_decision():
    """The wall is per row and per user: authoring and submitting together is fine.

    PRD 3.3: "The acting user must not be the `created_by_user_id` who drafted it,
    on pain of `ERR_SEGREGATION_OF_DUTIES` (409)."
    PRD 3.3: "The new row lands in `DRAFT` state with `created_by_user_id` captured
    from the acting `X-User-ID` and `decided_by_user_id` left null."

    Design: Corner/rbac/the_classification_author_may_not_record_its_own_decision
    """
    staged = _one_team_and_one_unclassified_employee()
    employee = staged["employee"]

    self_authored = get_success_data(
        api_client.create_classification(
            classification_payload(
                employee["id"], employee["version"], requested_class="HYBRID"
            ),
            MANAGER,
        )
    )
    assert self_authored["created_by_user_id"] == "mgr-1"
    validate_success(api_client.submit_classification(self_authored["id"], MANAGER))

    validate_error(
        api_client.decide_classification(
            self_authored["id"],
            classification_decision_payload(
                "APPROVE", "authored and decided by the same user"
            ),
            MANAGER,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        409,
    )
    blocked = validate_success(api_client.get_classification(self_authored["id"], HRBP))
    assert blocked["state"] == "PENDING_MANAGER", (
        "authoring and submitting as one user is legal; only the decision is walled off"
    )
    assert blocked["decided_by_user_id"] is None

    partner_authored = draft_classification(
        read_employee(employee["id"]),
        requested_class="FULLY_REMOTE",
        justification_code="TALENT_RETENTION",
        effective_from="2026-10-01",
    )
    assert partner_authored["created_by_user_id"] == "hrbp-1"
    validate_success(api_client.submit_classification(partner_authored["id"], HRBP))
    decided = validate_success(
        api_client.decide_classification(
            partner_authored["id"],
            classification_decision_payload("APPROVE", "HR authored, manager decided"),
            MANAGER,
        )
    )
    assert decided["state"] == "APPROVED", (
        "the user blocked on their own row may decide a row someone else authored"
    )
    assert decided["decided_by_user_id"] == "mgr-1"
    assert read_employee(employee["id"])["current_eligibility_class"] == "FULLY_REMOTE"
    assert validate_success(
        api_client.get_classification(self_authored["id"], HRBP)
    )["state"] == "PENDING_MANAGER"


def test_05_a_child_classification_create_advances_the_parent_employee_version():
    """The caller's own successful create is what makes its next request stale.

    PRD 2.8: "`POST /eligibility-classifications` must carry
    `expected_employee_version`, equal to the current `version` of the `Employee`
    named by `employee_id`."
    PRD 2.8: "When another writer has already created a classification that
    legitimately supersedes the employee's current `APPROVED` class, the employee's
    `version` has advanced and the current writer's picture of the employee is
    stale; the create is then rejected with `ERR_STALE_EMPLOYEE_VERSION` (412)."
    PRD 3.3: "A successful draft also advances the parent employee's `version` by
    one, which is precisely why the next writer's `expected_employee_version` will
    no longer match."

    Design: Corner/cross_cutting_complexity_layers/occ_on_the_employee_and_cycle_carriers_with_exact_version_accounting
    """
    staged = _one_team_and_one_unclassified_employee()
    employee = staged["employee"]
    first_version = employee["version"]
    assert first_version == 1

    get_success_data(
        api_client.create_classification(
            classification_payload(employee["id"], first_version,
                                   requested_class="HYBRID"),
            HRBP,
        )
    )
    assert read_employee(employee["id"])["version"] == 2, (
        "a child create advanced the parent employee's version"
    )

    validate_error(
        api_client.create_classification(
            classification_payload(
                employee["id"], first_version,
                requested_class="FULLY_REMOTE",
                justification_code="TALENT_RETENTION",
            ),
            HRBP,
        ),
        ApiErrorId.ERR_STALE_EMPLOYEE_VERSION.value,
        412,
    )
    assert read_employee(employee["id"])["version"] == 2, (
        "a rejected write does not advance the guard"
    )

    get_success_data(
        api_client.create_classification(
            classification_payload(
                employee["id"], 2,
                requested_class="FULLY_REMOTE",
                justification_code="TALENT_RETENTION",
            ),
            HRBP,
        )
    )
    assert read_employee(employee["id"])["version"] == 3

    assert set_status(employee["id"], "ON_LEAVE", "sabbatical")["version"] == 4
    assert set_status(employee["id"], "ACTIVE", "returned")["version"] == 5, (
        "the status machine shares the same counter as the classification writes"
    )
