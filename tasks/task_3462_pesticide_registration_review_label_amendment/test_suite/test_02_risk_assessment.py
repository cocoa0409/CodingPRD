"""Quantitative risk assessment: dual-tier dietary model, pinned rounding order,
level-of-concern boundary, runoff factors, and the signal-word derivation
(PRD §3.3–§3.4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_iso_instant_equal,
    assert_risk_assessment,
    create_active_ingredient,
    create_application,
    create_product,
    create_registered_product,
    create_required_studies,
    create_study,
    create_tolerance,
    get_product,
    list_product_tolerances,
    make_application_decision_payload,
    make_non_food_use_site_object,
    run_risk_assessment,
    setup_application_in_review,
    submit_application,
    accept_study,
    approve_application,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]
ASSESSOR = TEST_USERS["assessor_1_headers"]
ASSESSOR_B = TEST_USERS["assessor_2_headers"]


def test_dietary_risk_screening_vs_refined_divergence(api):
    """PRD §3.3: "Under `SCREENING`, the term is the tolerance's `tolerance_ppm`
    multiplied by the commodity's daily consumption in grams, rounded half-up to
    four decimal places — the legal maximum residue, assuming the entire crop is
    treated."
    PRD §3.3: "Under `REFINED`, when at least one `ACCEPTED` study of type
    `RESIDUE_CHEMISTRY` exists bearing this commodity code and this application's
    id, the term instead takes the mean of those studies' `field_trial_residue_ppm`
    values — the mean itself rounded half-up to four decimal places — multiplied
    by the consumption and by `pct_crop_treated`, rounded half-up to four decimal
    places"
    PRD §3.3: "Each assessment of an application takes the next 1-based
    `assessment_seq` in creation order, so the "latest" assessment of an
    application is the one with the highest `assessment_seq`."

    Design: Difficulty/dual_variant_calc/dietary_risk_screening_vs_refined_divergence
    """
    ctx = setup_application_in_review(
        use_pattern="FOOD_USE", accept_studies=True, with_tolerance=True,
        tolerance_commodity="CORN", tolerance_ppm=2.0, residue_ppm=0.4,
        use_site_overrides={"max_application_rate_lbs_acre": 2.0})
    app_id = ctx["application"]["id"]

    screening = run_risk_assessment(app_id, tier="SCREENING")
    refined = run_risk_assessment(app_id, tier="REFINED", pct_crop_treated=0.3)

    assert_risk_assessment(screening)
    assert screening["assessment_seq"] == 1
    assert screening["dietary_exposure_mg_day"] == 25.0
    assert screening["dietary_rq"] == 7.143
    assert screening["occupational_rq"] == 0.006
    assert screening["ecological_rq"] == 0.001
    assert screening["level_of_concern_exceeded"] is True

    assert_risk_assessment(refined)
    assert refined["assessment_seq"] == 2
    assert refined["dietary_exposure_mg_day"] == 1.5
    assert refined["dietary_rq"] == 0.429
    assert refined["level_of_concern_exceeded"] is False

    # Identical product/study inputs: only the dietary pathway diverges by tier.
    assert refined["occupational_rq"] == screening["occupational_rq"] == 0.006
    assert refined["ecological_rq"] == screening["ecological_rq"] == 0.001


def test_dietary_exposure_round_per_commodity_then_sum(api):
    """PRD §3.3: "The rounding order is pinned: round each per-commodity term to
    four decimal places first, then sum the rounded terms, then round the sum
    half-up to three decimal places — that sum is `dietary_exposure_mg_day`."
    PRD §3.3: "The dietary risk quotient `dietary_rq` is the exposure divided by
    the product of the active ingredient's `reference_dose_mg_kg_day` and a
    70-kilogram reference body weight, rounded half-up to three decimal places."

    Design: Difficulty/combinatorial_formula/dietary_exposure_round_per_commodity_then_sum
    """
    ctx = setup_application_in_review(use_pattern="FOOD_USE")
    product_id = ctx["product"]["id"]
    reg = ctx["registrant_headers"]
    create_tolerance(product_id, reg, commodity_code="CORN", tolerance_ppm=0.11111)
    create_tolerance(product_id, reg, commodity_code="WHEAT", tolerance_ppm=0.22223)

    assessment = run_risk_assessment(ctx["application"]["id"], tier="SCREENING")
    # 0.11111*12.5 -> 1.3889 and 0.22223*20.0 -> 4.4446 per-term; the pinned
    # order sums 5.8335 and rounds to 5.834 (NOT the 5.833 of sum-then-round).
    assert assessment["dietary_exposure_mg_day"] == 5.834
    assert assessment["dietary_rq"] == 1.667
    assert assessment["level_of_concern_exceeded"] is True


def test_dietary_rq_exactly_one_exceeds_loc(api):
    """PRD §3.3: "The boolean `level_of_concern_exceeded` is true when the stored,
    rounded `dietary_rq` is at least 1.0, or the stored, rounded `occupational_rq`
    is at least 1.0, or the stored, rounded `ecological_rq` is at least 0.5."
    PRD §3.3: "The comparisons are inclusive and run against the rounded stored
    values, so a dietary quotient of exactly 1.000 exceeds the level of concern."

    Design: Difficulty/boundary_precision_check/dietary_rq_exactly_one_exceeds_loc
    """
    ctx_over = setup_application_in_review(
        use_pattern="FOOD_USE", with_tolerance=True, tolerance_ppm=0.28)
    ctx_under = setup_application_in_review(
        use_pattern="FOOD_USE", with_tolerance=True, tolerance_ppm=0.27)

    over = run_risk_assessment(ctx_over["application"]["id"], tier="SCREENING")
    under = run_risk_assessment(ctx_under["application"]["id"], tier="SCREENING")

    assert over["dietary_exposure_mg_day"] == 3.5
    assert over["dietary_rq"] == 1.0
    assert over["level_of_concern_exceeded"] is True

    assert under["dietary_exposure_mg_day"] == 3.375
    assert under["dietary_rq"] == 0.964
    assert under["level_of_concern_exceeded"] is False

    # Occupational and ecological quotients sit far below threshold on both.
    for assessment in (over, under):
        assert assessment["occupational_rq"] == 0.003
        assert assessment["ecological_rq"] == 0.001


def test_tolerance_establishment_gated_by_latest_assessment(api):
    """PRD §3.4: "The latest assessment — the one with the highest
    `assessment_seq` — must have `level_of_concern_exceeded` false, else
    `ERR_LOC_EXCEEDED`."
    PRD §3.4: "The application's `PROPOSED` use sites become `ACTIVE`; the
    product's `PROPOSED` tolerances become `ESTABLISHED` with `established_at`
    stamped from the clock."

    Design: Difficulty/cross_entity_state_dependency/tolerance_establishment_gated_by_latest_assessment
    """
    ctx = setup_application_in_review(
        use_pattern="FOOD_USE", accept_studies=True, with_tolerance=True,
        tolerance_commodity="CORN", tolerance_ppm=2.0, residue_ppm=0.4,
        use_site_overrides={"max_application_rate_lbs_acre": 2.0})
    app_id = ctx["application"]["id"]
    product_id = ctx["product"]["id"]
    tolerance_id = ctx["tolerance"]["id"]

    screening = run_risk_assessment(app_id, tier="SCREENING")
    assert screening["level_of_concern_exceeded"] is True

    resp = api_client.decide_application(
        app_id,
        make_application_decision_payload("APPROVE", final_classification="GENERAL_USE"),
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_LOC_EXCEEDED)
    tol = [t for t in list_product_tolerances(product_id) if t["id"] == tolerance_id][0]
    assert tol["status"] == "PROPOSED"
    assert get_product(product_id)["status"] == "UNREGISTERED"

    refined = run_risk_assessment(
        app_id, tier="REFINED", pct_crop_treated=0.3, assessor_headers=ASSESSOR_B)
    assert refined["dietary_rq"] == 0.429
    assert refined["level_of_concern_exceeded"] is False

    approve_application(app_id, final_classification="GENERAL_USE")
    tol = [t for t in list_product_tolerances(product_id) if t["id"] == tolerance_id][0]
    assert tol["status"] == "ESTABLISHED"
    assert_iso_instant_equal(tol["established_at"], "2026-09-01T00:00:00Z",
                             "tolerance.established_at")
    assert get_product(product_id)["status"] == "REGISTERED"


def test_refined_assessment_falls_back_to_tolerance_for_unstudied_commodity(api):
    """PRD §3.3: "where no such accepted study exists for a commodity, the
    `REFINED` term falls back to the `SCREENING` term for that commodity, so
    identical inputs never produce a higher exposure under `REFINED` than under
    `SCREENING`."

    Design: Corner/calculations/refined_assessment_falls_back_to_tolerance_for_unstudied_commodity
    """
    ctx = setup_application_in_review(
        use_pattern="FOOD_USE", accept_studies=True,
        residue_commodity="WHEAT", residue_ppm=0.01)
    product_id = ctx["product"]["id"]
    reg = ctx["registrant_headers"]
    create_tolerance(product_id, reg, commodity_code="CORN", tolerance_ppm=0.11111)
    create_tolerance(product_id, reg, commodity_code="WHEAT", tolerance_ppm=0.05)

    refined = run_risk_assessment(
        ctx["application"]["id"], tier="REFINED", pct_crop_treated=0.5)
    # WHEAT refined term: 0.01 * 20.0 * 0.5 = 0.1000; unstudied CORN falls back
    # to 0.11111 * 12.5 = 1.3889; sum 1.4889 rounds to 1.489.
    assert refined["dietary_exposure_mg_day"] == 1.489
    assert refined["dietary_rq"] == 0.425
    assert refined["level_of_concern_exceeded"] is False


def test_ecological_rq_varies_by_application_method_runoff_factor(api):
    """PRD §3.3: "For each use site of the product in `PROPOSED` or `ACTIVE`,
    multiply its rate by the runoff factor of its `application_method` — 0.05 for
    `GROUND`, 0.15 for `AERIAL`, 0.10 for `CHEMIGATION`, and 0.02 for
    `SEED_TREATMENT` — and take the maximum of those products, or zero when no
    site qualifies."

    Design: Corner/calculations/ecological_rq_varies_by_application_method_runoff_factor
    """
    ai = create_active_ingredient(common_name="nominex", cas_number="100-00-1",
                                  aquatic_lc50_ppm=2.0)
    product_a = create_product(REGISTRANT, ai["id"], product_name="Nominex A",
                               formulation_type="EMULSIFIABLE_CONCENTRATE")
    app_a = create_application(
        product_a["id"], REGISTRANT,
        proposed_use_sites=[make_non_food_use_site_object(
            max_application_rate_lbs_acre=4.0, max_applications_per_season=1,
            application_method="AERIAL")])
    create_required_studies(app_a["id"], "NON_FOOD_USE", REGISTRANT)
    submit_application(app_a["id"], REGISTRANT, "NON_FOOD_USE")

    product_s = create_product(REGISTRANT, ai["id"], product_name="Nominex S",
                               formulation_type="SEED_TREATMENT")
    app_s = create_application(
        product_s["id"], REGISTRANT,
        proposed_use_sites=[make_non_food_use_site_object(
            pest_code="SEED_MAGGOT", max_application_rate_lbs_acre=4.0,
            max_applications_per_season=1, application_method="SEED_TREATMENT",
            restricted_entry_interval_hours=0)])
    create_required_studies(app_s["id"], "NON_FOOD_USE", REGISTRANT)
    submit_application(app_s["id"], REGISTRANT, "NON_FOOD_USE")

    ra_aerial = run_risk_assessment(app_a["id"], tier="SCREENING")
    ra_seed = run_risk_assessment(app_s["id"], tier="SCREENING")

    # AERIAL: EEC 4.0 * 0.15 = 0.6 / 2.0 = 0.300; SEED_TREATMENT: 0.08/2.0 = 0.040.
    assert ra_aerial["ecological_rq"] == 0.3
    assert ra_aerial["level_of_concern_exceeded"] is False
    assert ra_seed["ecological_rq"] == 0.04
    # Occupational is method-independent: 4.0 * 0.01 / (0.05 * 70) -> 0.011.
    assert ra_aerial["occupational_rq"] == ra_seed["occupational_rq"] == 0.011


def test_signal_word_derived_from_tox_category(api):
    """PRD §3.4: "The product's `classification` takes the decision's
    `final_classification`; its `signal_word` is derived from the active
    ingredient's `tox_category` — category `I` maps to `DANGER_POISON`, `II` maps
    to `WARNING`, and both `III` and `IV` map to `CAUTION`"
    PRD §3.4: "the very first approval in the system mints `EPA-RR-000001`"

    Design: Corner/calculations/signal_word_derived_from_tox_category
    """
    ai = create_active_ingredient(common_name="toximax", cas_number="200-00-2",
                                  tox_category="I")
    product = create_product(REGISTRANT, ai["id"], product_name="Toximax RTU",
                             formulation_type="READY_TO_USE")
    application = create_application(
        product["id"], REGISTRANT, requested_classification="RESTRICTED_USE",
        proposed_use_sites=[make_non_food_use_site_object(
            max_applications_per_season=1, restricted_entry_interval_hours=48)])
    studies = create_required_studies(application["id"], "NON_FOOD_USE", REGISTRANT)
    for study in studies.values():
        accept_study(study["id"])
    submit_application(application["id"], REGISTRANT, "NON_FOOD_USE")
    run_risk_assessment(application["id"], tier="SCREENING")

    assert get_product(product["id"])["signal_word"] is None
    approve_application(application["id"], final_classification="RESTRICTED_USE")

    product = get_product(product["id"])
    assert product["signal_word"] == "DANGER_POISON"
    assert product["classification"] == "RESTRICTED_USE"
    assert product["epa_registration_number"] == "EPA-RR-000001"
