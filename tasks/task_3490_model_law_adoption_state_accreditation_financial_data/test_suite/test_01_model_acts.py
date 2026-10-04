"""Model act lifecycle: creation defaults, exposure windows, ballot gates,
publication, and read-after-write consistency."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_model_act,
    constants,
    factories,
    fixtures,
    make_actuary_headers,
    validate_error,
    validate_success,
)

STAFF = TEST_USERS["association_staff_headers"]


class TestModelActLifecycle:
    def test_model_act_creation_defaults(self, api):
        """PRD §3.1: "A new act starts in `DRAFTING` status with `published_at` null and both vote counters, `votes_cast` and `favorable_votes`, at zero."
        PRD §3.1: "The optional `is_core` flag defaults to false and marks the act as counting toward each state's core-act coverage (§3.2)."
        PRD §2.4: "`id`, a server-minted UUID with no type prefix".

        Design: Corner/entities/model_act_creation_defaults
        """
        resp = api.create_model_act(
            factories.model_act_payload(
                model_code="MDL-800",
                version_label="v1",
                title="Model Annuity Act",
                act_type="MODEL_LAW",
                committee_name="A Committee",
                is_core=factories.DROP,
            ),
            STAFF,
        )
        data = validate_success(resp, 201)
        assert_model_act(data)
        assert data["status"] == "DRAFTING", "new act must start DRAFTING"
        assert data["votes_cast"] == 0
        assert data["favorable_votes"] == 0
        assert data["is_core"] is False, "is_core defaults to false when omitted"
        assert data["published_at"] is None, "published_at null until published"

    def test_act_happy_path_full_lifecycle(self, api):
        """PRD §3.1: "The first draft of an act is numbered `exposure_number` 1 and moves the act from `DRAFTING` to `EXPOSURE_OPEN`"
        PRD §3.1: "When the draft being closed was the act's last remaining `OPEN` draft, the act itself advances from `EXPOSURE_OPEN` to `BALLOTING`"
        PRD §3.1: "On a pass the act moves from `BALLOTING` to `ADOPTED`, its counters are recomputed from the `CAST` ballots, and its `version` increments."
        PRD §3.2: "Publication stamps `published_at` with the current logical clock, moves the act to `PUBLISHED`, increments its `version`"
        PRD §3.1: "the draft must still be `OPEN` (`ERR_EXPOSURE_DRAFT_NOT_OPEN`, 409)"

        Design: Corner/state_machines/act_happy_path_full_lifecycle
        """
        state = fixtures.create_state(api, code="CA")
        act = fixtures.create_model_act(api, model_code="MDL-810", version_label="v1")
        draft = fixtures.open_exposure_draft(api, act["id"])
        assert draft["exposure_number"] == 1
        assert draft["status"] == "OPEN"
        act = fixtures.read_model_act(api, act["id"])
        assert act["status"] == "EXPOSURE_OPEN"
        closed = fixtures.close_exposure_draft(
            api, draft["id"], window_end=constants.DEFAULT_EXPOSURE_END
        )
        assert closed["status"] == "CLOSED"
        act = fixtures.read_model_act(api, act["id"])
        assert act["status"] == "BALLOTING"
        fixtures.cast_ballot(api, act["id"], state, "YEA")
        adopted = validate_success(api.close_ballot(act["id"], STAFF))
        assert adopted["status"] == "ADOPTED"
        published = validate_success(api.publish_model_act(act["id"], STAFF))
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] == constants.DEFAULT_EXPOSURE_END, (
            "published_at must read the logical clock at publish time "
            "(advanced to the window end for the close)"
        )
        resp = api.close_exposure_draft(draft["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_EXPOSURE_DRAFT_NOT_OPEN)

    def test_act_action_state_guards(self, api):
        """PRD §3.1: "the act must be in `BALLOTING` (`ERR_ACT_NOT_BALLOTING`, 409 — the same rejection covers the ballot-closing action below)"
        PRD §3.2: "Staff may publish only an act in `ADOPTED` status — any other status is rejected with `ERR_ACT_NOT_ADOPTED` (409)."

        Design: Corner/state_machines/act_action_state_guards
        """
        act = fixtures.create_model_act(
            api, model_code="MDL-811", version_label="v1", act_type="MODEL_REGULATION"
        )
        resp = api.close_ballot(act["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_ACT_NOT_BALLOTING)
        resp = api.publish_model_act(act["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_ACT_NOT_ADOPTED)
        act = fixtures.read_model_act(api, act["id"])
        assert act["status"] == "DRAFTING", "rejected actions must not move the act"

    def test_draft_close_before_window_end_rejected(self, api):
        """PRD §3.1: "Closing a draft is also staff work and checks two conditions in order: the draft must still be `OPEN` (`ERR_EXPOSURE_DRAFT_NOT_OPEN`, 409), and the logical clock must have reached its `comment_window_end` (`ERR_COMMENT_WINDOW_OPEN`, 409)."
        PRD §2.4: "Before any request has been processed, the clock reads exactly 2026-09-01T00:00:00Z."

        Design: Corner/state_machines/draft_close_before_window_end_rejected
        """
        act = fixtures.create_model_act(api, model_code="MDL-812", version_label="v1")
        draft = fixtures.open_exposure_draft(api, act["id"])
        # The clock still reads its start instant, before the window end.
        resp = api.close_exposure_draft(draft["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_COMMENT_WINDOW_OPEN)
        act = fixtures.read_model_act(api, act["id"])
        assert act["status"] == "EXPOSURE_OPEN", "a rejected close must not move the act"

    def test_comment_window_too_short_rejected(self, api):
        """PRD §3.1: "then the window length must span at least 30 days, otherwise `ERR_COMMENT_WINDOW_TOO_SHORT` (422)"

        Design: Corner/validations/comment_window_too_short_rejected
        """
        act = fixtures.create_model_act(api, model_code="MDL-832", version_label="v1")
        resp = api.create_exposure_draft(
            factories.exposure_draft_payload(
                act["id"],
                comment_window_start="2026-09-01T00:00:00Z",
                comment_window_end="2026-09-21T00:00:00Z",
            ),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_COMMENT_WINDOW_TOO_SHORT)
        act = fixtures.read_model_act(api, act["id"])
        assert act["status"] == "DRAFTING", "a rejected draft must not move the act"

    def test_draft_create_state_beats_window_constraint(self, api):
        """PRD §3.1: "Three checks guard draft creation and are evaluated in this order: first the act must be in `DRAFTING` or `EXPOSURE_OPEN` status, otherwise the request fails with `ERR_ACT_NOT_OPEN_FOR_EXPOSURE` (409); then the window length must span at least 30 days, otherwise `ERR_COMMENT_WINDOW_TOO_SHORT` (422)"

        Design: Difficulty/priority_pair_validation_conflict/draft_create_state_beats_window_constraint
        """
        act = fixtures.create_model_act(
            api, model_code="MDL-701", version_label="v1", act_type="MODEL_REGULATION"
        )
        fixtures.move_act_to_balloting(api, act["id"])
        # The act is BALLOTING and the proposed window is also too short (10
        # days); the act-state gate is evaluated first and wins.
        resp = api.create_exposure_draft(
            factories.exposure_draft_payload(
                act["id"],
                comment_window_start="2026-11-01T00:00:00Z",
                comment_window_end="2026-11-11T00:00:00Z",
            ),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_ACT_NOT_OPEN_FOR_EXPOSURE)

    def test_exposure_window_half_open_adjacency(self, api):
        """PRD §3.1: "finally the new window must not intersect the window of any other existing draft of the same act in any status, otherwise `ERR_EXPOSURE_WINDOW_OVERLAP` (409) — bare adjacency, where the new start equals an existing end, does not count as an intersection."
        PRD §3.1: "each additional draft takes the next sequential number — one more than the count of the act's prior drafts in any status — and leaves the act in `EXPOSURE_OPEN`"

        Design: Difficulty/resource_temporal_overlap/exposure_window_half_open_adjacency
        """
        act = fixtures.create_model_act(
            api, model_code="MDL-704", version_label="v1", act_type="MODEL_REGULATION"
        )
        fixtures.open_exposure_draft(
            api,
            act["id"],
            start="2026-09-01T00:00:00Z",
            end="2026-10-01T00:00:00Z",
        )
        # Adjacent draft: start == prior end is legal under half-open windows.
        resp = api.create_exposure_draft(
            factories.exposure_draft_payload(
                act["id"],
                comment_window_start="2026-10-01T00:00:00Z",
                comment_window_end="2026-10-31T00:00:00Z",
            ),
            STAFF,
        )
        second = validate_success(resp, 201)
        assert second["exposure_number"] == 2
        assert second["status"] == "OPEN"
        # Intersecting draft: 2026-10-15 lies inside [2026-10-01, 2026-10-31).
        resp = api.create_exposure_draft(
            factories.exposure_draft_payload(
                act["id"],
                comment_window_start="2026-10-15T00:00:00Z",
                comment_window_end="2026-11-15T00:00:00Z",
            ),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_EXPOSURE_WINDOW_OVERLAP)

    def test_immediate_read_after_write(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_read_after_write
        """
        created = validate_success(
            api.create_model_act(
                factories.model_act_payload(
                    model_code="MDL-870",
                    version_label="v1",
                    title="Model Immediate Act",
                    act_type="MODEL_REGULATION",
                    committee_name="B Committee",
                    is_core=True,
                ),
                STAFF,
            ),
            201,
        )
        # A different role reads the act in the immediately following request.
        read = validate_success(
            api.get_model_act(created["id"], make_actuary_headers("actuary-7"))
        )
        assert read["title"] == "Model Immediate Act"
        assert read["status"] == "DRAFTING"
        assert read["is_core"] is True
