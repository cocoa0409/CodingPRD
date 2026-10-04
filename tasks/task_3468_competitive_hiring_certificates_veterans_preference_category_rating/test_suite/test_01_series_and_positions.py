"""Series creation, position grading (both variants), classification,
reclassification range checks, and OCC on the position version.
"""
from test_helpers import (
    HR, HM, NON_EXISTENT_UUID, ApiErrorId,
    assert_position, assert_series,
    create_classified_position, create_draft_position, create_series,
    create_series_payload, classify_position,
    expected_official_grade, expected_provisional_grade, expected_total_points,
    api_client, reclassify_position_payload, validate_error, validate_success,
    get_success_data,
)


def test_series_creation_echoes_inputs_with_system_fields(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.4: "`id`: a server-minted UUID, formatted as a bare UUID with no
    type prefix." and "`version`: an integer that increments by one on every
    mutation of the resource."

    Design: Corner/entities/series_creation_echo_and_system_fields
    """
    payload = create_series_payload(
        series_code="0343", title="Program Analyst", min_grade=5, max_grade=12,
        quals_base_months=6, quals_months_per_grade_step=6,
        allows_education_substitution=True, education_substitution_cap_months=12,
        positive_education_required=False)
    resp = api_client.create_series(payload, HR)
    data = validate_success(resp, 201)
    assert_series(data)
    assert data["version"] == 1, f"new resource version must be 1, got {data['version']}"
    for field, value in payload.items():
        assert data[field] == value, f"echo mismatch on {field}: {data[field]!r} != {value!r}"

    fetched = get_success_data(api_client.get_series(data["id"], HR))
    assert_series(fetched)
    assert fetched["series_code"] == "0343"
    assert fetched["quals_base_months"] == 6
    assert fetched["education_substitution_cap_months"] == 12


def test_position_computed_fields_at_creation(api):
    """PRD §3.1: "The position is born in `DRAFT`, and two figures are computed
    at once and stored: `total_points`, the weighted point sum in which
    knowledge contributes 300 points per level, supervision 200, complexity 250,
    and impact 250; and `provisional_grade`, the narrative-method grade preview."
    PRD §3.1: "While the position remains `DRAFT`, its `official_grade` is null."

    Design: Corner/entities/position_computed_fields_at_creation
    """
    series = create_series()
    resp = api_client.create_position(
        {
            "series_id": series["id"],
            "title": "Analyst",
            "org_code": "OPM1",
            "factor_knowledge_level": 2,
            "factor_supervision_level": 2,
            "factor_complexity_level": 3,
            "factor_impact_level": 2,
            "sensitivity_level": "NONE",
        },
        HM,
    )
    position = validate_success(resp, 201)
    assert_position(position)
    assert position["total_points"] == expected_total_points(2, 2, 3, 2) == 2250
    assert position["provisional_grade"] == expected_provisional_grade(2, 2, 3, 2) == 7
    assert position["official_grade"] is None
    assert position["status"] == "DRAFT"


def test_missing_position_read_returns_not_found_envelope(api):
    """PRD §2.8: "the first identifier that does not resolve to an existing
    entity produces `ERR_NOT_FOUND` (HTTP 404), and later segments are never
    examined."

    Design: Corner/entities/get_missing_position_returns_not_found_envelope
    """
    resp = api_client.get_position(NON_EXISTENT_UUID, HR)
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert isinstance(error.get("message"), str) and error["message"], (
        "error payload must carry a human-readable message")
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["meta"].get("api_request_id"), "error envelope must carry meta.api_request_id"


def test_position_starts_draft_with_null_official_grade(api):
    """PRD §3.1: "The position is born in `DRAFT`" and "While the position
    remains `DRAFT`, its `official_grade` is null."

    Design: Corner/state_machines/position_starts_draft_with_null_official_grade
    """
    series = create_series()
    position = create_draft_position(series["id"])
    assert position["status"] == "DRAFT"
    assert position["official_grade"] is None, (
        f"official_grade must be null while DRAFT, got {position['official_grade']!r}")


def test_classify_from_classified_rejected(api):
    """PRD §3.1: "Classification is the `HRSpecialist`'s act of record, moving
    the position from `DRAFT` to `CLASSIFIED`" — and per §3.2 "a request whose
    transition preconditions fail is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/classify_from_classified_rejected
    """
    _series, position = create_classified_position()
    assert position["official_grade"] == 9

    resp = api_client.classify_position(position["id"], HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    reread = get_success_data(api_client.get_position(position["id"], HR))
    assert reread["status"] == "CLASSIFIED"
    assert reread["official_grade"] == 9, "rejected classify must not change the stored grade"


def test_reclassify_outside_series_range_rejected(api):
    """PRD §3.1: "When the computed grade falls outside the series' inclusive
    range from `min_grade` to `max_grade`, the classification fails with
    `ERR_SERIES_GRADE_RANGE` (HTTP 422) and the position stays `DRAFT`; the same
    range check applies at every later re-grade."

    Design: Corner/validations/reclassify_outside_series_range_rejected
    """
    _series, position = create_classified_position()
    assert position["official_grade"] == 9

    resp = api_client.reclassify_position(
        position["id"],
        reclassify_position_payload(
            position["version"],
            factor_knowledge_level=5, factor_supervision_level=5,
            factor_complexity_level=5, factor_impact_level=5),
        HR)
    validate_error(resp, ApiErrorId.ERR_SERIES_GRADE_RANGE)

    reread = get_success_data(api_client.get_position(position["id"], HR))
    assert reread["official_grade"] == 9, "rejected regrade must leave official_grade alone"
    assert reread["factor_knowledge_level"] == 2, "rejected regrade must not rewrite factor levels"


def test_reclassify_stale_version_occ(api):
    """PRD §2.6: "if the position's current `version` differs — because the
    position has been classified or reclassified since the client last read it —
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client
    must refresh its factor view before re-grading."

    Design: Corner/cross_cutting_layers/reclassify_stale_version_occ
    """
    _series, position = create_classified_position()
    observed_version = position["version"]

    # Fresh version: in-range re-grade (3,3,3,3) -> 3000 points -> grade 11.
    resp = api_client.reclassify_position(
        position["id"],
        reclassify_position_payload(
            observed_version,
            factor_knowledge_level=3, factor_supervision_level=3,
            factor_complexity_level=3, factor_impact_level=3),
        HR)
    regraded = validate_success(resp, 200)
    assert regraded["official_grade"] == expected_official_grade(3000) == 11
    assert regraded["total_points"] == expected_total_points(3, 3, 3, 3) == 3000
    assert regraded["version"] == observed_version + 1 == 3

    # Replaying the stale version must fail the OCC check. The replacement
    # factors here stay inside the series range (2,3,3,2) -> 2450 -> grade 9,
    # so the OCC mismatch is the only rule this request violates (§2.7's
    # ladder makes the concurrency check the last one evaluated).
    resp = api_client.reclassify_position(
        position["id"],
        reclassify_position_payload(
            observed_version,
            factor_knowledge_level=2, factor_supervision_level=3,
            factor_complexity_level=3, factor_impact_level=2),
        HR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    reread = get_success_data(api_client.get_position(position["id"], HR))
    assert reread["official_grade"] == 11, "stale regrade must not change the stored grade"
    assert reread["version"] == 3


def test_position_grade_narrative_vs_point_factor(api):
    """PRD §3.1: "The two grading methods can legitimately disagree on identical
    inputs — levels of 3 across the board preview at grade 9 but classify at
    grade 11, and a profile of 5, 1, 1, 1 previews at grade 5 but classifies at
    grade 9 — so `provisional_grade` is deliberately left stored unchanged by
    classification precisely to preserve that comparison."

    Design: Difficulty/dual_variant_calc/position_grade_narrative_vs_point_factor
    """
    series = create_series()
    resp = api_client.create_position(
        {
            "series_id": series["id"],
            "title": "Analyst",
            "org_code": "OPM1",
            "factor_knowledge_level": 3,
            "factor_supervision_level": 3,
            "factor_complexity_level": 3,
            "factor_impact_level": 3,
            "sensitivity_level": "NONE",
        },
        HM,
    )
    draft = validate_success(resp, 201)
    assert draft["provisional_grade"] == expected_provisional_grade(3, 3, 3, 3) == 9
    assert draft["total_points"] == expected_total_points(3, 3, 3, 3) == 3000
    assert draft["official_grade"] is None and draft["status"] == "DRAFT"

    classified = validate_success(api_client.classify_position(draft["id"], HR), 200)
    assert classified["status"] == "CLASSIFIED"
    assert classified["official_grade"] == expected_official_grade(3000) == 11
    assert classified["provisional_grade"] == 9, (
        "classification must leave the narrative preview stored unchanged")
    assert classified["official_grade"] != classified["provisional_grade"]
