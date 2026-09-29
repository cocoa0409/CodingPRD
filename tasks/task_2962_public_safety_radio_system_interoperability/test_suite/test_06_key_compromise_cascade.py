"""The five linked consequences of declaring an encryption keyset compromised.

Every test in this module translates exactly one design instance and carries a
verbatim PRD citation for the rule it pins.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_KEYSET_NOT_ACTIVE
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_unit_dimensions,
)
from test_helpers.constants import (
    AGENCY_TYPE_LAW,
    ALGO_AES256,
    BACKUP_GENERATOR,
    CAMPAIGN_COMPLETED,
    COVERAGE_MISSION_CRITICAL,
    ENC_ENCRYPTED,
    INTEROP_PATCH_AUTHORITY,
    KEY_KEYED,
    KEY_STALE,
    KEYSET_ACTIVE,
    KEYSET_COMPROMISED,
    LOCK_REASON_KEY_COMPROMISE,
    LOCK_REASON_NONE,
    MODEL_PORTABLE,
    PATCH_ACTIVE,
    PATCH_RELEASED,
    PROVISION_ASSIGNED,
    RELEASE_REASON_KEY_COMPROMISE,
    STANDARD_P25_PHASE2,
    TG_ACTION_UNLOCK,
    TG_ACTIVE,
    TG_KIND_INTEROP,
    TG_KIND_TACTICAL,
    TG_LOCKED,
)
from test_helpers.test_users import SYSTEM_ADMIN, make_agency_radio_manager_headers


def _golf_city_active_patch(api: ApiClient):
    """Agency G with one `KEYED` radio, two `ENCRYPTED` talkgroups on a
    `MISSION_CRITICAL` site, and one `ACTIVE` patch riding on them.

    Returns `(agency, site, keyset, campaign, unit, tg1, tg2, patch)` with the
    logical clock left at `2026-08-01T00:00:00Z`.
    """
    site = fx.site_with_coverage(
        api,
        985,
        1000,
        site_code="MC-1",
        name="Mission Critical One",
        channel_capacity=12,
        backup_power_type=BACKUP_GENERATOR,
        generator_fuel_hours=48,
    )
    assert_fields(site, coverage_class=COVERAGE_MISSION_CRITICAL)

    agency = fx.register_agency(
        api,
        name="Golf City Police",
        agency_code="LAWG1",
        agency_type=AGENCY_TYPE_LAW,
        interop_privilege=INTEROP_PATCH_AUTHORITY,
        recorder_retention_days=180,
    )
    template = fx.published_template(
        api,
        template_name="GOLF-ENC-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=8,
        encryption_required=True,
    )
    tg1 = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="TAC1",
        tg_decimal_id=101,
        kind=TG_KIND_TACTICAL,
        encryption_mode=ENC_ENCRYPTED,
    )
    tg2 = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="TAC2",
        tg_decimal_id=102,
        kind=TG_KIND_INTEROP,
        encryption_mode=ENC_ENCRYPTED,
    )
    unit = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="SNG001",
        radio_id=6001,
        model=MODEL_PORTABLE,
    )
    keyset = fx.active_keyset(
        api,
        keyset_name="KS-CMP-1",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-12-01T00:00:00Z",
    )
    campaign = fx.keyed_fleet(
        api,
        agency["id"],
        keyset["id"],
        "2026-08-01T00:00:00Z",
        "2026-08-02T00:00:00Z",
        "2026-08-01T00:00:00Z",
    )
    assert_fields(campaign, status=CAMPAIGN_COMPLETED, rekeyed_unit_count=1)
    assert_unit_dimensions(fx.read_unit(api, unit["id"]), PROVISION_ASSIGNED, KEY_KEYED)

    patch = fx.active_patch(
        api,
        tg1["id"],
        tg2["id"],
        agency["id"],
        scheduled_start="2026-08-01T00:00:00Z",
        scheduled_end="2026-08-02T00:00:00Z",
    )
    assert_fields(patch, status=PATCH_ACTIVE)
    assert_instant_equals(patch["activated_at"], "2026-08-01T00:00:00Z", "activated_at")
    return agency, site, keyset, campaign, unit, tg1, tg2, patch


def test_keyset_compromise_cascades_five_links_to_patch_release(
    api: ApiClient, clock_at_start: str
):
    """Declaring the key compromised staled the radio, the staled radio locked the
    encrypted talkgroups, and the locked talkgroups dropped the live patch — three
    links, each caused by the one before it, inside one request.

    PRD 3.5: "Because the key can no longer be trusted, every subscriber unit
    whose `active_keyset_id` is the compromised keyset and whose `key_status` is
    `KEYED` moves to `key_status` `KEY_STALE`. Its `provision_status` is left
    exactly as it was, and its `active_keyset_id` is **not** cleared — the radio
    still holds the bad key, which is why the state is called stale rather than
    keyless."

    PRD 3.5: "Every talkgroup whose `encryption_mode` is `ENCRYPTED`, whose
    `status` is `ACTIVE`, and whose `owner_agency_id` now owns zero subscriber
    units with `key_status` `KEYED` moves to `status` `LOCKED` with `lock_reason`
    set to `KEY_COMPROMISE`."

    PRD 3.5: "Every interoperability patch whose `status` is `REQUESTED` or
    `ACTIVE` and which names a newly locked talkgroup as either its
    `source_talkgroup_id` or its `target_talkgroup_id` moves to `status`
    `RELEASED` with `released_at` stamped at now and `release_reason` set to
    `KEY_COMPROMISE`; each such patch has its `duration_minutes` recomputed by the
    patch-duration rule of Section 3.6."

    Design: Difficulty/transitive_cascade/keyset_compromise_cascades_five_links_to_patch_release
    """
    agency, _site, keyset, _campaign, unit, tg1, tg2, patch = _golf_city_active_patch(api)

    compromised = fx.compromise_keyset(api, keyset["id"])

    # Link 0: the trigger itself.
    assert_fields(compromised, status=KEYSET_COMPROMISED, loaded_unit_count=0)
    assert_instant_equals(
        compromised["compromised_at"], "2026-08-01T00:00:00Z", "compromised_at"
    )

    # Link 1: the radio goes stale but keeps the bad key and its provisioning.
    staled = fx.read_unit(api, unit["id"])
    assert_unit_dimensions(staled, PROVISION_ASSIGNED, KEY_STALE)
    assert_fields(staled, active_keyset_id=keyset["id"])

    # Link 2: both ENCRYPTED talkgroups lock, because the agency now has no
    # keyed radio at all.
    for talkgroup in (tg1, tg2):
        locked = fx.read_talkgroup(api, talkgroup["id"])
        assert_fields(
            locked, status=TG_LOCKED, lock_reason=LOCK_REASON_KEY_COMPROMISE
        )

    # Link 3: the patch riding on those talkgroups drops, and the duration rule
    # of PRD 3.6 logs 0 rather than null for a same-minute release.
    released = validate_success(api.get_interop_patch(patch["id"], SYSTEM_ADMIN), 200)
    assert_fields(
        released,
        status=PATCH_RELEASED,
        release_reason=RELEASE_REASON_KEY_COMPROMISE,
        duration_minutes=0,
        requesting_agency_id=agency["id"],
    )
    assert_instant_equals(released["released_at"], "2026-08-01T00:00:00Z", "released_at")


def test_keyset_compromise_cascade_settles_the_denormalized_patch_counters(
    api: ApiClient, clock_at_start: str
):
    """Because the patches were released, the two denormalized counters are
    recomputed to zero in the same request — and the already-executed campaign is
    left alone by the independent fifth link.

    PRD 3.5: "Because those patches were released, `active_patch_count` is
    recomputed on every talkgroup touched and `active_patch_request_count` is
    recomputed on every member agency touched."

    PRD 3.5: "Independently of the talkgroup chain, every OTAR campaign whose
    `keyset_id` is the compromised keyset and whose `status` is still `SCHEDULED`
    moves to `ABORTED`. Campaigns already `COMPLETED` are historical records and
    are left alone."

    Design: Difficulty/transitive_cascade/keyset_compromise_cascades_five_links_to_patch_release
    """
    agency, _site, keyset, campaign, _unit, tg1, tg2, _patch = _golf_city_active_patch(api)

    # Pre-trigger baseline: one live patch is counted on both talkgroups and on
    # the requesting agency.
    assert_fields(fx.read_talkgroup(api, tg1["id"]), active_patch_count=1)
    assert_fields(fx.read_talkgroup(api, tg2["id"]), active_patch_count=1)
    assert_fields(fx.read_agency(api, agency["id"]), active_patch_request_count=1)
    assert_fields(
        validate_success(api.get_keyset(keyset["id"], SYSTEM_ADMIN), 200),
        status=KEYSET_ACTIVE,
        loaded_unit_count=1,
    )

    fx.compromise_keyset(api, keyset["id"])

    assert_fields(fx.read_talkgroup(api, tg1["id"]), active_patch_count=0)
    assert_fields(fx.read_talkgroup(api, tg2["id"]), active_patch_count=0)
    assert_fields(fx.read_agency(api, agency["id"]), active_patch_request_count=0)

    # The fifth link only sweeps SCHEDULED campaigns.
    survivor = validate_success(api.get_otar_campaign(campaign["id"], SYSTEM_ADMIN), 200)
    assert_fields(survivor, status=CAMPAIGN_COMPLETED, rekeyed_unit_count=1)


def test_talkgroup_unlock_after_key_compromise_requires_a_keyed_radio(
    api: ApiClient, clock_at_start: str
):
    """`UNLOCK` off a `KEY_COMPROMISE` lock is guarded by the state of a different
    entity: it stays refused while the agency's only radio is `KEY_STALE`, and
    succeeds the moment a fresh keyset has been loaded onto that radio.

    PRD 3.6: "`UNLOCK` moves a `LOCKED` talkgroup back to `ACTIVE` and resets
    `lock_reason` to `NONE`, closing the lock cycle — but with one guard: when the
    `lock_reason` is `KEY_COMPROMISE`, the owning agency must have at least one
    subscriber unit whose `key_status` is `KEYED` before the talkgroup may go live
    again, and an unlock attempted while the agency still has no keyed radio is
    rejected with `ERR_KEYSET_NOT_ACTIVE`."

    Design: Corner/state_machines/talkgroup_unlock_after_key_compromise_requires_a_keyed_radio
    """
    agency = fx.register_agency(
        api,
        name="Guarded Transition Agency",
        agency_code="GRD01",
        agency_type=AGENCY_TYPE_LAW,
        recorder_retention_days=180,
    )
    site = fx.register_site(
        api,
        site_code="GRD-1",
        name="Guard One",
        channel_capacity=6,
        backup_power_type=BACKUP_GENERATOR,
    )
    template = fx.published_template(
        api,
        template_name="GRD-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
        encryption_required=True,
    )
    talkgroup = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="GRD-SEC",
        tg_decimal_id=1101,
        kind=TG_KIND_TACTICAL,
        encryption_mode=ENC_ENCRYPTED,
    )
    unit = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="GRD0001",
        radio_id=26001,
        model=MODEL_PORTABLE,
    )
    first_keyset = fx.active_keyset(
        api,
        keyset_name="KS-GUARD-1",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-11-01T00:00:00Z",
    )
    fx.keyed_fleet(
        api,
        agency["id"],
        first_keyset["id"],
        "2026-08-01T00:00:00Z",
        "2026-08-02T00:00:00Z",
        "2026-08-01T00:00:00Z",
    )
    compromised = fx.compromise_keyset(api, first_keyset["id"])
    assert_fields(compromised, status=KEYSET_COMPROMISED, loaded_unit_count=0)
    assert_unit_dimensions(fx.read_unit(api, unit["id"]), PROVISION_ASSIGNED, KEY_STALE)
    assert_fields(
        fx.read_talkgroup(api, talkgroup["id"]),
        status=TG_LOCKED,
        lock_reason=LOCK_REASON_KEY_COMPROMISE,
    )

    # A replacement keyset exists and is ACTIVE, but no radio carries it yet.
    second_keyset = fx.active_keyset(
        api,
        keyset_name="KS-GUARD-2",
        algorithm=ALGO_AES256,
        crypto_period_start="2026-08-01T00:00:00Z",
        crypto_period_end="2026-11-01T00:00:00Z",
    )

    premature = api.talkgroup_status(
        talkgroup["id"],
        {"action": TG_ACTION_UNLOCK},
        make_agency_radio_manager_headers(agency["id"]),
    )
    validate_error(premature, ERR_KEYSET_NOT_ACTIVE, 409)
    assert_fields(
        fx.read_talkgroup(api, talkgroup["id"]),
        status=TG_LOCKED,
        lock_reason=LOCK_REASON_KEY_COMPROMISE,
    )

    rekey = fx.keyed_fleet(
        api,
        agency["id"],
        second_keyset["id"],
        "2026-08-01T00:00:00Z",
        "2026-08-02T00:00:00Z",
        "2026-08-01T00:00:00Z",
    )
    assert_fields(
        rekey,
        status=CAMPAIGN_COMPLETED,
        target_unit_count=1,
        rekeyed_unit_count=1,
        failed_unit_count=0,
    )
    rekeyed_unit = fx.read_unit(api, unit["id"])
    assert_unit_dimensions(rekeyed_unit, PROVISION_ASSIGNED, KEY_KEYED)
    assert_fields(rekeyed_unit, active_keyset_id=second_keyset["id"])
    assert_fields(
        validate_success(api.get_keyset(second_keyset["id"], SYSTEM_ADMIN), 200),
        loaded_unit_count=1,
    )

    unlocked = fx.talkgroup_action(
        api, talkgroup["id"], agency["id"], TG_ACTION_UNLOCK
    )
    assert_fields(unlocked, status=TG_ACTIVE, lock_reason=LOCK_REASON_NONE)
