"""Construction-record slot coverage rules and project-version OCC.

Covers the exact-once slot coverage rule (missing and duplicated slots) and
optimistic concurrency on construction-record creation: a stale project version
is rejected, a fresh one succeeds, and supersession advances revisions.
"""

from test_helpers import (
    ApiErrorId,
    CANONICAL_COMPONENTS,
    component_entry,
    construction_record_payload,
    freeze_construction_record,
    make_manufacturer_rep_headers,
    refresh_project,
    setup_open_project,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_construction_record_missing_required_slot_returns_422(api, officer_headers):
    """PRD §3.3: "The array must cover every slot named in the pinned standard's
    `construction_requirements` exactly once: omitting a required slot is
    rejected with `ERR_MISSING_REQUIRED_SLOT`, and listing the same slot twice
    is rejected with `ERR_DUPLICATE_COMPONENT_SLOT`."

    Design: Corner/entities/construction_record_missing_required_slot_returns_422
    """
    ctx = setup_open_project(api)
    mfr_id = ctx["manufacturer"]["id"]
    components = [
        component_entry(
            "enclosure",
            component_name="BayBlend FR3010",
            material="PC/ABS",
            part_number="BB-FR3010",
            rating="V-0",
        )
    ]
    response = api.create_construction_record(
        ctx["project"]["id"],
        construction_record_payload(ctx["project"]["version"], components=components),
        make_manufacturer_rep_headers(mfr_id),
    )
    validate_error(response, ApiErrorId.ERR_MISSING_REQUIRED_SLOT)
    records, _meta = validate_paginated(
        api.list_construction_records(ctx["project"]["id"], officer_headers)
    )
    assert records == [], "a rejected record must not be created"


def test_construction_record_duplicate_slot_returns_422(api, officer_headers):
    """PRD §3.3: "The array must cover every slot named in the pinned standard's
    `construction_requirements` exactly once: omitting a required slot is
    rejected with `ERR_MISSING_REQUIRED_SLOT`, and listing the same slot twice
    is rejected with `ERR_DUPLICATE_COMPONENT_SLOT`."

    Design: Corner/validations/construction_record_duplicate_slot_returns_422
    """
    ctx = setup_open_project(api)
    mfr_id = ctx["manufacturer"]["id"]
    components = [
        component_entry(
            "enclosure",
            component_name="BayBlend FR3010",
            material="PC/ABS",
            part_number="BB-FR3010",
            rating="V-0",
        ),
        component_entry(
            "power_supply",
            component_name="MeanWell RS-25",
            material="n/a",
            part_number="MW-RS-25",
            rating="100-240VAC",
        ),
        component_entry(
            "power_supply",
            component_name="MeanWell RS-35",
            material="n/a",
            part_number="MW-RS-35",
            rating="100-240VAC",
        ),
    ]
    response = api.create_construction_record(
        ctx["project"]["id"],
        construction_record_payload(ctx["project"]["version"], components=components),
        make_manufacturer_rep_headers(mfr_id),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_COMPONENT_SLOT)
    records, _meta = validate_paginated(
        api.list_construction_records(ctx["project"]["id"], officer_headers)
    )
    assert records == [], "a rejected record must not be created"


def test_occ_stale_project_version_on_construction_record_returns_412(api, officer_headers):
    """PRD §2.7: "If the supplied value does not match the parent entity's
    current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412) and no mutation occurs."
    PRD §3.3: "the request must carry `expected_project_version` matching the
    project's current `version`, a mismatch is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and a successful creation increments the project's `version`
    by 1."
    PRD §3.3: "Each new record receives a `revision_no` one greater than the
    highest existing revision number on the project, is created `FROZEN`, and
    automatically supersedes the previously `FROZEN` revision, which becomes
    `SUPERSEDED` (terminal)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_construction_record_returns_412
    """
    ctx = setup_open_project(api)
    mfr_id = ctx["manufacturer"]["id"]
    project = ctx["project"]
    first = freeze_construction_record(api, project)
    assert first["revision_no"] == 1
    assert first["status"] == "FROZEN"
    project = refresh_project(api, project["id"])
    assert project["version"] == 2

    components_v2 = [dict(c) for c in CANONICAL_COMPONENTS]
    components_v2[1]["component_name"] = "MeanWell RS-35"
    components_v2[1]["part_number"] = "MW-RS-35"

    # Replay with the stale pre-mutation version (1) -> 412, no mutation.
    stale = api.create_construction_record(
        project["id"],
        construction_record_payload(1, components=components_v2),
        make_manufacturer_rep_headers(mfr_id),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    # Replay with the freshly observed version (2) -> 201, revision 2 FROZEN.
    replay = api.create_construction_record(
        project["id"],
        construction_record_payload(2, components=components_v2),
        make_manufacturer_rep_headers(mfr_id),
    )
    second = validate_success(replay, 201)
    assert second["revision_no"] == 2
    assert second["status"] == "FROZEN"

    project = refresh_project(api, project["id"])
    assert project["version"] == 3, (
        f"each successful creation bumps the project version by exactly 1, got {project['version']}"
    )

    records, _meta = validate_paginated(
        api.list_construction_records(project["id"], officer_headers)
    )
    by_revision = {record["revision_no"]: record for record in records}
    assert by_revision[1]["status"] == "SUPERSEDED"
    assert by_revision[2]["status"] == "FROZEN"
