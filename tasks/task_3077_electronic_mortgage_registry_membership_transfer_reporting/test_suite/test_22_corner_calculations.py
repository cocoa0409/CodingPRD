"""Corner coverage of the calculations: the proven-prior gate on the repeat
multiplier, the three-way SOR diff, portfolio-scoped registry_only counts and
the standing score's exception cap."""
import pytest

from test_helpers import (
    ADMIN,
    add_finding,
    api_client,
    create_active_member,
    create_transfer_payload,
    issue_review,
    list_sanctions,
    member_rep,
    open_review,
    read_loan,
    register_loan,
    set_clock,
    settle_review,
    setup_two_member_pair,
    validate_paginated,
    validate_success,
)


def test_sanction_repeat_offender_multiplier_applies_only_with_proven_prior(api):
    """PRD §3.5: "A repeat-offender multiplier is determined from the member's
    sanction history: if the member has any prior sanction in `UPHELD`,
    `REDUCED`, or `PAID` status — proven priors — the multiplier is 1.5;
    otherwise it is 1.0."

    Design: Corner/calculations/sanction_repeat_offender_multiplier_applies_only_with_proven_prior
    """
    set_clock("2026-01-05T00:00:00Z")
    d = create_active_member(org_id="1000002", member_type="ORIGINATOR")
    loan1 = register_loan(d["id"], loan_amount_cents=40000000)
    loan2 = register_loan(d["id"], loan_amount_cents=40000000)

    # R1: one MINOR finding, settled; its sanction stays ASSESSED (never
    # appealed, paid, upheld, reduced, or vacated) -> NOT a proven prior.
    review1 = open_review(d["id"], period_start="2026-01-01T00:00:00Z",
                          period_end="2026-03-31T00:00:00Z")
    add_finding(review1["id"], loan1["id"], severity="MINOR")
    issue_review(review1["id"])
    settle_review(review1["id"])

    # R2: one MINOR finding; settled while the prior is still merely ASSESSED.
    review2 = open_review(d["id"], period_start="2026-04-01T00:00:00Z",
                          period_end="2026-06-30T00:00:00Z")
    add_finding(review2["id"], loan2["id"], severity="MINOR",
                expected_value="2026-01-05", actual_value="2026-01-08")
    issue_review(review2["id"])
    settle_review(review2["id"])

    sanc2 = list_sanctions(review_id=review2["id"])[0]
    # Still a first offender: multiplier 1.0, one MINOR line at base 25005.
    assert sanc2["total_amount_cents"] == 25005, sanc2
    assert sanc2["line_count"] == 1, sanc2


def test_sor_match_rate_three_way_diff_counts(api):
    """PRD §3.8: "A record whose `min` is unknown to the registry counts toward
    `platform_only_count` and yields a `PLATFORM_ONLY` exception; a record whose
    `min` belongs to a loan that has left the registry — any of the
    `INACTIVE_ASSIGNED_OUT`, `INACTIVE_TERMINATED`, or `INACTIVE_SATISFIED`
    statuses — is treated the same way, as platform-only, since the registry no
    longer tracks the loan."
    PRD §3.8: "The run stores `total_records` (the number of submitted records),
    the four diff counts, and `match_rate` — the matched count divided by the
    sum of total records and registry-only count, with the denominator
    protected to at least 1, rounded half-up to four decimal places."

    Design: Corner/calculations/sor_match_rate_three_way_diff_counts
    """
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
    loan2 = register_loan(a["id"], loan_amount_cents=50000000)
    assert loan2["min"] == "100000000000000016", loan2
    # B becomes the servicer of the loan; A keeps the investor right.
    validate_success(
        api.create_transfer(
            create_transfer_payload(loan2["id"], b["id"], loan2["version"],
                                    idempotency_key="k-sor-1"),
            member_rep(a["id"]),
        ),
        expected_status=201,
    )

    # B submits two records: one matching its held loan, one with an
    # unknown MIN.
    run = validate_success(
        api.create_sor_run(
            {"records": [
                {"min": "100000000000000016", "servicer_org_id": "1000001",
                 "investor_org_id": "1000000"},
                {"min": "999999999999999999", "servicer_org_id": "1000001",
                 "investor_org_id": "1000001"},
            ]},
            member_rep(b["id"]),
        ),
        expected_status=201,
    )
    assert run["matched_count"] == 1, run
    assert run["platform_only_count"] == 1, run
    assert run["registry_only_count"] == 0, run
    assert run["field_mismatch_count"] == 0, run
    assert run["match_rate"] == pytest.approx(0.5000), run
    assert run["status"] == "OPEN", run

    exceptions, _ = validate_paginated(
        api.list_sor_exceptions(ADMIN, params={"run_id": run["id"]})
    )
    assert len(exceptions) == 1, exceptions
    assert exceptions[0]["exception_type"] == "PLATFORM_ONLY", exceptions
    assert exceptions[0]["status"] == "OPEN", exceptions


def test_sor_run_member_only_sees_own_portfolio_in_registry_only(api):
    """PRD §3.8: "The registry-side direction is then swept: every loan in
    `ACTIVE` or `FORECLOSING` status where the member is current servicer or
    current investor, and whose `min` appears in no submitted record, counts
    toward `registry_only_count` and yields a `REGISTRY_ONLY` exception."

    Design: Corner/calculations/sor_run_member_only_sees_own_portfolio_in_registry_only
    """
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
    register_loan(a["id"], loan_amount_cents=50000000)
    register_loan(a["id"], loan_amount_cents=50000000)
    register_loan(b["id"], loan_amount_cents=50000000)

    run = validate_success(
        api.create_sor_run({"records": []}, member_rep(a["id"])),
        expected_status=201,
    )
    # Only A's two loans are in A's portfolio; B's loan is not counted.
    assert run["registry_only_count"] == 2, run

    exceptions, _ = validate_paginated(
        api.list_sor_exceptions(
            ADMIN, params={"run_id": run["id"], "exception_type": "REGISTRY_ONLY"}
        )
    )
    assert len(exceptions) == 2, exceptions


def test_standing_score_exception_cap_limits_penalty_to_ten(api):
    """PRD §3.6: "These feed `standing_score`, which starts from a perfect 100
    and subtracts three penalties: sixty points scaled by the shortfall of the
    count-based reporting rate below perfect timeliness, forty points scaled by
    the member's discrepancy rate (capped at full weight — a discrepancy rate
    above 1 cannot penalize beyond the forty points), and two points per open
    exception with at most ten exceptions penalized."
    PRD §3.6: "`open_exceptions` counts the member's TransferMatch rows sitting
    in `PENDING` or `EXPIRED` at generation time."

    Design: Corner/calculations/standing_score_exception_cap_limits_penalty_to_ten
    """
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
    loans = [register_loan(a["id"], loan_amount_cents=50000000) for _ in range(10)]

    # All reports happen at the effective date itself: every transfer is on
    # time, so the reporting-rate and discrepancy penalties are both zero and
    # the open-exception penalty is the only mover of the standing score.
    seq = 0

    def xfer(loan, frm, to, ttype):
        nonlocal seq
        seq += 1
        loan_now = read_loan(loan["id"])
        return validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan_now["id"], to, loan_now["version"],
                    transfer_type=ttype,
                    effective_date="2026-01-05T00:00:00Z",
                    idempotency_key=f"k-cap-{seq:02d}",
                ),
                member_rep(frm),
            ),
            expected_status=201,
        )

    # A -> B SERVICING on all ten loans (10 PENDING matches addressed to A).
    for loan in loans:
        xfer(loan, a["id"], b["id"], "SERVICING")
    # B -> A SERVICING back on loans 1 and 2 (2 PENDING matches addressed to B).
    xfer(loans[0], b["id"], a["id"], "SERVICING")
    xfer(loans[1], b["id"], a["id"], "SERVICING")
    # A -> B BENEFICIAL on loans 1 and 2 (2 more PENDING matches addressed to A).
    xfer(loans[0], a["id"], b["id"], "BENEFICIAL")
    xfer(loans[1], a["id"], b["id"], "BENEFICIAL")

    set_clock("2026-12-31T00:00:00Z")
    report = validate_success(
        api.create_annual_report(a["id"], {"report_year": 2026}, ADMIN),
        expected_status=201,
    )

    # All 12 of A's CONFIRMED transfers in 2026 were reported on time.
    assert report["reporting_rate"] == pytest.approx(1.0), report
    # No settled review: discrepancy rate is 0.0.
    assert report["discrepancy_rate"] == pytest.approx(0.0), report
    # 10 servicing matches + 2 beneficial matches addressed to A; the 2
    # servicing-back matches belong to B.
    assert report["open_exceptions"] == 12, report
    # 100 - 60*0 - 40*0 - 2*min(12,10) = 80.00; the uncapped value 76.00
    # is the rejected variant.
    assert report["standing_score"] == pytest.approx(80.00), report
    assert report["standing_score"] != pytest.approx(76.00)
    assert report["standing_band"] == "GOOD_STANDING", report
