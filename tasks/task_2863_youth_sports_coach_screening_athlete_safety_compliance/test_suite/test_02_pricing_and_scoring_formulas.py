"""The three formulas whose evaluation order changes the answer.

Screening pricing, the sanction fine and the risk score are each specified as an
ordered sequence of steps with caps and roundings pinned to exact positions.  A
plausible reordering of any of them yields a different integer, so these tests
assert the intermediate values, not only the totals.
"""

from __future__ import annotations

from typing import Any, Dict, List

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_counters,
    assert_money_equals,
    assert_score_equals,
    assert_state,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR_HEADERS,
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    SCREENING_VENDOR_HEADERS,
    make_club_admin_headers,
)

ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}
SS101 = {
    "code": "SS101",
    "title": "Abuse Prevention Core",
    "validity_days": 365,
    "delivery_mode": "ONLINE",
    "required_for_tiers": ["TIER_1", "TIER_2", "TIER_3"],
    "pass_score": 80,
}


def _club(api: ApiClient) -> Dict[str, Any]:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    return get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)


def _register(api: ApiClient, club_id: str, **fields: Any) -> Dict[str, Any]:
    payload = {
        "club_id": club_id,
        "has_minor_athlete_contact": False,
        "jurisdiction_codes": ["CA"],
        "role_type": "VOLUNTEER",
        "date_of_birth": "1990-02-02",
    }
    payload.update(fields)
    return get_success_data(
        api.register_member(payload, make_club_admin_headers(club_id)), 201
    )


def _order(api: ApiClient, club_id: str, member_id: str, expedited: bool = False) -> Dict[str, Any]:
    club = get_success_data(api.get_club(club_id, NGB_ADMIN_HEADERS))
    return validate_success(
        api.order_screening(
            member_id,
            {"expedited": expedited, "expected_club_version": club["version"]},
            make_club_admin_headers(club_id),
        ),
        201,
    )


def _head_coach_in_three_states(api: ApiClient) -> Dict[str, Any]:
    """A TIER_3 head coach whose screen spans three jurisdictions."""
    club = _club(api)
    member = _register(
        api,
        club["id"],
        full_name="Harper Diaz",
        email="harper.diaz@alpha.test",
        role_type="HEAD_COACH",
        has_minor_athlete_contact=True,
        date_of_birth="1980-05-05",
        jurisdiction_codes=["CA", "NV", "OR"],
    )
    return {"club": club, "member": member}


def test_discount_band_is_selected_from_the_pre_discount_gross_subtotal(
    api: ApiClient,
) -> None:
    """A gross of 11,400 cents takes the 5 percent band, not the 10 percent band.

    PRD 3.2 says:
    "Step four selects the volume-discount rate **from that pre-discount gross subtotal**: 10 percent when the gross subtotal reaches or exceeds 12,000 cents, otherwise 5 percent when it reaches or exceeds 8,000 cents, otherwise no discount at all."
    and
    "Step five multiplies the gross subtotal by the selected rate and rounds the product half up to a whole cent, recording it as `discount_cents`."
    The TIER_3 base of 9,200 plus a 2,200 surcharge for two extra jurisdictions
    lands the gross below the 12,000 floor even though the expedited total exceeds it.

    Design: Difficulty/combinatorial_formula/screening_charge_discount_keyed_on_pre_discount_gross
    """
    setup = _head_coach_in_three_states(api)

    order = _order(api, setup["club"]["id"], setup["member"]["id"], expedited=True)

    assert_state(order, "tier", "TIER_3")
    assert_counters(order, jurisdiction_count=3)
    assert_money_equals(order, "gross_subtotal_cents", 11400)
    assert_money_equals(order, "discount_cents", 570)
    assert_state(order, "status", "ORDERED")


def test_expedite_fee_is_thirty_five_percent_of_the_post_discount_net(
    api: ApiClient,
) -> None:
    """The expedite fee is 3,791 cents and the charge lands on 14,621 cents.

    PRD 3.2 says:
    "Step seven, only when `expedited` is true, takes 35 percent **of that post-discount net subtotal**, rounds half up to a whole cent, and records it as `expedite_cents`; when `expedited` is false, `expedite_cents` is zero."
    and warns that
    "Note in particular that the discount band is chosen before any expedite fee exists, and the expedite percentage is taken after the discount has been deducted — keying the discount on a post-expedite total, or applying the expedite percentage to the gross subtotal, would both yield a different total."

    Design: Difficulty/combinatorial_formula/screening_charge_discount_keyed_on_pre_discount_gross
    """
    setup = _head_coach_in_three_states(api)

    order = _order(api, setup["club"]["id"], setup["member"]["id"], expedited=True)

    assert_money_equals(order, "expedite_cents", 3791)
    assert_money_equals(order, "charged_cents", 14621)

    club = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_money_equals(club, "escrow_balance_cents", 485379)
    assert_money_equals(club, "total_funded_cents", 500000)

    member = validate_success(api.get_member(setup["member"]["id"], NGB_ADMIN_HEADERS))
    assert_state(member, "screening_status", "SCREENING_ORDERED")


def _audit_with_three_repeat_minor_findings(api: ApiClient) -> Dict[str, Any]:
    """A finalized SELF_ATTESTED audit scoring 33.33 with three open repeat findings."""
    club = _club(api)
    admin = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)

    compliant = _register(
        api, club["id"], full_name="Sasha Long", email="sasha.long@alpha.test"
    )
    second = _register(
        api,
        club["id"],
        full_name="Nico Bell",
        email="nico.bell@alpha.test",
        date_of_birth="1991-03-03",
    )
    third = _register(
        api,
        club["id"],
        full_name="Wren Ortiz",
        email="wren.ortiz@alpha.test",
        date_of_birth="1992-04-04",
    )

    order = _order(api, club["id"], compliant["id"])
    get_success_data(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    get_success_data(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "registry return carried no records"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )
    assignment = get_success_data(
        api.assign_training(
            {
                "member_id": compliant["id"],
                "course_code": "SS101",
                "due_at": "2026-09-01T00:00:00Z",
            },
            admin,
        ),
        201,
    )
    get_success_data(api.start_training(assignment["id"], admin))
    get_success_data(api.complete_training(assignment["id"], {"score": 95}, admin))

    audit = get_success_data(
        api.open_club_audit(
            {
                "club_id": club["id"],
                "audit_period_start": "2026-01-01T00:00:00Z",
                "audit_period_end": "2026-08-01T00:00:00Z",
                "score_variant": "SELF_ATTESTED",
                "sampled_member_ids": [compliant["id"], second["id"], third["id"]],
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )
    findings: List[Dict[str, Any]] = []
    for _ in range(3):
        findings.append(
            get_success_data(
                api.write_finding(
                    audit["id"],
                    {
                        "finding_code": "RECORDS_INCOMPLETE",
                        "severity": "MINOR",
                        "is_repeat": True,
                    },
                    COMPLIANCE_AUDITOR_HEADERS,
                ),
                201,
            )
        )
    finalized = get_success_data(
        api.finalize_club_audit(audit["id"], {}, COMPLIANCE_AUDITOR_HEADERS)
    )
    return {"club": club, "audit": finalized, "findings": findings}


def test_each_finding_fine_is_rounded_before_any_summation(api: ApiClient) -> None:
    """Three identical raw fines of 11,550.275 cents each store 11,550 cents.

    PRD 3.9 says:
    "**Each finding's raw amount is rounded half up to a whole cent and stored as that finding's own `fine_cents` before any summation happens.**"
    A compliance score of 33.33 gives a shortfall factor of one plus 0.012 times
    56.67 points, and a MINOR repeat finding therefore prices at 25,000 times 0.20
    times 1.375 times that factor.

    Design: Difficulty/combinatorial_formula/sanction_fine_rounds_per_finding_before_sum
    """
    setup = _audit_with_three_repeat_minor_findings(api)
    assert_score_equals(setup["audit"]["compliance_score"], "33.33")

    validate_success(
        api.close_club_audit(
            setup["audit"]["id"], {"resolution": "SANCTION"}, COMPLIANCE_AUDITOR_HEADERS
        )
    )

    for finding in setup["findings"]:
        stored = validate_success(
            api.get_audit_finding(finding["id"], COMPLIANCE_AUDITOR_HEADERS)
        )
        assert_money_equals(stored, "fine_cents", 11550)


def test_sanction_total_is_the_sum_of_the_already_rounded_fines(api: ApiClient) -> None:
    """The audit total is 34,650 cents, one cent below the sum-then-round answer.

    PRD 3.9 says:
    "The audit's `sanction_fine_cents` is then the exact integer sum of those already-rounded per-finding amounts, accumulated in ascending `created_at` order of the findings."
    and rules out the alternative explicitly:
    "Summing the raw amounts and rounding once at the end is a different number whenever several findings each carry a fractional part below half a cent that together exceed half a cent, and it is not the specified behaviour."
    The closure also carries the club consequences:
    "The sanction branch then moves the audit `FINDINGS_ISSUED → CLOSED_SANCTIONED` with `closed_at` stamped, sets the club's `sanction_status` to `SUSPENDED`, and consequently forces the club's `compliance_posture` to `FROZEN` — a suspended club is frozen by the posture derivation of §2.9, not by a separate flag."

    Design: Difficulty/combinatorial_formula/sanction_fine_rounds_per_finding_before_sum
    """
    setup = _audit_with_three_repeat_minor_findings(api)

    closed = validate_success(
        api.close_club_audit(
            setup["audit"]["id"], {"resolution": "SANCTION"}, COMPLIANCE_AUDITOR_HEADERS
        )
    )

    assert_money_equals(closed, "sanction_fine_cents", 34650)
    assert closed["sanction_fine_cents"] != 34651
    assert_state(closed, "status", "CLOSED_SANCTIONED")

    club = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_state(club, "sanction_status", "SUSPENDED")
    assert_state(club, "compliance_posture", "FROZEN")


def test_jurisdiction_component_is_capped_at_fifteen_points(api: ApiClient) -> None:
    """Six jurisdictions score the same 15 points that four would score.

    PRD 3.1 says:
    "The jurisdiction component contributes 5 points for each jurisdiction beyond the first — that is, five points multiplied by the number of entries in `jurisdiction_codes` less one, never taken below zero — and is capped at 15 points, so a screen covering four or more states contributes the same 15 as one covering six."
    Combined with the role branch,
    "The role component contributes 40 points for a `HEAD_COACH`, 30 for an `ASSISTANT_COACH`, 25 for a `CHAPERONE`, 20 for an `OFFICIAL`, and 10 for a `VOLUNTEER`."
    a head coach in six states scores 80 rather than the 90 an uncapped term gives.

    Design: Difficulty/combinatorial_formula/screening_tier_nested_caps_with_role_branch
    """
    club = _club(api)

    six_states = _register(
        api,
        club["id"],
        full_name="Kai Mercer",
        email="kai.mercer@alpha.test",
        role_type="HEAD_COACH",
        has_minor_athlete_contact=True,
        date_of_birth="1979-06-06",
        jurisdiction_codes=["CA", "NV", "OR", "WA", "AZ", "ID"],
    )
    three_states = _register(
        api,
        club["id"],
        full_name="Tess Iyer",
        email="tess.iyer@alpha.test",
        role_type="VOLUNTEER",
        has_minor_athlete_contact=True,
        date_of_birth="1988-07-07",
        jurisdiction_codes=["CA", "NV", "OR"],
    )

    assert_counters(six_states, risk_points=80)
    assert_state(six_states, "required_tier", "TIER_3")
    assert_counters(three_states, risk_points=45)
    assert_state(three_states, "required_tier", "TIER_2")


def test_history_component_is_capped_at_thirty_points(api: ApiClient) -> None:
    """Three non-disqualifying records score 30 points, not 36, holding TIER_1.

    PRD 3.1 says:
    "The history component counts two lifetime exposures with no time window at all: each of the member's own screening orders that reached status `ADJUDICATED` with a `disposition` of `NON_DISQUALIFYING_RECORD` contributes 12 points (orders still `ORDERED`, still `RESULT_RETURNED`, or `VOIDED` contribute nothing), and each audit finding written against this member that currently stands in status `OPEN` contributes 6 points (findings that are `REMEDIATED` or `WAIVED` contribute nothing), across every audit of every club; the sum of those two contributions is then capped at 30 points."
    The capped total keeps the volunteer under the tier boundary, where
    "a score that reaches or exceeds 75 demands `TIER_3`, otherwise a score that reaches or exceeds 45 demands `TIER_2`, otherwise `TIER_1`"
    resolves to TIER_1.

    Design: Difficulty/combinatorial_formula/screening_tier_nested_caps_with_role_branch
    """
    club = _club(api)
    member = _register(
        api,
        club["id"],
        full_name="Ari Voss",
        email="ari.voss@alpha.test",
        date_of_birth="1993-08-08",
    )

    third_order = None
    for rationale in (
        "minor traffic matter, not disqualifying",
        "same minor matter re-verified",
        "third pass, still not disqualifying",
    ):
        third_order = _order(api, club["id"], member["id"])
        get_success_data(
            api.post_screening_result(
                third_order["id"],
                {"vendor_disposition": "RECORD_FOUND"},
                SCREENING_VENDOR_HEADERS,
            )
        )
        get_success_data(
            api.adjudicate_screening_order(
                third_order["id"],
                {"disposition": "NON_DISQUALIFYING_RECORD", "rationale": rationale},
                OFFICER_ADJUDICATOR_HEADERS,
            )
        )

    assert third_order is not None
    assert_state(third_order, "tier", "TIER_1")

    final = validate_success(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    assert_counters(final, risk_points=40)
    assert_state(final, "required_tier", "TIER_1")
    assert_state(final, "screening_status", "CLEARED")

    club_now = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_money_equals(club_now, "escrow_balance_cents", 492500)
