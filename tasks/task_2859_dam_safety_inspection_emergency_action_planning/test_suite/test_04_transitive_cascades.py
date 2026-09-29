"""Four-link cascades: certification reclassification, and enforcement default."""

import pytest

from test_helpers import (
    assert_cents,
    assert_instant,
    assert_score,
)
from test_helpers import factories as f
from test_helpers.constants import (
    ASSESSMENT_CERTIFIED,
    ASSESSMENT_SUPERSEDED,
    CATEGORY_EAP_MISSING,
    CATEGORY_STRUCTURAL,
    DEFICIENCY_ESCALATED,
    DEFICIENCY_OPEN,
    DELINQUENCY_DELINQUENT,
    EAP_APPROVED,
    EAP_REVISION_REQUIRED,
    ENTRY_CIVIL_PENALTY,
    HAZARD_HIGH,
    ORDER_DEFAULTED,
    ORDER_TYPE_EMERGENCY,
    REG_REGISTERED,
    REG_UNDER_ENFORCEMENT,
    SAFETY_UNRATED,
    SAFETY_UNSATISFACTORY,
    SEVERITY_CRITICAL,
    SEVERITY_SERIOUS,
    SOURCE_SYSTEM_EAP,
    SYSTEM_ACTOR_ID,
)


# ---------------------------------------------------------------------------
# Certification cascade: supersede -> reclassify -> revise plan -> open defect
# ---------------------------------------------------------------------------
@pytest.fixture()
def classified_dam_with_approved_plan(program, base):
    """A SIGNIFICANT dam with an APPROVED plan built on the 2019 inundation map."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    plan = program.approved_plan(
        base.dam_id,
        base.owner_id,
        base.engineer_a_id,
        version_label="EAP-2019-rev0",
        inundation_map_ref="IM-2019-A",
        notification_flowchart_ref="FC-2019-A",
        notification_contact_count=4,
        drawdown_procedure_ref="DD-2019-A",
    )
    return plan


def test_the_new_certification_supersedes_the_incumbent_assessment(
    program, base, classified_dam_with_approved_plan
):
    """Certifying a second assessment retires the first one as the record of truth.

    PRD 3.2: "Because this row has become the dam's certification of record, the dam's previously certified assessment — there is at most one — moves `CERTIFIED → SUPERSEDED` with `superseded_at` stamped at the clock, and stops contributing to the dam's classification from that instant."

    Design: Difficulty/transitive_cascade/certification_supersedes_reclassifies_revises_plan_and_opens_deficiency
    """
    incumbent = program.assessments_for(base.dam_id)[0]
    assert incumbent["status"] == ASSESSMENT_CERTIFIED
    assert incumbent["superseded_at"] is None

    second = program.create_assessment(f.assessment_a2(base.dam_id), base.engineer_a_id)
    program.certify_assessment(second["id"], base.engineer_a_id)

    rows = {row["id"]: row for row in program.assessments_for(base.dam_id)}
    retired = rows[incumbent["id"]]
    assert retired["status"] == ASSESSMENT_SUPERSEDED
    assert_instant(retired["superseded_at"], "2026-08-01T00:00:00Z", "superseded_at")
    assert rows[second["id"]]["status"] == ASSESSMENT_CERTIFIED


def test_the_reclassification_halves_the_interval_and_makes_the_dam_overdue(
    program, base, classified_dam_with_approved_plan
):
    """Moving SIGNIFICANT to HIGH shortens the interval against the same baseline.

    PRD 3.2: "A reclassification from `SIGNIFICANT` to `HIGH` halves the interval from 24 to 12 months against the same baseline visit, so a dam inspected 18 months ago and comfortably current a moment earlier can become overdue the instant it is certified `HIGH`."

    Design: Difficulty/transitive_cascade/certification_supersedes_reclassifies_revises_plan_and_opens_deficiency
    """
    second = program.create_assessment(f.assessment_a2(base.dam_id), base.engineer_a_id)
    program.certify_assessment(second["id"], base.engineer_a_id)

    dam = program.get_dam(base.dam_id)
    assert dam["hazard_class"] == HAZARD_HIGH
    assert_score(dam["current_consequence_score"], 45.00, "current_consequence_score")
    assert dam["eap_required"] is True
    # No accepted periodic inspection, so registered_at 2019-04-15 plus 12 months.
    assert_instant(
        dam["next_inspection_due_at"], "2020-04-15T00:00:00Z", "next_inspection_due_at"
    )
    assert dam["inspection_overdue"] is True
    # Neither dimension of the dam's own state machine moved.
    assert dam["regulatory_status"] == REG_REGISTERED
    assert dam["safety_status"] == SAFETY_UNRATED


def test_the_approved_plan_is_pushed_back_to_revision_required(
    program, base, classified_dam_with_approved_plan
):
    """A stale map reference costs the plan its approval and its expiry date.

    PRD 3.2: "Because link 2 changed the classification, any emergency action plan on this dam whose status is `APPROVED` and whose `inundation_map_ref` differs from this assessment's `inundation_map_ref` moves `APPROVED → REVISION_REQUIRED`, has its `expires_at` cleared to null, and the dam's `latest_eap_status` is refreshed accordingly."

    Design: Difficulty/transitive_cascade/certification_supersedes_reclassifies_revises_plan_and_opens_deficiency
    """
    plan = classified_dam_with_approved_plan
    assert plan["status"] == EAP_APPROVED
    # SIGNIFICANT validity is 60 calendar months from the approval instant.
    assert_instant(plan["expires_at"], "2031-08-01T00:00:00Z", "expires_at")

    second = program.create_assessment(f.assessment_a2(base.dam_id), base.engineer_a_id)
    program.certify_assessment(second["id"], base.engineer_a_id)

    revised = program.get_plan(plan["id"])
    assert revised["status"] == EAP_REVISION_REQUIRED
    assert revised["expires_at"] is None
    assert program.get_dam(base.dam_id)["latest_eap_status"] == EAP_REVISION_REQUIRED

    summary = program.summary(base.dam_id)
    assert summary["latest_eap_status"] == EAP_REVISION_REQUIRED
    assert summary["eap_expires_at"] is None
    assert summary["eap_exercise_current"] is False


def test_losing_the_approved_plan_opens_exactly_one_system_deficiency(
    program, base, classified_dam_with_approved_plan
):
    """The fourth link opens an unsourced EAP_MISSING defect on the dam.

    PRD 3.2: "Because link 3 has left a dam that requires a plan without an approved one, a deficiency is opened automatically: `source` of `SYSTEM_EAP`, `category` of `EAP_MISSING`, `severity` of `SERIOUS`, `status` of `OPEN`, and no inspection reference."

    Design: Difficulty/transitive_cascade/certification_supersedes_reclassifies_revises_plan_and_opens_deficiency
    """
    assert program.deficiencies_for(base.dam_id) == []

    second = program.create_assessment(f.assessment_a2(base.dam_id), base.engineer_a_id)
    program.certify_assessment(second["id"], base.engineer_a_id)

    deficiencies = program.deficiencies_for(base.dam_id)
    assert len(deficiencies) == 1
    opened = deficiencies[0]
    assert opened["source"] == SOURCE_SYSTEM_EAP
    assert opened["category"] == CATEGORY_EAP_MISSING
    assert opened["severity"] == SEVERITY_SERIOUS
    assert opened["status"] == DEFICIENCY_OPEN
    assert opened["inspection_id"] is None
    assert opened["dam_id"] == base.dam_id

    assert program.get_dam(base.dam_id)["open_deficiency_count"] == 1
    assert program.summary(base.dam_id)["open_deficiency_count"] == 1


# ---------------------------------------------------------------------------
# Enforcement cascade: default -> penalty ledger -> delinquency -> enforcement
# ---------------------------------------------------------------------------
@pytest.fixture()
def overdue_emergency_order(program, base):
    """A HIGH-hazard EMERGENCY_ORDER eight days past its five-day deadline."""
    program.classify_high(base.dam_id, base.engineer_a_id)
    inspection = program.schedule_inspection(
        base.dam_id,
        base.engineer_a_id,
        window_start="2026-08-05T08:00:00Z",
        window_end="2026-08-05T12:00:00Z",
    )
    program.set_clock("2026-08-05T13:00:00Z")
    program.submit_inspection(
        inspection["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T09:30:00Z",
        condition_rating=SAFETY_UNSATISFACTORY,
        narrative="Active sinkhole over the conduit; immediate action required.",
        deficiencies=[
            f.deficiency_item(
                category=CATEGORY_STRUCTURAL,
                severity=SEVERITY_CRITICAL,
                description="Sinkhole 3 ft across above the outlet conduit at station 0+90.",
            )
        ],
    )
    program.accept_inspection(inspection["id"], base.engineer_b_headers)
    deficiency = program.deficiencies_for(base.dam_id, severity=SEVERITY_CRITICAL)[0]
    order = program.issue_order(
        deficiency["id"],
        order_type=ORDER_TYPE_EMERGENCY,
        requested_response_days=30,
    )
    program.set_clock("2026-08-18T13:00:00Z")
    return {"order": order, "deficiency": deficiency}


def test_the_sweep_defaults_the_order_and_escalates_its_deficiency(
    program, base, overdue_emergency_order
):
    """The first link stamps the default, prices it, and moves the defect in one step.

    PRD 3.9: "**Link 1** stamps `defaulted_at` with the clock, computes `assessed_penalty_cents` from the final-assessment variant of §3.4 — the tiered daily accrual, capped at 5,000,000 cents, then reduced by the 25 percent good-faith abatement if `response_filed_at` is non-null — and moves the governing deficiency `ORDERED → ESCALATED` in the same step."

    Design: Difficulty/transitive_cascade/sweep_default_assesses_penalty_then_delinquency_then_enforcement
    """
    issued = program.get_order(overdue_emergency_order["order"]["id"])
    # CRITICAL base 45 days x 0.5 for HIGH is 22, but the EMERGENCY_ORDER floor of
    # five days applies, so the deadline sits at 2026-08-10T13:00:00Z.
    assert issued["effective_response_days"] == 5
    assert_instant(
        issued["compliance_deadline_at"],
        "2026-08-10T13:00:00Z",
        "compliance_deadline_at",
    )
    assert_cents(issued["daily_penalty_rate_cents"], 40000, "daily_penalty_rate_cents")

    program.sweep()

    order = program.get_order(overdue_emergency_order["order"]["id"])
    assert order["status"] == ORDER_DEFAULTED
    assert_instant(order["defaulted_at"], "2026-08-18T13:00:00Z", "defaulted_at")
    # No response was ever filed, so no abatement: seven days at 40000 plus one
    # day at the 1.15 tier of 46000.
    assert_cents(order["assessed_penalty_cents"], 326000, "assessed_penalty_cents")
    assert order["response_filed_at"] is None

    deficiencies = program.deficiencies_for(base.dam_id)
    assert [d["status"] for d in deficiencies] == [DEFICIENCY_ESCALATED]


def test_the_penalty_is_posted_to_the_ledger_by_the_system_actor(
    program, base, overdue_emergency_order
):
    """The second link appends one system-posted CIVIL_PENALTY naming the order.

    PRD 3.9: "**Link 2** fires because link 1 assessed a penalty: a ledger entry with `entry_type` of `CIVIL_PENALTY`, an `amount_cents` equal to the assessed penalty, a `source_ref` naming the defaulted order and `posted_by_user_id` of `SYSTEM` is appended to the owner's ledger, and the owner's `fee_balance_cents` and the affected `balance_after_cents` figures are recomputed."

    Design: Difficulty/transitive_cascade/sweep_default_assesses_penalty_then_delinquency_then_enforcement
    """
    order_id = overdue_emergency_order["order"]["id"]
    program.sweep()

    rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 1
    entry = rows[0]
    assert entry["entry_type"] == ENTRY_CIVIL_PENALTY
    assert_cents(entry["amount_cents"], 326000, "amount_cents")
    assert entry["sequence_no"] == 1
    assert_cents(entry["balance_after_cents"], 326000, "balance_after_cents")
    assert entry["source_ref"] == order_id
    assert entry["posted_by_user_id"] == SYSTEM_ACTOR_ID

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 326000, "fee_balance_cents")


def test_the_flipped_delinquency_drives_the_dam_under_enforcement(
    program, base, overdue_emergency_order
):
    """Links three and four turn a fiscal fact into a regulatory posture.

    PRD 3.9: "**Link 4** fires because link 3 made the owner delinquent: the dam moves `REGISTERED → UNDER_ENFORCEMENT` on the regulatory dimension and its `version` increments by 1."

    Design: Difficulty/transitive_cascade/sweep_default_assesses_penalty_then_delinquency_then_enforcement
    """
    before = program.get_dam(base.dam_id)
    assert before["regulatory_status"] == REG_REGISTERED

    result = program.sweep()
    assert result["defaulted_order_count"] == 1
    assert result["defaulted_order_ids"] == [overdue_emergency_order["order"]["id"]]
    assert result["escalated_deficiency_count"] == 1
    assert_cents(result["penalty_cents_assessed"], 326000, "penalty_cents_assessed")
    assert result["newly_delinquent_owner_count"] == 1
    assert result["dams_moved_under_enforcement"] == 1
    assert result["referred_order_count"] == 0
    assert result["expired_eap_count"] == 0

    owner = program.get_owner(base.owner_id)
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT

    dam = program.get_dam(base.dam_id)
    assert dam["regulatory_status"] == REG_UNDER_ENFORCEMENT
    # The enforcement move never rewrites the condition rating.
    assert dam["safety_status"] == SAFETY_UNSATISFACTORY


def test_an_already_delinquent_owner_does_not_drive_a_second_transition(
    program, base, overdue_emergency_order
):
    """Replaying the sweep leaves the ledger and the regulatory posture untouched.

    PRD 3.9: "Link 4 is conditional on link 3 having actually flipped the owner from `CURRENT` to `DELINQUENT` — an owner who was already delinquent does not drive a second dam transition, and a penalty too small to cross the threshold drives none at all."

    Design: Difficulty/transitive_cascade/sweep_default_assesses_penalty_then_delinquency_then_enforcement
    """
    program.sweep()

    replay = program.sweep()
    assert replay["defaulted_order_count"] == 0
    assert replay["defaulted_order_ids"] == []
    assert replay["escalated_deficiency_count"] == 0
    assert_cents(replay["penalty_cents_assessed"], 0, "penalty_cents_assessed")
    assert replay["newly_delinquent_owner_count"] == 0
    assert replay["dams_moved_under_enforcement"] == 0

    rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == ENTRY_CIVIL_PENALTY

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 326000, "fee_balance_cents")
    assert program.get_dam(base.dam_id)["regulatory_status"] == REG_UNDER_ENFORCEMENT
