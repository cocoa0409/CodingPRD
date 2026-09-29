"""State-machine breadth: initial states, refused transitions, terminal states,
sweep idempotency and the cross-entity side effects of PRD §2.5, §3.2 - §3.9.

Every test in this module starts from an empty database with the logical clock
reading `2026-08-01T00:00:00Z` (PRD §2.5) and drives one entity family through
the transitions the PRD declares for it, asserting both the state that was
reached and the state that was refused.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_instant_equals,
    assert_money,
    assert_money_list,
    assert_ratio_4dp,
    assert_score,
    assert_sweep_counters,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import INITIAL_CLOCK
from test_helpers.test_users import (
    CONTENT_OPS,
    DELIVERY_ENGINEER,
    DRM_OPERATOR,
    ENCODING_ENGINEER,
    PLATFORM_ADMIN,
    QC_ANALYST,
)


# ---------------------------------------------------------------------------
# Declared initial states
# ---------------------------------------------------------------------------


def test_new_master_and_ladder_start_in_their_declared_initial_states(api):
    """A freshly registered master is `INGESTED` and a freshly authored ladder is `DRAFT`.

    PRD §3.1: "Every new master is stored with `qc_state` of `INGESTED`,
    `qc_attempt_count` of 0, `latest_severity_index` of 0.00 and
    `blocking_defect_code` of `NONE`."

    PRD §3.3: "A newly authored ladder is stored in `state` `DRAFT` with
    `rung_count` set to the number of elements in `rungs`, `peak_bitrate_kbps`
    set to the largest `bitrate_kbps` across the rungs and `peak_height_px` set
    to the largest `height_px`."

    Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_state
    """
    fx.create_device_profile(api)
    title = fx.create_title(
        api, external_ref="TTL-INIT-20", title_name="Initial State Cut"
    )

    asset = validate_success(
        api.create_mezzanine_asset(
            f.mezzanine_asset_payload(title["id"], source_uri="s3://mez/init-20.mxf"),
            CONTENT_OPS,
        ),
        201,
    )
    assert asset["qc_state"] == "INGESTED"
    assert asset["qc_attempt_count"] == 0
    assert asset["blocking_defect_code"] == "NONE"
    assert_score(
        asset["latest_severity_index"], 0.00, "MezzanineAsset.latest_severity_index"
    )

    version = fx.title_version(api, title["id"])
    ladder = validate_success(
        api.create_encoding_ladder(
            f.encoding_ladder_payload(title["id"], version, codec_family="H264"),
            ENCODING_ENGINEER,
        ),
        201,
    )
    assert ladder["state"] == "DRAFT"
    assert ladder["rung_count"] == 2
    assert ladder["peak_bitrate_kbps"] == 2500
    assert ladder["peak_height_px"] == 720
    assert ladder["validation_reason_code"] == "NONE"
    assert ladder["compatible_device_count"] == 0
    assert_score(
        ladder["device_compat_score"], 0.00, "EncodingLadder.device_compat_score"
    )


def test_new_package_is_pending_and_new_vendor_is_active_with_seeded_health(api):
    """A new DRM package is `PENDING` and a new CDN vendor is `ACTIVE` with health 100.00.

    PRD §3.5: "On creation the package's `state` is `PENDING`, its `stale_reason`
    is `NONE`, its `entitlement_rule_count` is 0 and its `packaged_at` is null."

    PRD §3.7: "A new vendor's `state` is `ACTIVE`, its `reserved_gbps` is 0.00,
    its `breach_window_count` is 0, and **both** health figures —
    `health_score_rolling` and `health_score_contract` — are seeded at 100.00,
    which is the value the health calculation yields when no measurement rows
    exist yet."

    Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_state
    """
    fx.create_device_profile(api)
    title = fx.create_title(
        api, external_ref="TTL-INIT-20", title_name="Initial State Cut"
    )
    fx.create_asset(api, title["id"], source_uri="s3://mez/init-20.mxf")
    ladder = fx.create_ladder(api, title["id"], codec_family="H264")

    package = validate_success(
        api.create_drm_package(
            f.drm_package_payload(title["id"], ladder["id"]), DRM_OPERATOR
        ),
        201,
    )
    assert package["state"] == "PENDING"
    assert package["stale_reason"] == "NONE"
    assert package["entitlement_rule_count"] == 0
    assert package["packaged_at"] is None

    vendor = validate_success(
        api.create_cdn_vendor(
            f.cdn_vendor_payload(vendor_code="ALPHA", regions=["US"]), PLATFORM_ADMIN
        ),
        201,
    )
    assert vendor["state"] == "ACTIVE"
    assert_money(vendor["reserved_gbps"], 0.00, "CdnVendor.reserved_gbps")
    assert vendor["breach_window_count"] == 0
    assert_score(vendor["health_score_rolling"], 100.00, "health_score_rolling")
    assert_score(vendor["health_score_contract"], 100.00, "health_score_contract")


def test_first_window_is_scheduled_and_advances_the_title_dimension_only(api):
    """The first window is stored `SCHEDULED` and moves the title `DRAFT` -> `SCHEDULED`.

    PRD §3.6: "A new window is stored in `state` `SCHEDULED` with `activated_at`
    and `closed_at` both null."

    PRD §3.6: "Scheduling the **first** window of a title that is still in
    `DRAFT` also advances the title's `availability_state` from `DRAFT` to
    `SCHEDULED` and increments the title's `version` by one; windows added while
    the title is already `SCHEDULED`, `PUBLISHED` or `TAKEN_DOWN` leave
    `availability_state` exactly as it was."

    Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_state
    """
    fx.create_device_profile(api)
    title = fx.create_title(
        api, external_ref="TTL-INIT-20", title_name="Initial State Cut"
    )
    fx.create_asset(api, title["id"], source_uri="s3://mez/init-20.mxf")
    ladder = fx.create_ladder(api, title["id"], codec_family="H264")
    fx.create_package(api, title["id"], ladder["id"])

    window = validate_success(
        api.create_availability_window(
            title["id"],
            f.availability_window_payload(
                window_start_at="2026-08-15T00:00:00Z",
                window_end_at="2026-09-15T00:00:00Z",
            ),
            CONTENT_OPS,
        ),
        201,
    )
    assert window["state"] == "SCHEDULED"
    assert window["activated_at"] is None
    assert window["closed_at"] is None

    title_after = fx.read_title(api, title["id"])
    assert title_after["availability_state"] == "SCHEDULED"
    assert title_after["packaging_state"] == "UNPACKAGED"
    assert title_after["takedown_reason"] == "NONE"
    assert title_after["locked_ladder_count"] == 0


# ---------------------------------------------------------------------------
# Refused transitions on the source-master machine (§3.2)
# ---------------------------------------------------------------------------


def test_second_qc_run_against_a_passed_master_is_refused(api):
    """QC is only available from `INGESTED`, so a `QC_PASSED` master refuses a second run.

    PRD §3.2: "A `QcAnalyst` runs quality control against a master whose
    `qc_state` is `INGESTED`; attempting it against any other state — including
    anything at all against the terminal `QC_REJECTED` — is refused with
    `ERR_ASSET_STATE_INVALID`."

    PRD §3.2: "The per-attempt evidence is only observable through a master's
    report list, which returns its reports ordered by `attempt_number`
    ascending."

    Design: Corner/state_machines/invalid_asset_transitions_rejected
    """
    title = fx.create_title(api, external_ref="TTL-QCX-21", title_name="Refusal Cut")
    passed = fx.create_passed_asset(api, title["id"], source_uri="s3://mez/qcx-a.mxf")
    assert passed["qc_state"] == "QC_PASSED"

    validate_error(api.run_qc(passed["id"], QC_ANALYST), err.ERR_ASSET_STATE_INVALID)

    after = fx.read_asset(api, passed["id"])
    assert after["qc_state"] == "QC_PASSED"
    assert after["qc_attempt_count"] == 1

    rows, meta = validate_paginated(api.list_qc_reports(passed["id"], QC_ANALYST))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["attempt_number"] == 1


def test_remediation_request_against_an_ingested_master_is_refused(api):
    """Remediation is only reachable from `QC_FAILED`, so an `INGESTED` master refuses it.

    PRD §3.2: "A `QcAnalyst` requests remediation of a master whose `qc_state`
    is `QC_FAILED`, moving it to `REMEDIATION_REQUESTED` and incrementing the
    master's `version`; requesting remediation of a master in any other state is
    `ERR_ASSET_STATE_INVALID`."

    Design: Corner/state_machines/invalid_asset_transitions_rejected
    """
    title = fx.create_title(api, external_ref="TTL-QCX-21", title_name="Refusal Cut")
    fx.create_passed_asset(api, title["id"], source_uri="s3://mez/qcx-a.mxf")
    fresh = fx.create_asset(api, title["id"], source_uri="s3://mez/qcx-b.mxf")
    assert fresh["qc_state"] == "INGESTED"

    validate_error(
        api.request_remediation(fresh["id"], QC_ANALYST), err.ERR_ASSET_STATE_INVALID
    )

    after = fx.read_asset(api, fresh["id"])
    assert after["qc_state"] == "INGESTED"
    assert after["qc_attempt_count"] == 0


def test_resubmission_of_an_ingested_master_is_refused(api):
    """Resubmission requires `REMEDIATION_REQUESTED`, so an `INGESTED` master refuses it.

    PRD §3.2: "Then a `ContentOps` operator resubmits the corrected master,
    which requires `qc_state` of `REMEDIATION_REQUESTED` and `qc_attempt_count`
    below 3, and which accepts corrected values for `source_uri`,
    `peak_audio_lufs`, `artifact_defect_count` and `caption_languages`; any of
    those four that is omitted keeps its current value."

    Design: Corner/state_machines/invalid_asset_transitions_rejected
    """
    title = fx.create_title(api, external_ref="TTL-QCX-21", title_name="Refusal Cut")
    fresh = fx.create_asset(api, title["id"], source_uri="s3://mez/qcx-b.mxf")

    validate_error(
        api.resubmit_mezzanine_asset(
            fresh["id"],
            f.resubmit_payload(source_uri="s3://mez/qcx-b-fixed.mxf"),
            CONTENT_OPS,
        ),
        err.ERR_ASSET_STATE_INVALID,
    )

    after = fx.read_asset(api, fresh["id"])
    assert after["qc_state"] == "INGESTED"
    assert after["qc_attempt_count"] == 0
    assert after["source_uri"] == "s3://mez/qcx-b.mxf"


# ---------------------------------------------------------------------------
# Refused transitions on the ladder and package machines (§3.3, §3.5)
# ---------------------------------------------------------------------------


def test_locking_a_draft_ladder_is_refused_before_any_cross_entity_guard(api):
    """A `DRAFT` ladder cannot be locked: locking is reachable only from `VALIDATED`.

    PRD §3.4: "An `EncodingEngineer` may lock a ladder whose `state` is
    `VALIDATED`; a ladder that is `DRAFT`, already `LOCKED`, `REJECTED` or
    `SUPERSEDED` answers `ERR_LADDER_STATE_INVALID`, which also means a second
    lock of the same ladder is refused."

    Design: Corner/state_machines/invalid_ladder_and_package_transitions_rejected
    """
    fx.create_device_profile(api)
    title = fx.create_title(
        api, external_ref="TTL-LDX-22", title_name="Ladder Refusal Cut"
    )
    fx.create_passed_asset(api, title["id"])
    draft = fx.create_ladder(api, title["id"], codec_family="H264")
    validated = fx.create_ladder(api, title["id"], codec_family="HEVC")
    fx.validate_ladder(api, validated["id"])

    validate_error(
        api.lock_encoding_ladder(draft["id"], ENCODING_ENGINEER),
        err.ERR_LADDER_STATE_INVALID,
    )

    assert fx.read_ladder(api, draft["id"])["state"] == "DRAFT"
    assert fx.read_title(api, title["id"])["locked_ladder_count"] == 0


def test_revalidating_a_validated_ladder_is_refused_and_leaves_its_score(api):
    """Validation is only available from `DRAFT`, so a `VALIDATED` ladder refuses it.

    PRD §3.3: "**Validation** is the ladder's proving step, available to an
    `EncodingEngineer` while the ladder's `state` is `DRAFT`; any other state
    answers `ERR_LADDER_STATE_INVALID`."

    PRD §3.3: "The base figure is the sum of `market_share_pct` across all
    compatible profiles, multiplied by that coverage multiplier, and only then
    rounded half up to two decimals."

    Design: Corner/state_machines/invalid_ladder_and_package_transitions_rejected
    """
    fx.create_device_profile(api)
    title = fx.create_title(
        api, external_ref="TTL-LDX-22", title_name="Ladder Refusal Cut"
    )
    fx.create_passed_asset(api, title["id"])
    fx.create_ladder(api, title["id"], codec_family="H264")
    validated = fx.create_ladder(api, title["id"], codec_family="HEVC")
    scored = fx.validate_ladder(api, validated["id"])
    assert scored["state"] == "VALIDATED"

    validate_error(
        api.validate_encoding_ladder(validated["id"], ENCODING_ENGINEER),
        err.ERR_LADDER_STATE_INVALID,
    )

    after = fx.read_ladder(api, validated["id"])
    assert after["state"] == "VALIDATED"
    assert after["validation_reason_code"] == "OK"
    assert after["compatible_device_count"] == 1
    assert_score(
        after["device_compat_score"], 18.00, "EncodingLadder.device_compat_score"
    )


def test_revoked_package_is_terminal_and_refuses_a_second_revocation(api):
    """`REVOKED` is terminal: the second revocation of the same package is refused.

    PRD §3.5: "The reverse operation is **revocation**, available from `PENDING`,
    `PACKAGED` or `STALE` into the terminal `REVOKED`; revoking an
    already-`REVOKED` package is `ERR_PACKAGE_STATE_INVALID`."

    Design: Corner/state_machines/invalid_ladder_and_package_transitions_rejected
    """
    fx.create_device_profile(api)
    title = fx.create_title(
        api, external_ref="TTL-LDX-22", title_name="Ladder Refusal Cut"
    )
    fx.create_passed_asset(api, title["id"])
    fx.create_ladder(api, title["id"], codec_family="H264")
    validated = fx.create_ladder(api, title["id"], codec_family="HEVC")
    fx.validate_ladder(api, validated["id"])
    package = fx.create_package(api, title["id"], validated["id"])
    revoked = fx.revoke_package(api, package["id"])
    assert revoked["state"] == "REVOKED"

    validate_error(
        api.revoke_drm_package(package["id"], DRM_OPERATOR),
        err.ERR_PACKAGE_STATE_INVALID,
    )

    assert fx.read_package(api, package["id"])["state"] == "REVOKED"
    title_after = fx.read_title(api, title["id"])
    assert title_after["packaging_state"] == "UNPACKAGED"
    assert title_after["locked_ladder_count"] == 0


# ---------------------------------------------------------------------------
# Terminal states (§3.2, §3.3, §3.6)
# ---------------------------------------------------------------------------


def test_third_failing_verdict_drives_the_master_to_terminal_qc_rejected(api):
    """Two remediation loops then a third `FAIL` lands the master in `QC_REJECTED`.

    PRD §3.2: "A `FAIL` on the third attempt — that is, with `qc_attempt_count`
    standing at exactly 2 before the run — instead drives the master from
    `INGESTED` straight to the terminal `QC_REJECTED`: the report is written with
    `attempt_number` of 3, `qc_attempt_count` becomes 3, and
    `readiness_score_provisional` is recomputed because a rejected master leaves
    the optimistic numerator too."

    PRD §3.2: "Crucially, `qc_attempt_count` is **not** reset, so the loop
    `INGESTED` → `QC_FAILED` → `REMEDIATION_REQUESTED` → `INGESTED` can be
    walked at most twice: the third failing verdict is terminal no matter how
    many resubmissions preceded it."

    PRD §3.2: "The `artifact_penalty` is the `artifact_defect_count` multiplied
    by 4.0, rounded half up to two decimals."

    Design: Corner/state_machines/qc_rejected_asset_is_terminal
    """
    title = fx.create_title(api, external_ref="TTL-QCR-23", title_name="Rejected Cut")
    asset = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/qcr-23.mxf",
        artifact_defect_count=8,
    )

    first = fx.run_qc(api, asset["id"])
    assert first["attempt_number"] == 1
    assert first["verdict"] == "FAIL"
    assert fx.read_asset(api, asset["id"])["qc_state"] == "QC_FAILED"

    fx.request_remediation(api, asset["id"])
    fx.resubmit_asset(
        api,
        asset["id"],
        source_uri="s3://mez/qcr-23-v2.mxf",
        artifact_defect_count=8,
    )
    second = fx.run_qc(api, asset["id"])
    assert second["attempt_number"] == 2
    assert second["verdict"] == "FAIL"

    fx.request_remediation(api, asset["id"])
    fx.resubmit_asset(
        api,
        asset["id"],
        source_uri="s3://mez/qcr-23-v3.mxf",
        artifact_defect_count=8,
    )
    third = validate_success(api.run_qc(asset["id"], QC_ANALYST), 201)
    assert third["attempt_number"] == 3
    assert third["verdict"] == "FAIL"
    assert third["blocking_defect_code"] == "ARTIFACT_BURST"
    assert_score(third["severity_index"], 32.00, "QcReport.severity_index")
    assert_score(third["artifact_penalty"], 32.00, "QcReport.artifact_penalty")

    rejected = fx.read_asset(api, asset["id"])
    assert rejected["qc_state"] == "QC_REJECTED"
    assert rejected["qc_attempt_count"] == 3
    assert rejected["blocking_defect_code"] == "ARTIFACT_BURST"
    assert_score(rejected["latest_severity_index"], 32.00, "latest_severity_index")

    rows, meta = validate_paginated(api.list_qc_reports(asset["id"], QC_ANALYST))
    assert meta["total_count"] == 3
    assert [row["attempt_number"] for row in rows] == [1, 2, 3]

    title_after = fx.read_title(api, title["id"])
    assert_score(
        title_after["readiness_score_provisional"], 0.00, "readiness_score_provisional"
    )
    assert_score(
        title_after["readiness_score_certified"], 0.00, "readiness_score_certified"
    )


def test_qc_rejected_master_refuses_every_further_transition(api):
    """Nothing at all is accepted against a `QC_REJECTED` master.

    PRD §3.2: "A `QcAnalyst` runs quality control against a master whose
    `qc_state` is `INGESTED`; attempting it against any other state — including
    anything at all against the terminal `QC_REJECTED` — is refused with
    `ERR_ASSET_STATE_INVALID`."

    Design: Corner/state_machines/qc_rejected_asset_is_terminal
    """
    title = fx.create_title(api, external_ref="TTL-QCR-23", title_name="Rejected Cut")
    asset = fx.create_asset(
        api,
        title["id"],
        source_uri="s3://mez/qcr-23.mxf",
        artifact_defect_count=8,
    )
    for attempt in range(2):
        fx.run_qc(api, asset["id"])
        fx.request_remediation(api, asset["id"])
        fx.resubmit_asset(
            api,
            asset["id"],
            source_uri="s3://mez/qcr-23-v%d.mxf" % (attempt + 2),
            artifact_defect_count=8,
        )
    fx.run_qc(api, asset["id"])
    assert fx.read_asset(api, asset["id"])["qc_state"] == "QC_REJECTED"

    validate_error(api.run_qc(asset["id"], QC_ANALYST), err.ERR_ASSET_STATE_INVALID)
    validate_error(
        api.request_remediation(asset["id"], QC_ANALYST), err.ERR_ASSET_STATE_INVALID
    )
    validate_error(
        api.resubmit_mezzanine_asset(
            asset["id"], f.resubmit_payload(artifact_defect_count=0), CONTENT_OPS
        ),
        err.ERR_ASSET_STATE_INVALID,
    )

    after = fx.read_asset(api, asset["id"])
    assert after["qc_state"] == "QC_REJECTED"
    assert after["qc_attempt_count"] == 3
    assert after["artifact_defect_count"] == 8


def test_rejecting_validation_arm_answers_200_and_is_never_lockable(api):
    """A non-monotonic ladder is rejected as a verdict, and `REJECTED` refuses both calls.

    PRD §3.3: "Its `validation_reason_code` diagnoses the arm in a fixed
    precedence: `BITRATE_NOT_MONOTONIC` is checked first, then
    `DUPLICATE_HEIGHT`, and `NO_COMPATIBLE_DEVICE` last, so a ladder that is both
    non-monotonic and unservable reports the monotonicity problem."

    PRD §3.3: "The ladder moves from `DRAFT` to the terminal `REJECTED` and can
    never be locked."

    Design: Corner/state_machines/rejected_ladder_and_cancelled_window_are_terminal
    """
    fx.create_device_profile(api)
    title = fx.create_title(api, external_ref="TTL-TRM-24", title_name="Terminal Cut")
    ladder = fx.create_ladder(
        api,
        title["id"],
        codec_family="H264",
        rungs=[f.rung("480p", 480, 2500), f.rung("720p", 720, 1200)],
    )

    verdict = validate_success(
        api.validate_encoding_ladder(ladder["id"], ENCODING_ENGINEER), 200
    )
    assert verdict["state"] == "REJECTED"
    assert verdict["validation_reason_code"] == "BITRATE_NOT_MONOTONIC"

    validate_error(
        api.validate_encoding_ladder(ladder["id"], ENCODING_ENGINEER),
        err.ERR_LADDER_STATE_INVALID,
    )
    validate_error(
        api.lock_encoding_ladder(ladder["id"], ENCODING_ENGINEER),
        err.ERR_LADDER_STATE_INVALID,
    )

    assert fx.read_ladder(api, ladder["id"])["state"] == "REJECTED"
    assert fx.read_title(api, title["id"])["locked_ladder_count"] == 0


def test_cancelled_window_is_terminal_and_refuses_a_second_cancellation(api):
    """A `CANCELLED` window is terminal, and the title's dimension is untouched.

    PRD §3.6: "`ContentOps` can cancel a window whose `state` is `SCHEDULED` or
    `ACTIVE`; a window already `CLOSED` or `CANCELLED` answers
    `ERR_WINDOW_STATE_INVALID`."

    Design: Corner/state_machines/rejected_ladder_and_cancelled_window_are_terminal
    """
    fx.create_device_profile(api)
    title = fx.create_title(api, external_ref="TTL-TRM-24", title_name="Terminal Cut")
    window = fx.create_window(
        api,
        title["id"],
        window_start_at="2026-08-10T00:00:00Z",
        window_end_at="2026-09-10T00:00:00Z",
    )
    cancelled = fx.cancel_window(api, window["id"])
    assert cancelled["state"] == "CANCELLED"

    validate_error(
        api.cancel_availability_window(window["id"], CONTENT_OPS),
        err.ERR_WINDOW_STATE_INVALID,
    )

    assert fx.read_title(api, title["id"])["availability_state"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# The availability sweep (§2.5, §3.6)
# ---------------------------------------------------------------------------


def _read_window(api, title_id: str, window_id: str) -> dict:
    """Read one licensing window back through the title's window list (§4)."""
    rows, _meta = validate_paginated(
        api.list_availability_windows(title_id, CONTENT_OPS)
    )
    matches = [row for row in rows if row["id"] == window_id]
    assert matches, "window %s is missing from the title's window list" % window_id
    return matches[0]


def test_first_sweep_activates_the_window_and_publishes_the_title(api):
    """One sweep at the clock's start instant activates one window and publishes one title.

    PRD §2.5: "Each `AvailabilityWindow` in `SCHEDULED` whose `window_start_at`
    is at or before now, and whose `window_end_at` is strictly after now, becomes
    `ACTIVE` with `activated_at` set to the clock's current instant."

    PRD §3.6: "A title in `SCHEDULED` moves to `PUBLISHED` when at least one of
    its windows is `ACTIVE` after Phase 1, its `packaging_state` is `PACKAGED`
    after Phase 3, and its `readiness_score_certified` is at least 80.00."

    Design: Corner/state_machines/sweep_is_idempotent_for_a_fixed_clock
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-SWEEP-30"}
    )

    assert_sweep_counters(pipeline.sweep, windows_activated=1, titles_published=1)

    window = _read_window(api, pipeline.title_id, pipeline.window_id)
    assert window["state"] == "ACTIVE"
    assert_instant_equals(window["activated_at"], INITIAL_CLOCK)
    assert window["closed_at"] is None

    title = fx.read_title(api, pipeline.title_id)
    assert title["availability_state"] == "PUBLISHED"
    assert title["packaging_state"] == "PACKAGED"
    assert title["takedown_reason"] == "NONE"
    assert_score(
        title["readiness_score_certified"], 100.00, "readiness_score_certified"
    )
    assert_instant_equals(title["last_sweep_at"], INITIAL_CLOCK)


def test_second_sweep_at_the_same_clock_transitions_nothing(api):
    """Re-running the sweep without moving the clock returns all nine counts as zero.

    PRD §2.5: "The sweep is idempotent for a fixed clock value: running it a
    second time without moving the clock transitions nothing and returns all nine
    counts as zero."

    Design: Corner/state_machines/sweep_is_idempotent_for_a_fixed_clock
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-SWEEP-30"}
    )

    second = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN))
    assert_sweep_counters(second)

    window = _read_window(api, pipeline.title_id, pipeline.window_id)
    assert window["state"] == "ACTIVE"
    assert_instant_equals(window["activated_at"], INITIAL_CLOCK)

    title = fx.read_title(api, pipeline.title_id)
    assert title["availability_state"] == "PUBLISHED"
    assert title["packaging_state"] == "PACKAGED"


def test_manual_takedown_closes_the_active_window_and_stamps_manual_legal(api):
    """A hand takedown of a `PUBLISHED` title closes its `ACTIVE` window at the clock.

    PRD §3.6: "A manual takedown moves `availability_state` from `PUBLISHED` to
    `TAKEN_DOWN`, sets `takedown_reason` to `MANUAL_LEGAL`, increments the title's
    `version` by one, and closes every one of the title's `ACTIVE` windows with
    `closed_at` set to the logical clock's current instant."

    Design: Corner/state_machines/manual_legal_takedown_is_sticky_across_sweeps
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-STICKY-31"}
    )

    taken_down = validate_success(
        api.takedown_title(pipeline.title_id, f.takedown_payload(), CONTENT_OPS), 200
    )
    assert taken_down["availability_state"] == "TAKEN_DOWN"
    assert taken_down["takedown_reason"] == "MANUAL_LEGAL"
    assert taken_down["packaging_state"] == "PACKAGED"
    assert_score(
        taken_down["readiness_score_certified"], 100.00, "readiness_score_certified"
    )

    window = _read_window(api, pipeline.title_id, pipeline.window_id)
    assert window["state"] == "CLOSED"
    assert_instant_equals(window["closed_at"], INITIAL_CLOCK)


def test_manual_legal_takedown_is_never_republished_by_a_later_sweep(api):
    """The `MANUAL_LEGAL` reason is sticky, so the next sweep transitions nothing.

    PRD §3.6: "This closes the cycle `PUBLISHED` → `TAKEN_DOWN` → `PUBLISHED`: a
    title taken down for a contract gap or for stale packaging republishes itself
    once the gap closes and the packaging is repaired, while a `MANUAL_LEGAL`
    takedown is sticky and is never republished automatically."

    Design: Corner/state_machines/manual_legal_takedown_is_sticky_across_sweeps
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-STICKY-31"}
    )
    fx.takedown_title(api, pipeline.title_id)

    counters = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN))
    assert_sweep_counters(counters)

    title = fx.read_title(api, pipeline.title_id)
    assert title["availability_state"] == "TAKEN_DOWN"
    assert title["takedown_reason"] == "MANUAL_LEGAL"
    assert title["packaging_state"] == "PACKAGED"
    assert_score(
        title["readiness_score_certified"], 100.00, "readiness_score_certified"
    )


def test_cancelling_the_last_active_window_of_a_published_title(api):
    """Cancelling an `ACTIVE` window is terminal for the window and stamps `closed_at`.

    PRD §3.6: "Cancellation moves the window to the terminal `CANCELLED`, records
    `closed_at` at the logical clock's current instant, and releases the interval
    so a later window may legally occupy it."

    Design: Corner/state_machines/cancelling_last_active_window_takes_published_title_down
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-CANCEL-32"}
    )
    assert _read_window(api, pipeline.title_id, pipeline.window_id)["state"] == "ACTIVE"

    cancelled = validate_success(
        api.cancel_availability_window(pipeline.window_id, CONTENT_OPS), 200
    )
    assert cancelled["state"] == "CANCELLED"
    assert_instant_equals(cancelled["closed_at"], INITIAL_CLOCK)

    stored = _read_window(api, pipeline.title_id, pipeline.window_id)
    assert stored["state"] == "CANCELLED"
    assert_instant_equals(stored["closed_at"], INITIAL_CLOCK)


def test_cancelling_the_last_active_window_takes_the_title_down_for_contract_end(api):
    """Losing the last `ACTIVE` window drops a `PUBLISHED` title to `CONTRACT_END`.

    PRD §3.6: "Cancelling an `ACTIVE` window has one further consequence: when it
    was the title's last `ACTIVE` window and the title's `availability_state` was
    `PUBLISHED`, the title moves to `TAKEN_DOWN` with `takedown_reason` of
    `CONTRACT_END`."

    Design: Corner/state_machines/cancelling_last_active_window_takes_published_title_down
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-CANCEL-32"}
    )
    fx.cancel_window(api, pipeline.window_id)

    title = fx.read_title(api, pipeline.title_id)
    assert title["availability_state"] == "TAKEN_DOWN"
    assert title["takedown_reason"] == "CONTRACT_END"
    assert title["packaging_state"] == "PACKAGED"
    assert_score(
        title["readiness_score_certified"], 100.00, "readiness_score_certified"
    )


def test_sweep_closes_the_window_and_takes_the_title_down_without_expiring_it(api):
    """Moving the clock past `window_end_at` closes the window and takes the title down.

    PRD §2.5: "Each window in `SCHEDULED` or `ACTIVE` whose `window_end_at` is at
    or before now becomes `CLOSED` with `closed_at` set to the current instant."

    PRD §3.6: "A title in `PUBLISHED` moves to `TAKEN_DOWN` with
    `takedown_reason` of `CONTRACT_END` when, after Phase 1, none of its windows
    is `ACTIVE` and its `packaging_state` is still `PACKAGED` — the contract
    simply ran out."

    Design: Corner/state_machines/sweep_takes_down_then_expires_one_transition_per_title_per_sweep
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-WALK-33"}
    )
    fx.set_clock(api, "2026-09-01T00:00:00Z")

    counters = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN))
    assert_sweep_counters(counters, windows_closed=1, titles_taken_down=1)

    window = _read_window(api, pipeline.title_id, pipeline.window_id)
    assert window["state"] == "CLOSED"
    assert_instant_equals(window["closed_at"], "2026-09-01T00:00:00Z")

    title = fx.read_title(api, pipeline.title_id)
    assert title["availability_state"] == "TAKEN_DOWN"
    assert title["takedown_reason"] == "CONTRACT_END"
    assert title["packaging_state"] == "PACKAGED"


def test_expiry_needs_a_second_sweep_because_only_one_transition_fires_per_title(api):
    """The takedown consumes the first sweep's single transition; expiry waits for the next.

    PRD §2.5: "Each `Title` is re-evaluated for a publication change, and **at
    most one** `availability_state` transition is applied per title per sweep."

    PRD §3.6: "A title in `SCHEDULED` or in `TAKEN_DOWN` moves to the terminal
    `EXPIRED` when it owns at least one window, every one of its windows is
    `CLOSED` or `CANCELLED`, and the current logical clock has reached or passed
    the latest `window_end_at` across those windows."

    Design: Corner/state_machines/sweep_takes_down_then_expires_one_transition_per_title_per_sweep
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-WALK-33"}
    )
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.run_sweep(api)
    assert fx.read_title(api, pipeline.title_id)["availability_state"] == "TAKEN_DOWN"

    third = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN))
    assert_sweep_counters(third, titles_expired=1)

    title = fx.read_title(api, pipeline.title_id)
    assert title["availability_state"] == "EXPIRED"
    assert_instant_equals(title["last_sweep_at"], "2026-09-01T00:00:00Z")


def test_expired_title_is_terminal_and_a_fourth_sweep_transitions_nothing(api):
    """`EXPIRED` is terminal: once reached, further sweeps at the same clock do nothing.

    PRD §2.5: "The sweep is idempotent for a fixed clock value: running it a
    second time without moving the clock transitions nothing and returns all nine
    counts as zero."

    Design: Corner/state_machines/sweep_takes_down_then_expires_one_transition_per_title_per_sweep
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-WALK-33"}
    )
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.run_sweep(api)
    fx.run_sweep(api)
    assert fx.read_title(api, pipeline.title_id)["availability_state"] == "EXPIRED"

    fourth = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN))
    assert_sweep_counters(fourth)

    title = fx.read_title(api, pipeline.title_id)
    assert title["availability_state"] == "EXPIRED"
    assert title["packaging_state"] == "PACKAGED"


# ---------------------------------------------------------------------------
# The packaging dimension after revocation (§2.4, §3.5)
# ---------------------------------------------------------------------------


def test_revoking_the_packaged_package_drops_the_title_to_packaging(api):
    """Revoking the only `PACKAGED` package leaves the `LOCKED` ladder behind.

    PRD §3.5: "From every one of the three source states the title's
    `packaging_state` is re-derived with `REVOKED` packages ignored, which means
    revoking the last `STALE` package clears the staleness, and revoking a
    `PACKAGED` package drops the title to `PACKAGING` when a `LOCKED` ladder
    remains or to `UNPACKAGED` when none does."

    PRD §2.4: "Both variants blend three components with fixed weights: the
    source-master component contributes half the score, the ladder component
    contributes one fifth, and the DRM-package component contributes the
    remaining three tenths."

    Design: Corner/state_machines/revoking_packaged_package_reverts_title_to_packaging
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-REVOKE-34"}
    )

    revoked = validate_success(
        api.revoke_drm_package(pipeline.package_id, DRM_OPERATOR), 200
    )
    assert revoked["state"] == "REVOKED"

    title = fx.read_title(api, pipeline.title_id)
    assert title["packaging_state"] == "PACKAGING"
    assert title["locked_ladder_count"] == 1
    assert_score(
        title["readiness_score_certified"], 70.00, "readiness_score_certified"
    )
    assert_score(
        title["readiness_score_provisional"], 70.00, "readiness_score_provisional"
    )


def test_revocation_leaves_the_availability_dimension_published(api):
    """The two title dimensions are independent, so the sweep still transitions nothing.

    PRD §2.4: "A master in the terminal `QC_REJECTED` state stays in the
    denominator of both variants and leaves both numerators, so an abandoned
    master permanently depresses readiness until other masters are added; a
    `REVOKED` DRM package counts for neither variant."

    PRD §3.6: "A title in `PUBLISHED` moves to `TAKEN_DOWN` with
    `takedown_reason` of `CONTRACT_END` when, after Phase 1, none of its windows
    is `ACTIVE` and its `packaging_state` is still `PACKAGED` — the contract
    simply ran out."

    Design: Corner/state_machines/revoking_packaged_package_reverts_title_to_packaging
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-REVOKE-34"}
    )
    fx.revoke_package(api, pipeline.package_id)

    title = fx.read_title(api, pipeline.title_id)
    assert title["availability_state"] == "PUBLISHED"
    assert title["takedown_reason"] == "NONE"

    counters = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN))
    assert_sweep_counters(counters)

    after = fx.read_title(api, pipeline.title_id)
    assert after["availability_state"] == "PUBLISHED"
    assert after["packaging_state"] == "PACKAGING"


# ---------------------------------------------------------------------------
# The vendor state machine (§3.7)
# ---------------------------------------------------------------------------


def test_one_catastrophic_window_degrades_an_active_vendor(api):
    """A single 0.3200 rebuffer window scores 20.00 and drives the vendor to `DEGRADED`.

    PRD §3.7: "Finally the `quality_index` is 100.00 reduced by that penalty,
    clamped into the range 0.00 to 100.00, and rounded half up to two decimals,
    and the `breach_flag` is true exactly when `quality_index` is strictly below
    70.00; a `quality_index` of exactly 70.00 is not a breach while 69.99 is."

    PRD §3.7: "Otherwise, while `breach_window_count` is below 5, a vendor in
    `ACTIVE` whose `health_score_rolling` fell below 50.00 moves to `DEGRADED`,
    and a vendor in `DEGRADED` whose `health_score_rolling` reached 75.00 or more
    moves back to `ACTIVE`, which is the recovery arm of the `ACTIVE` →
    `DEGRADED` → `ACTIVE` cycle."

    Design: Corner/state_machines/vendor_recovers_to_active_after_three_clean_windows
    """
    profile = fx.create_tv_4k_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="ALPHA",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0300,
    )
    title = fx.create_title(
        api, external_ref="TTL-VHR-35", title_name="Vendor Health Cut"
    )

    metric = validate_success(
        api.create_playback_metric(
            f.playback_metric_payload(
                title["id"],
                profile["id"],
                vendor["id"],
                window_start_at="2026-07-25T00:00:00Z",
                window_end_at="2026-07-26T00:00:00Z",
                rebuffer_events=320,
            ),
            DELIVERY_ENGINEER,
        ),
        201,
    )
    assert_ratio_4dp(metric["rebuffer_ratio"], 0.3200, "rebuffer_ratio")
    assert_score(metric["quality_index"], 20.00, "PlaybackMetricWindow.quality_index")
    assert metric["breach_flag"] is True

    degraded = fx.read_vendor(api, vendor["id"])
    assert degraded["state"] == "DEGRADED"
    assert degraded["breach_window_count"] == 1
    assert_score(degraded["health_score_rolling"], 20.00, "health_score_rolling")
    assert_score(degraded["health_score_contract"], 20.00, "health_score_contract")


def test_two_clean_windows_are_not_yet_enough_to_recover(api):
    """The rolling mean climbs to 60.00 and then 73.33, both short of the 75.00 gate.

    PRD §3.7: "The `health_score_rolling` variant sorts those rows by
    `window_start_at` descending with `created_at` descending as its only
    tie-break, takes the newest 3 rows, and stores their unweighted arithmetic
    mean of `quality_index`, rounded half up to two decimals; when the vendor has
    fewer than 3 rows the mean is taken over however many exist, and when it has
    none at all the value is 100.00."

    Design: Corner/state_machines/vendor_recovers_to_active_after_three_clean_windows
    """
    profile = fx.create_tv_4k_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="ALPHA",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0300,
    )
    title = fx.create_title(
        api, external_ref="TTL-VHR-35", title_name="Vendor Health Cut"
    )
    fx.ingest_metric(
        api,
        title["id"],
        profile["id"],
        vendor["id"],
        window_start_at="2026-07-25T00:00:00Z",
        window_end_at="2026-07-26T00:00:00Z",
        rebuffer_events=320,
    )

    fx.ingest_metric(
        api,
        title["id"],
        profile["id"],
        vendor["id"],
        window_start_at="2026-07-26T00:00:00Z",
        window_end_at="2026-07-27T00:00:00Z",
        rebuffer_events=0,
    )
    after_two = fx.read_vendor(api, vendor["id"])
    assert after_two["state"] == "DEGRADED"
    assert_score(after_two["health_score_rolling"], 60.00, "health_score_rolling")

    fx.ingest_metric(
        api,
        title["id"],
        profile["id"],
        vendor["id"],
        window_start_at="2026-07-27T00:00:00Z",
        window_end_at="2026-07-28T00:00:00Z",
        rebuffer_events=0,
    )
    after_three = fx.read_vendor(api, vendor["id"])
    assert after_three["state"] == "DEGRADED"
    assert_score(after_three["health_score_rolling"], 73.33, "health_score_rolling")
    assert after_three["breach_window_count"] == 1


def test_third_clean_window_pushes_the_bad_row_out_and_recovers_the_vendor(api):
    """The fourth window drops the breach row from the newest three, so rolling hits 100.00.

    PRD §3.7: "The `health_score_contract` variant instead takes every row and
    computes a `play_attempts`-weighted mean: the sum over all rows of
    `quality_index` multiplied by `play_attempts`, divided by the sum of
    `play_attempts` across those rows, rounded half up to two decimals, and again
    100.00 when no rows exist."

    Design: Corner/state_machines/vendor_recovers_to_active_after_three_clean_windows
    """
    profile = fx.create_tv_4k_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="ALPHA",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0300,
    )
    title = fx.create_title(
        api, external_ref="TTL-VHR-35", title_name="Vendor Health Cut"
    )
    fx.ingest_metric(
        api,
        title["id"],
        profile["id"],
        vendor["id"],
        window_start_at="2026-07-25T00:00:00Z",
        window_end_at="2026-07-26T00:00:00Z",
        rebuffer_events=320,
    )
    for day in (26, 27, 28):
        fx.ingest_metric(
            api,
            title["id"],
            profile["id"],
            vendor["id"],
            window_start_at="2026-07-%dT00:00:00Z" % day,
            window_end_at="2026-07-%dT00:00:00Z" % (day + 1),
            rebuffer_events=0,
        )

    recovered = fx.read_vendor(api, vendor["id"])
    assert recovered["state"] == "ACTIVE"
    assert_score(recovered["health_score_rolling"], 100.00, "health_score_rolling")
    assert_score(recovered["health_score_contract"], 80.00, "health_score_contract")
    assert recovered["breach_window_count"] == 1


def test_single_candidate_policy_starts_standby_only_on_performance_rank(api):
    """One eligible vendor yields `STANDBY_ONLY` with a null backup.

    PRD §3.7: "Assignment third: `primary_vendor_id` becomes the first-ranked
    candidate, `backup_vendor_id` becomes the second-ranked candidate when two or
    more candidates survive and is null otherwise, `state` becomes `ACTIVE` with
    two or more candidates and `STANDBY_ONLY` with exactly one, and
    `selection_reason_code` records which branch chose the primary —
    `PERFORMANCE_RANK`, `COST_RANK` or `WEIGHTED_RANK` according to the mode."

    Design: Corner/state_machines/vendor_drained_after_five_breach_windows_is_terminal
    """
    fx.create_tv_4k_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="ALPHA",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0300,
    )
    title = fx.create_title(api, external_ref="TTL-VDR-36", title_name="Drain Cut")

    policy = validate_success(
        api.create_routing_policy(
            f.routing_policy_payload(
                title["id"], region_code="US", steering_mode="PERFORMANCE"
            ),
            DELIVERY_ENGINEER,
        ),
        201,
    )
    assert policy["state"] == "STANDBY_ONLY"
    assert policy["primary_vendor_id"] == vendor["id"]
    assert policy["backup_vendor_id"] is None
    assert policy["selection_reason_code"] == "PERFORMANCE_RANK"
    assert policy["excluded_vendor_ids"] == []
    assert policy["resteer_count"] == 0


def test_degradation_cascades_the_policy_to_unroutable(api):
    """The vendor leaving `ACTIVE` re-steers its policy into `UNROUTABLE` exactly once.

    PRD §3.7: "If and only if the vendor moved to `DEGRADED` or to `DRAINED`,
    every routing policy whose `primary_vendor_id` is that vendor re-runs the
    selector with that vendor added to its `excluded_vendor_ids` and its
    `resteer_count` incremented by one, landing in `ACTIVE`, `STANDBY_ONLY` or
    `UNROUTABLE` exactly as an operator-driven re-steer would; policies in
    `ACTIVE` and `STANDBY_ONLY` are both eligible for this cascade."

    PRD §3.7: "On a re-steer, whether operator-driven or cascaded, it is a
    legitimate outcome: the policy's `state` becomes `UNROUTABLE`,
    `primary_vendor_id` and `backup_vendor_id` both become null,
    `selection_reason_code` becomes `NO_CANDIDATE` and `projected_egress_cost_usd`
    becomes 0.00."

    Design: Corner/state_machines/vendor_drained_after_five_breach_windows_is_terminal
    """
    profile = fx.create_tv_4k_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="ALPHA",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0300,
    )
    title = fx.create_title(api, external_ref="TTL-VDR-36", title_name="Drain Cut")
    policy = fx.create_policy(
        api, title["id"], region_code="US", steering_mode="PERFORMANCE"
    )

    fx.ingest_metric(
        api,
        title["id"],
        profile["id"],
        vendor["id"],
        window_start_at="2026-07-25T00:00:00Z",
        window_end_at="2026-07-26T00:00:00Z",
        rebuffer_events=320,
    )

    degraded = fx.read_vendor(api, vendor["id"])
    assert degraded["state"] == "DEGRADED"
    assert degraded["breach_window_count"] == 1

    cascaded = fx.read_policy(api, policy["id"])
    assert cascaded["state"] == "UNROUTABLE"
    assert cascaded["primary_vendor_id"] is None
    assert cascaded["backup_vendor_id"] is None
    assert cascaded["selection_reason_code"] == "NO_CANDIDATE"
    assert cascaded["excluded_vendor_ids"] == [vendor["id"]]
    assert cascaded["resteer_count"] == 1
    assert_money(
        cascaded["projected_egress_cost_usd"], 0.00, "projected_egress_cost_usd"
    )


def test_fifth_breach_window_drains_the_vendor_terminally(api):
    """The drain arm is evaluated first, so the fifth breach ends the vendor's life.

    PRD §3.7: "A vendor whose `breach_window_count` has reached 5 or more after
    the ingest moves to the terminal `DRAINED`, from either `ACTIVE` or
    `DEGRADED`."

    Design: Corner/state_machines/vendor_drained_after_five_breach_windows_is_terminal
    """
    profile = fx.create_tv_4k_profile(api)
    vendor = fx.create_vendor(
        api,
        vendor_code="ALPHA",
        regions=["US"],
        committed_gbps=100.00,
        cost_per_gb_usd=0.0300,
    )
    title = fx.create_title(api, external_ref="TTL-VDR-36", title_name="Drain Cut")
    policy = fx.create_policy(
        api, title["id"], region_code="US", steering_mode="PERFORMANCE"
    )

    for day in (25, 26, 27, 28):
        fx.ingest_metric(
            api,
            title["id"],
            profile["id"],
            vendor["id"],
            window_start_at="2026-07-%dT00:00:00Z" % day,
            window_end_at="2026-07-%dT00:00:00Z" % (day + 1),
            rebuffer_events=320,
        )
    four = fx.read_vendor(api, vendor["id"])
    assert four["state"] == "DEGRADED"
    assert four["breach_window_count"] == 4

    fx.ingest_metric(
        api,
        title["id"],
        profile["id"],
        vendor["id"],
        window_start_at="2026-07-29T00:00:00Z",
        window_end_at="2026-07-30T00:00:00Z",
        rebuffer_events=320,
    )
    five = fx.read_vendor(api, vendor["id"])
    assert five["state"] == "DRAINED"
    assert five["breach_window_count"] == 5

    fx.ingest_metric(
        api,
        title["id"],
        profile["id"],
        vendor["id"],
        window_start_at="2026-07-30T00:00:00Z",
        window_end_at="2026-07-31T00:00:00Z",
        rebuffer_events=320,
    )
    six = fx.read_vendor(api, vendor["id"])
    assert six["state"] == "DRAINED"
    assert six["breach_window_count"] == 6
    assert_score(six["health_score_rolling"], 20.00, "health_score_rolling")
    assert_score(six["health_score_contract"], 20.00, "health_score_contract")

    settled = fx.read_policy(api, policy["id"])
    assert settled["state"] == "UNROUTABLE"
    assert settled["resteer_count"] == 1


# ---------------------------------------------------------------------------
# Live-event reservations (§3.8)
# ---------------------------------------------------------------------------


def test_booking_holds_the_capacity_on_the_primary_vendor(api):
    """A new reservation is `RESERVED`, buffered by 15 minutes, and charged to the primary.

    PRD §3.8: "A successful booking stores the reservation in `state` `RESERVED`
    with `active_vendor_id` set to `primary_vendor_id`, `failover_at` null and
    `released_gbps` 0.00, and immediately recomputes the primary vendor's
    `reserved_gbps`."

    PRD §3.8: "Two inputs are optional: `failover_vendor_id`, the vendor holding
    the standby stream, which defaults to null when no failover is contracted,
    and `buffer_minutes`, the setup and teardown buffer added to both ends of the
    window for capacity-overlap arithmetic, which defaults to 15 and must lie
    between 0 and 60 inclusive."

    Design: Corner/state_machines/reservation_cancel_releases_the_entire_hold
    """
    pipeline = fx.build_live_event_pipeline(api, vendor_count=1, committed_gbps=100.00)
    vendor_id = pipeline.vendor_ids[0]

    reservation = validate_success(
        api.create_live_reservation(
            f.live_reservation_payload(
                pipeline.title_id,
                vendor_id,
                window_start_at="2026-08-02T00:00:00Z",
                window_end_at="2026-08-02T04:00:00Z",
                reserved_gbps=40.00,
            ),
            DELIVERY_ENGINEER,
        ),
        201,
    )
    assert reservation["state"] == "RESERVED"
    assert reservation["active_vendor_id"] == vendor_id
    assert reservation["failover_vendor_id"] is None
    assert reservation["failover_at"] is None
    assert reservation["buffer_minutes"] == 15
    assert_money(reservation["reserved_gbps"], 40.00, "reserved_gbps")
    assert_money(reservation["released_gbps"], 0.00, "released_gbps")

    vendor = fx.read_vendor(api, vendor_id)
    assert_money(vendor["reserved_gbps"], 40.00, "CdnVendor.reserved_gbps")


def test_cancelling_a_reserved_booking_releases_the_whole_hold(api):
    """Cancellation is terminal and restores the vendor's pre-reservation ledger exactly.

    PRD §3.8: "A `DeliveryEngineer` cancels a reservation from `RESERVED` or from
    `ARMED`; both arms move it to the terminal `CANCELLED`, set `released_gbps` to
    `reserved_gbps` and release the whole hold from whichever vendor currently
    carries it, restoring that vendor's pre-reservation `reserved_gbps` exactly."

    Design: Corner/state_machines/reservation_cancel_releases_the_entire_hold
    """
    pipeline = fx.build_live_event_pipeline(api, vendor_count=1, committed_gbps=100.00)
    vendor_id = pipeline.vendor_ids[0]
    reservation = fx.create_reservation(
        api,
        pipeline.title_id,
        vendor_id,
        window_start_at="2026-08-02T00:00:00Z",
        window_end_at="2026-08-02T04:00:00Z",
        reserved_gbps=40.00,
    )

    cancelled = validate_success(
        api.cancel_live_reservation(reservation["id"], DELIVERY_ENGINEER), 200
    )
    assert cancelled["state"] == "CANCELLED"
    assert_money(cancelled["released_gbps"], 40.00, "released_gbps")
    assert_money(cancelled["reserved_gbps"], 40.00, "reserved_gbps")

    vendor = fx.read_vendor(api, vendor_id)
    assert_money(vendor["reserved_gbps"], 0.00, "CdnVendor.reserved_gbps")
    assert_money(vendor["committed_gbps"], 100.00, "CdnVendor.committed_gbps")


# ---------------------------------------------------------------------------
# Reprocessing jobs and the encode budget (§3.9)
# ---------------------------------------------------------------------------


def test_running_a_queued_job_commits_the_frozen_estimate(api):
    """The estimate is frozen at creation and the run debits exactly that figure.

    PRD §3.9: "The `cost_estimate_usd` is then the sum of those **already-rounded**
    per-rung entries, re-rounded to two decimals."

    PRD §3.9: "On success the job's `state` becomes `RUNNING`, its `committed_usd`
    becomes its `cost_estimate_usd`, the title's `encode_budget_remaining_usd`
    falls by that amount and the title's `version` increments by one."

    Design: Corner/state_machines/reprocess_completion_supersedes_source_and_stales_the_package
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-RPX-37"}
    )

    job = fx.create_job(
        api,
        pipeline.title_id,
        pipeline.ladder_id,
        trigger_reason="CODEC_DEPRECATION",
        target_codec_family="HEVC",
    )
    assert job["state"] == "QUEUED"
    assert job["result_ladder_id"] is None
    assert job["abort_reason"] == "NONE"
    assert_money_list(job["per_rung_cost_usd"], [1.94, 4.05], "per_rung_cost_usd")
    assert_money(job["cost_estimate_usd"], 5.99, "cost_estimate_usd")
    assert_score(job["priority_rank"], 40.60, "priority_rank")
    assert_money(job["committed_usd"], 0.00, "committed_usd")

    running = validate_success(
        api.run_reprocess_job(job["id"], ENCODING_ENGINEER), 200
    )
    assert running["state"] == "RUNNING"
    assert_money(running["committed_usd"], 5.99, "committed_usd")

    title = fx.read_title(api, pipeline.title_id)
    assert_money(
        title["encode_budget_remaining_usd"], 4994.01, "encode_budget_remaining_usd"
    )


def test_sweep_completion_mints_a_locked_result_ladder(api):
    """Phase 3 completes the job and the result ladder is born `LOCKED` with `OK`.

    PRD §3.9: "Hop one: a new encoding ladder is created for the same title with
    `codec_family` set to the job's `target_codec_family`, its `rungs` copied from
    the source ladder, `derived_from_ladder_id` set to the `source_ladder_id`,
    `state` `LOCKED` and `validation_reason_code` `OK` — the result ladder is born
    locked, without passing through authoring or validation."

    Design: Corner/state_machines/reprocess_completion_supersedes_source_and_stales_the_package
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-RPX-37"}
    )
    job = fx.create_job(
        api,
        pipeline.title_id,
        pipeline.ladder_id,
        trigger_reason="CODEC_DEPRECATION",
        target_codec_family="HEVC",
    )
    fx.run_job(api, job["id"])

    counters = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN))
    assert counters["jobs_completed"] == 1
    assert counters["jobs_failed"] == 0
    assert counters["titles_taken_down"] == 1
    assert counters["titles_published"] == 0

    completed = fx.read_job(api, job["id"])
    assert completed["state"] == "COMPLETED"
    assert completed["abort_reason"] == "NONE"
    assert completed["result_ladder_id"] is not None
    assert_money(completed["committed_usd"], 5.99, "committed_usd")

    result = fx.read_ladder(api, completed["result_ladder_id"])
    assert result["state"] == "LOCKED"
    assert result["codec_family"] == "HEVC"
    assert result["validation_reason_code"] == "OK"
    assert result["rung_count"] == 2
    assert result["peak_bitrate_kbps"] == 2500
    assert result["derived_from_ladder_id"] == pipeline.ladder_id


def test_sweep_completion_supersedes_the_source_and_takes_the_title_down(api):
    """Completion stales the package, so hop 5 takes the `PUBLISHED` title down.

    PRD §3.9: "Hop three: because the source ladder became `SUPERSEDED`, every DRM
    package bound to it in `state` `PACKAGED` moves to `STALE` with `stale_reason`
    `LADDER_SUPERSEDED`."

    PRD §3.4: "**Hop 5.** Because the title's `packaging_state` became `STALE`, a
    title whose `availability_state` was `PUBLISHED` moves to `TAKEN_DOWN` with
    `takedown_reason` of `PACKAGING_STALE`, and every licensing window of that
    title whose `state` was `ACTIVE` moves to `CLOSED` with `closed_at` set to the
    logical clock's current instant."

    Design: Corner/state_machines/reprocess_completion_supersedes_source_and_stales_the_package
    """
    pipeline = fx.build_published_title(
        api, title_overrides={"external_ref": "TTL-RPX-37"}
    )
    job = fx.create_job(
        api,
        pipeline.title_id,
        pipeline.ladder_id,
        trigger_reason="CODEC_DEPRECATION",
        target_codec_family="HEVC",
    )
    fx.run_job(api, job["id"])
    fx.run_sweep(api)

    result_ladder_id = fx.read_job(api, job["id"])["result_ladder_id"]
    source = fx.read_ladder(api, pipeline.ladder_id)
    assert source["state"] == "SUPERSEDED"
    assert source["superseded_by_ladder_id"] == result_ladder_id

    package = fx.read_package(api, pipeline.package_id)
    assert package["state"] == "STALE"
    assert package["stale_reason"] == "LADDER_SUPERSEDED"

    title = fx.read_title(api, pipeline.title_id)
    assert title["packaging_state"] == "STALE"
    assert title["locked_ladder_count"] == 1
    assert title["availability_state"] == "TAKEN_DOWN"
    assert title["takedown_reason"] == "PACKAGING_STALE"
    assert_score(
        title["readiness_score_certified"], 70.00, "readiness_score_certified"
    )
    assert_money(
        title["encode_budget_remaining_usd"], 4994.01, "encode_budget_remaining_usd"
    )

    window = _read_window(api, pipeline.title_id, pipeline.window_id)
    assert window["state"] == "CLOSED"
    assert_instant_equals(window["closed_at"], INITIAL_CLOCK)


def test_locking_a_sibling_ladder_supersedes_the_in_flight_job_source(api):
    """A second H264 lock supersedes the running job's source while the job is in flight.

    PRD §3.4: "**Hop 2.** Because this ladder locked, any *other* ladder of the
    same `title_id` **and** the same `codec_family` that was in `LOCKED` moves to
    the terminal `SUPERSEDED`, with its `superseded_by_ladder_id` pointing at the
    ladder that just locked."

    Design: Corner/state_machines/running_job_fails_when_source_ladder_superseded_mid_flight
    """
    pipeline = fx.build_locked_ladder_title(
        api, title_overrides={"external_ref": "TTL-JOBF-38"}
    )
    job = fx.create_job(
        api,
        pipeline.title_id,
        pipeline.ladder_id,
        trigger_reason="CODEC_DEPRECATION",
        target_codec_family="HEVC",
    )
    fx.run_job(api, job["id"])

    replacement = fx.create_locked_ladder(
        api,
        pipeline.title_id,
        codec_family="H264",
        rungs=[f.rung("540p", 540, 1500), f.rung("1080p", 1080, 4800)],
    )
    assert replacement["state"] == "LOCKED"

    source = fx.read_ladder(api, pipeline.ladder_id)
    assert source["state"] == "SUPERSEDED"
    assert source["superseded_by_ladder_id"] == replacement["id"]

    still_running = fx.read_job(api, job["id"])
    assert still_running["state"] == "RUNNING"
    assert_money(still_running["committed_usd"], 5.99, "committed_usd")
    assert_money(
        fx.read_title(api, pipeline.title_id)["encode_budget_remaining_usd"],
        4994.01,
        "encode_budget_remaining_usd",
    )


def test_sweep_fails_the_job_and_refunds_the_whole_commitment(api):
    """Phase 3 fails the job, refunds the estimate and mints no result ladder.

    PRD §3.9: "The job's `state` becomes `FAILED`, its `abort_reason` becomes
    `ENCODE_FAILURE` and its `committed_usd` returns to 0.00, and the title's
    `encode_budget_remaining_usd` rises by exactly the `cost_estimate_usd`,
    restoring the money invariant."

    PRD §3.9: "No result ladder is created and no packaging cascade fires."

    Design: Corner/state_machines/running_job_fails_when_source_ladder_superseded_mid_flight
    """
    pipeline = fx.build_locked_ladder_title(
        api, title_overrides={"external_ref": "TTL-JOBF-38"}
    )
    job = fx.create_job(
        api,
        pipeline.title_id,
        pipeline.ladder_id,
        trigger_reason="CODEC_DEPRECATION",
        target_codec_family="HEVC",
    )
    fx.run_job(api, job["id"])
    fx.create_locked_ladder(
        api,
        pipeline.title_id,
        codec_family="H264",
        rungs=[f.rung("540p", 540, 1500), f.rung("1080p", 1080, 4800)],
    )

    counters = validate_unpaginated(api.run_availability_sweep(PLATFORM_ADMIN))
    assert_sweep_counters(counters, jobs_failed=1)

    failed = fx.read_job(api, job["id"])
    assert failed["state"] == "FAILED"
    assert failed["abort_reason"] == "ENCODE_FAILURE"
    assert failed["result_ladder_id"] is None
    assert_money(failed["committed_usd"], 0.00, "committed_usd")
    assert_money(failed["cost_estimate_usd"], 5.99, "cost_estimate_usd")

    title = fx.read_title(api, pipeline.title_id)
    assert_money(
        title["encode_budget_remaining_usd"], 5000.00, "encode_budget_remaining_usd"
    )
    assert title["locked_ladder_count"] == 1

    rows, meta = validate_paginated(
        api.list_encoding_ladders(
            ENCODING_ENGINEER, params={"title_id": pipeline.title_id}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
