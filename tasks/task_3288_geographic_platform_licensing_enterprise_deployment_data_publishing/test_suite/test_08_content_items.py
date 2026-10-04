"""Content items: sharing machine, OCC on shares, publish gates, moderation
cascade, retraction, and RBAC."""
from test_helpers import (
    ApiErrorId,
    get_grant,
    get_item,
    get_org,
    get_org_version,
    get_pool,
    get_success_data,
    list_batches,
    make_named_user_headers,
    setup_base_chain,
    setup_with_user,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_license_grant_payload, create_license_product_payload
from test_helpers.fixtures import (
    accept_user,
    activate_grant,
    activate_org,
    create_draft_item,
    create_published_item,
    invite_user,
    publish_item,
    set_clock,
    setup_grant,
    setup_org,
    setup_product,
    share_item,
)
from test_helpers.test_users import TEST_USERS

BA_HEADERS = TEST_USERS["billing_admin_headers"]
CM_HEADERS = TEST_USERS["content_moderator_headers"]
LA_HEADERS = TEST_USERS["license_admin_headers"]
PA_HEADERS = TEST_USERS["platform_admin_headers"]


def _share(api, item_id, target, version, owner_id):
    return api.share_content_item(
        item_id,
        {"target_sharing_level": target, "expected_content_item_version": version},
        make_named_user_headers(owner_id),
    )


def test_sharing_cycle_private_org_public_org_private(api):
    """PRD section 3.9: "Sharing level — carried on the item's
    `sharing_level` field — is a dimension independent of `status`, cycling
    one step at a time along `PRIVATE` ↔ `ORGANIZATION` ↔ `PUBLIC`".
    PRD section 3.9: "Moving down — `PUBLIC` to `ORGANIZATION`, or
    `ORGANIZATION` to `PRIVATE` — follows the same single-step rule."

    Design: Difficulty/non_linear_state_machine/sharing_level_cyclic_single_step
    """
    base = setup_with_user()
    owner = base["user"]["id"]
    item = create_published_item(base["org"]["id"], owner)
    v = item["version"]

    d = get_success_data(_share(api, item["id"], "ORGANIZATION", v, owner))
    assert d["sharing_level"] == "ORGANIZATION"
    v = d["version"]
    d = get_success_data(_share(api, item["id"], "PUBLIC", v, owner))
    assert d["sharing_level"] == "PUBLIC"
    v = d["version"]
    d = get_success_data(_share(api, item["id"], "ORGANIZATION", v, owner))
    v = d["version"]
    d = get_success_data(_share(api, item["id"], "PRIVATE", v, owner))
    assert d["sharing_level"] == "PRIVATE"
    assert d["version"] == item["version"] + 4


def test_sharing_public_to_private_jump_rejected(api):
    """PRD section 3.9: "Any request whose current and target levels are not
    adjacent steps along this chain is rejected with
    `ERR_INVALID_SHARING_TRANSITION`; a user-initiated jump straight from
    `PUBLIC` to `PRIVATE` is invalid."
    PRD section 3.9: "Every user-initiated share increments the item's
    `version` by 1 — which is what the mandatory
    `expected_content_item_version` field on sharing requests is checked
    against, per §2.9."

    Design: Difficulty/non_linear_state_machine/sharing_level_cyclic_single_step
    """
    base = setup_with_user()
    owner = base["user"]["id"]
    item = create_published_item(base["org"]["id"], owner)
    v = item["version"]
    d = get_success_data(_share(api, item["id"], "ORGANIZATION", v, owner))
    v = d["version"]
    d = get_success_data(_share(api, item["id"], "PUBLIC", v, owner))
    v = d["version"]

    resp = _share(api, item["id"], "PRIVATE", v, owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_SHARING_TRANSITION)
    # failed share does not bump the version
    d = get_success_data(_share(api, item["id"], "ORGANIZATION", v, owner))
    assert d["sharing_level"] == "ORGANIZATION"


def test_share_with_stale_item_version_returns_412(api):
    """PRD section 2.9: "Every content sharing transition must carry
    `expected_content_item_version`, holding the client's last observed
    `version` of the ContentItem. A mismatch — whether the item's version
    advanced through a prior share or because a moderator flag forced the item
    private — is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_item_version_on_share_returns_412
    """
    base = setup_with_user()
    owner = base["user"]["id"]
    item = create_published_item(base["org"]["id"], owner)
    v0 = item["version"]
    get_success_data(_share(api, item["id"], "ORGANIZATION", v0, owner))
    resp = _share(api, item["id"], "PUBLIC", v0, owner)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_item(item["id"])["sharing_level"] == "ORGANIZATION"


def test_retracted_item_rejects_share_and_flag(api):
    """PRD section 3.9: "every sharing transition additionally requires the
    item to be `PUBLISHED` (else `ERR_ITEM_NOT_PUBLISHED`)".
    PRD section 3.9: "Flagging (action `FLAG`) moves a `PUBLISHED` item to
    `FLAGGED` (the item must be `PUBLISHED`, else `ERR_ITEM_NOT_PUBLISHED`)".
    PRD section 3.9: "Retraction moves a `PUBLISHED` item to the terminal
    state `RETRACTED`."

    Design: Corner/state_machines/retracted_item_rejects_share_and_flag
    """
    base = setup_with_user()
    owner = base["user"]["id"]
    item = create_published_item(base["org"]["id"], owner)
    item = get_success_data(api.transition_content_item(
        item["id"], {"target_status": "RETRACTED"}, make_named_user_headers(owner)))

    resp = _share(api, item["id"], "ORGANIZATION", item["version"], owner)
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_PUBLISHED)
    resp = api.moderate_content_item(item["id"], {"action": "FLAG"}, CM_HEADERS)
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_PUBLISHED)


def test_publish_synthesizes_pending_storage_batch(api):
    """PRD section 3.9: "A storage CreditBatch is synthesized in `PENDING`
    status: `service_kind` `STORAGE`, `api_key_id` null, `idempotency_key` the
    string `storage:` concatenated with the item's id, and `requested_units`
    equal to the item's `storage_bytes` divided by 104857600 (100 MiB per
    unit) rounded up to a whole unit".

    Design: Corner/endpoints/publish_synthesizes_storage_batch_pending
    """
    base = setup_with_user()
    owner = base["user"]["id"]
    item = create_draft_item(base["org"]["id"], owner, title="Big", item_kind="TILE_LAYER",
                             storage_bytes=209715201)
    publish_item(item["id"], owner)
    batches = list_batches(base["org"]["id"], service_kind="STORAGE")
    assert len(batches) == 1
    b = batches[0]
    assert b["requested_units"] == 3  # ceil(209715201 / 104857600) = 3
    assert b["provisional_credits"] == 3
    assert b["status"] == "PENDING"
    assert b["api_key_id"] is None
    assert b["idempotency_key"] == f"storage:{item['id']}"
    assert get_pool(base["org"]["id"])["reserved_credits"] == 3


def test_storage_unit_ceiling_boundaries(api):
    """PRD section 3.9: "zero bytes yields a zero-unit batch, still created,
    with `provisional_credits` of 0; one byte yields one unit; exactly
    104857600 bytes yields one unit; 104857601 bytes yields two units."

    Design: Difficulty/boundary_precision_check/storage_unit_ceiling_boundaries
    """
    base = setup_with_user()
    owner = base["user"]["id"]
    cases = [(0, 0), (104857600, 1), (104857601, 2)]
    for size, expected_units in cases:
        item = create_draft_item(base["org"]["id"], owner, title=f"s{size}",
                                 item_kind="FEATURE_LAYER", storage_bytes=size)
        publish_item(item["id"], owner)
    batches = sorted(
        list_batches(base["org"]["id"], service_kind="STORAGE"),
        key=lambda b: b["requested_units"],
    )
    assert [b["requested_units"] for b in batches] == [0, 1, 2]
    assert [b["provisional_credits"] for b in batches] == [0, 1, 2]
    assert get_pool(base["org"]["id"])["reserved_credits"] == 3


def test_storage_unit_one_byte_yields_one_unit(api):
    """PRD section 3.9: "zero bytes yields a zero-unit batch, still created,
    with `provisional_credits` of 0; one byte yields one unit; exactly
    104857600 bytes yields one unit; 104857601 bytes yields two units."

    Design: Difficulty/boundary_precision_check/storage_unit_ceiling_boundaries
    """
    base = setup_with_user()
    owner = base["user"]["id"]
    item = create_draft_item(base["org"]["id"], owner, title="one-byte",
                             item_kind="FEATURE_LAYER", storage_bytes=1)
    publish_item(item["id"], owner)
    batches = list_batches(base["org"]["id"], service_kind="STORAGE")
    assert len(batches) == 1
    assert batches[0]["requested_units"] == 1
    assert batches[0]["provisional_credits"] == 1


def test_basemap_public_share_requires_advanced_grant(api):
    """PRD section 3.9: "moving from `ORGANIZATION` to `PUBLIC` requires the
    owner's `named_user_level` to be one of `CREATOR`, `PROFESSIONAL`, or
    `PROFESSIONAL_PLUS` (else `ERR_INSUFFICIENT_USER_LEVEL`, HTTP 403) and,
    when the item's `contains_licensed_basemap` is true, the organization to
    hold an `ACTIVE` grant whose product's `edition` is `ADVANCED` (else
    `ERR_BASEMAP_PUBLIC_REQUIRES_ADVANCED`, HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/basemap_public_share_gated_by_advanced_grant
    """
    # Org whose only grant is STANDARD edition.
    set_clock()
    org = setup_org()
    get_success_data(api.create_credit_pool(
        {"organization_id": org["id"], "capacity_credits": 100000}, BA_HEADERS))
    product = setup_product(
        product_code="DESKTOP-STD-11", license_kind="NAMED_USER", edition="STANDARD",
        major_version=11, base_seat_count=50, supports_offline=True,
        allows_derivative_works=True)
    grant = setup_grant(org["id"], product["id"], seats_allocated=10)
    activate_org(org["id"])
    activate_grant(grant["id"], org["id"])
    user = invite_user(org["id"], grant["id"])
    user = accept_user(user["id"])
    item = create_draft_item(org["id"], user["id"], title="Basemap Mash", item_kind="WEB_MAP",
                             storage_bytes=0, contains_licensed_basemap=True)
    item = publish_item(item["id"], user["id"])
    v = item["version"]
    d = get_success_data(_share(api, item["id"], "ORGANIZATION", v, user["id"]))
    resp = _share(api, item["id"], "PUBLIC", d["version"], user["id"])
    validate_error(resp, ApiErrorId.ERR_BASEMAP_PUBLIC_REQUIRES_ADVANCED)


def test_basemap_public_share_unblocked_by_advanced_grant(api):
    """PRD section 3.9: "when the item's `contains_licensed_basemap` is true,
    the organization to hold an `ACTIVE` grant whose product's `edition` is
    `ADVANCED` (else `ERR_BASEMAP_PUBLIC_REQUIRES_ADVANCED`, HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/basemap_public_share_gated_by_advanced_grant
    """
    set_clock()
    org = setup_org()
    get_success_data(api.create_credit_pool(
        {"organization_id": org["id"], "capacity_credits": 100000}, BA_HEADERS))
    product = setup_product(
        product_code="DESKTOP-STD-11", license_kind="NAMED_USER", edition="STANDARD",
        major_version=11, base_seat_count=50, supports_offline=True,
        allows_derivative_works=True)
    grant = setup_grant(org["id"], product["id"], seats_allocated=10)
    activate_org(org["id"])
    activate_grant(grant["id"], org["id"])
    user = invite_user(org["id"], grant["id"])
    user = accept_user(user["id"])
    item = create_draft_item(org["id"], user["id"], title="Basemap Mash", item_kind="WEB_MAP",
                             storage_bytes=0, contains_licensed_basemap=True)
    item = publish_item(item["id"], user["id"])
    d = get_success_data(_share(api, item["id"], "ORGANIZATION", item["version"], user["id"]))
    validate_error(_share(api, item["id"], "PUBLIC", d["version"], user["id"]),
                   ApiErrorId.ERR_BASEMAP_PUBLIC_REQUIRES_ADVANCED)

    # Add an ACTIVE ADVANCED-edition grant and the identical share succeeds.
    adv = setup_product(product_code="DESKTOP-ADV-11", license_kind="NAMED_USER",
                        edition="ADVANCED", major_version=11, base_seat_count=50,
                        supports_offline=True, allows_derivative_works=True)
    adv_grant = setup_grant(org["id"], adv["id"], seats_allocated=10)
    activate_grant(adv_grant["id"], org["id"])
    d2 = get_success_data(_share(api, item["id"], "PUBLIC", d["version"], user["id"]))
    assert d2["sharing_level"] == "PUBLIC"


def test_insufficient_user_level_blocks_public_share(api):
    """PRD section 3.9: "moving from `ORGANIZATION` to `PUBLIC` requires the
    owner's `named_user_level` to be one of `CREATOR`, `PROFESSIONAL`, or
    `PROFESSIONAL_PLUS` (else `ERR_INSUFFICIENT_USER_LEVEL`, HTTP 403)".

    Design: Corner/validations/insufficient_user_level_blocks_public_share
    """
    base = setup_with_user()  # base grant is ADVANCED, so only the level gate can fail
    org_id, grant_id = base["org"]["id"], base["grant"]["id"]
    carol = invite_user(org_id, grant_id, username="carol", email="carol@meridian.example", level="EDITOR")
    carol = accept_user(carol["id"])
    item = create_published_item(org_id, carol["id"], title="Carol Map", item_kind="WEB_MAP")
    d = get_success_data(_share(api, item["id"], "ORGANIZATION", item["version"], carol["id"]))
    resp = _share(api, item["id"], "PUBLIC", d["version"], carol["id"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_USER_LEVEL)
    after = get_item(item["id"])
    assert after["sharing_level"] == "ORGANIZATION"
    assert after["version"] == d["version"]


def test_viewer_level_also_blocked_from_public(api):
    """PRD section 3.9: "moving from `ORGANIZATION` to `PUBLIC` requires the
    owner's `named_user_level` to be one of `CREATOR`, `PROFESSIONAL`, or
    `PROFESSIONAL_PLUS` (else `ERR_INSUFFICIENT_USER_LEVEL`, HTTP 403)".

    Design: Corner/validations/insufficient_user_level_blocks_public_share
    """
    base = setup_with_user()
    org_id, grant_id = base["org"]["id"], base["grant"]["id"]
    bob = invite_user(org_id, grant_id, username="bob", email="bob@meridian.example", level="VIEWER")
    bob = accept_user(bob["id"])
    item = create_published_item(org_id, bob["id"], title="Bob Map", item_kind="WEB_MAP")
    d = get_success_data(_share(api, item["id"], "ORGANIZATION", item["version"], bob["id"]))
    validate_error(_share(api, item["id"], "PUBLIC", d["version"], bob["id"]),
                   ApiErrorId.ERR_INSUFFICIENT_USER_LEVEL)


def test_offline_publish_requires_supports_offline_grant(api):
    """PRD section 3.9: "If `offline_enabled` is true, the organization must
    hold an `ACTIVE` grant whose product has `supports_offline` true (else
    `ERR_OFFLINE_NOT_LICENSED`, HTTP 403)."

    Design: Corner/validations/offline_publish_requires_supports_offline_grant
    """
    set_clock()
    org = setup_org(name="NoOffline Org")
    get_success_data(api.create_credit_pool(
        {"organization_id": org["id"], "capacity_credits": 1000}, BA_HEADERS))
    product = setup_product(
        product_code="BASIC-11", license_kind="NAMED_USER", edition="BASIC",
        major_version=11, base_seat_count=10, supports_offline=False,
        allows_derivative_works=False)
    grant = setup_grant(org["id"], product["id"], seats_allocated=5)
    activate_org(org["id"])
    activate_grant(grant["id"], org["id"])
    user = invite_user(org["id"], grant["id"], username="nia",
                       email="nia@noexample.example", level="CREATOR")
    user = accept_user(user["id"])
    item = create_draft_item(org["id"], user["id"], title="Offline", item_kind="WEB_MAP",
                             storage_bytes=0, offline_enabled=True)
    resp = api.transition_content_item(
        item["id"], {"target_status": "PUBLISHED"}, make_named_user_headers(user["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFLINE_NOT_LICENSED)
    assert get_item(item["id"])["status"] == "DRAFT"
    assert list_batches(org["id"], service_kind="STORAGE") == []


def test_offline_publish_succeeds_with_supports_offline_grant(api):
    """PRD section 3.9: "If `offline_enabled` is true, the organization must
    hold an `ACTIVE` grant whose product has `supports_offline` true (else
    `ERR_OFFLINE_NOT_LICENSED`, HTTP 403)."

    Design: Corner/validations/offline_publish_requires_supports_offline_grant
    """
    base = setup_with_user()  # base product has supports_offline=True
    owner = base["user"]["id"]
    item = create_draft_item(base["org"]["id"], owner, title="Offline OK",
                             item_kind="WEB_MAP", storage_bytes=0, offline_enabled=True)
    data = publish_item(item["id"], owner)
    assert data["status"] == "PUBLISHED"


def test_derivative_publish_from_flagged_source_rejected(api):
    """PRD section 3.9: "If `derived_from_item_id` is set, the organization
    must hold an `ACTIVE` grant whose product has `allows_derivative_works`
    true (else `ERR_DERIVATIVE_WORKS_NOT_LICENSED`, HTTP 403), and the source
    item must currently be `PUBLISHED` (else `ERR_DERIVATIVE_SOURCE_UNAVAILABLE`,
    HTTP 403)."

    Design: Corner/validations/derivative_publish_from_flagged_source_rejected
    """
    base = setup_with_user()
    owner = base["user"]["id"]
    src = create_published_item(base["org"]["id"], owner, title="Src", item_kind="FEATURE_LAYER")
    get_success_data(api.moderate_content_item(src["id"], {"action": "FLAG"}, CM_HEADERS))
    deriv = create_draft_item(base["org"]["id"], owner, title="Deriv", item_kind="WEB_MAP",
                              storage_bytes=0, derived_from_item_id=src["id"])
    resp = api.transition_content_item(
        deriv["id"], {"target_status": "PUBLISHED"}, make_named_user_headers(owner))
    validate_error(resp, ApiErrorId.ERR_DERIVATIVE_SOURCE_UNAVAILABLE)
    assert get_item(deriv["id"])["status"] == "DRAFT"


def test_derivative_publish_succeeds_from_published_source(api):
    """PRD section 3.9: "If `derived_from_item_id` is set, the organization
    must hold an `ACTIVE` grant whose product has `allows_derivative_works`
    true (else `ERR_DERIVATIVE_WORKS_NOT_LICENSED`, HTTP 403), and the source
    item must currently be `PUBLISHED` (else `ERR_DERIVATIVE_SOURCE_UNAVAILABLE`,
    HTTP 403)."

    Design: Corner/validations/derivative_publish_from_flagged_source_rejected
    """
    base = setup_with_user()  # base product allows_derivative_works=True
    owner = base["user"]["id"]
    src = create_published_item(base["org"]["id"], owner, title="Src2", item_kind="FEATURE_LAYER")
    deriv = create_draft_item(base["org"]["id"], owner, title="Deriv2", item_kind="WEB_MAP",
                              storage_bytes=0, derived_from_item_id=src["id"])
    data = publish_item(deriv["id"], owner)
    assert data["status"] == "PUBLISHED"


def test_flag_cascade_hits_only_depth_one_derivatives(api):
    """PRD section 3.9: "Flagging (action `FLAG`) moves a `PUBLISHED` item to
    `FLAGGED` (the item must be `PUBLISHED`, else `ERR_ITEM_NOT_PUBLISHED`),
    forces its sharing level to `PRIVATE` — bypassing the single-step sharing
    rule — and cascades one level deep: every other ContentItem whose
    `derived_from_item_id` is this item and which is currently `PUBLISHED` is
    also moved to `FLAGGED`, while *their* derivatives are not re-flagged."

    Design: Corner/state_machines/flag_cascade_hits_only_depth_one_derivatives
    """
    base = setup_with_user()
    owner = base["user"]["id"]
    a = create_published_item(base["org"]["id"], owner, title="A", item_kind="FEATURE_LAYER")
    b = create_published_item(base["org"]["id"], owner, title="B", item_kind="WEB_MAP",
                              derived_from_item_id=a["id"])
    c = create_published_item(base["org"]["id"], owner, title="C", item_kind="WEB_MAP",
                              derived_from_item_id=b["id"])
    get_success_data(api.moderate_content_item(a["id"], {"action": "FLAG"}, CM_HEADERS))
    assert get_item(a["id"])["status"] == "FLAGGED"
    assert get_item(a["id"])["sharing_level"] == "PRIVATE"
    assert get_item(b["id"])["status"] == "FLAGGED"
    assert get_item(c["id"])["status"] == "PUBLISHED"


def test_named_user_cannot_moderate_and_moderator_cannot_share(api):
    """PRD section 2.1: "A request whose role is not authorized for the target
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD section 4 endpoint table: "| POST | /geo-orgs/content-items/{id}/moderate
    | Moderation: FLAG (PUBLISHED → FLAGGED, forces PRIVATE, flags depth-1
    derivatives) or RESOLVE (FLAGGED → PUBLISHED; requires
    resolution_rationale ≥ 20 chars) | ContentModerator |" and
    "| POST | /geo-orgs/content-items/{id}/share | Single-step sharing
    transition PRIVATE↔ORGANIZATION↔PUBLIC; OCC on ContentItem.version |
    NamedUser |".

    Design: Corner/roles/named_user_cannot_moderate_and_moderator_cannot_share
    """
    base = setup_with_user()
    owner = base["user"]["id"]
    item = create_published_item(base["org"]["id"], owner, title="R", item_kind="WEB_MAP")
    resp = api.moderate_content_item(item["id"], {"action": "FLAG"},
                                     make_named_user_headers(owner))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    resp = api.share_content_item(
        item["id"],
        {"target_sharing_level": "ORGANIZATION", "expected_content_item_version": item["version"]},
        CM_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    after = get_item(item["id"])
    assert after["status"] == "PUBLISHED"
    assert after["sharing_level"] == "PRIVATE"


def test_moderator_can_retract_published_item(api):
    """PRD section 3.9: "The item must be `PUBLISHED`, and the caller must be
    either a `ContentModerator` or the item's owner (else
    `ERR_NOT_ITEM_OWNER`)."

    Design: Corner/roles/named_user_cannot_moderate_and_moderator_cannot_share
    """
    base = setup_with_user()
    item = create_published_item(base["org"]["id"], base["user"]["id"], title="MR",
                                 item_kind="WEB_MAP")
    data = get_success_data(api.transition_content_item(
        item["id"], {"target_status": "RETRACTED"}, CM_HEADERS))
    assert data["status"] == "RETRACTED"
