"""
Rows that carry more than one state dimension at once.

A participant carries three dimensions, a placement carries two, and a support
request cycles through an information-request loop with its own round counter.
Each dimension has to move without dragging the others along with it.
"""

from test_helpers.api_errors import ERR_INFO_ROUNDS_EXHAUSTED
from test_helpers.assertions import (
    assert_int_field,
    assert_ledger_identity,
    assert_money_cents,
    assert_one_decimal_place,
    assert_opening_seat_identity,
    validate_error,
    validate_unpaginated,
)
from test_helpers.constants import (
    BARRIER_TIER_HIGH,
    BONDING_BONDED,
    BONDING_REQUESTED,
    CATEGORY_ID_FEE,
    COMPLIANCE_COMPLIANT,
    DECISION_APPROVED,
    DECISION_INFO_REQUESTED,
    EMPLOYMENT_OFFERED,
    FUNDING_POSTURE_OPEN,
    LICENSE_RELIEF_INFO_REQUESTED,
    LICENSE_RELIEF_PETITION_SUBMITTED,
    OPENING_OPEN,
    POSTURE_FROZEN,
    RELEASE_PLAN_APPROVED,
    REQUEST_APPROVED,
    REQUEST_SUBMITTED,
    STAGE_POST_RELEASE,
    SUSPENSION_SUSPENDED,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR,
    PROGRAM_DIRECTOR_ID,
)

SUSPENSION_REASON = "Missed two supervision appointments"


def _participant_mid_petition_then_suspended(api, build):
    """A released participant one petition round in, then suspended."""
    participant = build.participant_released()
    for payload in (
        f.license_relief_payload(LICENSE_RELIEF_PETITION_SUBMITTED, "31-1131"),
        f.license_relief_payload(LICENSE_RELIEF_INFO_REQUESTED),
        f.license_relief_payload(LICENSE_RELIEF_PETITION_SUBMITTED),
    ):
        validate_unpaginated(
            api.drive_license_relief(participant["id"], payload, CASE_MANAGER)
        )

    suspended = validate_unpaginated(
        api.set_suspension(
            participant["id"],
            f.suspension_payload(SUSPENSION_SUSPENDED, SUSPENSION_REASON),
            PROGRAM_DIRECTOR,
        )
    )
    return participant, suspended


def test_suspending_a_participant_leaves_stage_and_licence_relief_where_they_were(
    api, build
):
    """
    The suspension dimension moves on its own and forces the posture, while
    `stage` and `license_relief_status` keep the values they already held.

    PRD section 3.9: "A suspended participant keeps whatever `stage` it had, and
    while suspended it is barred from placement creation, offer responses, support
    requests, and enrollment with `ERR_PARTICIPANT_SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/participant_three_parallel_dimensions_evolve_independently
    """
    participant, suspended = _participant_mid_petition_then_suspended(api, build)

    assert suspended["suspension_status"] == SUSPENSION_SUSPENDED
    assert suspended["suspension_reason"] == SUSPENSION_REASON
    assert suspended["stage"] == STAGE_POST_RELEASE
    assert suspended["license_relief_status"] == LICENSE_RELIEF_PETITION_SUBMITTED
    assert suspended["engagement_posture"] == POSTURE_FROZEN
    assert suspended["actual_release_date"] == "2026-08-01"


def test_the_petition_round_counter_and_stored_occupation_code_survive_a_suspension(
    api, build
):
    """
    The licence-relief cycle keeps its own counter and its first-submission
    occupation code across an unrelated dimension's write.

    PRD section 3.9: "The cycle edge returns `INFO_REQUESTED → PETITION_SUBMITTED`,
    requires that `petition_rounds_used` is strictly below two, and increments
    `petition_rounds_used` by exactly one — so the third re-submission is refused
    with `ERR_PETITION_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/participant_three_parallel_dimensions_evolve_independently
    """
    participant, suspended = _participant_mid_petition_then_suspended(api, build)

    assert_int_field(suspended, "petition_rounds_used", 1)
    assert suspended["license_relief_occupation_code"] == "31-1131"
    assert_one_decimal_place(suspended, "doc_completeness_pct", 80.0)
    assert_one_decimal_place(suspended, "barrier_score", 66.3)
    assert suspended["barrier_tier"] == BARRIER_TIER_HIGH
    assert suspended["release_plan_status"] == RELEASE_PLAN_APPROVED


def _bonded_placement_with_an_unanswered_offer(api, build):
    """An outstanding offer whose bonding dimension has been driven to BONDED."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    participant = build.participant_released()
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"])
    placement = build.placement_offered(participant["id"], opening["id"], grant["id"])

    requested = validate_unpaginated(
        api.drive_placement_bonding(
            placement["id"], f.placement_bonding_payload(BONDING_REQUESTED), EMPLOYER_LIAISON
        )
    )
    assert requested["bonding_status"] == BONDING_REQUESTED
    bonded = validate_unpaginated(
        api.drive_placement_bonding(
            placement["id"], f.placement_bonding_payload(BONDING_BONDED), EMPLOYER_LIAISON
        )
    )
    return grant, participant, partnership, opening, placement, bonded


def test_bonding_reaches_bonded_while_the_offer_is_still_outstanding(api, build):
    """
    Bonding may be requested and confirmed before the participant has answered,
    so the two dimensions on the placement row advance independently.

    PRD section 3.6: "`NONE → REQUESTED` opens a bonding request and requires that
    `employment_status` is `OFFERED` or `ACTIVE`, so bonding may be requested while
    the offer is still outstanding; it additionally requires the employer
    partnership's `fidelity_bond_enabled` to be true, and a request against an
    unbonded partnership is refused with `ERR_FIDELITY_BOND_UNAVAILABLE`."

    Design: Difficulty/non_linear_state_machine/placement_bonding_dimension_advances_while_employment_stays_offered
    """
    grant, participant, partnership, opening, placement, bonded = (
        _bonded_placement_with_an_unanswered_offer(api, build)
    )

    assert bonded["bonding_status"] == BONDING_BONDED
    assert bonded["employment_status"] == EMPLOYMENT_OFFERED
    assert bonded["schedule_compliance"] == COMPLIANCE_COMPLIANT
    assert_int_field(bonded, "match_score", 75)
    assert_money_cents(bonded, "projected_subsidy_cents", 0)
    assert_money_cents(bonded, "actual_subsidy_cents", 0)


def test_the_bonding_dimension_moves_no_money_and_no_seat_counters(api, build):
    """
    Bonding is carried by the employer, so driving it changes neither the seat
    arithmetic nor the grant ledger.

    PRD section 3.6: "Fidelity bonding runs as a second, independent dimension on
    the placement row, driven by `to_status` and touching no money — the bond is
    carried by the employer partnership, not by the grant."

    Design: Difficulty/non_linear_state_machine/placement_bonding_dimension_advances_while_employment_stays_offered
    """
    grant, participant, partnership, opening, placement, bonded = (
        _bonded_placement_with_an_unanswered_offer(api, build)
    )

    stored_opening = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(stored_opening, "offered_count", 1)
    assert_int_field(stored_opening, "filled_count", 0)
    assert_int_field(stored_opening, "remaining_openings", 1)
    assert stored_opening["status"] == OPENING_OPEN
    assert_opening_seat_identity(stored_opening)

    stored_partnership = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert_int_field(stored_partnership, "active_placement_count", 0)

    stored_participant = validate_unpaginated(
        api.get_participant(participant["id"], CASE_MANAGER)
    )
    assert stored_participant["stage"] == STAGE_POST_RELEASE

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 0)
    assert_ledger_identity(ledger)


def _request_after_two_information_rounds(api, build):
    """A request driven through both permitted information rounds."""
    grant = build.grant(authorized_cents=100000, per_participant_cap_cents=60000)
    participant = build.participant()
    request = build.support_request(
        participant["id"],
        grant["id"],
        [f.line_item("Replacement state identification card", 8000)],
        category=CATEGORY_ID_FEE,
    )
    assert_money_cents(request, "requested_cents", 8000)
    assert_money_cents(request, "admin_fee_cents", 240)
    assert_money_cents(request, "total_charge_cents", 8240)

    for expected_rounds in (1, 2):
        validate_unpaginated(
            api.review_support_request(
                request["id"],
                f.review_payload(DECISION_INFO_REQUESTED, "Please attach the fee schedule."),
                PROGRAM_DIRECTOR,
            )
        )
        resubmitted = validate_unpaginated(
            api.resubmit_support_request(request["id"], f.resubmit_payload(), CASE_MANAGER)
        )
        assert_int_field(resubmitted, "info_rounds_used", expected_rounds)
        assert resubmitted["status"] == REQUEST_SUBMITTED
    return grant, participant, request


def test_a_third_information_request_is_refused_with_the_rounds_exhausted(api, build):
    """
    Two information rounds are all the request gets, and the refusal leaves the
    request exactly where it was.

    PRD section 3.8: "A `decision` of `INFO_REQUESTED` moves the request
    `SUBMITTED → INFO_REQUESTED`, recording `review_note` and `reviewed_by_user_id`;
    it requires that fewer than two information-request rounds have been consumed,
    so a `decision` of `INFO_REQUESTED` when `info_rounds_used` has already reached
    2 is refused with `ERR_INFO_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/support_request_info_request_cycle_exhausts_after_two_rounds
    """
    grant, participant, request = _request_after_two_information_rounds(api, build)

    refused = api.review_support_request(
        request["id"], f.review_payload(DECISION_INFO_REQUESTED), PROGRAM_DIRECTOR
    )
    validate_error(refused, ERR_INFO_ROUNDS_EXHAUSTED, 409)

    unchanged = validate_unpaginated(api.get_support_request(request["id"], CASE_MANAGER))
    assert unchanged["status"] == REQUEST_SUBMITTED
    assert_int_field(unchanged, "info_rounds_used", 2)


def test_an_exhausted_request_can_still_be_approved_and_commits_its_total(api, build):
    """
    Exhausting the information loop closes only that loop: the request remains
    approvable and its approval commits the total charge.

    PRD section 3.8: "When the grant's `funding_posture` is not `EXHAUSTED` and its
    `available_cents` is at least the request's `total_charge_cents`, the request
    moves `SUBMITTED → APPROVED`: `reviewed_by_user_id` is recorded, the grant's
    `committed_cents` rises by `total_charge_cents`, and the ledger re-runs,
    lowering `available_cents` and possibly flipping `funding_posture` from `OPEN`
    to `RESTRICTED` or to `EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/support_request_info_request_cycle_exhausts_after_two_rounds
    """
    grant, participant, request = _request_after_two_information_rounds(api, build)

    approved = validate_unpaginated(
        api.review_support_request(
            request["id"], f.review_payload(DECISION_APPROVED), PROGRAM_DIRECTOR
        )
    )
    assert approved["status"] == REQUEST_APPROVED
    assert_int_field(approved, "info_rounds_used", 2)
    assert_money_cents(approved, "total_charge_cents", 8240)
    assert approved["reviewed_by_user_id"] == PROGRAM_DIRECTOR_ID

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 8240)
    assert_money_cents(ledger, "available_cents", 91760)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_int_field(ledger, "open_request_count", 0)
    assert_ledger_identity(ledger)
