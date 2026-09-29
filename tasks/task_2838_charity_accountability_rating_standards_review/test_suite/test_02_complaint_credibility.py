"""Complaint credibility under its two variants, and the ceiling it sets."""
from test_helpers import (
    assert_instant,
    assert_score,
    file_complaint,
    read_complaint,
    read_organization,
    resolve_complaint,
    resolve_complaint_payload,
    setup_bare_organization,
    triage_complaint,
    validate_error,
)


def test_intake_variant_scores_the_base_alone_and_lands_the_complaint_in_the_medium_tier(
    api, analyst_headers
):
    """A donor alleging misuse of funds with two documents is scored 30 + 30 + 16 at
    triage — the standing, the category and the documents, and nothing else.

    PRD §3.8: "The base is the complainant's standing — `DONOR` 30 points, `BENEFICIARY` 25, `EMPLOYEE` 35, `ANONYMOUS` 10 — plus the category — `MISUSE_OF_FUNDS` 30, `GOVERNANCE` 25, `SOLICITATION_PRACTICE` 20, `TRANSPARENCY` 15, `OTHER` 5 — plus 8 points for each corroborating document, counting at most 3 of them, so documentary support contributes at most 24 points however many files arrive."

    PRD §3.8: "The intake variant is exactly that base and nothing else: at triage neither the investigation's outcome nor any corroborating pattern is knowable."

    Design: Difficulty/dual_variant_calc/complaint_credibility_intake_vs_investigated_crosses_severity_tier
    """
    scenario = setup_bare_organization()
    complaint = file_complaint(
        scenario["organization"]["id"],
        complainant_kind="DONOR",
        category="MISUSE_OF_FUNDS",
        narrative="Restricted gift spent on unrelated overhead",
        corroborating_document_count=2,
    )
    triaged = triage_complaint(complaint["id"], "INVESTIGATE", triage_note="credible on its face")

    assert triaged["status"] == "INVESTIGATING"
    assert_score(triaged["credibility_score"], 76.00, "credibility_score")
    assert triaged["credibility_variant"] == "INTAKE"
    assert triaged["severity_tier"] == "MEDIUM"
    assert_instant(
        triaged["investigation_due_at"], "2026-08-31T00:00:00Z", "investigation_due_at"
    )


def test_investigated_variant_adds_the_finding_adjustment_and_crosses_into_the_high_tier(
    api, analyst_headers
):
    """The same complaint, resolved as substantiated, is rescored 76 + 10 and moves out
    of the medium tier into the high one.

    PRD §3.8: "The investigated variant adds two further terms — 5 points for each **other** complaint of the same organization already in `SUBSTANTIATED`, capped at 20 points in total, and then either 10 points when the finding is `SUBSTANTIATED` or a subtraction of 15 points when it is `UNSUBSTANTIATED`."

    PRD §3.8: "`severity_tier` follows from the score: `HIGH` at 80.00 or above, `MEDIUM` at 50.00 or above, and `LOW` otherwise."

    Design: Difficulty/dual_variant_calc/complaint_credibility_intake_vs_investigated_crosses_severity_tier
    """
    scenario = setup_bare_organization()
    complaint = file_complaint(
        scenario["organization"]["id"],
        complainant_kind="DONOR",
        category="MISUSE_OF_FUNDS",
        narrative="Restricted gift spent on unrelated overhead",
        corroborating_document_count=2,
    )
    triage_complaint(complaint["id"], "INVESTIGATE")
    resolved = resolve_complaint(
        complaint["id"], "SUBSTANTIATED", 12, finding_note="records confirm diversion"
    )

    assert resolved["status"] == "SUBSTANTIATED"
    assert_score(resolved["credibility_score"], 86.00, "credibility_score")
    assert resolved["credibility_variant"] == "INVESTIGATED"
    assert resolved["severity_tier"] == "HIGH"
    assert resolved["penalty_points_applied"] == 12
    assert resolved["penalized_rating_cycle_id"] is None
    assert read_organization(scenario["organization"]["id"])["substantiated_complaint_count"] == 1


def test_penalty_ceiling_is_re_derived_from_the_investigated_score_before_it_is_applied(
    api, analyst_headers
):
    """A beneficiary complaint about solicitation practice scores 45.00 at triage — a
    LOW tier capped at 5 points — yet 8 points are admissible on resolution, because
    the finding adjustment carried it into the MEDIUM tier first.

    PRD §3.8: "The subtle and load-bearing rule is that on resolution the tier is re-derived from the **investigated** score before the submitted `penalty_points` is checked against the ceiling, so the admissible ceiling is not knowable from the intake score alone: the pattern term and the finding adjustment can push a complaint across a severity boundary in either direction, raising or lowering the ceiling that the analyst's own request is then judged against."

    PRD §3.8: "The tier is what caps the penalty — at most 5 accountability points at `LOW`, 10 at `MEDIUM` and 15 at `HIGH`."

    Design: Difficulty/dual_variant_calc/complaint_credibility_intake_vs_investigated_crosses_severity_tier
    """
    scenario = setup_bare_organization()
    complaint = file_complaint(
        scenario["organization"]["id"],
        complainant_kind="BENEFICIARY",
        category="SOLICITATION_PRACTICE",
        narrative="Door-to-door canvassers described the charity as government funded",
        corroborating_document_count=0,
    )
    triaged = triage_complaint(complaint["id"], "INVESTIGATE")

    assert_score(triaged["credibility_score"], 45.00, "intake credibility_score")
    assert triaged["severity_tier"] == "LOW"

    resolved = resolve_complaint(complaint["id"], "SUBSTANTIATED", 8)

    assert_score(resolved["credibility_score"], 55.00, "investigated credibility_score")
    assert resolved["severity_tier"] == "MEDIUM"
    assert resolved["penalty_points_applied"] == 8


def test_penalty_above_the_investigated_tier_ceiling_is_refused(api, analyst_headers):
    """Twelve points is inside the statutory 1-to-15 range but above the ten the
    MEDIUM tier allows, so the resolution is refused and nothing is recorded.

    PRD §2.8: "**Penalty range.** On a substantiated finding, `penalty_points` is an integer between 1 and 15 inclusive and does not exceed the ceiling for the severity tier derived from the *investigated* credibility score; on an unsubstantiated finding `penalty_points` is absent or zero."

    Design: Difficulty/dual_variant_calc/complaint_credibility_intake_vs_investigated_crosses_severity_tier
    """
    scenario = setup_bare_organization()
    complaint = file_complaint(
        scenario["organization"]["id"],
        complainant_kind="BENEFICIARY",
        category="SOLICITATION_PRACTICE",
        narrative="Door-to-door canvassers described the charity as government funded",
        corroborating_document_count=0,
    )
    triage_complaint(complaint["id"], "INVESTIGATE")

    response = api.resolve_complaint(
        complaint["id"],
        resolve_complaint_payload("SUBSTANTIATED", 12),
        analyst_headers,
    )
    validate_error(response, "ERR_PENALTY_POINTS_RANGE", 422)

    unchanged = read_complaint(complaint["id"])
    assert unchanged["status"] == "INVESTIGATING"
    assert unchanged["penalty_points_applied"] == 0
    assert unchanged["credibility_variant"] == "INTAKE"
