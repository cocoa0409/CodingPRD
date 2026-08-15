"""Robot selections: payload margin boundary, inertia independence, brand
scope (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_robot_selection,
    create_robot_selection_payload,
    make_project_engineer_headers,
    setup_project_in_design,
    validate_error,
    validate_success,
)


def test_payload_margin_exactly_twenty_passes(api):
    """PRD §3.4: "validation requires a margin of at least 20.0 percent and a
    wrist inertia no greater than the manufacturer limit".

    Design: Difficulty/boundary_precision_check/payload_margin_exactly_twenty_passes
    """
    ctx = setup_project_in_design(project_overrides={"project_code": "P-BP1"})
    eng = ctx["users"]["PROJECT_ENGINEER"]

    # rated 50.0, ee 34.0, part 6.0 -> load 40.0 -> margin exactly 20.00.
    rs = validate_success(
        api.create_robot_selection(
            ctx["project"]["id"],
            create_robot_selection_payload(
                rated_payload_kg=50.0,
                end_effector_weight_kg=34.0,
                part_weight_kg=6.0,
                wrist_inertia_kgm2=10.0,
                wrist_inertia_limit_kgm2=12.0,
            ),
            make_project_engineer_headers(eng["id"]),
        ),
        201,
    )
    validated = validate_success(
        api.validate_robot_selection(
            rs["id"], make_project_engineer_headers(eng["id"])
        )
    )
    assert_robot_selection(validated)
    assert validated["payload_margin_pct"] == 20.0
    assert validated["selection_status"] == "VALIDATED"


def test_payload_margin_multi_input_threshold(api):
    """PRD §3.4: "the `payload_margin_pct` is one hundred times the difference
    between rated payload and total load, divided by the rated payload,
    rounded half-up to two decimal places; validation requires a margin of at
    least 20.0 percent and a wrist inertia no greater than the manufacturer
    limit, and any shortfall is rejected with `ERR_PAYLOAD_CHECK_FAILED`."

    Design: Difficulty/combinatorial_formula/payload_margin_multi_input_threshold
    """
    ctx = setup_project_in_design(
        org_overrides={"brand_specialization": "DUAL"},
        project_overrides={"project_code": "P-300"},
    )
    eng = ctx["users"]["PROJECT_ENGINEER"]

    # Margin passes (80.00%) but inertia 12.5 > limit 12.0 -> reject.
    rs = validate_success(
        api.create_robot_selection(
            ctx["project"]["id"],
            create_robot_selection_payload(
                robot_model="FANUC M-710iC/50",
                brand="FANUC",
                rated_payload_kg=50.0,
                end_effector_weight_kg=6.0,
                part_weight_kg=4.0,
                wrist_inertia_kgm2=12.5,
                wrist_inertia_limit_kgm2=12.0,
            ),
            make_project_engineer_headers(eng["id"]),
        ),
        201,
    )
    resp = api.validate_robot_selection(
        rs["id"], make_project_engineer_headers(eng["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PAYLOAD_CHECK_FAILED)

    after = validate_success(
        api.get_robot_selection(rs["id"], make_project_engineer_headers(eng["id"]))
    )
    assert after["selection_status"] == "PROPOSED"


def test_brand_out_of_scope_rejected(api):
    """PRD §3.4: "the selection's `brand` must fall within the org's
    `brand_specialization`, where a `DUAL` specialization covers both brands;
    an out-of-scope brand is rejected with `ERR_BRAND_OUT_OF_SCOPE`."

    Design: Corner/validations/brand_out_of_scope_rejected
    """
    ctx = setup_project_in_design(
        org_overrides={"brand_specialization": "FANUC"},
        project_overrides={"project_code": "P-BRAND"},
    )
    eng = ctx["users"]["PROJECT_ENGINEER"]

    rs = validate_success(
        api.create_robot_selection(
            ctx["project"]["id"],
            create_robot_selection_payload(
                robot_model="ABB IRB 6700",
                brand="ABB",
                rated_payload_kg=200.0,
                end_effector_weight_kg=20.0,
                part_weight_kg=30.0,
                wrist_inertia_kgm2=10.0,
                wrist_inertia_limit_kgm2=20.0,
            ),
            make_project_engineer_headers(eng["id"]),
        ),
        201,
    )
    resp = api.validate_robot_selection(
        rs["id"], make_project_engineer_headers(eng["id"])
    )
    validate_error(resp, ApiErrorId.ERR_BRAND_OUT_OF_SCOPE)
