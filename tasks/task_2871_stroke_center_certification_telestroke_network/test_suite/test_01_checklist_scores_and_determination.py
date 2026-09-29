"""The thrombolytic checklist: two score variants, two state dimensions.

Covers the screening/attested divergence, the amendment compensation, the
cross-entity gate the amendment opens on thrombolytic administration, and the
validation precedence between a closed case and an absolute contraindication.
"""
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import ED


def test_attested_score_diverges_from_screening_on_the_window_penalty():
    """A non-board-certified attestation on a WITHIN_4_5H case stores 52.00 next to a screening 60.00.

    PRD 3.5: "The two fields never overwrite each other: a determination writes
    `attested_eligibility_score` and leaves `screening_eligibility_score` exactly
    as the last documentation write left it, so the bedside screening figure and
    the attested figure can be read side by side and will legitimately differ."

    Design: Difficulty/dual_variant_calc/eligibility_score_screening_and_attested_diverge_on_window_penalty
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(
        clock=door_at,
        coverage_tier="TIER_2_CONSULT_ONLY",
        neurologists=[{"board_certified": False}],
    )
    neurologist = context["neurologist"]
    case = fx.activate_case(
        context["spoke"]["id"], door_at, last_known_well_at="2026-09-01T04:30:00Z"
    )
    fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    fx.run_consult_to_completed(
        case["id"], context["agreement"]["id"], neurologist["id"],
        requested_at="2026-09-01T08:15:00Z", accept_after_seconds=180, session_seconds=240,
    )
    checklist = fx.setup_documented_checklist(case["id"])

    assert checklist["screening_eligibility_score"] == 60.00, (
        "Four inclusion items and no contraindications must screen at 60.00, got "
        f"{checklist['screening_eligibility_score']}"
    )
    assert checklist["attested_eligibility_score"] is None, (
        "attested_eligibility_score must stay null until the determination"
    )

    determined = fx.determine(checklist["id"], neurologist["id"], at="2026-09-01T08:30:00Z")

    case_after = fx.read_case(case["id"])
    assert case_after["thrombolytic_window_class"] == "WITHIN_4_5H", (
        "240 minutes from last_known_well_at must classify as WITHIN_4_5H, got "
        f"{case_after['thrombolytic_window_class']}"
    )
    assert determined["screening_eligibility_score"] == 60.00, (
        "the screening variant must survive the determination untouched, got "
        f"{determined['screening_eligibility_score']}"
    )
    assert determined["attested_eligibility_score"] == 52.00, (
        "60.00 minus the 8.0 WITHIN_4_5H window penalty with no board credit is 52.00, got "
        f"{determined['attested_eligibility_score']}"
    )
    assert determined["determination_status"] == "INELIGIBLE", (
        "an attested 52.00 is below the 55.0 eligible threshold, got "
        f"{determined['determination_status']}"
    )
    assert determined["documentation_status"] == "DOCUMENTED"
    assert a.instants_equal(determined["determined_at"], "2026-09-01T08:30:00Z"), (
        f"determined_at must be stamped from the logical clock, got {determined['determined_at']}"
    )
    assert case_after["status"] == "ELIGIBILITY_DETERMINED"
    assert case_after["disposition"] == "NO_TREATMENT", (
        f"an INELIGIBLE verdict must set disposition NO_TREATMENT, got {case_after['disposition']}"
    )
    a.assert_thrombolytic_checklist(determined)


def test_board_certification_credit_lands_only_on_the_attested_variant():
    """The PRD's worked example: a board-certified attestation on a WITHIN_4_5H case stores 58.00.

    PRD 3.5: "Four inclusion items and no contraindications screen at 60.00; if
    the case is `WITHIN_4_5H` and the attesting neurologist is board certified,
    the attested figure is 60.00 − 8.00 + 6.00 = 58.00."

    Design: Difficulty/dual_variant_calc/eligibility_score_screening_and_attested_diverge_on_window_penalty
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at, neurologists=[{"board_certified": True}])
    neurologist = context["neurologist"]
    case = fx.activate_case(
        context["spoke"]["id"], door_at, last_known_well_at="2026-09-01T04:30:00Z"
    )
    fx.run_consult_to_completed(
        case["id"], context["agreement"]["id"], neurologist["id"],
        requested_at="2026-09-01T08:05:00Z", accept_after_seconds=60, session_seconds=240,
    )
    checklist = fx.setup_documented_checklist(case["id"])
    determined = fx.determine(checklist["id"], neurologist["id"], at="2026-09-01T08:30:00Z")

    assert fx.read_case(case["id"])["thrombolytic_window_class"] == "WITHIN_4_5H"
    assert determined["attested_eligibility_score"] == 58.00, (
        "60.00 - 8.00 window penalty + 6.00 board credit is 58.00, got "
        f"{determined['attested_eligibility_score']}"
    )
    assert determined["screening_eligibility_score"] == 60.00, (
        "the screening variant carries neither the window penalty nor the board credit, got "
        f"{determined['screening_eligibility_score']}"
    )
    assert determined["determination_status"] == "ELIGIBLE", (
        "an attested 58.00 with no relative contraindications is ELIGIBLE, got "
        f"{determined['determination_status']}"
    )


def test_absolute_contraindication_clamps_both_score_variants_to_zero():
    """A single absolute contraindication clamps the screening and the attested figure alike.

    PRD 3.5: "A single absolute contraindication drives the raw expression to
    −40.0 and the stored value clamps to 0.00 in both variants."

    Design: Difficulty/dual_variant_calc/eligibility_score_screening_and_attested_diverge_on_window_penalty
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    neurologist = context["neurologist"]
    built = fx.setup_case_with_completed_consult(context, door_at)
    checklist = fx.setup_documented_checklist(
        built["case"]["id"], absolute_contraindications=1
    )

    assert checklist["screening_eligibility_score"] == 0.00, (
        "15.0*4 - 100.0 clamps to 0.00 under the screening variant, got "
        f"{checklist['screening_eligibility_score']}"
    )

    determined = fx.determine(checklist["id"], neurologist["id"], at="2026-09-01T08:20:00Z")

    assert determined["attested_eligibility_score"] == 0.00, (
        f"the attested variant clamps to 0.00 as well, got {determined['attested_eligibility_score']}"
    )
    assert determined["absolute_contraindication_count"] == 1
    assert determined["determination_status"] == "INELIGIBLE", (
        "an absolute contraindication is INELIGIBLE regardless of the score, got "
        f"{determined['determination_status']}"
    )
    assert fx.read_case(built["case"]["id"])["disposition"] == "NO_TREATMENT"


def test_amendment_rewinds_the_determination_while_the_case_self_loops():
    """AMENDED moves the documentation dimension forward and the verdict dimension back to PENDING.

    PRD 3.5: "an amendment pushes the documentation dimension forward to
    `AMENDED` while pulling the verdict dimension backward to `PENDING`, and the
    combination is perfectly legal"

    Design: Difficulty/non_linear_state_machine/checklist_amendment_rewinds_determination_while_the_case_self_loops
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    built = fx.setup_eligible_case(
        context, door_at, dti_minutes=10, determine_at="2026-09-01T08:20:00Z"
    )
    checklist = built["checklist"]

    assert checklist["documentation_status"] == "DOCUMENTED"
    assert checklist["determination_status"] == "ELIGIBLE"
    assert checklist["attested_eligibility_score"] == 66.00, (
        "15.0*4 with no window penalty plus the 6.0 board credit is 66.00, got "
        f"{checklist['attested_eligibility_score']}"
    )

    amended = fx.amend_checklist(checklist["id"], at="2026-09-01T08:25:00Z")

    assert amended["documentation_status"] == "AMENDED", (
        f"the documentation dimension must move forward, got {amended['documentation_status']}"
    )
    assert amended["determination_status"] == "PENDING", (
        f"the verdict dimension must move backward, got {amended['determination_status']}"
    )
    assert amended["attested_eligibility_score"] is None, (
        "the amendment nulls the attested score, got "
        f"{amended['attested_eligibility_score']}"
    )
    assert amended["determined_at"] is None
    assert amended["overridden_by_neurologist_id"] is None
    assert amended["override_justification"] is None
    assert amended["amendment_count"] == 1, (
        f"amendment_count must rise by 1, got {amended['amendment_count']}"
    )
    assert amended["screening_eligibility_score"] == 60.00, (
        "the amendment leaves the screening variant alone, got "
        f"{amended['screening_eligibility_score']}"
    )

    case_after = fx.read_case(built["case"]["id"])
    assert case_after["status"] == "ELIGIBILITY_DETERMINED", (
        f"the case must not rewind out of ELIGIBILITY_DETERMINED, got {case_after['status']}"
    )
    assert case_after["disposition"] == "PENDING", (
        f"the amendment resets the case disposition to PENDING, got {case_after['disposition']}"
    )


def test_redetermination_after_an_amendment_takes_the_relative_override_path():
    """A relative contraindication documented after the amendment lands the re-determination on the override verdict.

    PRD 3.5: "otherwise if `relative_contraindication_count` is 1 or more, the
    attested score is 40.0 or higher and an `override_justification` was
    supplied, the verdict is `ELIGIBLE_WITH_RELATIVE_OVERRIDE`"

    Design: Difficulty/non_linear_state_machine/checklist_amendment_rewinds_determination_while_the_case_self_loops
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    neurologist = context["neurologist"]
    built = fx.setup_eligible_case(
        context, door_at, dti_minutes=10, determine_at="2026-09-01T08:20:00Z"
    )
    checklist_id = built["checklist"]["id"]
    fx.amend_checklist(checklist_id, at="2026-09-01T08:25:00Z")

    with_relative = fx.document_contraindication(
        checklist_id, "CI_ANTICOAGULATION_RECENT", "RELATIVE",
        "INR 1.6 on the outside record dated 2026-08-31",
    )

    assert with_relative["documentation_status"] == "AMENDED", (
        "documenting more after an amendment must not fall back to IN_PROGRESS, got "
        f"{with_relative['documentation_status']}"
    )
    assert with_relative["relative_contraindication_count"] == 1
    assert with_relative["screening_eligibility_score"] == 48.00, (
        "15.0*4 - 12.0*1 is 48.00 under the screening variant, got "
        f"{with_relative['screening_eligibility_score']}"
    )

    redetermined = fx.determine(
        checklist_id, neurologist["id"], at="2026-09-01T08:30:00Z",
        override_justification="benefit outweighs bleeding risk after MDT discussion",
    )

    assert redetermined["attested_eligibility_score"] == 54.00, (
        "48.00 with no window penalty plus the 6.0 board credit is 54.00, got "
        f"{redetermined['attested_eligibility_score']}"
    )
    assert redetermined["determination_status"] == "ELIGIBLE_WITH_RELATIVE_OVERRIDE", (
        "54.00 sits below 55.0 but at or above 40.0 with a justification, got "
        f"{redetermined['determination_status']}"
    )
    assert redetermined["documentation_status"] == "DOCUMENTED", (
        f"the re-determination re-documents the row, got {redetermined['documentation_status']}"
    )
    assert redetermined["amendment_count"] == 1, (
        f"re-determining is not itself an amendment, got {redetermined['amendment_count']}"
    )
    assert redetermined["overridden_by_neurologist_id"] == neurologist["id"], (
        "an override outcome records the acting neurologist, got "
        f"{redetermined['overridden_by_neurologist_id']}"
    )
    assert (
        redetermined["override_justification"]
        == "benefit outweighs bleeding risk after MDT discussion"
    )
    assert redetermined["screening_eligibility_score"] == 48.00, (
        "the screening variant is untouched by the re-determination, got "
        f"{redetermined['screening_eligibility_score']}"
    )
    assert fx.read_case(built["case"]["id"])["thrombolytic_window_class"] == "WITHIN_3H"


def test_administer_is_refused_while_the_checklist_sits_at_amended():
    """The other entity's determination_status alone blocks the drug.

    PRD 3.6: "the case's checklist must have `determination_status` of `ELIGIBLE`
    or `ELIGIBLE_WITH_RELATIVE_OVERRIDE` **and** `documentation_status` of
    `DOCUMENTED`, otherwise `ERR_ELIGIBILITY_NOT_DETERMINED` — which is exactly
    what an amended-but-not-yet-re-determined checklist trips."

    Design: Difficulty/cross_entity_state_dependency/administer_depends_on_checklist_determination_state_after_amendment
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    built = fx.setup_eligible_case(
        context, door_at, dti_minutes=10, determine_at="2026-09-01T08:20:00Z"
    )
    case_id = built["case"]["id"]
    amended = fx.amend_checklist(built["checklist"]["id"], at="2026-09-01T08:25:00Z")
    assert amended["documentation_status"] == "AMENDED"
    before = fx.read_case(case_id)

    fx.set_clock("2026-09-01T08:30:00Z")
    response = api_client.administer_thrombolytic(
        case_id, f.administer_thrombolytic_payload(), ED
    )
    validate_error(response, ApiErrorId.ERR_ELIGIBILITY_NOT_DETERMINED.value, 409)

    after = fx.read_case(case_id)
    assert after["needle_at"] is None, "the refused write must not stamp needle_at"
    assert after["thrombolytic_agent"] is None
    assert after["door_to_needle_minutes"] is None
    assert after["status"] == "ELIGIBILITY_DETERMINED"
    assert after["version"] == before["version"], (
        f"a refused administer must not bump the case version, got {after['version']}"
    )


def test_administer_succeeds_once_the_amended_checklist_is_redetermined():
    """The re-determination reopens the gate and the drug goes in at 35 minutes.

    PRD 3.6: "On success `needle_at` is stamped from the logical clock,
    `thrombolytic_agent` and `thrombolytic_dose_mg` are recorded,
    `door_to_needle_minutes` is computed from `door_at`"

    Design: Difficulty/cross_entity_state_dependency/administer_depends_on_checklist_determination_state_after_amendment
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    neurologist = context["neurologist"]
    built = fx.setup_eligible_case(
        context, door_at, dti_minutes=10, determine_at="2026-09-01T08:20:00Z"
    )
    case_id = built["case"]["id"]
    checklist_id = built["checklist"]["id"]
    fx.amend_checklist(checklist_id, at="2026-09-01T08:25:00Z")

    redetermined = fx.determine(checklist_id, neurologist["id"], at="2026-09-01T08:30:00Z")
    assert redetermined["documentation_status"] == "DOCUMENTED"
    assert redetermined["determination_status"] == "ELIGIBLE"
    assert redetermined["attested_eligibility_score"] == 66.00
    assert fx.read_case(case_id)["status"] == "ELIGIBILITY_DETERMINED", (
        "the re-determination is a self-loop on the case"
    )

    treated = fx.administer(case_id, at="2026-09-01T08:35:00Z")

    assert treated["status"] == "THROMBOLYSIS_ADMINISTERED"
    assert treated["disposition"] == "TREATED_LOCAL"
    assert treated["door_to_needle_minutes"] == 35, (
        f"08:00 to 08:35 is 35 whole minutes, got {treated['door_to_needle_minutes']}"
    )
    assert a.instants_equal(treated["needle_at"], "2026-09-01T08:35:00Z")
    assert treated["thrombolytic_agent"] == "ALTEPLASE"
    assert treated["deviation_count"] == 0, (
        f"35 minutes is inside the 60-minute target, got {treated['deviation_count']}"
    )
    a.assert_case_clock_intervals(treated)


def test_closed_case_outranks_the_absolute_contraindication_on_administer():
    """Two armed rules, and the case-active rule is the one reported.

    PRD 2.11: "This is the highest-precedence clinical safety rule, and it
    deliberately sits below rule 13, so a request to treat a closed case that
    also carries an absolute contraindication returns `ERR_CASE_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/closed_case_outranks_absolute_contraindication_on_administer
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    neurologist = context["neurologist"]
    built = fx.setup_case_with_completed_consult(context, door_at)
    case_id = built["case"]["id"]
    fx.complete_imaging(case_id, at="2026-09-01T08:10:00Z")
    checklist = fx.setup_documented_checklist(case_id, absolute_contraindications=1)
    determined = fx.determine(checklist["id"], neurologist["id"], at="2026-09-01T08:20:00Z")
    assert determined["absolute_contraindication_count"] == 1
    assert determined["determination_status"] == "INELIGIBLE"
    closed = fx.close_case(case_id, at="2026-09-01T08:40:00Z")
    assert closed["status"] == "CLOSED"
    assert closed["disposition"] == "NO_TREATMENT"

    fx.set_clock("2026-09-01T08:45:00Z")
    response = api_client.administer_thrombolytic(
        case_id, f.administer_thrombolytic_payload(), ED
    )
    error = validate_error(response, ApiErrorId.ERR_CASE_NOT_ACTIVE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ABSOLUTE_CONTRAINDICATION.value
    assert error["error_id"] != ApiErrorId.ERR_ELIGIBILITY_NOT_DETERMINED.value

    after = fx.read_case(case_id)
    assert after["status"] == "CLOSED"
    assert after["needle_at"] is None
    assert after["thrombolytic_agent"] is None
    assert after["door_to_needle_minutes"] is None
    assert after["version"] == closed["version"], (
        f"the rejected request must write nothing, got version {after['version']}"
    )


def test_absolute_contraindication_is_reported_once_the_case_is_still_active():
    """With the case-active rule satisfied, the clinical safety rule surfaces on its own.

    PRD 3.6: "The checklist's `absolute_contraindication_count` must be 0,
    otherwise `ERR_ABSOLUTE_CONTRAINDICATION`."

    Design: Difficulty/priority_pair_validation_conflict/closed_case_outranks_absolute_contraindication_on_administer
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    neurologist = context["neurologist"]
    built = fx.setup_case_with_completed_consult(context, door_at)
    case_id = built["case"]["id"]
    fx.complete_imaging(case_id, at="2026-09-01T08:10:00Z")
    checklist = fx.setup_documented_checklist(case_id, absolute_contraindications=1)
    fx.determine(checklist["id"], neurologist["id"], at="2026-09-01T08:20:00Z")
    active = fx.read_case(case_id)
    assert active["status"] == "ELIGIBILITY_DETERMINED"

    fx.set_clock("2026-09-01T08:45:00Z")
    response = api_client.administer_thrombolytic(
        case_id, f.administer_thrombolytic_payload(), ED
    )
    validate_error(response, ApiErrorId.ERR_ABSOLUTE_CONTRAINDICATION.value, 422)

    after = fx.read_case(case_id)
    assert after["needle_at"] is None
    assert after["status"] == "ELIGIBILITY_DETERMINED"
    assert after["version"] == active["version"]
