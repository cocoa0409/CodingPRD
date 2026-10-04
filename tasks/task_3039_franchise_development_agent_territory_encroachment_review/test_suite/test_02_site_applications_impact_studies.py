"""Site applications and impact studies: lifecycle, dual-variant calculation,
input-set filtering, approval gate, revision cycle (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_application,
    create_franchisee,
    create_impact_study_payload,
    create_store,
    get_impact_study,
    get_site_application,
    get_store,
    get_territory,
    make_development_agent_headers,
    make_franchisee_headers,
    setup_application_in_impact_review,
    setup_approved_application,
    setup_assigned_territory,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
)


def _get_app(api, app_id, agent_id):
    return validate_success(
        api.get_site_application(app_id, make_development_agent_headers(agent_id)), 200
    )


def test_impact_study_provisional_variant_prices_off_estimated_sales(api):
    """PRD §3.2: "For the provisional variant, each affected store's line is
    its `estimated_weekly_sales_cents` multiplied by its bucket percentage,
    rounded half up to 2 decimal places, and `provisional_impact_cents` is the
    sum of those rounded lines."

    Design: Difficulty/dual_variant_calc/impact_study_provisional_vs_final_variants_diverge
    """
    ctx = setup_assigned_territory()
    owner = create_franchisee()
    create_store(
        ctx["territory"]["id"], owner["id"],
        geo_lat=40.0, geo_lng=-75.0,
        estimated_weekly_sales_cents=5_000_000,
        actual_avg_weekly_sales_cents=4_000_000,
    )
    applicant = create_franchisee()
    app = create_application(ctx["territory"], ctx["agent"], applicant["id"])
    app = submit_application(app["id"], ctx["agent"]["id"])
    resp = api.create_impact_study(app["id"], create_impact_study_payload(radius_miles=2.0),
                                   ctx_headers(api))
    study = validate_success(resp, 201)
    # Manhattan distance 0.012 deg -> 0.01 <= d < 0.02 -> 7% bucket.
    assert study["status"] == "PROVISIONAL"
    assert study["affected_store_count"] == 1
    assert study["provisional_impact_cents"] == pytest.approx(350_000, abs=0.01)


def test_impact_study_final_variant_diverges_from_provisional(api):
    """PRD §3.2: "Finalizing the study moves it `PROVISIONAL → FINAL` and
    recomputes every line against the store's
    `actual_avg_weekly_sales_cents` — the trailing thirteen-week actual
    average — producing `final_impact_cents`; provisional and final figures
    differ whenever estimates diverge from actuals."

    Design: Difficulty/dual_variant_calc/impact_study_provisional_vs_final_variants_diverge
    """
    ctx2 = setup_assigned_territory()
    owner2 = create_franchisee()
    create_store(
        ctx2["territory"]["id"], owner2["id"],
        geo_lat=40.0, geo_lng=-75.0,
        estimated_weekly_sales_cents=5_000_000,
        actual_avg_weekly_sales_cents=4_000_000,
    )
    applicant = create_franchisee()
    app = create_application(ctx2["territory"], ctx2["agent"], applicant["id"])
    app = submit_application(app["id"], ctx2["agent"]["id"])
    study = validate_success(
        api.create_impact_study(app["id"], create_impact_study_payload(radius_miles=2.0),
                                ctx_headers(api)), 201
    )
    resp = api.finalize_impact_study(study["id"], ctx_headers(api))
    final = validate_success(resp, 200)
    assert final["status"] == "FINAL"
    assert final["affected_store_count"] == 1
    assert final["provisional_impact_cents"] == pytest.approx(350_000, abs=0.01)
    assert final["final_impact_cents"] == pytest.approx(280_000, abs=0.01)
    assert final["provisional_impact_cents"] != final["final_impact_cents"]


def ctx_headers(api):
    from test_helpers import TEST_USERS
    return TEST_USERS["franchisor_ops_headers"]


def test_impact_study_zero_affected_stores_empty_set(api, franchisor_ops_headers):
    """PRD §3.2: "a store enters the input set when that sum is strictly less
    than the radius in miles multiplied by 0.0145 degrees per mile" and
    "`affected_store_count` is the number of stores receiving a nonzero
    bucket."

    Design: Difficulty/boundary_precision_check/impact_study_zero_affected_stores_empty_set
    """
    ctx = setup_assigned_territory()
    owner = create_franchisee()
    create_store(ctx["territory"]["id"], owner["id"], geo_lat=40.0, geo_lng=-75.0,
                 estimated_weekly_sales_cents=5_000_000, actual_avg_weekly_sales_cents=4_000_000)
    applicant = create_franchisee()
    app = create_application(ctx["territory"], ctx["agent"], applicant["id"],
                             proposed_lat=41.5, proposed_lng=-76.5)
    app = submit_application(app["id"], ctx["agent"]["id"])
    study = validate_success(
        api.create_impact_study(app["id"], create_impact_study_payload(radius_miles=2.0),
                                franchisor_ops_headers), 201
    )
    final = validate_success(api.finalize_impact_study(study["id"], franchisor_ops_headers), 200)
    # Manhattan distance 2.5 deg >> 2.0 miles * 0.0145 = 0.029 deg: empty set.
    assert final["affected_store_count"] == 0
    assert final["provisional_impact_cents"] == pytest.approx(0, abs=0.01)
    assert final["final_impact_cents"] == pytest.approx(0, abs=0.01)
    assert final["status"] == "FINAL"
    # The zero-impact FINAL study still satisfies the approval gate.
    approved = validate_success(api.approve_site_application(app["id"], franchisor_ops_headers), 200)
    assert approved["status"] == "APPROVED"


def test_impact_study_zero_impact_still_gates_approval(api, franchisor_ops_headers):
    """PRD §3.2: "Approval requires the application's study to be in `FINAL`
    status, otherwise `ERR_IMPACT_STUDY_NOT_FINAL`; approval stamps
    `approved_on` with the logical clock, creates a `PIPELINE` store owned by
    the applicant franchisee"

    Design: Difficulty/boundary_precision_check/impact_study_zero_affected_stores_empty_set
    """
    ctx = setup_assigned_territory()
    owner = create_franchisee()
    create_store(ctx["territory"]["id"], owner["id"], geo_lat=40.0, geo_lng=-75.0)
    applicant = create_franchisee()
    app = create_application(ctx["territory"], ctx["agent"], applicant["id"],
                             proposed_lat=41.5, proposed_lng=-76.5)
    app = submit_application(app["id"], ctx["agent"]["id"])
    study = validate_success(
        api.create_impact_study(app["id"], create_impact_study_payload(radius_miles=2.0),
                                franchisor_ops_headers), 201
    )
    validate_success(api.finalize_impact_study(study["id"], franchisor_ops_headers), 200)
    approved = validate_success(api.approve_site_application(app["id"], franchisor_ops_headers), 200)
    assert approved["store_id"] is not None
    pipeline = get_store(approved["store_id"])
    assert pipeline["status"] == "PIPELINE"
    assert pipeline["source_site_application_id"] == app["id"]


def test_impact_input_set_excludes_terminated_and_out_of_radius_stores(api, franchisor_ops_headers):
    """PRD §3.2: "The input set is every store of the application's territory
    in `OPEN`, `CLOSED_FOR_REMODEL`, or `PROBATION` status whose distance from
    the proposed site is within the radius."

    Design: Corner/calculations/impact_input_set_excludes_terminated_and_out_of_radius_stores
    """
    from test_helpers import drive_store_to_termination_pending
    ctx = setup_assigned_territory()
    f1 = create_franchisee()
    create_store(ctx["territory"]["id"], f1["id"], geo_lat=40.0, geo_lng=-75.0,
                 estimated_weekly_sales_cents=5_000_000, actual_avg_weekly_sales_cents=4_000_000)
    f2 = create_franchisee()
    s2 = create_store(ctx["territory"]["id"], f2["id"], geo_lat=40.005, geo_lng=-75.0,
                      estimated_weekly_sales_cents=9_000_000, actual_avg_weekly_sales_cents=9_000_000)
    f3 = create_franchisee()
    create_store(ctx["territory"]["id"], f3["id"], geo_lat=42.5, geo_lng=-77.5,
                 estimated_weekly_sales_cents=9_000_000, actual_avg_weekly_sales_cents=9_000_000)
    # Terminate the near store S2 (would otherwise be the 12% bucket).
    drive_store_to_termination_pending(s2["id"])
    validate_success(api.terminate_store(s2["id"], franchisor_ops_headers), 200)
    applicant = create_franchisee()
    app = create_application(ctx["territory"], ctx["agent"], applicant["id"],
                             proposed_lat=40.012, proposed_lng=-75.0)
    app = submit_application(app["id"], ctx["agent"]["id"])
    study = validate_success(
        api.create_impact_study(app["id"], create_impact_study_payload(radius_miles=2.0),
                                franchisor_ops_headers), 201
    )
    final = validate_success(api.finalize_impact_study(study["id"], franchisor_ops_headers), 200)
    # Only S1 counts: distance 0.012 -> 7% bucket. TERMINATED S2 excluded by
    # status; far S3 excluded by radius.
    assert final["affected_store_count"] == 1
    assert final["provisional_impact_cents"] == pytest.approx(350_000, abs=0.01)
    assert final["final_impact_cents"] == pytest.approx(280_000, abs=0.01)


def test_approve_requires_final_impact_study(api, franchisor_ops_headers):
    """PRD §3.2: "Approval requires the application's study to be in `FINAL`
    status, otherwise `ERR_IMPACT_STUDY_NOT_FINAL`"

    Design: Difficulty/cross_entity_state_dependency/approve_requires_final_impact_study
    """
    ctx = setup_application_in_impact_review()
    resp = api.approve_site_application(ctx["application"]["id"], franchisor_ops_headers)
    validate_error(resp, ApiErrorId.ERR_IMPACT_STUDY_NOT_FINAL, 422)
    still = _get_app(api, ctx["application"]["id"], ctx["agent"]["id"])
    assert still["status"] == "IMPACT_REVIEW"


def test_approve_after_finalize_creates_pipeline_store(api, franchisor_ops_headers):
    """PRD §3.2: "approval stamps `approved_on` with the logical clock, creates
    a `PIPELINE` store owned by the applicant franchisee at the proposed
    address and coordinates with `source_site_application_id` pointing back to
    the application, sets the application's `store_id`, and recomputes the
    territory's `open_store_count`."

    Design: Difficulty/cross_entity_state_dependency/approve_requires_final_impact_study
    """
    ctx = setup_approved_application()
    app = ctx["application"]
    assert app["status"] == "APPROVED"
    assert app["store_id"] is not None
    pipeline = get_store(app["store_id"])
    assert pipeline["status"] == "PIPELINE"
    assert pipeline["territory_id"] == ctx["territory"]["id"]
    assert pipeline["franchisee_id"] == ctx["applicant"]["id"]
    assert pipeline["source_site_application_id"] == app["id"]


def test_site_application_revision_cycle_voids_study_and_increments_count(api, franchisor_ops_headers):
    """PRD §3.2: "The agent's resubmission returns it to `SUBMITTED`,
    increments `revision_count` by one, and voids the existing study — the
    study moves to `VOID` and must be redone from scratch."

    Design: Difficulty/non_linear_state_machine/site_application_revision_cycle
    """
    ctx = setup_application_in_impact_review()
    study = ctx["study"]
    validate_success(
        api.request_revision(ctx["application"]["id"],
                             {"revision_notes": "Traffic study insufficient"},
                             franchisor_ops_headers), 200)
    resubmitted = submit_application(ctx["application"]["id"], ctx["agent"]["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1
    voided = get_impact_study(study["id"])
    assert voided["status"] == "VOID"
    # A fresh study can be commissioned; the application returns to IMPACT_REVIEW.
    study2 = validate_success(
        api.create_impact_study(ctx["application"]["id"],
                                create_impact_study_payload(radius_miles=2.0),
                                franchisor_ops_headers), 201
    )
    assert study2["status"] == "PROVISIONAL"
    app = _get_app(api, ctx["application"]["id"], ctx["agent"]["id"])
    assert app["status"] == "IMPACT_REVIEW"


def test_site_application_revision_cycle_can_repeat(api, franchisor_ops_headers):
    """PRD §3.2: "From `IMPACT_REVIEW`, `FranchisorOps` may request revisions,
    supplying `revision_notes`, moving the application to `REVISION_REQUESTED`.
    The agent's resubmission returns it to `SUBMITTED`, increments
    `revision_count` by one"

    Design: Difficulty/non_linear_state_machine/site_application_revision_cycle
    """
    ctx = setup_application_in_impact_review()
    for expected_count in (1, 2):
        study = validate_success(
            api.get_impact_study(ctx["study"]["id"], franchisor_ops_headers), 200
        ) if expected_count == 1 else None
        validate_success(
            api.request_revision(ctx["application"]["id"],
                                 {"revision_notes": f"rev {expected_count}"},
                                 franchisor_ops_headers), 200)
        resubmitted = submit_application(ctx["application"]["id"], ctx["agent"]["id"])
        assert resubmitted["revision_count"] == expected_count
        fresh = validate_success(
            api.create_impact_study(ctx["application"]["id"],
                                    create_impact_study_payload(radius_miles=2.0),
                                    franchisor_ops_headers), 201
        )
        ctx["study"] = fresh
    app = _get_app(api, ctx["application"]["id"], ctx["agent"]["id"])
    assert app["status"] == "IMPACT_REVIEW"
    assert app["revision_count"] == 2


def test_site_application_created_in_draft_initial_state(api, franchisor_ops_headers):
    """PRD §3.2: "The application is born `DRAFT` with `revision_count` zero
    and `store_id` null"

    Design: Corner/state_machines/site_application_created_in_draft_initial_state
    """
    ctx = setup_assigned_territory()
    applicant = create_franchisee()
    app = create_application(ctx["territory"], ctx["agent"], applicant["id"])
    assert app["status"] == "DRAFT"
    assert app["revision_count"] == 0
    assert app["store_id"] is None
    assert app["approved_on"] is None


def test_approve_from_draft_rejected_invalid_state(api, franchisor_ops_headers):
    """PRD §2.8: "(5) state validity — the target must be in a from-state of
    the requested transition ... State failures return `ERR_INVALID_STATE`
    (HTTP 409)."
    PRD §3.2: "Approval requires the application's study to be in `FINAL`
    status" — approval is an IMPACT_REVIEW transition, not a DRAFT one.

    Design: Corner/state_machines/approve_from_draft_rejected_invalid_state
    """
    ctx = setup_assigned_territory()
    applicant = create_franchisee()
    app = create_application(ctx["territory"], ctx["agent"], applicant["id"])
    resp = api.approve_site_application(app["id"], franchisor_ops_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    still = _get_app(api, app["id"], ctx["agent"]["id"])
    assert still["status"] == "DRAFT"


def test_withdrawn_application_rejects_all_further_transitions(api, franchisor_ops_headers):
    """PRD §3.2: "`REJECTED` and `WITHDRAWN` are terminal."
    PRD §2.8: "the target must be in a from-state of the requested transition,
    terminal states reject everything"

    Design: Corner/state_machines/withdrawn_application_rejects_all_further_transitions
    """
    ctx = setup_assigned_territory()
    applicant = create_franchisee()
    app = create_application(ctx["territory"], ctx["agent"], applicant["id"])
    da_headers = make_development_agent_headers(ctx["agent"]["id"])
    withdrawn = validate_success(api.withdraw_site_application(app["id"], da_headers), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    validate_error(api.submit_site_application(app["id"], da_headers),
                   ApiErrorId.ERR_INVALID_STATE, 409)
    validate_error(api.approve_site_application(app["id"], franchisor_ops_headers),
                   ApiErrorId.ERR_INVALID_STATE, 409)
    validate_error(api.reject_site_application(app["id"], {"reason": "no"}, franchisor_ops_headers),
                   ApiErrorId.ERR_INVALID_STATE, 409)
    validate_error(api.request_revision(app["id"], {"revision_notes": "x"}, franchisor_ops_headers),
                   ApiErrorId.ERR_INVALID_STATE, 409)
    validate_error(api.withdraw_site_application(app["id"], da_headers),
                   ApiErrorId.ERR_INVALID_STATE, 409)
    still = _get_app(api, app["id"], ctx["agent"]["id"])
    assert still["status"] == "WITHDRAWN"


def test_double_submit_returns_invalid_state_idempotency(api):
    """PRD §3.2: "Submitting a `DRAFT` application moves it to `SUBMITTED`" —
    an already-SUBMITTED application is not in a from-state of submit.
    PRD §2.8: "State failures return `ERR_INVALID_STATE` (HTTP 409); stale-version failures return `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/state_machines/double_submit_returns_invalid_state_idempotency
    """
    ctx = setup_submitted_application()
    da_headers = make_development_agent_headers(ctx["agent"]["id"])
    resp = api.submit_site_application(ctx["application"]["id"], da_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    still = _get_app(api, ctx["application"]["id"], ctx["agent"]["id"])
    assert still["status"] == "SUBMITTED"
    assert still["revision_count"] == 0


def test_franchisee_cannot_approve_site_application(api):
    """PRD §4: the approve row names only `FranchisorOps` as authorized.
    PRD §2.1: "Attempting an operation outside the caller's role ... is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/franchisee_cannot_approve_site_application
    """
    ctx = setup_application_in_impact_review()
    validate_success(api.finalize_impact_study(ctx["study"]["id"],
                                               ctx_headers(api)), 200)
    resp = api.approve_site_application(
        ctx["application"]["id"], make_franchisee_headers(ctx["applicant"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
    still = _get_app(api, ctx["application"]["id"], ctx["agent"]["id"])
    assert still["status"] == "IMPACT_REVIEW"
