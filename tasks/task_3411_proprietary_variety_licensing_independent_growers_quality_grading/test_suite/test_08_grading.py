"""Quality grading: band boundaries, JUICE/REJECT, receive gate, four-eyes
segregation, double-certify lockdown, and the dispute-regrade cycle."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    grade_payload,
    set_clock, get_harvest_lot, create_lot_in_transit, receive_lot,
    submit_grade, certify_lot, dispute_grade,
    setup_lot_in_transit, setup_lot_received, setup_lot_submitted,
    setup_lot_certified,
    make_quality_grader_headers, get_success_data,
    GRADER_SUBMITTER, GRADER_CERTIFIER, GRADER_THIRD,
)


def _two_received_lots(api):
    """Canonical chain through P1 confirmed; lots HA and HB both received
    (harvest 06:00, receipt 12:00, pulp 3.0) and still UNGRADED."""
    bundle = setup_lot_received()  # HA received
    hb = create_lot_in_transit(bundle["planting"], bundle["grower"],
                               gross_weight_kg=500, tare_weight_kg=50)
    hb = receive_lot(hb["id"])
    bundle["hb"] = hb
    return bundle


def test_grade_brix_exactly_11_0_premium(api):
    """PRD section 3.7: "`PREMIUM`: `flavor_brix` at least 11.0, `firmness_g`
    at least 350, `appearance_score` at least 85, and `defect_pct` at most 3.0."
    PRD section 3.7: "the first band whose bounds all hold wins and every bound
    is inclusive".

    Design: Difficulty/boundary_precision_check/grade_brix_boundary_exactly_11_0
    """
    bundle = setup_lot_received()
    data = submit_grade(bundle["harvest_lot"]["id"], flavor_brix=11.0,
                        firmness_g=350, appearance_score=85, defect_pct=3.0)
    assert data["grade"] == "PREMIUM"
    assert data["pack_designation"] == "PREMIUM"


def test_grade_brix_10_9_drops_to_standard(api):
    """PRD section 3.7: "`PREMIUM`: `flavor_brix` at least 11.0, `firmness_g`
    at least 350, `appearance_score` at least 85, and `defect_pct` at most
    3.0."
    PRD section 3.7: "`STANDARD`: `flavor_brix` at least 9.0, `firmness_g` at
    least 300, `appearance_score` at least 70, and `defect_pct` at most 6.0."

    Design: Difficulty/boundary_precision_check/grade_brix_boundary_exactly_11_0
    """
    bundle = setup_lot_received()
    data = submit_grade(bundle["harvest_lot"]["id"], flavor_brix=10.9,
                        firmness_g=350, appearance_score=85, defect_pct=3.0)
    assert data["grade"] == "STANDARD"
    assert data["pack_designation"] == "STANDARD"


def test_grade_standard_process_defect_boundary(api):
    """PRD section 3.7: "`STANDARD`: `flavor_brix` at least 9.0, `firmness_g`
    at least 300, `appearance_score` at least 70, and `defect_pct` at most 6.0."
    PRD section 3.7: "`PROCESS`: `flavor_brix` at least 7.0, `firmness_g` at
    least 250, `appearance_score` at least 50, and `defect_pct` at most 12.0."

    Design: Corner/calculations/grade_standard_process_defect_boundary
    """
    bundle = _two_received_lots(api)
    ha = submit_grade(bundle["harvest_lot"]["id"], flavor_brix=9.0,
                      firmness_g=300, appearance_score=70, defect_pct=6.0)
    assert ha["grade"] == "STANDARD"
    assert ha["pack_designation"] == "STANDARD"
    hb = submit_grade(bundle["hb"]["id"], flavor_brix=9.0, firmness_g=300,
                      appearance_score=70, defect_pct=6.1)
    assert hb["grade"] == "PROCESS", "defect 6.1 > 6.0 drops out of STANDARD"
    assert hb["pack_designation"] == "PROCESS"


def test_grade_juice_and_reject_bands(api):
    """PRD section 3.7: "`JUICE`: `flavor_brix` at least 5.0 and `defect_pct`
    at most 20.0 — firmness and appearance carry no bounds at this tier."
    PRD section 3.7: "Anything failing all four bands is graded `REJECT`."
    PRD section 3.7: "a certified `REJECT` grade moves it `RECEIVED →
    REJECTED`."

    Design: Corner/calculations/grade_juice_and_reject_bands
    """
    bundle = _two_received_lots(api)
    ha = submit_grade(bundle["harvest_lot"]["id"], flavor_brix=6.0,
                      firmness_g=200, appearance_score=30, defect_pct=15.0)
    assert ha["grade"] == "JUICE"
    hb = submit_grade(bundle["hb"]["id"], flavor_brix=4.9, firmness_g=200,
                      appearance_score=30, defect_pct=25.0)
    assert hb["grade"] == "REJECT"
    certified = certify_lot(bundle["hb"]["id"])
    assert certified["lot_status"] == "REJECTED"
    assert certified["grade_status"] == "CERTIFIED"


def test_grade_before_receive_rejected(api):
    """PRD section 3.7: "Submission requires the lot's `lot_status` to be
    `RECEIVED` — otherwise `ERR_LOT_NOT_RECEIVED`".

    Design: Corner/errors/grade_before_receive_rejected
    """
    bundle = setup_lot_in_transit()
    resp = api.grade_harvest_lot(bundle["harvest_lot"]["id"], grade_payload(),
                                 make_quality_grader_headers(GRADER_SUBMITTER))
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_RECEIVED)
    lot = get_harvest_lot(bundle["harvest_lot"]["id"])
    assert lot["grade_status"] == "UNGRADED"
    assert lot["grade_version"] == 0
    assert lot["grade"] is None


def test_double_certify_rejected(api):
    """PRD section 3.7: "A `QualityGrader` certifies a `SUBMITTED` grade, moving
    the grade dimension `SUBMITTED → CERTIFIED`".
    PRD section 2.8: "the generic `ERR_INVALID_STATE` (which covers
    terminal-state lockdown and repeated transitions)".

    Design: Corner/errors/double_certify_rejected
    """
    bundle = setup_lot_certified()  # certified by qg-2
    resp = api.certify_grade(bundle["harvest_lot"]["id"],
                             make_quality_grader_headers(GRADER_THIRD))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    lot = get_harvest_lot(bundle["harvest_lot"]["id"])
    assert lot["grade_status"] == "CERTIFIED"
    assert lot["certified_by_user_id"] == "qg-2"


def test_segregation_certifier_equals_submitter(api):
    """PRD section 3.7: "a certifier who submitted or received the lot is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_certifier_equals_submitter
    """
    bundle = setup_lot_submitted()  # submitted by qg-1, received by co-1
    resp = api.certify_grade(bundle["harvest_lot"]["id"],
                             make_quality_grader_headers(GRADER_SUBMITTER))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    data = certify_lot(bundle["harvest_lot"]["id"], certifier_id=GRADER_CERTIFIER)
    assert data["grade_status"] == "CERTIFIED"
    assert data["certified_by_user_id"] == "qg-2"


def test_segregation_certifier_equals_receiver(api):
    """PRD section 3.7: "only when the certifier's `X-User-ID` differs from both
    the lot's `submitted_by_user_id` and its `received_by_user_id`; a certifier
    who submitted or received the lot is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_certifier_equals_receiver
    """
    bundle = setup_lot_submitted()  # received by co-1
    resp = api.certify_grade(bundle["harvest_lot"]["id"],
                             make_quality_grader_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    lot = get_harvest_lot(bundle["harvest_lot"]["id"])
    assert lot["grade_status"] == "SUBMITTED"
    assert lot["certified_by_user_id"] is None


def test_regrade_cycle_dispute_then_fresh_submission(api):
    """PRD section 3.7: "A dispute moves the grade dimension `CERTIFIED →
    DISPUTED` and records the reason in `grade_dispute_reason`."
    PRD section 3.7: "A regrade replaces the prior scores with the new ones,
    recomputes the `grade` by the same band rules, increments `grade_version`
    by 1, refreshes `submitted_by_user_id` and `grade_submitted_at`, and resets
    `certified_by_user_id` to null so a fresh certification must follow."

    Design: Difficulty/non_linear_state_machine/harvest_lot_grade_regrade_cycle
    """
    bundle = setup_lot_certified()  # PREMIUM v1, submitted qg-1, certified qg-2
    lot_id = bundle["harvest_lot"]["id"]
    disputed = dispute_grade(lot_id, bundle["grower"],
                             reason="firmness gauge miscalibrated")
    assert disputed["grade_status"] == "DISPUTED"
    assert disputed["lot_status"] == "GRADED"
    assert disputed["grade_dispute_reason"] == "firmness gauge miscalibrated"
    resp = api.certify_grade(lot_id, make_quality_grader_headers(GRADER_CERTIFIER))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE,
                   409)  # no DISPUTED → CERTIFIED edge
    regraded = submit_grade(lot_id, flavor_brix=10.0, firmness_g=320,
                            appearance_score=75, defect_pct=4.0)
    assert regraded["grade_status"] == "SUBMITTED"
    assert regraded["grade_version"] == 2
    assert regraded["grade"] == "STANDARD", "brix 10.0 drops out of PREMIUM"
    assert regraded["pack_designation"] == "STANDARD"
    assert regraded["certified_by_user_id"] is None
    assert regraded["submitted_by_user_id"] == "qg-1"


def test_regrade_cycle_closes_with_fresh_certification(api):
    """PRD section 3.7: "The cycle `SUBMITTED → CERTIFIED → DISPUTED →
    SUBMITTED` may repeat without limit."
    PRD section 3.7: "Certification records `certified_by_user_id` and drives
    the lot dimension: a certified grade other than `REJECT` moves the lot
    `RECEIVED → GRADED`".

    Design: Difficulty/non_linear_state_machine/harvest_lot_grade_regrade_cycle
    """
    bundle = setup_lot_certified()
    lot_id = bundle["harvest_lot"]["id"]
    dispute_grade(lot_id, bundle["grower"], reason="firmness gauge miscalibrated")
    submit_grade(lot_id, flavor_brix=10.0, firmness_g=320,
                 appearance_score=75, defect_pct=4.0)
    certified = certify_lot(lot_id, certifier_id=GRADER_CERTIFIER)
    assert certified["grade_status"] == "CERTIFIED"
    assert certified["lot_status"] == "GRADED"
    assert certified["grade"] == "STANDARD"
    assert certified["certified_by_user_id"] == "qg-2"
