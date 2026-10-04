"""Queue A — dual_variant_calc: the same inputs produce different outcomes
under two contract variants (CAT provisional vs final outcome; NCCP vs HOURLY
recertification models over identical CE entries).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_DELIVERY_CLOCK,
    DEFAULT_ISSUE_CLOCK,
    DEFAULT_RECERT_CLOCK,
    advance_clock,
    cat_responses_payload,
    create_approved_exam_application,
    create_candidate,
    create_level,
    create_program,
    create_recert_draft,
    create_verified_completion,
    create_verified_psychomotor,
    deliver_attempt,
    issue_certification,
    make_candidate_headers,
    refresh_recert_application,
    schedule_attempt,
    setup_approved_application,
    submit_recert,
    api_client,
    add_ce_entries,
    validate_error,
    validate_success,
)

# Identical portfolio used for both models: NATIONAL 35 in-person (17.5+17.5),
# LOCAL 5 in-person, no INDIVIDUAL — total 40 hours.
_DIVERGENT_ENTRIES = [
    dict(component="NATIONAL", hours=17.5, delivery_method="IN_PERSON",
         course_code="N1", course_date="2027-10-01", provider_name="AlphaCE"),
    dict(component="NATIONAL", hours=17.5, delivery_method="IN_PERSON",
         course_code="N2", course_date="2027-10-02", provider_name="BetaCE"),
    dict(component="LOCAL", hours=5, delivery_method="IN_PERSON",
         course_code="L1", course_date="2027-10-03", provider_name="GammaCE"),
]


def test_cat_provisional_pass_final_fail_divergence(api):
    """PRD §3.4: "Once at least six items have been delivered, the engine reports
    a `provisional_outcome`: `PASS` when the weighted accuracy at exactly six
    items meets or exceeds the level's `cognitive_cut_score`, otherwise `FAIL`."
    PRD §3.4: "The provisional outcome is a bare point estimate with no
    confidence qualification, and on identical response data it can diverge from
    the final outcome — a borderline estimate can be dragged across the cut in
    either direction by later items."
    PRD §3.4: "Every comparison uses the unrounded accuracy; the stored
    `theta_final` is the final weighted accuracy rounded half up to four decimal
    places."

    Five correct then seven incorrect items at uniform difficulty 0.5 against a
    0.66 cut: theta_6 = 5/6 = 0.8333 (provisional PASS), no confidence-band exit
    until k=12 where UCB = 0.6508 < 0.66 (final FAIL, theta 5/12 stored 0.4167).

    Design: Difficulty/dual_variant_calc/cat_provisional_pass_final_fail_divergence
    """
    ctx = setup_approved_application()
    attempt = schedule_attempt(ctx["candidate"]["id"], ctx["att_id"])
    advance_clock(DEFAULT_DELIVERY_CLOCK)

    scored = deliver_attempt(attempt["id"], cat_responses_payload(5, 12))

    assert scored["provisional_outcome"] == "PASS", (
        f"theta_6 = 5/6 >= 0.66 must give provisional PASS, got {scored['provisional_outcome']}"
    )
    assert scored["final_outcome"] == "FAIL", (
        f"no band exit until k=12, UCB_12 ~ 0.6508 < 0.66 must give final FAIL, "
        f"got {scored['final_outcome']}"
    )
    assert scored["status"] == "SCORED_FAIL"
    assert scored["items_delivered_count"] == 12
    assert scored["theta_final"] == pytest.approx(0.4167, abs=1e-9)
    assert scored["provisional_outcome"] != scored["final_outcome"]


def test_ce_nccp_rejects_hourly_accepts_same_entries(api):
    """PRD §3.6: "Identical entry sets can pass one model and fail the other."
    PRD §3.6: "Under the `HOURLY` model the components and the spill are
    ignored: the credited total is the sum of all `IN_PERSON` hours on eligible
    entries plus the smaller of the total `DISTRIBUTED` hours and the level's
    `hourly_model_total_hours` halved and rounded up to a whole hour, and the
    portfolio is sufficient exactly when that total meets
    `hourly_model_total_hours`, otherwise `ERR_CE_TOTAL_SHORTFALL`."
    PRD §3.6: "Sufficiency under the `NCCP` model is checked in a fixed order,
    first failure wins: credited national hours against `ce_national_min_hours`,
    then local against `ce_local_min_hours`, then individual against
    `ce_individual_min_hours` — any shortfall rejected with
    `ERR_CE_COMPONENT_SHORTFALL` — and finally the credited total against
    `ce_total_hours` (`ERR_CE_TOTAL_SHORTFALL`)."

    Identical entries (NATIONAL 35 in-person, LOCAL 5 in-person; total 40):
    HOURLY credits 40 >= 40 and submits; NCCP credits LOCAL 5 < 10 and the
    NATIONAL spill flows to INDIVIDUAL only, so the LOCAL component shortfall
    rejects the submission.

    Design: Difficulty/dual_variant_calc/ce_nccp_rejects_hourly_accepts_same_entries
    """
    level = create_level()
    program = create_program(level["id"])

    def _certified_candidate():
        candidate = create_candidate()
        record = create_verified_completion(candidate["id"], program)
        application = create_approved_exam_application(
            candidate["id"], level["id"], record["id"],
        )
        attempt = schedule_attempt(candidate["id"], application["att_id"])
        return {
            "candidate": candidate,
            "record": record,
            "application": application,
            "attempt": attempt,
        }

    ctx_a = _certified_candidate()
    ctx_b = _certified_candidate()
    advance_clock(DEFAULT_DELIVERY_CLOCK)
    for ctx in (ctx_a, ctx_b):
        ctx["attempt"] = deliver_attempt(ctx["attempt"]["id"])
        ctx["psychomotor"] = create_verified_psychomotor(
            ctx["candidate"]["id"], level["id"], ctx["record"]["id"],
        )
    advance_clock(DEFAULT_ISSUE_CLOCK)
    for ctx in (ctx_a, ctx_b):
        ctx["certification"] = issue_certification(
            ctx["candidate"]["id"], level["id"], ctx["application"]["id"],
            ctx["attempt"]["id"], ctx["psychomotor"]["id"],
        )

    advance_clock(DEFAULT_RECERT_CLOCK)
    draft_a = create_recert_draft(
        ctx_a["candidate"]["id"], ctx_a["certification"]["id"], model="HOURLY",
    )
    add_ce_entries(draft_a["id"], ctx_a["candidate"]["id"], list(_DIVERGENT_ENTRIES))
    draft_b = create_recert_draft(
        ctx_b["candidate"]["id"], ctx_b["certification"]["id"], model="NCCP",
    )
    add_ce_entries(draft_b["id"], ctx_b["candidate"]["id"], list(_DIVERGENT_ENTRIES))

    submitted_a = submit_recert(draft_a["id"], ctx_a["candidate"]["id"])
    assert submitted_a["status"] == "SUBMITTED", (
        f"HOURLY credits 40 >= 40 and must submit, got {submitted_a['status']}"
    )
    assert submitted_a["total_credited_hours"] == 40, (
        f"credited_total = min(0 distributed, 20) + 40 in-person == 40, "
        f"got {submitted_a['total_credited_hours']}"
    )

    resp_b = api_client.submit_recert_application(
        draft_b["id"], make_candidate_headers(ctx_b["candidate"]["id"]),
    )
    validate_error(resp_b, ApiErrorId.ERR_CE_COMPONENT_SHORTFALL)
    assert refresh_recert_application(draft_b["id"])["status"] == "DRAFT", (
        "a rejected submission leaves the NCCP application in DRAFT"
    )
