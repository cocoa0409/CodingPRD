"""Training sessions, group formation, and temporal overlap rules.

Covers difficulty instances under resource_temporal_overlap and corner
instances for training cross-references and meeting scheduling.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_center_manager,
    create_center_meeting_payload,
    create_member_payload,
    create_peer_group,
    create_training_session_payload,
    get_success_data,
    make_center_manager_headers,
    recruit_member,
    setup_org,
    setup_two_active_groups,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
FO = TEST_USERS["field_officer_headers"]


class TestMeetingOverlapHalfOpen:
    def test_center_meeting_half_open_adjacency_allowed_overlap_rejected(self, api):
        """PRD §3.5: "the meeting occupies its center's calendar as a **half-open
        interval** — it collides with any other non-`CANCELLED` meeting of the
        same center whose interval intersects it, failing with
        `ERR_MEETING_OVERLAP`, while two meetings that merely touch at a
        boundary are allowed."

        Design: Difficulty/resource_temporal_overlap/center_meeting_half_open_adjacency_allowed_overlap_rejected
        """
        branch, manager, center = setup_org()
        cm = make_center_manager_headers(manager["id"])

        first = api.create_center_meeting(
            create_center_meeting_payload(
                center["id"],
                scheduled_start="2026-09-08T10:00:00Z",
                scheduled_end="2026-09-08T11:00:00Z",
            ),
            cm,
        )
        assert first.status_code == 201, f"first meeting must be created: {first.text}"

        adjacent = api.create_center_meeting(
            create_center_meeting_payload(
                center["id"],
                scheduled_start="2026-09-08T11:00:00Z",
                scheduled_end="2026-09-08T12:00:00Z",
            ),
            cm,
        )
        assert adjacent.status_code == 201, (
            f"an adjacent meeting touching at the boundary must be allowed: {adjacent.text}"
        )

        overlapping = api.create_center_meeting(
            create_center_meeting_payload(
                center["id"],
                scheduled_start="2026-09-08T10:30:00Z",
                scheduled_end="2026-09-08T11:30:00Z",
            ),
            cm,
        )
        validate_error(overlapping, ApiErrorId.ERR_MEETING_OVERLAP, expected_status=409)

    def test_center_meeting_half_open_adjacency_allowed_overlap_rejected_across_weeks(self, api):
        """PRD §3.5: "the meeting occupies its center's calendar as a **half-open
        interval** — it collides with any other non-`CANCELLED` meeting of the
        same center whose interval intersects it, failing with
        `ERR_MEETING_OVERLAP`, while two meetings that merely touch at a
        boundary are allowed."
        PRD §3.5: "the UTC weekday of `scheduled_start` must equal the center's
        `meeting_day_of_week` (`ERR_MEETING_DAY_MISMATCH`)".

        Design: Difficulty/resource_temporal_overlap/center_meeting_half_open_adjacency_allowed_overlap_rejected
        """
        branch, manager, center = setup_org()
        cm = make_center_manager_headers(manager["id"])
        # Adjacent pair on the following Tuesday still succeeds, and a meeting
        # that straddles the first meeting's start is rejected.
        first = api.create_center_meeting(
            create_center_meeting_payload(
                center["id"],
                scheduled_start="2026-09-15T10:00:00Z",
                scheduled_end="2026-09-15T11:00:00Z",
            ),
            cm,
        )
        assert first.status_code == 201
        adjacent = api.create_center_meeting(
            create_center_meeting_payload(
                center["id"],
                scheduled_start="2026-09-15T11:00:00Z",
                scheduled_end="2026-09-15T11:30:00Z",
            ),
            cm,
        )
        assert adjacent.status_code == 201, "touching at the boundary is allowed"
        straddling = api.create_center_meeting(
            create_center_meeting_payload(
                center["id"],
                scheduled_start="2026-09-15T09:30:00Z",
                scheduled_end="2026-09-15T10:30:00Z",
            ),
            cm,
        )
        validate_error(straddling, ApiErrorId.ERR_MEETING_OVERLAP, expected_status=409)


class TestTrainingSlotBuffer:
    def test_training_slot_buffer_rejects_20_min_gap(self, api):
        """PRD §3.2: "Sessions occupy their facilitator's calendar as **closed
        intervals padded by a 30-minute buffer on both sides**: a new session
        collides with any of the same manager's `SCHEDULED` or `COMPLETED`
        sessions whose padded interval intersects it, and even adjacency inside
        the buffer is rejected with `ERR_TRAINING_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/training_slot_buffer_rejects_20_min_gap_allows_40

        Note: the original "allows a 40-minute gap" half is removed — the PRD
        prose does not uniquely determine whether padding both intervals means
        a 40-minute gap is allowed (unpadded intersect: allowed; padded
        intersect: rejected), so that assertion is not uniquely derivable.
        """
        branch, manager, center = setup_org()
        cm = make_center_manager_headers(manager["id"])

        def forming_group(name, label):
            group = create_peer_group(center["id"], name=name)
            for i in range(5):
                member = recruit_member(
                    branch["id"],
                    full_name=f"{label} {i}",
                    national_id=f"NID-{label}-{i}-buf",
                )
                get_success_data(
                    api.add_group_member(group["id"], {"member_id": member["id"]}, FO)
                )
            return group

        g1 = forming_group("G1", "bufa")
        g2 = forming_group("G2", "bufb")

        first = api.create_training_session(
            create_training_session_payload(
                g1["id"], manager["id"],
                start_time="2026-09-02T09:00:00Z", end_time="2026-09-02T10:00:00Z",
            ),
            cm,
        )
        assert first.status_code == 201, f"first session must be scheduled: {first.text}"

        inside_buffer = api.create_training_session(
            create_training_session_payload(
                g2["id"], manager["id"],
                start_time="2026-09-02T10:20:00Z", end_time="2026-09-02T11:20:00Z",
            ),
            cm,
        )
        validate_error(
            inside_buffer, ApiErrorId.ERR_TRAINING_SLOT_OVERLAP, expected_status=409
        )

    def test_training_slot_buffer_rejects_20_min_gap_allows_40_zero_gap(self, api):
        """PRD §3.2: "Sessions occupy their facilitator's calendar as **closed
        intervals padded by a 30-minute buffer on both sides**: a new session
        collides with any of the same manager's `SCHEDULED` or `COMPLETED`
        sessions whose padded interval intersects it, and even adjacency inside
        the buffer is rejected with `ERR_TRAINING_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/training_slot_buffer_rejects_20_min_gap_allows_40
        """
        branch, manager, center = setup_org()
        cm = make_center_manager_headers(manager["id"])

        def forming_group(name, label):
            group = create_peer_group(center["id"], name=name)
            for i in range(5):
                member = recruit_member(
                    branch["id"],
                    full_name=f"{label} {i}",
                    national_id=f"NID-{label}-{i}-zero",
                )
                get_success_data(
                    api.add_group_member(group["id"], {"member_id": member["id"]}, FO)
                )
            return group

        g1 = forming_group("G1", "zga")
        g2 = forming_group("G2", "zgb")
        first = api.create_training_session(
            create_training_session_payload(
                g1["id"], manager["id"],
                start_time="2026-09-02T09:00:00Z", end_time="2026-09-02T10:00:00Z",
            ),
            cm,
        )
        assert first.status_code == 201
        # Zero-minute gap (adjacent) is inside the padded buffer: rejected.
        adjacent = api.create_training_session(
            create_training_session_payload(
                g2["id"], manager["id"],
                start_time="2026-09-02T10:00:00Z", end_time="2026-09-02T11:00:00Z",
            ),
            cm,
        )
        validate_error(adjacent, ApiErrorId.ERR_TRAINING_SLOT_OVERLAP, expected_status=409)


class TestMeetingWeekdayRule:
    def test_meeting_weekday_must_match_center_day(self, api):
        """PRD §3.5: "the UTC weekday of `scheduled_start` must equal the
        center's `meeting_day_of_week` (`ERR_MEETING_DAY_MISMATCH`)".

        Design: Corner/validations/meeting_weekday_must_match_center_day
        """
        branch, manager, center = setup_org()
        cm = make_center_manager_headers(manager["id"])
        response = api.create_center_meeting(
            create_center_meeting_payload(
                center["id"],
                scheduled_start="2026-09-09T10:00:00Z",  # Wednesday; center meets Tuesday
                scheduled_end="2026-09-09T11:00:00Z",
            ),
            cm,
        )
        validate_error(response, ApiErrorId.ERR_MEETING_DAY_MISMATCH, expected_status=422)


class TestTrainingManagerCoherence:
    def test_training_session_manager_must_match_center_manager(self, api):
        """PRD §3.2: "the `center_manager_id` must be the manager of the group's
        center (`ERR_MANAGER_CENTER_MISMATCH`)."

        Design: Corner/validations/training_session_manager_must_match_center_manager
        """
        branch, manager, center = setup_org()
        other_manager = create_center_manager(branch["id"], full_name="Other Manager")
        group = create_peer_group(center["id"])
        for i in range(5):
            member = recruit_member(
                branch["id"],
                full_name=f"mismatch {i}",
                national_id=f"NID-mismatch-{i}",
            )
            get_success_data(
                api.add_group_member(group["id"], {"member_id": member["id"]}, FO)
            )
        response = api.create_training_session(
            create_training_session_payload(
                group["id"], other_manager["id"],
                start_time="2026-09-04T09:00:00Z", end_time="2026-09-04T10:00:00Z",
            ),
            make_center_manager_headers(other_manager["id"]),
        )
        validate_error(response, ApiErrorId.ERR_MANAGER_CENTER_MISMATCH, expected_status=422)
        group_now = get_success_data(api.get_peer_group(group["id"], PA))
        assert group_now["status"] == "FORMING", "no TRAINING transition may fire"
