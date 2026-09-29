"""Optimistic concurrency on both guarded writes, and a per-device history selector.

Each case replays a value the client legitimately held a moment earlier and shows
that the refusal changes nothing, then repeats the same write with the value the
store now expects.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    PHANTOM_BASELINE_BMD,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    SCHEDULER_HEADERS,
    TECHNOLOGIST_HEADERS,
    assert_four_decimals,
    assert_qc_scoring,
    get_success_data,
    precision_assessment_payload,
    qc_run_payload,
    risk_profile_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-03-02T08:00:00Z"


class TestThePatientVersionIsSpentByTheFirstProfileWrite:
    """A version is a one-shot token, not a duplicate-suppression key."""

    def test_replaying_the_creation_version_is_refused_and_changes_nothing(
        self, world: ProgramWorld
    ):
        """The rejected write leaves the incumbent profile and the version untouched.

        "Recording a new clinical risk factor profile at `POST
        /bone-density/patients/{id}/risk-factor-profiles` requires
        `expected_patient_version` matching the addressed `Patient`'s current `version`.
        If any writer has advanced that patient's version since the client last read it,
        the request is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412). The reason is
        that a new profile legitimately supersedes the incumbent `ACTIVE` profile"

        Design: Corner/cross_cutting_complexity_layers/stale_patient_version_on_a_profile_write_is_rejected_and_the_reread_version_succeeds
        """
        world.set_clock(CLOCK_START)
        policy = world.create_policy()
        patient = world.create_patient(policy["id"])
        version_at_creation = patient["version"]

        first_profile = world.create_profile(patient)
        version_after_first = world.read_patient(patient["id"])["version"]
        assert version_after_first == version_at_creation + 1

        replayed = world.api.create_risk_factor_profile(
            patient["id"],
            risk_profile_payload(
                version_at_creation, height_cm=164.0, weight_kg=57.0, current_smoker=True
            ),
            PHYSICIAN_HEADERS,
        )
        validate_error(replayed, ApiErrorId.STALE_PATIENT_VERSION.value, 412)

        assert world.read_patient(patient["id"])["version"] == version_after_first
        active_rows, active_meta = validate_paginated(
            world.api.list_risk_factor_profiles(
                patient["id"], PHYSICIAN_HEADERS, {"status": "ACTIVE"}
            )
        )
        assert active_meta["total_count"] == 1
        assert active_rows[0]["id"] == first_profile["id"]

        accepted = validate_success(
            world.api.create_risk_factor_profile(
                patient["id"],
                risk_profile_payload(
                    version_after_first,
                    height_cm=164.0,
                    weight_kg=57.0,
                    current_smoker=True,
                ),
                PHYSICIAN_HEADERS,
            ),
            201,
        )
        assert accepted["status"] == "ACTIVE"
        assert accepted["current_smoker"] is True
        assert accepted["height_cm"] == 164.0

        assert world.read_patient(patient["id"])["version"] == version_after_first + 1

        rows, meta = validate_paginated(
            world.api.list_risk_factor_profiles(patient["id"], SCHEDULER_HEADERS)
        )
        assert meta["total_count"] == 2
        by_id = {row["id"]: row["status"] for row in rows}
        assert by_id[first_profile["id"]] == "SUPERSEDED"
        assert [row["status"] for row in rows].count("ACTIVE") == 1


class TestTheDensitometerVersionGuardsTheLeastSignificantChange:
    """The guarded value is one that later acquisitions freeze, so it may not slip."""

    def test_replaying_the_creation_version_leaves_the_first_studys_threshold(
        self, world: ProgramWorld
    ):
        """The identical body succeeds once it carries the re-read version.

        "Here the stake is the least significant change: a new assessment overwrites the
        device's `rms_sd_g_cm2` and `lsc_g_cm2`, and a writer holding a stale view would
        overwrite a least-significant-change value that has already moved"
        "When the study is accepted, the device's least significant change in absolute
        units is the reported root-mean-square standard deviation multiplied by 2.77 — the
        two-sided ninety-five-percent coefficient for a paired measurement — rounded half
        up to four decimal places, and written to `lsc_g_cm2`. A study reporting 0.0100
        therefore certifies a least significant change of 0.0277."

        Design: Corner/cross_cutting_complexity_layers/stale_densitometer_version_on_a_precision_write_is_rejected_and_the_lsc_is_unchanged
        """
        world.set_clock(CLOCK_START)
        device = world.create_device()
        version_at_creation = device["version"]

        certified = world.certify_device(device, rms_sd_g_cm2=0.0100)
        assert certified["precision_degrees_of_freedom"] == 30
        assert_four_decimals(certified["lsc_g_cm2"], 0.0277, "lsc_g_cm2")

        version_after_first = world.read_device(device["id"])["version"]
        assert version_after_first == version_at_creation + 1

        replayed = world.api.create_precision_assessment(
            device["id"],
            precision_assessment_payload(
                version_at_creation,
                technologist_user_id="tech-002",
                rms_sd_g_cm2=0.0200,
            ),
            ADMIN_HEADERS,
        )
        validate_error(replayed, ApiErrorId.STALE_DENSITOMETER_VERSION.value, 412)

        unchanged = world.read_device(device["id"])
        assert_four_decimals(unchanged["rms_sd_g_cm2"], 0.0100, "rms_sd_g_cm2")
        assert_four_decimals(unchanged["lsc_g_cm2"], 0.0277, "lsc_g_cm2")
        assert unchanged["version"] == version_after_first

        # PRD §4 pins HTTP 201 to "creation endpoints ... with the created resource in
        # `data`" and HTTP 200 to "action endpoints that transition an existing
        # resource". The precision assessment returns the pre-existing Densitometer
        # with its `version` advanced, and the PRD never declares a PrecisionAssessment
        # resource, so the success status is not uniquely determined here. Validate the
        # envelope and the certified values, not the status code.
        accepted = get_success_data(
            world.api.create_precision_assessment(
                device["id"],
                precision_assessment_payload(
                    version_after_first,
                    technologist_user_id="tech-002",
                    rms_sd_g_cm2=0.0200,
                ),
                ADMIN_HEADERS,
            )
        )
        assert_four_decimals(accepted["rms_sd_g_cm2"], 0.0200, "rms_sd_g_cm2")
        assert_four_decimals(accepted["lsc_g_cm2"], 0.0554, "lsc_g_cm2")

        reread = world.read_device(device["id"])
        assert reread["version"] == version_after_first + 1
        assert_four_decimals(reread["lsc_g_cm2"], 0.0554, "lsc_g_cm2")


SHIFT_CLOCKS = [
    "2026-03-02T08:00:00Z",
    "2026-03-02T09:00:00Z",
    "2026-03-03T08:00:00Z",
    "2026-03-03T09:00:00Z",
    "2026-03-04T08:00:00Z",
    "2026-03-04T09:00:00Z",
]


def _two_devices_with_interleaved_chart_history(world: ProgramWorld):
    """Two identical devices whose first two daily runs alternate in wall-clock order."""
    world.set_clock(SHIFT_CLOCKS[0])
    device_a = world.create_device()
    device_b = world.create_device()
    assert device_a["phantom_baseline_bmd_g_cm2"] == PHANTOM_BASELINE_BMD
    assert device_b["phantom_baseline_bmd_g_cm2"] == PHANTOM_BASELINE_BMD

    history = [
        (device_a["id"], 1.0100, 0.0100, 1.000, "PASS"),
        (device_b["id"], 1.0150, 0.0150, 1.500, "WARN"),
        (device_a["id"], 1.0120, 0.0120, 1.200, "WARN"),
        (device_b["id"], 0.9880, -0.0120, -1.200, "WARN"),
    ]
    for index, (device_id, phantom, deviation, sd_units, result) in enumerate(history):
        world.set_clock(SHIFT_CLOCKS[index])
        run = validate_success(
            world.api.create_qc_run(
                device_id,
                qc_run_payload(phantom_bmd_g_cm2=phantom),
                TECHNOLOGIST_HEADERS,
            ),
            201,
        )
        assert_qc_scoring(run, deviation, sd_units, result)
        assert run["shift_detected"] is False

    return device_a, device_b


class TestTheShiftSelectorReadsOnlyItsOwnDeviceHistory:
    """Two charts interleaved in time reach opposite verdicts from the same magnitude."""

    def test_one_device_trips_a_sustained_shift_while_the_other_breaks_the_sign_chain(
        self, world: ProgramWorld
    ):
        """A run that passes at exactly the limit still counts toward the shift.

        "`shift_detected` is computed only for `DAILY_QC` runs, and is true when this run
        together with the **two immediately preceding** `DAILY_QC` runs on the same device
        — the two ranked highest by `performed_at_utc` descending and then `created_at`
        descending among the runs before it — all show an absolute `deviation_sd_units` of
        at least 1.000 *and* all three share the same sign. A deviation of exactly zero has
        no sign and therefore breaks the chain. When fewer than two preceding daily runs
        exist the flag is false"
        "Otherwise a true `shift_detected` drives `status` to `QC_HOLD` with
        `qc_hold_reason_code` `SUSTAINED_SHIFT`, the same `qc_hold_started_at`, and the same
        reset — and this fires even when the run's own `result` is `PASS`"

        Design: Corner/cross_cutting_complexity_layers/shift_detection_reads_only_the_two_preceding_daily_runs_on_the_same_device
        """
        device_a, device_b = _two_devices_with_interleaved_chart_history(world)

        before = world.read_device(device_a["id"])
        assert before["status"] == "ACTIVE"
        assert before["consecutive_qc_pass_count"] == 0

        world.set_clock(SHIFT_CLOCKS[4])
        third_on_a = validate_success(
            world.api.create_qc_run(
                device_a["id"],
                qc_run_payload(phantom_bmd_g_cm2=1.0110),
                TECHNOLOGIST_HEADERS,
            ),
            201,
        )
        assert_qc_scoring(third_on_a, 0.0110, 1.100, "WARN")
        assert third_on_a["shift_detected"] is True

        held = world.read_device(device_a["id"])
        assert held["status"] == "QC_HOLD"
        assert held["qc_hold_reason_code"] == "SUSTAINED_SHIFT"
        assert held["consecutive_qc_pass_count"] == 0

        world.set_clock(SHIFT_CLOCKS[5])
        third_on_b = validate_success(
            world.api.create_qc_run(
                device_b["id"],
                qc_run_payload(phantom_bmd_g_cm2=1.0110),
                TECHNOLOGIST_HEADERS,
            ),
            201,
        )
        assert_qc_scoring(third_on_b, 0.0110, 1.100, "WARN")
        assert third_on_b["shift_detected"] is False

        still_active = world.read_device(device_b["id"])
        assert still_active["status"] == "ACTIVE"
        assert still_active["qc_hold_reason_code"] is None

        for device_id in (device_a["id"], device_b["id"]):
            _, meta = validate_paginated(
                world.api.list_qc_runs(ADMIN_HEADERS, {"densitometer_id": device_id})
            )
            assert meta["total_count"] == 3
