"""Pod catalog: variety creation, defaults, lifecycle, and recyclable conversion."""
from test_helpers import (
    OPS,
    PLANNER,
    ApiErrorId,
    assert_pod_variety,
    create_brand,
    create_facility_with_line,
    create_variety,
    get_success_data,
    make_brand_manager_headers,
    transition_variety,
    validate_error,
    validate_success,
)


def test_pod_variety_create_applies_defaults_and_initial_state(api):
    """PRD §3.3: "The `material` may be supplied as `CONVENTIONAL` or
    `RECYCLABLE` and defaults to `CONVENTIONAL` when omitted."
    PRD §3.3: "A new variety starts `ACTIVE` with `version` 1 and
    `education_notices_sent` at 0."

    Design: Corner/entities/pod_variety_create_applies_defaults_and_initial_state
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Defaults Brand")
    headers = make_brand_manager_headers(brand["id"])
    resp = api.create_pod_variety(
        {"brand_id": brand["id"], "name": "Plain Medium", "roast_level": "MEDIUM",
         "flavor_family": "UNFLAVORED", "wholesale_price_cents": 100,
         "margin_cents": 20},
        headers)
    data = validate_success(resp, 201)
    assert_pod_variety(data)
    assert data["material"] == "CONVENTIONAL"
    assert data["status"] == "ACTIVE"
    assert data["velocity_units_90d"] == 0
    assert data["slow_mover"] is False
    assert data["education_notices_sent"] == 0
    assert data["version"] == 1


def test_create_variety_missing_required_field_rejected(api):
    """PRD §2.10: "**Payload shape** — required fields are present, types and
    enum memberships are valid, numeric ranges hold"

    Design: Corner/entities/create_variety_missing_required_field_rejected
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Required Brand")
    headers = make_brand_manager_headers(brand["id"])
    resp = api.create_pod_variety(
        {"brand_id": brand["id"], "name": "No Roast",
         "flavor_family": "UNFLAVORED", "wholesale_price_cents": 100,
         "margin_cents": 20},
        headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_variety_invalid_enum_rejected(api):
    """PRD §2.10: "**Payload shape** — required fields are present, types and
    enum memberships are valid, numeric ranges hold"
    PRD §3.3: "a `roast_level` of `LIGHT`, `MEDIUM`, or `DARK`"

    Design: Corner/entities/create_variety_invalid_enum_rejected
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Enum Brand")
    headers = make_brand_manager_headers(brand["id"])
    resp = api.create_pod_variety(
        {"brand_id": brand["id"], "name": "Burnt", "roast_level": "EXTRA_DARK",
         "flavor_family": "UNFLAVORED", "wholesale_price_cents": 100,
         "margin_cents": 20},
        headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_variety_phase_out_reverts_to_active(api):
    """PRD §3.3: "A `BrandManager` may move a variety `ACTIVE → PHASE_OUT` when
    it begins its wind-down, and `PHASE_OUT → ACTIVE` back again — phase-out is
    explicitly revertible, not absorbing."

    Design: Corner/state_machines/variety_phase_out_reverts_to_active
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Revert Brand")
    variety = create_variety(brand["id"], name="Revert Var", roast_level="LIGHT")

    phased = get_success_data(
        transition_variety(variety["id"], brand["id"], "PHASE_OUT"))
    assert phased["status"] == "PHASE_OUT"

    reactivated = get_success_data(
        transition_variety(variety["id"], brand["id"], "ACTIVE"))
    assert reactivated["status"] == "ACTIVE"
    # create (1) + two transitions -> version 3 (PRD §2.5 version discipline).
    assert reactivated["version"] == 3


def test_delisted_variety_is_terminal(api):
    """PRD §3.3: "From either `ACTIVE` or `PHASE_OUT`, the variety may be
    driven to `DELISTED`, which is terminal"
    PRD §2.9: "Terminal states are absorbing — a resource in a terminal state
    accepts no further transitions, and any attempt to drive one is rejected
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/delisted_variety_is_terminal
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Final Brand")
    variety = create_variety(brand["id"], name="Final Var")
    get_success_data(transition_variety(variety["id"], brand["id"], "DELISTED"))

    resp = transition_variety(variety["id"], brand["id"], "ACTIVE")
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    read_back = get_success_data(
        api.get_pod_variety(variety["id"], make_brand_manager_headers(brand["id"])))
    assert read_back["status"] == "DELISTED"


def test_writes_are_visible_immediately(api):
    """PRD §2.9: "The rule everywhere is **immediate consistency**: all such
    effects are applied atomically with the triggering operation and are
    visible in that request's own response."

    Design: Corner/consistency_model/writes_are_visible_immediately
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Immediate Brand")
    headers = make_brand_manager_headers(brand["id"])
    created = validate_success(api.create_pod_variety(
        {"brand_id": brand["id"], "name": "Immediate Var", "roast_level": "LIGHT",
         "flavor_family": "UNFLAVORED", "wholesale_price_cents": 101,
         "margin_cents": 21},
        headers), 201)

    read_back = get_success_data(api.get_pod_variety(created["id"], headers))
    assert read_back["name"] == "Immediate Var"
    assert read_back["status"] == "ACTIVE"
    assert read_back["wholesale_price_cents"] == 101

    transitioned = validate_success(
        api.transition_pod_variety(created["id"], {"target_state": "PHASE_OUT"},
                                   headers))
    assert transitioned["status"] == "PHASE_OUT"


def test_convert_recyclable_requires_education_notices(api):
    """PRD §3.3: "Fewer than one notice — zero — is rejected with
    `ERR_EDUCATION_REQUIRED` (HTTP 422); education must precede conversion."
    PRD §3.3: "the variety stays `ACTIVE`, its `material` becomes `RECYCLABLE`,
    and `education_notices_sent` is set to the payload value."

    Design: Corner/validations/convert_recyclable_requires_education_notices
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Edu Brand")
    variety = create_variety(brand["id"], name="Edu Var")
    # A BOTH-capable line exists so only the education gate can fire.
    create_facility_with_line(material_capability="BOTH")

    denied = transition_variety(variety["id"], brand["id"], "CONVERT_RECYCLABLE",
                                education_notices_sent=0)
    validate_error(denied, ApiErrorId.ERR_EDUCATION_REQUIRED)
    stayed = get_success_data(
        api.get_pod_variety(variety["id"], make_brand_manager_headers(brand["id"])))
    assert stayed["material"] == "CONVENTIONAL"

    converted = validate_success(
        api.transition_pod_variety(
            variety["id"],
            {"target_state": "CONVERT_RECYCLABLE", "education_notices_sent": 1},
            make_brand_manager_headers(brand["id"])))
    assert converted["status"] == "ACTIVE"
    assert converted["material"] == "RECYCLABLE"
    assert converted["education_notices_sent"] == 1


def test_convert_recyclable_without_any_capable_line(api):
    """PRD §3.3: "Independently, at least one filling line anywhere in the
    network must be able to run recyclable material — a line whose
    `material_capability` is `RECYCLABLE` or `BOTH`; with no such line the
    conversion is rejected with `ERR_NO_COMPATIBLE_LINE` (HTTP 409)."

    Design: Corner/validations/convert_recyclable_without_any_capable_line
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="NoLine Brand")
    variety = create_variety(brand["id"], name="NoLine Var")
    # No filling lines exist anywhere; notices alone cannot convert.
    resp = transition_variety(variety["id"], brand["id"], "CONVERT_RECYCLABLE",
                              education_notices_sent=5)
    validate_error(resp, ApiErrorId.ERR_NO_COMPATIBLE_LINE)


def test_line_rejects_recyclable_material_when_conventional_only(api):
    """PRD §3.4: "its `material_capability` must cover the variety's `material`
    (`BOTH` covers either material); a shortfall anywhere is
    `ERR_LINE_INCOMPATIBLE` (HTTP 422)."

    Design: Corner/validations/line_rejects_recyclable_material_when_conventional_only
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Material Brand")
    variety = create_variety(brand["id"], name="Material Var")
    facility, capable = create_facility_with_line(material_capability="BOTH")
    conventional_only = get_success_data(api.create_filling_line(
        facility["id"],
        {"line_code": "L-CONV", "supported_roast": "UNIVERSAL",
         "supports_flavored": True, "material_capability": "CONVENTIONAL",
         "capacity_pods_per_day": 100000, "changeover_hours": 0},
        OPS), 201)

    converted = validate_success(api.transition_pod_variety(
        variety["id"],
        {"target_state": "CONVERT_RECYCLABLE", "education_notices_sent": 1},
        make_brand_manager_headers(brand["id"])))
    assert converted["material"] == "RECYCLABLE"

    resp = api.create_production_run(
        {"line_id": conventional_only["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-11T00:00:00Z", "planned_units": 100},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_LINE_INCOMPATIBLE)
