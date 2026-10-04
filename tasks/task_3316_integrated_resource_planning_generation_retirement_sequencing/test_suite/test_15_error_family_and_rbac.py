"""Error-family corners and RBAC denials (PRD §2.1, §2.8, §3.2, §3.4, §3.6, §3.9, §3.10)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_forecast,
    add_portfolio,
    compute_snapshot,
    create_draft_plan_with_basics,
    create_intervenor_payload,
    create_plan,
    create_plan_payload,
    create_testimony_payload,
    file_comment,
    file_testimony,
    get_success_data,
    issue_commitment,
    open_plan_for_comment,
    register_candidate,
    register_intervenor,
    register_resource,
    retire_resource,
    set_clock,
    setup_approved_plan,
    setup_plan_under_review,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01
from test_helpers.fixtures import PLANNER, COMMISSIONER, ADMIN, COMMENTER
from test_helpers.test_users import make_commissioner_headers, make_intervener_headers, make_planner_headers


def test_duplicate_intervenor_name_rejected(api):
    """PRD §3.10: "A `PlatformAdmin` registers an intervenor with a globally unique,
    case-sensitive `legal_name` — duplicates rejected with `ERR_DUPLICATE_INTERVENOR`
    (HTTP 409) — a `party_type` of `CONSUMER_ADVOCATE`, `INDUSTRIAL_GROUP`,
    `ENVIRONMENTAL_ORG`, or `MUNICIPALITY`, and an optional `standing_approved` flag
    that defaults to true when omitted."

    Design: Corner/errors/duplicate_intervenor_name_rejected
    """
    register_intervenor(legal_name="Dup Legal", party_type="MUNICIPALITY")

    resp = api.create_intervenor(
        create_intervenor_payload(legal_name="Dup Legal", party_type="CONSUMER_ADVOCATE"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INTERVENOR)


def test_analysis_reopen_requires_draft_plan(api):
    """PRD §3.6: "An analysis may be finalized, moving `DRAFT → FINAL` with a version
    bump, and later reopened, moving `FINAL → DRAFT`, provided the analysis's plan is
    back in `DRAFT` status — reopening against a plan in any other state is rejected
    with `ERR_PLAN_NOT_DRAFT`."

    Design: Corner/errors/analysis_reopen_requires_draft_plan
    """
    plan = create_plan(plan_name="IRP RARe")
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2031, residential_mw=10)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-RARe", preferred_flag=True)
    resource = register_resource(unit_name="COAL-RARE", resource_type="COAL",
                                 nameplate_mw=300, in_service_year=1985, fuel_type="COAL")
    register_candidate(candidate_name="K-RARE", resource_type="GAS_CC", nameplate_mw=500,
                       online_year=2029, capex_usd_per_kw=1200,
                       fixed_om_usd_per_kw_year=15, fuel_type="NATURAL_GAS",
                       build_lead_years=3)
    retire_resource(resource["id"], retirement_year=2031, plan_id=plan["id"])
    snapshot = compute_snapshot(portfolio["id"], forecast_year=2031, scenario_tag="BASE")
    analysis = get_success_data(api.create_retirement_analysis(
        resource["id"], {"plan_id": plan["id"], "snapshot_id": snapshot["id"]}, PLANNER
    ))
    validate_success(api.finalize_analysis(analysis["id"], PLANNER))

    # Default clock 2026-09-01 meets the cycle deadline, so the plan opens.
    open_plan_for_comment(plan["id"])

    resp = api.reopen_analysis(analysis["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT)

    after = get_success_data(api.get_analysis(analysis["id"], PLANNER))
    assert after["status"] == "FINAL"


def test_referential_integrity_retire_superseded_plan(api):
    """PRD §3.4: "The deciding plan must currently be in `DRAFT` status; a retire
    referencing a plan in any other state is rejected — a reference to a plan in a
    non-draft but otherwise live state surfaces `ERR_PLAN_NOT_DRAFT` (HTTP 409), while a
    reference to a `SUPERSEDED` plan is a referential failure surfaced as
    `ERR_REFERENTIAL_INTEGRITY` (HTTP 422)."

    Design: Corner/errors/referential_integrity_retire_superseded_plan
    """
    plan, _portfolio = setup_plan_under_review(plan_name="IRP RI")
    resource = register_resource(unit_name="COAL-RI", resource_type="COAL",
                                 nameplate_mw=300, in_service_year=1990, fuel_type="COAL")

    resp = api.retire_resource(
        resource["id"], {"retirement_year": 2030, "plan_id": plan["id"]}, PLANNER
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT)

    after = get_success_data(api.get_resource(resource["id"], PLANNER))
    assert after["status"] == "ACTIVE"


def test_comment_not_found_typed_404(api):
    """PRD §2.8: "Nested paths are validated left to right: for a path naming a plan and
    then a child, the plan's existence is checked first (a missing plan yields
    `ERR_PLAN_NOT_FOUND`), and only then the child under that plan (a missing child
    yields the child-specific not-found error such as `ERR_FORECAST_NOT_FOUND`,
    `ERR_PORTFOLIO_NOT_FOUND`, or `ERR_COMMENT_NOT_FOUND`)."

    Design: Corner/errors/comment_not_found_typed_404
    """
    set_clock(CLOCK_AUG_01)
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP CN", preferred=False)
    open_plan_for_comment(plan["id"])

    resp = api.acknowledge_comment(plan["id"], NON_EXISTENT_UUID, PLANNER)
    validate_error(resp, ApiErrorId.ERR_COMMENT_NOT_FOUND)


def test_commissioner_cannot_create_plan(api):
    """PRD §2.1: "`Commissioner` is the commission reviewer. Commissioners decide plans
    under review and award issued procurement commitments."
    PRD §2.1: "A request whose role is not permitted for the endpoint — or which
    violates an ownership or segregation-of-duties rule described below — is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/commissioner_cannot_create_plan
    """
    resp = api.create_plan(
        create_plan_payload(plan_name="IRP RBAC", cycle_year=2026,
                            planning_horizon_years=15),
        COMMISSIONER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_planner_cannot_commission_review(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint — or which
    violates an ownership or segregation-of-duties rule described below — is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "`Commissioner` is the commission reviewer. Commissioners decide plans
    under review and award issued procurement commitments."

    Design: Corner/rbac/planner_cannot_commission_review
    """
    plan, _portfolio = setup_plan_under_review(plan_name="IRP RBAC2")

    resp = api.commission_review(
        plan["id"],
        {"decision": "REJECT", "expected_plan_version": plan["version"]},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    after = get_success_data(api.get_plan(plan["id"], PLANNER))
    assert after["status"] == "UNDER_REVIEW"


def test_intervenor_cannot_withdraw_others_testimony(api):
    """PRD §3.10: "Its owner — and only its owner, with ownership mismatches rejected
    as `ERR_FORBIDDEN` — may withdraw it (`FILED → WITHDRAWN`) and later refile it
    (`WITHDRAWN → FILED`), each gated on the plan still being `UNDER_REVIEW` and each
    bumping the testimony's `version`; refiled testimony keeps its original
    `volume_no`, which is never reassigned."
    PRD §2.1: "When `X-User-Role` is `Intervener`, `X-User-ID` is the `id` of the acting
    `Intervenor` record; ownership checks on testimony compare the testimony's
    `intervenor_id` field to `X-User-ID`, and a filing whose `intervenor_id` does not
    match the caller's `X-User-ID` is rejected."

    Design: Corner/rbac/intervenor_cannot_withdraw_others_testimony
    """
    intervenor_a = register_intervenor(legal_name="Intervenor A")
    intervenor_b = register_intervenor(legal_name="Intervenor B",
                                       party_type="INDUSTRIAL_GROUP")
    plan, _portfolio = setup_plan_under_review(plan_name="IRP RBAC3")
    testimony = file_testimony(plan["id"], intervenor_a["id"], topic="Rates",
                               body="A's testimony.")

    resp = api.withdraw_testimony(testimony["id"], make_intervener_headers(intervenor_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    withdrawn = validate_success(
        api.withdraw_testimony(testimony["id"], make_intervener_headers(intervenor_a["id"]))
    )
    assert withdrawn["status"] == "WITHDRAWN"


def test_issuer_cannot_award_own_commitment_sod(api):
    """PRD §3.9: "Segregation of duties binds here: the awarding commissioner's
    `X-User-ID` must differ from the commitment's recorded `created_by_user_id`; the
    issuer awarding their own commitment is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.9: "At issue the server stamps `created_by_user_id` with the issuing
    planner's `X-User-ID` for later segregation of duties."

    Design: Corner/rbac/issuer_cannot_award_own_commitment_sod
    """
    plan, _portfolio, _snapshot = setup_approved_plan(plan_name="IRP SOD")
    candidate = register_candidate(candidate_name="K-SOD")
    commitment = issue_commitment(
        plan["id"], candidate_id=candidate["id"], committed_mw=50,
        headers=make_planner_headers("planner-1"),
    )
    assert commitment["created_by_user_id"] == "planner-1"

    resp = api.award_commitment(commitment["id"], make_commissioner_headers("planner-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    awarded = validate_success(
        api.award_commitment(commitment["id"], make_commissioner_headers("commissioner-9"))
    )
    assert awarded["status"] == "AWARDED"


def test_public_commenter_cannot_acknowledge(api):
    """PRD §2.1: "`PublicCommenter` is a member of the public who may file comments
    during the comment window."
    PRD §2.1: "A request whose role is not permitted for the endpoint — or which
    violates an ownership or segregation-of-duties rule described below — is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/public_commenter_cannot_acknowledge
    """
    set_clock(CLOCK_AUG_01)
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP RBAC4", preferred=False)
    open_plan_for_comment(plan["id"])
    comment = file_comment(plan["id"], commenter_name="Pub",
                           commenter_email="pub@example.org", body="A comment.")

    resp = api.acknowledge_comment(plan["id"], comment["id"], COMMENTER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    after = get_success_data(api.get_comment_flat(comment["id"], PLANNER))
    assert after["status"] == "RECEIVED"
