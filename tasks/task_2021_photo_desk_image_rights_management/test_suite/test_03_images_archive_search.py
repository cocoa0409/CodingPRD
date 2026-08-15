"""Image ingest, metadata standard, embargo maintenance, archive search, and the
re-use check (PRD §3.3, §3.7)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_image,
    create_active_license,
    create_release,
    get_image_fresh,
    ingest_cleared_wire_image,
    ingest_image_payload,
    ingest_wire_image,
    parse_instant,
    record_usage_run,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_wire_image_ingest_defaults_and_initial_state(api, rights_manager_headers):
    """PRD §3.3: "Clearance moves the image from `INGESTED` to `CLEARED`." PRD
    §3.8: "latches the image's `restriction_status` from `NONE` to `RESTRICTED`".
    PRD §3.5: "its `pricing_variant` is set to `REUSE` when the image's
    `times_used` is greater than zero at that moment, else `FIRST_USE`." PRD
    §3.7: "it is true exactly when `rights_reversion_at` is non-null and the
    logical now is at or after it" and "Wire and stock images never carry a
    reversion date; theirs stays null."

    Design: Corner/entities/wire_image_ingest_defaults_and_initial_state
    """
    resp = api.ingest_image(ingest_image_payload(), rights_manager_headers)
    data = validate_success(resp, 201)
    assert_image(data)
    assert data["status"] == "INGESTED"
    assert data["restriction_status"] == "NONE"
    assert data["times_used"] == 0
    assert data["rights_reverted"] is False
    assert data["base_license_fee_cents"] == 10000


def test_wire_ingest_missing_agency_rejected(api, rights_manager_headers):
    """PRD §3.3: "Independently, a `RightsManager` ingests wire and stock imagery
    directly, supplying `source_type` of `WIRE` or `STOCK`, the `agency_name`
    (required for these two sources), and a `base_license_fee_cents` agency base
    fee that feeds the license fee quote." PRD §2.8: "Request shape — required
    fields, types, enum ranges, and conditional requirements; else
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/image_wire_ingest_missing_agency_rejected
    """
    payload = ingest_image_payload()
    del payload["agency_name"]
    resp = api.ingest_image(payload, rights_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_ingest_assignment_source_rejected(api, rights_manager_headers):
    """PRD §3.3: "Submitting `ASSIGNMENT` as the `source_type` on direct ingest is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/image_ingest_assignment_source_rejected
    """
    payload = ingest_image_payload(
        source_type="ASSIGNMENT",
        base_license_fee_cents=0,
        caption="Firefighters at dawn on the bridge",
        credit_line="Sam Staff / ACME News",
    )
    del payload["agency_name"]
    resp = api.ingest_image(payload, rights_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_image_not_found_returns_404(api, photo_editor_headers):
    """PRD §2.8: "Resource existence — path parameters and body-referenced foreign
    keys resolve to existing resources, validated left-to-right, each surfacing
    its resource-specific not-found code (`ERR_PHOTOGRAPHER_NOT_FOUND`,
    `ERR_STORY_REQUEST_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_IMAGE_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_PAYMENT_RUN_NOT_FOUND`)."

    Design: Corner/entities/get_image_not_found_returns_404
    """
    resp = api.get_image(NON_EXISTENT_UUID, photo_editor_headers)
    validate_error(resp, ApiErrorId.ERR_IMAGE_NOT_FOUND)


def test_archive_from_ingested_rejected(api, rights_manager_headers):
    """PRD §3.3: "From `CLEARED`, a `RightsManager` may archive the image, moving
    it to `ARCHIVED`; the same archive action is available from `PUBLISHED`." PRD
    §2.8: "State-machine from-state preconditions for action endpoints; terminal
    states reject all further transitions; else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/image_archive_from_ingested_rejected
    """
    image = ingest_wire_image()
    assert image["status"] == "INGESTED"
    resp = api.archive_image(image["id"], rights_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_clear_without_credit_line_returns_incomplete_metadata(api, rights_manager_headers):
    """PRD §3.3: "A `RightsManager` clears an `INGESTED` image only when its
    `caption` is present and at least ten characters long and its `credit_line` is
    present and non-empty; otherwise the clear is rejected with
    `ERR_INCOMPLETE_METADATA`."

    Design: Corner/state_machines/clear_without_credit_line_returns_incomplete_metadata
    """
    # Ingest a wire image with a valid caption but no credit_line.
    payload = ingest_image_payload()
    del payload["credit_line"]
    resp = api.ingest_image(payload, rights_manager_headers)
    image = validate_success(resp, 201)

    resp = api.clear_image(image["id"], rights_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INCOMPLETE_METADATA)


def test_embargo_set_then_cleared_with_null(api, rights_manager_headers):
    """PRD §3.3: "A `RightsManager` may later set or clear the embargo — passing
    null clears it — via the embargo-update capability, which increments the
    image's `version` by one."

    Design: Corner/state_machines/embargo_set_then_cleared_with_null
    """
    image = ingest_cleared_wire_image()

    set_resp = api.set_embargo(image["id"], {"embargo_until": "2026-09-01T00:00:00Z"}, rights_manager_headers)
    after_set = validate_success(set_resp, 200)
    assert parse_instant(after_set["embargo_until"]) == parse_instant("2026-09-01T00:00:00Z")

    clear_resp = api.set_embargo(image["id"], {"embargo_until": None}, rights_manager_headers)
    after_clear = validate_success(clear_resp, 200)
    assert after_clear["embargo_until"] is None, "passing null must clear the embargo"
    assert after_clear["version"] == after_set["version"] + 1, (
        "each embargo write must increment the image version by exactly one"
    )


def test_images_search_filters_pagination_and_archive_visibility(api, archivist_headers):
    """PRD §3.3: "Archiving is a soft removal: archived images are excluded from
    default archive search results unless the caller passes `include_archived=true`,
    a flag honored only for `Archivist` and `RightsManager`." PRD §3.3: "Archive
    search lets any desk role filter images by `q` (matching keywords and caption
    text), `status`, `source_type`, `photographer_id`, or `assignment_id`, with
    `limit` and `offset` pagination." PRD §2.3: "Paginated list responses carry
    `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/endpoints/images_search_filters_pagination_and_archive_visibility
    """
    w1 = ingest_cleared_wire_image(keywords=["flood"])  # caption: Flooded main street...
    w2 = ingest_cleared_wire_image(
        source_type="STOCK", agency_name="StockHouse", base_license_fee_cents=8000,
        caption="Aerial view of the harbor at dusk", credit_line="StockHouse / StockHouse",
    )
    w3 = ingest_cleared_wire_image(
        base_license_fee_cents=12000, caption="Championship celebration on the pitch",
    )
    validate_success(api.archive_image(w3["id"], TEST_USERS["rights_manager_headers"]), 200)

    # Default list: ARCHIVED image excluded.
    data, meta = validate_paginated(api.list_images(archivist_headers))
    assert meta["total_count"] == 2, f"ARCHIVED image must be excluded by default, got {meta['total_count']}"
    assert len(data) == 2

    # include_archived=true (Archivist is permitted): all three.
    data, meta = validate_paginated(api.list_images(archivist_headers, params={"include_archived": True}))
    assert meta["total_count"] == 3

    # source_type filter: only the non-archived WIRE image remains.
    data, meta = validate_paginated(api.list_images(archivist_headers, params={"source_type": "WIRE"}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == w1["id"]

    # q filter matches keywords/caption text.
    data, meta = validate_paginated(api.list_images(archivist_headers, params={"q": "flood"}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == w1["id"]

    # Pagination window into the default two-item list.
    data, meta = validate_paginated(api.list_images(archivist_headers, params={"limit": 1, "offset": 1}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert data[0]["id"] == w2["id"], "created_at ascending order: offset 1 yields the second image"


def test_include_archived_forbidden_for_photo_editor(api, photo_editor_headers):
    """PRD §2.1: "One additional access rule: the archive search's
    `include_archived` flag may be set to `true` only by `Archivist` and
    `RightsManager`; any other role passing `include_archived=true` is rejected
    with `ERR_FORBIDDEN`."

    Design: Corner/endpoints/include_archived_forbidden_for_photo_editor
    """
    ingest_cleared_wire_image()
    resp = api.list_images(photo_editor_headers, params={"include_archived": True})
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_reuse_check_reports_eligibility_requirements_and_quote(api, archivist_headers, rights_manager_headers):
    """PRD §3.7: "The check returns `eligible`, a list of `blocking_reasons`, a
    `fee_quote_cents` computed by the same fee-quote rule as §3.5 against the
    image's current state, the `pricing_variant` that would apply, and the
    booleans `requires_model_release` and `requires_property_release` reflecting
    the image's depictions."

    Design: Corner/endpoints/reuse_check_computed_read_blockers_and_quote
    """
    image = ingest_cleared_wire_image(
        caption="Actor on the gala red carpet",
        has_identifiable_people=True,
        embargo_until="2026-08-05T00:00:00Z",
    )

    first = validate_success(
        api.reuse_check(image["id"], archivist_headers,
                        params={"channel": "DIGITAL", "published_at": "2026-08-03T00:00:00Z"}),
        200,
    )
    assert first["eligible"] is False, (
        "pre-embargo publication with a missing MODEL release must be ineligible"
    )
    assert isinstance(first["blocking_reasons"], list)
    assert first["requires_model_release"] is True
    assert first["requires_property_release"] is False
    # Same fee-quote rule as licensing: 10000 x DIGITAL 1.2 x DOMESTIC 1.0, non-exclusive.
    assert first["fee_quote_cents"] == 12000
    assert first["pricing_variant"] == "FIRST_USE"

    create_release(image["id"], subject_type="MODEL", subject_name="Actor A")

    second = validate_success(
        api.reuse_check(image["id"], archivist_headers,
                        params={"channel": "DIGITAL", "published_at": "2026-08-06T00:00:00Z"}),
        200,
    )
    assert second["eligible"] is True, (
        "with the MODEL release registered and the embargo lifted, re-use must be eligible"
    )
    assert second["fee_quote_cents"] == 12000


def test_times_used_reconciles_with_usage_log_across_archival(api, rights_manager_headers):
    """PRD §3.7: "The line is then added to the photographer's
    `accrued_earnings_cents`, and the image's `times_used` increments by one."
    PRD §3.3: "Archiving is a soft removal: archived images are excluded from
    default archive search results unless the caller passes `include_archived=true`,
    a flag honored only for `Archivist` and `RightsManager`."

    Design: Corner/complexity_layers/image_times_used_derived_field_reconciliation
    """
    image = ingest_cleared_wire_image()
    lic = create_active_license(image["id"])

    record_usage_run(image["id"], lic["id"], story_slug="flood-day-one",
                     published_at="2026-08-03T12:00:00Z")
    record_usage_run(image["id"], lic["id"], story_slug="flood-day-two",
                     published_at="2026-08-04T12:00:00Z")

    after_runs = get_image_fresh(image["id"])
    assert after_runs["times_used"] == 2, "times_used must reconcile with the two recorded runs"

    validate_success(api.archive_image(image["id"], rights_manager_headers), 200)
    after_archive = get_image_fresh(image["id"])
    assert after_archive["status"] == "ARCHIVED"
    assert after_archive["times_used"] == 2, "archival must not erase usage history"
