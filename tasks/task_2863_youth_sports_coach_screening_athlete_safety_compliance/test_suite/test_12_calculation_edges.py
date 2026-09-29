"""Arithmetic edges: the rounding tie, the two score short-circuits and the minima.

Every literal asserted here is recomputed by hand from the PRD's pinned steps
before it is written down, so a test that fails names the step that drifted:
the half-cent expedite tie, the ordered short-circuits of the compliance score,
the downward recomputation of the club posture, the BOOKED-only overlap input
set, and the minimum that produces a member's forward eligibility horizon.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_counters,
    assert_finding_partition,
    assert_instant_equals,
    assert_money_equals,
    assert_pagination_meta,
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
MINOR_BED = {
    "occupant_kind": "MINOR_ATHLETE",
    "trip_label": "SPRING_MEET",
    "room_number": "204",
    "check_in": "2026-10-10T15:00:00Z",
    "check_out": "2026-10-12T11:00:00Z",
}
THIRD_BED = {
    "occupant_kind": "MINOR_ATHLETE",
    "trip_label": "SPRING_MEET",
    "room_number": "204",
    "check_in": "2026-10-11T15:00:00Z",
    "check_out": "2026-10-12T11:00:00Z",
    "minor_athlete_age": 14,
}


def _epoch(api: ApiClient) -> None:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))


def _club(api: ApiClient) -> Dict[str, Any]:
    _epoch(api)
    return get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)


def _member(
    api: ApiClient,
    club_id: str,
    name: str,
    email: str,
    dob: str,
    role_type: str = "VOLUNTEER",
    contact: bool = False,
    codes: Iterable[str] = ("CA",),
) -> Dict[str, Any]:
    return get_success_data(
        api.register_member(
            {
                "club_id": club_id,
                "full_name": name,
                "email": email,
                "role_type": role_type,
                "has_minor_athlete_contact": contact,
                "date_of_birth": dob,
                "jurisdiction_codes": list(codes),
            },
            make_club_admin_headers(club_id),
        ),
        201,
    )


def _live_club_version(api: ApiClient, club_id: str) -> int:
    club = get_success_data(api.get_club(club_id, make_club_admin_headers(club_id)))
    return club["version"]


def _open_audit(
    api: ApiClient,
    club_id: str,
    start: str,
    end: str,
    variant: str,
    sample: Iterable[str],
) -> Dict[str, Any]:
    return get_success_data(
        api.open_club_audit(
            {
                "club_id": club_id,
                "audit_period_start": start,
                "audit_period_end": end,
                "score_variant": variant,
                "sampled_member_ids": list(sample),
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )


def test_the_expedite_fee_breaks_a_half_cent_tie_upward_on_the_post_discount_net(
    api: ApiClient,
) -> None:
    """A TIER_3 four-jurisdiction expedited order nets 11250, and 35 percent of it ties at 3937.5.

    PRD 3.1 says:
    "The role component contributes 40 points for a `HEAD_COACH`, 30 for an `ASSISTANT_COACH`, 25 for a `CHAPERONE`, 20 for an `OFFICIAL`, and 10 for a `VOLUNTEER`."
    "The contact component contributes 25 points when `has_minor_athlete_contact` is true and nothing when it is false."
    "The jurisdiction component contributes 5 points for each jurisdiction beyond the first — that is, five points multiplied by the number of entries in `jurisdiction_codes` less one, never taken below zero — and is capped at 15 points, so a screen covering four or more states contributes the same 15 as one covering six."
    "The score selects a screening tier and writes it to `required_tier`: a score that reaches or exceeds 75 demands `TIER_3`, otherwise a score that reaches or exceeds 45 demands `TIER_2`, otherwise `TIER_1`."

    PRD 3.2 says:
    "Step one takes the tier base fee: 2,500 cents for `TIER_1`, 4,800 cents for `TIER_2`, and 9,200 cents for `TIER_3`."
    "Step two computes the multi-jurisdiction surcharge as 1,100 cents for each jurisdiction beyond the first — that is, 1,100 multiplied by the order's `jurisdiction_count` less one, never taken below zero."
    "Step four selects the volume-discount rate **from that pre-discount gross subtotal**: 10 percent when the gross subtotal reaches or exceeds 12,000 cents, otherwise 5 percent when it reaches or exceeds 8,000 cents, otherwise no discount at all."
    "Step seven, only when `expedited` is true, takes 35 percent **of that post-discount net subtotal**, rounds half up to a whole cent, and records it as `expedite_cents`; when `expedited` is false, `expedite_cents` is zero."
    "Step eight adds the net subtotal and the expedite fee to give `charged_cents`."
    "Rounding happens exactly twice, at step five and step seven, and `charged_cents` itself is never rounded again."
    "A successful order is written in status `ORDERED` with all four money fields stamped, the club's `escrow_balance_cents` is debited by `charged_cents`, the club's `version` advances by one, and the member's screening dimension moves `UNSCREENED → SCREENING_ORDERED` (or `CLEARED → SCREENING_ORDERED`, or `EXPIRED → SCREENING_ORDERED`, all three governed by the identical preconditions and side effects)."

    PRD 2.7 says:
    "Wherever a percentage or multiplier produces a fractional cent, the result is rounded half up to a whole cent, and the document below states exactly where each rounding occurs; a total is never rounded a second time after its rounded components have been summed."

    Design: Corner/calculations/expedite_fee_rounds_half_up_on_the_post_discount_net
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    member = _member(
        api,
        club["id"],
        "Pat Rowe",
        "pat.rowe@alpha.test",
        "1980-08-14",
        role_type="HEAD_COACH",
        contact=True,
        codes=("CA", "NV", "AZ", "OR"),
    )
    # 40 for the head coach, 25 for minor-athlete contact, and 5 * 3 capped at 15.
    assert_counters(member, risk_points=80)
    assert_state(member, "required_tier", "TIER_3")

    order = validate_success(
        api.order_screening(
            member["id"],
            {
                "expedited": True,
                "expected_club_version": _live_club_version(api, club["id"]),
            },
            headers,
        ),
        201,
    )
    assert_state(order, "tier", "TIER_3")
    assert_counters(order, jurisdiction_count=4)
    # 9200 + 1100 * 3 = 12500, which reaches the 12,000-cent band, so the
    # discount is exactly 1250 and the net subtotal is exactly 11250.
    assert_money_equals(order, "gross_subtotal_cents", 12500)
    assert_money_equals(order, "discount_cents", 1250)
    # 11250 * 0.35 = 3937.5 exactly; rounded half up that is 3938, not 3937.
    assert_money_equals(order, "expedite_cents", 3938)
    assert_money_equals(order, "charged_cents", 15188)

    after = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_money_equals(after, "escrow_balance_cents", 484812)
    assert_money_equals(after, "total_funded_cents", 500000)


def test_a_cancelled_bed_stops_counting_so_the_third_stay_fits_on_the_second_attempt(
    api: ApiClient,
) -> None:
    """The capacity rule counts BOOKED neighbours only, so cancelling one reopens the slot.

    PRD 3.7 says:
    "Two overlap rules then run against the stays already in the same slot, and only stays in status `BOOKED` participate — a `CANCELLED` stay never conflicts with anything."
    "The platform first collects the neighbouring stays: those in the same slot, in status `BOOKED`, whose interval intersects the requested one, where intersection means the requested `check_in` falls strictly before the neighbour's `check_out` and the neighbour's `check_in` falls strictly before the requested `check_out`."
    "If the number of neighbours plus the requested booking would exceed two occupants, the request is refused with `ERR_ROOM_OCCUPANCY_CONFLICT`."
    "A successful booking is written in status `BOOKED` with `cancel_reason` null."
    "The club administrator supplies a `reason`, which is retained as `cancel_reason`, and the stay moves `BOOKED → CANCELLED`; from that moment its interval no longer participates in either overlap rule, so the freed slot can be rebooked immediately."

    PRD 2.3 says:
    "Flat collections with foreign-key filters exist alongside those nested paths so that every relationship declared in this system is reverse-reachable: screening orders can be listed by `member_id`, training assignments by `member_id` and `course_code`, coach placements by `member_id` and by `club_id`, cases by `club_id`, `reported_member_id`, and `investigating_body_id`, interim measures by `case_id` and `member_id`, audits by `club_id` and by `score_variant`, findings by `audit_id`, `member_id`, and `severity`, and room stays by `club_id`, `member_id`, `trip_label`, and `room_number`."
    "Every one of these list endpoints additionally accepts a `status` filter matching that resource's own state field, and the member lists accept `screening_status`, `membership_status`, `contact_eligibility`, and `role_type`."
    "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` is true exactly when rows remain beyond the current window."

    Design: Corner/calculations/cancelled_stay_frees_the_slot_for_a_third_booking
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    first = get_success_data(
        api.book_room_stay(
            club["id"], dict(MINOR_BED, minor_athlete_age=12), headers
        ),
        201,
    )
    second = validate_success(
        api.book_room_stay(
            club["id"], dict(MINOR_BED, minor_athlete_age=13), headers
        ),
        201,
    )
    assert_state(second, "status", "BOOKED")

    # Both neighbours are BOOKED and both intersect the requested window, so the
    # third bed would put three occupants in a slot that holds two.
    validate_error(
        api.book_room_stay(club["id"], dict(THIRD_BED), headers),
        ApiErrorId.ROOM_OCCUPANCY_CONFLICT,
        409,
    )

    cancelled = validate_success(
        api.cancel_room_stay(
            second["id"], {"reason": "athlete moved to a different room"}, headers
        )
    )
    assert_state(cancelled, "status", "CANCELLED")
    assert_state(cancelled, "cancel_reason", "athlete moved to a different room")
    # The row keeps its original interval; it simply stops participating.
    assert_instant_equals(cancelled["check_in"], "2026-10-10T15:00:00.000Z")
    assert_instant_equals(cancelled["check_out"], "2026-10-12T11:00:00.000Z")

    third = validate_success(
        api.book_room_stay(club["id"], dict(THIRD_BED), headers), 201
    )
    assert_state(third, "status", "BOOKED")
    assert third["cancel_reason"] is None, (
        f"a fresh booking carries no cancel_reason: {third['cancel_reason']!r}"
    )

    rows, meta = validate_paginated(
        api.list_room_stays(
            NGB_ADMIN_HEADERS,
            club_id=club["id"],
            trip_label="SPRING_MEET",
            room_number="204",
            status="BOOKED",
        )
    )
    assert_pagination_meta(meta, total=2, limit=10, offset=0)
    assert {row["id"] for row in rows} == {first["id"], third["id"]}, (
        f"expected the two live beds, got {[row['id'] for row in rows]}"
    )


def test_an_empty_sample_scores_one_hundred_while_a_zero_denominator_scores_nothing(
    api: ApiClient,
) -> None:
    """The two short-circuit clauses are ordered, and both of them are reachable.

    PRD 3.9 says:
    "The sample list holds between zero and fifty entries with no duplicates, and every entry must be a member of the audited club — a foreign member in the sample is refused with `ERR_CLUB_SCOPE_VIOLATION`, and an id that matches no member at all with `ERR_MEMBER_NOT_FOUND`."
    "The audit is created in status `SAMPLED`, with `sampled_member_count` set to the number of entries supplied, `compliant_member_count`, `denominator_count`, `compliance_score`, and `sanction_fine_cents` all null, all four finding counters at zero, and `finalized_at`, `closed_at`, and `resolution` null."
    "The numerator, `compliant_member_count`, is the number of the audit's own sampled members who satisfy all four conditions at the moment of finalization — not at sampling time — namely a `screening_status` of `CLEARED`, a `training_status` of `CURRENT`, a `membership_status` of `ACTIVE`, and no interim measure against them in status `ACTIVE` or `PERMANENT`."
    "Under `SELF_ATTESTED` it is the club's `roster_size_attested`, the figure the club itself supplied at charter time, so an inflated attestation drives the score down for exactly the same sample."
    "Under `REGISTRY_VERIFIED` it is the live number of coach placements at that club in status `PENDING` or `ACTIVE`; placements that are `SUSPENDED`, `EXPIRED`, or `TERMINATED` are excluded, which is what makes a sanctioned club's registry denominator shrink."
    "When the audit's `sampled_member_count` is zero the score is exactly 100.00 — an audit that sampled nobody found nothing wrong with anybody."
    "Otherwise, when `denominator_count` is zero the score is exactly 0.00."
    "Finalize copies the resulting score onto the club's own `compliance_score` field and re-derives the club's `open_finding_count`, `critical_open_finding_count`, and `compliance_posture`."

    Design: Corner/calculations/compliance_score_returns_the_documented_edge_values
    """
    club = _club(api)
    member = _member(api, club["id"], "Ed Dane", "ed.dane@alpha.test", "1992-09-15")

    empty = _open_audit(
        api,
        club["id"],
        "2026-01-01T00:00:00Z",
        "2026-03-31T00:00:00Z",
        "SELF_ATTESTED",
        [],
    )
    assert_counters(empty, sampled_member_count=0)
    # This club has no coach placement at all, so a registry denominator is zero
    # even though the sample is not.
    zero = _open_audit(
        api,
        club["id"],
        "2026-04-01T00:00:00Z",
        "2026-06-30T00:00:00Z",
        "REGISTRY_VERIFIED",
        [member["id"]],
    )
    assert_counters(zero, sampled_member_count=1)

    empty_final = validate_success(
        api.finalize_club_audit(empty["id"], {}, COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_score_equals(empty_final["compliance_score"], "100.00")
    assert_counters(empty_final, compliant_member_count=0, denominator_count=3)

    zero_final = validate_success(
        api.finalize_club_audit(zero["id"], {}, COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_score_equals(zero_final["compliance_score"], "0.00")
    assert_counters(zero_final, compliant_member_count=0, denominator_count=0)

    after = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_score_equals(after["compliance_score"], "0.00")


def test_waiving_one_of_three_open_findings_walks_the_posture_back_down_to_open(
    api: ApiClient,
) -> None:
    """Three OPEN findings sit exactly on the restriction threshold, and a waiver drops below it.

    PRD 2.9 says:
    "The posture is recomputed by the platform, never set by a caller, and it is re-derived inside every operation that touches the club's findings, its sanction standing, or the eligibility of a member holding a placement there."
    "The posture is `FROZEN` when the club's `sanction_status` is either `SUSPENDED` or `TERMINATED`, or when its `critical_open_finding_count` reaches or exceeds one."
    "Otherwise the posture is `RESTRICTED` when the club's `open_finding_count` reaches or exceeds three, or when its `restricted_member_count` reaches or is above one."
    "Otherwise the posture is `OPEN`."
    "`open_finding_count` on the club counts every finding in status `OPEN` across every audit of that club, regardless of what status those audits themselves are in; `critical_open_finding_count` is the same count narrowed to findings whose `severity` is `CRITICAL`."

    PRD 2.12 says:
    "For every audit, `finding_total_count` equals the sum of `open_finding_count`, `remediated_finding_count`, and `waived_finding_count`, and also equals the number of findings actually written against that audit, irrespective of their `severity`, their `member_id`, or whether `fine_cents` has been stamped."

    PRD 3.9 says:
    "The finding is created in status `OPEN` with `fine_cents`, `evidence_note`, and `decision_note` null; the audit's `finding_total_count` and `open_finding_count` both rise by one, preserving the finding partition identity; and the club's `open_finding_count`, `critical_open_finding_count`, and `compliance_posture` are re-derived, which is how a single `CRITICAL` finding freezes a club the moment it is written."
    "A `ComplianceAuditor` may instead submit `WAIVED` against a finding in status `OPEN`: the finding moves `OPEN → WAIVED`, the `note` is retained as `decision_note`, `open_finding_count` falls by one while `waived_finding_count` rises by one, the finding is thereafter excluded from any fine, and the club's counters and posture are re-derived."

    Design: Corner/calculations/waiving_the_third_open_finding_relaxes_posture_from_restricted_to_open
    """
    club = _club(api)
    member = _member(api, club["id"], "Pola Ott", "pola.ott@alpha.test", "1993-10-16")
    audit = _open_audit(
        api,
        club["id"],
        "2026-01-01T00:00:00Z",
        "2026-06-30T00:00:00Z",
        "SELF_ATTESTED",
        [member["id"]],
    )
    findings = [
        get_success_data(
            api.write_finding(
                audit["id"],
                {
                    "finding_code": code,
                    "severity": "MINOR",
                    "member_id": member["id"],
                    "is_repeat": False,
                },
                COMPLIANCE_AUDITOR_HEADERS,
            ),
            201,
        )
        for code in ("RECORDS_INCOMPLETE", "TRAINING_LAPSED", "UNSCREENED_CONTACT")
    ]
    get_success_data(
        api.finalize_club_audit(audit["id"], {}, COMPLIANCE_AUDITOR_HEADERS)
    )

    before = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_counters(before, open_finding_count=3, critical_open_finding_count=0)
    assert_state(before, "compliance_posture", "RESTRICTED")

    waived = validate_success(
        api.decide_finding(
            findings[2]["id"],
            {"decision": "WAIVED", "note": "finding withdrawn after document review"},
            COMPLIANCE_AUDITOR_HEADERS,
        )
    )
    assert_state(waived, "status", "WAIVED")

    after = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_counters(after, open_finding_count=2, critical_open_finding_count=0)
    assert_state(after, "compliance_posture", "OPEN")

    reread = validate_success(
        api.get_club_audit(audit["id"], COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_counters(reread, open_finding_count=2, waived_finding_count=1)
    assert_finding_partition(reread, 3)


def test_the_projection_is_null_until_both_legs_exist_and_then_takes_the_earlier_one(
    api: ApiClient,
) -> None:
    """A cleared screen alone projects nothing; the completion supplies the earlier horizon.

    PRD 3.3 says:
    "On the two clearing dispositions the order moves `RESULT_RETURNED → ADJUDICATED`, `adjudicated_at` is stamped with the clock, and the order's `expires_at` is set to `adjudicated_at` plus 730 days — the two-year screening validity period."
    "The member's screening dimension moves to `CLEARED` (from `SCREENING_ORDERED` on a `CLEAR`, from either `SCREENING_ORDERED` or `FLAGGED` on a `NON_DISQUALIFYING_RECORD`), and `screening_expires_at` on the member is set from the order's `expires_at`."

    PRD 3.4 says:
    "The assignment moves `IN_PROGRESS → COMPLETED`, stamping `completed_at` from the clock, the submitted `score`, and `expires_at` as `completed_at` plus that course's `validity_days`."
    "Otherwise `training_status` is `CURRENT`."
    "Otherwise the value is `ELIGIBLE`."

    PRD 3.5 says:
    "The response reports the `variant` actually applied, the resulting `projected_eligible_through`, the two horizons it was built from as `screening_expiry` and `training_expiry`, the member's current `screening_status`, `training_status`, `membership_status`, `contact_eligibility`, `required_tier`, and `risk_points`, the retention horizon `records_retained_through`, and a `blocking_reasons` array listing the conditions that currently stand between this member and athlete contact."
    "Second, the **screening horizon** is the latest `expires_at` among the member's own screening orders that reached status `ADJUDICATED` with a `disposition` of `CLEAR` or `NON_DISQUALIFYING_RECORD`; when two such orders carry the identical `expires_at`, the one with the earlier `created_at` is the row selected, and when the member has no such order at all the screening horizon is null."
    "If a required course has no candidate assignment at all, its per-course expiry is null."
    "`projected_eligible_through` is then null if either the screening horizon or the training horizon is null, and otherwise the earlier of the two."
    "Under `AUDIT_SNAPSHOT` the candidate set is `COMPLETED` alone: an in-flight course contributes nothing, so a member whose only completion for a required course is old projects an earlier horizon, or none at all."
    "`AUDIT_SNAPSHOT` is the variant the platform itself always uses: it is the view stamped onto the member's `eligible_through` on every adjudication, every training completion, and every renewal, and it is the view every audit compliance evaluation reads."

    Design: Corner/calculations/eligible_through_is_the_earlier_of_the_screening_and_training_expiries
    """
    club = _club(api)
    headers = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = _member(api, club["id"], "Mona Nash", "mona.nash@alpha.test", "1994-11-17")

    order = get_success_data(
        api.order_screening(
            member["id"],
            {
                "expedited": False,
                "expected_club_version": _live_club_version(api, club["id"]),
            },
            headers,
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
    assignment = get_success_data(
        api.assign_training(
            {
                "member_id": member["id"],
                "course_code": "SS101",
                "due_at": "2026-09-01T00:00:00Z",
            },
            headers,
        ),
        201,
    )
    get_success_data(api.start_training(assignment["id"], headers))

    # 2026-08-01 plus 730 days is 2028-07-31, but the started course is not a
    # candidate under AUDIT_SNAPSHOT, so the training leg is still missing.
    before = validate_success(
        api.get_eligibility_projection(
            member["id"], headers, variant="AUDIT_SNAPSHOT"
        )
    )
    assert_instant_equals(before["screening_expiry"], "2028-07-31T00:00:00.000Z")
    assert before["training_expiry"] is None, (
        f"an IN_PROGRESS assignment is no candidate: {before['training_expiry']!r}"
    )
    assert before["projected_eligible_through"] is None, (
        "one missing leg nullifies the projection: "
        f"{before['projected_eligible_through']!r}"
    )

    completed = validate_success(
        api.complete_training(assignment["id"], {"score": 88}, headers)
    )
    # 2026-08-01 plus the course's 365 validity days is 2027-08-01.
    assert_instant_equals(completed["expires_at"], "2027-08-01T00:00:00.000Z")

    after = validate_success(
        api.get_eligibility_projection(
            member["id"], headers, variant="AUDIT_SNAPSHOT"
        )
    )
    assert_state(after, "variant", "AUDIT_SNAPSHOT")
    assert_instant_equals(after["training_expiry"], "2027-08-01T00:00:00.000Z")
    assert_instant_equals(after["screening_expiry"], "2028-07-31T00:00:00.000Z")
    # The training horizon is the earlier of the two, so it wins.
    assert_instant_equals(
        after["projected_eligible_through"], "2027-08-01T00:00:00.000Z"
    )
    assert_state(after, "training_status", "CURRENT")
    assert_state(after, "contact_eligibility", "ELIGIBLE")

    reread = validate_success(api.get_member(member["id"], headers))
    assert_instant_equals(reread["eligible_through"], "2027-08-01T00:00:00.000Z")
    assert_instant_equals(reread["screening_expires_at"], "2028-07-31T00:00:00.000Z")
