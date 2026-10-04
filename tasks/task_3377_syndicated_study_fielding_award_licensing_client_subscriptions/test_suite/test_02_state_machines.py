"""Study/license state machine structure: invalid edges, terminal lockdown,
cascade side effects, and the re-pin happy path (PRD §2.8, §3.1-§3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    add_brand,
    add_frame,
    assert_license,
    close_fielding,
    create_study,
    create_study_with_pinned_methodology,
    get_license,
    get_study,
    license_goto,
    list_awards_for,
    open_fielding,
    quote_license,
    register_client,
    setup_awards_set_study,
    setup_fielding_study,
    study_goto,
    validate_error,
    validate_success,
    api_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["study_admin_headers"]
ML = TEST_USERS["methodology_lead_headers"]
FOPS = TEST_USERS["field_ops_headers"]


def test_draft_to_fielding_returns_invalid_state(api, study_admin_headers):
    """PRD §3.2: "Opening fielding — driving the study from `DESIGN_LOCKED` to
    `FIELDING` — requires that at least one sample frame exist for the study; an
    attempt with no frames fails with `ERR_NO_FRAMES`."
    PRD §2.8: "State gates — the entity is in a state where the requested
    transition or action is defined, including cross-entity gates ..."

    Design: Corner/state_machines/draft_to_fielding_returns_invalid_state
    """
    study = create_study()
    resp = api.study_state(study["id"], {"to_status": "FIELDING"}, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_study(study["id"])["status"] == "DRAFT"


def test_design_locked_reachable_only_via_pin(api, study_admin_headers):
    """PRD §3.1: "There is no other road into `DESIGN_LOCKED`: asking the study
    state endpoint for `to_status` of `DESIGN_LOCKED` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/design_locked_reachable_only_via_pin
    """
    study = create_study()
    resp = api.study_state(study["id"], {"to_status": "DESIGN_LOCKED"}, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_study(study["id"])["status"] == "DRAFT"


def test_cancelled_study_is_terminal(api, study_admin_headers):
    """PRD §3.3: "Once fielding has closed, cancellation is impossible, and
    `PUBLISHED` and `CANCELLED` are the study's terminal states."
    PRD §2.8: "State gates — the entity is in a state where the requested
    transition or action is defined ..."

    Design: Corner/state_machines/cancelled_study_is_terminal
    """
    study = create_study()
    study_goto(study["id"], "CANCELLED")
    resp = api.study_state(study["id"], {"to_status": "FIELDING"}, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_study(study["id"])["status"] == "CANCELLED"


def test_cancel_from_fielding_closes_open_frames(api, field_ops_headers):
    """PRD §3.3: "A `StudyAdmin` may drive a study from `DRAFT`, `DESIGN_LOCKED`,
    or `FIELDING` to `CANCELLED`; cancelling while fielding is open first closes
    every `OPEN` frame."

    Design: Corner/state_machines/cancel_from_fielding_closes_open_frames
    """
    ctx = create_study_with_pinned_methodology(min_sample_per_brand=3)
    sid = ctx["study"]["id"]
    ba = add_brand("BrandA")
    bb = add_brand("BrandB")
    fa = add_frame(sid, ba["id"], source_type="PANEL", target_completes=4)
    fb = add_frame(sid, bb["id"], source_type="CUSTOMER_LIST", target_completes=4)
    open_fielding(sid)

    cancelled = study_goto(sid, "CANCELLED")
    assert cancelled["status"] == "CANCELLED"
    closed = validate_success(
        api_client.list_sample_frames(FOPS, params={"study_id": sid, "status": "CLOSED"})
    )
    closed_ids = {row["id"] for row in closed}
    assert closed_ids == {fa["id"], fb["id"]}, (
        f"both OPEN frames must be closed by the cancel cascade, got {closed_ids}"
    )


def test_repin_supersedes_previous_version(api):
    """PRD §3.1: "On success, four things happen at once: any previously `PINNED`
    version of the same study flips to `SUPERSEDED`; the study's
    `active_methodology_id` is set to the newly pinned version; the pinning actor's
    `X-User-ID` is recorded as the version's `pinned_by_user_id`; and the study's
    `version` increments by 1, taking the study from `DRAFT` to `DESIGN_LOCKED`
    (a study already in `DESIGN_LOCKED` stays there while its `version` still
    increments)."

    Design: Corner/state_machines/repin_supersedes_previous_version
    """
    ctx = create_study_with_pinned_methodology(min_sample_per_brand=3)
    study, mv1 = ctx["study"], ctx["mv"]
    assert study["status"] == "DESIGN_LOCKED" and study["version"] == 2

    mv2 = validate_success(
        api_client.create_methodology_version(
            {
                "study_id": study["id"],
                "change_class": "ADJUSTED",
                "change_notes": "rebalanced weights",
                "min_duration_seconds": 200,
                "straightline_min_items": 12,
                "pooled_sd_1000": 60,
                "z_value": 1.96,
                "tie_epsilon": 3,
                "factors": [
                    {"code": "QUAL", "name": "Quality & Reliability", "weight_bp": 5000, "ordinal": 1},
                    {"code": "FEAT", "name": "Features & Controls", "weight_bp": 5000, "ordinal": 2},
                ],
            },
            ML,
        ),
        expected_status=201,
    )
    pinned2 = validate_success(
        api_client.pin_methodology_version(
            mv2["id"], {"expected_study_version": study["version"]}, ML
        )
    )
    assert pinned2["status"] == "PINNED"
    mv1_after = validate_success(api_client.get_methodology_version(mv1["id"], ML))
    assert mv1_after["status"] == "SUPERSEDED", f"prior version must be SUPERSEDED, got {mv1_after['status']}"
    study_after = get_study(study["id"])
    assert study_after["active_methodology_id"] == mv2["id"]
    assert study_after["version"] == 3, f"create 1, pin 2, repin 3 — got {study_after['version']}"
    assert study_after["status"] == "DESIGN_LOCKED"


def test_withdrawn_license_is_terminal(api, licensing_manager_headers):
    """PRD §3.7: "`REVOKED`, `WITHDRAWN`, and `EXPIRED` are terminal, and reaching
    `REVOKED` anywhere in a client's history permanently arms the 1.25 multiplier
    on that client's future activations."
    PRD §3.6: "the license is born `QUOTED` with `fee_final_cents`, `activated_at`,
    and `expires_at` all null and `suspension_count` at 0."

    Design: Corner/state_machines/withdrawn_license_is_terminal
    """
    ctx = setup_awards_set_study(
        min_sample=1,
        brands=[{"name": "BrandA", "responses": [{"token": "rt-1", "qual": 9, "feat": 8}]}],
    )
    award = ctx["awards"][0]
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    lic = quote_license(award["id"], client["id"], tier="DIGITAL", term_months=12, markets_count=1)
    license_goto(lic["id"], "WITHDRAWN")

    resp = api_client.license_state(lic["id"], {"to_status": "ACTIVE"}, licensing_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_license(lic["id"])
    assert_license(after)
    assert after["status"] == "WITHDRAWN"
    assert after["fee_final_cents"] is None


def test_reopen_without_shortfall_returns_no_shortfall(api, study_admin_headers):
    """PRD §3.3: "From `FIELDING_CLOSED`, from `SCORING`, and even from `SCORED`, a
    `StudyAdmin` may reopen fielding by driving the study back to `FIELDING` — but
    only when at least one brand with a frame is in shortfall, meaning its
    `accepted_n` is below the study's `min_sample_per_brand`. With no shortfall
    brand the reopen is rejected with `ERR_NO_SHORTFALL`."

    Design: Corner/state_machines/reopen_without_shortfall_returns_no_shortfall
    """
    ctx = setup_fielding_study(
        min_sample=1,
        brands=[{"name": "BrandA", "responses": [{"token": "rt-1", "qual": 9, "feat": 8}]}],
    )
    sid = ctx["study"]["id"]
    close_fielding(sid)
    resp = api.study_state(sid, {"to_status": "FIELDING"}, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NO_SHORTFALL)
    assert get_study(sid)["status"] == "FIELDING_CLOSED"


def test_determine_twice_returns_invalid_state(api, awards_officer_headers):
    """PRD §2.8: "State gates — ... computing requires `SCORING`, determining
    requires `SCORED`, publishing requires `AWARDS_SET` ..."
    PRD §3.5: "The determination returns the `study_id` and the `award_count`, and
    moves the study from `SCORED` to `AWARDS_SET`."

    Design: Corner/state_machines/determine_twice_returns_invalid_state
    """
    ctx = setup_awards_set_study(
        min_sample=1,
        brands=[{"name": "BrandA", "responses": [{"token": "rt-1", "qual": 9, "feat": 8}]}],
    )
    sid = ctx["study"]["id"]
    assert ctx["determine"]["award_count"] == 1
    resp = api.determine_awards(sid, awards_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    awards = list_awards_for(sid)
    assert len(awards) == 1, f"still exactly one award must exist, got {len(awards)}"
