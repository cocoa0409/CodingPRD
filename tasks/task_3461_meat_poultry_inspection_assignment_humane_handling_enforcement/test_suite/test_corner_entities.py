"""Breadth tests: entity creation defaults, listings, and field ownership."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    DISTRICT_MANAGER_HEADERS,
    PROGRAM_ADMINISTRATOR_HEADERS,
    assert_effectiveness_check,
    assert_envelope_meta,
    assert_establishment,
    assert_grant_application,
    assert_list_page,
    assert_recall,
    assert_shift_assignment,
    factories as f,
    fixtures as fx,
    make_establishment_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_establishment_create_returns_declared_defaults(api):
    """PRD §3.1: "The new establishment begins life at `grant_status`
    `UNGRANTED` and `inspection_status` `INACTIVE`, at `version` 1."
    PRD §3.6: "If no pathogen has sufficient samples, the category is unchanged
    (null if the establishment has never been categorized)."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/establishment_create_returns_declared_defaults
    """
    resp = api.create_establishment(
        f.establishment_payload(name="C1 Beef Plant", species_classes=["CATTLE"], slaughter_capable=True),
        PROGRAM_ADMINISTRATOR_HEADERS,
    )

    data = validate_success(resp, 201)
    assert_envelope_meta(resp.json())
    assert_establishment(data)
    assert data["grant_status"] == "UNGRANTED"
    assert data["inspection_status"] == "INACTIVE"
    assert data["pathogen_category"] is None
    assert data["open_nr_count"] == 0
    assert data["suspension_count"] == 0
    assert data["version"] == 1


def test_grant_application_create_defaults_findings_pending(api):
    """PRD §3.1: "A fresh application lands in `SUBMITTED` with all three
    findings — `facility_finding`, `sanitation_finding`, and `haccp_finding` —
    at `PENDING`, a `revision_count` of 0, and no `decided_at`."

    Design: Corner/entities/grant_application_create_defaults_findings_pending
    """
    est = fx.create_establishment(api, name="C2 Pork Plant", species_classes=["SWINE"],
                                  slaughter_capable=False)

    resp = api.create_grant_application(
        f.grant_application_payload(est["id"]), make_establishment_manager_headers(est["id"])
    )

    data = validate_success(resp, 201)
    assert_grant_application(data)
    assert data["facility_finding"] == "PENDING"
    assert data["sanitation_finding"] == "PENDING"
    assert data["haccp_finding"] == "PENDING"
    assert data["revision_count"] == 0
    assert data["status"] == "SUBMITTED"
    assert data["decided_at"] is None


def test_noncompliance_records_list_paginates(api):
    """PRD §2.3: "List endpoints accept two query parameters. The `limit`
    parameter caps the number of items returned: it defaults to 10 when
    omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter
    specifies how many items to skip and defaults to 0."
    PRD §2.3: "List responses carry the fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."

    Design: Corner/entities/noncompliance_records_list_paginates
    """
    est = fx.create_establishment(api, name="C3 Plant", species_classes=["CATTLE"])
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
    for i in range(3):
        fx.issue_nr(api, est["id"], inspector["id"], regulation_family="SANITATION",
                    description=f"nr {i + 1}")

    page1, meta1 = validate_paginated(
        api.list_noncompliance_records(DISTRICT_MANAGER_HEADERS, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert_list_page(meta1, limit=2, offset=0, total_count=3, has_more=True)

    page2, meta2 = validate_paginated(
        api.list_noncompliance_records(DISTRICT_MANAGER_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert_list_page(meta2, limit=2, offset=2, total_count=3, has_more=False)

    all_rows, meta_all = validate_paginated(api.list_noncompliance_records(DISTRICT_MANAGER_HEADERS))
    assert len(all_rows) == 3, "defaults limit=10, offset=0 return the whole set"
    assert_list_page(meta_all, limit=10, offset=0, total_count=3, has_more=False)


def test_establishment_get_unknown_id_returns_not_found(api):
    """PRD §2.7: "Resource identifiers in the path are validated left to right,
    and body-supplied foreign-key references are then checked — a missing
    Establishment yields `ERR_ESTABLISHMENT_NOT_FOUND`, and correspondingly
    `ERR_GRANT_APPLICATION_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`,
    `ERR_SHIFT_WINDOW_NOT_FOUND`, `ERR_SHIFT_ASSIGNMENT_NOT_FOUND`,
    `ERR_NONCOMPLIANCE_RECORD_NOT_FOUND`, `ERR_ENFORCEMENT_ACTION_NOT_FOUND`,
    `ERR_HUMANE_EVENT_NOT_FOUND`, `ERR_PATHOGEN_SAMPLE_NOT_FOUND`,
    `ERR_LABEL_APPLICATION_NOT_FOUND`, `ERR_RECALL_NOT_FOUND`, or
    `ERR_APPEAL_NOT_FOUND` (all HTTP 404)."

    Design: Corner/entities/establishment_get_unknown_id_returns_not_found
    """
    resp = api.get_establishment(NON_EXISTENT_UUID, DISTRICT_MANAGER_HEADERS)

    error = validate_error(resp, ApiErrorId.ERR_ESTABLISHMENT_NOT_FOUND)
    assert isinstance(error.get("message"), str) and error["message"], "error carries a message"
    assert resp.json()["response_type"] == "error"


def test_establishment_create_missing_species_classes_returns_invalid_request(api):
    """PRD §2.7: "Field-shape failures anywhere — a missing required field, a
    type mismatch, an enum member outside its declared set, an empty
    `species_classes` array, a `quantity_lbs` that is not greater than 0, an
    interval whose end is not strictly after its start or that falls outside
    its window, `grounds` shorter than 10 characters, `abatement_evidence`
    shorter than 20 characters, or a duplicate `badge_number` — are rejected
    with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "A `ProgramAdministrator` registers each establishment by
    supplying its `name`, the `species_classes` it handles — a non-empty array
    drawn from `CATTLE`, `SWINE`, `POULTRY`, and `SHEEP` (an empty array is
    rejected with `ERR_INVALID_REQUEST`) — and the `slaughter_capable` flag,
    which records whether the establishment performs slaughter and is therefore
    subject to the continuous-presence verification regime of §3.2."

    Design: Corner/entities/establishment_create_missing_species_classes_returns_invalid_request
    """
    resp = api.create_establishment(
        {"name": "No Species Plant", "slaughter_capable": True},
        PROGRAM_ADMINISTRATOR_HEADERS,
    )

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"


def test_recall_effectiveness_check_is_append_only_without_version(api):
    """PRD §2.6: "One resource is deliberately thinner. A recall effectiveness
    check is an append-only event record: it carries `id` and `created_at`
    only, with no `updated_at` and no `version`, and it is never modified after
    creation."

    Design: Corner/entities/recall_effectiveness_check_is_append_only_without_version
    """
    est = fx.create_establishment(api, name="C6 Plant", species_classes=["CATTLE"])
    recall = fx.create_class_determined_recall(
        api, est["id"], "CLASS_III", product_description="ground beef lot 7", quantity_lbs=1200.5
    )

    resp = api.record_effectiveness_check(
        recall["id"],
        f.effectiveness_check_payload(
            consignee_name="Depot One", outcome="EFFECTIVE", checked_at="2026-08-31T09:00:00Z"
        ),
        fx.RECALL_COORDINATOR_HEADERS,
    )

    data = validate_success(resp, 201)
    assert_effectiveness_check(data)
    assert data["outcome"] == "EFFECTIVE"
    assert data["consignee_name"] == "Depot One"
    assert data["recall_id"] == recall["id"]


def test_shift_assignment_denormalizes_establishment_from_window(api):
    """PRD §3.2: "At creation the assignment's `establishment_id` is
    denormalized from its shift window, and its `status` begins at
    `SCHEDULED`."

    Design: Corner/entities/shift_assignment_denormalizes_establishment_from_window
    """
    base = fx.setup_granted_with_window(
        api, species_classes=["CATTLE"], name="C7 Plant", shift_type="PROCESSING"
    )
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])

    resp = api.create_assignment(
        base["window"]["id"],
        f.assignment_payload(
            inspector["id"], 1, "2026-09-02T06:00:00Z", "2026-09-02T10:00:00Z",
            base["window"]["version"],
        ),
        PROGRAM_ADMINISTRATOR_HEADERS,
    )

    data = validate_success(resp, 201)
    assert_shift_assignment(data)
    assert data["establishment_id"] == base["establishment"]["id"], (
        "denormalized from the window, not from any payload field"
    )
    assert data["shift_window_id"] == base["window"]["id"]
    assert data["status"] == "SCHEDULED"


def test_recall_determine_class_sets_derived_requirements(api):
    """PRD §3.8: "The class pins the closure requirements: a `CLASS_I` recall
    requires at least 10 effectiveness checks and an effectiveness ratio of at
    least 0.95; `CLASS_II` requires at least 5 checks and 0.80; `CLASS_III`
    requires at least 4 checks and 0.75. Both values are stored on the recall
    as `required_min_checks` and `required_effectiveness_ratio`."
    PRD §3.8: "The case is born `INITIATED` with `recall_class` null and both
    requirement fields, `required_min_checks` and `required_effectiveness_ratio`,
    unset; its effectiveness counters `checks_performed` and `checks_effective`
    start at 0 and its `effectiveness_ratio` is null while no checks are
    recorded."

    Design: Corner/entities/recall_determine_class_sets_derived_requirements
    """
    est = fx.create_establishment(api, name="C8 Plant", species_classes=["CATTLE"])
    recall = fx.create_recall(api, est["id"], product_description="trim lot 9", quantity_lbs=800)

    fx.determine_recall_class(api, recall["id"], "CLASS_I")
    data = fx.get_recall(api, recall["id"])

    assert_recall(data)
    assert data["recall_class"] == "CLASS_I"
    assert data["status"] == "CLASS_DETERMINED"
    assert data["required_min_checks"] == 10
    assert data["required_effectiveness_ratio"] == 0.95
    assert data["checks_performed"] == 0
    assert data["checks_effective"] == 0
    assert data["effectiveness_ratio"] is None
