"""Corner coverage: endpoint behaviors — employer verification, FK reverse
reads, append-only sub-resource lists."""
from test_helpers import (
    ADMIN,
    QA,
    TC,
    ApiErrorId,
    assert_card_verification,
    create_card_verification_payload,
    create_center_with_faculty,
    create_instructor_payload,
    create_monitoring_payload,
    create_teaching_evaluation_payload,
    get_success_data,
    make_faculty_headers,
    make_instructor_headers,
    setup_completed_session_with_cards,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

EMPLOYER = TEST_USERS["employer_headers"]


class TestEmployerVerification:
    def test_employer_verification_valid_and_mismatch(self, api):
        """PRD §3.10: "A `verification_token` that does not match the resolved
        card rejects with `ERR_CARD_VERIFICATION_MISMATCH` and no verification
        event is recorded. A successful verification appends a
        `CardVerification` event stamped with the current clock as
        `verified_at` and the resolved card's `id` as `card_id`. The event's
        `result` echoes the card's standing: `VALID` when the card is `ACTIVE`
        and the token matched; otherwise the card's own status, `EXPIRED` or
        `REVOKED`. The event also surfaces `card_expires_at`, a copy of the
        card's `expires_at`, so the employer can schedule the provider's
        renewal without a second call."

        Design: Corner/endpoints/employer_verification_valid_and_mismatch
        """
        built = setup_completed_session_with_cards(num_students=1)
        card = built["cards"][0]
        assert card["expires_at"] == "2028-09-30T23:59:59Z"

        resp = api.create_card_verification(
            create_card_verification_payload(
                card["card_code"], "WRONG-TOKEN"), EMPLOYER)
        validate_error(resp, ApiErrorId.ERR_CARD_VERIFICATION_MISMATCH)

        ok = validate_success(
            api.create_card_verification(
                create_card_verification_payload(
                    card["card_code"], card["verification_token"]), EMPLOYER),
            expected_status=201)
        assert_card_verification(ok)
        assert ok["result"] == "VALID"
        assert ok["card_expires_at"] == "2028-09-30T23:59:59Z"
        assert ok["card_id"] == card["id"]

        rows, meta = validate_paginated(
            api.list_card_verifications(card["id"], EMPLOYER))
        # The mismatch recorded nothing; exactly one event exists.
        assert len(rows) == 1
        assert meta["total_count"] == 1


class TestAlignmentReverseReads:
    def test_alignment_visible_from_both_reverse_directions(self, api):
        """PRD §3.1: "the center must have faculty oversight: at least one
        `TCAlignment` row whose `status` is `ACTIVE`, whose `as_faculty` flag
        is `true`, and whose referenced instructor is currently `CERTIFIED`."
        PRD §3.1: "each alignment starts in `ACTIVE` and at most one `ACTIVE`
        alignment may exist for a given (`training_center_id`, `instructor_id`)
        pair — a second alignment for the same pair is rejected with
        `ERR_DUPLICATE_ACTIVE_ALIGNMENT`."

        Design: Corner/endpoints/alignment_visible_from_both_reverse_directions
        """
        center, faculty = create_center_with_faculty()

        center_rows, _ = validate_paginated(
            api.list_center_alignments(center["id"], TC,
                                       params={"status": "ACTIVE"}))
        instructor_rows, _ = validate_paginated(
            api.list_instructor_alignments(
                faculty["id"], make_instructor_headers(faculty["id"]),
                params={"status": "ACTIVE"}))
        assert len(center_rows) == 1
        assert len(instructor_rows) == 1
        assert center_rows[0]["id"] == instructor_rows[0]["id"]
        row = center_rows[0]
        assert row["training_center_id"] == center["id"]
        assert row["instructor_id"] == faculty["id"]
        assert row["as_faculty"] is True
        assert row["status"] == "ACTIVE"


class TestPathwayRecordsReverseReads:
    def test_monitorings_and_evaluations_visible_via_reverse_gets(self, api):
        """PRD §3.2: "The system records the evaluating faculty on the
        resulting `CourseMonitoring` row as `monitoring_faculty_id`, taken from
        the caller's `X-User-ID`, and the candidate on the row as
        `instructor_id`. When `outcome` is `SATISFACTORY` the candidate
        advances from `CANDIDATE` to `MONITORED`."
        PRD §3.2: "the evaluating faculty is recorded as
        `evaluator_faculty_id` from the caller's `X-User-ID`."

        Design: Corner/endpoints/monitorings_and_evaluations_visible_via_reverse_gets
        """
        center, faculty = create_center_with_faculty()
        cand = get_success_data(api.create_instructor(
            create_instructor_payload(center["id"]), ADMIN))
        fac = make_faculty_headers(faculty["id"])
        get_success_data(api.monitor_instructor(
            cand["id"], create_monitoring_payload(), fac))
        get_success_data(api.create_teaching_evaluation(
            cand["id"], create_teaching_evaluation_payload(
                score=4, notes="Solid."), fac))

        monitorings, _ = validate_paginated(
            api.list_monitorings(cand["id"], QA))
        assert len(monitorings) == 1
        m = monitorings[0]
        assert m["instructor_id"] == cand["id"]
        assert m["monitoring_faculty_id"] == faculty["id"]
        assert m["outcome"] == "SATISFACTORY"

        evals, _ = validate_paginated(
            api.list_teaching_evaluations(cand["id"], QA))
        assert len(evals) == 1
        assert evals[0]["evaluator_faculty_id"] == faculty["id"]
        assert evals[0]["score"] == 4

        cand_now = validate_success(api.get_instructor(cand["id"], TC))
        assert cand_now["status"] == "MONITORED"


class TestImmediateConsistency:
    def test_immediate_read_after_activate_shows_new_state(self, api):
        """PRD §3.1: "Only once at least one site is `ALIGNED` may a
        `NationalAdmin` activate the center, moving it from `PROVISIONAL` to
        `ACTIVE`. If no site is `ALIGNED` the activation is rejected with
        `ERR_NO_ALIGNED_SITE`. Activation increments the center's `version`
        by 1."
        PRD §2.7: "`updated_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was last modified;
        refreshed on any mutation."

        Design: Corner/consistency_model/immediate_read_after_activate_shows_new_state
        """
        from test_helpers import (
            align_center_site,
            create_center_with_faculty,
            create_site_payload,
        )
        center, faculty = create_center_with_faculty()
        site = get_success_data(api.create_site(
            center["id"], create_site_payload(), TC))
        align_center_site(center["id"], site["id"])
        before = validate_success(api.get_training_center(center["id"], TC))

        activated = validate_success(
            api.activate_training_center(center["id"], ADMIN))
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == before["version"] + 1

        # The very next read observes the mutation: no lag, no recompute delay.
        after = validate_success(api.get_training_center(center["id"], TC))
        assert after["status"] == "ACTIVE"
        assert after["version"] == activated["version"]
        assert after["updated_at"] >= before["updated_at"]
