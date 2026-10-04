"""Business validation rules: capacity, window, escrow, staffing, goals."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    create_advisor, create_territory, create_administrator,
    create_site_approved_branch, create_validated_advisor,
    setup_retiring_advisor_with_transfer,
    post_production, make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_territory_capacity_boundary():
    """PRD §3.2: "Two guards apply at logging time, evaluated in this order:
    capacity first, then window. If the count of non-archived contacts in the
    territory already equals `household_capacity`, the registration is
    rejected with `ERR_TERRITORY_CAPACITY`."

    Design: Corner/validations/territory_capacity_boundary
    """
    advisor = create_advisor()
    territory = create_territory(household_capacity=1)
    validate_success(api_client.assign_territory(
        territory["id"],
        {
            "advisor_id": advisor["id"],
            "assignment_start": "2026-01-01T00:00:00Z",
            "assignment_end": "2027-01-01T00:00:00Z",
        },
        ADMIN,
    ))
    headers = make_advisor_headers(advisor["id"])

    validate_success(api_client.create_contact(
        territory["id"],
        {
            "household_address": "1 First Ave",
            "contact_outcome": "PITCHED",
            "contacted_at": "2026-03-01T10:00:00Z",
        },
        headers,
    ), expected_status=201)

    validate_error(
        api_client.create_contact(
            territory["id"],
            {
                "household_address": "2 Second Ave",
                "contact_outcome": "NO_ANSWER",
                "contacted_at": "2026-03-02T10:00:00Z",
            },
            headers,
        ),
        ApiErrorId.ERR_TERRITORY_CAPACITY,
    )


def test_contact_outside_assignment_window():
    """PRD §3.2: "If `contacted_at` falls outside the current assignment
    interval — before `assignment_start`, or at or after `assignment_end` when
    an end is set — the contact is rejected with
    `ERR_CONTACT_OUTSIDE_WINDOW`."

    Design: Corner/validations/contact_outside_assignment_window
    """
    advisor = create_advisor()
    territory = create_territory(household_capacity=50)
    validate_success(api_client.assign_territory(
        territory["id"],
        {
            "advisor_id": advisor["id"],
            "assignment_start": "2026-01-01T00:00:00Z",
            "assignment_end": "2027-01-01T00:00:00Z",
        },
        ADMIN,
    ))
    headers = make_advisor_headers(advisor["id"])

    validate_error(
        api_client.create_contact(
            territory["id"],
            {
                "household_address": "5 Past Ln",
                "contact_outcome": "PITCHED",
                "contacted_at": "2025-12-31T23:59:59Z",
            },
            headers,
        ),
        ApiErrorId.ERR_CONTACT_OUTSIDE_WINDOW,
    )

    # The inclusive start boundary passes.
    validate_success(api_client.create_contact(
        territory["id"],
        {
            "household_address": "6 Start Ave",
            "contact_outcome": "PITCHED",
            "contacted_at": "2026-01-01T00:00:00Z",
        },
        headers,
    ), expected_status=201)


def test_escrow_insufficient_at_acceptance():
    """PRD §3.7: "Acceptance additionally requires escrow sufficiency:
    `escrow_deposit_cents` must be at least ten percent of the current
    `offer_price_cents`, computed as the offer price multiplied by 0.10 and
    rounded half-up to whole cents; insufficient escrow is rejected with
    `ERR_ESCROW_INSUFFICIENT`."

    Design: Corner/validations/escrow_insufficient_at_acceptance
    """
    # Offer is 1800000; ten percent is 180000.
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer(
        escrow_deposit_cents=179999,
    )
    validate_error(
        api_client.accept_transfer(
            transfer["id"], make_advisor_headers(successor["id"])
        ),
        ApiErrorId.ERR_ESCROW_INSUFFICIENT,
    )
    fresh = get_success_data(api_client.get_goodwill_transfer(transfer["id"], ADMIN))
    assert fresh["status"] == "OFFERED"


def test_branch_occupied_single_advisor_invariant():
    """PRD §3.3: "A validated advisor is assigned to a branch in the
    `SITE_APPROVED` or `OPEN` operating state, provided three conditions hold
    — the advisor is `VALIDATED` (otherwise `ERR_ADVISOR_NOT_VALIDATED`), the
    branch has no other advisor whose status is neither `RETIRED` nor
    `TERMINATED` (otherwise `ERR_BRANCH_OCCUPIED`), and the branch's territory
    is either `OPEN` or already assigned to this advisor."

    Design: Corner/validations/branch_occupied_single_advisor_invariant
    """
    branch, territory = create_site_approved_branch()
    advisor_a = create_validated_advisor()
    advisor_b = create_validated_advisor()
    validate_success(
        api_client.assign_branch(advisor_a["id"], {"branch_id": branch["id"]}, ADMIN)
    )

    validate_error(
        api_client.assign_branch(advisor_b["id"], {"branch_id": branch["id"]}, ADMIN),
        ApiErrorId.ERR_BRANCH_OCCUPIED,
    )
    assert get_success_data(
        api_client.get_advisor(advisor_b["id"], ADMIN)
    )["status"] == "VALIDATED"


def test_boa_already_assigned_invariant():
    """PRD §2.9: "The one-advisor model is enforced as a hard invariant: a
    branch may host at most one advisor whose status is anything other than
    `RETIRED` or `TERMINATED`, and symmetrically a branch may have at most one
    `ACTIVE` administrator, with each administrator serving at most one
    branch."
    PRD §3.3: "Assigning an administrator to a branch names the hire through
    `administrator_id` and requires the administrator to be `HIRED` and the
    branch to have no `ACTIVE` administrator — a second active assignment is
    rejected with `ERR_BOA_ALREADY_ASSIGNED` — and moves the administrator
    `HIRED → ACTIVE` with `branch_id` set; if an advisor is already assigned,
    the branch becomes `FULLY_STAFFED`."

    Design: Corner/validations/boa_already_assigned_invariant
    """
    territory = create_territory()
    from test_helpers import create_branch
    branch, _ = create_branch(territory["id"])
    boa_one = create_administrator()
    boa_two = create_administrator()

    validate_success(api_client.assign_administrator(
        branch["id"], {"administrator_id": boa_one["id"]}, ADMIN,
    ))
    validate_error(
        api_client.assign_administrator(
            branch["id"], {"administrator_id": boa_two["id"]}, ADMIN,
        ),
        ApiErrorId.ERR_BOA_ALREADY_ASSIGNED,
    )
    assert get_success_data(
        api_client.get_administrator(boa_two["id"], ADMIN)
    )["status"] == "HIRED"


def test_forced_pass_with_unmet_goal_rejected():
    """PRD §3.1: "An administrator may force an outcome by supplying
    `force_outcome`, but forcing `PASS` when the computed production falls
    short of the goal is rejected with `ERR_GOAL_NOT_MET`."

    Design: Corner/validations/forced_pass_with_unmet_goal_rejected
    """
    advisor = create_advisor()
    program = get_success_data(api_client.enroll_training(
        advisor["id"],
        {"goal_cents": 10000, "start_date": "2026-01-05T00:00:00Z"},
        ADMIN,
    ), expected_status=201)
    post_production(advisor["id"], 5000, "2026-02-01T00:00:00Z")
    get_success_data(
        api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    )

    validate_error(
        api_client.evaluate_milestone(
            program["id"],
            {"window_end": "2026-04-05T00:00:00Z", "force_outcome": "PASS"},
            ADMIN,
        ),
        ApiErrorId.ERR_GOAL_NOT_MET,
    )
    assert get_success_data(
        api_client.get_training_program(program["id"], ADMIN)
    )["status"] == "MILESTONE_PENDING"


def test_second_consecutive_fail_terminates_trainee():
    """PRD §3.1: "The loop terminates harshly: if a milestone evaluation fails
    and an earlier `FAIL` evaluation already exists for the same program — a
    second failing cycle — the program moves `MILESTONE_PENDING → FAILED` into
    the terminal `FAILED` status and the advisor is terminated outright
    (`TRAINEE → TERMINATED`)."

    Design: Corner/validations/second_consecutive_fail_terminates_trainee
    """
    advisor = create_advisor()
    program = get_success_data(api_client.enroll_training(
        advisor["id"],
        {"goal_cents": 10000, "start_date": "2026-01-05T00:00:00Z"},
        ADMIN,
    ), expected_status=201)
    post_production(advisor["id"], 100, "2026-02-01T00:00:00Z")

    get_success_data(
        api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    )
    first = validate_success(
        api_client.evaluate_milestone(
            program["id"], {"window_end": "2026-03-01T00:00:00Z"}, ADMIN,
        ),
        expected_status=201,
    )
    assert first["outcome"] == "FAIL"
    assert get_success_data(
        api_client.get_training_program(program["id"], ADMIN)
    )["status"] == "REMEDIATION"

    get_success_data(
        api_client.submit_milestone(program["id"], make_advisor_headers(advisor["id"]))
    )
    second = validate_success(
        api_client.evaluate_milestone(
            program["id"], {"window_end": "2026-04-01T00:00:00Z"}, ADMIN,
        ),
        expected_status=201,
    )
    assert second["outcome"] == "FAIL"
    assert get_success_data(
        api_client.get_training_program(program["id"], ADMIN)
    )["status"] == "FAILED"
    assert get_success_data(
        api_client.get_advisor(advisor["id"], ADMIN)
    )["status"] == "TERMINATED"
