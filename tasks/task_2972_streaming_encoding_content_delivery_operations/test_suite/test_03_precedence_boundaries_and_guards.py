"""Validation-ladder precedence, inclusive boundaries and cross-entity guards.

Three families of behaviour are exercised here, all rooted in PRD §2.6:

* a single request that violates two rungs at once must report the *earlier*
  rung and must never surface the later rung's identifier;
* the two inclusive numeric boundaries of the delivery desk -- capacity accepted
  at exact equality and refused one hundredth of a Gbps past it, and a
  compatibility score of exactly 0.00 against a strict `> 0.00` predicate;
* the two cross-entity guards, driven on both arms: the refusing arm first, then
  the identical request succeeding once the precondition on the *other* entity
  has been repaired.

Every test builds its own world from an empty database with the logical clock at
its startup value.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money, assert_score
from test_helpers.test_users import DELIVERY_ENGINEER, DRM_OPERATOR, ENCODING_ENGINEER

# ---------------------------------------------------------------------------
# World builders -- one per scenario, so every test stands on its own
# ---------------------------------------------------------------------------


def _failover_state_versus_capacity_world(api):
    """Two vendors, a live-event title, a fully-booked failover vendor and a
    still-`RESERVED` target reservation that names it."""
    alpha = fx.create_vendor(
        api, vendor_code="ALPHA", regions=["US"], committed_gbps=100.00, cost_per_gb_usd=0.0250
    )
    bravo = fx.create_vendor(
        api, vendor_code="BRAVO", regions=["US"], committed_gbps=60.00, cost_per_gb_usd=0.0300
    )
    title = fx.create_live_event_title(
        api,
        external_ref="TTL-LIVE-01",
        title_name="Championship Final",
        studio_code="NOVASPORT",
    )
    fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-11-01T00:00:00Z",
        license_tier="STANDARD",
    )
    blocking = fx.create_reservation(
        api,
        title["id"],
        bravo["id"],
        window_start_at="2026-09-10T00:00:00Z",
        window_end_at="2026-09-10T04:00:00Z",
        reserved_gbps=60.00,
    )
    target = fx.create_reservation(
        api,
        title["id"],
        alpha["id"],
        failover_vendor_id=bravo["id"],
        window_start_at="2026-09-10T00:00:00Z",
        window_end_at="2026-09-10T04:00:00Z",
        reserved_gbps=10.00,
    )
    return alpha, bravo, blocking, target


def test_failover_from_reserved_reports_the_state_rung_not_the_capacity_rung(api):
    """A failover that is both wrongly-stated and over capacity reports 409 ERR_RESERVATION_STATE_INVALID.

    PRD §2.6: "The **first** rule violated determines the single error returned,
    and no later rule is evaluated once a rule has fired — even when a later
    rule's condition also holds."

    PRD §3.8: "A failover attempted from `RESERVED`, from `FAILED_OVER` again, or
    from either terminal state answers `ERR_RESERVATION_STATE_INVALID`; there is
    no route back to the primary vendor and no second failover."

    Design: Difficulty/priority_pair_validation_conflict/reservation_failover_state_beats_capacity
    """
    _alpha, _bravo, _blocking, target = _failover_state_versus_capacity_world(api)

    response = api.failover_live_reservation(target["id"], DELIVERY_ENGINEER)

    validate_error(response, err.ERR_RESERVATION_STATE_INVALID, 409)
    assert response.status_code != 422, (
        "the fiscal rung must not be reached: "
        f"got {response.status_code} {response.text}"
    )
    assert response.json()["data"]["error_id"] != err.ERR_VENDOR_CAPACITY_EXCEEDED


def test_failover_refused_on_state_leaves_the_reservation_untouched(api):
    """The refused failover writes nothing on the reservation itself.

    PRD §3.8: "On success `active_vendor_id` becomes the `failover_vendor_id`,
    `failover_at` records the logical clock's current instant, and `state`
    becomes `FAILED_OVER`."

    Design: Difficulty/priority_pair_validation_conflict/reservation_failover_state_beats_capacity
    """
    alpha, _bravo, _blocking, target = _failover_state_versus_capacity_world(api)

    validate_error(
        api.failover_live_reservation(target["id"], DELIVERY_ENGINEER),
        err.ERR_RESERVATION_STATE_INVALID,
        409,
    )

    stored = fx.read_reservation(api, target["id"])
    assert stored["state"] == "RESERVED", stored
    assert stored["active_vendor_id"] == alpha["id"], stored
    assert stored["failover_at"] is None, stored
    assert_money(stored["reserved_gbps"], 10.00, "LiveEventReservation.reserved_gbps")


def test_failover_refused_on_state_moves_no_bandwidth_between_vendors(api):
    """Both vendor ledgers still read their pre-failover holds of 10.00 and 60.00.

    PRD §2.9: "A vendor's `reserved_gbps` is always the sum, rounded to two
    decimals, of `reserved_gbps` over the live reservations charged to that
    vendor through `active_vendor_id` whose `state` is `RESERVED`, `ARMED`,
    `LIVE` or `FAILED_OVER`; reservations in `ENDED` or `CANCELLED` hold nothing."

    Design: Difficulty/priority_pair_validation_conflict/reservation_failover_state_beats_capacity
    """
    alpha, bravo, blocking, target = _failover_state_versus_capacity_world(api)

    validate_error(
        api.failover_live_reservation(target["id"], DELIVERY_ENGINEER),
        err.ERR_RESERVATION_STATE_INVALID,
        409,
    )

    assert_money(
        fx.read_vendor(api, alpha["id"])["reserved_gbps"], 10.00, "ALPHA.reserved_gbps"
    )
    assert_money(
        fx.read_vendor(api, bravo["id"])["reserved_gbps"], 60.00, "BRAVO.reserved_gbps"
    )
    assert fx.read_reservation(api, blocking["id"])["state"] == "RESERVED"


def _hdcp_floor_versus_region_world(api):
    """A title with no licensing window at all, owning a 2160p-peaking DRAFT
    ladder and a `PENDING` package whose derived `hdcp_floor` is `TYPE_1`."""
    fx.create_device_profile(api)
    title = fx.create_title(
        api,
        external_ref="TTL-SAFETY-01",
        title_name="Protection Floor Subject",
        studio_code="NOVAPIC",
    )
    ladder = fx.create_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[
            f.rung("1080p", 1080, 5000),
            f.rung("2160p", 2160, 12000),
        ],
    )
    package = fx.create_package(
        api,
        title["id"],
        ladder["id"],
        drm_systems=["WIDEVINE"],
        license_server_url="https://lic.novapic.example/v1",
        persistent_license_allowed=False,
    )
    return title, ladder, package


def _fr_rule_payload(hdcp_level):
    return f.entitlement_rule_payload(
        region_code="FR",
        subscription_tier="PREMIUM",
        device_class_scope="ALL",
        max_concurrent_streams=1,
        max_playback_height_px=1080,
        hdcp_level=hdcp_level,
        offline_playback_allowed=False,
        priority=10,
    )


def test_entitlement_rule_reports_the_hdcp_floor_before_the_unlicensed_region(api):
    """A `NONE` rule for an unlicensed region under a `TYPE_1` floor reports 422 ERR_HDCP_FLOOR_VIOLATION.

    PRD §2.6: "An entitlement rule's `hdcp_level` is at or above its package's
    `hdcp_floor` under the ordering where `NONE` is lowest, `TYPE_0` is next and
    `TYPE_1` is highest, failing with `ERR_HDCP_FLOOR_VIOLATION`; a rule may not
    set `offline_playback_allowed` to true when its package's
    `persistent_license_allowed` is false, failing with
    `ERR_OFFLINE_NOT_LICENSED`; and a package's `drm_systems` must carry at least
    one system and must include `WIDEVINE` whenever its `hdcp_floor` is
    `TYPE_1`, failing with `ERR_DRM_SYSTEM_UNSUPPORTED`."

    PRD §3.5: "The package's `hdcp_floor` is derived, not supplied: it reads
    `TYPE_1` when the bound ladder's `peak_height_px` is 2160 or greater,
    `TYPE_0` when that height is 1080 or greater but below 2160, and `NONE`
    otherwise."

    Design: Difficulty/priority_pair_validation_conflict/entitlement_rule_safety_beats_referential
    """
    _title, _ladder, package = _hdcp_floor_versus_region_world(api)
    assert fx.read_package(api, package["id"])["hdcp_floor"] == "TYPE_1"

    response = api.create_entitlement_rule(
        package["id"], _fr_rule_payload("NONE"), DRM_OPERATOR
    )

    validate_error(response, err.ERR_HDCP_FLOOR_VIOLATION, 422)
    assert response.json()["data"]["error_id"] != err.ERR_RULE_REGION_NOT_LICENSED


def test_entitlement_rule_with_a_repaired_hdcp_level_then_reports_the_unlicensed_region(api):
    """Raising `hdcp_level` to `TYPE_1` surfaces the later rung: 422 ERR_RULE_REGION_NOT_LICENSED.

    PRD §3.5: "And a concrete `region_code` must be a region the title is
    actually licensed in — that is, a region covered by at least one of the
    title's licensing windows in `SCHEDULED` or `ACTIVE` — otherwise
    `ERR_RULE_REGION_NOT_LICENSED`; the wildcard is exempt from that check."

    Design: Difficulty/priority_pair_validation_conflict/entitlement_rule_safety_beats_referential
    """
    _title, _ladder, package = _hdcp_floor_versus_region_world(api)

    validate_error(
        api.create_entitlement_rule(package["id"], _fr_rule_payload("NONE"), DRM_OPERATOR),
        err.ERR_HDCP_FLOOR_VIOLATION,
        422,
    )

    repaired = api.create_entitlement_rule(
        package["id"], _fr_rule_payload("TYPE_1"), DRM_OPERATOR
    )

    validate_error(repaired, err.ERR_RULE_REGION_NOT_LICENSED, 422)


def test_neither_rejected_entitlement_rule_is_persisted_on_the_package(api):
    """`entitlement_rule_count` still reads 0 after both refusals.

    PRD §3.5: "A successful attachment increments the package's
    `entitlement_rule_count` by one."

    Design: Difficulty/priority_pair_validation_conflict/entitlement_rule_safety_beats_referential
    """
    _title, _ladder, package = _hdcp_floor_versus_region_world(api)

    validate_error(
        api.create_entitlement_rule(package["id"], _fr_rule_payload("NONE"), DRM_OPERATOR),
        err.ERR_HDCP_FLOOR_VIOLATION,
        422,
    )
    validate_error(
        api.create_entitlement_rule(package["id"], _fr_rule_payload("TYPE_1"), DRM_OPERATOR),
        err.ERR_RULE_REGION_NOT_LICENSED,
        422,
    )

    stored = fx.read_package(api, package["id"])
    assert stored["entitlement_rule_count"] == 0, stored
    assert stored["state"] == "PENDING", stored


def _capacity_boundary_world(api):
    """Vendor ALPHA committed to 80.00 Gbps with 20.00 already held over
    2026-09-10T00:00:00Z..04:00:00Z at the default 15-minute buffer."""
    alpha = fx.create_vendor(
        api, vendor_code="ALPHA", regions=["US"], committed_gbps=80.00, cost_per_gb_usd=0.0250
    )
    title = fx.create_live_event_title(
        api,
        external_ref="TTL-BOUND-01",
        title_name="Capacity Boundary Event",
        studio_code="NOVASPORT",
    )
    fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-11-01T00:00:00Z",
        license_tier="STANDARD",
    )
    first = fx.create_reservation(
        api,
        title["id"],
        alpha["id"],
        window_start_at="2026-09-10T00:00:00Z",
        window_end_at="2026-09-10T04:00:00Z",
        reserved_gbps=20.00,
    )
    return alpha, title, first


def _boundary_reservation_payload(title_id, vendor_id, reserved_gbps):
    return f.live_reservation_payload(
        title_id,
        vendor_id,
        window_start_at="2026-09-10T00:00:00Z",
        window_end_at="2026-09-10T04:00:00Z",
        reserved_gbps=reserved_gbps,
    )


def test_reservation_at_exactly_the_committed_ceiling_is_accepted(api):
    """20.00 already held plus a requested 60.00 exactly meets a committed 80.00.

    PRD §3.8: "The booking is accepted when that held figure plus the requested
    `reserved_gbps` is less than **or equal to** the vendor's `committed_gbps`,
    and refused with `ERR_VENDOR_CAPACITY_EXCEEDED` only when it strictly exceeds
    it: exact equality is a legal, fully-booked vendor, and one hundredth of a
    Gbps beyond equality is a rejection."

    Design: Difficulty/boundary_precision_check/vendor_capacity_equality_admits_reservation
    """
    alpha, title, _first = _capacity_boundary_world(api)

    created = validate_success(
        api.create_live_reservation(
            _boundary_reservation_payload(title["id"], alpha["id"], 60.00), DELIVERY_ENGINEER
        ),
        201,
    )

    assert_money(created["reserved_gbps"], 60.00, "LiveEventReservation.reserved_gbps")
    assert created["state"] == "RESERVED", created
    assert created["active_vendor_id"] == alpha["id"], created


def test_vendor_ledger_reads_the_full_committed_capacity_after_the_equality_booking(api):
    """ALPHA's derived ledger reads exactly 80.00 once both holds are counted.

    PRD §3.8: "A successful booking stores the reservation in `state` `RESERVED`
    with `active_vendor_id` set to `primary_vendor_id`, `failover_at` null and
    `released_gbps` 0.00, and immediately recomputes the primary vendor's
    `reserved_gbps`."

    Design: Difficulty/boundary_precision_check/vendor_capacity_equality_admits_reservation
    """
    alpha, title, _first = _capacity_boundary_world(api)

    validate_success(
        api.create_live_reservation(
            _boundary_reservation_payload(title["id"], alpha["id"], 60.00), DELIVERY_ENGINEER
        ),
        201,
    )

    assert_money(
        fx.read_vendor(api, alpha["id"])["reserved_gbps"], 80.00, "ALPHA.reserved_gbps"
    )


def test_one_hundredth_of_a_gbps_past_equality_is_refused(api):
    """A further 0.01 Gbps against a fully-booked vendor is 422 ERR_VENDOR_CAPACITY_EXCEEDED.

    PRD §2.6: "On the vendor being charged, the already-held bandwidth plus the
    requested `reserved_gbps` must not exceed that vendor's `committed_gbps`;
    equality is accepted."

    Design: Difficulty/boundary_precision_check/vendor_capacity_equality_admits_reservation
    """
    alpha, title, first = _capacity_boundary_world(api)
    validate_success(
        api.create_live_reservation(
            _boundary_reservation_payload(title["id"], alpha["id"], 60.00), DELIVERY_ENGINEER
        ),
        201,
    )

    response = api.create_live_reservation(
        _boundary_reservation_payload(title["id"], alpha["id"], 0.01), DELIVERY_ENGINEER
    )

    validate_error(response, err.ERR_VENDOR_CAPACITY_EXCEEDED, 422)
    assert_money(
        fx.read_vendor(api, alpha["id"])["reserved_gbps"], 80.00, "ALPHA.reserved_gbps"
    )
    assert fx.read_reservation(api, first["id"])["state"] == "RESERVED"


def _retired_matrix_world(api):
    """The only device profile in the system is `RETIRED`, so the `ACTIVE`
    candidate pool of the compatibility matrix is empty."""
    fx.create_device_profile(api, state="RETIRED")
    title = fx.create_title(
        api,
        external_ref="TTL-NODEV-01",
        title_name="Empty Device Pool Subject",
        studio_code="NOVAPIC",
    )
    ladder = fx.create_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[
            f.rung("720p", 720, 2500),
            f.rung("1080p", 1080, 5000),
        ],
    )
    return title, ladder


def test_validating_against_an_empty_active_pool_rejects_the_ladder(api):
    """The rejection is a recorded verdict: 200 OK with `REJECTED` and `NO_COMPATIBLE_DEVICE`.

    PRD §3.3: "The **rejecting arm** applies when at least one of the opposite
    conditions holds: the rungs are not strictly increasing, or two rungs share a
    `height_px`, or the computed score is exactly 0.00 — which is what an empty
    `ACTIVE` candidate pool always produces."

    PRD §3.3: "Scoring begins with the candidate set: every device profile whose
    `state` is `ACTIVE`."

    Design: Difficulty/boundary_precision_check/empty_active_device_pool_rejects_ladder
    """
    _title, ladder = _retired_matrix_world(api)

    validated = validate_success(
        api.validate_encoding_ladder(ladder["id"], ENCODING_ENGINEER), 200
    )

    assert validated["state"] == "REJECTED", validated
    assert validated["validation_reason_code"] == "NO_COMPATIBLE_DEVICE", validated


def test_rejected_ladder_scores_zero_and_counts_no_compatible_device(api):
    """`device_compat_score` reads exactly 0.00 and `compatible_device_count` 0.

    PRD §3.3: "Both figures are still written on this arm, and they read 0.00 and
    0 on the `NO_COMPATIBLE_DEVICE` branch."

    Design: Difficulty/boundary_precision_check/empty_active_device_pool_rejects_ladder
    """
    _title, ladder = _retired_matrix_world(api)

    fx.validate_ladder(api, ladder["id"])

    stored = fx.read_ladder(api, ladder["id"])
    assert_score(stored["device_compat_score"], 0.00, "EncodingLadder.device_compat_score")
    assert stored["compatible_device_count"] == 0, stored
    assert stored["state"] == "REJECTED", stored


def test_locking_a_rejected_ladder_is_refused_and_leaves_readiness_at_zero(api):
    """The terminal ladder answers 409 ERR_LADDER_STATE_INVALID and both readiness variants stay 0.00.

    PRD §3.4: "An `EncodingEngineer` may lock a ladder whose `state` is
    `VALIDATED`; a ladder that is `DRAFT`, already `LOCKED`, `REJECTED` or
    `SUPERSEDED` answers `ERR_LADDER_STATE_INVALID`, which also means a second
    lock of the same ladder is refused."

    PRD §3.1: "**Readiness scoring** is the catalog desk's headline number, and
    it exists in two variants that are recomputed together after *any* mutation
    of the title's masters, ladders or DRM packages."

    Design: Difficulty/boundary_precision_check/empty_active_device_pool_rejects_ladder
    """
    title, ladder = _retired_matrix_world(api)
    fx.validate_ladder(api, ladder["id"])

    validate_error(
        api.lock_encoding_ladder(ladder["id"], ENCODING_ENGINEER),
        err.ERR_LADDER_STATE_INVALID,
        409,
    )

    stored_title = fx.read_title(api, title["id"])
    assert stored_title["locked_ladder_count"] == 0, stored_title
    assert_score(
        stored_title["readiness_score_provisional"], 0.00, "Title.readiness_score_provisional"
    )
    assert_score(
        stored_title["readiness_score_certified"], 0.00, "Title.readiness_score_certified"
    )


def _arm_gate_world(api):
    """A live-event title with a `QC_PASSED` master, a `LOCKED` HEVC ladder, a
    licensed but still `PENDING` DRM package, a routable US policy and a
    `RESERVED` 10.00 Gbps hold on ALPHA."""
    fx.create_device_profile(api)
    alpha = fx.create_vendor(
        api, vendor_code="ALPHA", regions=["US"], committed_gbps=100.00, cost_per_gb_usd=0.0250
    )
    title = fx.create_live_event_title(
        api, external_ref="TTL-ARM-01", title_name="Arm Gate Event", studio_code="NOVASPORT"
    )
    fx.create_window(
        api,
        title["id"],
        region_code="US",
        window_start_at="2026-09-01T00:00:00Z",
        window_end_at="2026-11-01T00:00:00Z",
        license_tier="STANDARD",
    )
    fx.create_passed_asset(
        api,
        title["id"],
        source_uri="s3://mez/arm-01.mxf",
        duration_seconds=7200,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    ladder = fx.create_locked_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[
            f.rung("720p", 720, 2500),
            f.rung("1080p", 1080, 5000),
            f.rung("2160p", 2160, 12000),
        ],
    )
    package = fx.create_package(
        api,
        title["id"],
        ladder["id"],
        drm_systems=["WIDEVINE"],
        license_server_url="https://lic.novasport.example/v1",
        persistent_license_allowed=False,
    )
    fx.add_entitlement_rule(
        api,
        package["id"],
        region_code="US",
        subscription_tier="ANY",
        device_class_scope="ALL",
        max_concurrent_streams=2,
        max_playback_height_px=2160,
        hdcp_level="TYPE_1",
        offline_playback_allowed=False,
        priority=60,
    )
    policy = fx.create_policy(api, title["id"], region_code="US", steering_mode="PERFORMANCE")
    reservation = fx.create_reservation(
        api,
        title["id"],
        alpha["id"],
        window_start_at="2026-09-10T00:00:00Z",
        window_end_at="2026-09-10T04:00:00Z",
        reserved_gbps=10.00,
    )
    return alpha, title, package, policy, reservation


def test_arming_is_refused_while_the_titles_drm_package_is_still_pending(api):
    """The guard lives on another entity: 409 ERR_PACKAGE_NOT_READY, reservation still `RESERVED`.

    PRD §3.8: "The title must own at least one DRM package in `state` `PACKAGED`,
    otherwise `ERR_PACKAGE_NOT_READY` — a live event may not be armed against
    unprotected content."

    PRD §2.6: "Preconditions that live on a *different* entity than the one being
    mutated, failing with `ERR_NO_PASSED_ASSET`, `ERR_ASSET_REMEDIATION_PENDING`,
    `ERR_PACKAGE_NOT_READY`, `ERR_LADDER_NOT_LOCKED`, `ERR_LADDER_NOT_BINDABLE`
    or `ERR_TITLE_LEGALLY_BLOCKED` (all 409)."

    Design: Difficulty/cross_entity_state_dependency/live_arm_requires_packaged_drm
    """
    _alpha, _title, _package, _policy, reservation = _arm_gate_world(api)

    validate_error(
        api.arm_live_reservation(reservation["id"], DELIVERY_ENGINEER),
        err.ERR_PACKAGE_NOT_READY,
        409,
    )

    assert fx.read_reservation(api, reservation["id"])["state"] == "RESERVED"


def test_arming_succeeds_once_the_drm_package_reaches_packaged(api):
    """The identical arm request answers 200 with `ARMED` after the package is packaged.

    PRD §3.5: "A successful packaging sets the package's `state` to `PACKAGED`,
    sets `packaged_at` to the logical clock's current instant, clears
    `stale_reason` back to `NONE`, and re-derives `hdcp_floor` from the possibly
    rebound ladder's `peak_height_px`."

    PRD §3.5: "The title's `packaging_state` is then re-derived: from `PACKAGING`
    it becomes `PACKAGED` provided no package of the title remains `STALE`, and
    from `STALE` it becomes `PACKAGED` provided no *other* package of the title is
    still `STALE`."

    Design: Difficulty/cross_entity_state_dependency/live_arm_requires_packaged_drm
    """
    _alpha, title, package, _policy, reservation = _arm_gate_world(api)
    validate_error(
        api.arm_live_reservation(reservation["id"], DELIVERY_ENGINEER),
        err.ERR_PACKAGE_NOT_READY,
        409,
    )

    packaged = validate_success(api.package_drm_package(package["id"], DRM_OPERATOR), 200)
    assert packaged["state"] == "PACKAGED", packaged
    assert fx.read_title(api, title["id"])["packaging_state"] == "PACKAGED"

    armed = validate_success(
        api.arm_live_reservation(reservation["id"], DELIVERY_ENGINEER), 200
    )
    assert armed["state"] == "ARMED", armed


def test_arming_moves_no_capacity_and_leaves_the_policy_on_standby_only(api):
    """ALPHA still holds exactly 10.00 Gbps and the single-candidate policy stays `STANDBY_ONLY`.

    PRD §3.8: "A `DeliveryEngineer` arms a `RESERVED` reservation, which moves it
    to `ARMED` and increments its `version`; no capacity moves, because the hold
    already sits on the active vendor."

    PRD §3.7: "Assignment third: `primary_vendor_id` becomes the first-ranked
    candidate, `backup_vendor_id` becomes the second-ranked candidate when two or
    more candidates survive and is null otherwise, `state` becomes `ACTIVE` with
    two or more candidates and `STANDBY_ONLY` with exactly one, and
    `selection_reason_code` records which branch chose the primary —
    `PERFORMANCE_RANK`, `COST_RANK` or `WEIGHTED_RANK` according to the mode."

    Design: Difficulty/cross_entity_state_dependency/live_arm_requires_packaged_drm
    """
    alpha, _title, package, policy, reservation = _arm_gate_world(api)

    validate_error(
        api.arm_live_reservation(reservation["id"], DELIVERY_ENGINEER),
        err.ERR_PACKAGE_NOT_READY,
        409,
    )
    assert_money(
        fx.read_vendor(api, alpha["id"])["reserved_gbps"], 10.00, "ALPHA.reserved_gbps"
    )

    fx.package_package(api, package["id"])
    fx.arm_reservation(api, reservation["id"])

    armed = fx.read_reservation(api, reservation["id"])
    assert armed["state"] == "ARMED", armed
    assert armed["active_vendor_id"] == alpha["id"], armed
    assert_money(
        fx.read_vendor(api, alpha["id"])["reserved_gbps"], 10.00, "ALPHA.reserved_gbps"
    )
    assert fx.read_policy(api, policy["id"])["state"] == "STANDBY_ONLY"


def _remediation_gate_world(api):
    """A title owning a `QC_PASSED` master A1, a sibling master A2 sitting in
    `REMEDIATION_REQUESTED` after one failing run, and one `VALIDATED` ladder."""
    fx.create_device_profile(api)
    title = fx.create_title(
        api,
        external_ref="TTL-GATE-01",
        title_name="Lock Gate Subject",
        studio_code="NOVAPIC",
    )
    first = fx.create_passed_asset(
        api,
        title["id"],
        source_uri="s3://mez/gate-01-a1.mxf",
        duration_seconds=7200,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=0,
        caption_languages=["en"],
        audio_language="en",
    )
    second = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/gate-01-a2-v1.mxf",
        duration_seconds=7200,
        frame_rate=24.0,
        peak_audio_lufs=-24.0,
        artifact_defect_count=9,
        caption_languages=[],
        audio_language="en",
    )
    fx.run_qc(api, second["id"])
    fx.request_remediation(api, second["id"])
    ladder = fx.create_ladder(
        api,
        title["id"],
        codec_family="HEVC",
        rungs=[
            f.rung("720p", 720, 2500),
            f.rung("1080p", 1080, 5000),
        ],
    )
    fx.validate_ladder(api, ladder["id"])
    return title, first, second, ladder


def _repair_second_asset(api, asset_id):
    fx.resubmit_asset(
        api,
        asset_id,
        source_uri="s3://mez/gate-01-a2-v2.mxf",
        artifact_defect_count=0,
        caption_languages=["en"],
        peak_audio_lufs=None,
    )
    fx.run_qc(api, asset_id)


def test_lock_is_refused_for_the_sibling_asset_awaiting_remediation(api):
    """409 ERR_ASSET_REMEDIATION_PENDING, not ERR_NO_PASSED_ASSET, even though A1 passed.

    PRD §3.4: "Two cross-entity guards then apply, both drawn from the
    quality-control desk's work rather than the encoding desk's: the title must
    own at least one master whose `qc_state` is `QC_PASSED`, otherwise
    `ERR_NO_PASSED_ASSET`, and no master of the title may sit in
    `REMEDIATION_REQUESTED`, otherwise `ERR_ASSET_REMEDIATION_PENDING` — the
    second holds even when another master has already passed."

    Design: Difficulty/cross_entity_state_dependency/ladder_lock_requires_passed_asset
    """
    title, _first, _second, ladder = _remediation_gate_world(api)

    response = api.lock_encoding_ladder(ladder["id"], ENCODING_ENGINEER)

    validate_error(response, err.ERR_ASSET_REMEDIATION_PENDING, 409)
    assert response.json()["data"]["error_id"] != err.ERR_NO_PASSED_ASSET
    assert fx.read_ladder(api, ladder["id"])["state"] == "VALIDATED"
    assert fx.read_title(api, title["id"])["locked_ladder_count"] == 0


def test_remediated_asset_returns_to_qc_passed_on_its_second_attempt(api):
    """The resubmitted master passes on attempt 2 -- its attempt count is never reset.

    PRD §3.2: "Crucially, `qc_attempt_count` is **not** reset, so the loop
    `INGESTED` → `QC_FAILED` → `REMEDIATION_REQUESTED` → `INGESTED` can be walked
    at most twice: the third failing verdict is terminal no matter how many
    resubmissions preceded it."

    Design: Difficulty/cross_entity_state_dependency/ladder_lock_requires_passed_asset
    """
    _title, _first, second, ladder = _remediation_gate_world(api)
    validate_error(
        api.lock_encoding_ladder(ladder["id"], ENCODING_ENGINEER),
        err.ERR_ASSET_REMEDIATION_PENDING,
        409,
    )

    _repair_second_asset(api, second["id"])

    repaired = fx.read_asset(api, second["id"])
    assert repaired["qc_state"] == "QC_PASSED", repaired
    assert repaired["qc_attempt_count"] == 2, repaired


def test_lock_succeeds_after_the_remediated_asset_passes(api):
    """The identical lock answers 200, `locked_ladder_count` reads 1 and both readiness variants read 70.00.

    PRD §3.4: "The ladder moves from `VALIDATED` to `LOCKED`, the title's
    `locked_ladder_count` is recomputed as the number of that title's ladders in
    `LOCKED`, and the title's `version` increments by one."

    PRD §3.1: "Both variants blend three components with fixed weights: the
    source-master component contributes half the score, the ladder component
    contributes one fifth, and the DRM-package component contributes the
    remaining three tenths."

    Design: Difficulty/cross_entity_state_dependency/ladder_lock_requires_passed_asset
    """
    title, _first, second, ladder = _remediation_gate_world(api)
    validate_error(
        api.lock_encoding_ladder(ladder["id"], ENCODING_ENGINEER),
        err.ERR_ASSET_REMEDIATION_PENDING,
        409,
    )
    _repair_second_asset(api, second["id"])

    locked = validate_success(
        api.lock_encoding_ladder(ladder["id"], ENCODING_ENGINEER), 200
    )

    assert locked["state"] == "LOCKED", locked
    stored_title = fx.read_title(api, title["id"])
    assert stored_title["locked_ladder_count"] == 1, stored_title
    assert_score(
        stored_title["readiness_score_certified"], 70.00, "Title.readiness_score_certified"
    )
    assert_score(
        stored_title["readiness_score_provisional"], 70.00, "Title.readiness_score_provisional"
    )
