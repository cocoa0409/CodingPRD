"""The sustained-disposition cascade and its reversal on appeal."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    assert_discipline_days,
    assert_instant,
    assert_officer_ledgers,
    assert_officer_risk,
    assert_two_dp,
)
from test_helpers import factories, fixtures


TWO_FORCE_EVENTS = (
    ("USE_OF_FORCE", "LEVEL_3", "2026-07-01T00:00:00Z", "V-1"),
    ("USE_OF_FORCE", "LEVEL_2", "2026-07-05T00:00:00Z", "V-2"),
)


def untruthfulness_case_at_findings(api, world):
    """A Class I untruthfulness file carried to findings against a scored officer."""
    fixtures.ingest_event_pattern(api, world["subj_id"], TWO_FORCE_EVENTS)
    complaint = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Officer gave a false account in a report.",
        reported_allegation_types=["UNTRUTHFULNESS"],
    )
    allegation = fixtures.attach_allegation(
        api,
        world,
        complaint["id"],
        allegation_type="UNTRUTHFULNESS",
        offense_class="A",
        narrative="Report contradicted body-camera footage.",
    )
    investigation = fixtures.open_investigation(api, world, complaint["id"])
    fixtures.assign_investigation(
        api, world, investigation["id"], investigation["version"], world["inv_a_id"]
    )
    session = fixtures.schedule_session(
        api,
        world,
        investigation["id"],
        scheduled_start="2026-08-05T09:00:00Z",
        scheduled_end="2026-08-05T10:30:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        representation_status="REP_PRESENT",
    )
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    fixtures.hold_session(api, world, session["id"])
    fixtures.submit_findings(
        api,
        world,
        investigation["id"],
        [factories.finding_entry(allegation["id"], 60, 40, policy_compliant=False)],
    )
    return {
        "c_id": complaint["id"],
        "complaint": complaint,
        "a1_id": allegation["id"],
        "i1_id": investigation["id"],
    }


def test_a_sustained_untruthfulness_finding_fires_all_five_cascades(api, world):
    """One disposition writes a discipline, an event, a rescore, an alert and a disclosure.

    PRD: Acceptance raises the complaint's `sustained_allegation_count` by 1 and fires five cascades.
    PRD: Fourth, when that recomputation puts `eis_alert_level` above `NONE`, an `EarlyInterventionAlert` is created with `trigger_source` `DISPOSITION_CASCADE` and the officer's `open_alert_count` rises by 1.
    PRD: Fifth, when the allegation's `allegation_type` is `UNTRUTHFULNESS`, a `CredibilityDisclosure` is created in `ACTIVE` with `permanent_retention` true and the officer's `credibility_disclosure_active` is set to true.
    Design: Difficulty/transitive_cascade/untruthfulness_sustained_fires_five_link_cascade
    """
    case = untruthfulness_case_at_findings(api, world)
    assert case["complaint"]["classification"] == "CLASS_I"
    before = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_risk(before, eis_score=28.75, eis_alert_level="NONE")
    assert_officer_ledgers(before, credibility_disclosure_active=False, open_alert_count=0)

    disposed = fixtures.dispose_allegation(api, world, case["a1_id"], "SUSTAINED")

    assert disposed["disposition"] == "SUSTAINED"
    assert_instant(disposed["disposed_at"], "2026-08-05T09:00:00Z")
    assert disposed["prior_sustained_count_at_disposition"] == 0

    discipline = fixtures.discipline_for_allegation(api, world, case["a1_id"])
    assert discipline["status"] == "PROPOSED"
    assert_discipline_days(discipline, presumptive_prior_tier=0, presumptive_days=30)

    complaint = fixtures.read_complaint(api, case["c_id"], world["cmdr_headers"])
    assert complaint["sustained_allegation_count"] == 1

    officer = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_risk(officer, eis_score=38.75, eis_alert_level="WATCH")
    assert_officer_ledgers(officer, open_alert_count=1, credibility_disclosure_active=True)

    alert = fixtures.alert_for_officer(api, world, world["subj_id"])
    assert alert["trigger_source"] == "DISPOSITION_CASCADE"
    assert_two_dp(alert["composite_score"], 38.75, label="composite_score")
    assert alert["alert_level"] == "WATCH"
    assert alert["status"] == "OPEN"
    assert_instant(alert["review_due_at"], "2026-09-04T09:00:00Z")

    disclosures, _ = fixtures.rows(
        api.list_credibility_disclosures(world["custodian_headers"], {"officer_id": world["subj_id"]})
    )
    assert len(disclosures) == 1
    assert disclosures[0]["basis"] == "UNTRUTHFULNESS_SUSTAINED"
    assert disclosures[0]["status"] == "ACTIVE"
    assert disclosures[0]["permanent_retention"] is True
    assert disclosures[0]["source_allegation_id"] == case["a1_id"]

    assert fixtures.read_investigation(api, case["i1_id"], world["cmdr_headers"])["status"] == "PENDING_REVIEW"
    events, _ = fixtures.rows(api.list_activity_events(world["subj_id"], world["cmdr_headers"]))
    assert len(events) == 4
    assert events[-1]["event_type"] == "COMPLAINT_SUSTAINED"
    assert_instant(events[-1]["occurred_at"], "2026-08-05T09:00:00Z")
    assert events[-1]["system_generated"] is True


def test_a_not_sustained_finding_on_the_same_file_fires_none_of_them(api, world):
    """The alternative branch stamps the instant and leaves every other row alone.

    PRD: Acceptance stamps `disposed_at` and nothing else: no discipline row, no activity event, no early-intervention alert and no credibility disclosure are created.
    Design: Difficulty/transitive_cascade/untruthfulness_sustained_fires_five_link_cascade
    """
    case = untruthfulness_case_at_findings(api, world)

    disposed = fixtures.dispose_allegation(api, world, case["a1_id"], "NOT_SUSTAINED")

    assert disposed["disposition"] == "NOT_SUSTAINED"
    assert_instant(disposed["disposed_at"], "2026-08-05T09:00:00Z")

    disciplines, _ = fixtures.rows(
        api.list_disciplines(world["cmdr_headers"], {"allegation_id": case["a1_id"]})
    )
    assert disciplines == []
    events, _ = fixtures.rows(api.list_activity_events(world["subj_id"], world["cmdr_headers"]))
    assert len(events) == 3
    assert [row["event_type"] for row in events] == [
        "USE_OF_FORCE",
        "USE_OF_FORCE",
        "COMPLAINT_INTAKE",
    ]
    alerts, _ = fixtures.rows(
        api.list_eis_alerts(world["cmdr_headers"], {"officer_id": world["subj_id"]})
    )
    assert alerts == []
    disclosures, _ = fixtures.rows(
        api.list_credibility_disclosures(world["custodian_headers"], {"officer_id": world["subj_id"]})
    )
    assert disclosures == []

    complaint = fixtures.read_complaint(api, case["c_id"], world["cmdr_headers"])
    assert complaint["sustained_allegation_count"] == 0
    officer = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_risk(officer, eis_score=28.75, eis_alert_level="NONE")
    assert_officer_ledgers(officer, open_alert_count=0, credibility_disclosure_active=False)


def case_with_heard_appeal(api, world):
    """The five-link cascade fired, the discipline imposed and the appeal heard."""
    case = untruthfulness_case_at_findings(api, world)
    fixtures.dispose_allegation(api, world, case["a1_id"], "SUSTAINED")
    discipline = fixtures.discipline_for_allegation(api, world, case["a1_id"])
    disclosures, _ = fixtures.rows(
        api.list_credibility_disclosures(world["custodian_headers"], {"officer_id": world["subj_id"]})
    )

    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    imposed = get_success_data(
        api.impose_discipline(
            discipline["id"],
            factories.imposition_payload(effective_date="2026-08-20T00:00:00Z"),
            world["cmdr_headers"],
        )
    )
    fixtures.set_clock(api, "2026-08-25T00:00:00Z")
    appeal = get_success_data(
        api.file_appeal(
            discipline["id"],
            factories.appeal_payload(
                "ARBITRATION", grounds="The finding rests on a misreading of the footage."
            ),
            world["rep_headers"],
        )
    )
    fixtures.hear_appeal(api, world, appeal["id"])
    case.update(
        {
            "d1_id": discipline["id"],
            "imposed": imposed,
            "disc_id": disclosures[0]["id"],
            "ap1_id": appeal["id"],
            "appeal": appeal,
        }
    )
    return case


def test_an_overturned_appeal_walks_the_cascade_backwards(api, world):
    """The allegation, the disclosure and the officer's status all reverse together.

    PRD: Third, because the discipline was overturned, the source allegation moves `SUSTAINED → OVERTURNED_ON_APPEAL`, the owning complaint's `sustained_allegation_count` falls by 1, and any `CredibilityDisclosure` whose `source_allegation_id` is that allegation moves `ACTIVE → EXPUNGED`, after which the officer's `credibility_disclosure_active` is recomputed over the disclosures that remain `ACTIVE`.
    Design: Difficulty/transitive_cascade/appeal_overturned_reverses_the_whole_cascade
    """
    case = case_with_heard_appeal(api, world)
    assert_discipline_days(case["imposed"], final_days=30, effective_days=30)
    before = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert before["employment_status"] == "SUSPENDED"
    assert_officer_ledgers(before, imposed_suspension_days_total=30)

    decided = fixtures.decide_appeal(api, world, case["ap1_id"], "OVERTURNED")

    assert decided["outcome"] == "OVERTURNED"
    assert decided["status"] == "DECIDED"
    assert_instant(decided["decided_at"], "2026-08-25T00:00:00Z")

    discipline = fixtures.read_discipline(api, case["d1_id"], world["cmdr_headers"])
    assert discipline["status"] == "OVERTURNED"
    assert_discipline_days(discipline, final_days=30, effective_days=0)

    officer = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(officer, imposed_suspension_days_total=0, credibility_disclosure_active=False)
    assert officer["employment_status"] == "ACTIVE"
    assert officer["suspension_end_date"] is None

    allegation = fixtures.read_allegation(api, case["a1_id"], world["cmdr_headers"])
    assert allegation["disposition"] == "OVERTURNED_ON_APPEAL"
    disclosure = fixtures.read_disclosure(api, case["disc_id"], world["custodian_headers"])
    assert disclosure["status"] == "EXPUNGED"


def test_the_reversal_creates_a_pending_award_for_the_full_final_days(api, world):
    """Thirty reversed days are queued for back pay while final_days keeps its value.

    PRD: Fourth, a `Reinstatement` is created in `PENDING` with `reversed_days` equal to the full `final_days`.
    PRD: Filing stamps the appeal's `filed_at` from the logical clock and computes `days_to_file` as the elapsed span from the discipline's `imposed_at` to `filed_at` in whole days with any partial day discarded — an appeal filed at exactly a fifteen-day-old deadline has `days_to_file` 15.
    Design: Difficulty/transitive_cascade/appeal_overturned_reverses_the_whole_cascade
    """
    case = case_with_heard_appeal(api, world)
    assert case["appeal"]["days_to_file"] == 5
    assert case["appeal"]["modified_days"] is None

    fixtures.decide_appeal(api, world, case["ap1_id"], "OVERTURNED")

    reinstatement = fixtures.reinstatement_for_appeal(api, world, case["ap1_id"])
    assert reinstatement["status"] == "PENDING"
    assert reinstatement["reversed_days"] == 30
    assert reinstatement["interim_earnings_cents"] == 0
    assert reinstatement["gross_back_pay_cents"] is None
    assert reinstatement["total_award_cents"] is None
    assert reinstatement["finalized_at"] is None
    assert_instant(reinstatement["effective_date"], "2026-08-25T00:00:00Z")

    discipline = fixtures.read_discipline(api, case["d1_id"], world["cmdr_headers"])
    assert_discipline_days(discipline, final_days=30, effective_days=0)
