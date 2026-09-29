"""The two identities that must hold after every single request.

Money is conserved across an order and its void; the cardinality of a finding set
is conserved across a remediation and its rejection.  Each pair walks the forward
move and its exact compensating counterpart and reads the identity at every point.
"""

from __future__ import annotations

from typing import Any, Dict, List

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_counters,
    assert_escrow_conservation,
    assert_finding_partition,
    assert_money_equals,
    assert_state,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR_HEADERS,
    NGB_ADMIN_HEADERS,
    make_club_admin_headers,
)

ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}


def _expedited_tier_three_order(api: ApiClient) -> Dict[str, Any]:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    assert_money_equals(club, "escrow_balance_cents", 500000)
    assert_money_equals(club, "total_funded_cents", 500000)
    admin = make_club_admin_headers(club["id"])
    member = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Ivo Sandoval",
                "email": "ivo.sandoval@alpha.test",
                "role_type": "HEAD_COACH",
                "has_minor_athlete_contact": True,
                "date_of_birth": "1983-08-08",
                "jurisdiction_codes": ["CA", "NV", "OR"],
            },
            admin,
        ),
        201,
    )
    assert_state(member, "required_tier", "TIER_3")
    order = get_success_data(
        api.order_screening(
            member["id"], {"expedited": True, "expected_club_version": club["version"]}, admin
        ),
        201,
    )
    return {"club": club, "member": member, "order": order, "admin": admin}


def test_an_expedited_top_tier_order_debits_the_escrow_by_its_charged_cents(
    api: ApiClient,
) -> None:
    """The escrow identity holds with one order in flight.

    PRD 2.12 says:
    "For every club, the club's current `escrow_balance_cents` plus the sum of `charged_cents` over every screening order belonging to a member of that club whose status is `ORDERED`, `RESULT_RETURNED`, or `ADJUDICATED` equals that club's `total_funded_cents`."
    "Only two actions move the quantity: ordering a screen debits the balance, and voiding an order credits precisely the same number of cents back."

    Design: Difficulty/compensating_invariant/escrow_conservation_across_screening_order_and_void
    """
    setup = _expedited_tier_three_order(api)
    order = setup["order"]

    assert_money_equals(order, "gross_subtotal_cents", 11400)
    assert_money_equals(order, "discount_cents", 570)
    assert_money_equals(order, "expedite_cents", 3791)
    assert_money_equals(order, "charged_cents", 14621)

    club = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_money_equals(club, "escrow_balance_cents", 485379)
    assert_money_equals(club, "total_funded_cents", 500000)
    assert_escrow_conservation(club, [order])


def test_voiding_the_order_credits_exactly_the_same_cents_back_with_no_drift(
    api: ApiClient,
) -> None:
    """The voided row keeps its charge but leaves the sum, so the identity survives.

    PRD 2.12 says:
    "A voided order keeps its `charged_cents` on the row for the audit trail but drops out of the sum because status `VOIDED` is excluded, so the identity survives the refund exactly."
    "All arithmetic here is exact integer cents with no rounding, which is why an order-then-void round trip leaves zero drift."
    PRD 3.3 says:
    "The order moves to `VOIDED`, the club's `escrow_balance_cents` is credited with exactly the order's `charged_cents` and the club's `version` advances by one, and the member's screening dimension reverts to `UNSCREENED` — from `SCREENING_ORDERED` or from `FLAGGED` — with `contact_eligibility` re-derived and the member's `version` advanced by one."

    Design: Difficulty/compensating_invariant/escrow_conservation_across_screening_order_and_void
    """
    setup = _expedited_tier_three_order(api)

    voided = validate_success(
        api.void_screening_order(
            setup["order"]["id"],
            {"reason": "ordered against the wrong tier snapshot"},
            NGB_ADMIN_HEADERS,
        )
    )
    assert_state(voided, "status", "VOIDED")
    assert_money_equals(voided, "charged_cents", 14621)

    club = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_money_equals(club, "escrow_balance_cents", 500000)
    assert_money_equals(club, "total_funded_cents", 500000)
    assert_escrow_conservation(club, [voided])

    member = validate_success(api.get_member(setup["member"]["id"], setup["admin"]))
    assert_state(member, "screening_status", "UNSCREENED")


def _finalized_audit_with_three_open_findings(api: ApiClient) -> Dict[str, Any]:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    member = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Lena Ostrow",
                "email": "lena.ostrow@alpha.test",
                "role_type": "VOLUNTEER",
                "has_minor_athlete_contact": False,
                "date_of_birth": "1991-09-09",
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    audit = get_success_data(
        api.open_club_audit(
            {
                "club_id": club["id"],
                "audit_period_start": "2026-01-01T00:00:00Z",
                "audit_period_end": "2026-06-30T00:00:00Z",
                "score_variant": "SELF_ATTESTED",
                "sampled_member_ids": [member["id"]],
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )
    assert_counters(audit, finding_total_count=0, open_finding_count=0)

    payloads: List[Dict[str, Any]] = [
        {
            "finding_code": "RECORDS_INCOMPLETE",
            "severity": "MINOR",
            "member_id": member["id"],
            "is_repeat": False,
        },
        {
            "finding_code": "TRAINING_LAPSED",
            "severity": "MAJOR",
            "member_id": member["id"],
            "is_repeat": False,
        },
        {"finding_code": "RECORDS_INCOMPLETE", "severity": "MINOR", "is_repeat": True},
    ]
    findings = [
        get_success_data(api.write_finding(audit["id"], payload, COMPLIANCE_AUDITOR_HEADERS), 201)
        for payload in payloads
    ]
    assert_state(findings[0], "status", "OPEN")
    finalized = get_success_data(api.finalize_club_audit(audit["id"], {}, COMPLIANCE_AUDITOR_HEADERS))
    return {"club": club, "audit": finalized, "findings": findings, "admin": admin}


def test_a_finalized_audit_partitions_every_written_finding_into_the_open_count(
    api: ApiClient,
) -> None:
    """Three written findings, three open, nothing anywhere else.

    PRD 2.12 says:
    "For every audit, `finding_total_count` equals the sum of `open_finding_count`, `remediated_finding_count`, and `waived_finding_count`, and also equals the number of findings actually written against that audit, irrespective of their `severity`, their `member_id`, or whether `fine_cents` has been stamped."
    "Writing a finding raises the total and the open count together."

    Design: Difficulty/compensating_invariant/finding_partition_conserved_across_remediation_reject_cycle
    """
    setup = _finalized_audit_with_three_open_findings(api)
    audit = setup["audit"]

    assert_state(audit, "status", "FINDINGS_ISSUED")
    assert_counters(
        audit,
        finding_total_count=3,
        open_finding_count=3,
        remediated_finding_count=0,
        waived_finding_count=0,
    )
    assert_finding_partition(audit, 3)


def test_a_rejected_remediation_restores_the_counts_a_waiver_moved_permanently(
    api: ApiClient,
) -> None:
    """The club's move and the auditor's rejection cancel out; the waiver does not.

    PRD 2.12 says:
    "Submitting remediation moves one unit from the open count to the remediated count; rejecting that remediation moves the same unit back; waiving moves one unit from the open count to the waived count."
    PRD 3.9 says:
    "A `ComplianceAuditor` submits `REMEDIATION_REJECTED` against a finding in status `REMEDIATED`: the finding moves `REMEDIATED → OPEN`, the `note` is retained as `decision_note`, `open_finding_count` rises by one while `remediated_finding_count` falls by one, and the club's counters and posture are re-derived — the compensating action that closes the `OPEN → REMEDIATED → OPEN` cycle, which a club and an auditor may traverse any number of times."

    Design: Difficulty/compensating_invariant/finding_partition_conserved_across_remediation_reject_cycle
    """
    setup = _finalized_audit_with_three_open_findings(api)
    first, second, third = setup["findings"]

    submitted = validate_success(
        api.decide_finding(
            first["id"],
            {
                "decision": "REMEDIATION_SUBMITTED",
                "note": "screening records back-filled and attached",
            },
            setup["admin"],
        )
    )
    assert_state(submitted, "status", "REMEDIATED")

    rejected = validate_success(
        api.decide_finding(
            first["id"],
            {
                "decision": "REMEDIATION_REJECTED",
                "note": "attachments do not cover the audit period",
            },
            COMPLIANCE_AUDITOR_HEADERS,
        )
    )
    assert_state(rejected, "status", "OPEN")

    waived = validate_success(
        api.decide_finding(
            second["id"],
            {
                "decision": "WAIVED",
                "note": "training gap already cured before the period closed",
            },
            COMPLIANCE_AUDITOR_HEADERS,
        )
    )
    assert_state(waived, "status", "WAIVED")
    assert_state(
        validate_success(api.get_audit_finding(third["id"], COMPLIANCE_AUDITOR_HEADERS)),
        "status",
        "OPEN",
    )

    audit = validate_success(api.get_club_audit(setup["audit"]["id"], COMPLIANCE_AUDITOR_HEADERS))
    assert_counters(
        audit,
        finding_total_count=3,
        open_finding_count=2,
        remediated_finding_count=0,
        waived_finding_count=1,
    )
    assert_finding_partition(audit, 3)
