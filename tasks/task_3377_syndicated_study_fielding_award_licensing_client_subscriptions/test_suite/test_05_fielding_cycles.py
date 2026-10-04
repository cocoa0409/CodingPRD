"""Fielding lifecycle: close cascade depth, shortfall-gated reopen cycle, and the
conserved response-count partition across the cycle (PRD §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    add_brand,
    add_frame,
    close_fielding,
    create_sample_frame_payload,
    create_study,
    create_study_with_pinned_methodology,
    get_brand_result_for,
    get_frame,
    get_study,
    ingest,
    list_frame_responses,
    open_fielding,
    setup_fielding_study,
    study_goto,
    validate_error,
    validate_success,
    api_client,
    TEST_USERS,
)

FOPS = TEST_USERS["field_ops_headers"]


def _reopen_cycle_ctx():
    """BrandA short (2 of 3), BrandB satisfied (4 of 3); study FIELDING."""
    return setup_fielding_study(
        min_sample=3,
        brands=[
            {"name": "BrandA", "source_type": "PANEL", "target": 4,
             "responses": [{"token": "ra-1", "qual": 8, "feat": 8},
                           {"token": "ra-2", "qual": 8, "feat": 8}]},
            {"name": "BrandB", "source_type": "CUSTOMER_LIST", "target": 4,
             "responses": [{"token": f"rb-{i}", "qual": 7, "feat": 7} for i in range(1, 5)]},
        ],
    )


def test_reopen_reopens_only_shortfall_frames(api, field_ops_headers):
    """PRD §3.3: "On a successful reopen, exactly the shortfall brands' frames flip
    from `CLOSED` back to `OPEN`; frames of brands meeting the minimum stay
    `CLOSED`."

    Design: Difficulty/non_linear_state_machine/study_fielding_reopen_cycle
    """
    ctx = _reopen_cycle_ctx()
    sid = ctx["study"]["id"]
    fa, fb = ctx["frames"]["BrandA"], ctx["frames"]["BrandB"]
    close_fielding(sid)
    reopened = study_goto(sid, "FIELDING")
    assert reopened["status"] == "FIELDING"
    assert get_frame(fa["id"])["status"] == "OPEN", "shortfall brand's frame reopens"
    assert get_frame(fb["id"])["status"] == "CLOSED", "satisfied brand's frame stays CLOSED"


def test_full_reopen_cycle_completes_with_updated_counts(api):
    """PRD §3.3: "Fielding is cyclic by design. From `FIELDING_CLOSED`, from
    `SCORING`, and even from `SCORED`, a `StudyAdmin` may reopen fielding by
    driving the study back to `FIELDING` — but only when at least one brand with a
    frame is in shortfall, meaning its `accepted_n` is below the study's
    `min_sample_per_brand`."

    Design: Difficulty/non_linear_state_machine/study_fielding_reopen_cycle
    """
    ctx = _reopen_cycle_ctx()
    sid = ctx["study"]["id"]
    close_fielding(sid)
    study_goto(sid, "FIELDING")
    ingest(ctx["frames"]["BrandA"]["id"], "ra-3", 8, 8)
    closed_again = study_goto(sid, "FIELDING_CLOSED")
    assert closed_again["status"] == "FIELDING_CLOSED"
    bra = get_brand_result_for(sid, ctx["brands"]["BrandA"]["id"])
    brb = get_brand_result_for(sid, ctx["brands"]["BrandB"]["id"])
    assert bra["accepted_n"] == 3, f"2 originals + ra-3, got {bra['accepted_n']}"
    assert brb["accepted_n"] == 4, f"untouched brand, got {brb['accepted_n']}"


def _dedupe_ctx():
    return setup_fielding_study(
        min_sample=3,
        brands=[{
            "name": "BrandA", "target": 5,
            "responses": [
                {"token": "rt-1", "qual": 10, "feat": 10, "clock": "2026-09-02T00:00:00Z"},
                {"token": "rt-1", "qual": 2, "feat": 2, "clock": "2026-09-03T00:00:00Z"},
                {"token": "rt-2", "qual": 6, "feat": 6},
            ],
        }],
    )


def test_close_cascade_closes_open_frames(api):
    """PRD §3.3: "Closing fielding — driving the study from `FIELDING` to
    `FIELDING_CLOSED` — has no preconditions of its own, but it fires a three-hop
    cascade that materializes the study's provisional standing. In the first hop,
    every `OPEN` sample frame of the study flips to `CLOSED`."

    Design: Difficulty/transitive_cascade/fielding_close_depth3_cascade
    """
    ctx = _dedupe_ctx()
    sid = ctx["study"]["id"]
    frame = ctx["frames"]["BrandA"]
    assert get_frame(frame["id"])["status"] == "OPEN"
    study_goto(sid, "FIELDING_CLOSED")
    # Hop 1: no manual close call was ever issued against the frame endpoint.
    assert get_frame(frame["id"])["status"] == "CLOSED"


def test_close_cascade_sweeps_duplicates_and_snapshots_provisional(api):
    """PRD §3.3: "In the second hop, each frame closure triggers the duplicate
    sweep within that frame's brand ... Every other response in such a sharing
    group flips from `ACCEPTED` to `REJECTED` with `reject_reason` set to
    `DUPLICATE` — and `REJECTED` is terminal for a response; nothing resurrects
    it. In the third hop, each flip recomputes the brand's `BrandResult` ... These
    rows are born with `status` `PROVISIONAL`, and their `final_index`,
    `eligible`, `significance_group`, and `rank_position` are all null until
    scoring compute fills them in."

    Design: Difficulty/transitive_cascade/fielding_close_depth3_cascade
    """
    ctx = _dedupe_ctx()
    sid = ctx["study"]["id"]
    r_lost = ctx["responses"][1]["id"]
    study_goto(sid, "FIELDING_CLOSED")

    rejected = list_frame_responses(ctx["frames"]["BrandA"]["id"], quality_status="REJECTED")
    assert [r["id"] for r in rejected] == [r_lost]
    assert rejected[0]["reject_reason"] == "DUPLICATE"

    br = get_brand_result_for(sid, ctx["brands"]["BrandA"]["id"])
    assert br["provisional_accepted_n"] == 3
    assert br["accepted_n"] == 2
    assert br["provisional_index"] == 600
    assert br["status"] == "PROVISIONAL"
    assert br["final_index"] is None and br["eligible"] is None
    assert br["significance_group"] is None and br["rank_position"] is None


def test_close_reopen_preserves_response_partition(api):
    """PRD §3.3: "Every other response in such a sharing group flips from
    `ACCEPTED` to `REJECTED` with `reject_reason` set to `DUPLICATE` — and
    `REJECTED` is terminal for a response; nothing resurrects it."
    PRD §3.3: "On a successful reopen, exactly the shortfall brands' frames flip
    from `CLOSED` back to `OPEN`; frames of brands meeting the minimum stay
    `CLOSED`."

    Design: Difficulty/compensating_invariant/close_reopen_cycle_conserves_response_totals
    """
    ctx = _dedupe_ctx()
    sid = ctx["study"]["id"]
    close_fielding(sid)
    study_goto(sid, "FIELDING")  # accepted_n 2 < min_sample 3, so reopen is legal

    frame_id = ctx["frames"]["BrandA"]["id"]
    all_rows = list_frame_responses(frame_id)
    accepted = list_frame_responses(frame_id, quality_status="ACCEPTED")
    rejected = list_frame_responses(frame_id, quality_status="REJECTED")
    assert len(all_rows) == 3, f"total ingested, got {len(all_rows)}"
    assert len(accepted) + len(rejected) == len(all_rows), (
        f"partition must be conserved: {len(accepted)} + {len(rejected)} != {len(all_rows)}"
    )
    assert (len(accepted), len(rejected)) == (2, 1)


def test_reopen_does_not_resurrect_swept_duplicate(api):
    """PRD §3.3: "`REJECTED` is terminal for a response; nothing resurrects it."
    PRD §3.3: "Fielding is cyclic by design. From `FIELDING_CLOSED`, from
    `SCORING`, and even from `SCORED`, a `StudyAdmin` may reopen fielding by
    driving the study back to `FIELDING` ..."

    Design: Difficulty/compensating_invariant/close_reopen_cycle_conserves_response_totals
    """
    ctx = _dedupe_ctx()
    sid = ctx["study"]["id"]
    r_lost = ctx["responses"][1]["id"]
    close_fielding(sid)
    study_goto(sid, "FIELDING")

    rejected = list_frame_responses(ctx["frames"]["BrandA"]["id"], quality_status="REJECTED")
    assert [r["id"] for r in rejected] == [r_lost], "the swept duplicate stays REJECTED"
    assert rejected[0]["reject_reason"] == "DUPLICATE"
    br = get_brand_result_for(sid, ctx["brands"]["BrandA"]["id"])
    assert br["accepted_n"] == 2, f"no count drift across the cycle, got {br['accepted_n']}"
    assert get_study(sid)["status"] == "FIELDING"
    assert get_frame(ctx["frames"]["BrandA"]["id"])["status"] == "OPEN"


def test_fielding_without_frames_returns_no_frames(api, study_admin_headers):
    """PRD §3.2: "Opening fielding — driving the study from `DESIGN_LOCKED` to
    `FIELDING` — requires that at least one sample frame exist for the study; an
    attempt with no frames fails with `ERR_NO_FRAMES`."

    Design: Corner/errors/fielding_without_frames_returns_no_frames
    """
    ctx = create_study_with_pinned_methodology(min_sample_per_brand=3)
    sid = ctx["study"]["id"]
    resp = api.study_state(sid, {"to_status": "FIELDING"}, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NO_FRAMES)
    assert get_study(sid)["status"] == "DESIGN_LOCKED"


def test_duplicate_frame_returns_409(api, field_ops_headers):
    """PRD §3.2: "Frame creation is only permitted while the study is
    `DESIGN_LOCKED`, and a study may hold at most one frame per brand — a second
    frame for the same (`study_id`, `brand_id`) pair is rejected with
    `ERR_DUPLICATE_FRAME`."

    Design: Corner/validations/duplicate_frame_returns_409
    """
    ctx = create_study_with_pinned_methodology(min_sample_per_brand=1)
    sid = ctx["study"]["id"]
    brand = add_brand("BrandA")
    add_frame(sid, brand["id"], source_type="PANEL", target_completes=3)

    resp = api.create_sample_frame(
        create_sample_frame_payload(sid, brand["id"], source_type="CUSTOMER_LIST",
                                    target_completes=5),
        FOPS,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FRAME)
    frames = validate_success(api.list_sample_frames(FOPS, params={"study_id": sid}))
    assert len(frames) == 1, f"only one frame may exist for (study, brand), got {len(frames)}"


def test_frame_create_requires_design_locked(api, field_ops_headers):
    """PRD §3.2: "Frame creation is only permitted while the study is
    `DESIGN_LOCKED`, and a study may hold at most one frame per brand — a second
    frame for the same (`study_id`, `brand_id`) pair is rejected with
    `ERR_DUPLICATE_FRAME`."
    PRD §2.8: "State gates — the entity is in a state where the requested
    transition or action is defined, including cross-entity gates ..."

    Design: Corner/validations/frame_create_requires_design_locked
    """
    study = create_study(min_sample_per_brand=1)
    brand = add_brand("BrandA")
    assert study["status"] == "DRAFT"
    resp = api.create_sample_frame(
        create_sample_frame_payload(study["id"], brand["id"], source_type="PANEL",
                                    target_completes=3),
        FOPS,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    frames = validate_success(api.list_sample_frames(FOPS, params={"study_id": study["id"]}))
    assert frames == [], "no frame may be created while the study is DRAFT"
