"""Score sheet lifecycle: supersession, OCC on creation, publication guard order."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_score_sheet,
    cycle_version,
    finalize_score_sheet,
    get_cycle,
    get_success_data,
    make_class_registrar_headers,
    setup_classification_review,
    setup_scoring_cycle,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["field_analyst_headers"]
COORD = TEST_USERS["evaluation_coordinator_headers"]


def test_sheet_finalize_superseded_returns_conflict(api):
    """PRD §3.6: "the sheet must still be `DRAFT` and its cycle must be in
    `SCORING` or `CLASSIFICATION_REVIEW`, with violations rejected as
    `ERR_SHEET_INVALID_STATE`" and "any existing `DRAFT` sheet of the same
    cycle immediately becomes `SUPERSEDED`" on a new creation.

    Design: Corner/state_machines/sheet_finalize_superseded_returns_conflict
    """
    ctx = setup_scoring_cycle(api, name="Sheetville")
    cycle_id = ctx["cycle"]["id"]
    sheet1 = create_score_sheet(api, cycle_id)
    sheet2 = create_score_sheet(api, cycle_id)
    superseded = get_success_data(api.get_score_sheet(sheet1["id"], ANALYST))
    assert superseded["status"] == "SUPERSEDED"
    resp = api.finalize_score_sheet(sheet1["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_SHEET_INVALID_STATE)
    assert get_success_data(api.get_score_sheet(sheet2["id"], ANALYST))["status"] == "DRAFT"


def test_occ_sheet_create_stale_and_fresh_versions(api):
    """PRD §2.7: "Creating a score sheet for a cycle requires the request to
    carry `expected_cycle_version` equal to the cycle's current `version`"
    and "the request is rejected with `ERR_STALE_VERSION` (HTTP 412)";
    PRD §3.6: "the cycle's `version` increments by one" per creation.

    Design: Corner/complexity_layers/occ_sheet_create_stale_and_fresh_versions
    """
    ctx = setup_scoring_cycle(api, name="OCC1")
    cycle_id = ctx["cycle"]["id"]
    v1 = cycle_version(api, cycle_id)
    sheet1 = create_score_sheet(api, cycle_id, expected_version=v1)
    resp = api.create_score_sheet(cycle_id, {"expected_cycle_version": v1}, ANALYST)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    v2 = cycle_version(api, cycle_id)
    assert v2 == v1 + 1, "exactly one version increment per successful create"
    resp2 = api.create_score_sheet(cycle_id, {"expected_cycle_version": v2}, ANALYST)
    validate_success(resp2, 201)
    assert cycle_version(api, cycle_id) == v1 + 2
    assert get_success_data(api.get_score_sheet(sheet1["id"], ANALYST))["status"] == "SUPERSEDED"


def _scoring_with_final_sheet(api, name):
    ctx = setup_scoring_cycle(api, name=name)
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    finalize_score_sheet(api, sheet["id"])
    ctx["sheet"] = sheet
    return ctx


def test_state_priority_beats_segregation_on_publish(api):
    """PRD §3.7: "Publication enforces its guards in order: the cycle must be
    in `CLASSIFICATION_REVIEW`, otherwise `ERR_CYCLE_INVALID_STATE`;
    segregation of duties then requires the registrar's `X-User-ID` to differ
    from the cycle's `field_analyst_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_segregation_on_publish
    """
    ctx = _scoring_with_final_sheet(api, "Prio One")
    cycle_id = ctx["cycle"]["id"]
    resp = api.publish_classification(
        cycle_id, {"score_sheet_id": ctx["sheet"]["id"]},
        make_class_registrar_headers("analyst-1"),
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_INVALID_STATE)
    classifications = get_success_data(
        api.list_classifications(COORD, params={"cycle_id": cycle_id})
    )
    assert classifications == [], "no Classification may be created"
    assert get_cycle(api, cycle_id)["status"] == "SCORING"


def test_segregation_surfaces_once_state_gate_passes(api):
    """PRD §3.7: "segregation of duties then requires the registrar's
    `X-User-ID` to differ from the cycle's `field_analyst_id`, else
    `ERR_SEGREGATION_OF_DUTIES`" — with the cycle properly in
    CLASSIFICATION_REVIEW the same publisher identity hits the second rung.

    Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_segregation_on_publish
    """
    ctx = setup_classification_review(api, name="Prio One Review")
    resp = api.publish_classification(
        ctx["cycle"]["id"], {"score_sheet_id": ctx["sheet"]["id"]},
        make_class_registrar_headers("analyst-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
