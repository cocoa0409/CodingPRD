"""Role authorization: endpoint roles, entity-backed ownership, segregation of duties."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    begin_data_verification,
    create_community_bundle,
    evaluation_cycle_payload,
    file_appeal,
    make_class_registrar_headers,
    make_community_official_headers,
    make_fire_chief_headers,
    make_water_utility_manager_headers,
    setup_classification_review,
    setup_published_classification,
    setup_scoring_cycle,
    validate_error,
)

INSURER = TEST_USERS["insurer_headers"]


def test_insurer_cannot_create_cycle_returns_forbidden(api):
    """PRD §2.1: "A caller whose role is not authorized for the endpoint —
    or, on the parameterized transition endpoints, whose role is not the
    role entitled to the requested `target_state` — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." Cycle creation belongs to
    EvaluationCoordinator alone (§4).

    Design: Corner/rbac/insurer_cannot_create_cycle_returns_forbidden
    """
    bundle = create_community_bundle(api, name="RBAC1")
    resp = api.create_evaluation_cycle(
        evaluation_cycle_payload(bundle["community"]["id"]), INSURER
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_official_cannot_transition_credit_returns_forbidden(api):
    """PRD §2.1: "A caller whose role is not authorized for the endpoint …
    is rejected with `ERR_FORBIDDEN` (HTTP 403)." Credit adjudication is the
    FieldAnalyst's exclusive operation (§4), so the filing official cannot
    also verify.

    Design: Corner/rbac/official_cannot_transition_credit_returns_forbidden
    """
    ctx = setup_scoring_cycle(
        api, name="RBAC2", target_state="FIELD_VERIFICATION",
        credits=[{"program_type": "PUBLIC_EDUCATION", "activity_points": 1.5,
                  "evidence_note": "flyer"}],
    )
    resp = api.transition_risk_reduction_credit(
        ctx["credits"][0]["id"], {"target_state": "VERIFIED"},
        make_community_official_headers(ctx["community"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_chief_cannot_patch_other_department_returns_not_owner(api):
    """PRD §2.1: "When `X-User-Role` is `FireChief`, `X-User-ID` is the `id`
    of the acting FireDepartment, and any write targeting a department or
    one of its apparatus compares the department's `id` to `X-User-ID`." and
    "An entity-backed caller acting on a resource it does not own is rejected
    with `ERR_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/chief_cannot_patch_other_department_returns_not_owner
    """
    bundle_a = create_community_bundle(api, name="OwnA")
    bundle_b = create_community_bundle(api, name="OwnB")
    resp = api.patch_fire_department(
        bundle_b["department"]["id"], {"career_on_duty_per_shift": 9},
        make_fire_chief_headers(bundle_a["department"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)


def test_manager_cannot_create_hydrant_on_other_system_returns_not_owner(api):
    """PRD §2.1: "When `X-User-Role` is `WaterUtilityManager`, `X-User-ID` is
    the `id` of the acting WaterSupplySystem, and any write targeting a
    system, one of its hydrants, or one of its flow tests compares the owning
    system's `id` to `X-User-ID`." and "An entity-backed caller acting on a
    resource it does not own is rejected with `ERR_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/manager_cannot_create_hydrant_on_other_system_returns_not_owner
    """
    bundle_a = create_community_bundle(api, name="OwnC")
    bundle_b = create_community_bundle(api, name="OwnD")
    resp = api.create_hydrant(
        {"system_id": bundle_b["system"]["id"], "location_descriptor": "foreign hydrant"},
        make_water_utility_manager_headers(bundle_a["system"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER)


def test_sod_publish_same_user_as_analyst_returns_segregation_error(api):
    """PRD §2.9: "Publishing a classification requires that the publishing
    registrar's `X-User-ID` differ from the cycle's assigned
    `field_analyst_id`." A violation is "rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/sod_publish_same_user_as_analyst_returns_segregation_error
    """
    ctx = setup_classification_review(api, name="SoD1")
    resp = api.publish_classification(
        ctx["cycle"]["id"], {"score_sheet_id": ctx["sheet"]["id"]},
        make_class_registrar_headers("analyst-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_sod_adjudicate_same_user_as_publisher_returns_segregation_error(api):
    """PRD §2.9: "Adjudicating an appeal — whether upholding or revising —
    requires that the adjudicating registrar's `X-User-ID` differ from the
    classification's recorded `published_by`."

    Design: Corner/rbac/sod_adjudicate_same_user_as_publisher_returns_segregation_error
    """
    ctx = setup_published_classification(api, name="SoD2", registrar_id="registrar-1")
    appeal = file_appeal(api, ctx["classification"]["id"], ctx["community"]["id"])
    begin_data_verification(api, appeal["id"])
    resp = api.transition_appeal(
        appeal["id"], {"target_state": "ADJUDICATED_UPHELD"},
        make_class_registrar_headers("registrar-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_registrar_cannot_witness_flow_test_returns_forbidden(api):
    """PRD §2.1: "A caller whose role is not authorized for the endpoint —
    or, on the parameterized transition endpoints, whose role is not the
    role entitled to the requested `target_state` — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." Flow-test witnessing belongs to the
    FieldAnalyst (§4).

    Design: Corner/rbac/registrar_cannot_witness_flow_test_returns_forbidden
    """
    ctx = setup_scoring_cycle(
        api, name="RBAC3", target_state="FIELD_VERIFICATION",
        hydrant_count=1, flow_tests=[{"measured_flow_gpm": 1000}],
    )
    resp = api.transition_flow_test(
        ctx["flow_tests"][0]["id"], {"target_state": "WITNESSED"},
        make_class_registrar_headers("registrar-1"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
