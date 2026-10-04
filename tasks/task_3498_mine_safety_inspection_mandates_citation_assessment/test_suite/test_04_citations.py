"""Citation reads and listings (PRD §3.4, §2.3, §2.10): computed-field
round-trip, pagination, conjunctive filters, the 1:1 assessment sub-resource,
and the version/timestamp mutation contract.

Clock note: all logical-clock readings are >= the startup reading
2026-09-01T00:00:00Z (PRD §2.4). Issuance at 2026-09-10T09:00:00Z with
NO_INJURY severity (30-day base) yields abatement_deadline
2026-10-10T09:00:00Z.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    abate_citation_flow,
    assert_citation,
    file_contest_flow,
    get_success_data,
    in_progress_inspection,
    issue_citation,
    issue_n_citations,
    make_inspector_headers,
    set_clock,
    setup_citation,
    setup_inspector,
    setup_registry,
    validate_error,
    validate_paginated,
    validate_success,
    verify_citation_flow,
)

_DM = TEST_USERS["district_manager_headers"]


def test_citation_get_round_trips_computed_fields(api):
    """PRD §3.4: "The `abatement_base_days` derive from `gravity_severity`:
    30 days for `NO_INJURY`, 15 for `MINOR`, 5 for `SERIOUS`, and 1 for
    `FATAL_POTENTIAL`; the `abatement_deadline` is `issued_at` plus that many
    days."
    PRD §3.4: "Issuance stamps `issued_at` from the logical clock, records the
    acting inspector as `issued_by_inspector_id`, and leaves `system_issued`
    false."

    Design: Corner/entities/citation_get_round_trips_computed_fields
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(inspection, mine, i1)

    data = validate_success(
        api.get_citation(citation["id"], make_inspector_headers(i1["id"]))
    )
    assert_citation(data)
    assert data["issued_at"] == "2026-09-10T09:00:00Z"
    assert data["abatement_base_days"] == 30
    assert data["abatement_deadline"] == "2026-10-10T09:00:00Z"
    assert data["abatement_status"] == "OPEN"
    assert data["contest_status"] == "UNCONTESTED"
    assert data["abatement_extended"] is False
    assert data["issued_by_inspector_id"] == i1["id"]
    assert data["system_issued"] is False


def test_citations_list_paginates_with_total_count(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items skipped and defaults to 0.
    Paginated list responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."
    PRD §3.4: "The citations listing filters by `mine_id`, `inspection_id`,
    `issued_by_inspector_id`, `verified_by_inspector_id`, `abatement_status`,
    `contest_status`, and `significant_and_substantial`"

    Design: Corner/entities/citations_list_paginates_with_total_count
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    issue_n_citations(inspection, mine, i1, 3)

    page1, meta1 = validate_paginated(
        api.list_citations(_DM, params={"mine_id": mine["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3, "total_count counts the filtered set, not the page"
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_citations(_DM, params={"mine_id": mine["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    rows, meta3 = validate_paginated(
        api.list_citations(
            _DM, params={"mine_id": mine["id"], "significant_and_substantial": "false"}
        )
    )
    assert len(rows) == 3 and meta3["total_count"] == 3

    rows, meta4 = validate_paginated(
        api.list_citations(_DM, params={"mine_id": mine["id"], "abatement_status": "OPEN"})
    )
    assert len(rows) == 3 and meta4["total_count"] == 3


def test_citation_get_unknown_id_returns_not_found(api):
    """PRD §2.5 tier 4: "Path identifiers resolve left-to-right, then body
    foreign keys resolve (`operator_id`, `mine_id`, `inspector_id`,
    `cycle_id`, `accident_id`, `citation_id`, `new_inspector_id`); the first
    unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/citation_get_unknown_id_returns_not_found
    """
    set_clock("2026-09-10T08:00:00Z")
    resp = api.get_citation(NON_EXISTENT_UUID, _DM)
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert isinstance(error_data["message"], str) and error_data["message"].strip()


def test_citation_list_filters_combine(api):
    """PRD §3.4: "The citations listing filters by `mine_id`, `inspection_id`,
    `issued_by_inspector_id`, `verified_by_inspector_id`, `abatement_status`,
    `contest_status`, and `significant_and_substantial`"
    PRD §3.6: "A successful filing stamps `filed_at` from the clock, creates
    the contest in `FILED` status, moves the citation's contest axis from
    `UNCONTESTED` to `CONTESTED` with a `Citation.version` increment, and moves
    the linked assessment from `PROPOSED` to `CONTESTED`."

    Design: Corner/endpoints/citation_list_filters_combine
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    citations = issue_n_citations(inspection, mine, i1, 3)
    contested = citations[2]
    file_contest_flow(contested, operator)

    rows, meta = validate_paginated(
        api.list_citations(
            _DM, params={"mine_id": mine["id"], "contest_status": "CONTESTED"}
        )
    )
    assert [r["id"] for r in rows] == [contested["id"]]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_citations(
            _DM, params={"mine_id": mine["id"], "contest_status": "UNCONTESTED"}
        )
    )
    assert len(rows) == 2 and meta["total_count"] == 2
    assert contested["id"] not in {r["id"] for r in rows}

    rows, meta = validate_paginated(
        api.list_citations(
            _DM, params={"mine_id": mine["id"], "abatement_status": "OPEN"}
        )
    )
    assert len(rows) == 3 and meta["total_count"] == 3


def test_assessment_subresource_returns_singleton(api):
    """PRD §2.10: "The penalty-assessment listing of a citation in particular
    returns an array of zero or one element, since exactly one assessment
    exists per citation once the citation exists."
    PRD §3.4: "Every citation automatically spawns exactly one
    **PenaltyAssessment** in `PROPOSED` status, storing the computed
    `points_total` and a `proposed_penalty_cents` figure produced by the dollar
    pipeline."

    Design: Corner/endpoints/assessment_subresource_returns_singleton
    """
    set_clock("2026-09-10T08:00:00Z")
    bundle = setup_citation()
    citation = bundle["citation"]

    resp = api.list_citation_penalty_assessments(citation["id"], _DM)
    assert resp.status_code == 200
    assert resp.json()["response_type"] == "array", (
        "the sub-resource read keeps the array shape regardless of cardinality"
    )
    rows, meta = validate_paginated(resp)
    assert len(rows) == 1 and meta["total_count"] == 1
    assert rows[0]["citation_id"] == citation["id"]
    assert rows[0]["status"] == "PROPOSED"


def test_citation_version_increments_on_every_mutation(api):
    """PRD §2.4: "The `version` is an integer that increments by exactly one on
    every mutation, and it is the basis of the optimistic concurrency rules in
    §2.8."
    PRD §2.4: "`updated_at` refreshes on every mutation of the resource."
    PRD §3.4: "An `OperatorRep` of the mine's operator reports abatement with
    an `abatement_note`, moving the axis from `OPEN` to `ABATED`, stamping
    `abated_at`, and incrementing the citation's `version`; a representative of
    any other operator is rejected with `ERR_OPERATOR_MISMATCH`."

    Note: PRD pins the +1-per-mutation delta rather than the start value, so
    the assertions track exact deltas between observed versions.

    Design: Corner/complexity_layers/citation_version_increments_on_every_mutation
    """
    set_clock("2026-09-10T09:00:00Z")
    bundle = setup_citation()
    citation = bundle["citation"]
    v_created = citation["version"]

    set_clock("2026-09-11T09:00:00Z")
    abated = abate_citation_flow(citation, bundle["operator"])
    assert abated["version"] == v_created + 1
    assert abated["updated_at"] == "2026-09-11T09:00:00.000Z"

    set_clock("2026-09-12T09:00:00Z")
    verifier = setup_inspector()
    verified = verify_citation_flow(abated, verifier)
    assert verified["version"] == abated["version"] + 1
    assert verified["updated_at"] == "2026-09-12T09:00:00.000Z"

    final = get_success_data(api.get_citation(citation["id"], _DM))
    assert final["version"] == verified["version"]


def test_immediate_visibility_of_create_response_and_readback(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.4: "The `abatement_base_days` derive from `gravity_severity`:
    30 days for `NO_INJURY`, 15 for `MINOR`, 5 for `SERIOUS`, and 1 for
    `FATAL_POTENTIAL`; the `abatement_deadline` is `issued_at` plus that many
    days."

    Design: Corner/consistency_model/immediate_visibility_of_create_response_and_readback
    """
    set_clock("2026-09-10T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    set_clock("2026-09-10T09:00:00Z")
    created = issue_citation(inspection, mine, i1)

    # The create response itself already carries the computed fields.
    assert created["issued_at"] == "2026-09-10T09:00:00Z"
    assert created["abatement_base_days"] == 30
    assert created["abatement_deadline"] == "2026-10-10T09:00:00Z"
    assert created["abatement_status"] == "OPEN"

    # An immediate read-back returns the identical derived values.
    read = validate_success(api.get_citation(created["id"], _DM))
    assert read["issued_at"] == created["issued_at"]
    assert read["abatement_deadline"] == created["abatement_deadline"]
    assert read["abatement_status"] == created["abatement_status"]
    assert read["version"] == created["version"]
