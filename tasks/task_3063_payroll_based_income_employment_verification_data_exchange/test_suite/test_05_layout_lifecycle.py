"""RecordLayout lifecycle: supersession, the DRAFT self-loop and terminality."""
from test_helpers import (
    onboard_employer,
    create_layout,
    create_verified_layout,
    verify_layout,
    get_layout,
    get_batch,
    set_clock,
    make_employer_headers,
    api,
    validate_success,
    validate_error,
    ApiErrorId,
    DEFAULTS,
)


def test_higher_layout_version_supersedes_the_incumbent(api):
    """PRD §3.1: "When a predecessor exists, its `status` becomes `SUPERSEDED` and it
    is terminal."
    PRD §3.1: "among the layouts whose `employer_id` equals the new layout's
    `employer_id`, it is the one with the greatest `layout_version` strictly less than
    the new layout's `layout_version`".

    Design: Corner/state_machines/record_layout_verified_to_superseded_retires_predecessor
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    layout_1 = create_verified_layout(employer["id"], layout_version=1)
    layout_2 = create_layout(employer["id"], layout_version=2)

    assert get_layout(layout_1["id"], headers)["status"] == "SUPERSEDED"
    assert layout_2["status"] == "DRAFT"
    assert layout_2["layout_version"] == 2


def test_supersession_bumps_only_the_predecessor_version(api):
    """PRD §2.4: "Every persisted resource carries an integer `version` that starts at
    1 and increments by exactly 1 on every mutation, including mutations caused by
    cascades rather than by a direct client call."

    Design: Corner/state_machines/record_layout_verified_to_superseded_retires_predecessor
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    layout_1 = create_verified_layout(employer["id"], layout_version=1)
    version_after_verify = get_layout(layout_1["id"], headers)["version"]

    create_layout(employer["id"], layout_version=2)
    assert get_layout(layout_1["id"], headers)["version"] == version_after_verify + 1


def test_draft_self_loop_revises_the_mapping_in_place(api):
    """PRD §3.1: "it may be revised any number of times while `DRAFT`; each revision
    replaces the `column_map` wholesale, recomputes the diagnostics, and leaves
    `verified_at` alone."

    Design: Corner/state_machines/record_layout_draft_self_loop_revises_mapping_without_leaving_draft
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    incomplete = dict(DEFAULTS["COMPLETE_COLUMN_MAP"])
    incomplete.pop("BASIS")
    layout = create_layout(employer["id"], layout_version=1, column_map=incomplete)

    revised = api.patch_layout(
        layout["id"], {"column_map": DEFAULTS["COMPLETE_COLUMN_MAP"], "fiscal_year_start_month": 1}, headers
    )
    validate_success(revised, 200)
    second = api.patch_layout(
        layout["id"], {"column_map": incomplete, "fiscal_year_start_month": 1}, headers
    )
    data = validate_success(second, 200)

    assert data["status"] == "DRAFT"
    assert data["validation_error_count"] == 1
    assert data["missing_canonical_fields"] == ["pay_rate_basis"]
    assert data["verified_at"] is None


def test_draft_revision_keeps_the_layout_unverified(api):
    """PRD §3.1: "A layout begins life as `DRAFT`, its `verified_at` null".
    PRD §3.1: "Each registration recomputes the layout's two diagnostics —
    `validation_error_count`, the number of required canonical entries absent from the
    map, and `missing_canonical_fields`, the sorted list of those absent names, empty
    when the map is complete."

    Design: Corner/state_machines/record_layout_draft_self_loop_revises_mapping_without_leaving_draft
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    layout = create_layout(employer["id"], layout_version=1)
    assert get_layout(layout["id"], headers)["status"] == "DRAFT"
    assert get_layout(layout["id"], headers)["verified_at"] is None
    assert get_layout(layout["id"], headers)["validation_error_count"] == 0


def test_re_verifying_a_verified_layout_is_rejected(api):
    """PRD §4: "POST | /work-number/record-layouts/{id}/verify | Promote a complete
    mapping to `VERIFIED`."
    PRD §2.8: "An action addressed at a resource that is not in any state from which
    that action is defined fails with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/record_layout_verify_from_verified_is_invalid
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    layout = create_verified_layout(employer["id"], layout_version=1)

    response = api.verify_layout(layout["id"], headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_layout(layout["id"], headers)["status"] == "VERIFIED"


def test_incomplete_mapping_cannot_be_verified(api):
    """PRD §3.1: "A layout with any absent canonical field cannot be promoted: the
    verify step requires `validation_error_count` of zero and a complete map, and
    otherwise fails with `ERR_LAYOUT_MAPPING_INCOMPLETE` (HTTP 422)."

    Design: Corner/state_machines/record_layout_verify_from_verified_is_invalid
    """
    employer = onboard_employer()
    headers = make_employer_headers(employer["id"])
    incomplete = dict(DEFAULTS["COMPLETE_COLUMN_MAP"])
    incomplete.pop("BASIS")
    layout = create_layout(employer["id"], layout_version=1, column_map=incomplete)

    response = api.verify_layout(layout["id"], headers)
    validate_error(response, ApiErrorId.ERR_LAYOUT_MAPPING_INCOMPLETE)
    assert get_layout(layout["id"], headers)["status"] == "DRAFT"