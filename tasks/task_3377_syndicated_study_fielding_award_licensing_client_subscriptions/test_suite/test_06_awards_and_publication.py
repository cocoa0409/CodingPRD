"""Award determination cascade, segregation of duties, embargo boundary, and the
state-before-temporal validation order on publish (PRD §2.5, §2.8, §3.5)."""
from test_helpers import (
    U_AWARDS_OFFICER,
    U_METHODOLOGY_LEAD,
    ApiErrorId,
    determine_awards,
    get_brand_result_for,
    get_study,
    list_awards_for,
    make_awards_officer_headers,
    set_clock,
    setup_awards_set_study,
    setup_scored_study,
    study_goto,
    validate_error,
    api_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["study_admin_headers"]
AO = TEST_USERS["awards_officer_headers"]

_ONE_BRAND = [{"name": "BrandA", "responses": [{"token": "rt-1", "qual": 9, "feat": 8}]}]


def test_determine_creates_embargoed_award(api):
    """PRD §3.5: "For every winner the server creates an `Award` carrying the
    `study_id` and `brand_id`, copies `rank_position` and `significance_group`
    from the winning result (1 and 1 respectively by construction), and sets
    `status` `EMBARGOED` with `published_at` null; each created award in turn
    flips its winning `BrandResult` from `FINAL` to `AWARDED`."

    Design: Difficulty/transitive_cascade/award_determination_depth2_cascade
    """
    ctx = setup_awards_set_study(min_sample=1, brands=_ONE_BRAND)
    sid = ctx["study"]["id"]
    assert ctx["determine"]["award_count"] == 1
    assert ctx["determine"]["study_id"] == sid
    award = ctx["awards"][0]
    assert award["brand_id"] == ctx["brands"]["BrandA"]["id"]
    assert award["rank_position"] == 1 and award["significance_group"] == 1
    assert award["status"] == "EMBARGOED"
    assert award["published_at"] is None


def test_determine_flips_winning_brand_result_to_awarded(api):
    """PRD §3.5: "each created award in turn flips its winning `BrandResult` from
    `FINAL` to `AWARDED`. The determination returns the `study_id` and the
    `award_count`, and moves the study from `SCORED` to `AWARDS_SET`."

    Design: Difficulty/transitive_cascade/award_determination_depth2_cascade
    """
    ctx = setup_awards_set_study(min_sample=1, brands=_ONE_BRAND)
    sid = ctx["study"]["id"]
    br = get_brand_result_for(sid, ctx["brands"]["BrandA"]["id"])
    assert br["status"] == "AWARDED", f"was FINAL before determination, got {br['status']}"
    assert get_study(sid)["status"] == "AWARDS_SET"


def test_publish_one_second_before_embargo_rejected(api, study_admin_headers):
    """PRD §3.5: "Publication is the last gate. A `StudyAdmin` drives the study
    from `AWARDS_SET` to `PUBLISHED`, permitted only when the logical clock has
    reached the study's `embargo_lift_at` — equality lifts the embargo, and a
    strictly earlier clock is rejected with `ERR_EMBARGO_ACTIVE`."

    Design: Difficulty/boundary_precision_check/embargo_lift_exact_instant
    """
    ctx = setup_awards_set_study(min_sample=1, brands=_ONE_BRAND)
    sid = ctx["study"]["id"]
    set_clock("2026-10-14T23:59:59Z")
    resp = api.study_state(sid, {"to_status": "PUBLISHED"}, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_EMBARGO_ACTIVE)
    assert get_study(sid)["status"] == "AWARDS_SET"


def test_publish_at_exact_lift_instant_succeeds(api):
    """PRD §3.5: "permitted only when the logical clock has reached the study's
    `embargo_lift_at` — equality lifts the embargo, and a strictly earlier clock
    is rejected with `ERR_EMBARGO_ACTIVE`. The publish cascade flips every
    `EMBARGOED` award of the study to `PUBLISHED`, stamps each award's
    `published_at` with the clock, and stamps the study's own `published_at` the
    same way."

    Design: Difficulty/boundary_precision_check/embargo_lift_exact_instant
    """
    ctx = setup_awards_set_study(min_sample=1, brands=_ONE_BRAND)
    sid = ctx["study"]["id"]
    set_clock("2026-10-15T00:00:00Z")
    published = study_goto(sid, "PUBLISHED")
    assert published["status"] == "PUBLISHED"
    assert published["published_at"].startswith("2026-10-15T00:00:00"), (
        f"published_at must be stamped with the logical clock, got {published['published_at']}"
    )
    award = list_awards_for(sid)[0]
    assert award["status"] == "PUBLISHED", "the publish cascade flips every award"
    assert award["published_at"].startswith("2026-10-15T00:00:00")


def test_publish_from_scored_reports_state_error_not_embargo(api, study_admin_headers):
    """PRD §2.8: "When a request is malformed in more than one way, the server
    reports a single error, and the order in which checks run is fixed"
    PRD §2.8: "5. **State gates** — the entity is in a state where the requested
    transition or action is defined, including cross-entity gates (... publishing
    requires `AWARDS_SET` ...)." (temporal gates follow at item 7)

    Design: Difficulty/priority_pair_validation_conflict/publish_state_error_beats_embargo_temporal
    """
    ctx = setup_scored_study(min_sample=1, brands=_ONE_BRAND)
    sid = ctx["study"]["id"]
    # Clock strictly before embargo: BOTH the state gate and the temporal gate fail.
    set_clock("2026-10-10T00:00:00Z")
    resp = api.study_state(sid, {"to_status": "PUBLISHED"}, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_study(sid)["status"] == "SCORED"


def test_publish_from_scored_reports_state_error_even_after_embargo(api, study_admin_headers):
    """PRD §2.8: "5. **State gates** — the entity is in a state where the requested
    transition or action is defined, including cross-entity gates (... publishing
    requires `AWARDS_SET` ...)."
    PRD §3.5: "Publication is the last gate. A `StudyAdmin` drives the study from
    `AWARDS_SET` to `PUBLISHED` ..."

    Design: Difficulty/priority_pair_validation_conflict/publish_state_error_beats_embargo_temporal
    """
    ctx = setup_scored_study(min_sample=1, brands=_ONE_BRAND)
    sid = ctx["study"]["id"]
    # Clock past embargo: the temporal gate passes, so only the state gate can fire.
    set_clock("2026-10-20T00:00:00Z")
    resp = api.study_state(sid, {"to_status": "PUBLISHED"}, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_study(sid)["status"] == "SCORED"


def test_determine_by_methodology_pinner_returns_sod_conflict(api):
    """PRD §3.5: "Two preconditions guard the ceremony, checked in the priority
    order of §2.8. First, segregation of duties: the acting `X-User-ID` must not
    equal the `pinned_by_user_id` recorded on the study's active methodology
    version — the person who set the ruler may not crown the winners, and a
    conflict is rejected with `ERR_SOD_CONFLICT` (HTTP 403). Second, at least one
    `BrandResult` must have `eligible` true; otherwise the determination is
    rejected with `ERR_NO_ELIGIBLE_BRAND` and no awards are created."

    Design: Difficulty/priority_pair_validation_conflict/determine_sod_beats_no_eligible
    """
    # Zero eligible brands AND the caller is the pinner: SoD (priority 6) fires first.
    ctx = setup_scored_study(
        min_sample=3,
        brands=[{"name": "BrandA", "target": 4,
                 "responses": [{"token": "ra-1", "qual": 8, "feat": 8},
                               {"token": "ra-2", "qual": 8, "feat": 8}]}],
    )
    sid = ctx["study"]["id"]
    resp = api_client.determine_awards(sid, make_awards_officer_headers(U_METHODOLOGY_LEAD))
    validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT)
    assert get_study(sid)["status"] == "SCORED"
    assert list_awards_for(sid) == [], "no award may be created on a rejected determination"


def test_sod_conflict_fires_even_with_eligible_brand(api):
    """PRD §3.5: "First, segregation of duties: the acting `X-User-ID` must not
    equal the `pinned_by_user_id` recorded on the study's active methodology
    version — the person who set the ruler may not crown the winners, and a
    conflict is rejected with `ERR_SOD_CONFLICT` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/determine_sod_beats_no_eligible
    """
    # One eligible brand; only the SoD precondition fails.
    ctx = setup_scored_study(min_sample=1, brands=_ONE_BRAND)
    sid = ctx["study"]["id"]
    assert ctx["compute"]["eligible_count"] == 1
    resp = api_client.determine_awards(sid, make_awards_officer_headers(U_METHODOLOGY_LEAD))
    validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT)
    assert get_study(sid)["status"] == "SCORED"
    assert list_awards_for(sid) == []


def test_determine_without_eligible_brand_returns_409(api, awards_officer_headers):
    """PRD §3.5: "Second, at least one `BrandResult` must have `eligible` true;
    otherwise the determination is rejected with `ERR_NO_ELIGIBLE_BRAND` and no
    awards are created."

    Design: Corner/validations/determine_without_eligible_brand_returns_409
    """
    # SoD satisfied (determiner u_ao_001 != pinner u_ml_001); zero eligible brands.
    ctx = setup_scored_study(
        min_sample=3,
        brands=[{"name": "BrandA", "target": 4,
                 "responses": [{"token": "ra-1", "qual": 8, "feat": 8},
                               {"token": "ra-2", "qual": 8, "feat": 8}]}],
    )
    sid = ctx["study"]["id"]
    assert ctx["compute"]["eligible_count"] == 0
    resp = api.determine_awards(sid, awards_officer_headers)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_BRAND)
    assert get_study(sid)["status"] == "SCORED"
    assert list_awards_for(sid) == []


def test_default_logical_epoch_gates_publish(api, study_admin_headers):
    """PRD §2.5: "Before any administrative call sets it, the logical clock reads
    exactly `2026-09-01T00:00:00Z`; it never falls back to wall-clock time."
    PRD §3.5: "permitted only when the logical clock has reached the study's
    `embargo_lift_at` — equality lifts the embargo, and a strictly earlier clock
    is rejected with `ERR_EMBARGO_ACTIVE`."

    Design: Corner/complexity_layers/default_logical_epoch_gates_publish
    """
    # The whole chain runs with NO clock call at all; embargo is 2026-10-15.
    ctx = setup_awards_set_study(min_sample=1, brands=_ONE_BRAND, set_default_clock=False)
    sid = ctx["study"]["id"]
    resp = api.study_state(sid, {"to_status": "PUBLISHED"}, study_admin_headers)
    validate_error(resp, ApiErrorId.ERR_EMBARGO_ACTIVE)
    assert get_study(sid)["status"] == "AWARDS_SET"
