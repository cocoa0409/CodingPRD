"""Conditional, cascading and temporal rules: the penalty ceiling, the retired pin
chain, the comment window and the correction round limit."""
from test_helpers import (
    assert_instant,
    assert_score,
    claim_correction,
    create_correction_request_payload,
    create_draft_methodology,
    create_organization,
    create_public_comment_payload,
    create_rating_cycle_payload,
    decide_correction,
    evaluate_governance_profile,
    file_complaint,
    file_correction,
    file_public_comment,
    make_public_headers,
    open_comment,
    close_comment,
    open_org_review,
    read_complaint,
    read_cycle,
    read_organization,
    resolve_complaint,
    resolve_complaint_payload,
    score_cycle,
    set_clock,
    setup_cycle_in_org_review,
    setup_transition_grant,
    triage_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_penalty_ceiling_comes_from_the_investigated_tier_not_the_stored_intake_tier(
    api, analyst_headers
):
    """The intake tier is LOW and caps at 5, the investigated tier is MEDIUM and caps at
    10, and the accepted resolve submits exactly 10.

    PRD §2.8: "28. **Penalty range.** On a substantiated finding, `penalty_points` is an integer between 1 and 15 inclusive and does not exceed the ceiling for the severity tier derived from the *investigated* credibility score; on an unsubstantiated finding `penalty_points` is absent or zero. Otherwise `ERR_PENALTY_POINTS_RANGE` (422), on `POST /complaints/{complaint_id}/resolve`."

    PRD §3.8: "It requires `penalty_points` to be absent or 0, otherwise `ERR_PENALTY_POINTS_RANGE`; an unsubstantiated complaint cannot cost the charity a point."

    PRD §3.8: "When that candidate set is empty the field stays null, hops two through four are simply skipped, and **no error is raised** — a substantiated complaint against a charity with no open cycle is recorded, counts toward future pattern scoring, and penalises nothing."

    Design: Corner/validations/the_penalty_ceiling_is_read_from_the_investigated_tier_not_the_intake_tier
    """
    harbor = create_organization()
    lakeside = create_organization(
        legal_name="Lakeside Youth Trust",
        ein="222222222",
        fiscal_year_end_month=6,
        contact_email="ops@lakesideyouth.org",
    )

    solicitation = file_complaint(
        harbor["id"],
        headers=make_public_headers("public-1"),
        complainant_kind="BENEFICIARY",
        category="SOLICITATION_PRACTICE",
        narrative="The telephone appeal claimed 90 percent of my gift reaches the food programme",
        corroborating_document_count=0,
    )
    at_intake = triage_complaint(
        solicitation["id"], "INVESTIGATE", triage_note="worth a look at the script"
    )
    assert_score(at_intake["credibility_score"], 45.00, "intake credibility_score")
    assert at_intake["severity_tier"] == "LOW"

    transparency = file_complaint(
        lakeside["id"],
        headers=make_public_headers("public-2"),
        complainant_kind="DONOR",
        category="TRANSPARENCY",
        narrative="The annual report is two years out of date",
    )
    triage_complaint(
        transparency["id"], "INVESTIGATE", triage_note="check the filing cabinet"
    )
    other = file_complaint(
        lakeside["id"],
        headers=make_public_headers("public-3"),
        complainant_kind="DONOR",
        category="OTHER",
        narrative="Nobody answered my letter",
    )
    triage_complaint(other["id"], "INVESTIGATE", triage_note="routine")

    finding_note = "the script overstated the programme share"
    for penalty_points, finding in ((16, "SUBSTANTIATED"), (0, "SUBSTANTIATED"), (11, "SUBSTANTIATED")):
        validate_error(
            api.resolve_complaint(
                solicitation["id"],
                resolve_complaint_payload(
                    finding, penalty_points=penalty_points, finding_note=finding_note
                ),
                analyst_headers,
            ),
            "ERR_PENALTY_POINTS_RANGE",
            422,
        )
    validate_error(
        api.resolve_complaint(
            solicitation["id"],
            resolve_complaint_payload(
                "UNSUBSTANTIATED", penalty_points=3, finding_note="no misstatement found"
            ),
            analyst_headers,
        ),
        "ERR_PENALTY_POINTS_RANGE",
        422,
    )

    resolved = resolve_complaint(
        solicitation["id"],
        "SUBSTANTIATED",
        penalty_points=10,
        finding_note=finding_note,
    )
    assert resolved["status"] == "SUBSTANTIATED"
    assert_score(resolved["credibility_score"], 55.00, "investigated credibility_score")
    assert resolved["severity_tier"] == "MEDIUM"
    assert resolved["penalty_points_applied"] == 10
    assert resolved["penalized_rating_cycle_id"] is None
    assert read_complaint(solicitation["id"], analyst_headers)["version"] == 3

    omitted = resolve_complaint(
        transparency["id"],
        "UNSUBSTANTIATED",
        finding_note="the report was published on time",
    )
    assert omitted["status"] == "UNSUBSTANTIATED"
    assert omitted["penalty_points_applied"] == 0
    explicit_zero = resolve_complaint(
        other["id"],
        "UNSUBSTANTIATED",
        penalty_points=0,
        finding_note="correspondence backlog, no misconduct",
    )
    assert explicit_zero["status"] == "UNSUBSTANTIATED"
    assert_score(explicit_zero["credibility_score"], 20.00, "credibility_score")

    assert read_organization(harbor["id"])["substantiated_complaint_count"] == 1
    assert read_organization(lakeside["id"])["substantiated_complaint_count"] == 0


def test_a_retired_pin_is_handed_down_the_chain_and_the_grant_is_spent_exactly_once(
    api, admin_headers, analyst_headers
):
    """Four outcomes off one retirement: the flagless pin answers check 12, the
    not-yet-effective successor answers 15, the flagged pin succeeds on grace_until, and
    the next flagged pin answers 13 twice over.

    PRD §2.8: "13. **Transition grace.** When a new rating cycle pins a `MethodologyVersion` whose status is `RETIRED`, `use_transition_grant` must be true **and** the organization must hold a `TransitionGrant` whose `superseded_version_label` equals that version's `version_label`, whose `status` is `ACTIVE`, and whose `grace_until` is at or after the logical clock. Otherwise `ERR_TRANSITION_GRACE_UNAVAILABLE` (409), on `POST /rating-cycles`. A retired pin submitted *without* `use_transition_grant` never reaches this check, because check 12 has already rejected it as `ERR_METHODOLOGY_NOT_ADOPTED`."

    PRD §2.8: "15. **Methodology effectivity.** The `MethodologyVersion` pinned to a new rating cycle is effective at the logical clock: its `effective_from` is at or before the clock, and either its `effective_until` is null or the clock is at or before it. Otherwise `ERR_METHODOLOGY_NOT_EFFECTIVE` (409), on `POST /rating-cycles`. A `RETIRED` version already admitted by check 13's grant is exempt from this check, because a transition grant is precisely a licence to pin an interval that has closed."

    PRD §3.2: "A grant is a licence, and it is spent. When a `RatingAnalyst` opens a new cycle pinned to a `RETIRED` methodology version while passing `use_transition_grant` as true, the organization's `ACTIVE` grant whose `superseded_version_label` matches the pinned version's `version_label` moves `ACTIVE` → `CONSUMED` and its `version` counter advances by one."

    Design: Corner/validations/the_retired_pin_verdict_is_handed_down_the_priority_chain_twelve_thirteen_fifteen
    """
    scenario = setup_transition_grant()
    organization_id = scenario["organization"]["id"]
    retired_id = scenario["methodology"]["id"]
    successor_id = scenario["successor_methodology"]["id"]
    grant = scenario["transition_grant"]
    assert_instant(grant["grace_until"], "2026-12-21T00:00:00Z", "grace_until")
    assert grant["trigger_reason"] == "WEIGHT_CHANGE"
    assert_score(grant["projected_score_delta"], -5.00, "projected_score_delta")
    assert_instant(
        scenario["organization"]["transition_grace_until"],
        "2026-12-21T00:00:00Z",
        "transition_grace_until",
    )

    def cycle_payload(methodology_version_id, fiscal_year, **extra):
        return create_rating_cycle_payload(
            organization_id,
            methodology_version_id,
            fiscal_year=fiscal_year,
            period_start=f"{fiscal_year}-01-01T00:00:00Z",
            period_end=f"{fiscal_year + 1}-01-01T00:00:00Z",
            **extra,
        )

    validate_error(
        api.create_rating_cycle(cycle_payload(retired_id, 2024), analyst_headers),
        "ERR_METHODOLOGY_NOT_ADOPTED",
        409,
    )
    validate_error(
        api.create_rating_cycle(cycle_payload(successor_id, 2024), analyst_headers),
        "ERR_METHODOLOGY_NOT_EFFECTIVE",
        409,
    )

    set_clock(grant["grace_until"])
    admitted = validate_success(
        api.create_rating_cycle(
            cycle_payload(retired_id, 2024, use_transition_grant=True), analyst_headers
        ),
        201,
    )
    assert admitted["methodology_version_id"] == retired_id

    validate_error(
        api.create_rating_cycle(
            cycle_payload(retired_id, 2023, use_transition_grant=True), analyst_headers
        ),
        "ERR_TRANSITION_GRACE_UNAVAILABLE",
        409,
    )
    set_clock("2026-12-22T00:00:00Z")
    validate_error(
        api.create_rating_cycle(
            cycle_payload(retired_id, 2022, use_transition_grant=True), analyst_headers
        ),
        "ERR_TRANSITION_GRACE_UNAVAILABLE",
        409,
    )

    spent = validate_success(api.get_transition_grant(grant["id"], admin_headers))
    assert spent["status"] == "CONSUMED"
    assert spent["version"] == 2

    _cycles, cycle_meta = validate_paginated(
        api.list_rating_cycles(analyst_headers, params={"organization_id": organization_id})
    )
    assert cycle_meta["total_count"] == 2


def test_the_comment_window_admits_its_deadline_instant_and_shuts_for_either_reason(
    api, admin_headers
):
    """One second before the close, on the close, one second after, and after an
    administrative close — one error code for two independent causes.

    PRD §3.1: "The transition stamps `comment_open_at` with the logical clock, derives `comment_deadline_at` as that instant plus the version's own `comment_period_days`, and advances the version's `version` counter by one."

    PRD §3.1: "A comment filed while the version is not `COMMENT_OPEN`, or filed after `comment_deadline_at` has passed, is refused with `ERR_COMMENT_PERIOD_CLOSED`; the deadline instant itself is still inside the window."

    PRD §3.1: "A new comment lands with `status` `SUBMITTED` and a null `disposition_note`, and it advances its parent version's `comment_count` and `unresolved_comment_count` by one each and that version's `version` counter by one."

    Design: Corner/validations/the_comment_window_is_inclusive_at_its_deadline_and_shut_by_either_cause
    """
    methodology = create_draft_methodology()
    never_opened = create_draft_methodology(
        version_label="M-DRAFT",
        weight_financial_health=0.25,
        weight_accountability=0.25,
        weight_transparency=0.25,
        weight_impact=0.25,
    )
    opened = open_comment(methodology["id"])
    assert_instant(
        opened["comment_deadline_at"], "2026-08-31T00:00:00Z", "comment_deadline_at"
    )

    first = file_public_comment(
        methodology["id"],
        headers=make_public_headers("public-1"),
        commenter_kind="DONOR",
        body="Please publish the sensitivity analysis behind the financial health weight",
    )
    assert first["status"] == "SUBMITTED"

    validate_error(
        api.create_public_comment(
            create_public_comment_payload(
                never_opened["id"],
                commenter_kind="PUBLIC",
                body="Commenting on a version nobody has opened for comment",
            ),
            make_public_headers("public-1"),
        ),
        "ERR_COMMENT_PERIOD_CLOSED",
        409,
    )

    set_clock("2026-08-30T23:59:59Z")
    file_public_comment(
        methodology["id"],
        headers=make_public_headers("public-2"),
        commenter_kind="RATED_ORGANIZATION",
        body="One second before the close of business on the penultimate day",
    )
    set_clock("2026-08-31T00:00:00Z")
    on_the_instant = file_public_comment(
        methodology["id"],
        headers=make_public_headers("public-3"),
        commenter_kind="PUBLIC",
        body="Filed on the deadline instant itself, which the rule admits",
    )
    assert on_the_instant["status"] == "SUBMITTED"

    set_clock("2026-08-31T00:00:01Z")
    validate_error(
        api.create_public_comment(
            create_public_comment_payload(
                methodology["id"],
                commenter_kind="PUBLIC",
                body="One second late, while the version is still COMMENT_OPEN",
            ),
            make_public_headers("public-4"),
        ),
        "ERR_COMMENT_PERIOD_CLOSED",
        409,
    )
    still_open = validate_success(
        api.get_methodology_version(methodology["id"], admin_headers)
    )
    assert still_open["status"] == "COMMENT_OPEN"

    closed = close_comment(methodology["id"])
    validate_error(
        api.create_public_comment(
            create_public_comment_payload(
                methodology["id"],
                commenter_kind="PUBLIC",
                body="Filed after the administrator closed the period",
            ),
            make_public_headers("public-5"),
        ),
        "ERR_COMMENT_PERIOD_CLOSED",
        409,
    )

    assert closed["comment_count"] == 3
    assert closed["unresolved_comment_count"] == 3
    assert_instant(
        closed["comment_deadline_at"], "2026-08-31T00:00:00Z", "comment_deadline_at"
    )
    assert_instant(
        closed["comment_closed_at"], "2026-08-31T00:00:01Z", "comment_closed_at"
    )

    comments, comment_meta = validate_paginated(
        api.list_methodology_public_comments(methodology["id"], admin_headers)
    )
    assert comment_meta["total_count"] == 3
    assert comments[0]["id"] == first["id"]


def test_the_third_dispute_is_refused_after_two_accepted_correction_rounds(api):
    """Both laps are walked in full, the counter is raised only by the two acceptances,
    and the third request is refused at creation with the cycle left publishable.

    PRD §2.8: "25. **Correction round limit.** A correction is accepted only while the cycle's `correction_round` is below the maximum of 2, and the request's `round_number` equals the cycle's `correction_round` plus 1. Otherwise `ERR_CORRECTION_ROUND_LIMIT` (409), on both `POST /correction-requests` and `POST /correction-requests/{correction_request_id}/decide`."

    PRD §3.7: "Filing it drives the cycle `ORG_REVIEW` → `CORRECTION_REQUESTED` and advances the cycle's `version` counter by one; the cycle must be in `ORG_REVIEW` for this to be admissible, else `ERR_CYCLE_STATE_INVALID`, and its `correction_round` must still be below two, else `ERR_CORRECTION_ROUND_LIMIT`."

    PRD §3.7: "The complete loop — `DATA_COLLECTION` → `SCORED` → `ORG_REVIEW` → `CORRECTION_REQUESTED` → `DATA_COLLECTION` — may be travelled at most twice, because the third acceptance is what the round limit forbids."

    Design: Corner/validations/the_correction_loop_is_shut_after_two_accepted_rounds
    """
    scenario = setup_cycle_in_org_review()
    cycle_id = scenario["cycle"]["id"]
    analyst_headers = scenario["analyst_headers"]
    org_rep_headers = scenario["org_rep_headers"]

    first = file_correction(
        cycle_id,
        org_rep_headers,
        target_kind="GOVERNANCE_DISCLOSURE",
        target_field_name="ceo_compensation_reviewed",
        proposed_value="true",
        narrative="The compensation committee reviewed CEO pay in March 2026",
        target_fiscal_year=None,
        target_source_kind=None,
    )
    assert first["round_number"] == 1
    claim_correction(first["id"], headers=analyst_headers)
    decide_correction(
        first["id"],
        "ACCEPT",
        headers=analyst_headers,
        decision_note="committee minutes verified",
    )
    evaluate_governance_profile(
        scenario["governance_profile"]["id"], headers=analyst_headers
    )
    score_cycle(cycle_id, headers=analyst_headers)
    after_first = open_org_review(cycle_id, headers=analyst_headers)
    assert after_first["correction_round"] == 1

    second = file_correction(
        cycle_id,
        org_rep_headers,
        target_field_name="net_assets_cents",
        proposed_value="7000000",
        narrative="The reserve figure omitted the board-designated fund",
    )
    assert second["round_number"] == 2
    claim_correction(second["id"], headers=analyst_headers)
    decide_correction(
        second["id"],
        "ACCEPT",
        headers=analyst_headers,
        decision_note="the designated fund belongs in net assets",
    )
    score_cycle(cycle_id, headers=analyst_headers)
    after_second = open_org_review(cycle_id, headers=analyst_headers)
    assert after_second["correction_round"] == 2
    assert after_second["status"] == "ORG_REVIEW"
    assert_instant(
        after_second["correction_deadline_at"],
        "2026-09-22T00:00:00Z",
        "correction_deadline_at",
    )

    validate_error(
        api.create_correction_request(
            create_correction_request_payload(
                cycle_id,
                target_fiscal_year=2024,
                target_field_name="program_expense_cents",
                proposed_value="4700000",
                narrative="A third bite at the cherry",
            ),
            org_rep_headers,
        ),
        "ERR_CORRECTION_ROUND_LIMIT",
        409,
    )

    corrections, correction_meta = validate_paginated(
        api.list_correction_requests(analyst_headers, params={"rating_cycle_id": cycle_id})
    )
    assert correction_meta["total_count"] == 2
    assert corrections[0]["id"] == first["id"]

    final = read_cycle(cycle_id, analyst_headers)
    assert final["status"] == "ORG_REVIEW"
    assert final["correction_round"] == 2
