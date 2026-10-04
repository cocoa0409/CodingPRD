"""Difficulty depth index: non-linear state machines — the qualification
probation/recertification loop and the substitution-request review-round
cycle.
"""
from test_helpers import (
    COAT_APPLIED_AT,
    CURE_CLOCK_TWO_COATS,
    PROBATION_PENALTY,
    SECOND_COAT_APPLIED_AT,
    ApiClient,
    adjudicate,
    assert_cents,
    assert_score,
    begin_evidence,
    claim_warranty,
    create_substitution_request,
    create_world,
    decide_payload,
    drive_to_prep_approved,
    file_inspection_report,
    issue_warranty,
    read_applicator,
    read_investigation,
    read_qualification,
    read_substitution_request,
    read_warranty,
    record_application,
    set_clock,
    advance_clock_and_mark_cured,
    complete_work_order,
    create_coating_system,
    TECHNICAL_SERVICE_ENGINEER_HEADERS,
    OWNER_REPRESENTATIVE_HEADERS,
    validate_success,
)


def test_applicator_qualification_probation_recertification_loop(api: ApiClient):
    """PRD §3.3: "When a failure investigation concludes that a warranty claim
    arose from application error, the applicator qualification that was used
    on the failed work order moves automatically from `CERTIFIED` to
    `PROBATION` and the applicator's score takes the 150-point probation
    penalty."
    PRD §3.3: "accumulating 2 consecutive accepted inspection reports after
    entering probation automatically restores the qualification to
    `CERTIFIED`".

    Design: Difficulty/non_linear_state_machine/applicator_qualification_probation_recertification_loop
    """
    world = create_world(
        api,
        system_overrides={"system_code": "SW-PROB-200", "coat_count": 2},
        applicator_overrides={"company_name": "Piperack Painters"},
    )
    applicator_id = world["applicator"]["id"]
    qualification_id = world["qualification"]["id"]

    wo1 = drive_to_prep_approved(api, world, asset_zone="RACK-NORTH")
    wo2 = drive_to_prep_approved(api, world, asset_zone="RACK-SOUTH")
    w1c1 = record_application(api, wo1["id"], applicator_id, coat_number=1, applied_at=COAT_APPLIED_AT)
    w1c2 = record_application(api, wo1["id"], applicator_id, coat_number=2, applied_at=SECOND_COAT_APPLIED_AT)
    w2c1 = record_application(api, wo2["id"], applicator_id, coat_number=1, applied_at=COAT_APPLIED_AT)
    w2c2 = record_application(api, wo2["id"], applicator_id, coat_number=2, applied_at=SECOND_COAT_APPLIED_AT)
    set_clock(api, CURE_CLOCK_TWO_COATS)
    for coat in (w1c1, w1c2, w2c1, w2c2):
        advance_clock_and_mark_cured(
            api, coat["work_order_id"], coat["id"], applicator_id, CURE_CLOCK_TWO_COATS
        )

    # Two ACCEPTED reports on wo1: score 500 + 10 + 10 = 520, streak 2.
    file_inspection_report(api, wo1["id"], w1c1["id"])
    file_inspection_report(api, wo1["id"], w1c2["id"])
    complete_work_order(api, world["project"]["id"], wo1["id"])

    warranty = issue_warranty(
        api, world["project"]["id"], wo1["id"], term_years=5, exposure_cents=80_000
    )
    claim_warranty(api, world["project"]["id"], warranty["id"], defect_mode="ADHESION_LOSS")
    investigation = begin_evidence(api, warranty["id"], read_investigation(api, warranty["id"])["id"])

    investigation = adjudicate(
        api, warranty["id"], investigation["id"], "APPLICATION_ERROR", adjudicated_fault_pct=0
    )

    assert investigation["status"] == "ADJUDICATED_APPLICATION_ERROR"
    resolved = read_warranty(api, warranty["id"])
    assert resolved["status"] == "RESOLVED"
    assert_cents(resolved["material_share_cents"], 0, "material_share_cents")
    assert_cents(resolved["application_share_cents"], 80_000, "application_share_cents")

    qualification = read_qualification(api, applicator_id, qualification_id)
    assert qualification["status"] == "PROBATION", "CERTIFIED -> PROBATION on application error"
    assert_score(
        read_applicator(api, applicator_id)["quality_history_score"],
        520 - PROBATION_PENALTY,
    )

    # First post-probation ACCEPTED report: one of the required two.
    file_inspection_report(api, wo2["id"], w2c1["id"])
    assert read_qualification(api, applicator_id, qualification_id)["status"] == "PROBATION"

    # Second consecutive post-probation ACCEPTED report closes the loop.
    file_inspection_report(api, wo2["id"], w2c2["id"])
    qualification = read_qualification(api, applicator_id, qualification_id)
    assert qualification["status"] == "CERTIFIED", "PROBATION -> CERTIFIED after 2 accepts"
    assert qualification["suspension_count"] == 0, "the loop never enters SUSPENDED"
    applicator = read_applicator(api, applicator_id)
    assert_score(applicator["quality_history_score"], 370 + 10 + 10)
    assert applicator["consecutive_passed_inspections"] == 4


def test_substitution_request_review_round_cycle(api: ApiClient):
    """PRD §3.4: "The request is born `SUBMITTED` with `review_round` at 1".
    PRD §3.4: "The owner answers by resubmitting with a fresh `rationale`,
    which returns the request from `MORE_INFO_REQUESTED` to `SUBMITTED` and
    increments `review_round` by 1."

    Design: Difficulty/non_linear_state_machine/substitution_request_review_round_cycle
    """
    world = create_world(
        api,
        asset_type="STRUCTURAL_STEEL",
        system_overrides={"system_code": "SW-HOUSE-300"},
    )
    competitor = create_coating_system(
        api,
        system_code="CMP-ALT-300",
        manufacturer_name="Competitor Coatings",
        is_competitor_system=True,
        base_voc_gpl=320,
    )
    request = create_substitution_request(
        api, world["spec"]["id"], competitor["id"], rationale="lead-time advantage",
        max_review_rounds=3,
    )
    spec_id, request_id = world["spec"]["id"], request["id"]

    validate_success(api.start_substitution_review(spec_id, request_id, TECHNICAL_SERVICE_ENGINEER_HEADERS))
    request = read_substitution_request(api, request_id)
    assert request["status"] == "UNDER_REVIEW" and request["review_round"] == 1

    validate_success(api.request_substitution_info(spec_id, request_id, TECHNICAL_SERVICE_ENGINEER_HEADERS))
    request = read_substitution_request(api, request_id)
    assert request["status"] == "MORE_INFO_REQUESTED" and request["review_round"] == 1, (
        "the round is not consumed until resubmit"
    )

    validate_success(
        api.resubmit_substitution_request(
            spec_id, request_id, {"rationale": "added freight quote"},
            OWNER_REPRESENTATIVE_HEADERS,
        )
    )
    request = read_substitution_request(api, request_id)
    assert request["status"] == "SUBMITTED" and request["review_round"] == 2, (
        "cycle re-entry increments review_round"
    )

    validate_success(api.start_substitution_review(spec_id, request_id, TECHNICAL_SERVICE_ENGINEER_HEADERS))
    validate_success(
        api.decide_substitution_request(
            spec_id, request_id,
            decide_payload("REJECT", "house system retained"),
            TECHNICAL_SERVICE_ENGINEER_HEADERS,
        )
    )
    request = read_substitution_request(api, request_id)
    assert request["status"] == "REJECTED" and request["review_round"] == 2
