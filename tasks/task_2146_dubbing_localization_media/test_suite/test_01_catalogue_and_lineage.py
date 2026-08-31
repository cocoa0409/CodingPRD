"""Catalogue: properties, cuts and their self-referential lineage, plus the
platform specification, the talent bench and the logical clock."""

from test_helpers import (
    ADMIN,
    CASTING,
    MIXER,
    PC,
    REVIEWER,
    ApiErrorId,
    UNKNOWN_UUID,
    UNKNOWN_UUIDS,
    api_client,
    assert_cut,
    assert_same_instant,
    assert_title,
    assert_voice_talent,
    create_platform_spec,
    create_platform_spec_payload,
    create_title_payload,
    create_voice_talent_payload,
    derive_cut,
    make_adaptor_headers,
    make_native_reviewer_headers,
    setup_canon,
    setup_draft_order,
    setup_locked_cut_and_spec,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_register_title_returns_201_with_server_minted_identity(api):
    """PRD §3.1: "Registration supplies a `title_code` — the vendor-side catalogue
    code, which must be non-empty and unique across all properties — together with
    `source_language`, the BCP-47 tag of the original audio, and `runtime_seconds`,
    the reference runtime of the original master, which must be at least 1."
    PRD §3.1: "The property is stored with a `cut_count` of 0."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/create_title_returns_201_with_all_declared_fields
    """
    setup_canon(1)
    resp = api.create_title(
        create_title_payload(
            title_code="TTL-2146",
            source_language="en-US",
            runtime_seconds=7200,
            content_rating="TEEN",
        ),
        PC,
    )
    data = validate_success(resp, 201)
    assert_title(data)
    assert data["title_code"] == "TTL-2146"
    assert data["source_language"] == "en-US"
    assert data["runtime_seconds"] == 7200
    assert data["content_rating"] == "TEEN"
    assert data["cut_count"] == 0, "a freshly registered property holds no cuts"
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"


def test_read_root_cut_reports_its_computed_lineage_fields(api):
    """PRD §3.1: "A root cut is stored with `derived_from_cut_id` of null,
    `lineage_depth` of 0 and `conform_delta_seconds` of 0, and its creation
    increments the owning property's `cut_count` by 1."
    PRD §3.1: "Each cut is `OPEN` while its conform data may still change and
    `LOCKED` once it has been frozen."

    Design: Corner/entities/get_cut_by_id_returns_stored_row
    """
    ctx = setup_canon(3)
    data = validate_success(api.get_cut(ctx["c_id"], PC))
    assert_cut(data)
    assert data["cut_code"] == "THEATRICAL"
    assert data["loop_count"] == 400
    assert data["lineage_depth"] == 0
    assert data["conform_delta_seconds"] == 0
    assert data["derived_from_cut_id"] is None
    assert data["status"] == "OPEN"


def test_cut_listing_reports_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit` (the effective
    page size actually applied), `offset` (the effective starting index),
    `total_count` (the number of rows matching the filters before the page window is
    applied) and `has_more` (true when rows remain beyond the current window)."
    PRD §3.1: "Cuts may be listed and filtered by `title_id`, by
    `derived_from_cut_id` — the discovery channel for a cut's immediate children —
    and by `status`."

    Design: Corner/entities/list_cuts_paginates_with_total_count_and_has_more
    """
    ctx = setup_canon(3)
    derive_cut(ctx, "c_id", "c2_id", ctx["c_v1"], cut_code="AIRLINE",
               loop_count=360, runtime_seconds=6900)
    rows, meta = validate_paginated(
        api.list_cuts(PC, {"title_id": ctx["t_id"], "limit": 1, "offset": 0})
    )
    assert len(rows) == 1, f"limit=1 must return one row, got {len(rows)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "a second cut remains beyond the window"


def test_reading_an_unknown_order_returns_order_not_found(api):
    """PRD §2.5: "Path identifiers are resolved strictly left to right, and the first
    one that names no stored row terminates the request with that entity's own
    not-found code at HTTP 404 — `ERR_TITLE_NOT_FOUND`, `ERR_CUT_NOT_FOUND`,
    `ERR_CHARACTER_NOT_FOUND`, `ERR_PLATFORM_SPEC_NOT_FOUND`, `ERR_TALENT_NOT_FOUND`,
    `ERR_STUDIO_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ADAPTATION_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_MIX_JOB_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_RETAKE_ITEM_NOT_FOUND` or `ERR_PAYMENT_NOT_FOUND`
    respectively."

    Design: Corner/entities/get_missing_order_returns_order_not_found
    """
    setup_canon(1)
    resp = api.get_localization_order(UNKNOWN_UUID, PC)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)
    assert resp.status_code == 404


def test_platform_spec_missing_a_required_field_is_refused(api):
    """PRD §2.6 ladder step 8: "On every write endpoint: every required body field is
    present, every value matches its declared type, every enum value is a declared
    member of its enumeration, and every declared numeric range holds — the "at least
    1" fields, the "at least 0" fields and the fields confined to the closed interval
    0.0 through 1.0; otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/platform_spec_missing_required_field_returns_invalid_request
    """
    setup_canon(1)
    payload = create_platform_spec_payload(metadata_fields_required=["title_local"])
    payload.pop("qc_pass_threshold")
    resp = api.create_platform_spec(payload, PC)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert resp.status_code == 422


def test_voice_talent_optional_fields_take_their_declared_defaults(api):
    """PRD §3.2: "Two optional fields carry defaults: `union_status` defaults to
    `NON_UNION` and may instead be `UNION`, in which case every session that performer
    records attracts the union uplift line described in §3.7; and
    `max_daily_recorded_minutes` defaults to 300, the aggregate per-UTC-day minute cap
    across all of that performer's sessions."
    PRD §3.2: "A newly registered performer starts `ACTIVE` with `held_minutes` and
    `recorded_minutes` both at 0."

    Design: Corner/entities/voice_talent_defaults_applied_when_optional_fields_omitted
    """
    setup_canon(1)
    payload = create_voice_talent_payload(
        full_name="Anna Vogel", language_code="de-DE",
        base_rate_cents_per_hour=30000, licensed_territories=["DE"],
    )
    payload.pop("union_status")
    payload.pop("max_daily_recorded_minutes")
    data = validate_success(api.create_voice_talent(payload, CASTING), 201)
    assert_voice_talent(data)
    assert data["union_status"] == "NON_UNION"
    assert data["max_daily_recorded_minutes"] == 300
    assert data["status"] == "ACTIVE"
    assert data["held_minutes"] == 0
    assert data["recorded_minutes"] == 0


def test_deriving_a_shorter_cut_stamps_depth_and_a_negative_conform_delta(api):
    """PRD §3.1: "The child is stored with `derived_from_cut_id` pointing at the cut
    it was branched from, a `lineage_depth` of one more than the parent's, and a
    `conform_delta_seconds` equal to the child's `runtime_seconds` minus the parent's
    `runtime_seconds` — a signed figure that may be negative when the branch is
    shorter than its ancestor."
    PRD §3.1: "Deriving also increments the parent's `derived_cut_count` by 1,
    increments the parent cut's `version` by 1, and increments the property's
    `cut_count` by 1."

    Design: Corner/entities/derived_cut_computes_lineage_depth_and_conform_delta
    """
    ctx = setup_canon(3)
    child = validate_success(
        api.derive_cut(
            ctx["c_id"],
            {
                "cut_code": "AIRLINE",
                "loop_count": 360,
                "runtime_seconds": 6900,
                "expected_parent_cut_version": ctx["c_v1"],
            },
            PC,
        ),
        201,
    )
    assert_cut(child)
    assert child["lineage_depth"] == 1
    assert child["conform_delta_seconds"] == -300
    assert child["derived_from_cut_id"] == ctx["c_id"]
    assert child["status"] == "OPEN"

    parent = validate_success(api.get_cut(ctx["c_id"], PC))
    assert parent["derived_cut_count"] == 1
    title = validate_success(api.get_title(ctx["t_id"], PC))
    assert title["cut_count"] == 2


def test_new_order_carries_only_server_minted_lifecycle_fields(api):
    """PRD §3.3: "A new order lands in `DRAFT` with `committed_cents`,
    `released_cents`, `gross_accrued_cents` and `retake_cycles` all at 0,
    `metadata_locale_fields` an empty object, and `delivered_at` null."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/order_system_fields_are_server_minted_and_not_client_supplied
    """
    ctx = setup_draft_order(
        spec_overrides={"metadata_fields_required": ["title_local"]},
        priority_tier="RUSH",
    )
    data = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert data["status"] == "DRAFT"
    assert data["committed_cents"] == 0
    assert data["released_cents"] == 0
    assert data["gross_accrued_cents"] == 0
    assert data["retake_cycles"] == 0
    assert data["version"] == 1
    assert data["delivered_at"] is None


def test_undeclared_priority_tier_is_refused_as_an_invalid_request(api):
    """PRD §3.3: "A `priority_tier` may be supplied and defaults to `STANDARD`; the
    alternatives are `EXPEDITED` and `RUSH`, and the tier chosen here reaches into
    three separate calculations later — the fidelity tier weight, the rush surcharge
    on the invoice, and the ranking of the order's bookings in the studio waitlist."
    PRD §2.6 ladder step 8: "On every write endpoint: every required body field is
    present, every value matches its declared type, every enum value is a declared
    member of its enumeration, and every declared numeric range holds — the "at least
    1" fields, the "at least 0" fields and the fields confined to the closed interval
    0.0 through 1.0; otherwise `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/invalid_priority_tier_enum_returns_invalid_request
    """
    ctx = setup_locked_cut_and_spec(metadata_fields_required=["title_local"])
    resp = api.create_localization_order(
        {
            "cut_id": ctx["c_id"],
            "platform_spec_id": ctx["ps_id"],
            "target_language": "de-DE",
            "territory": "DE",
            "budget_cap_cents": 500000,
            "priority_tier": "OVERNIGHT",
        },
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert resp.status_code == 422
    rows, _ = validate_paginated(api.list_localization_orders(PC, {"cut_id": ctx["c_id"]}))
    assert rows == [], "a refused create must leave no order behind"


def test_casting_a_character_from_another_property_is_refused(api):
    """PRD §3.5: "The character's `title_id` must match the `title_id` of the cut
    behind the order, otherwise `ERR_CHARACTER_TITLE_MISMATCH`."

    Design: Corner/entities/character_from_another_title_rejected_on_casting
    """
    ctx = setup_canon(16)
    other_title = validate_success(
        api.create_title(
            create_title_payload(
                title_code="TTL-OTHER", source_language="en-US",
                runtime_seconds=5400, content_rating="GENERAL",
            ),
            PC,
        ),
        201,
    )
    other_character = validate_success(
        api.create_character(
            {
                "title_id": other_title["id"],
                "character_code": "STRANGER",
                "loop_count": 40,
                "screen_time_seconds": 300,
                "is_principal": False,
            },
            PC,
        ),
        201,
    )
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    resp = api.create_casting_assignment(
        {
            "order_id": ctx["o_id"],
            "character_id": other_character["id"],
            "talent_id": ctx["tal1_id"],
            "usage_variant": "BUYOUT",
            "agreed_rate_cents_per_hour": 36000,
            "expected_order_version": order["version"],
        },
        CASTING,
    )
    validate_error(resp, ApiErrorId.ERR_CHARACTER_TITLE_MISMATCH.value)
    assert resp.status_code == 422
    rows, _ = validate_paginated(api.list_casting_assignments(CASTING, {"order_id": ctx["o_id"]}))
    assert rows == []


def test_cut_children_are_discoverable_through_the_lineage_filter(api):
    """PRD §3.1: "Cuts may be listed and filtered by `title_id`, by
    `derived_from_cut_id` — the discovery channel for a cut's immediate children —
    and by `status`."
    PRD §3.1: "The child is stored with `derived_from_cut_id` pointing at the cut it
    was branched from, a `lineage_depth` of one more than the parent's, and a
    `conform_delta_seconds` equal to the child's `runtime_seconds` minus the parent's
    `runtime_seconds` — a signed figure that may be negative when the branch is
    shorter than its ancestor."

    Design: Corner/entities/self_referential_cut_chain_is_discoverable_by_parent_filter
    """
    ctx = setup_canon(3)
    child = validate_success(
        api.derive_cut(
            ctx["c_id"],
            {"cut_code": "AIRLINE", "loop_count": 360, "runtime_seconds": 6900,
             "expected_parent_cut_version": ctx["c_v1"]},
            PC,
        ),
        201,
    )
    grandchild = validate_success(
        api.derive_cut(
            child["id"],
            {"cut_code": "AIRLINE_SHORT", "loop_count": 300, "runtime_seconds": 6000,
             "expected_parent_cut_version": child["version"]},
            PC,
        ),
        201,
    )
    rows, _ = validate_paginated(api.list_cuts(PC, {"derived_from_cut_id": ctx["c_id"]}))
    assert len(rows) == 1 and rows[0]["id"] == child["id"], (
        "the root cut has exactly one immediate child"
    )
    assert grandchild["lineage_depth"] == 2
    assert grandchild["conform_delta_seconds"] == -900
    assert validate_success(api.get_cut(child["id"], PC))["derived_cut_count"] == 1
    assert validate_success(api.get_cut(ctx["c_id"], PC))["derived_cut_count"] == 1


def test_locking_an_already_locked_cut_is_refused(api):
    """PRD §3.1: "Attempting to lock a cut that is already `LOCKED`, or one whose
    lineage parent is still `OPEN`, is refused with `ERR_INVALID_STATE`."
    PRD §3.1: "Locking is a `ProductionCoordinator` action that advances
    `OPEN → LOCKED` and increments the cut's `version` by 1."

    Design: Corner/state_machines/locking_an_already_locked_cut_returns_invalid_state
    """
    ctx = setup_canon(4)
    resp = api.lock_cut(ctx["c_id"], PC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409
    cut = validate_success(api.get_cut(ctx["c_id"], PC))
    assert cut["status"] == "LOCKED"
    assert cut["version"] == 2, (
        f"create then lock is exactly two writes, got version {cut['version']}"
    )


def test_pagination_limit_above_the_maximum_is_refused(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, has a minimum of 1 and a
    maximum of 100."
    PRD §2.3: "A `limit` outside the inclusive range 1 to 100, a non-integer `limit`,
    a negative `offset` or a non-integer `offset` is refused with
    `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/validations/pagination_limit_above_maximum_returns_invalid_pagination
    """
    ctx = setup_canon(3)
    resp = api.list_cuts(PC, {"title_id": ctx["t_id"], "limit": 101, "offset": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)
    assert resp.status_code == 422


def test_order_against_an_open_cut_is_refused_until_the_cut_is_locked(api):
    """PRD §3.3: "The cut named by `cut_id` must be `LOCKED`; a cut still `OPEN` earns
    `ERR_CUT_NOT_LOCKED`."
    PRD §3.1: "Locking matters because a localization order may only be raised
    against a `LOCKED` cut, which makes locking the gate that freezes conform data for
    every downstream order."

    Design: Corner/validations/order_on_an_open_cut_returns_cut_not_locked
    """
    ctx = setup_canon(3)
    create_platform_spec(ctx, metadata_fields_required=["title_local"])
    body = {
        "cut_id": ctx["c_id"],
        "platform_spec_id": ctx["ps_id"],
        "target_language": "de-DE",
        "territory": "DE",
        "budget_cap_cents": 500000,
        "priority_tier": "STANDARD",
    }
    resp = api.create_localization_order(body, PC)
    validate_error(resp, ApiErrorId.ERR_CUT_NOT_LOCKED.value)
    assert resp.status_code == 409

    validate_success(api.lock_cut(ctx["c_id"], PC))
    assert validate_success(api.get_cut(ctx["c_id"], PC))["status"] == "LOCKED"
    order = validate_success(api.create_localization_order(body, PC), 201)
    assert order["status"] == "DRAFT"


def test_deriving_below_a_depth_three_parent_is_refused(api):
    """PRD §3.1: "Lineage may not run arbitrarily deep: a derive whose parent already
    sits at a `lineage_depth` of 3 or more is refused with
    `ERR_LINEAGE_DEPTH_EXCEEDED`, so the deepest cut the catalogue will ever hold has
    a `lineage_depth` of 3."

    Design: Corner/validations/deriving_beyond_lineage_depth_three_is_rejected
    """
    ctx = setup_canon(3)
    parent_id, parent_version = ctx["c_id"], ctx["c_v1"]
    for code, loops, runtime in (("D1", 390, 7100), ("D2", 380, 7000), ("D3", 370, 6900)):
        child = validate_success(
            api.derive_cut(
                parent_id,
                {"cut_code": code, "loop_count": loops, "runtime_seconds": runtime,
                 "expected_parent_cut_version": parent_version},
                PC,
            ),
            201,
        )
        parent_id, parent_version = child["id"], child["version"]

    assert validate_success(api.get_cut(parent_id, PC))["lineage_depth"] == 3
    resp = api.derive_cut(
        parent_id,
        {"cut_code": "D4", "loop_count": 360, "runtime_seconds": 6800,
         "expected_parent_cut_version": parent_version},
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_LINEAGE_DEPTH_EXCEEDED.value)
    assert resp.status_code == 422
    assert validate_success(api.get_cut(parent_id, PC))["derived_cut_count"] == 0
    rows, _ = validate_paginated(api.list_cuts(PC, {"derived_from_cut_id": parent_id}))
    assert rows == []


def test_order_target_language_equal_to_the_source_language_is_refused(api):
    """PRD §3.3: "And the `target_language` must differ from the `source_language` of
    the property reached through that cut — the service will not accept an order to
    dub a property into the language it was shot in, and refuses with
    `ERR_SAME_LANGUAGE`."

    Design: Corner/validations/order_target_language_equal_to_source_language_is_rejected
    """
    ctx = setup_locked_cut_and_spec(metadata_fields_required=["title_local"])
    resp = api.create_localization_order(
        {
            "cut_id": ctx["c_id"],
            "platform_spec_id": ctx["ps_id"],
            "target_language": "en-US",
            "territory": "DE",
            "budget_cap_cents": 500000,
            "priority_tier": "STANDARD",
        },
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_SAME_LANGUAGE.value)
    assert resp.status_code == 422


def test_request_without_auth_headers_is_refused_before_payload_validation(api):
    """PRD §2.1: "If either header is absent or empty, the request is refused with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.6 ladder step 1: "Both `X-User-Role` and `X-User-ID` are present and
    non-empty on every endpoint without exception; otherwise `ERR_UNAUTHENTICATED`
    (401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    setup_canon(1)
    resp = api.create_title(
        {"title_code": "TTL-2146", "source_language": "en-US",
         "runtime_seconds": "not-a-number"},
        {"Content-Type": "application/json"},
    )
    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert resp.status_code == 401
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value


def test_every_collection_answers_with_its_own_not_found_code(api):
    """PRD §2.5: "Path identifiers are resolved strictly left to right, and the first
    one that names no stored row terminates the request with that entity's own
    not-found code at HTTP 404 — `ERR_TITLE_NOT_FOUND`, `ERR_CUT_NOT_FOUND`,
    `ERR_CHARACTER_NOT_FOUND`, `ERR_PLATFORM_SPEC_NOT_FOUND`, `ERR_TALENT_NOT_FOUND`,
    `ERR_STUDIO_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ADAPTATION_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_MIX_JOB_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_RETAKE_ITEM_NOT_FOUND` or `ERR_PAYMENT_NOT_FOUND`
    respectively."

    Design: Corner/errors/unknown_path_id_returns_entity_specific_not_found
    """
    setup_canon(1)
    probes = [
        (api.get_title, UNKNOWN_UUIDS["title"], PC, ApiErrorId.ERR_TITLE_NOT_FOUND),
        (api.get_cut, UNKNOWN_UUIDS["cut"], PC, ApiErrorId.ERR_CUT_NOT_FOUND),
        (api.get_character, UNKNOWN_UUIDS["character"], PC,
         ApiErrorId.ERR_CHARACTER_NOT_FOUND),
        (api.get_platform_spec, UNKNOWN_UUIDS["platform_spec"], PC,
         ApiErrorId.ERR_PLATFORM_SPEC_NOT_FOUND),
        (api.get_voice_talent, UNKNOWN_UUIDS["talent"], CASTING,
         ApiErrorId.ERR_TALENT_NOT_FOUND),
        (api.get_script_adaptation, UNKNOWN_UUIDS["adaptation"],
         make_adaptor_headers("adaptor-1"), ApiErrorId.ERR_ADAPTATION_NOT_FOUND),
        (api.get_casting_assignment, UNKNOWN_UUIDS["assignment"], CASTING,
         ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        (api.get_recording_session, UNKNOWN_UUIDS["session"], PC,
         ApiErrorId.ERR_SESSION_NOT_FOUND),
        (api.get_mix_job, UNKNOWN_UUIDS["mix_job"], MIXER,
         ApiErrorId.ERR_MIX_JOB_NOT_FOUND),
        (api.get_quality_review, UNKNOWN_UUIDS["review"],
         make_native_reviewer_headers("reviewer-1"), ApiErrorId.ERR_REVIEW_NOT_FOUND),
        (api.get_retake_item, UNKNOWN_UUIDS["retake_item"],
         make_native_reviewer_headers("reviewer-1"),
         ApiErrorId.ERR_RETAKE_ITEM_NOT_FOUND),
        (api.get_talent_payment, UNKNOWN_UUIDS["payment"], ADMIN,
         ApiErrorId.ERR_PAYMENT_NOT_FOUND),
    ]
    for method, unknown_id, headers, expected in probes:
        resp = method(unknown_id, headers)
        validate_error(resp, expected.value)
        assert resp.status_code == 404, (
            f"{expected.value} must answer HTTP 404, got {resp.status_code}"
        )


def test_logical_clock_starts_at_its_declared_epoch_and_moves_on_command(api):
    """PRD §2.8: "Before any client touches it, the clock reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."
    PRD §2.8: "A `PlatformAdmin` may move the clock by supplying a `to_iso8601`
    instant, and any role may read it."

    Design: Corner/endpoints/logical_clock_defaults_to_the_declared_epoch
    """
    first = validate_success(api.get_clock(PC))
    assert_same_instant(first["current_utc"], "2026-08-01T00:00:00Z", "clock epoch")

    validate_success(api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN))
    second = validate_success(api.get_clock(PC))
    assert_same_instant(second["current_utc"], "2026-09-01T00:00:00Z", "clock after move")


def test_stale_parent_cut_version_blocks_a_second_derive(api):
    """PRD §2.7: "If that value does not equal the parent cut's current `version`, the
    derive is rejected with `ERR_STALE_CUT_VERSION` at HTTP 412 and no child cut is
    created."
    PRD §3.1: "Deriving also increments the parent's `derived_cut_count` by 1,
    increments the parent cut's `version` by 1, and increments the property's
    `cut_count` by 1."

    Design: Corner/cross_cutting_layers/stale_parent_cut_version_on_derive_returns_412
    """
    ctx = setup_canon(3)
    validate_success(
        api.derive_cut(
            ctx["c_id"],
            {"cut_code": "AIRLINE", "loop_count": 360, "runtime_seconds": 6900,
             "expected_parent_cut_version": ctx["c_v1"]},
            PC,
        ),
        201,
    )
    stale_body = {
        "cut_code": "BROADCAST", "loop_count": 350, "runtime_seconds": 6800,
        "expected_parent_cut_version": ctx["c_v1"],
    }
    resp = api.derive_cut(ctx["c_id"], stale_body, PC)
    validate_error(resp, ApiErrorId.ERR_STALE_CUT_VERSION.value)
    assert resp.status_code == 412

    fresh = validate_success(api.get_cut(ctx["c_id"], PC))
    retry_body = dict(stale_body, expected_parent_cut_version=fresh["version"])
    third = validate_success(api.derive_cut(ctx["c_id"], retry_body, PC), 201)
    assert third["lineage_depth"] == 1
    assert third["conform_delta_seconds"] == -400
    assert validate_success(api.get_cut(ctx["c_id"], PC))["derived_cut_count"] == 2
    rows, _ = validate_paginated(api.list_cuts(PC, {"derived_from_cut_id": ctx["c_id"]}))
    assert len(rows) == 2
