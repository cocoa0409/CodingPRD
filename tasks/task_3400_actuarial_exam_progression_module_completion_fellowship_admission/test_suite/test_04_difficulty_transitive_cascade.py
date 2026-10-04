"""Difficulty queue — transitive cascade chains.

Discipline-sanction cascade depth 4 (PRD §3.9) and the syllabus-activation
retirement cascade depth 4 (PRD §3.2).
"""
from datetime import datetime

from test_helpers import (
    CLOCK_REGISTRATION_OPEN,
    CLOCK_SUSPENSION_DAY,
    FEE_EARLY_CENTS,
    REGISTRAR,
    SEVERITY_HIGH,
    STANDARD_SYLLABUS_CODE,
    SECOND_SYLLABUS_CODE,
    SUSPENSION_DAYS,
    WINDOW_CAPACITY_TIGHT,
    activate_syllabus,
    file_case,
    get_candidate,
    get_success_data,
    get_window,
    make_candidate,
    make_exam,
    make_syllabus,
    make_window,
    register,
    sanction_case,
    set_clock,
    setup_registered,
)


def _utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _suspension_scenario(api):
    """Capacity-1 window: candA REGISTERED (early fee), candB WAITLISTED; a
    FILED case against candA; clock advanced to the sanction day."""
    ctx = setup_registered(api, num_candidates=2, capacity=WINDOW_CAPACITY_TIGHT)
    cand_a, cand_b = ctx["candidates"]
    reg_a, reg_b = ctx["registrations"]
    case = file_case(api, cand_a["id"], charge="Misconduct in exam administration",
                     severity=SEVERITY_HIGH)
    set_clock(api, CLOCK_SUSPENSION_DAY)
    return {"window": ctx["window"], "cand_a": cand_a, "cand_b": cand_b,
            "reg_a": reg_a, "reg_b": reg_b, "case": case}


def test_suspension_sanction_sets_candidate_suspended_until(api):
    """PRD §3.9: "a suspension's `suspended_until` — computed as the resolution
    moment plus `suspension_days` days — is likewise recorded and copied onto
    the candidate."

    Design: Difficulty/transitive_cascade/suspension_cascade_promotes_waitlisted_candidate
    """
    sc = _suspension_scenario(api)
    resolved = sanction_case(api, sc["case"]["id"], resolution="SUSPENSION",
                             suspension_days=SUSPENSION_DAYS)
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "SUSPENSION"
    assert _utc(resolved["suspended_until"]) == _utc("2026-10-05T00:00:00Z")

    candidate = get_candidate(api, sc["cand_a"]["id"])
    assert candidate["status"] == "SUSPENDED"
    assert _utc(candidate["suspended_until"]) == _utc("2026-10-05T00:00:00Z")


def test_suspension_cascade_cancels_refunds_and_promotes(api):
    """PRD §3.9: "Every registration of the candidate whose `logistics_status`
    is `REGISTERED` or `WAITLISTED` is cancelled with `cancel_reason` of
    `DISCIPLINE_SUSPENSION`."
    PRD §3.9: "Each such cancellation refunds in full regardless of timing — a
    formerly `REGISTERED` row's `refund_cents` is set to its `fee_charged_cents`."
    PRD §3.9: "And each freed seat on a window still `REGISTRATION_OPEN`
    triggers the waitlist promotion of §3.3, with the promoted row's fee
    computed at promotion time."

    Design: Difficulty/transitive_cascade/suspension_cascade_promotes_waitlisted_candidate
    """
    sc = _suspension_scenario(api)
    assert sc["reg_b"]["logistics_status"] == "WAITLISTED"
    sanction_case(api, sc["case"]["id"], resolution="SUSPENSION",
                  suspension_days=SUSPENSION_DAYS)

    rows = get_success_data(api.list_window_registrations(sc["window"]["id"], REGISTRAR))
    row_a = [r for r in rows if r["id"] == sc["reg_a"]["id"]][0]
    row_b = [r for r in rows if r["id"] == sc["reg_b"]["id"]][0]
    assert row_a["logistics_status"] == "CANCELLED"
    assert row_a["cancel_reason"] == "DISCIPLINE_SUSPENSION"
    assert row_a["refund_cents"] == FEE_EARLY_CENTS
    # The freed seat promotes the waitlisted row; fee at promotion time is the
    # early tier (2026-09-05 is more than 14 days before the deadline).
    assert row_b["logistics_status"] == "REGISTERED"
    assert row_b["fee_charged_cents"] == FEE_EARLY_CENTS

    window = get_window(api, sc["window"]["id"])
    assert window["seats_held"] == 1
    assert window["waitlist_count"] == 0


def _syllabus_cascade_scenario(api):
    """ACTIVE 2026-A syllabus with exam P; an open window with one REGISTERED
    registration; a DRAFT 2026-B version carrying credit_map {P: P2} and P2."""
    syl1 = make_syllabus(api, version_code=STANDARD_SYLLABUS_CODE)
    exam_p = make_exam(api, syl1["id"], exam_code="P", title="Probability")
    activate_syllabus(api, syl1["id"])
    window = make_window(api, exam_p["id"], window_code="P-2026-10")
    candidate = make_candidate(api)
    set_clock(api, CLOCK_REGISTRATION_OPEN)
    registration = register(api, window["id"], candidate)
    syl2 = make_syllabus(api, version_code=SECOND_SYLLABUS_CODE, credit_map={"P": "P2"})
    exam_p2 = make_exam(api, syl2["id"], exam_code="P2", title="Probability (2026 syllabus)")
    return {"syl1": syl1, "syl2": syl2, "exam_p": exam_p, "exam_p2": exam_p2,
            "window": window, "candidate": candidate, "registration": registration}


def test_syllabus_activation_retires_prior_version_and_exams(api):
    """PRD §3.2: "On success the activation stamps `activated_at` with the
    current logical-clock reading and then cascades through four links. First,
    the previously `ACTIVE` version, if any, transitions `ACTIVE` → `RETIRED`.
    Second, every exam of the retired version transitions `ACTIVE` → `RETIRED`,
    and every exam of the newly activated version transitions `DRAFT` →
    `ACTIVE`."

    Design: Difficulty/transitive_cascade/syllabus_activation_retires_windows_and_refunds
    """
    sc = _syllabus_cascade_scenario(api)
    activated = activate_syllabus(api, sc["syl2"]["id"])
    assert activated["status"] == "ACTIVE"
    assert _utc(activated["activated_at"]) == _utc(CLOCK_REGISTRATION_OPEN)

    old = get_success_data(api.get_syllabus_version(sc["syl1"]["id"], REGISTRAR))
    assert old["status"] == "RETIRED"
    exam_p = get_success_data(api.get_exam(sc["exam_p"]["id"], REGISTRAR))
    exam_p2 = get_success_data(api.get_exam(sc["exam_p2"]["id"], REGISTRAR))
    assert exam_p["status"] == "RETIRED"
    assert exam_p2["status"] == "ACTIVE"


def test_syllabus_activation_cancels_window_with_full_refund(api):
    """PRD §3.2: "Third, every exam window of a retired exam whose status is
    `SCHEDULED`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED` transitions to
    `CANCELLED`. Fourth, every registration on a cancelled window whose
    `logistics_status` is `REGISTERED` or `WAITLISTED` transitions to
    `CANCELLED` with `cancel_reason` of `SYLLABUS_RETIREMENT` and a full refund
    — `refund_cents` is set to the `fee_charged_cents` that was charged."

    Design: Difficulty/transitive_cascade/syllabus_activation_retires_windows_and_refunds
    """
    sc = _syllabus_cascade_scenario(api)
    assert sc["registration"]["fee_charged_cents"] == FEE_EARLY_CENTS
    activate_syllabus(api, sc["syl2"]["id"])

    window = get_window(api, sc["window"]["id"])
    assert window["status"] == "CANCELLED"
    rows = get_success_data(api.list_candidate_registrations(sc["candidate"]["id"], REGISTRAR))
    assert rows[0]["logistics_status"] == "CANCELLED"
    assert rows[0]["cancel_reason"] == "SYLLABUS_RETIREMENT"
    assert rows[0]["refund_cents"] == FEE_EARLY_CENTS
