"""Version pinning on two different parents, one freeze threshold, and immediate visibility.

These three cases share a shape: a write is rejected or accepted on the strength
of a value the caller last observed, and the very next read is expected to agree
with the write that produced it.  Nothing here waits, retries or polls.
"""

from __future__ import annotations

from typing import Any, Dict, Sequence

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
    assert_money_equals,
    assert_pagination_meta,
    assert_score_equals,
    assert_state,
    assert_version_is,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    COMPLIANCE_AUDITOR_HEADERS,
    NGB_ADMIN_HEADERS,
    OFFICER_IMPOSE_HEADERS,
    OFFICER_INTAKE_HEADERS,
    make_club_admin_headers,
)

ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}


def _epoch(api: ApiClient) -> None:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))


def _club(api: ApiClient) -> Dict[str, Any]:
    return get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)


def _member(
    api: ApiClient,
    club_id: str,
    name: str,
    email: str,
    dob: str,
    role_type: str = "VOLUNTEER",
    contact: bool = False,
    codes: Sequence[str] = ("CA",),
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


def _audit(
    api: ApiClient, club_id: str, sampled: Sequence[str]
) -> Dict[str, Any]:
    return get_success_data(
        api.open_club_audit(
            {
                "club_id": club_id,
                "audit_period_start": "2026-01-01T00:00:00Z",
                "audit_period_end": "2026-06-30T00:00:00Z",
                "score_variant": "SELF_ATTESTED",
                "sampled_member_ids": list(sampled),
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )


def test_a_stale_club_version_and_a_stale_member_version_are_each_refused_then_retried(
    api: ApiClient,
) -> None:
    """Two pinned parents go stale in the same fixture, and each rejection leaves no row behind.

    PRD 2.6 says:
    "Ordering a background screen requires `expected_club_version`, carrying the `version` of the chartering `Club` that the caller last observed. If it does not equal the club's current `version`, the request is refused with `ERR_STALE_CLUB_VERSION` (HTTP 412): another screening order, a void, or an escrow funding has already moved the balance the caller budgeted against, so the debit would be computed from a stale escrow view."
    "Imposing an interim measure likewise requires `expected_member_version` against the `Member` named in the measure, and a mismatch with the member's current `version` is refused with `ERR_STALE_MEMBER_VERSION` (HTTP 412). A second measure of a different kind against an unchanged member is legitimate and would succeed, so this version check is the only guard against restricting a member record the caller has not actually observed."

    PRD 3.1 says:
    "Adding money to the escrow is the only action in the platform that raises `total_funded_cents`, a lifetime total that never decreases: a caller supplies `amount_cents`, a positive whole number of cents, and both `escrow_balance_cents` and `total_funded_cents` rise by that amount while the club's `version` advances by one."

    PRD 3.2 says:
    "A successful order is written in status `ORDERED` with all four money fields stamped, the club's `escrow_balance_cents` is debited by `charged_cents`, the club's `version` advances by one, and the member's screening dimension moves `UNSCREENED → SCREENING_ORDERED` (or `CLEARED → SCREENING_ORDERED`, or `EXPIRED → SCREENING_ORDERED`, all three governed by the identical preconditions and side effects)."

    PRD 3.8 says:
    "Hop one creates the measure in status `ACTIVE` with `permanence` of `TEMPORARY` and `imposed_by_user_id` set from the acting `X-User-ID`, leaving `converted_by_user_id`, `lifted_at`, `lift_reason`, and `rationale` null."

    Design: Corner/cross_cutting_complexity_layers/stale_club_version_and_stale_member_version_are_both_enforced
    """
    _epoch(api)
    club = _club(api)
    assert_version_is(club, 1)
    funded = validate_success(
        api.fund_escrow(club["id"], {"amount_cents": 100000}, NGB_ADMIN_HEADERS)
    )
    assert_version_is(funded, 2)
    assert_money_equals(funded, "escrow_balance_cents", 600000)
    member = _member(
        api,
        club["id"],
        "Ida Okonjo",
        "ida.okonjo@alpha.test",
        "1989-08-12",
        role_type="ASSISTANT_COACH",
        contact=True,
    )
    body = get_success_data(
        api.register_investigating_body(
            {
                "name": "Conduct Panel",
                "scope_categories": ["PHYSICAL_ABUSE"],
                "max_open_cases": 5,
                "intake_status": "ACCEPTING",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    case = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": member["id"],
                "allegation_category": "PHYSICAL_ABUSE",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "physical misconduct reported at practice by a duty coach",
                "occurred_at": "2026-07-31T23:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    validate_success(
        api.route_case(
            case["id"], {"investigating_body_id": body["id"]}, OFFICER_INTAKE_HEADERS
        )
    )
    admin = make_club_admin_headers(club["id"])

    validate_error(
        api.order_screening(member["id"], {"expected_club_version": 1}, admin),
        ApiErrorId.STALE_CLUB_VERSION,
        412,
    )
    order = get_success_data(
        api.order_screening(
            member["id"], {"expedited": False, "expected_club_version": 2}, admin
        ),
        201,
    )
    assert_state(order, "status", "ORDERED")
    assert_state(order, "tier", "TIER_2")
    assert_money_equals(order, "charged_cents", 4800)

    after_order = validate_success(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    assert_version_is(after_order, 2)
    assert_state(after_order, "screening_status", "SCREENING_ORDERED")
    window = {
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-09-01T00:00:00Z",
    }
    first_measure = get_success_data(
        api.impose_interim_measure(
            case["id"],
            {
                "member_id": member["id"],
                "measure_kind": "NO_CONTACT_DIRECTIVE",
                "expected_member_version": 2,
                **window,
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        201,
    )
    assert_state(first_measure, "status", "ACTIVE")

    validate_error(
        api.impose_interim_measure(
            case["id"],
            {
                "member_id": member["id"],
                "measure_kind": "TEMPORARY_SUSPENSION",
                "expected_member_version": 2,
                **window,
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        ApiErrorId.STALE_MEMBER_VERSION,
        412,
    )
    after_measure = validate_success(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    assert_version_is(after_measure, 3)
    second_measure = get_success_data(
        api.impose_interim_measure(
            case["id"],
            {
                "member_id": member["id"],
                "measure_kind": "TEMPORARY_SUSPENSION",
                "expected_member_version": 3,
                **window,
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        201,
    )
    assert_state(second_measure, "status", "ACTIVE")

    orders, orders_meta = validate_paginated(
        api.list_member_screening_orders(member["id"], NGB_ADMIN_HEADERS)
    )
    assert_pagination_meta(orders_meta, total=1)
    assert [row["id"] for row in orders] == [order["id"]], (
        "the rejected order was written after all"
    )
    measures, measures_meta = validate_paginated(
        api.list_interim_measures(NGB_ADMIN_HEADERS, member_id=member["id"])
    )
    assert_pagination_meta(measures_meta, total=2)
    assert {row["id"] for row in measures} == {
        first_measure["id"],
        second_measure["id"],
    }, "the rejected measure was written after all"
    final_club = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_money_equals(final_club, "escrow_balance_cents", 600000 - 4800)
    assert_money_equals(final_club, "total_funded_cents", 600000)


def test_the_first_critical_finding_freezes_the_club_and_waiving_it_hands_the_posture_back(
    api: ApiClient,
) -> None:
    """The freeze boundary sits at one critical finding, and it outranks the three-finding band.

    PRD 2.9 says:
    "The posture is recomputed by the platform, never set by a caller, and it is re-derived inside every operation that touches the club's findings, its sanction standing, or the eligibility of a member holding a placement there."
    "The posture is `FROZEN` when the club's `sanction_status` is either `SUSPENDED` or `TERMINATED`, or when its `critical_open_finding_count` reaches or exceeds one. A single open finding of `CRITICAL` severity anywhere in the club's audit history is therefore enough to freeze it."
    "Otherwise the posture is `RESTRICTED` when the club's `open_finding_count` reaches or exceeds three, or when its `restricted_member_count` reaches or is above one."
    "`open_finding_count` on the club counts every finding in status `OPEN` across every audit of that club, regardless of what status those audits themselves are in; `critical_open_finding_count` is the same count narrowed to findings whose `severity` is `CRITICAL`."

    PRD 3.1 says:
    "A freshly chartered club has `escrow_balance_cents` and `total_funded_cents` both equal to the seeded amount, `sanction_status` of `NONE`, and `compliance_posture` of `OPEN`, with `compliance_score` null and all four of its finding and placement counters at zero."

    PRD 3.9 says:
    "The finding is created in status `OPEN` with `fine_cents`, `evidence_note`, and `decision_note` null; the audit's `finding_total_count` and `open_finding_count` both rise by one, preserving the finding partition identity; and the club's `open_finding_count`, `critical_open_finding_count`, and `compliance_posture` are re-derived, which is how a single `CRITICAL` finding freezes a club the moment it is written."
    "A `ComplianceAuditor` may instead submit `WAIVED` against a finding in status `OPEN`: the finding moves `OPEN → WAIVED`, the `note` is retained as `decision_note`, `open_finding_count` falls by one while `waived_finding_count` rises by one, the finding is thereafter excluded from any fine, and the club's counters and posture are re-derived."

    Design: Corner/cross_cutting_complexity_layers/critical_finding_freeze_threshold_at_one_and_its_reset
    """
    _epoch(api)
    club = _club(api)
    assert_state(club, "compliance_posture", "OPEN")
    member = _member(api, club["id"], "Ray Tull", "ray.tull@alpha.test", "1991-09-13")
    audit = _audit(api, club["id"], [member["id"]])

    for code in ("RECORDS_INCOMPLETE", "TRAINING_LAPSED"):
        get_success_data(
            api.write_finding(
                audit["id"],
                {"finding_code": code, "severity": "MINOR", "is_repeat": False},
                COMPLIANCE_AUDITOR_HEADERS,
            ),
            201,
        )
    two_minor = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_counters(two_minor, open_finding_count=2, critical_open_finding_count=0)
    assert_state(two_minor, "compliance_posture", "OPEN")

    critical = get_success_data(
        api.write_finding(
            audit["id"],
            {
                "finding_code": "UNSCREENED_CONTACT",
                "severity": "CRITICAL",
                "member_id": member["id"],
                "is_repeat": False,
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )
    assert_state(critical, "status", "OPEN")
    frozen = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_counters(frozen, open_finding_count=3, critical_open_finding_count=1)
    assert_state(frozen, "compliance_posture", "FROZEN")

    finalized = validate_success(
        api.finalize_club_audit(audit["id"], {}, COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_state(finalized, "status", "FINDINGS_ISSUED")
    assert_counters(finalized, finding_total_count=3)

    waived = validate_success(
        api.decide_finding(
            critical["id"],
            {
                "decision": "WAIVED",
                "note": "critical finding waived on documented evidence",
            },
            COMPLIANCE_AUDITOR_HEADERS,
        )
    )
    assert_state(waived, "status", "WAIVED")
    reopened = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_counters(reopened, open_finding_count=2, critical_open_finding_count=0)
    assert_state(reopened, "compliance_posture", "OPEN")
    audit_after = validate_success(
        api.get_club_audit(audit["id"], COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_counters(
        audit_after,
        open_finding_count=2,
        waived_finding_count=1,
        finding_total_count=3,
    )


def test_every_derived_field_is_already_correct_on_the_first_read_after_its_write(
    api: ApiClient,
) -> None:
    """A finding write, a posture and a score are each read back once immediately, and once more.

    PRD 2.10 says:
    "When they do, every affected row's `updated_at` is refreshed and its `version` increases by one, exactly as if the row had been written directly, and every derived counter that depends on the changed rows is recomputed inside the same request — this platform has no deferred or eventually consistent recomputation."
    "A caller who reads a club immediately after disqualifying one of its coaches sees the club's counters and posture already reduced."

    PRD 3.9 says:
    "The audit is created in status `SAMPLED`, with `sampled_member_count` set to the number of entries supplied, `compliant_member_count`, `denominator_count`, `compliance_score`, and `sanction_fine_cents` all null, all four finding counters at zero, and `finalized_at`, `closed_at`, and `resolution` null."
    "The finding is created in status `OPEN` with `fine_cents`, `evidence_note`, and `decision_note` null; the audit's `finding_total_count` and `open_finding_count` both rise by one, preserving the finding partition identity; and the club's `open_finding_count`, `critical_open_finding_count`, and `compliance_posture` are re-derived, which is how a single `CRITICAL` finding freezes a club the moment it is written."
    "Under `SELF_ATTESTED` it is the club's `roster_size_attested`, the figure the club itself supplied at charter time, so an inflated attestation drives the score down for exactly the same sample."
    "Otherwise, when `denominator_count` is zero the score is exactly 0.00."
    "Finalize copies the resulting score onto the club's own `compliance_score` field and re-derives the club's `open_finding_count`, `critical_open_finding_count`, and `compliance_posture`."

    Design: Corner/consistency_model/derived_fields_and_cascades_are_visible_immediately
    """
    _epoch(api)
    club = _club(api)
    member = _member(
        api, club["id"], "Ines Marek", "ines.marek@alpha.test", "1990-10-14"
    )
    audit = _audit(api, club["id"], [member["id"]])
    assert_counters(audit, sampled_member_count=1, open_finding_count=0)
    assert audit["compliance_score"] is None, (
        f"a freshly opened audit carries no score, got {audit['compliance_score']!r}"
    )

    finding = get_success_data(
        api.write_finding(
            audit["id"],
            {
                "finding_code": "UNSCREENED_CONTACT",
                "severity": "CRITICAL",
                "member_id": member["id"],
                "is_repeat": False,
            },
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )
    assert_state(finding, "status", "OPEN")
    club_read_1 = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_counters(club_read_1, critical_open_finding_count=1)
    assert_state(club_read_1, "compliance_posture", "FROZEN")
    audit_read_1 = validate_success(
        api.get_club_audit(audit["id"], COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_counters(audit_read_1, open_finding_count=1, finding_total_count=1)

    finalized = validate_success(
        api.finalize_club_audit(audit["id"], {}, COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_counters(finalized, denominator_count=3, compliant_member_count=0)
    assert_score_equals(finalized["compliance_score"], "0.00")

    club_read_2 = validate_success(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    assert_score_equals(club_read_2["compliance_score"], "0.00")
    assert_state(club_read_2, "compliance_posture", "FROZEN")
    audit_read_2 = validate_success(
        api.get_club_audit(audit["id"], COMPLIANCE_AUDITOR_HEADERS)
    )
    assert_state(audit_read_2, "status", "FINDINGS_ISSUED")
    assert_score_equals(audit_read_2["compliance_score"], "0.00")
    audit_read_3 = validate_success(
        api.get_club_audit(audit["id"], COMPLIANCE_AUDITOR_HEADERS)
    )
    assert audit_read_3["compliance_score"] == audit_read_2["compliance_score"], (
        "the same read repeated returned a different score: "
        f"{audit_read_2['compliance_score']!r} then {audit_read_3['compliance_score']!r}"
    )
    assert audit_read_3["version"] == audit_read_2["version"], (
        "a read advanced the audit's version"
    )
