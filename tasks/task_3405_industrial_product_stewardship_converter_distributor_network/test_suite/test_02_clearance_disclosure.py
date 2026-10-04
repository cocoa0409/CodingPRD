"""Clearance lifecycle and disclosure-level computation (PRD §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    clearance_payload,
    create_formulation,
    create_jurisdiction,
    create_substance,
    decide_clearance,
    decision_payload,
    get_clearance,
    get_formulation,
    set_clock,
    setup_active_formulation,
    submit_clearance,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
    add_component,
)

PM = TEST_USERS["product_manager_headers"]
RM = TEST_USERS["regulatory_manager_headers"]


def test_clearance_decision_on_already_cleared_rejected(api):
    """PRD §3.2: "Decisions belong to the `RegulatoryManager`, acting only while
    the clearance is `SUBMITTED` (a decision aimed at any other status is
    rejected with `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/clearance_decision_on_already_cleared_rejected
    """
    ctx = setup_active_formulation()
    cl = ctx["clearance"]
    assert cl["status"] == "CLEARED"
    resp = api.decide_clearance(cl["id"], decision_payload("CHANGES_REQUESTED"), RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_clearance(cl["id"])
    assert after["status"] == "CLEARED"
    assert get_formulation(ctx["formulation"]["id"])["active_clearance_count"] == 1


def test_duplicate_live_clearance_rejected(api):
    """PRD §3.2: "If a clearance for the same (formulation, jurisdiction) pair
    is already live — sitting in `SUBMITTED` or `CLEARED` — the duplicate is
    rejected with `ERR_DUPLICATE_CLEARANCE` (HTTP 409)."

    Design: Corner/validations/duplicate_live_clearance_rejected
    """
    set_clock()
    jur = create_jurisdiction()
    form = create_formulation()
    cl = submit_clearance(form["id"], jur["id"], "EXEMPT")
    resp = api.create_clearance(
        clearance_payload(form["id"], jur["id"], "FULL_DISCLOSURE"), PM
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLEARANCE)
    after = get_clearance(cl["id"])
    assert after["submission_count"] == 1
    assert after["status"] == "SUBMITTED"


def test_disclosure_lower_threshold_edge_is_inclusive(api):
    """PRD §3.1: "Both boundaries are inclusive at the lower edge — a maximum
    concentration exactly equal to the declaration threshold already forces
    `DECLARATION`, and one exactly equal to the full-disclosure threshold forces
    `FULL_DISCLOSURE`."

    Design: Corner/calculations/disclosure_lower_threshold_edge_is_inclusive
    """
    set_clock()
    jur = create_jurisdiction(declaration_threshold_ppm=1000, full_disclosure_threshold_ppm=10000)
    form = create_formulation()
    sub = create_substance(cas_number="64-17-5", name="Ethanol", restriction_class="REPORTABLE")
    add_component(form["id"], sub["id"], 1000)
    cl = submit_clearance(form["id"], jur["id"], "DECLARATION")
    assert cl["required_disclosure_level"] == "DECLARATION", (
        "1000 ppm == declaration_threshold_ppm is inclusive at the lower edge"
    )


def test_disclosure_upper_threshold_edge_is_full(api):
    """PRD §3.1: "at or above `full_disclosure_threshold_ppm` yields
    `FULL_DISCLOSURE`. Both boundaries are inclusive at the lower edge — a
    maximum concentration exactly equal to the declaration threshold already
    forces `DECLARATION`, and one exactly equal to the full-disclosure threshold
    forces `FULL_DISCLOSURE`."

    Design: Corner/calculations/disclosure_upper_threshold_edge_is_full
    """
    set_clock()
    jur = create_jurisdiction(declaration_threshold_ppm=1000, full_disclosure_threshold_ppm=10000)
    form = create_formulation()
    sub = create_substance(cas_number="50-00-0", name="Formaldehyde", restriction_class="RESTRICTED")
    add_component(form["id"], sub["id"], 10000)
    cl = submit_clearance(form["id"], jur["id"], "FULL_DISCLOSURE")
    assert cl["required_disclosure_level"] == "FULL_DISCLOSURE", (
        "10000 ppm == full_disclosure_threshold_ppm forces FULL_DISCLOSURE"
    )


def test_prohibited_substance_blocks_clearance_submission(api):
    """PRD §3.2: "Before anything else at the business-rule tier, the
    formulation is screened: if any component references a `PROHIBITED`
    substance at a positive concentration, submission is refused with
    `ERR_SUBSTANCE_PROHIBITED` (HTTP 422)."

    Design: Corner/calculations/prohibited_substance_blocks_clearance_submission
    """
    set_clock()
    jur = create_jurisdiction()
    form = create_formulation()
    sub = create_substance(cas_number="1332-21-4", name="Asbestos", restriction_class="PROHIBITED")
    add_component(form["id"], sub["id"], 50)
    resp = api.create_clearance(clearance_payload(form["id"], jur["id"], "FULL_DISCLOSURE"), PM)
    validate_error(resp, ApiErrorId.ERR_SUBSTANCE_PROHIBITED)
    rows, meta = validate_paginated(
        api.list_clearances(PM, params={"formulation_id": form["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_disclosure_insufficient_blocks_clear_decision(api):
    """PRD §3.2: "Granting `CLEARED` carries a guard: the submitted package level
    must rank at least as high as the clearance's `required_disclosure_level`,
    on the ordering in which `EXEMPT` ranks below `DECLARATION` and
    `DECLARATION` ranks below `FULL_DISCLOSURE`; an insufficient package is
    rejected with `ERR_DISCLOSURE_INSUFFICIENT` (HTTP 422)."

    Design: Corner/calculations/disclosure_insufficient_blocks_clear_decision
    """
    set_clock()
    jur = create_jurisdiction(declaration_threshold_ppm=1000, full_disclosure_threshold_ppm=10000)
    form = create_formulation()
    sub = create_substance(restriction_class="RESTRICTED")
    add_component(form["id"], sub["id"], 5000)
    cl = submit_clearance(form["id"], jur["id"], "EXEMPT")
    assert cl["required_disclosure_level"] == "DECLARATION"
    resp = api.decide_clearance(cl["id"], decision_payload("CLEARED"), RM)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_INSUFFICIENT)
    assert get_clearance(cl["id"])["status"] == "SUBMITTED"
    ok = api.decide_clearance(cl["id"], decision_payload("CHANGES_REQUESTED"), RM)
    decided = validate_success(ok, 200)
    assert decided["status"] == "CHANGES_REQUESTED", (
        "the package-sufficiency guard only blocks the CLEARED decision"
    )


def test_clearance_resubmission_upserts_same_row(api):
    """PRD §3.2: "when the pair's existing clearance sits in `CHANGES_REQUESTED`
    or `SUSPENDED`, a fresh submission for the same pair acts as an upsert
    rather than a create. The new payload's `disclosure_package_level` replaces
    the old one, `required_disclosure_level` is recomputed, `submission_count`
    increments by one, and the clearance returns to `SUBMITTED`; the response is
    HTTP 200 rather than 201."

    Design: Difficulty/non_linear_state_machine/clearance_changes_requested_resubmission_cycle
    """
    set_clock()
    jur = create_jurisdiction(declaration_threshold_ppm=1000, full_disclosure_threshold_ppm=10000)
    sub = create_substance(cas_number="50-00-0", name="Formaldehyde", restriction_class="RESTRICTED")
    form = create_formulation(product_code="F-200", name="Solvent adhesive",
                              base_polymer_family="solvent")
    add_component(form["id"], sub["id"], 5000)
    first = api.create_clearance(clearance_payload(form["id"], jur["id"], "EXEMPT"), PM)
    cl = validate_success(first, 201)
    assert cl["required_disclosure_level"] == "DECLARATION"
    assert cl["submission_count"] == 1
    decide_clearance(cl["id"], "CHANGES_REQUESTED", decider="rm-1")
    assert get_formulation(form["id"])["status"] == "DRAFT"

    resub = api.create_clearance(clearance_payload(form["id"], jur["id"], "FULL_DISCLOSURE"), PM)
    after = validate_success(resub, 200)
    assert after["id"] == cl["id"], "resubmission is an upsert on the same row"
    assert after["status"] == "SUBMITTED"
    assert after["submission_count"] == 2
    assert after["disclosure_package_level"] == "FULL_DISCLOSURE"


def test_clearance_resubmission_cycle_reaches_cleared_and_activates(api):
    """PRD §3.2: "A clearance granted `CLEARED` increments the formulation's
    `active_clearance_count`, and when that count rises from 0 to 1 the
    formulation itself bubbles up from `DRAFT` to `ACTIVE` — the moment the
    product becomes eligible for price agreements, application cases, and
    orders."

    Design: Difficulty/non_linear_state_machine/clearance_changes_requested_resubmission_cycle
    """
    set_clock()
    jur = create_jurisdiction(declaration_threshold_ppm=1000, full_disclosure_threshold_ppm=10000)
    sub = create_substance(cas_number="50-00-0", name="Formaldehyde", restriction_class="RESTRICTED")
    form = create_formulation(product_code="F-200", name="Solvent adhesive",
                              base_polymer_family="solvent")
    add_component(form["id"], sub["id"], 5000)
    cl = validate_success(
        api.create_clearance(clearance_payload(form["id"], jur["id"], "EXEMPT"), PM), 201
    )
    decide_clearance(cl["id"], "CHANGES_REQUESTED", decider="rm-1")
    resub = api.create_clearance(clearance_payload(form["id"], jur["id"], "FULL_DISCLOSURE"), PM)
    validate_success(resub, 200)
    decided = validate_success(
        api.decide_clearance(cl["id"], decision_payload("CLEARED"), RM), 200
    )
    assert decided["status"] == "CLEARED"
    form_after = get_formulation(form["id"])
    assert form_after["status"] == "ACTIVE"
    assert form_after["active_clearance_count"] == 1
