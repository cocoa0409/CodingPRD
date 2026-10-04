"""Corner coverage — RBAC (PRD §2.1 role admission gate, §4 endpoint role
table). Each denial is issued by the role the instance names, with
entity-backed identities threaded correctly so the 403 comes from the role
gate and never from an ownership mismatch.

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    adjudicate_claim_payload,
    complete_work_order,
    create_draft_standard,
    create_warranty_claim_payload,
    file_claim,
    make_certification_engineer_headers,
    make_fleet_manager_headers,
    make_service_advisor_headers,
    record_results_payload,
    schedule_test_run,
    schedule_work_order,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_family_testing,
    setup_family_under_review,
    setup_fleet,
    setup_full_environment,
    stamp_family_non_conforming,
    start_claim_review,
    start_work_order,
    validate_error,
    validate_success,
)


def test_fleet_manager_cannot_publish_standard(api, admin_headers, officer_headers):
    """PRD §2.1: "If the role is valid but the endpoint does not admit it, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: "POST `/emissions/regulation-standards/{id}/publish` | Publish a draft standard | RegulatoryOfficer"

    FleetManager is not in the publish endpoint's roles: 403
    ERR_FORBIDDEN_FOR_ROLE, and the standard remains DRAFT.

    Design: Corner/rbac/fleet_manager_cannot_publish_standard
    """
    standard = create_draft_standard()
    fleet = setup_fleet()

    refused = api.publish_regulation_standard(
        standard["id"], make_fleet_manager_headers(fleet["id"])
    )
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    standard_now = validate_success(api.get_regulation_standard(standard["id"], officer_headers))
    assert standard_now["status"] == "DRAFT", (
        f"the role gate fires before any window logic, got {standard_now['status']}"
    )


def test_service_advisor_cannot_adjudicate_claim(api, adjudicator_headers):
    """PRD §2.1: "If the role is valid but the endpoint does not admit it, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: "POST `/emissions/warranty-claims/{id}/adjudicate` | Decide a claim under review | WarrantyAdjudicator"
    PRD §3.7: "the claimant never adjudicates, because the filing roles (`FleetManager`, `ServiceAdvisor`) and the deciding role (`WarrantyAdjudicator`) are disjoint on every claim workflow step."

    The repairing center's ServiceAdvisor (who may file the claim) may not
    adjudicate it: 403 ERR_FORBIDDEN_FOR_ROLE, and the claim stays
    UNDER_REVIEW with no score stamped.

    Design: Corner/rbac/service_advisor_cannot_adjudicate_claim
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    set_logical_clock("2026-12-01T00:00:00Z")
    claim = file_claim(
        unit, env["center"],
        failed_component_class="ENGINE_BASE", failure_code="FC-rbac",
        claimed_amount_cents=40000,
    )
    start_claim_review(claim["id"])

    refused = api.adjudicate_claim(
        claim["id"],
        adjudicate_claim_payload("APPROVE_FULL"),
        make_service_advisor_headers(env["center"]["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    claim_now = validate_success(api.get_warranty_claim(claim["id"], adjudicator_headers))
    assert claim_now["status"] == "UNDER_REVIEW"
    assert claim_now["neglect_score"] is None


def test_warranty_adjudicator_cannot_file_claim(api):
    """PRD §2.1: "If the role is valid but the endpoint does not admit it, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: "POST `/emissions/warranty-claims` | File an emissions warranty claim | FleetManager, ServiceAdvisor"
    PRD §3.7: "`WarrantyAdjudicator` — the warranty claim adjudicator: reviews claims, requests information, and decides coverage versus maintenance neglect; an adjudicator never files claims."

    WarrantyAdjudicator is an adjudication-only role: claim creation returns
    403 ERR_FORBIDDEN_FOR_ROLE.

    Design: Corner/rbac/warranty_adjudicator_cannot_file_claim
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    set_logical_clock("2026-12-01T00:00:00Z")

    refused = api.create_warranty_claim(
        create_warranty_claim_payload(
            engine_unit_id=unit["id"],
            service_center_id=env["center"]["id"],
            failed_component_class="ENGINE_BASE",
            failure_code="FC-rbac2",
            claimed_amount_cents=40000,
        ),
        {"X-User-ID": "wa-ines", "X-User-Role": "WarrantyAdjudicator",
         "Content-Type": "application/json"},
    )
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_reman_planner_cannot_verify_work_order(api, planner_headers):
    """PRD §2.1: "If the role is valid but the endpoint does not admit it, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: "POST `/emissions/campaign-work-orders/{id}/verify` | Verify a completed remedy | RegulatoryOfficer"
    PRD §3.8: "Verification belongs to a `RegulatoryOfficer` and drives the program's deepest cascade."

    RemanPlanner calling verify on a COMPLETED work order returns 403
    ERR_FORBIDDEN_FOR_ROLE; the order remains COMPLETED with verified_at null.

    Design: Corner/rbac/reman_planner_cannot_verify_work_order
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-CE")
    work_order = schedule_work_order(
        campaign["id"], unit["id"], center_id, env["technician"]["id"]
    )
    start_work_order(work_order["id"], center_id)
    complete_work_order(work_order["id"], center_id)

    refused = api.verify_work_order(work_order["id"], planner_headers)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    order_now = validate_success(api.get_campaign_work_order(work_order["id"], planner_headers))
    assert order_now["status"] == "COMPLETED"
    assert order_now["verified_at"] is None


def test_certification_engineer_cannot_certify_family(api, engineer_headers):
    """PRD §2.1: "If the role is valid but the endpoint does not admit it, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: "POST `/emissions/engine-families/{id}/certify` | Certify a family under review | RegulatoryOfficer"
    PRD §3.2: "Certification itself is performed by a `RegulatoryOfficer` and moves the family from `UNDER_REVIEW` to `CERTIFIED`."

    The engineer who ran the test program gets 403 ERR_FORBIDDEN_FOR_ROLE from
    certify; the family remains UNDER_REVIEW.

    Design: Corner/rbac/certification_engineer_cannot_certify_family
    """
    env = setup_family_under_review()
    family_id = env["family"]["id"]

    refused = api.certify_family(
        family_id, make_certification_engineer_headers("ce-lena")
    )
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    family_now = validate_success(api.get_engine_family(family_id, engineer_headers))
    assert family_now["certification_status"] == "UNDER_REVIEW"


def test_regulatory_officer_cannot_record_test_results(api, officer_headers):
    """PRD §2.1: "If the role is valid but the endpoint does not admit it, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: "POST `/emissions/test-runs/{id}/record-results` | Record measured results for a scheduled run | CertificationEngineer"
    PRD §3.3: "Recording results is the engineer's next step, moving a run from `SCHEDULED` to `COMPLETED` with the payload `measured_nox_g_per_bhp_hr`, `measured_pm_g_per_bhp_hr`, and `deterioration_factor`."

    The reviewing officer cannot also produce the measurements: 403
    ERR_FORBIDDEN_FOR_ROLE, and the run remains SCHEDULED with result
    UNRECORDED.

    Design: Corner/rbac/regulatory_officer_cannot_record_test_results
    """
    env = setup_family_testing()
    run = schedule_test_run(env["family"]["id"], test_type="FTP")

    refused = api.record_test_results(run["id"], record_results_payload(), officer_headers)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    run_now = validate_success(api.get_test_run(run["id"], officer_headers))
    assert run_now["status"] == "SCHEDULED"
    assert run_now["result"] == "UNRECORDED"
