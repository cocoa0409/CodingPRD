"""Wage attestation, the violation-threshold suspension cascade, compliance
audit scoring, and the audit-clearing compensating action."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    assert_instant,
    assert_two_dp,
    factories,
    fixtures,
    make_employer_rep_headers,
    worlds,
)


def test_wage_record_zero_amount_no_violation(api):
    """PRD §3.6: "An `amount_cents` of exactly 0 is the normal no-wage attestation."

    Design: Corner/validations/wage_record_zero_amount_no_violation
    """
    ns = fixtures.setup_match(api, advance_to="active")
    record = fixtures.post_wage_record(
        api, ns.match["id"], ns.employer["id"], "2026-10-05", "2026-10-11", 0,
        memo="no wages — service continues pay",
    )
    assert record["is_violation"] is False
    employer = fixtures.get_employer(api, ns.employer["id"])
    assert employer["pending_violations"] == 0
    assert fixtures.get_match(api, ns.match["id"])["flagged_wage_violation"] is False


def test_first_wage_violation_flags_match_increments_ledger(api):
    """PRD §3.6: "Any positive amount sets the record's computed `is_violation` to
    true and fires the wage-violation cascade: the match's `flagged_wage_violation`
    becomes true, the employer's `pending_violations` ledger increments by 1, and if
    that raises `pending_violations` to at least the suspension threshold of 2
    (`WAGE_VIOLATION_SUSPEND_THRESHOLD`) while the employer is `AUTHORIZED` or
    `AUTHORIZATION_LAPSED`, the employer moves to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/wage_violation_threshold_cascade
    """
    ns = worlds.setup_two_active_matches(api)
    assert ns.sweep["matches_activated"] == 2

    record = fixtures.post_wage_record(
        api, ns.match1["id"], ns.employer["id"], "2026-10-05", "2026-10-11", 50000, memo="weekly stipend"
    )
    assert record["is_violation"] is True
    assert fixtures.get_match(api, ns.match1["id"])["flagged_wage_violation"] is True
    employer = fixtures.get_employer(api, ns.employer["id"])
    assert employer["pending_violations"] == 1
    assert employer["authorization_status"] == "AUTHORIZED", "threshold 2 not yet reached"


def test_second_wage_violation_suspends_employer(api):
    """PRD §3.6: "Any positive amount sets the record's computed `is_violation` to
    true and fires the wage-violation cascade: the match's `flagged_wage_violation`
    becomes true, the employer's `pending_violations` ledger increments by 1, and if
    that raises `pending_violations` to at least the suspension threshold of 2
    (`WAGE_VIOLATION_SUSPEND_THRESHOLD`) while the employer is `AUTHORIZED` or
    `AUTHORIZATION_LAPSED`, the employer moves to `SUSPENDED`."
    PRD §3.4: "The owning employer must be `AUTHORIZED` at posting time, otherwise
    `ERR_EMPLOYER_NOT_AUTHORIZED`."

    Design: Difficulty/transitive_cascade/wage_violation_threshold_cascade
    """
    ns = worlds.setup_two_active_matches(api)
    fixtures.post_wage_record(api, ns.match1["id"], ns.employer["id"], "2026-10-05", "2026-10-11", 50000)
    fixtures.post_wage_record(api, ns.match2["id"], ns.employer["id"], "2026-10-05", "2026-10-11", 100)

    employer = fixtures.get_employer(api, ns.employer["id"])
    assert employer["pending_violations"] == 2
    assert employer["authorization_status"] == "SUSPENDED"

    blocked = api.create_opening(
        factories.create_opening_payload(ns.employer["id"], title="Second Opening"),
        make_employer_rep_headers(ns.employer["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_EMPLOYER_NOT_AUTHORIZED)


def test_audit_sanction_score_revokes_employer_closes_opening(api):
    """PRD §3.8: "A score below 70 closes the audit as `CLOSED_SANCTIONED`:
    `closed_at` and the employer's `last_compliance_score` are stamped, and the
    employer — provided it is not already `REVOKED` — moves to `REVOKED` from
    `AUTHORIZED`, `SUSPENDED`, or `AUTHORIZATION_LAPSED` alike."
    PRD §3.8: "Revocation cascades in full: every `OPEN` opening of the employer
    moves to `CLOSED`; every match of the employer in `PROPOSED` or
    `INSTALLATION_APPROVED` moves to `MATCH_VOIDED`; every such match in `ACTIVE`
    moves to `TERMINATED_EARLY` with `termination_reason` set to `EMPLOYER_REVOKED`;
    and `filled_count` plus `active_match_count` are recomputed for every affected
    opening and member."

    One CRITICAL finding deducts 45.00 for a score of 55.00.

    Design: Difficulty/transitive_cascade/audit_sanction_revocation_cascade
    """
    ns = worlds.setup_cascade_world(api)
    closed = fixtures.close_audit(
        api, ns.audit["id"],
        findings=[factories.finding("WAGE_PAYMENT_DETECTED", "CRITICAL", "member paid stipend for internship labor")],
    )
    assert closed["status"] == "CLOSED_SANCTIONED"
    assert_two_dp(closed["compliance_score"], 55.00, "compliance_score")
    assert fixtures.get_employer(api, ns.employer["id"])["authorization_status"] == "REVOKED"
    assert fixtures.get_opening(api, ns.opening["id"])["status"] == "CLOSED"


def test_audit_sanction_cascade_voids_and_terminates_matches(api):
    """PRD §3.8: "Revocation cascades in full: every `OPEN` opening of the employer
    moves to `CLOSED`; every match of the employer in `PROPOSED` or
    `INSTALLATION_APPROVED` moves to `MATCH_VOIDED`; every such match in `ACTIVE`
    moves to `TERMINATED_EARLY` with `termination_reason` set to `EMPLOYER_REVOKED`;
    and `filled_count` plus `active_match_count` are recomputed for every affected
    opening and member."

    Design: Difficulty/transitive_cascade/audit_sanction_revocation_cascade
    """
    ns = worlds.setup_cascade_world(api)
    fixtures.close_audit(
        api, ns.audit["id"],
        findings=[factories.finding("WAGE_PAYMENT_DETECTED", "CRITICAL", "member paid stipend for internship labor")],
    )
    assert fixtures.get_match(api, ns.match1["id"])["match_status"] == "MATCH_VOIDED"
    match2 = fixtures.get_match(api, ns.match2["id"])
    assert match2["match_status"] == "TERMINATED_EARLY"
    assert match2["termination_reason"] == "EMPLOYER_REVOKED"
    assert fixtures.get_opening(api, ns.opening["id"])["filled_count"] == 0
    assert fixtures.get_member(api, ns.members[1]["id"])["active_match_count"] == 0


def test_compliance_score_repeat_minor_deductions(api):
    """PRD §3.8: "Each finding's deduction is its severity base — 5.00 for `MINOR`,
    20.00 for `MAJOR`, 45.00 for `CRITICAL` — multiplied by one plus the
    `REPEAT_MULTIPLIER` of 0.5 times the number of earlier findings in the same
    audit carrying the same `finding_code`; every deduction is rounded half-up to 2
    decimal places individually, and only then are the rounded deductions summed."

    Three repeated MINORs deduct 5.00, 7.50, 10.00 — score 77.50 clears.

    Design: Difficulty/combinatorial_formula/compliance_score_per_finding_rounding
    """
    employer = fixtures.create_authorized_employer(api)
    audit = fixtures.open_audit(api, employer["id"])
    closed = fixtures.close_audit(
        api, audit["id"],
        findings=[
            factories.finding("WAGE_PAYMENT_DETECTED", "MINOR", "stipend w1"),
            factories.finding("WAGE_PAYMENT_DETECTED", "MINOR", "stipend w2"),
            factories.finding("WAGE_PAYMENT_DETECTED", "MINOR", "stipend w3"),
        ],
    )
    assert closed["status"] == "CLOSED_CLEARED"
    assert_two_dp(closed["compliance_score"], 77.50, "compliance_score")


def test_compliance_score_clamped_at_base(api):
    """PRD §3.8: "The total deduction is capped at the base score of 100, and the
    score is the base minus that capped total."
    PRD §3.8: "A score below 70 closes the audit as `CLOSED_SANCTIONED`: `closed_at`
    and the employer's `last_compliance_score` are stamped, and the employer —
    provided it is not already `REVOKED` — moves to `REVOKED` from `AUTHORIZED`,
    `SUSPENDED`, or `AUTHORIZATION_LAPSED` alike."

    Two repeated CRITICALs deduct 45.00 and 67.50 = 112.50, clamped to 100 — score
    0.00 sanctions and revokes.

    Design: Difficulty/combinatorial_formula/compliance_score_per_finding_rounding
    """
    employer = fixtures.create_authorized_employer(api, legal_name="BadActor Staffing", industry_code="TMP")
    audit = fixtures.open_audit(api, employer["id"])
    closed = fixtures.close_audit(
        api, audit["id"],
        findings=[
            factories.finding("SUPERVISION_MISSING", "CRITICAL", "no supervisor weeks 1-3"),
            factories.finding("SUPERVISION_MISSING", "CRITICAL", "repeat: weeks 4-6"),
        ],
    )
    assert closed["status"] == "CLOSED_SANCTIONED"
    assert_two_dp(closed["compliance_score"], 0.00, "compliance_score")
    assert fixtures.get_employer(api, employer["id"])["authorization_status"] == "REVOKED"


def _ledger_world(api):
    """An ACTIVE match whose employer then records one violating wage record."""
    ns = fixtures.setup_match(api, advance_to="active")
    fixtures.post_wage_record(api, ns.match["id"], ns.employer["id"], "2026-10-05", "2026-10-11", 2500)
    return ns


def test_violation_ledger_cleared_by_audit(api):
    """PRD §3.8: "A score of at least 70 closes the audit as `CLOSED_CLEARED`:
    `closed_at` is stamped, the employer's `pending_violations` ledger resets to 0,
    `last_cleared_audit_at` is set to the logical clock, and `last_compliance_score`
    records the computed score."
    PRD §3.8: "An audit closed with no findings scores exactly 100.00."

    Design: Difficulty/compensating_invariant/violation_ledger_cleared_by_audit
    """
    ns = _ledger_world(api)
    before = fixtures.get_employer(api, ns.employer["id"])
    assert before["pending_violations"] == 1
    assert before["last_cleared_audit_at"] is None

    audit = fixtures.open_audit(api, ns.employer["id"])
    closed = fixtures.close_audit(api, audit["id"])
    assert closed["status"] == "CLOSED_CLEARED"
    assert_two_dp(closed["compliance_score"], 100.00, "compliance_score")

    after = fixtures.get_employer(api, ns.employer["id"])
    assert after["pending_violations"] == 0, "the cleared audit resets the ledger"
    assert_instant(after["last_cleared_audit_at"], "2026-10-01T00:00:00Z", "last_cleared_audit_at")
    assert after["authorization_status"] == "AUTHORIZED"


def test_violation_ledger_counts_from_new_baseline(api):
    """PRD §3.6: "The ledger counts only violations recorded after the employer's
    `last_cleared_audit_at`; a cleared audit resets it (§3.8)."

    Design: Difficulty/compensating_invariant/violation_ledger_cleared_by_audit
    """
    ns = _ledger_world(api)
    audit = fixtures.open_audit(api, ns.employer["id"])
    fixtures.close_audit(api, audit["id"])

    fixtures.post_wage_record(api, ns.match["id"], ns.employer["id"], "2026-10-12", "2026-10-13", 100)
    after = fixtures.get_employer(api, ns.employer["id"])
    assert after["pending_violations"] == 1, (
        "the post-clear violation counts from the new baseline, not cumulatively"
    )
