"""Corner queue — validation rules (PRD §2.1, §2.8, §3.2-§3.9).

Auth and ownership gates, pathway eligibility boundaries, the mitigation
trigger, notice/comment temporal gates, sequencing and singleton rules,
fiscal gates, and the decision/permit-lifecycle prerequisites.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_to_decision,
    assert_credit_requirement,
    assert_mitigation_plan,
    build_user_headers,
    close_comment_period,
    create_aa,
    create_agency_comment_payload,
    create_alternatives_analysis_payload,
    create_and_issue_jd,
    create_applicant,
    create_applicant_payload,
    create_appeal_payload,
    create_application,
    create_application_payload,
    create_case,
    create_credit_transaction_payload,
    create_jd,
    create_mitigation_bank_payload,
    create_mitigation_plan_payload,
    create_plan,
    create_site,
    file_appeal,
    file_comment,
    get_case,
    grant_extension,
    impact_line,
    issue_jd,
    iso_add_days,
    make_agency_reviewer_headers,
    make_applicant_headers,
    patch_aa,
    patch_plan,
    publish_notice_payload,
    render_decision,
    render_decision_payload,
    reserve_and_purchase,
    resolve_comment,
    review_aa,
    review_aa_payload,
    review_plan,
    review_report,
    set_clock,
    setup_aa_accepted,
    setup_active_permit,
    setup_applicant_and_site,
    setup_application_decision_pending,
    setup_application_in_alternatives_review,
    setup_application_public_notice_open,
    setup_case_restoration_pending,
    setup_operational_bank,
    setup_secured_prm_plan,
    setup_site_with_issued_jd,
    setup_suspended_permit_by_breach,
    submit_application,
    submit_plan,
    submit_report,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    walk_general_application_to_decision_pending,
)


# ---------------------------------------------------------------------------
# Auth and role gates (PRD §2.1)
# ---------------------------------------------------------------------------
def test_corner_missing_auth_header_rejected(api, no_auth_headers):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`
    identifying the acting principal, and `X-User-Role` naming the
    principal's role. If either header is missing, or if `X-User-Role` is not
    one of the six declared roles, the request is rejected with
    `ERR_MISSING_AUTH` (HTTP 401)."

    The call carries neither header.

    Design: Corner/validations/corner_missing_auth_header_rejected
    """
    resp = api.create_applicant(create_applicant_payload(), no_auth_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH)


def test_corner_unknown_role_rejected(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one
    of the six declared roles, the request is rejected with
    `ERR_MISSING_AUTH` (HTTP 401)."

    X-User-Role: SuperUser is an authentication failure (401), not a 403.

    Design: Corner/validations/corner_unknown_role_rejected
    """
    headers = build_user_headers("test-superuser-1", "SuperUser")
    resp = api.create_applicant(create_applicant_payload(), headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH)


def test_corner_role_denied_forbidden(api):
    """PRD §2.1: "If the role is valid but does not appear in the endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /wetland-permits/mitigation-banks is authorized for
    SystemAdmin only.

    Design: Corner/validations/corner_role_denied_forbidden
    """
    applicant = create_applicant()
    resp = api.create_mitigation_bank(
        create_mitigation_bank_payload(bank_name="Rogue Bank", sponsor_name="Nobody"),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_corner_not_resource_owner_rejected(api, reviewer_headers):
    """PRD §2.9: "Ownership scoping applies whenever `X-User-Role` is
    `Applicant`."
    PRD §2.9: "For an application, the caller's `X-User-ID` must equal the
    application's `applicant_id`."
    PRD §2.9: "A violation is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Applicant B submitting applicant A's DRAFT application is rejected; the
    application stays DRAFT.

    Design: Corner/validations/corner_not_resource_owner_rejected
    """
    ap_a = create_applicant(legal_name="Acme Dredging LLC", contact_email="a@acme.example")
    ap_b = create_applicant(legal_name="Blue Ridge Builders", contact_email="b@brb.example")
    site = create_site(ap_a)
    jd = create_and_issue_jd(site)
    app = create_application(site, jd, ap_a)

    resp = api.submit_application(app["id"], make_applicant_headers(ap_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    app_after = validate_success(api.get_application(app["id"], reviewer_headers))
    assert app_after["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# General-permit eligibility (PRD §3.3)
# ---------------------------------------------------------------------------
def test_corner_gp_acreage_boundary(api):
    """PRD §3.3: "The general-permit pathways are deliberately narrow, and
    their eligibility rule is enforced both when the application is created
    and again when it is submitted: the `general_permit_code` must be
    `NWP-29` or `NWP-39`, the `total_impact_acres` must not exceed 0.50 acres
    (exactly 0.50 remains eligible), and every impact line's resource type
    must be `EMERGENT_MARSH` or `STREAM`. Any breach is
    `ERR_GENERAL_PERMIT_INELIGIBLE` (HTTP 422)."

    0.50 EMERGENT_MARSH acres creates and submits cleanly; 0.51 breaches the
    cap and is rejected (the rule fires at creation).

    Design: Corner/validations/corner_gp_acreage_boundary
    """
    applicant, site, jd = setup_site_with_issued_jd(
        site_overrides={"resource_types_present": ["EMERGENT_MARSH", "STREAM"]}
    )
    app_ok = create_application(
        site, jd, applicant, pathway="GENERAL", general_permit_code="NWP-29",
        impacts=[impact_line("EMERGENT_MARSH", 0.50)],
        project_purpose="Boat ramp", estimated_cost_dollars=120000.0,
    )
    app_ok = submit_application(app_ok, applicant)
    assert app_ok["status"] == "SUBMITTED", "0.50 exactly is eligible"

    resp = api.create_application(
        create_application_payload(
            site["id"], jd["id"], pathway="GENERAL", general_permit_code="NWP-29",
            impacts=[impact_line("EMERGENT_MARSH", 0.51)],
            project_purpose="Boat ramp expansion", estimated_cost_dollars=130000.0,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GENERAL_PERMIT_INELIGIBLE)


def test_corner_gp_disallowed_resource_type(api):
    """PRD §3.3: "The general-permit pathways are deliberately narrow, and
    their eligibility rule is enforced both when the application is created
    and again when it is submitted: the `general_permit_code` must be
    `NWP-29` or `NWP-39`, the `total_impact_acres` must not exceed 0.50 acres
    (exactly 0.50 remains eligible), and every impact line's resource type
    must be `EMERGENT_MARSH` or `STREAM`. Any breach is
    `ERR_GENERAL_PERMIT_INELIGIBLE` (HTTP 422)."

    A 0.30-acre FORESTED_WETLAND GENERAL application is ineligible despite
    passing the acreage cap; the rule fires at creation.

    Design: Corner/validations/corner_gp_disallowed_resource_type
    """
    applicant, site, jd = setup_site_with_issued_jd(
        site_overrides={"resource_types_present": ["FORESTED_WETLAND"]}
    )
    resp = api.create_application(
        create_application_payload(
            site["id"], jd["id"], pathway="GENERAL", general_permit_code="NWP-29",
            impacts=[impact_line("FORESTED_WETLAND", 0.30)],
            project_purpose="Access road", estimated_cost_dollars=90000.0,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_GENERAL_PERMIT_INELIGIBLE)


def test_corner_mitigation_threshold_boundary(api, decision_engineer_headers):
    """PRD §3.3: "derives `compensatory_mitigation_required` as true exactly
    when `total_impact_acres` is strictly greater than 0.10 acres."
    PRD §3.7: "Fourth, when `compensatory_mitigation_required` is true, one
    of the application's mitigation plans must stand in `CREDITS_SECURED`,
    else `ERR_MITIGATION_NOT_SECURED` (HTTP 422)."

    At exactly 0.10 acres a GENERAL application issues with no plan at all;
    at 0.11 acres render-decision ISSUE fails.

    Design: Corner/validations/corner_mitigation_threshold_boundary
    """
    applicant, site, jd = setup_site_with_issued_jd(
        site_overrides={"resource_types_present": ["EMERGENT_MARSH", "STREAM"]}
    )
    app_low = create_application(
        site, jd, applicant, pathway="GENERAL", general_permit_code="NWP-39",
        impacts=[impact_line("EMERGENT_MARSH", 0.10)],
        project_purpose="Kiosk pad", estimated_cost_dollars=80000.0,
    )
    assert app_low["compensatory_mitigation_required"] is False
    app_high = create_application(
        site, jd, applicant, pathway="GENERAL", general_permit_code="NWP-39",
        impacts=[impact_line("EMERGENT_MARSH", 0.11)],
        project_purpose="Kiosk pad plus", estimated_cost_dollars=85000.0,
    )
    assert app_high["compensatory_mitigation_required"] is True

    app_low = walk_general_application_to_decision_pending(app_low, applicant)
    app_high = walk_general_application_to_decision_pending(app_high, applicant)

    app_low = render_decision(app_low, "ISSUE")
    assert app_low["status"] == "ISSUED", (
        "no mitigation plan exists or is needed at exactly 0.10 acres"
    )

    resp = api.render_decision(
        app_high["id"], render_decision_payload("ISSUE"), decision_engineer_headers
    )
    validate_error(resp, ApiErrorId.ERR_MITIGATION_NOT_SECURED)


# ---------------------------------------------------------------------------
# Notice and comment temporal gates (PRD §3.5, §2.5)
# ---------------------------------------------------------------------------
def test_corner_comment_after_period_closed(api):
    """PRD §3.5: "Once the window is anything other than `PUBLISHED`, filing
    is rejected with `ERR_COMMENT_PERIOD_CLOSED` (HTTP 422)."

    The clock move strictly past published+30 days auto-closes the notice;
    the comment filed afterwards is rejected.

    Design: Corner/validations/corner_comment_after_period_closed
    """
    ctx = setup_application_public_notice_open()
    close_comment_period(ctx["app"])

    resp = api.create_agency_comment(
        create_agency_comment_payload(
            ctx["app"]["id"], agency="EPA", comment_type="ADVISORY",
            comment_text="Late advisory",
        ),
        make_agency_reviewer_headers("epa-1"),
    )
    validate_error(resp, ApiErrorId.ERR_COMMENT_PERIOD_CLOSED)


def test_corner_advance_before_period_closed(api, reviewer_headers):
    """PRD §2.5: "A clock value exactly equal to the publication instant plus
    the comment period leaves the window `PUBLISHED`; the comparison is
    strictly-greater."
    PRD §3.5: "Advancing the application from `PUBLIC_NOTICE_OPEN` to
    `DECISION_PENDING` is the `Reviewer`'s act and carries two preconditions:
    the notice dimension must have reached `COMMENT_PERIOD_CLOSED`, else
    `ERR_NOTICE_PERIOD_STILL_OPEN` (HTTP 422)".

    At exactly published+30 days the advance is rejected; one day later it
    succeeds and stores the public interest review.

    Design: Corner/validations/corner_advance_before_period_closed
    """
    ctx = setup_application_public_notice_open()
    app = ctx["app"]
    published = app["notice_published_date"]

    set_clock(iso_add_days(published, 30))
    resp = api.advance_to_decision(app["id"], reviewer_headers)
    validate_error(resp, ApiErrorId.ERR_NOTICE_PERIOD_STILL_OPEN)

    set_clock(iso_add_days(published, 31))
    app = advance_to_decision(app)
    assert app["status"] == "DECISION_PENDING"
    assert app["pir_score"] == pytest.approx(17.25, abs=0.005)


def test_corner_unresolved_objection_blocks_advance(api, reviewer_headers):
    """PRD §3.5: "Advancing the application from `PUBLIC_NOTICE_OPEN` to
    `DECISION_PENDING` is the `Reviewer`'s act and carries two preconditions:
    the notice dimension must have reached `COMMENT_PERIOD_CLOSED`, else
    `ERR_NOTICE_PERIOD_STILL_OPEN` (HTTP 422), and no agency comment of this
    application may remain with `comment_type` `SUBSTANTIVE_OBJECTION` and
    `status` `FILED`, else `ERR_UNRESOLVED_AGENCY_OBJECTIONS` (HTTP 422)."

    A FILED substantive objection blocks the advance; resolving it unblocks
    the identical call.

    Design: Corner/validations/corner_unresolved_objection_blocks_advance
    """
    ctx = setup_application_public_notice_open()
    app = ctx["app"]
    comment = file_comment(
        app, agency="FWS", comment_type="SUBSTANTIVE_OBJECTION",
        comment_text="Jeopardy to Indiana bat habitat", agency_user_id="fws-1",
    )
    close_comment_period(app)

    resp = api.advance_to_decision(app["id"], reviewer_headers)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_AGENCY_OBJECTIONS)

    comment = resolve_comment(
        comment, "Applicant committed to seasonal tree-clearing restrictions"
    )
    assert comment["status"] == "RESOLVED"

    app = advance_to_decision(app)
    assert app["status"] == "DECISION_PENDING"


# ---------------------------------------------------------------------------
# Singleton and sequencing rules (PRD §3.4, §3.5, §3.6)
# ---------------------------------------------------------------------------
def test_corner_second_plan_rejected(api):
    """PRD §3.6: "Each application carries at most one plan outside the
    terminal statuses — a second plan while one stands in `DRAFT`,
    `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`, `CREDITS_SECURED`, or
    `ACTIVE` is rejected with `ERR_ACTIVE_PLAN_EXISTS` (HTTP 409)."

    Design: Corner/validations/corner_second_plan_rejected
    """
    ctx = setup_aa_accepted()
    create_plan(ctx["app"], ctx["applicant"])  # first plan, DRAFT

    resp = api.create_mitigation_plan(
        create_mitigation_plan_payload(ctx["app"]["id"], mechanism="IN_LIEU_FEE"),
        make_applicant_headers(ctx["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_PLAN_EXISTS)


def test_corner_second_aa_rejected(api):
    """PRD §3.4: "Once an application reaches `ALTERNATIVES_REVIEW`, the
    applicant files exactly one alternatives analysis for it — a second
    analysis for the same application is rejected with
    `ERR_AA_ALREADY_EXISTS` (HTTP 409)".

    Design: Corner/validations/corner_second_aa_rejected
    """
    ctx = setup_application_in_alternatives_review()
    create_aa(ctx["app"], ctx["applicant"])

    resp = api.create_alternatives_analysis(
        create_alternatives_analysis_payload(
            ctx["app"]["id"], avoidance_narrative="Second attempt",
            offsite_alternatives_considered=4,
        ),
        make_applicant_headers(ctx["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AA_ALREADY_EXISTS)


def test_corner_double_notice_rejected(api, reviewer_headers):
    """PRD §3.5: "With an accepted analysis in hand, a `Reviewer` publishes
    the public notice, which requires the application in
    `ALTERNATIVES_REVIEW`, the analysis `ACCEPTED` (else
    `ERR_AA_NOT_ACCEPTED`), and the notice dimension still at `NONE` — a
    notice already published cannot be published again,
    `ERR_NOTICE_ALREADY_PUBLISHED` (HTTP 409)."

    Design: Corner/validations/corner_double_notice_rejected
    """
    ctx = setup_application_public_notice_open()
    resp = api.publish_notice(
        ctx["app"]["id"], reviewer_headers, payload=publish_notice_payload(15)
    )
    # PRD §3.5 names ERR_NOTICE_ALREADY_PUBLISHED for re-publication, but
    # §2.8 runs the tier-7 state gate (ERR_APPLICATION_INVALID_STATE, the
    # application now sitting in PUBLIC_NOTICE_OPEN) before the domain
    # singleton rules; PRD pins no precedence between them on this path.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_NOTICE_ALREADY_PUBLISHED,
         ApiErrorId.ERR_APPLICATION_INVALID_STATE],
    )


def test_corner_ledpa_gate_rejects_bad_analysis(api, reviewer_headers):
    """PRD §3.4: "Accepting the analysis is gated on the LEDPA demonstration
    — the least environmentally damaging practicable alternative: acceptance
    requires `avoidance_demonstrated` to be true, at least two entries in
    `minimization_steps`, and a `ledpa_conclusion` of `PROPOSED_IS_LEDPA`,
    all three together, else the acceptance is rejected with
    `ERR_LEDPA_NOT_DEMONSTRATED` (HTTP 422)."

    An ALTERNATIVE_IS_LEDPA conclusion fails even with avoidance demonstrated
    and 2 steps; after revision, a PROPOSED_IS_LEDPA conclusion with only 1
    minimization step also fails.

    Design: Corner/validations/corner_ledpa_gate_rejects_bad_analysis
    """
    ctx = setup_application_in_alternatives_review()
    applicant = ctx["applicant"]
    aa = create_aa(ctx["app"], applicant, ledpa_conclusion="ALTERNATIVE_IS_LEDPA")

    resp = api.review_alternatives_analysis(
        aa["id"], review_aa_payload("ACCEPT"), reviewer_headers
    )
    validate_error(resp, ApiErrorId.ERR_LEDPA_NOT_DEMONSTRATED)

    review_aa(aa, "REQUEST_REVISION", revision_notes="Fix the LEDPA basis")
    aa = patch_aa(
        aa, applicant, ledpa_conclusion="PROPOSED_IS_LEDPA",
        minimization_steps=["Only one step"],
    )
    resp = api.review_alternatives_analysis(
        aa["id"], review_aa_payload("ACCEPT"), reviewer_headers
    )
    validate_error(resp, ApiErrorId.ERR_LEDPA_NOT_DEMONSTRATED)


# ---------------------------------------------------------------------------
# Determination temporal and appeal gates (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------
def test_corner_jd_expired_blocks_submit(api):
    """PRD §3.3: "The referenced determination must be `ISSUED` (else
    `ERR_JD_INVALID_STATE` at the state tier), must be unexpired — the
    current clock no later than its `expiration_date`, with expiry exactly at
    the clock still acceptable, else `ERR_JD_EXPIRED` (HTTP 409)".

    The determination issued at the 2026-09-01 startup clock expires at
    2031-08-31; at 2031-09-01 the submission fails.

    Design: Corner/validations/corner_jd_expired_blocks_submit
    """
    applicant, site, jd = setup_site_with_issued_jd()
    app = create_application(site, jd, applicant)

    set_clock(iso_add_days(jd["expiration_date"], 1))
    resp = api.submit_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_JD_EXPIRED)


def test_corner_preliminary_jd_not_appealable(api):
    """PRD §3.2: "Only an `APPROVED` determination carries appeal rights;
    attempting to appeal a `PRELIMINARY` one is rejected with
    `ERR_JD_NOT_APPEALABLE` (HTTP 422)."

    Design: Corner/validations/corner_preliminary_jd_not_appealable
    """
    applicant, site = setup_applicant_and_site(
        resource_types_present=["FORESTED_WETLAND"]
    )
    jd = create_jd(site, jd_type="PRELIMINARY", rationale="Preliminary assessment")
    jd = issue_jd(jd)

    resp = api.create_appeal(
        create_appeal_payload(
            jd["id"], grounds_text="Disagree with the preliminary finding"
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_JD_NOT_APPEALABLE)


def test_corner_second_appeal_rejected(api):
    """PRD §3.2: "each determination carries at most one appeal, so a second
    filing against the same determination is rejected with
    `ERR_APPEAL_ALREADY_FILED` (HTTP 409)".

    Design: Corner/validations/corner_second_appeal_rejected
    """
    applicant, site, jd = setup_site_with_issued_jd(
        site_overrides={"resource_types_present": ["FORESTED_WETLAND"]}
    )
    file_appeal(jd, applicant, "First appeal")

    resp = api.create_appeal(
        create_appeal_payload(jd["id"], grounds_text="Second appeal"),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_FILED)


def test_corner_atf_requires_case(api):
    """PRD §3.3: "Two conditional fields attach at creation:
    `general_permit_code` is required exactly when the pathway is `GENERAL`
    or `ATF_GENERAL` and must be `NWP-29` or `NWP-39`, and
    `enforcement_case_id` is required exactly when the pathway is
    after-the-fact, naming an existing case whose `responsible_applicant_id`
    equals the creating applicant — shape failures of any of these rules are
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.3: "The after-the-fact pathways carry their own gate, also checked
    at creation and again at submission: the linked enforcement case must
    exist with a `case_status` of `VIOLATION_CONFIRMED` or
    `RESOLUTION_PENDING`, else `ERR_CASE_INVALID_STATE` (HTTP 409)."

    A missing enforcement_case_id is a 400; a linked case still OPENED is a
    409.

    Design: Corner/validations/corner_atf_requires_case
    """
    applicant, site, jd = setup_site_with_issued_jd(
        site_overrides={"resource_types_present": ["FORESTED_WETLAND"]}
    )
    case = create_case(site, applicant, 2.0)  # OPENED, never confirmed
    assert case["case_status"] == "OPENED"
    headers = make_applicant_headers(applicant["id"])

    base = dict(
        pathway="ATF_INDIVIDUAL",
        impacts=[impact_line("FORESTED_WETLAND", 2.0)],
        project_purpose="Stormwater facility", estimated_cost_dollars=750000.0,
    )
    resp = api.create_application(
        create_application_payload(site["id"], jd["id"], **base), headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    resp = api.create_application(
        create_application_payload(
            site["id"], jd["id"], enforcement_case_id=case["id"], **base
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)


# ---------------------------------------------------------------------------
# Fiscal gates (PRD §3.6)
# ---------------------------------------------------------------------------
def test_corner_out_of_state_bank_rejected(api):
    """PRD §3.6: "Two business guards follow: the bank's `state_code` must
    equal the state code of the site on the plan's application, else
    `ERR_OUT_OF_SERVICE_AREA` (HTTP 422); and the bank's
    `available_credits_by_type` for the resource type must be at least the
    requested credits, with exact equality allowed, else
    `ERR_INSUFFICIENT_CREDIT_INVENTORY` (HTTP 422)."

    The site is in VA; the MD bank cannot sell credits to the plan regardless
    of inventory.

    Design: Corner/validations/corner_out_of_state_bank_rejected
    """
    ctx = setup_aa_accepted()
    applicant = ctx["applicant"]
    plan = create_plan(ctx["app"], applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank(
        state_code="MD", service_area_watersheds=["02060001"],
    )

    resp = api.create_credit_transaction(
        create_credit_transaction_payload(
            bank["id"], plan["id"], resource_type="FORESTED_WETLAND", credits=6.0
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OUT_OF_SERVICE_AREA)


def test_corner_insufficient_assurance_rejected(api):
    """PRD §3.6: "For `PERMITTEE_RESPONSIBLE`, `financial_assurance_dollars`
    must be at least the recomputed `assurance_required_dollars` and
    `long_term_stewardship_secured` must be true, else
    `ERR_INSUFFICIENT_FINANCIAL_ASSURANCE` (HTTP 422)."

    The PRD never publishes the assurance formula, so the requirement is read
    back from the created plan and the posted assurance is set to half of it
    (stewardship stays secured, so only the assurance leg fails).

    Design: Corner/validations/corner_insufficient_assurance_rejected
    """
    ctx = setup_aa_accepted()
    applicant = ctx["applicant"]
    plan = create_plan(
        ctx["app"], applicant, mechanism="PERMITTEE_RESPONSIBLE",
        stewardship_entity_name="Piney Branch Stewardship LLC",
        long_term_stewardship_secured=True,
    )
    required = plan["assurance_required_dollars"]
    assert required is not None and required > 0, (
        "a PERMITTEE_RESPONSIBLE plan must carry a positive computed "
        "assurance requirement for the assurance gate to be exercisable"
    )
    plan = patch_plan(
        plan, applicant, plan["version"], financial_assurance_dollars=required / 2
    )
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)

    resp = api.secure_credits(plan["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FINANCIAL_ASSURANCE)


def test_corner_prm_secure_success(api):
    """PRD §3.6: "For `PERMITTEE_RESPONSIBLE`, `financial_assurance_dollars`
    must be at least the recomputed `assurance_required_dollars` and
    `long_term_stewardship_secured` must be true, else
    `ERR_INSUFFICIENT_FINANCIAL_ASSURANCE` (HTTP 422)."
    PRD §3.6: "Either route moves the plan `APPROVED` to `CREDITS_SECURED`
    and stamps `secured_date` with the clock."

    With assurance posted at exactly the server-computed requirement
    (read-back pattern — the PRD never publishes the rate) and stewardship
    secured, secure-credits succeeds; the final requirement equals the
    provisional 6.00 in the same clock period (lag tier 1.0).

    Design: Corner/validations/corner_prm_secure_success
    """
    ctx = setup_aa_accepted()
    ctx = setup_secured_prm_plan(ctx)
    plan = ctx["plan"]
    assert_mitigation_plan(plan)
    assert plan["status"] == "CREDITS_SECURED"
    assert_credit_requirement(
        plan, {"FORESTED_WETLAND": 6.00}, field="final_credits_required_by_type"
    )


def test_corner_credits_shortfall_blocks_secure(api):
    """PRD §3.6: "For `BANK_CREDITS`, the sum of `PURCHASED` transaction
    credits must meet the final requirement for every resource type, else
    `ERR_CREDITS_NOT_SECURED` (HTTP 422)".
    PRD §3.6: "The lag multiplier prices delay: take the whole days elapsed
    from the application's `submitted_date` to the current clock, and apply
    1.0 when that lag is at most 365 days, 1.10 when it is between 366 and
    730 days inclusive, and 1.20 once it exceeds 730 days."

    6.00 purchased credits satisfy the provisional 6.00 but not the final
    6.60 once the 400-day lag lifts the requirement.

    Design: Corner/validations/corner_credits_shortfall_blocks_secure
    """
    ctx = setup_aa_accepted()
    app, applicant = ctx["app"], ctx["applicant"]
    plan = create_plan(app, applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank()
    reserve_and_purchase(bank, plan, applicant, credits=6.0)

    set_clock(iso_add_days(app["submitted_date"], 400))
    resp = api.secure_credits(plan["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDITS_NOT_SECURED)


# ---------------------------------------------------------------------------
# Enforcement and permit-lifecycle gates (PRD §3.8, §3.9)
# ---------------------------------------------------------------------------
def test_corner_extension_only_once(api, district_engineer_headers):
    """PRD §3.9: "Should the clock pass a restoration deadline while the case
    still pends, the case transitions `RESOLUTION_PENDING` to `DEFAULTED`; a
    `DistrictEngineer` may then grant a one-time extension, returning the
    case to `RESOLUTION_PENDING` with `restoration_deadline` reset to the
    current clock plus 60 days and `extension_used` set true — a second
    extension attempt is rejected with `ERR_EXTENSION_ALREADY_USED` (HTTP
    409)."

    Design: Corner/validations/corner_extension_only_once
    """
    _, _, case = setup_case_restoration_pending(2.0)
    set_clock(iso_add_days(case["restoration_deadline"], 1))
    case = get_case(case)
    assert case["case_status"] == "DEFAULTED"

    case = grant_extension(case)
    assert case["case_status"] == "RESOLUTION_PENDING"
    assert case["extension_used"] is True

    set_clock(iso_add_days(case["restoration_deadline"], 1))
    case = get_case(case)
    assert case["case_status"] == "DEFAULTED"

    resp = api.grant_extension(case["id"], district_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_EXTENSION_ALREADY_USED)


def test_corner_reinstate_blocked_while_overdue(api, district_engineer_headers):
    """PRD §3.8: "A `DistrictEngineer` reinstates a `SUSPENDED` permit to
    `ACTIVE` only once none of its reports remains `OVERDUE`, else
    `ERR_REPORTS_OVERDUE_EXIST` (HTTP 422)".

    While report 1 is OVERDUE the reinstate fails; submitting and accepting
    the late report cures the breach and the identical reinstate succeeds.

    Design: Corner/validations/corner_reinstate_blocked_while_overdue
    """
    ctx = setup_suspended_permit_by_breach()
    permit, applicant = ctx["permit"], ctx["applicant"]
    assert permit["status"] == "SUSPENDED"

    resp = api.reinstate_permit(permit["id"], district_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_REPORTS_OVERDUE_EXIST)

    rep1 = ctx["reports"][0]
    rep1 = submit_report(rep1, permit, applicant, findings_text="Late year-1 filing")
    review_report(rep1, "ACCEPTED")

    permit = validate_success(api.reinstate_permit(permit["id"], district_engineer_headers))
    assert permit["status"] == "ACTIVE"


def test_corner_close_blocked_until_monitoring_complete(api, district_engineer_headers):
    """PRD §3.8: "A `DistrictEngineer` reinstates a `SUSPENDED` permit to
    `ACTIVE` only once none of its reports remains `OVERDUE`, else
    `ERR_REPORTS_OVERDUE_EXIST` (HTTP 422); and closes an `ACTIVE` permit to
    `CLOSED` only when all five of its monitoring reports stand `ACCEPTED`
    and the mitigation plan has reached `COMPLETED`, else
    `ERR_MONITORING_INCOMPLETE` (HTTP 422)."

    With all five reports still DUE, close fails.

    Design: Corner/validations/corner_close_blocked_until_monitoring_complete
    """
    ctx = setup_active_permit()
    resp = api.close_permit(ctx["permit"]["id"], district_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_MONITORING_INCOMPLETE)


def test_corner_pir_unfavorable_blocks_issue(api, decision_engineer_headers):
    """PRD §3.7: "Second, on the `INDIVIDUAL` and `ATF_INDIVIDUAL` pathways
    the stored `pir_outcome` must be `FAVORABLE`, else
    `ERR_PUBLIC_INTEREST_UNFAVORABLE` (HTTP 422)."
    PRD §3.5: "The `pir_outcome` is `FAVORABLE` when the score is at least
    0.0 and `UNFAVORABLE` below that."

    6.0 STREAM acres with 2 minimization steps and cost 260000 scores
    0.40*(-60+10) + 0.35*1.0 + 0.25*(-10) = -22.15 (UNFAVORABLE); ISSUE is
    rejected while DENY remains available.

    Design: Corner/validations/corner_pir_unfavorable_blocks_issue
    """
    ctx = setup_application_decision_pending(
        app_overrides={
            "impacts": [impact_line("STREAM", 6.0)],
            "project_purpose": "Channel relocation",
            "estimated_cost_dollars": 260000.0,
        }
    )
    app, applicant = ctx["app"], ctx["applicant"]
    assert app["pir_score"] == pytest.approx(-22.15, abs=0.005)
    assert app["pir_outcome"] == "UNFAVORABLE"

    resp = api.render_decision(
        app["id"], render_decision_payload("ISSUE"), decision_engineer_headers
    )
    validate_error(resp, ApiErrorId.ERR_PUBLIC_INTEREST_UNFAVORABLE)

    app = render_decision(app, "DENY", "Public interest review is unfavorable")
    assert app["status"] == "DENIED", (
        "the unfavorable application is still decidable, just not issuable"
    )
