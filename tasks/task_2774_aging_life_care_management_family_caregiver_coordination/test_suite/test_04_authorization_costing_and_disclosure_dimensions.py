"""Pinned costing order on a vendor engagement, and the two state dimensions an
authorization advances along independently.
"""
from test_helpers import (
    acknowledge_conflict_of_interest,
    activate_service_authorization,
    api_client,
    authorization_state_payload,
    authorize_service_authorization,
    disclose_conflict_of_interest,
    make_practice_supervisor_headers,
    read_authorization,
    read_care_plan,
    read_client,
    setup_proposed_authorization_scenario,
    suspend_service_authorization,
    uniform_domain_scores,
    validate_error,
)


def _fifty_hour_engagement():
    """An engagement buying fifty caregiver-hours at 3,800 cents an hour, which
    is the 190,000-cent base cost the tier rule is pinned to.
    """
    return setup_proposed_authorization_scenario(
        clock="2026-08-07T09:00:00Z",
        client_overrides={
            "full_name": "Bertram Oyelaran-Vance",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
        },
        vendor_overrides={
            "name": "Northgate Home Care",
            "vendor_type": "HOME_CARE",
            "has_referral_relationship": False,
        },
        scores=uniform_domain_scores(2),
        coverage_start="2026-09-01T00:00:00Z",
        coverage_end="2026-09-03T02:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=3_800,
    )


def test_01_coverage_hours_discard_the_partial_hour_and_scale_by_caregivers():
    """A fifty-hour, two-minute window staffed by a single caregiver buys fifty
    whole caregiver-hours, and the base cost follows from them.

    PRD: "First, `coverage_hours` is the number of whole hours between `coverage_start` and `coverage_end`, with any partial hour discarded downward, multiplied by `concurrent_caregivers`."

    Design: Difficulty/combinatorial_formula/coordination_fee_tier_pinned_to_base_cost_mode_c
    """
    scenario = _fifty_hour_engagement()
    authorization = scenario.authorization

    assert authorization["coverage_hours"] == 50
    assert authorization["base_cost_cents"] == 190_000
    assert authorization["concurrent_caregivers"] == 1
    assert authorization["hourly_cost_cents"] == 3_800


def test_02_the_coordination_fee_tier_is_selected_from_the_base_cost():
    """190,000 cents sits in the first tier and takes 8 percent, even though the
    resulting total would read as a second-tier base.

    PRD: "Selecting the tier from the total would be circular — the total depends on the fee, the fee depends on the tier — and is wrong: a base cost of 190,000 cents sits in the first tier and takes an 8 percent fee of 15,200 cents even though the resulting total of 205,200 cents would, read as a base, have fallen in the second tier."

    Design: Difficulty/combinatorial_formula/coordination_fee_tier_pinned_to_base_cost_mode_c
    """
    scenario = _fifty_hour_engagement()
    authorization = scenario.authorization

    assert authorization["coordination_fee_cents"] == 15_200
    assert authorization["coordination_fee_cents"] != 11_400
    assert authorization["total_projected_cost_cents"] == 205_200


def test_03_a_vendor_without_a_referral_relationship_owes_no_disclosure():
    """The disclosure dimension opens at `NOT_REQUIRED` with no statement minted,
    while the commercial dimension opens at `PROPOSED`.

    PRD: "The disclosure dimension is initialised from the vendor: when the vendor's `has_referral_relationship` is true, `coi_status` is set to `PENDING_DISCLOSURE` and a `disclosure_text` statement is minted at creation; when it is false, `coi_status` is set to `NOT_REQUIRED` and `disclosure_text` stays null."

    Design: Difficulty/combinatorial_formula/coordination_fee_tier_pinned_to_base_cost_mode_c
    """
    scenario = _fifty_hour_engagement()
    authorization = scenario.authorization

    assert authorization["auth_status"] == "PROPOSED"
    assert authorization["coi_status"] == "NOT_REQUIRED"
    assert authorization["disclosure_text"] is None
    assert authorization["suspension_reason"] == "NONE"
    assert authorization["termination_reason"] == "NONE"


def _referred_engagement():
    """A PROPOSED eight-hour engagement of a vendor the practice takes a referral
    fee from, so the disclosure dimension opens at `PENDING_DISCLOSURE`.
    """
    return setup_proposed_authorization_scenario(
        clock="2026-08-08T09:00:00Z",
        client_overrides={
            "full_name": "Cornelia Achterberg",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
            "authorized_concurrent_caregivers": 2,
        },
        vendor_overrides={
            "name": "Lakeside Legal Advocates",
            "vendor_type": "LEGAL",
            "has_referral_relationship": True,
            "referral_fee_pct": 5,
        },
        scores=uniform_domain_scores(1),
        coverage_start="2026-09-01T08:00:00Z",
        coverage_end="2026-09-01T16:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=4_000,
    )


def test_04_a_referred_vendor_opens_the_disclosure_dimension_and_elevates_risk():
    """Creation mints the disclosure statement and puts the obligation at
    `PENDING_DISCLOSURE`, which is itself an elevated-risk trigger.

    PRD: "Because a pending disclosure is one of the `ELEVATED` triggers, the client's `risk_posture` is recomputed; the parent care plan's `version` and the client's `version` each increase by 1."

    Design: Difficulty/non_linear_state_machine/service_authorization_parallel_dimensions_evolve_independently
    """
    scenario = _referred_engagement()

    assert scenario.authorization["auth_status"] == "PROPOSED"
    assert scenario.authorization["coi_status"] == "PENDING_DISCLOSURE"
    assert scenario.authorization["disclosure_text"] is not None
    assert scenario.authorization["coi_acknowledged_by_contact_id"] is None
    assert read_client(scenario.client_id)["risk_posture"] == "ELEVATED"


def test_05_authorizing_before_acknowledgement_leaves_the_commercial_dimension_still():
    """The one point at which the commercial dimension reads the disclosure one:
    the engagement cannot be authorized while the family has not acknowledged.

    PRD: "It requires, in this order: the parent care plan is still `ACTIVE`, else `ERR_CARE_PLAN_NOT_ACTIVE`; the client's `status` is neither `SUSPENDED_NONPAYMENT` nor `DISCHARGED`, else `ERR_CLIENT_NOT_IN_SERVICE`; the vendor's `standing` is not `BARRED`, else `ERR_VENDOR_BARRED`; the authorization's `coi_status` is either `NOT_REQUIRED` or `ACKNOWLEDGED`, else `ERR_COI_NOT_ACKNOWLEDGED`; aggregate coverage capacity holds, else `ERR_COVERAGE_CAPACITY_EXCEEDED`; and the client's `retainer_balance_cents` is at least the client's `retainer_floor_cents`, else `ERR_RETAINER_INSUFFICIENT` — the one payment-required rejection in the whole API."

    Design: Difficulty/non_linear_state_machine/service_authorization_parallel_dimensions_evolve_independently
    """
    scenario = _referred_engagement()
    response = api_client.patch_service_authorization_state(
        scenario.authorization_id,
        authorization_state_payload("AUTHORIZED"),
        make_practice_supervisor_headers(scenario.supervisor_id),
    )
    validate_error(response, "ERR_COI_NOT_ACKNOWLEDGED", 422)

    unchanged = read_authorization(scenario.authorization_id)
    assert unchanged["auth_status"] == "PROPOSED"
    assert unchanged["coi_status"] == "PENDING_DISCLOSURE"
    assert read_client(scenario.client_id)["authorized_coverage_hours"] == 0


def test_06_the_disclosure_dimension_advances_while_the_commercial_one_stands_still():
    """Disclosing and then acknowledging carries the obligation all the way to
    `ACKNOWLEDGED` without the engagement ever leaving `PROPOSED`.

    PRD: "The two do not gate each other except at one point: a `PROPOSED` authorization can reach `ACKNOWLEDGED` on the disclosure dimension while sitting still on the commercial one, and an `AUTHORIZED` authorization can perfectly well remain at `NOT_REQUIRED`; only the step from `PROPOSED` to `AUTHORIZED` reads the disclosure dimension at all."

    Design: Difficulty/non_linear_state_machine/service_authorization_parallel_dimensions_evolve_independently
    """
    scenario = _referred_engagement()

    disclosed = disclose_conflict_of_interest(
        scenario.authorization_id, scenario.care_manager_id
    )
    assert disclosed["coi_status"] == "DISCLOSED"
    assert disclosed["auth_status"] == "PROPOSED"

    acknowledged = acknowledge_conflict_of_interest(
        scenario.authorization_id, scenario.surrogate_id
    )
    assert acknowledged["coi_status"] == "ACKNOWLEDGED"
    assert acknowledged["auth_status"] == "PROPOSED"
    assert acknowledged["coi_acknowledged_by_contact_id"] == scenario.surrogate_id

    # The activated plan still has nobody authorized to deliver it.
    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is True
    assert read_client(scenario.client_id)["risk_posture"] == "ELEVATED"


def test_07_authorizing_after_acknowledgement_closes_the_coverage_gap():
    """With the disclosure discharged the engagement authorizes, the hours land on
    the client, and the disclosure dimension is not disturbed.

    PRD: "On success the authorization's `coverage_hours` is added to the client's `authorized_coverage_hours`, the parent plan's `coverage_gap_flag` is recomputed and becomes false, the client's `risk_posture` is recomputed, and the authorization's `version`, the care plan's `version` and the client's `version` each increase by 1."

    Design: Difficulty/non_linear_state_machine/service_authorization_parallel_dimensions_evolve_independently
    """
    scenario = _referred_engagement()
    disclose_conflict_of_interest(scenario.authorization_id, scenario.care_manager_id)
    acknowledge_conflict_of_interest(scenario.authorization_id, scenario.surrogate_id)

    authorized = authorize_service_authorization(
        scenario.authorization_id, scenario.supervisor_id
    )
    assert authorized["auth_status"] == "AUTHORIZED"
    assert authorized["coi_status"] == "ACKNOWLEDGED"
    assert authorized["coi_acknowledged_by_contact_id"] == scenario.surrogate_id

    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is False
    client = read_client(scenario.client_id)
    assert client["authorized_coverage_hours"] == 8
    assert client["risk_posture"] == "ROUTINE"


def test_08_suspending_withdraws_the_hours_and_leaves_the_disclosure_alone():
    """The commercial dimension keeps moving after the disclosure dimension has
    reached its terminal state, and only the coverage totals respond.

    PRD: "In every case the authorization's `coverage_hours` is subtracted from the client's `authorized_coverage_hours`, the parent plan's `coverage_gap_flag` is recomputed, the client's `risk_posture` is recomputed, and the authorization's `version` increases by 1."

    Design: Difficulty/non_linear_state_machine/service_authorization_parallel_dimensions_evolve_independently
    """
    scenario = _referred_engagement()
    disclose_conflict_of_interest(scenario.authorization_id, scenario.care_manager_id)
    acknowledge_conflict_of_interest(scenario.authorization_id, scenario.surrogate_id)
    authorize_service_authorization(scenario.authorization_id, scenario.supervisor_id)

    activated = activate_service_authorization(
        scenario.authorization_id, scenario.care_manager_id
    )
    assert activated["auth_status"] == "ACTIVE"
    assert activated["coi_status"] == "ACKNOWLEDGED"

    suspended = suspend_service_authorization(
        scenario.authorization_id, scenario.care_manager_id
    )
    assert suspended["auth_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "FAMILY_REQUEST"
    assert suspended["coi_status"] == "ACKNOWLEDGED"

    client = read_client(scenario.client_id)
    assert client["authorized_coverage_hours"] == 0
    assert read_care_plan(scenario.care_plan_id)["coverage_gap_flag"] is True
    assert client["risk_posture"] == "ELEVATED"
