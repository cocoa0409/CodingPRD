"""Resource creation, identity and validation boundaries (queue B)."""
import pytest
from test_helpers import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import project_payload, revision_payload, worker_payload
from test_helpers.fixtures import (
    create_coordinated_model,
    create_draft_model,
    create_project,
    register_default_assembly,
)


# --------------------------------------------------------------------------
# entities / project_creation_returns_derived_defaults
# --------------------------------------------------------------------------

def test_freshly_created_project_reports_derived_defaults(api, admin_headers):
    """PRD §2.10: "A project with no non-`COMPLETE` activity has `slippage_pct` of
    zero and posture `ON_TRACK`."
    PRD §3.2: "The `credit_policy` input selects which of the two crew-day credit
    variants the field-credit computation uses; it is either `FIRST_ACCEPTED` or
    `HIGHEST_TOTAL`, and when omitted it defaults to `FIRST_ACCEPTED`."

    Design: Corner/entities/project_creation_returns_derived_defaults
    """
    payload = project_payload(project_code="P-3333-CR1")
    payload.pop("credit_policy")
    project = validate_success(api.create_project(payload, admin_headers),
                               expected_status=201)

    assert project["project_posture"] == "ON_TRACK"
    assert project["slippage_pct"] == 0.0
    assert project["credit_policy"] == "FIRST_ACCEPTED", (
        "an omitted credit policy resolves to the FIRST_ACCEPTED variant"
    )


# --------------------------------------------------------------------------
# entities / project_read_not_found
# --------------------------------------------------------------------------

def test_reading_an_unknown_project_returns_not_found(api, admin_headers):
    """PRD §2.8: "Third, existence of the explicitly named entities, in this order —
    the project named in the path or body (`ERR_PROJECT_NOT_FOUND`, HTTP 404)".
    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format".

    Design: Corner/entities/project_read_not_found
    """
    error = validate_error(
        api.get_project(NON_EXISTENT_UUID, admin_headers),
        ApiErrorId.ERR_PROJECT_NOT_FOUND,
    )
    assert error["error_id"] == "ERR_PROJECT_NOT_FOUND"


# --------------------------------------------------------------------------
# entities / model_version_lineage_self_reference
# --------------------------------------------------------------------------

def test_two_versions_share_one_lineage_and_keep_independent_totals(api,
                                                                    model_coordinator_headers):
    """PRD §3.1: "A `ModelCoordinator` registers a building model revision letter
    and points it at the version it succeeds using `model_id`, forming a
    self-referential lineage chain across successive letters".
    PRD §3.1: "A newly registered version is `DRAFT`, its `zone_quantity_total`
    starts at zero and its `empty_takeoff` flag starts true."

    Design: Corner/entities/model_version_lineage_self_reference
    """
    create_project(project_code="P-3333-CR2")
    first = create_draft_model(model_id="mdl-cs", revision_letter="A")
    second = create_draft_model(model_id="mdl-cs", revision_letter="B")

    listed = api.list_model_versions(model_coordinator_headers, {"model_id": "mdl-cs"})
    rows = validate_success(listed, expected_status=200)
    data = rows["data"] if isinstance(rows, dict) else rows
    ids = {row["id"] for row in data}
    assert {first["id"], second["id"]}.issubset(ids), (
        "both versions appear in the filtered lineage list"
    )

    assert first["model_id"] == "mdl-cs"
    assert second["model_id"] == "mdl-cs"
    assert first["zone_quantity_total"] == 0
    assert second["zone_quantity_total"] == 0
    assert first["empty_takeoff"] is True


# --------------------------------------------------------------------------
# entities / takeoff_line_system_hash_is_server_stamped
# --------------------------------------------------------------------------

def test_takeoff_hash_is_stamped_by_the_server(api, admin_headers,
                                               model_coordinator_headers):
    """PRD §2.4: "others are stamped by the server because they record when
    something happened (a `coordinated_at_iso`, an `actual_start_iso`, a
    `release_to_shop_iso`, a `restriction_since_iso`, a `locked_release_iso`, a
    `takeoff_hash`)".
    PRD §3.1: "Extraction stamps a content hash — `takeoff_hash`, a digest over the
    version, zone, assembly and quantity — and that hash is the line's duplicate key".
    PRD §3.1: "`zone_quantity_total` is the sum of the quantity of every
    non-superseded line extracted from that version".

    Design: Corner/entities/takeoff_line_system_hash_is_server_stamped
    """
    register_default_assembly("A-RACK")
    model, lines = create_coordinated_model(model_id="mdl-cu", takeoff_lines=[
        {"zone_code": "Z-1", "quantity": 10},
    ])
    assert lines[0]["takeoff_hash"], (
        "the hash is derived by the server, never supplied by the client"
    )

    line = validate_success(
        api.create_takeoff_line(
            {
                "model_version_id": model["id"], "zone_code": "Z-9",
                "assembly_code": "A-RACK", "conduit_run_type": "RIGID_RACK",
                "conduit_run_type_code": "RC50", "quantity": 10,
                "prefab_share_pct": 0.5,
            },
            model_coordinator_headers,
        ),
        expected_status=201,
    )
    assert line["takeoff_hash"] and line["takeoff_hash"] != lines[0]["takeoff_hash"], (
        "a different extraction tuple yields a different digest"
    )

    listed = api.list_takeoff_lines(model_coordinator_headers, {"model_version_id": model["id"]})
    data = listed.json()["data"]
    assert sum(row["quantity"] for row in data) == 20
    assert any(row["id"] == line["id"] for row in data)


# --------------------------------------------------------------------------
# entities / worker_apprentice_period_required_only_for_apprentices
# --------------------------------------------------------------------------

def test_apprentice_period_consistency_rule(api, general_foreman_headers):
    """PRD §3.5: "A worker's `apprentice_period` must be a member of the range 1 to
    5 exactly when the worker's `classification` is `APPRENTICE`, and must be null
    for every other classification; a violation is refused with
    `ERR_APPRENTICE_PERIOD_INVALID` (HTTP 422)."

    Design: Corner/entities/worker_apprentice_period_required_only_for_apprentices
    """
    apprentice_without_period = worker_payload(classification="APPRENTICE",
                                               apprentice_period=None,
                                               worker_code="W-BAD-1")
    validate_error(api.create_worker(apprentice_without_period, general_foreman_headers),
                   ApiErrorId.ERR_APPRENTICE_PERIOD_INVALID)

    journeyman_with_period = worker_payload(classification="JOURNEYMAN",
                                            apprentice_period=3, worker_code="W-BAD-2")
    validate_error(api.create_worker(journeyman_with_period, general_foreman_headers),
                   ApiErrorId.ERR_APPRENTICE_PERIOD_INVALID)

    accepted = validate_success(
        api.create_worker(
            worker_payload(classification="APPRENTICE", apprentice_period=3,
                           worker_code="W-GOOD-1"),
            general_foreman_headers,
        ),
        expected_status=201,
    )
    assert accepted["apprentice_period"] == 3


def test_accepted_apprentice_is_credited_with_ring_hours(api, general_foreman_headers):
    """PRD §3.6: "Registration also stamps the worker's safety verification expiry as
    the logical clock instant plus 90 days and initializes `journey_ring_claim_hours`
    to 0."
    PRD §2.5: "Registering a worker also stamps a safety-verification expiry,
    computed as the logical clock instant plus 90 days."

    Design: Corner/entities/worker_apprentice_period_required_only_for_apprentices
    """
    accepted = validate_success(
        api.create_worker(
            worker_payload(classification="APPRENTICE", apprentice_period=3,
                           worker_code="W-GOOD-2"),
            general_foreman_headers,
        ),
        expected_status=201,
    )
    assert accepted["journey_ring_claim_hours"] == 0
    assert accepted["upgrade_eligible"] is False
    assert accepted["credited_field_hours"] == 0


# --------------------------------------------------------------------------
# entities / qualification_code_length_boundary
# --------------------------------------------------------------------------

def test_qualification_code_is_capped_at_forty_characters(api, general_foreman_headers):
    """PRD §3.5: "A worker's `qualification_state_code` may be at most 40 characters
    and is rejected with `ERR_SHIFT_BAND_TOO_LONG` (HTTP 422) if longer."

    Design: Corner/entities/qualification_code_length_boundary
    """
    accepted = validate_success(
        api.create_worker(
            worker_payload(worker_code="W-LEN-40", qualification_state_code="Q" * 40,
                           classification="JOURNEYMAN", apprentice_period=None),
            general_foreman_headers,
        ),
        expected_status=201,
    )
    assert accepted["shift_band_delta"] == 0

    validate_error(
        api.create_worker(
            worker_payload(worker_code="W-LEN-41", qualification_state_code="Q" * 41,
                           classification="JOURNEYMAN", apprentice_period=None),
            general_foreman_headers,
        ),
        ApiErrorId.ERR_SHIFT_BAND_TOO_LONG,
    )


# --------------------------------------------------------------------------
# entities / revision_lifecycle_percent_monotonicity
# --------------------------------------------------------------------------

def test_replacement_lifecycle_may_not_trail_the_replaced_content(api,
                                                                  model_coordinator_headers,
                                                                  project_manager_headers):
    """PRD §3.7: "a revision whose `replacement_lifecycle_percent` is below its
    `prior_lifecycle_percent` — a replacement younger than the content it replaces —
    is refused with `ERR_SERVICE_LIFECYCLE_INVALID` (HTTP 422)."
    PRD §2.4: "The service never applies a partial mutation: if any precondition of
    an operation fails, no field of the target resource, and no cascaded field of any
    related resource, is changed."

    Design: Corner/entities/revision_lifecycle_percent_monotonicity
    """
    project = create_project(project_code="P-3333-CR3")
    model_a, lines = create_coordinated_model(model_id="mdl-ct", revision_letter="A",
                                              takeoff_lines=[{"quantity": 10}])
    successor = create_draft_model(model_id="mdl-ct", revision_letter="B")

    payload = revision_payload(
        project_id=project["id"], model_version_id=model_a["id"],
        revised_version_id=successor["id"], revision_kind="RFI_RESPONSE",
        impact_keys=[lines[0]["takeoff_hash"]],
        replacement_lifecycle_percent=40, prior_lifecycle_percent=60,
    )
    validate_error(api.create_revision(payload, project_manager_headers),
                   ApiErrorId.ERR_SERVICE_LIFECYCLE_INVALID)

    listed = api.list_revisions(project_manager_headers, {"project_id": project["id"]})
    assert listed.json()["data"] == [], "no revision row was created for the refused call"