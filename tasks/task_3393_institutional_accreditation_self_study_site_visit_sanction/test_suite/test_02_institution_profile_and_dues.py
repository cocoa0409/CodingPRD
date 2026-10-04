"""Institution profile maintenance: OCC, immediate consistency, and annual dues."""
from test_helpers import (
    ApiErrorId,
    DUES_1003_A_M_D,
    DUES_800_A_B_M,
    DUES_CANONICAL_800_A_B,
    create_change_request,
    decide_change_request,
    get_institution,
    institution_patch_payload,
    institution_payload,
    set_logical_clock,
    setup_accredited_institution,
    submit_change_request,
    validate_error,
    validate_success,
)


def test_annual_dues_rounding_is_per_line_then_sum(api, admin_headers, staff_headers):
    """PRD section 3.1: "The rounding order is pinned: each line is rounded half-up to whole cents first, then the rounded lines are summed, and only then is the base added; summing the raw unrounded lines first produces a different total and is not the contract."
    PRD section 3.1: "At creation the system also initializes `dues_paid_cents` equal to `current_annual_dues_cents`, so a freshly onboarded institution starts with zero arrears."
    PRD section 3.1: "Whenever an update touches `fte_enrollment` or `degree_levels_offered`, the dues assessment is recomputed from the new values; a change of `legal_status` flips the CFI variant used by future indicator submissions without recomputing past reports."

    Design: Difficulty/combinatorial_formula/annual_dues_per_line_rounding_pinned
    """
    set_logical_clock()
    create_response = api.create_institution(
        institution_payload(
            legal_name="Rounding Test Institute",
            fte_enrollment=1003,
            degree_levels_offered=["ASSOCIATE", "MASTERS", "DOCTORAL"],
        ),
        admin_headers,
    )
    data = validate_success(create_response, 201)
    institution_id = data["id"]
    # 250000 + round(1003*33*1.00) + round(1003*61*1.15) + round(1003*83*1.35)
    # = 250000 + 33099 + 70360 + 112386 = 465845 per the pinned per-line order.
    assert data["current_annual_dues_cents"] == DUES_1003_A_M_D
    assert data["dues_paid_cents"] == DUES_1003_A_M_D
    assert data["outstanding_dues_cents"] == 0
    created_version = data["version"]

    patch_response = api.update_institution(
        institution_id,
        institution_patch_payload(
            created_version,
            fte_enrollment=800,
            degree_levels_offered=["ASSOCIATE", "BACCALAUREATE"],
        ),
        staff_headers,
    )
    patched = validate_success(patch_response)
    assert patched["current_annual_dues_cents"] == DUES_CANONICAL_800_A_B
    assert patched["version"] == created_version + 1


def test_institution_patch_with_stale_version_rejected(api, admin_headers, staff_headers):
    """PRD section 2.7: "In both cases, if the supplied value does not equal the parent resource's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412): the client holds a stale view and must re-read the resource before writing, which prevents it from overwriting changes it has not observed."

    Design: Corner/cross_cutting_complexity_layers/occ_institution_patch_stale_version_rejected
    """
    set_logical_clock()
    create_response = api.create_institution(institution_payload(), admin_headers)
    institution = validate_success(create_response, 201)
    institution_id = institution["id"]
    observed_version = institution["version"]

    first = api.update_institution(
        institution_id,
        institution_patch_payload(observed_version, state_code="MO"),
        staff_headers,
    )
    patched = validate_success(first)
    assert patched["version"] == observed_version + 1
    assert patched["state_code"] == "MO"

    replay = api.update_institution(
        institution_id,
        institution_patch_payload(observed_version, state_code="IL"),
        staff_headers,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
    assert get_institution(institution_id)["state_code"] == "MO"


def test_institution_patch_immediately_visible_in_reads(api, admin_headers, staff_headers):
    """PRD section 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD section 2.5: "Any write that changes a resource's stored state — including writes driven by a cascade rather than by a direct client call on that resource — refreshes `updated_at` and advances `version`."

    Design: Corner/consistency_model/patch_immediately_visible_in_same_and_subsequent_reads
    """
    set_logical_clock()
    create_response = api.create_institution(institution_payload(), admin_headers)
    institution = validate_success(create_response, 201)
    institution_id = institution["id"]

    patch_response = api.update_institution(
        institution_id,
        institution_patch_payload(institution["version"], state_code="MO"),
        staff_headers,
    )
    patched = validate_success(patch_response)
    assert patched["state_code"] == "MO"
    assert patched["version"] == institution["version"] + 1

    reread = get_institution(institution_id)
    assert reread["state_code"] == "MO"
    assert reread["version"] == patched["version"]


def test_program_level_approval_recomputes_dues(api):
    """PRD section 3.9: "Approval applies the type's mutation: a `NEW_LOCATION` increments the institution's `locations_count` by one; a `PROGRAM_LEVEL` appends the `requested_program_level` to `degree_levels_offered` and recomputes the annual dues assessment of §3.1; a `DISTANCE_DELIVERY` sets `distance_delivery_approved` to true; and an `OWNERSHIP_CHANGE` mutates no institutional field beyond status, because the CFI variant follows `legal_status`, which staff maintain through the versioned profile update."

    Design: Corner/calculations/dues_recompute_on_program_level_approval
    """
    ctx = setup_accredited_institution()
    institution_id = ctx["institution"]["id"]

    change = create_change_request(institution_id, "PROGRAM_LEVEL")
    submit_change_request(change["id"], institution_id)
    decided = decide_change_request(
        change["id"], "APPROVE", "Masters programs authorized."
    )
    assert decided["status"] == "APPROVED"

    institution = get_institution(institution_id)
    assert "MASTERS" in institution["degree_levels_offered"]
    # New line: round(800 * 61 * 1.15) = 56120 on top of the prior 312400.
    assert institution["current_annual_dues_cents"] == DUES_800_A_B_M
    assert institution["outstanding_dues_cents"] == DUES_800_A_B_M - DUES_CANONICAL_800_A_B
