"""State-machine corners: transitions, preconditions, initial and terminal states."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers.api_errors import (  # noqa: E402
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SELF_APPROVAL_FORBIDDEN,
)
from test_helpers.assertions import (  # noqa: E402
    assert_audit_action_present,
    assert_fields,
    assert_instant_equals,
    assert_money,
    snapshot_price,
)
from test_helpers.constants import (  # noqa: E402
    ACTION_APPROVE,
    ACTION_SCHEDULE,
    ACTION_SUBMIT,
    ACTION_WITHDRAW,
    AUDIT_BUNDLE_PUBLISHED,
    AUDIT_ITEM_EIGHTY_SIXED,
    AUDIT_STATE_PASSED,
    AUDIT_STATE_PENDING,
    AVAIL_AVAILABLE,
    AVAIL_LIMITED,
    AVAIL_UNAVAILABLE,
    BUNDLE_DRAFT,
    BUNDLE_PUBLISHED,
    BUNDLE_SUPERSEDED,
    BUNDLE_VALIDATED,
    BURGER_ZONE_A_CENTS,
    CACHE_FRESH,
    CACHE_MISSING,
    CACHE_STALE,
    CAMPAIGN_WITHDRAWN,
    CATEGORY_DESSERT,
    CATEGORY_ENTREE,
    CLOCK_T0,
    DEVICE_CODE_K001,
    HEALTH_OFFLINE,
    HEALTH_ONLINE,
    LISTING_EIGHTY_SIXED,
    LOCK_PENDING_CHANGE,
    PAYMENT_COMPLIANT,
    PAYMENT_UNATTESTED,
    PCR_DRAFT,
    PCR_APPROVED,
    PCR_PENDING_APPROVAL,
    POSTURE_OPEN,
    SKU_BURGER,
    SKU_PIE,
    STORE_CODE_S001,
    STORE_CODE_S002,
    SUBJECT_CONTENT_BUNDLE,
    SUBJECT_ITEM_AVAILABILITY,
    SUPPLY_LOW,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ANALYST,
    APPROVER,
    CONTENT_MANAGER,
    USER_ANALYST_1,
    make_analyst_headers,
    make_approver_headers,
    make_store_operator_headers,
)

EIGHTY_SIX_UNTIL = "2026-08-05T21:00:00Z"
LATER_EIGHTY_SIX_UNTIL = "2026-08-05T23:00:00Z"
DUAL_HAT = "u_dual_hat"
NINTH_APPROVER = "u_approver_9"


def _priced_item_and_zone(api, proposed_cents: int, headers):
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_ZONE")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    item_version = world.get_item(burger["id"])["version"]
    request = world.price_change_request(burger["id"], zone["id"], proposed_cents, CLOCK_T0,
                                        item_version, headers,
                                        justification="Beef cost increase")
    return world, zone, burger, item_version, request


def test_submitting_a_draft_request_opens_the_approval_queue(api):
    """PRD: "**Submission.** The analyst that opened the request submits it, moving `DRAFT → PENDING_APPROVAL`."

    Design: Corner/state_machines/submit_moves_price_change_request_from_draft_to_pending_approval
    """
    world, _, burger, item_version, request = _priced_item_and_zone(api, 590, ANALYST)

    assert request["state"] == PCR_DRAFT
    # PRD 3.3: creation increments the item's version by 1 and pins
    # pinned_menu_item_version to the item's *new* version.
    assert request["pinned_menu_item_version"] == item_version + 1

    submitted = validate_success(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_SUBMIT), ANALYST),
        200,
    )
    assert_fields(submitted, state=PCR_PENDING_APPROVAL, revision_round=0,
                  required_approvals=2, approval_user_ids=[],
                  requested_by_user_id=USER_ANALYST_1)

    item = world.get_item(burger["id"])
    assert_fields(item, pending_price_request_count=1, pricing_lock_state=LOCK_PENDING_CHANGE)


def test_an_approver_may_not_approve_the_request_it_wrote(api):
    """PRD: "In both approval branches the approving `X-User-ID` must differ from `requested_by_user_id` and must not already appear in `approval_user_ids`; either violation is refused with `ERR_SELF_APPROVAL_FORBIDDEN`."

    Design: Corner/state_machines/approver_cannot_approve_a_request_it_opened
    """
    _, _, _, _, request = _priced_item_and_zone(api, 570, make_analyst_headers(DUAL_HAT))
    assert request["requested_by_user_id"] == DUAL_HAT
    validate_success(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_SUBMIT),
                                        make_analyst_headers(DUAL_HAT)),
        200,
    )

    refused = api.price_change_request_action(request["id"], f.action_payload(ACTION_APPROVE),
                                              make_approver_headers(DUAL_HAT))
    validate_error(refused, ERR_SELF_APPROVAL_FORBIDDEN, 403)

    still_pending = validate_success(api.get_price_change_request(request["id"], ANALYST), 200)
    assert_fields(still_pending, state=PCR_PENDING_APPROVAL, approval_user_ids=[])

    approved = validate_success(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_APPROVE),
                                        make_approver_headers(NINTH_APPROVER)),
        200,
    )
    assert_fields(approved, state=PCR_APPROVED, required_approvals=1,
                  approval_user_ids=[NINTH_APPROVER])


def test_publishing_executes_every_declared_side_effect(api):
    """PRD: "`price_snapshot` is frozen to one object per snapshot item and price zone pair, each holding a `menu_item_id`, a `price_zone_id` and the `price_cents` that is the effective zone price of that pair computed at this instant."

    Design: Corner/state_machines/publish_executes_snapshot_and_cluster_version_side_effects
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    assert cluster["published_bundle_version"] == 0
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    pie = world.item(SKU_PIE, category=CATEGORY_DESSERT, base_price_cents=200,
                     contrast_ratio=5.4)

    bundle = world.bundle(cluster["id"], effective_from_utc="2026-08-05T00:00:00Z")
    bundle = world.slot(bundle["id"], bundle["version"], category_codes=[CATEGORY_ENTREE])
    audited = world.audit_pass(bundle["id"])
    assert audited["accessibility_audit_state"] == AUDIT_STATE_PASSED
    validated = world.validate(bundle["id"])
    assert_fields(validated, state=BUNDLE_VALIDATED, validation_findings=[])

    published = world.publish(bundle["id"])
    assert_fields(published, state=BUNDLE_PUBLISHED, bundle_version=1, stale_flag=False,
                  snapshot_item_ids=[burger["id"]])
    assert_instant_equals(published["published_at_utc"], CLOCK_T0, "published_at_utc")
    assert pie["id"] not in published["snapshot_item_ids"]

    assert len(published["price_snapshot"]) == 1
    assert_money(snapshot_price(published, burger["id"], zone["id"]), BURGER_ZONE_A_CENTS,
                 "price_snapshot price_cents")
    assert published["price_snapshot_checksum"] == published["live_price_checksum"]

    refreshed = validate_success(api.get_store_cluster(cluster["id"], CONTENT_MANAGER), 200)
    assert refreshed["published_bundle_version"] == 1
    assert_audit_action_present(world.audit(subject_kind=SUBJECT_CONTENT_BUNDLE,
                                            subject_id=bundle["id"]),
                               AUDIT_BUNDLE_PUBLISHED)


def test_approving_a_draft_request_is_not_a_declared_transition(api):
    """PRD: "Declared transition — the requested action verb is a declared transition out of the row's current state → `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/approve_a_draft_price_request_returns_invalid_state_transition
    """
    _, _, _, _, request = _priced_item_and_zone(api, 570, ANALYST)
    assert request["state"] == PCR_DRAFT

    response = api.price_change_request_action(request["id"], f.action_payload(ACTION_APPROVE),
                                               APPROVER)
    validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)

    unchanged = validate_success(api.get_price_change_request(request["id"], ANALYST), 200)
    assert_fields(unchanged, state=PCR_DRAFT, approval_user_ids=[])


def test_a_new_bundle_starts_in_draft_with_nothing_derived(api):
    """PRD: "The new bundle starts in `DRAFT` with its `accessibility_audit_state` at `PENDING`, its `bundle_version` set to 1 more than the highest `bundle_version` among the cluster's existing bundles — 1 for the cluster's first bundle — its drift marker `stale_flag` false, and `daypart_slots`, `snapshot_item_ids`, `price_snapshot`, `validation_findings` and `accessibility_findings` all empty, `price_snapshot_checksum` and `live_price_checksum` at 0, and `published_at_utc` null."

    Design: Corner/state_machines/new_content_bundle_starts_in_draft_with_empty_derived_collections
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    cluster = world.cluster("CL_WEST")

    bundle = validate_success(
        api.create_content_bundle(
            f.content_bundle_payload(cluster["id"],
                                     effective_from_utc="2026-08-05T00:00:00Z"),
            CONTENT_MANAGER),
        201,
    )

    assert_fields(bundle, state=BUNDLE_DRAFT, accessibility_audit_state=AUDIT_STATE_PENDING,
                  bundle_version=1, stale_flag=False, daypart_slots=[], snapshot_item_ids=[],
                  price_snapshot=[], validation_findings=[], accessibility_findings=[],
                  price_snapshot_checksum=0, live_price_checksum=0)
    assert bundle["published_at_utc"] is None

    refreshed = validate_success(api.get_store_cluster(cluster["id"], CONTENT_MANAGER), 200)
    assert refreshed["published_bundle_version"] == 0


def test_a_withdrawn_campaign_version_is_locked_down(api):
    """PRD: "Terminality — the addressed row is not already in a terminal state → `ERR_ALREADY_TERMINAL` (409)."

    Design: Corner/state_machines/withdrawn_campaign_version_cannot_be_scheduled_again
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    cluster = world.cluster("CL_WEST")
    version = world.campaign("SPRING5", cluster["id"], "2026-09-01T00:00:00Z",
                             "2026-09-10T00:00:00Z", discount_value=500, priority_rank=30)

    withdrawn = validate_success(
        api.campaign_version_action(version["id"], f.action_payload(ACTION_WITHDRAW),
                                    CONTENT_MANAGER),
        200,
    )
    assert withdrawn["state"] == CAMPAIGN_WITHDRAWN

    response = api.campaign_version_action(version["id"], f.action_payload(ACTION_SCHEDULE),
                                           CONTENT_MANAGER)
    validate_error(response, ERR_ALREADY_TERMINAL, 409)

    unchanged = validate_success(api.get_campaign_version(version["id"], CONTENT_MANAGER), 200)
    assert unchanged["state"] == CAMPAIGN_WITHDRAWN
    assert unchanged["pinned_bundle_version"] is None


def test_eighty_sixing_a_row_that_is_already_pulled_is_refused(api):
    """PRD: "A manual 86 requires the row's `listing_state` to be `LISTED`, sets `eighty_six_state` to `MANUAL_86`, takes `eighty_six_until_utc` from the supplied `until_utc`, records the supplied `eighty_six_reason`, drives `availability_state` to `UNAVAILABLE` and runs exactly the same five-link cascade, recording `ITEM_EIGHTY_SIXED`."

    Design: Corner/state_machines/repeating_eighty_six_on_an_already_eighty_sixed_row_is_rejected
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    row = world.availability(store["id"], burger["id"], on_hand_units=40, par_units=20)
    operator = make_store_operator_headers(store["id"])

    pulled = validate_success(
        api.item_availability_action(
            row["id"], f.eighty_six_payload(EIGHTY_SIX_UNTIL, eighty_six_reason="Grill down"),
            operator),
        200,
    )
    assert_fields(pulled, listing_state=LISTING_EIGHTY_SIXED,
                  availability_state=AVAIL_UNAVAILABLE, eighty_six_reason="Grill down")
    assert_instant_equals(pulled["eighty_six_until_utc"], EIGHTY_SIX_UNTIL, "eighty_six_until_utc")

    repeat = api.item_availability_action(
        row["id"],
        f.eighty_six_payload(LATER_EIGHTY_SIX_UNTIL, eighty_six_reason="Grill still down"),
        operator,
    )
    validate_error(repeat, ERR_INVALID_STATE_TRANSITION, 409)

    unchanged = validate_success(api.get_item_availability(row["id"], operator), 200)
    assert_fields(unchanged, listing_state=LISTING_EIGHTY_SIXED,
                  eighty_six_reason="Grill down")
    assert_instant_equals(unchanged["eighty_six_until_utc"], EIGHTY_SIX_UNTIL,
                          "eighty_six_until_utc")

    rows = world.audit(subject_kind=SUBJECT_ITEM_AVAILABILITY, subject_id=row["id"],
                       action=AUDIT_ITEM_EIGHTY_SIXED)
    assert len(rows) == 1, f"the refused repeat writes no second audit row: {rows!r}"


def test_the_three_device_dimensions_move_one_at_a_time(api):
    """PRD: "A device carries **three independent state dimensions**, each held in its own field: its health band in `health_state`, its content-cache condition in `cache_state`, and its payment-attestation condition in `payment_compliance_state`."

    Design: Corner/state_machines/device_health_payment_and_cache_dimensions_advance_independently
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])

    device = world.device(store["id"], DEVICE_CODE_K001)
    assert_fields(device, health_state=HEALTH_OFFLINE, cache_state=CACHE_MISSING,
                  payment_compliance_state=PAYMENT_UNATTESTED)

    after_heartbeat = world.heartbeat(device["id"])
    assert_fields(after_heartbeat, health_state=HEALTH_ONLINE, cache_state=CACHE_MISSING,
                  payment_compliance_state=PAYMENT_UNATTESTED)

    after_attestation = world.attest(device["id"])
    assert_fields(after_attestation, health_state=HEALTH_ONLINE, cache_state=CACHE_MISSING,
                  payment_compliance_state=PAYMENT_COMPLIANT)
    # PRD 2.9: the degraded test names a *stale* cache; a MISSING cache is not one,
    # so with an ONLINE kiosk and a COMPLIANT payment dimension the store reads OPEN.
    assert world.get_store(store["id"])["content_posture"] == POSTURE_OPEN

    after_sync = world.cache_sync(device["id"], bundle["id"])
    assert_fields(after_sync, health_state=HEALTH_ONLINE, cache_state=CACHE_FRESH,
                  payment_compliance_state=PAYMENT_COMPLIANT,
                  cached_bundle_id=bundle["id"], cached_bundle_version=1)


def test_the_chainwide_rollup_reads_every_store_row(api):
    """PRD: "The item's `chainwide_availability_state` then bubbles up over **every** availability row of that item, regardless of the owning store's posture and including discontinued rows, which still count as unavailable and are never removed: it is `UNAVAILABLE` when the item has no rows at all or when every row is unavailable; `LIMITED` when no row is available and at least one is limited; and `AVAILABLE` otherwise."

    Design: Corner/state_machines/chainwide_availability_bubbles_up_from_every_store_row
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    first = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    second = world.store(cluster["id"], zone["id"], STORE_CODE_S002,
                         timezone_offset_minutes=-300)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    assert burger["chainwide_availability_state"] == AVAIL_UNAVAILABLE, (
        "an item with no rows at all is chain-wide unavailable"
    )

    row_one = world.availability(first["id"], burger["id"], on_hand_units=40, par_units=20)
    row_two = world.availability(second["id"], burger["id"], on_hand_units=40, par_units=20)
    assert world.get_item(burger["id"])["chainwide_availability_state"] == AVAIL_AVAILABLE

    low = world.sync_on_hand(row_one["id"], on_hand_units=4)
    assert_fields(low, supply_state=SUPPLY_LOW, availability_state=AVAIL_LIMITED)
    assert world.get_item(burger["id"])["chainwide_availability_state"] == AVAIL_AVAILABLE, (
        "one still-available row keeps the whole chain available"
    )

    world.sync_on_hand(row_two["id"], on_hand_units=4)
    assert world.get_item(burger["id"])["chainwide_availability_state"] == AVAIL_LIMITED

    world.sync_on_hand(row_one["id"], on_hand_units=0)
    world.sync_on_hand(row_two["id"], on_hand_units=0)
    assert world.get_item(burger["id"])["chainwide_availability_state"] == AVAIL_UNAVAILABLE


def test_a_second_publication_supersedes_only_its_predecessor(api):
    """PRD: "If the cluster already had a `PUBLISHED` bundle, that bundle moves to `SUPERSEDED`, every device caching it moves its content dimension to `STALE`, and the cluster's `published_bundle_version` is recomputed."

    Design: Corner/state_machines/publishing_a_second_bundle_supersedes_only_the_prior_published_one
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)

    first = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])
    assert_fields(first, state=BUNDLE_PUBLISHED, bundle_version=1)
    device = world.device(store["id"], DEVICE_CODE_K001)
    world.heartbeat(device["id"])
    device = world.cache_sync(device["id"], first["id"])
    assert_fields(device, cache_state=CACHE_FRESH, cached_bundle_version=1)

    second = world.bundle(cluster["id"], effective_from_utc="2026-08-06T00:00:00Z")
    second = world.slot(second["id"], second["version"], category_codes=[CATEGORY_ENTREE])
    world.audit_pass(second["id"])
    world.validate(second["id"])
    untouched_draft = world.bundle(cluster["id"], effective_from_utc="2026-08-07T00:00:00Z")

    published = world.publish(second["id"])
    assert_fields(published, state=BUNDLE_PUBLISHED, bundle_version=2)

    assert world.get_bundle(first["id"])["state"] == BUNDLE_SUPERSEDED
    assert world.get_bundle(untouched_draft["id"])["state"] == BUNDLE_DRAFT, (
        "a bundle that was never published is not superseded"
    )
    assert world.get_device(device["id"])["cache_state"] == CACHE_STALE
    assert validate_success(api.get_store_cluster(cluster["id"], CONTENT_MANAGER),
                            200)["published_bundle_version"] == 2
