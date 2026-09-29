"""The progressive discipline matrix, its two variants, and the back-pay award."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    assert_cents,
    assert_discipline_days,
    assert_instant,
    assert_officer_ledgers,
)
from test_helpers import factories, fixtures


def run_case_to_sustained(
    api,
    world: Dict[str, Any],
    *,
    subject_officer_id: Optional[str] = None,
    allegation_type: str = "NEGLECT_OF_DUTY",
    offense_class: str = "B",
    session_start: str,
    session_end: str,
    notice_served_at: str,
    hold_at: str,
    aggravator_count: int = 0,
    mitigator_count: int = 0,
    evidence_weight_for: float = 60,
    evidence_weight_against: float = 40,
    incident_datetime: str = "2026-07-15T20:00:00Z",
    alleged_injury: bool = False,
) -> Dict[str, Any]:
    """Carry one complaint from intake to a sustained disposition and its Discipline row."""
    subject_id = subject_officer_id or world["subj_id"]
    complaint = fixtures.file_supervisor_complaint(
        api,
        world,
        reported_allegation_types=[allegation_type],
        incident_datetime=incident_datetime,
        alleged_injury=alleged_injury,
    )
    allegation = fixtures.attach_allegation(
        api,
        world,
        complaint["id"],
        subject_officer_id=subject_id,
        allegation_type=allegation_type,
        offense_class=offense_class,
    )
    investigation = fixtures.open_investigation(api, world, complaint["id"])
    fixtures.assign_investigation(
        api, world, investigation["id"], investigation["version"], world["inv_a_id"]
    )
    session = fixtures.schedule_session(
        api,
        world,
        investigation["id"],
        subject_officer_id=subject_id,
        scheduled_start=session_start,
        scheduled_end=session_end,
        notice_served_at=notice_served_at,
    )
    fixtures.set_clock(api, hold_at)
    fixtures.hold_session(api, world, session["id"])
    fixtures.submit_findings(
        api,
        world,
        investigation["id"],
        [
            factories.finding_entry(
                allegation["id"],
                evidence_weight_for=evidence_weight_for,
                evidence_weight_against=evidence_weight_against,
            )
        ],
    )
    fixtures.dispose_allegation(
        api,
        world,
        allegation["id"],
        "SUSTAINED",
        aggravator_count=aggravator_count,
        mitigator_count=mitigator_count,
    )
    discipline = fixtures.discipline_for_allegation(api, world, allegation["id"])
    return {
        "complaint_id": complaint["id"],
        "allegation_id": allegation["id"],
        "investigation_id": investigation["id"],
        "session_id": session["id"],
        "discipline_id": discipline["id"],
        "discipline": discipline,
    }


def two_prior_files(api, world: Dict[str, Any]) -> Dict[str, Any]:
    """One earlier sustained finding left un-imposed, then a second sustained finding."""
    first = run_case_to_sustained(
        api,
        world,
        session_start="2026-08-05T09:00:00Z",
        session_end="2026-08-05T10:30:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        hold_at="2026-08-05T09:00:00Z",
    )
    second = run_case_to_sustained(
        api,
        world,
        incident_datetime="2026-07-20T18:00:00Z",
        session_start="2026-08-09T09:00:00Z",
        session_end="2026-08-09T10:30:00Z",
        notice_served_at="2026-08-05T09:00:00Z",
        hold_at="2026-08-09T09:00:00Z",
        aggravator_count=2,
        mitigator_count=1,
    )
    return {"first": first, "second": second}


def test_presumptive_tier_counts_every_prior_sustained_finding(api, world):
    """A second sustained class B finding proposes 24 days at prior tier 1.

    PRD: Its reference instant is the allegation's `disposed_at`, its `aggravator_count` and `mitigator_count` are taken from the disposition payload, and its prior tier counts every qualifying sustained allegation regardless of whether the discipline arising from it was ever imposed — at proposal time only the findings are known.
    Design: Difficulty/dual_variant_calc/presumptive_versus_final_discipline_matrix_prior_tier
    """
    files = two_prior_files(api, world)

    second = files["second"]["discipline"]
    assert_discipline_days(second, presumptive_prior_tier=1, presumptive_days=24)
    assert second["status"] == "PROPOSED"
    assert second["offense_class"] == "B"

    first = fixtures.read_discipline(api, files["first"]["discipline_id"], world["cmdr_headers"])
    assert first["status"] == "PROPOSED"
    assert_discipline_days(first, presumptive_prior_tier=0, presumptive_days=10)


def test_final_tier_drops_the_prior_that_was_never_imposed(api, world):
    """Imposition recomputes the tier over imposed priors only, awarding 16 days.

    PRD: Priors that were proposed but never imposed drop out, so the final tier can be lower than the presumptive tier for the same officer — and the final award correspondingly lighter.
    Design: Difficulty/dual_variant_calc/presumptive_versus_final_discipline_matrix_prior_tier
    """
    files = two_prior_files(api, world)
    d2_id = files["second"]["discipline_id"]

    imposed = get_success_data(
        api.impose_discipline(
            d2_id,
            factories.imposition_payload(
                effective_date="2026-08-10T00:00:00Z", aggravator_count=2, mitigator_count=1
            ),
            world["cmdr_headers"],
        )
    )

    assert imposed["status"] == "IMPOSED"
    assert_discipline_days(
        imposed,
        presumptive_prior_tier=1,
        presumptive_days=24,
        final_prior_tier=0,
        final_days=16,
        effective_days=16,
    )
    assert_instant(imposed["appeal_deadline_at"], "2026-08-24T09:00:00Z")

    untouched = fixtures.read_discipline(api, files["first"]["discipline_id"], world["cmdr_headers"])
    assert untouched["status"] == "PROPOSED"

    officer = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(officer, imposed_suspension_days_total=16)
    assert officer["employment_status"] == "SUSPENDED"
    assert officer["suspension_end_date"].startswith("2026-08-26")


def case_to_pending_reinstatement(api, world):
    """One class A suspension of 30 days, reduced to 6 on appeal, awaiting its award."""
    case = run_case_to_sustained(
        api,
        world,
        allegation_type="EXCESSIVE_FORCE",
        offense_class="A",
        alleged_injury=True,
        session_start="2026-08-05T09:00:00Z",
        session_end="2026-08-05T10:30:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        hold_at="2026-08-05T09:00:00Z",
    )
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    imposed = get_success_data(
        api.impose_discipline(
            case["discipline_id"],
            factories.imposition_payload(effective_date="2026-08-20T00:00:00Z"),
            world["cmdr_headers"],
        )
    )
    assert_discipline_days(imposed, final_days=30, effective_days=30)

    fixtures.set_clock(api, "2026-08-25T00:00:00Z")
    appeal = get_success_data(
        api.file_appeal(case["discipline_id"], factories.appeal_payload("ARBITRATION"), world["rep_headers"])
    )
    fixtures.hear_appeal(api, world, appeal["id"])
    fixtures.decide_appeal(api, world, appeal["id"], "MODIFIED", modified_days=6)
    reinstatement = fixtures.reinstatement_for_appeal(api, world, appeal["id"])
    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    case.update({"appeal_id": appeal["id"], "reinstatement": reinstatement})
    return case


def test_back_pay_rounds_each_ten_day_period_before_summing(api, world):
    """Twenty-four reversed days on 9,100,013 cents gross 840,002, not 840,001.

    PRD: Each ten-day period rounds to 350,001 cents and the four-day period to 140,000 cents, giving a gross of 840,002 cents — a single rounding at the end would have produced 840,001.
    Design: Difficulty/combinatorial_formula/back_pay_per_period_rounding_then_offset_then_interest
    """
    case = case_to_pending_reinstatement(api, world)
    pending = case["reinstatement"]
    assert pending["status"] == "PENDING"
    assert pending["reversed_days"] == 24

    finalized = fixtures.finalize_reinstatement(
        api, world, pending["id"], interim_earnings_cents=125000
    )

    assert_cents(finalized["gross_back_pay_cents"], 840002)
    assert finalized["interim_earnings_cents"] == 125000


def test_interest_accrues_on_the_net_figure_after_the_interim_offset(api, world):
    """The award nets 715,002, accrues 7,150 of interest and totals 722,152.

    PRD: An interim-earnings offset of 125,000 cents leaves a net of 715,002 cents; a 73-day span from imposition to finalization yields interest of 7,150 cents; and the total award is 722,152 cents.
    Design: Difficulty/combinatorial_formula/back_pay_per_period_rounding_then_offset_then_interest
    """
    case = case_to_pending_reinstatement(api, world)

    finalized = fixtures.finalize_reinstatement(
        api, world, case["reinstatement"]["id"], interim_earnings_cents=125000
    )

    assert_cents(finalized["net_back_pay_cents"], 715002)
    assert_cents(finalized["interest_cents"], 7150)
    assert_cents(finalized["total_award_cents"], 722152)
    assert finalized["status"] == "FINALIZED"
    assert_instant(finalized["finalized_at"], "2026-11-01T00:00:00Z")

    discipline = fixtures.read_discipline(api, case["discipline_id"], world["cmdr_headers"])
    assert_discipline_days(discipline, final_days=30, effective_days=6)
    officer = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(officer, imposed_suspension_days_total=6)


def test_mitigation_rate_is_selected_from_the_pre_credit_figure(api, world):
    """Class B at tier 0 with two mitigators and no aggravators nets 8 days.

    PRD: The mitigation percentage is selected from the **pre-credit** figure, not from the base.
    Design: Difficulty/combinatorial_formula/mitigation_rate_selected_from_post_aggravator_subtotal
    """
    iyer = fixtures.create_officer(
        api, world["patrol_unit_id"], badge_number="PN-601", full_name="Officer Iyer"
    )

    case = run_case_to_sustained(
        api,
        world,
        subject_officer_id=iyer["id"],
        session_start="2026-08-05T09:00:00Z",
        session_end="2026-08-05T10:00:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        hold_at="2026-08-05T09:00:00Z",
        aggravator_count=0,
        mitigator_count=2,
    )

    assert_discipline_days(case["discipline"], presumptive_prior_tier=0, presumptive_days=8)


def test_one_aggravator_crosses_the_mitigation_band_and_adds_only_one_day(api, world):
    """The same finding with one aggravator nets 9 days, not 12.

    PRD: Four bands are walked from the top and the first match wins: 10 percent when the pre-credit figure is at most 10 days, 20 percent when it is at most 30 days, 25 percent when it is at most 60 days, and 30 percent for anything larger.
    Design: Difficulty/combinatorial_formula/mitigation_rate_selected_from_post_aggravator_subtotal
    """
    iyer = fixtures.create_officer(
        api, world["patrol_unit_id"], badge_number="PN-601", full_name="Officer Iyer"
    )
    jung = fixtures.create_officer(
        api, world["patrol_unit_id"], badge_number="PN-602", full_name="Officer Jung"
    )

    without_aggravator = run_case_to_sustained(
        api,
        world,
        subject_officer_id=iyer["id"],
        incident_datetime="2026-07-10T20:00:00Z",
        session_start="2026-08-05T09:00:00Z",
        session_end="2026-08-05T10:00:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        hold_at="2026-08-05T09:00:00Z",
        aggravator_count=0,
        mitigator_count=2,
    )
    with_aggravator = run_case_to_sustained(
        api,
        world,
        subject_officer_id=jung["id"],
        incident_datetime="2026-07-11T20:00:00Z",
        session_start="2026-08-05T11:30:00Z",
        session_end="2026-08-05T12:30:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        hold_at="2026-08-05T11:30:00Z",
        aggravator_count=1,
        mitigator_count=2,
    )

    assert_discipline_days(
        with_aggravator["discipline"], presumptive_prior_tier=0, presumptive_days=9
    )
    assert without_aggravator["discipline"]["presumptive_days"] == 8


def two_imposed_disciplines(api, world):
    """A 30-day class A award and a 24-day class B award, both standing."""
    first = run_case_to_sustained(
        api,
        world,
        offense_class="A",
        incident_datetime="2026-07-10T20:00:00Z",
        session_start="2026-08-05T09:00:00Z",
        session_end="2026-08-05T10:30:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        hold_at="2026-08-05T09:00:00Z",
        evidence_weight_for=70,
        evidence_weight_against=30,
    )
    assert_discipline_days(first["discipline"], presumptive_prior_tier=0, presumptive_days=30)
    d1 = get_success_data(
        api.impose_discipline(
            first["discipline_id"],
            factories.imposition_payload(effective_date="2026-08-06T00:00:00Z"),
            world["cmdr_headers"],
        )
    )
    assert_discipline_days(d1, final_prior_tier=0, final_days=30, effective_days=30)

    second = run_case_to_sustained(
        api,
        world,
        offense_class="B",
        incident_datetime="2026-07-12T20:00:00Z",
        session_start="2026-08-06T09:00:00Z",
        session_end="2026-08-06T10:00:00Z",
        notice_served_at="2026-08-01T00:00:00Z",
        hold_at="2026-08-06T09:00:00Z",
        aggravator_count=2,
        mitigator_count=1,
        evidence_weight_for=70,
        evidence_weight_against=30,
    )
    assert_discipline_days(second["discipline"], presumptive_prior_tier=1, presumptive_days=24)
    d2 = get_success_data(
        api.impose_discipline(
            second["discipline_id"],
            factories.imposition_payload(
                effective_date="2026-08-07T00:00:00Z", aggravator_count=2, mitigator_count=1
            ),
            world["cmdr_headers"],
        )
    )
    assert_discipline_days(d2, final_prior_tier=1, final_days=24, effective_days=24)
    return {"first": first, "second": second}


def test_overturn_returns_the_suspension_ledger_to_its_pre_imposition_value(api, world):
    """Reversing the 24-day award leaves the ledger at exactly 30, still suspended.

    PRD: First, `final_days` is subtracted from the officer's `imposed_suspension_days_total`, restoring exactly the pre-imposition value.
    Design: Difficulty/compensating_invariant/suspension_day_ledger_returns_to_its_pre_appeal_value_before_the_employment_flip
    """
    cases = two_imposed_disciplines(api, world)

    before = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(before, imposed_suspension_days_total=54)
    assert before["employment_status"] == "SUSPENDED"

    appeal = get_success_data(
        api.file_appeal(
            cases["second"]["discipline_id"],
            factories.appeal_payload("ARBITRATION"),
            world["rep_headers"],
        )
    )
    assert appeal["days_to_file"] == 0
    fixtures.hear_appeal(api, world, appeal["id"])
    decided = fixtures.decide_appeal(api, world, appeal["id"], "OVERTURNED")
    assert decided["outcome"] == "OVERTURNED"

    reversed_discipline = fixtures.read_discipline(
        api, cases["second"]["discipline_id"], world["cmdr_headers"]
    )
    assert reversed_discipline["status"] == "OVERTURNED"
    assert_discipline_days(reversed_discipline, final_days=24, effective_days=0)

    mid = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(mid, imposed_suspension_days_total=30)
    assert mid["employment_status"] == "SUSPENDED"
    assert mid["suspension_end_date"] is not None

    overturned_allegation = fixtures.read_allegation(
        api, cases["second"]["allegation_id"], world["cmdr_headers"]
    )
    assert overturned_allegation["disposition"] == "OVERTURNED_ON_APPEAL"
    standing_allegation = fixtures.read_allegation(
        api, cases["first"]["allegation_id"], world["cmdr_headers"]
    )
    assert standing_allegation["disposition"] == "SUSTAINED"
    standing_discipline = fixtures.read_discipline(
        api, cases["first"]["discipline_id"], world["cmdr_headers"]
    )
    assert standing_discipline["status"] == "IMPOSED"
    assert standing_discipline["effective_days"] == 30


def test_employment_flips_only_when_the_ledger_reaches_exactly_zero(api, world):
    """Only the second reversal, which empties the ledger, restores ACTIVE.

    PRD: Second, when that subtraction brings `imposed_suspension_days_total` to exactly 0, the officer returns `SUSPENDED → ACTIVE` and `suspension_end_date` is cleared; when other imposed discipline still stands the officer remains `SUSPENDED`.
    Design: Difficulty/compensating_invariant/suspension_day_ledger_returns_to_its_pre_appeal_value_before_the_employment_flip
    """
    cases = two_imposed_disciplines(api, world)

    second_appeal = get_success_data(
        api.file_appeal(
            cases["second"]["discipline_id"],
            factories.appeal_payload("ARBITRATION"),
            world["rep_headers"],
        )
    )
    fixtures.hear_appeal(api, world, second_appeal["id"])
    fixtures.decide_appeal(api, world, second_appeal["id"], "OVERTURNED")

    first_appeal = get_success_data(
        api.file_appeal(
            cases["first"]["discipline_id"],
            factories.appeal_payload("CIVIL_SERVICE"),
            world["rep_headers"],
        )
    )
    assert first_appeal["days_to_file"] == 1
    fixtures.hear_appeal(api, world, first_appeal["id"])
    fixtures.decide_appeal(api, world, first_appeal["id"], "OVERTURNED")

    after = fixtures.read_officer(api, world["subj_id"], world["cmdr_headers"])
    assert_officer_ledgers(after, imposed_suspension_days_total=0)
    assert after["employment_status"] == "ACTIVE"
    assert after["suspension_end_date"] is None

    from_second, _ = fixtures.rows(
        api.list_appeal_reinstatements(second_appeal["id"], world["appeals_headers"])
    )
    from_first, _ = fixtures.rows(
        api.list_appeal_reinstatements(first_appeal["id"], world["appeals_headers"])
    )
    assert len(from_second) == 1 and len(from_first) == 1
    assert from_second[0]["reversed_days"] == 24
    assert from_second[0]["status"] == "PENDING"
    assert from_first[0]["reversed_days"] == 30
    assert from_first[0]["status"] == "PENDING"
