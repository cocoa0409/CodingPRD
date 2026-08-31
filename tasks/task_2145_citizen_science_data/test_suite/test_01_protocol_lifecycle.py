"""Survey protocol drafting, activation and the self-referential version chain."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_bare_uuid,
    assert_iso8601_millis,
    assert_protocol,
    build_world,
    certify,
    complete_training,
    create_active_protocol,
    create_campaign,
    create_protocol_payload,
    enroll_certification,
    read_certification,
    read_protocol,
    read_volunteer,
    set_clock,
    STAGE_ACTORS,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-05T09:00:00Z"


def test_protocol_created_in_draft_with_derived_version_number(api):
    """PRD 3.1: "A new protocol lands in `DRAFT` with `activated_at` still null."
    PRD 3.1: "The `version_number` is derived rather than supplied: a
    first-generation protocol, created without a `supersedes_protocol_id`, gets
    `version_number` 1, while a protocol created with a `supersedes_protocol_id`
    pointing at an existing row gets that row's `version_number` plus one."
    PRD 2.4: "Every persisted record carries a server-minted `id`, a UUID with no
    type prefix of any kind."

    Design: Corner/entities/protocol_create_returns_declared_defaults_and_system_fields
    """
    validate_paginated(api.list_protocols(ADMIN, {"limit": 10, "offset": 0}))

    payload = create_protocol_payload(
        code="CORNER-1", title="Corner Protocol", required_certification_level="BASIC",
        min_photo_count=2, max_submission_lag_hours=48,
        required_equipment_type="GPS_LOGGER", certification_valid_days=90)
    created = validate_success(api.create_protocol(payload, ADMIN), 201)

    assert_protocol(created)
    assert created["status"] == "DRAFT", f"Expected DRAFT, got {created['status']}"
    assert created["version_number"] == 1, (
        f"A first-generation protocol gets version_number 1, got "
        f"{created['version_number']}")
    assert created["version"] == 1, (
        f"version starts at 1 on creation, got {created['version']}")
    assert created["supersedes_protocol_id"] is None
    assert created["activated_at"] is None, "A new protocol has activated_at still null"
    assert created["min_photo_count"] == 2
    assert_bare_uuid(created["id"])


def test_protocol_and_site_optional_inputs_fall_back_to_declared_defaults(api):
    """PRD 3.1: "`required_equipment_type` names the instrument class an
    observation must be backed by and takes the values `NONE`, `ACOUSTIC_RECORDER`,
    `GPS_LOGGER`, or `SPOTTING_SCOPE`, defaulting to `NONE` when omitted.
    `certification_valid_days` sets how long a granted credential under this
    protocol stays live and defaults to 365 days when omitted; it must be greater
    than zero."
    PRD 3.3: "an optional `priority_weight` between 0.50 and 2.00 at two decimal
    places, defaulting to 1.0"
    PRD 3.3: "A newly added site starts with `accepted_observation_count` at 0,
    `coverage_ratio` at 0.0, and `coverage_status` at `GAP`."

    Design: Corner/entities/protocol_defaults_applied_when_optional_inputs_omitted
    """
    protocol = validate_success(api.create_protocol({
        "code": "DEF-1", "title": "Defaults Protocol",
        "required_certification_level": "BASIC", "min_photo_count": 0,
        "max_submission_lag_hours": 24}, ADMIN), 201)
    assert protocol["required_equipment_type"] == "NONE"
    assert protocol["certification_valid_days"] == 365

    campaign = create_campaign(
        protocol["id"], name="Defaults Campaign", season_start_date="2026-08-01",
        season_end_date="2026-08-31", target_observations_per_site=2)

    site = validate_success(api.create_site(campaign["id"], {
        "site_code": "S-DEF", "latitude": 40.0, "longitude": -75.0,
        "habitat_type": "URBAN"}, ADMIN), 201)

    assert float(site["priority_weight"]) == 1.0, (
        f"priority_weight defaults to 1.0, got {site['priority_weight']}")
    assert float(site["coverage_ratio"]) == 0.00
    assert site["coverage_status"] == "GAP"
    assert read_campaign_site_count(api, campaign["id"]) == 1


def read_campaign_site_count(api, campaign_id):
    return validate_success(api.get_campaign(campaign_id, ADMIN))["site_count"]


def test_protocol_create_missing_required_field_returns_invalid_request(api):
    """PRD 2.7: "**Priority 6 — payload shape (all creating and acting operations
    that take a body).** Every required field must be present, every value must
    match its declared type, every enum value must be a declared member of its
    enumeration, and every numeric value must fall inside its declared range;
    otherwise `ERR_INVALID_REQUEST` (422)."
    PRD 3.1: "A `ProgramAdmin` drafts one by supplying a `code`, a descriptive
    `title`, the `required_certification_level` a volunteer must hold before
    submitting under it (`BASIC`, `ADVANCED`, or `EXPERT`), a `min_photo_count` of
    at least zero, and a `max_submission_lag_hours` greater than zero."

    Design: Corner/entities/protocol_create_missing_required_field_returns_invalid_request
    """
    response = api.create_protocol({
        "code": "MISS-1", "title": "Missing Field Protocol",
        "required_certification_level": "BASIC",
        "max_submission_lag_hours": 48}, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    _rows, meta = validate_paginated(api.list_protocols(ADMIN, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, "A rejected draft must not be persisted"


def test_protocol_version_chain_is_reverse_reachable_by_filter(api):
    """PRD 3.1: "The `version_number` is derived rather than supplied: a
    first-generation protocol, created without a `supersedes_protocol_id`, gets
    `version_number` 1, while a protocol created with a `supersedes_protocol_id`
    pointing at an existing row gets that row's `version_number` plus one."
    PRD 2.3: "Protocols may be filtered by `status`, by `code`, and by
    `supersedes_protocol_id`."

    Design: Corner/entities/protocol_self_referential_version_chain_is_reverse_reachable
    """
    first = create_active_protocol(code="CHAIN-1", title="Chain Protocol v1",
                                   min_photo_count=1, max_submission_lag_hours=48)

    successor = validate_success(api.create_protocol(create_protocol_payload(
        code="CHAIN-2", title="Chain Protocol v2",
        required_certification_level="ADVANCED", min_photo_count=2,
        max_submission_lag_hours=48, supersedes_protocol_id=first["id"]), ADMIN), 201)

    assert successor["version_number"] == 2, (
        f"Successor gets the predecessor's version_number plus one, got "
        f"{successor['version_number']}")
    assert successor["supersedes_protocol_id"] == first["id"]
    assert successor["status"] == "DRAFT"
    assert read_protocol(first["id"])["status"] == "ACTIVE"

    rows, meta = validate_paginated(api.list_protocols(
        ADMIN, {"supersedes_protocol_id": first["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, f"Expected 1 successor row, got {meta['total_count']}"
    assert rows[0]["id"] == successor["id"]


def test_activating_a_successor_retires_predecessor_and_revokes_its_certifications(api):
    """PRD 3.1: "In the first link, when the activating protocol carries a
    `supersedes_protocol_id` and that predecessor is currently `ACTIVE`, the
    predecessor transitions `ACTIVE → RETIRED`."
    PRD 3.1: "In the second link, caused by the first, every certification whose
    `protocol_id` names the newly retired protocol and whose `status` is
    `ENROLLED`, `TRAINED`, `CERTIFIED`, or `SUSPENDED` transitions to `REVOKED` —
    that is, `ENROLLED → REVOKED`, `TRAINED → REVOKED`, `CERTIFIED → REVOKED`, and
    `SUSPENDED → REVOKED` all apply, and `REVOKED` is a terminal state from which
    nothing returns."
    PRD 3.1: "In the third link, caused by the second, every volunteer who lost
    their last `CERTIFIED` certification in the second link, and whose own `status`
    was `ACTIVE`, transitions `ACTIVE → PENDING`; a volunteer who still holds at
    least one `CERTIFIED` certification elsewhere is untouched."

    Design: Corner/state_machines/protocol_supersede_cascade_revokes_certification_and_demotes_volunteer
    """
    world = build_world(stage=STAGE_ACTORS, clock=CLOCK)
    certification = certify(world["v1"], world["p1"], world["et"], level="BASIC")
    assert certification["status"] == "CERTIFIED"
    assert read_volunteer(world["v1"])["status"] == "ACTIVE"

    successor = validate_success(api.create_protocol(create_protocol_payload(
        code="BBS-2027", title="Breeding Bird Survey 2027",
        supersedes_protocol_id=world["p1"]), ADMIN), 201)

    activated = validate_success(api.activate_protocol(successor["id"], ADMIN))

    assert activated["status"] == "ACTIVE"
    assert read_protocol(world["p1"])["status"] == "RETIRED"
    assert read_certification(certification["id"])["status"] == "REVOKED"
    assert read_volunteer(world["v1"])["status"] == "PENDING"


def test_activating_an_already_active_protocol_is_refused(api):
    """PRD 3.1: "A `DRAFT` protocol moves `DRAFT → ACTIVE` only when it is
    genuinely still in `DRAFT` — an activation aimed at a protocol already `ACTIVE`
    or already `RETIRED` is refused with `ERR_PROTOCOL_NOT_DRAFT` — and only when no
    other protocol carrying the same `code` is currently `ACTIVE`, the sole exception
    being the very row this protocol names as its `supersedes_protocol_id`."
    PRD 3.1: "Activation stamps `activated_at` from the logical clock and advances
    the protocol's `version` by one."

    Design: Corner/errors/protocol_activate_twice_rejected
    """
    set_clock(CLOCK)
    protocol = create_active_protocol()

    response = api.activate_protocol(protocol["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_PROTOCOL_NOT_DRAFT.value, 409)

    stored = read_protocol(protocol["id"])
    assert stored["status"] == "ACTIVE"
    assert stored["activated_at"] == "2026-08-05T09:00:00.000Z", (
        f"activated_at is stamped from the logical clock, got {stored['activated_at']}")
    assert_iso8601_millis(stored["activated_at"], "activated_at")


def test_granting_a_certification_on_a_draft_protocol_is_refused(api):
    """PRD 3.2: "A `TRAINED` certification moves `TRAINED → CERTIFIED` provided the
    underlying protocol is still `ACTIVE`; if the protocol has drifted out of
    `ACTIVE`, the grant is refused with `ERR_PROTOCOL_NOT_ACTIVE`."

    Design: Corner/errors/certification_grant_on_draft_protocol_rejected
    """
    set_clock(CLOCK)
    protocol = validate_success(api.create_protocol(create_protocol_payload(
        code="DRAFT-ONLY", title="Never Activated Protocol"), ADMIN), 201)
    volunteer = validate_success(api.create_volunteer({
        "full_name": "Vera Finch", "email": "vera@example.org",
        "home_region_code": "NE-01"}, ADMIN), 201)
    trainer = validate_success(api.create_expert({
        "full_name": "Tess Trainer", "specialty_taxon": "AVES",
        "verification_weight": 1.00}, ADMIN), 201)

    certification = enroll_certification(volunteer["id"], protocol["id"],
                                         trainer["id"], level="BASIC")
    complete_training(certification["id"], trainer["id"])

    response = api.grant_certification(certification["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_PROTOCOL_NOT_ACTIVE.value, 409)

    stored = read_certification(certification["id"])
    assert stored["status"] == "TRAINED"
    assert stored["granted_at"] is None
    assert read_volunteer(volunteer["id"])["status"] == "PENDING"


def test_reusing_a_protocol_code_is_a_duplicate_key_collision(api):
    """PRD 3.1: "Its `code` is unique across every protocol row in the system
    regardless of that row's status, so re-using a code — even one belonging to a
    long-retired protocol — is a duplicate-key collision."
    PRD 2.7: "Protocol `code`, volunteer `email`, equipment `asset_tag`,
    publication `doi`, and partner `org_name` are each unique across all rows of
    their type; `site_code` is unique within its owning campaign; `file_hash` is
    unique within its owning observation. A collision yields `ERR_DUPLICATE_KEY`
    (409)."

    Design: Corner/validations/duplicate_protocol_code_rejected
    """
    first = validate_success(api.create_protocol(create_protocol_payload(), ADMIN), 201)

    response = api.create_protocol(create_protocol_payload(
        code="BBS-2026", title="Duplicate Code Protocol",
        required_certification_level="EXPERT", min_photo_count=3,
        max_submission_lag_hours=12), ADMIN)
    validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value, 409)

    _rows, meta = validate_paginated(api.list_protocols(
        ADMIN, {"code": "BBS-2026", "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, (
        f"Only the first protocol carrying the code may exist, got {meta['total_count']}")
    assert read_protocol(first["id"])["status"] == "DRAFT"
