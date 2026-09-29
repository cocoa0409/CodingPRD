"""The two computed reads whose answer is chosen by a variant.

Both the member eligibility projection and the club compliance score are
specified twice over: one formula, two candidate sets.  These tests pin the
divergence, because a single-variant implementation passes half of them.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_counters, assert_score_equals, assert_state
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR_HEADERS,
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    SCREENING_VENDOR_HEADERS,
    make_club_admin_headers,
)

SS101 = {
    "code": "SS101",
    "title": "Abuse Prevention Core",
    "validity_days": 365,
    "delivery_mode": "ONLINE",
    "required_for_tiers": ["TIER_1", "TIER_2", "TIER_3"],
    "pass_score": 80,
}
SS201 = {
    "code": "SS201",
    "title": "Mandatory Reporting",
    "validity_days": 730,
    "delivery_mode": "ONLINE",
    "required_for_tiers": ["TIER_2", "TIER_3"],
    "pass_score": 80,
}
ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}


def _clear_screening(api: ApiClient, club_id: str, club_version: int, member_id: str) -> None:
    """Order, return and adjudicate a clean screen so the member reaches CLEARED."""
    admin = make_club_admin_headers(club_id)
    order = get_success_data(
        api.order_screening(
            member_id,
            {"expedited": False, "expected_club_version": club_version},
            admin,
        ),
        201,
    )
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


def _tier_two_member_with_one_course_in_flight(api: ApiClient) -> Tuple[str, str]:
    """A CLEARED TIER_2 member holding SS101 COMPLETED and SS201 only IN_PROGRESS."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    get_success_data(api.publish_course(SS201, NGB_ADMIN_HEADERS), 201)
    member = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Dana Reyes",
                "email": "dana.reyes@alpha.test",
                "role_type": "ASSISTANT_COACH",
                "has_minor_athlete_contact": True,
                "date_of_birth": "1985-04-11",
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    _clear_screening(api, club["id"], club["version"], member["id"])

    ta101 = get_success_data(
        api.assign_training(
            {
                "member_id": member["id"],
                "course_code": "SS101",
                "due_at": "2026-09-01T00:00:00Z",
            },
            admin,
        ),
        201,
    )
    get_success_data(api.start_training(ta101["id"], admin))
    get_success_data(api.complete_training(ta101["id"], {"score": 90}, admin))

    ta201 = get_success_data(
        api.assign_training(
            {
                "member_id": member["id"],
                "course_code": "SS201",
                "due_at": "2026-10-01T00:00:00Z",
            },
            admin,
        ),
        201,
    )
    get_success_data(api.start_training(ta201["id"], admin))
    return club["id"], member["id"]


def test_audit_snapshot_projection_ignores_the_course_that_is_only_in_progress(
    api: ApiClient,
) -> None:
    """A required course still in flight leaves the audit-snapshot horizon null.

    PRD 3.5 says:
    "Under `AUDIT_SNAPSHOT` the candidate set is `COMPLETED` alone: an in-flight course contributes nothing, so a member whose only completion for a required course is old projects an earlier horizon, or none at all."
    With the training horizon null the whole projection collapses:
    "`projected_eligible_through` is then null if either the screening horizon or the training horizon is null, and otherwise the earlier of the two."

    Design: Difficulty/dual_variant_calc/eligibility_projection_audit_snapshot_vs_renewal_forward
    """
    club_id, member_id = _tier_two_member_with_one_course_in_flight(api)
    admin = make_club_admin_headers(club_id)

    snapshot = validate_success(
        api.get_eligibility_projection(member_id, admin, variant="AUDIT_SNAPSHOT")
    )

    assert snapshot["variant"] == "AUDIT_SNAPSHOT"
    assert snapshot["training_expiry"] is None
    assert snapshot["projected_eligible_through"] is None
    assert snapshot["screening_expiry"] == "2028-07-31T00:00:00.000Z"

    member = validate_success(api.get_member(member_id, admin))
    assert member["eligible_through"] is None
    assert_state(member, "required_tier", "TIER_2")
    assert_counters(member, risk_points=55)


def test_renewal_forward_projection_credits_the_in_progress_course_at_its_due_at(
    api: ApiClient,
) -> None:
    """The forward variant projects the started course to finish on its deadline.

    PRD 3.5 says:
    "Under `RENEWAL_FORWARD` the candidate set is `COMPLETED` together with `IN_PROGRESS`: an in-progress assignment is projected to complete at its `due_at` and therefore contributes `due_at` plus `validity_days`, which can move the answer years later than the audit-snapshot answer over exactly the same rows."
    The two answers must differ over identical rows, because
    "The two variants differ in exactly one respect — which assignment statuses count as candidates."

    Design: Difficulty/dual_variant_calc/eligibility_projection_audit_snapshot_vs_renewal_forward
    """
    club_id, member_id = _tier_two_member_with_one_course_in_flight(api)
    admin = make_club_admin_headers(club_id)

    snapshot = validate_success(
        api.get_eligibility_projection(member_id, admin, variant="AUDIT_SNAPSHOT")
    )
    forward = validate_success(
        api.get_eligibility_projection(member_id, admin, variant="RENEWAL_FORWARD")
    )

    assert forward["variant"] == "RENEWAL_FORWARD"
    assert forward["training_expiry"] == "2027-08-01T00:00:00.000Z"
    assert forward["projected_eligible_through"] == "2027-08-01T00:00:00.000Z"
    assert forward["screening_expiry"] == "2028-07-31T00:00:00.000Z"
    assert snapshot["projected_eligible_through"] != forward["projected_eligible_through"]


def _two_audits_over_one_sample(api: ApiClient) -> Dict[str, Any]:
    """One compliant member out of three sampled, one PENDING placement, two audits."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)

    people = []
    for full_name, email, dob in (
        ("Corey Vance", "corey.vance@alpha.test", "1990-02-02"),
        ("Blair Nunez", "blair.nunez@alpha.test", "1991-03-03"),
        ("Rowan Pike", "rowan.pike@alpha.test", "1992-04-04"),
    ):
        people.append(
            get_success_data(
                api.register_member(
                    {
                        "club_id": club["id"],
                        "full_name": full_name,
                        "email": email,
                        "role_type": "VOLUNTEER",
                        "has_minor_athlete_contact": False,
                        "date_of_birth": dob,
                        "jurisdiction_codes": ["CA"],
                    },
                    admin,
                ),
                201,
            )
        )
    compliant, _second, _third = people

    current_club = get_success_data(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    _clear_screening(api, club["id"], current_club["version"], compliant["id"])

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

    get_success_data(
        api.create_coach_assignment(
            {
                "member_id": compliant["id"],
                "club_id": club["id"],
                "team_name": "Senior Squad",
                "season_start": "2026-09-01T00:00:00Z",
                "season_end": "2027-06-01T00:00:00Z",
            },
            admin,
        ),
        201,
    )

    sample = [person["id"] for person in people]
    audits = {}
    for variant in ("SELF_ATTESTED", "REGISTRY_VERIFIED"):
        audits[variant] = get_success_data(
            api.open_club_audit(
                {
                    "club_id": club["id"],
                    "audit_period_start": "2026-01-01T00:00:00Z",
                    "audit_period_end": "2026-08-01T00:00:00Z",
                    "score_variant": variant,
                    "sampled_member_ids": sample,
                },
                COMPLIANCE_AUDITOR_HEADERS,
            ),
            201,
        )
    return {"club_id": club["id"], "audits": audits}


def test_self_attested_variant_divides_by_the_roster_the_club_attested(
    api: ApiClient,
) -> None:
    """One compliant member out of an attested roster of three scores 33.33.

    PRD 3.9 says:
    "Under `SELF_ATTESTED` it is the club's `roster_size_attested`, the figure the club itself supplied at charter time, so an inflated attestation drives the score down for exactly the same sample."
    The numerator counts only the fully compliant sampled member, and the score is
    "one hundred multiplied by the numerator and divided by the denominator, rounded half up to two decimal places, and capped at 100.00"

    Design: Difficulty/dual_variant_calc/compliance_score_self_attested_vs_registry_verified
    """
    setup = _two_audits_over_one_sample(api)
    audit_id = setup["audits"]["SELF_ATTESTED"]["id"]

    finalized = validate_success(
        api.finalize_club_audit(audit_id, {}, COMPLIANCE_AUDITOR_HEADERS)
    )

    assert_counters(
        finalized, compliant_member_count=1, denominator_count=3, sampled_member_count=3
    )
    assert_score_equals(finalized["compliance_score"], "33.33")
    assert_state(finalized, "status", "FINDINGS_ISSUED")


def test_registry_verified_variant_divides_by_the_live_placement_count(
    api: ApiClient,
) -> None:
    """The same sample and the same numerator score 100.00 against one placement.

    PRD 3.9 says:
    "Under `REGISTRY_VERIFIED` it is the live number of coach placements at that club in status `PENDING` or `ACTIVE`; placements that are `SUSPENDED`, `EXPIRED`, or `TERMINATED` are excluded, which is what makes a sanctioned club's registry denominator shrink."
    And the two answers are required to disagree here:
    "For identical sampled members and identical compliance the two variants yield different scores whenever the attested roster differs from the registry count."

    Design: Difficulty/dual_variant_calc/compliance_score_self_attested_vs_registry_verified
    """
    setup = _two_audits_over_one_sample(api)
    self_attested = validate_success(
        api.finalize_club_audit(
            setup["audits"]["SELF_ATTESTED"]["id"], {}, COMPLIANCE_AUDITOR_HEADERS
        )
    )
    registry = validate_success(
        api.finalize_club_audit(
            setup["audits"]["REGISTRY_VERIFIED"]["id"], {}, COMPLIANCE_AUDITOR_HEADERS
        )
    )

    assert_counters(
        registry, compliant_member_count=1, denominator_count=1, sampled_member_count=3
    )
    assert_score_equals(registry["compliance_score"], "100.00")
    assert_score_equals(self_attested["compliance_score"], "33.33")

    club = validate_success(api.get_club(setup["club_id"], NGB_ADMIN_HEADERS))
    assert_score_equals(club["compliance_score"], "100.00")
