"""Temporal overlap rules: half-open speaker-segment intervals and the
60-second capture gap buffer.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    create_encounter,
    create_patient,
    create_physician,
    grant_consent,
    ready_world,
    set_clock,
    start_capture,
    start_encounter,
    stop_capture,
)


class TestSegmentHalfOpenIntervals:
    """Adjacency is allowed; a 1ms overlap is rejected."""

    def _setup(self, client):
        """IN_PROGRESS encounter with a RECORDING capture carrying [0,5000)."""
        world = ready_world(client)
        # Start a fresh capture; ready_world's capture stopped at 16:00, so
        # push the clock past the 60-second buffer before starting a new one.
        set_clock(client, "2026-09-01T16:01:00Z")
        capture = start_capture(client, world["encounter"], world["physician"])
        get_success_data(
            client.append_segment(
                capture["id"],
                f.segment_payload(
                    start_offset_ms=0,
                    end_offset_ms=5000,
                    speaker_role="PHYSICIAN",
                    base_confidence=0.95,
                ),
                headers=world["physician_headers"],
            )
        )
        world["capture"] = capture
        return world

    def test_adjacent_segment_accepted(self, client):
        """PRD 3.3: "Intervals within one capture must be pairwise disjoint
        under half-open semantics: adjacency (one segment's start equal to
        another's end) is allowed, while even a 1-millisecond overlap is
        rejected with `ERR_SEGMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/segment_half_open_intervals_on_capture
        """
        world = self._setup(client)
        body = validate_success(
            client.append_segment(
                world["capture"]["id"],
                f.segment_payload(
                    start_offset_ms=5000,
                    end_offset_ms=9000,
                    speaker_role="PATIENT",
                    base_confidence=0.9,
                ),
                headers=world["physician_headers"],
            ),
            201,
        )
        assert body["start_offset_ms"] == 5000
        assert body["end_offset_ms"] == 9000

    def test_one_millisecond_overlap_rejected(self, client):
        """PRD 3.3: "Intervals within one capture must be pairwise disjoint
        under half-open semantics: adjacency (one segment's start equal to
        another's end) is allowed, while even a 1-millisecond overlap is
        rejected with `ERR_SEGMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/segment_half_open_intervals_on_capture
        """
        world = self._setup(client)
        get_success_data(
            client.append_segment(
                world["capture"]["id"],
                f.segment_payload(
                    start_offset_ms=5000,
                    end_offset_ms=9000,
                    speaker_role="PATIENT",
                    base_confidence=0.9,
                ),
                headers=world["physician_headers"],
            )
        )
        resp = client.append_segment(
            world["capture"]["id"],
            f.segment_payload(
                start_offset_ms=8999,
                end_offset_ms=12000,
                speaker_role="CAREGIVER",
                base_confidence=0.8,
            ),
            headers=world["physician_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SEGMENT_OVERLAP.value, 409)


class TestCaptureBufferGap:
    """A new capture needs 60 seconds after the last stopped capture."""

    def _setup(self, client):
        """Encounter IN_PROGRESS, consent GRANTED, capture1 stopped 10:02:00."""
        patient = create_patient(client)
        physician = create_physician(client)
        set_clock(client, "2026-09-01T10:00:00Z")
        encounter = create_encounter(client, patient, physician)
        grant_consent(client, encounter, patient)
        encounter = start_encounter(client, encounter, physician)
        capture = start_capture(client, encounter, physician)
        set_clock(client, "2026-09-01T10:02:00Z")
        stop_capture(client, capture, physician)
        headers = {"X-User-ID": physician["id"], "X-User-Role": "Physician"}
        return {"encounter": encounter, "headers": headers}

    def test_59_second_gap_rejected(self, client):
        """PRD 3.3: "a new capture may start only at least 60 seconds after
        the most recently stopped capture's `ended_at` on the same encounter
        — a start exactly 60 seconds later is allowed, one second earlier is
        rejected with `ERR_CAPTURE_GAP_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/capture_buffer_gap_on_encounter
        """
        w = self._setup(client)
        set_clock(client, "2026-09-01T10:02:59Z")
        resp = client.start_audio_capture(
            w["encounter"]["id"], f.start_capture_payload(), headers=w["headers"]
        )
        validate_error(resp, ApiErrorId.ERR_CAPTURE_GAP_VIOLATION.value, 409)

    def test_exactly_60_seconds_allowed(self, client):
        """PRD 3.3: "a new capture may start only at least 60 seconds after
        the most recently stopped capture's `ended_at` on the same encounter
        — a start exactly 60 seconds later is allowed, one second earlier is
        rejected with `ERR_CAPTURE_GAP_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/capture_buffer_gap_on_encounter
        """
        w = self._setup(client)
        set_clock(client, "2026-09-01T10:02:59Z")
        validate_error(
            client.start_audio_capture(
                w["encounter"]["id"], f.start_capture_payload(), headers=w["headers"]
            ),
            ApiErrorId.ERR_CAPTURE_GAP_VIOLATION.value,
            409,
        )
        set_clock(client, "2026-09-01T10:03:00Z")
        body = validate_success(
            client.start_audio_capture(
                w["encounter"]["id"], f.start_capture_payload(), headers=w["headers"]
            ),
            201,
        )
        assert body["status"] == "RECORDING"
