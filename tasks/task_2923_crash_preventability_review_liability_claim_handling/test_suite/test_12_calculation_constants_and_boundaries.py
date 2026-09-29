"""Named constants, thresholds and rounding rules, each pinned at its boundary.

Every figure asserted here is recomputed by hand from the published rule rather
than copied from a previous response, so a formula that is right on one input and
wrong one cent away is still caught.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_instants_equal,
    assert_multiplier,
    assert_points_1dp,
    assert_rate,
    assert_score_2dp,
)
from test_helpers.constants import (
    ACTION_STATE_ISSUED,
    ACTION_TIER_COACHING,
    ACTION_TIER_NONE,
    ACTION_TIER_RETRAINING,
    ACTION_TYPE_RETRAINING,
    ACTION_TYPE_SUSPENSION,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIM_HANDLING_NEGOTIATION,
    CLAIM_HANDLING_SETTLEMENT_COMPLETE,
    CLAIMANT_TYPE_BODILY_INJURY,
    CLAIMANT_TYPE_PROPERTY,
    CLOCK_EPOCH,
    COUNSEL_TYPE_LEAD_TRIAL,
    COUNSEL_TYPE_NONE,
    COUNSEL_TYPE_PANEL,
    DECISION_BASIS_WEIGHTED_CRITERIA,
    DEMAND_STATE_SETTLED,
    DETERMINATION_PREVENTABLE,
    DRIVER_STATUS_RETRAINING_REQUIRED,
    DRIVER_STATUS_SUSPENDED_PENDING_ACTION,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_POSTURE_COMPLETE,
    EVIDENCE_POSTURE_COMPROMISED,
    EVIDENCE_POSTURE_PARTIAL,
    EVIDENCE_SCENE_PHOTO,
    EVIDENCE_TELEMATICS,
    LAYER_KIND_EXCESS,
    LAYER_KIND_PRIMARY,
    LAYER_KIND_SIR,
    PRESERVATION_PRESERVED,
    PRESERVATION_RELEASED,
    PRESERVATION_REQUESTED,
    RECORDABILITY_CODE_ORDER,
    REPORTING_STATUS_NOT_REQUIRED,
    REPORTING_STATUS_PENDING_FILING,
    RESERVE_BASIS_DEMAND_BASED,
    RESERVE_BASIS_PROVISIONAL_REFRESH,
    RESERVE_STATUS_PROVISIONAL,
    RESERVE_STATUS_REVISED,
    RETRAINING_STATUS_PENDING,
    RISK_SCORE_CAP,
    RISK_TIER_STANDARD,
    ROUND_OUTCOME_ACCEPTED,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_LOCAL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_CATASTROPHIC,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    SEVERITY_SEVERE,
    STAFFING_POSTURE_CRITICAL,
    STAFFING_POSTURE_OK,
    STAFFING_POSTURE_STRAINED,
    SUBROGATION_RESOLUTION_RECOVERED,
    SUBROGATION_STATE_READY_TO_PURSUE,
    SUBROGATION_STATE_RECOVERED,
    TENURE_UNDER_12_MONTHS,
    TOW_REASON_CONVENIENCE,
    TOW_REASON_DISABLING_DAMAGE,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    CLAIMS_ADJUSTER,
    CLAIMS_MANAGER,
    DISPATCHER,
    SAFETY_ADMIN,
    SAFETY_MANAGER,
    build_case_in_deliberation,
    build_claim,
    build_crash,
    build_demand,
    build_discipline,
    build_driver,
    build_policy_layer,
    build_review_case,
    build_statement,
    build_subrogation_demand,
    build_terminal,
    cast_quorum,
    decide_case,
    make_offer,
    preserve_evidence,
    purge_evidence,
    request_evidence,
    revise_reserve,
    set_clock,
    settle,
)

FATALITY = RECORDABILITY_CODE_ORDER[0]
INJURY_TRANSPORTED = RECORDABILITY_CODE_ORDER[1]
DISABLING_TOW = RECORDABILITY_CODE_ORDER[2]
HAZMAT_RELEASE = RECORDABILITY_CODE_ORDER[3]


def _orrville_fleet(api: ApiClient) -> dict:
    """One high-mileage terminal with one long-tenured driver."""
    set_clock(api, CLOCK_EPOCH)
    terminal = build_terminal(
        api,
        name="Orrville Terminal",
        terminal_code="ORR02",
        region_code="OH",
        annual_miles_millions=6.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4001",
        full_name="Emeka Sundqvist",
        cdl_number="OH-CDL-4001",
        hire_date="2010-10-10",
    )
    return {"terminal": terminal, "driver": driver}


class TestRecordabilityCodesAndTheFilingWindow:
    """Which codes fire, in which order, and how long the agency window runs."""

    def test_all_four_codes_emit_in_their_pinned_order_on_the_short_window(
        self, api: ApiClient
    ):
        """Fatality first, hazmat last, and 24 hours from the crash itself.

        PRD: "The codes that fired are written to `recordability_codes` in one
        fixed sequence — fatality first, then transported injury, then disabling
        tow, then hazmat release — never in the order the triggers happened to be
        evaluated and never sorted alphabetically." — "`report_due_at` is 24 hours
        after `occurred_at` when a hazardous-material release occurred"

        Design: Corner/calculations/recordability_codes_emit_in_fixed_order_with_the_hazmat_window
        """
        fleet = _orrville_fleet(api)
        crash = build_crash(
            api,
            fleet["driver"]["id"],
            fleet["terminal"]["id"],
            occurred_at="2026-07-31T06:00:00Z",
            notified_at="2026-07-31T06:40:00Z",
            location_text="I-76 MM 209",
            severity=SEVERITY_CATASTROPHIC,
            route_class=ROUTE_CLASS_LINEHAUL,
            tow_away=True,
            tow_reason=TOW_REASON_DISABLING_DAMAGE,
            injury_transported_count=2,
            fatality_count=1,
            hazmat_release=True,
        )

        assert crash["recordability_codes"] == [
            FATALITY,
            INJURY_TRANSPORTED,
            DISABLING_TOW,
            HAZMAT_RELEASE,
        ]
        assert crash["recordability_codes"][0] != DISABLING_TOW
        assert crash["dot_recordable"] is True
        assert crash["reporting_status"] == REPORTING_STATUS_PENDING_FILING
        assert_instants_equal(crash["report_due_at"], "2026-08-01T06:00:00Z", "report_due_at")

    def test_a_release_with_no_injury_and_no_tow_is_still_recordable(
        self, api: ApiClient
    ):
        """One trigger is enough, and it is the one that shortens the window.

        PRD: "A hazmat crash with no injury and no tow is therefore recordable on
        the strength of the release alone and carries the short 24-hour window."

        Design: Corner/calculations/recordability_codes_emit_in_fixed_order_with_the_hazmat_window
        """
        fleet = _orrville_fleet(api)
        crash = build_crash(
            api,
            fleet["driver"]["id"],
            fleet["terminal"]["id"],
            occurred_at="2026-07-31T12:00:00Z",
            notified_at="2026-07-31T12:05:00Z",
            location_text="Tank farm apron",
            severity=SEVERITY_MODERATE,
            route_class=ROUTE_CLASS_LOCAL,
            tow_away=False,
            tow_reason=TOW_REASON_NONE,
            hazmat_release=True,
        )

        assert crash["recordability_codes"] == [HAZMAT_RELEASE]
        assert crash["dot_recordable"] is True
        assert crash["reporting_status"] == REPORTING_STATUS_PENDING_FILING
        assert_instants_equal(crash["report_due_at"], "2026-08-01T12:00:00Z", "report_due_at")

    def test_a_convenience_tow_fires_nothing_while_a_transported_injury_fires_once(
        self, api: ApiClient
    ):
        """The tow trigger is a conjunction, and the plain window is 72 hours.

        PRD: "A tow contributes `DISABLING_TOW` only when `tow_away` is true *and*
        `tow_reason` is `DISABLING_DAMAGE` — a unit towed for convenience is not a
        trigger, and both conditions must hold together." — "and 72 hours — three
        days — after `occurred_at` otherwise"

        Design: Corner/calculations/recordability_codes_emit_in_fixed_order_with_the_hazmat_window
        """
        fleet = _orrville_fleet(api)
        convenience = build_crash(
            api,
            fleet["driver"]["id"],
            fleet["terminal"]["id"],
            occurred_at="2026-07-31T15:00:00Z",
            notified_at="2026-07-31T15:10:00Z",
            location_text="Customer lot",
            severity=SEVERITY_MINOR,
            route_class=ROUTE_CLASS_LOCAL,
            tow_away=True,
            tow_reason=TOW_REASON_CONVENIENCE,
        )

        assert convenience["recordability_codes"] == []
        assert convenience["dot_recordable"] is False
        assert convenience["report_due_at"] is None
        assert convenience["reporting_status"] == REPORTING_STATUS_NOT_REQUIRED

        injured = build_crash(
            api,
            fleet["driver"]["id"],
            fleet["terminal"]["id"],
            occurred_at="2026-07-30T19:00:00Z",
            notified_at="2026-07-30T19:25:00Z",
            location_text="US-30 at Kidron Rd",
            severity=SEVERITY_MODERATE,
            route_class=ROUTE_CLASS_REGIONAL,
            tow_away=False,
            tow_reason=TOW_REASON_NONE,
            injury_transported_count=1,
        )

        assert injured["recordability_codes"] == [INJURY_TRANSPORTED]
        assert injured["dot_recordable"] is True
        assert_instants_equal(injured["report_due_at"], "2026-08-02T19:00:00Z", "report_due_at")


PIQUA_CRASH_AT = "2026-07-31T12:00:00Z"
PIQUA_RETENTION = "2026-10-31T00:00:00Z"


def _moderate_crash_with_no_claim_on_file(api: ApiClient) -> dict:
    """A moderate crash needing two kinds, and no claim to hold the evidence."""
    set_clock(api, CLOCK_EPOCH)
    terminal = build_terminal(
        api,
        name="Piqua Terminal",
        terminal_code="POR02",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4101",
        full_name="Freya Lindenbaum",
        cdl_number="OH-CDL-4101",
        hire_date="2012-02-22",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at=PIQUA_CRASH_AT,
        notified_at="2026-07-31T12:20:00Z",
        location_text="SR-66 at Looney Rd",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    return {"terminal": terminal, "driver": driver, "crash": crash}


def _preserve_touching_telematics(api: ApiClient, crash_id: str) -> dict:
    """A telematics window that ends exactly at the crash instant."""
    requested = request_evidence(
        api,
        crash_id,
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-4101-A",
        window_start_at="2026-07-31T10:00:00Z",
        window_end_at=PIQUA_CRASH_AT,
        retention_deadline_at=PIQUA_RETENTION,
    )
    return preserve_evidence(
        api,
        requested["id"],
        preserved_copy_uri="s3://evidence/2923por/ecm-4101-a.json",
        evidence_hash="8d8d9e9e0f0f1a1a2b2b3c3c4d4d5e5e",
    )


def _request_bracketing_telematics(api: ApiClient, crash_id: str):
    """The adjacent telematics window that opens at the crash instant."""
    return api.create_evidence_item(
        crash_id,
        {
            "kind": EVIDENCE_TELEMATICS,
            "source_device_id": "ECM-4101-B",
            "window_start_at": PIQUA_CRASH_AT,
            "window_end_at": "2026-07-31T14:00:00Z",
            "retention_deadline_at": PIQUA_RETENTION,
        },
        DISPATCHER,
    )


def _preserve_bracketing_camera(api: ApiClient, crash_id: str) -> dict:
    """The forward camera whose window straddles the crash instant."""
    requested = request_evidence(
        api,
        crash_id,
        kind=EVIDENCE_FORWARD_CAMERA,
        source_device_id="CAM-4101",
        window_start_at="2026-07-31T11:30:00Z",
        window_end_at="2026-07-31T12:30:00Z",
        retention_deadline_at=PIQUA_RETENTION,
    )
    return preserve_evidence(
        api,
        requested["id"],
        preserved_copy_uri="s3://evidence/2923por/cam-4101.mp4",
        evidence_hash="0f0f1a1a2b2b3c3c4d4d5e5e6f6f7a7a",
    )


class TestOnlyPreservedItemsThatBracketTheCrashCountTowardThePosture:
    """The bracket test is half-open, and only live items are counted."""

    def test_a_window_that_ends_at_the_crash_instant_satisfies_nothing(
        self, api: ApiClient
    ):
        """Preserved is necessary but the exclusive end makes it insufficient.

        PRD: "A required kind counts as satisfied only by an item that is
        currently in `PRESERVED` state *and* whose data window brackets the crash
        instant, where bracketing means `window_start_at` is at or before
        `occurred_at` and `occurred_at` is strictly earlier than `window_end_at`.
        An item whose window ends exactly at the crash instant therefore does not
        bracket it, because the end of the window is exclusive."

        Design: Corner/calculations/evidence_posture_counts_only_preserved_items_that_bracket_the_crash
        """
        context = _moderate_crash_with_no_claim_on_file(api)
        touching = _preserve_touching_telematics(api, context["crash"]["id"])
        assert touching["preservation_state"] == PRESERVATION_PRESERVED

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL
        assert crash["evidence_posture"] != EVIDENCE_POSTURE_COMPROMISED

    def test_an_adjacent_window_of_the_same_kind_is_accepted_and_then_counts(
        self, api: ApiClient
    ):
        """Touching windows are not overlapping, and the second one brackets.

        PRD: "Overlap is judged on half-open intervals that include their start
        instant and exclude their end instant, so two windows that merely touch at
        an instant, one ending exactly where the next begins, are accepted as
        adjacent rather than rejected as overlapping."

        Design: Corner/calculations/evidence_posture_counts_only_preserved_items_that_bracket_the_crash
        """
        context = _moderate_crash_with_no_claim_on_file(api)
        crash_id = context["crash"]["id"]
        _preserve_touching_telematics(api, crash_id)

        adjacent = validate_success(_request_bracketing_telematics(api, crash_id), 201)
        assert adjacent["kind"] == EVIDENCE_TELEMATICS
        assert adjacent["preservation_state"] == PRESERVATION_REQUESTED
        preserve_evidence(
            api,
            adjacent["id"],
            preserved_copy_uri="s3://evidence/2923por/ecm-4101-b.json",
            evidence_hash="9e9e0f0f1a1a2b2b3c3c4d4d5e5e6f6f",
        )

        still_partial = validate_success(api.get_crash(crash_id, SAFETY_MANAGER))
        assert still_partial["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL

        _preserve_bracketing_camera(api, crash_id)
        complete = validate_success(api.get_crash(crash_id, SAFETY_MANAGER))
        assert complete["evidence_posture"] == EVIDENCE_POSTURE_COMPLETE

    def test_releasing_a_counted_item_drops_the_posture_back_to_partial(
        self, api: ApiClient
    ):
        """A released item stops satisfying its kind rather than staying counted.

        PRD: "the crash's evidence posture is re-derived — and since a released
        item no longer satisfies any required kind, a crash that was complete can
        fall back to partial"

        Design: Corner/calculations/evidence_posture_counts_only_preserved_items_that_bracket_the_crash
        """
        context = _moderate_crash_with_no_claim_on_file(api)
        crash_id = context["crash"]["id"]
        _preserve_touching_telematics(api, crash_id)
        adjacent = validate_success(_request_bracketing_telematics(api, crash_id), 201)
        preserve_evidence(
            api,
            adjacent["id"],
            preserved_copy_uri="s3://evidence/2923por/ecm-4101-b.json",
            evidence_hash="9e9e0f0f1a1a2b2b3c3c4d4d5e5e6f6f",
        )
        camera = _preserve_bracketing_camera(api, crash_id)
        assert (
            validate_success(api.get_crash(crash_id, SAFETY_MANAGER))["evidence_posture"]
            == EVIDENCE_POSTURE_COMPLETE
        )

        released = purge_evidence(
            api,
            camera["id"],
            purge_reason="released after the retention schedule with no claim on file",
        )

        assert released["preservation_state"] == PRESERVATION_RELEASED
        fallen_back = validate_success(api.get_crash(crash_id, SAFETY_MANAGER))
        assert fallen_back["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL
        assert fallen_back["evidence_posture"] != EVIDENCE_POSTURE_COMPROMISED


COUNSEL_BOUNDARY_SCORE = 55
COUNSEL_BOUNDARY_MULTIPLIER = 1.35
REPRESENTED_BI_SCORE = 70
UNGATED_SCORE = 10
CATASTROPHIC_GROSS_CENTS = 135_000_000
FROZEN_CATASTROPHIC_RESERVE_CENTS = 182_250_000
EXPENSE_ON_UNMULTIPLIED_GROSS_CENTS = 24_300_000
REVISED_CATASTROPHIC_RESERVE_CENTS = 206_550_000
EXPENSE_ON_MULTIPLIED_FIGURE_CENTS = 32_805_000
COUNSEL_FIRM = "Brackett & Nunn LLP"


def _fatal_compromised_claim_and_an_unremarkable_one(api: ApiClient) -> dict:
    """A claim scoring exactly at the counsel boundary, beside one scoring 10."""
    set_clock(api, CLOCK_EPOCH)
    terminal = build_terminal(
        api,
        name="Quincy Terminal",
        terminal_code="QCY02",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4201",
        full_name="Gunnar Adeyemi",
        cdl_number="OH-CDL-4201",
        hire_date="2015-01-05",
    )
    fatal = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-29T02:00:00Z",
        notified_at="2026-07-29T02:40:00Z",
        location_text="I-70 MM 9",
        severity=SEVERITY_CATASTROPHIC,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        fatality_count=1,
    )
    spoliated = request_evidence(
        api,
        fatal["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-4201",
        window_start_at="2026-07-29T01:00:00Z",
        window_end_at="2026-07-29T03:00:00Z",
        retention_deadline_at="2026-12-31T00:00:00Z",
    )
    purge_evidence(api, spoliated["id"], purge_reason="unit destroyed on impact")
    build_statement(
        api,
        fatal["id"],
        driver["id"],
        narrative="I do not remember the impact.",
        conditions_note=None,
    )
    build_review_case(api, fatal["id"], committee_name="Quincy Safety Review Committee")
    minor = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-31T20:00:00Z",
        notified_at="2026-07-31T20:05:00Z",
        location_text="Dock 9",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    return {"terminal": terminal, "driver": driver, "fatal": fatal, "minor": minor}


def _bodily_injury_demand(api: ApiClient, claim_id: str) -> dict:
    """A represented bodily-injury demand for fifty million cents."""
    return build_demand(
        api,
        claim_id,
        claimant_name="Estate of R. Halvorsen",
        claimant_type=CLAIMANT_TYPE_BODILY_INJURY,
        demand_amount_cents=50_000_000,
        represented_by_counsel=True,
        demand_received_at="2026-07-31T18:00:00Z",
    )


class TestTheCounselBoundaryIsInclusiveAndGatesInjuryOffers:
    """Fifty-five points exactly, and what that single point buys.

    The loadings are chosen so the sum lands on the threshold rather than near it.
    """

    def test_the_score_lands_on_fifty_five_and_freezes_the_multiplied_reserve(
        self, api: ApiClient
    ):
        """Ten plus twenty-five plus twenty, with severity deliberately absent.

        PRD: "`counsel_required` is true when `litigation_risk_score` is at least
        55 — a score of exactly 55 does require counsel. And
        `litigation_risk_multiplier` is a band over the same score: 1.00 at 24
        points or below, 1.15 from 25 through 54, 1.35 from 55 through 79" —
        "Crash `severity` deliberately plays no part here"

        Design: Corner/calculations/litigation_risk_constants_at_the_counsel_boundary_gate_offers
        """
        context = _fatal_compromised_claim_and_an_unremarkable_one(api)
        claim = build_claim(api, context["fatal"]["id"], claimant_notice_date="2026-07-31")

        assert claim["litigation_risk_score"] == COUNSEL_BOUNDARY_SCORE
        assert claim["counsel_required"] is True
        assert_multiplier(
            claim["litigation_risk_multiplier"],
            COUNSEL_BOUNDARY_MULTIPLIER,
            "litigation_risk_multiplier",
        )
        assert_cents(
            claim["provisional_reserve_cents"],
            FROZEN_CATASTROPHIC_RESERVE_CENTS,
            "provisional_reserve_cents",
        )
        assert claim["counsel_assigned"] is False
        assert claim["counsel_type"] == COUNSEL_TYPE_NONE
        assert claim["litigation_flag"] is False

    def test_an_injury_offer_is_blocked_until_counsel_is_engaged(self, api: ApiClient):
        """The identical offer is refused, then accepted, on the same demand.

        PRD: "When the demand's `claimant_type` is `THIRD_PARTY_BODILY_INJURY` and
        the parent claim's `counsel_required` is true, an offer may be made only
        once the claim's `counsel_assigned` is true; otherwise it is refused with
        `ERR_COUNSEL_REQUIRED`."

        Design: Corner/calculations/litigation_risk_constants_at_the_counsel_boundary_gate_offers
        """
        context = _fatal_compromised_claim_and_an_unremarkable_one(api)
        claim = build_claim(api, context["fatal"]["id"], claimant_notice_date="2026-07-31")
        demand = _bodily_injury_demand(api, claim["id"])

        validate_error(
            api.create_offer(demand["id"], factories.offer_payload(10_000_000), CLAIMS_ADJUSTER),
            ApiErrorId.COUNSEL_REQUIRED.value,
            422,
        )
        _, blocked_meta = validate_paginated(
            api.list_negotiation_rounds(demand["id"], CLAIMS_ADJUSTER)
        )
        assert blocked_meta["total_count"] == 0

        assigned = validate_success(
            api.assign_counsel(
                claim["id"],
                factories.counsel_assignment_payload(
                    counsel_firm_name=COUNSEL_FIRM, counsel_type=COUNSEL_TYPE_LEAD_TRIAL
                ),
                CLAIMS_MANAGER,
            )
        )
        assert assigned["counsel_assigned"] is True
        assert assigned["counsel_type"] == COUNSEL_TYPE_LEAD_TRIAL
        assert assigned["litigation_flag"] is True
        assert_instants_equal(assigned["counsel_assigned_at"], CLOCK_EPOCH, "counsel_assigned_at")
        assert assigned["litigation_risk_score"] == REPRESENTED_BI_SCORE
        assert_multiplier(
            assigned["litigation_risk_multiplier"],
            COUNSEL_BOUNDARY_MULTIPLIER,
            "litigation_risk_multiplier",
        )
        assert_cents(
            assigned["provisional_reserve_cents"],
            FROZEN_CATASTROPHIC_RESERVE_CENTS,
            "provisional_reserve_cents",
        )

        allowed = validate_success(
            api.create_offer(demand["id"], factories.offer_payload(10_000_000), CLAIMS_ADJUSTER),
            201,
        )
        assert allowed["round_index"] == 1
        assert_cents(allowed["carrier_offer_cents"], 10_000_000, "carrier_offer_cents")

    def test_the_expense_loading_is_taken_on_the_unmultiplied_gross(self, api: ApiClient):
        """Loading the multiplied figure would count litigation risk twice.

        PRD: "the expense component is taken **on the unmultiplied gross
        exposure**, not on the indemnity component: it is 18 percent of the gross
        exposure rounded half up to a whole cent when the claim has counsel
        assigned ... Loading the multiplied figure instead would count litigation
        risk twice."

        Design: Corner/calculations/litigation_risk_constants_at_the_counsel_boundary_gate_offers
        """
        context = _fatal_compromised_claim_and_an_unremarkable_one(api)
        claim = build_claim(api, context["fatal"]["id"], claimant_notice_date="2026-07-31")
        validate_success(
            api.assign_counsel(
                claim["id"],
                factories.counsel_assignment_payload(
                    counsel_firm_name=COUNSEL_FIRM, counsel_type=COUNSEL_TYPE_LEAD_TRIAL
                ),
                CLAIMS_MANAGER,
            )
        )
        observed = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))

        revised = revise_reserve(
            api,
            claim["id"],
            observed["version"],
            basis=RESERVE_BASIS_PROVISIONAL_REFRESH,
            revision_note="refresh now that lead trial counsel is engaged",
        )

        assert_cents(
            revised["revised_reserve_cents"],
            REVISED_CATASTROPHIC_RESERVE_CENTS,
            "revised_reserve_cents",
        )
        assert (
            REVISED_CATASTROPHIC_RESERVE_CENTS
            == FROZEN_CATASTROPHIC_RESERVE_CENTS + EXPENSE_ON_UNMULTIPLIED_GROSS_CENTS
        )
        assert revised["revised_reserve_cents"] != (
            FROZEN_CATASTROPHIC_RESERVE_CENTS + EXPENSE_ON_MULTIPLIED_FIGURE_CENTS
        )
        assert_cents(
            revised["outstanding_reserve_cents"],
            REVISED_CATASTROPHIC_RESERVE_CENTS,
            "outstanding_reserve_cents",
        )
        assert revised["reserve_status"] == RESERVE_STATUS_REVISED
        assert_cents(revised["indemnity_paid_cents"], 0, "indemnity_paid_cents")
        assert_cents(revised["alae_paid_cents"], 0, "alae_paid_cents")

    def test_a_claim_scoring_ten_refuses_the_very_same_counsel_assignment(
        self, api: ApiClient
    ):
        """Below the boundary the assignment is the request that is wrong.

        PRD: "It is refused on a claim whose `counsel_required` is false, with
        `ERR_COUNSEL_NOT_REQUIRED` — panel counsel is not assigned to files that
        do not warrant it"

        Design: Corner/calculations/litigation_risk_constants_at_the_counsel_boundary_gate_offers
        """
        context = _fatal_compromised_claim_and_an_unremarkable_one(api)
        quiet = build_claim(api, context["minor"]["id"], claimant_notice_date="2026-08-01")

        assert quiet["litigation_risk_score"] == UNGATED_SCORE
        assert quiet["counsel_required"] is False

        validate_error(
            api.assign_counsel(
                quiet["id"],
                factories.counsel_assignment_payload(
                    counsel_firm_name=COUNSEL_FIRM, counsel_type=COUNSEL_TYPE_PANEL
                ),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.COUNSEL_NOT_REQUIRED.value,
            422,
        )

        unchanged = validate_success(api.get_claim(quiet["id"], CLAIMS_ADJUSTER))
        assert unchanged["counsel_assigned"] is False
        assert unchanged["counsel_firm_name"] is None
        assert unchanged["counsel_type"] == COUNSEL_TYPE_NONE
        assert unchanged["version"] == quiet["version"]


MODERATE_RESERVE_CENTS = 2_500_000
RAVENNA_OFFER_CENTS = 925_001
RAVENNA_ALAE_CENTS = 74_000
RAVENNA_TOTAL_CENTS = 999_001
RAVENNA_AT_FAULT_PERCENTAGE = 50
RAVENNA_CEILING_CENTS = 499_501
RAVENNA_BANKERS_ROUNDING_CENTS = 499_500
RAVENNA_OUTSTANDING_AFTER_CENTS = 1_500_999
RAVENNA_INCURRED_CENTS = 2_000_499


def _settled_property_claim_with_a_half_cent_ceiling(api: ApiClient) -> dict:
    """A settlement whose recoverable base halves onto an exact half cent."""
    set_clock(api, CLOCK_EPOCH)
    terminal = build_terminal(
        api,
        name="Ravenna Terminal",
        terminal_code="RVN02",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4301",
        full_name="Hana Wlodarczyk",
        cdl_number="OH-CDL-4301",
        hire_date="2013-04-04",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T13:00:00Z",
        notified_at="2026-07-30T13:15:00Z",
        location_text="SR-14 at Diagonal Rd",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        third_party_at_fault=True,
    )
    layer = build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=10_000_000,
        insurer_name="Self-insured retention",
    )
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-31")
    demand = build_demand(
        api,
        claim["id"],
        claimant_name="Diagonal Road Auto Body",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=1_000_000,
        represented_by_counsel=False,
        demand_received_at="2026-07-31T09:00:00Z",
    )
    recovery = build_subrogation_demand(
        api,
        claim["id"],
        third_party_name="Portage County Paving",
        at_fault_percentage=RAVENNA_AT_FAULT_PERCENTAGE,
        basis_note="unmarked lane closure caused the swerve",
    )
    make_offer(api, demand["id"], RAVENNA_OFFER_CENTS)
    return {
        "layer": layer,
        "claim": claim,
        "demand": demand,
        "recovery": recovery,
    }


class TestTheRecoveryCeilingRoundsHalfUpOnTheExactHalfCent:
    """A base of 999,001 at fifty percent, which is the awkward case by design."""

    def test_the_low_expense_tier_produces_the_awkward_recoverable_base(
        self, api: ApiClient
    ):
        """An indemnity under five million takes the eight-percent band.

        PRD: "an indemnity of 5,000,000 cents or more but under 25,000,000 takes
        0.12, and anything under 5,000,000 takes 0.08" — "`recoverable_base_cents`
        is the claim's `indemnity_paid_cents` plus `alae_paid_cents` at the instant
        of promotion"

        Design: Corner/calculations/subrogation_ceiling_rounds_half_up_at_the_exact_half_cent
        """
        context = _settled_property_claim_with_a_half_cent_ceiling(api)
        assert_cents(
            context["claim"]["outstanding_reserve_cents"],
            MODERATE_RESERVE_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(
            context["claim"]["claim_exposure_cents"],
            MODERATE_RESERVE_CENTS,
            "claim_exposure_cents",
        )

        settled = settle(api, context["demand"]["id"], settlement_reference="SET-2026-RVN02-0001")

        assert settled["status"] == DEMAND_STATE_SETTLED
        assert_cents(settled["settled_amount_cents"], RAVENNA_OFFER_CENTS, "settled_amount_cents")
        assert_cents(settled["alae_cents"], RAVENNA_ALAE_CENTS, "alae_cents")
        assert_cents(
            settled["settlement_total_cents"], RAVENNA_TOTAL_CENTS, "settlement_total_cents"
        )

        promoted = validate_success(
            api.get_subrogation_demand(context["recovery"]["id"], CLAIMS_MANAGER)
        )
        assert promoted["status"] == SUBROGATION_STATE_READY_TO_PURSUE
        assert_cents(
            promoted["recoverable_base_cents"], RAVENNA_TOTAL_CENTS, "recoverable_base_cents"
        )

    def test_the_ceiling_rounds_up_from_the_half_cent_and_caps_the_recovery(
        self, api: ApiClient
    ):
        """499,500.5 becomes 499,501, and 499,502 is one cent too many.

        PRD: "`max_recoverable_cents` is that base multiplied by
        `at_fault_percentage` and divided by 100, rounded half up to a whole cent."
        — "`recovered_amount_cents` must be greater than zero and may not exceed
        the frozen `max_recoverable_cents`; exceeding the ceiling is
        `ERR_RECOVERY_EXCEEDS_BASE`."

        Design: Corner/calculations/subrogation_ceiling_rounds_half_up_at_the_exact_half_cent
        """
        context = _settled_property_claim_with_a_half_cent_ceiling(api)
        settle(api, context["demand"]["id"], settlement_reference="SET-2026-RVN02-0001")
        recovery_id = context["recovery"]["id"]

        promoted = validate_success(api.get_subrogation_demand(recovery_id, CLAIMS_MANAGER))
        assert_cents(
            promoted["max_recoverable_cents"], RAVENNA_CEILING_CENTS, "max_recoverable_cents"
        )
        assert promoted["max_recoverable_cents"] != RAVENNA_BANKERS_ROUNDING_CENTS

        validate_error(
            api.resolve_subrogation_demand(
                recovery_id,
                factories.resolve_subrogation_payload(
                    resolution=SUBROGATION_RESOLUTION_RECOVERED,
                    recovered_amount_cents=RAVENNA_CEILING_CENTS + 1,
                    resolution_note="asking one cent over the ceiling",
                ),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.RECOVERY_EXCEEDS_BASE.value,
            422,
        )
        still_open = validate_success(api.get_subrogation_demand(recovery_id, CLAIMS_MANAGER))
        assert still_open["status"] == SUBROGATION_STATE_READY_TO_PURSUE
        assert still_open["recovered_amount_cents"] is None

        resolved = validate_success(
            api.resolve_subrogation_demand(
                recovery_id,
                factories.resolve_subrogation_payload(
                    resolution=SUBROGATION_RESOLUTION_RECOVERED,
                    recovered_amount_cents=RAVENNA_CEILING_CENTS,
                    resolution_note="paving contractor's carrier paid the ceiling",
                ),
                CLAIMS_MANAGER,
            )
        )
        assert resolved["status"] == SUBROGATION_STATE_RECOVERED
        assert_cents(
            resolved["recovered_amount_cents"], RAVENNA_CEILING_CENTS, "recovered_amount_cents"
        )
        assert_instants_equal(resolved["resolved_at"], CLOCK_EPOCH, "resolved_at")

    def test_the_recovery_lowers_the_incurred_total_without_moving_the_exposure(
        self, api: ApiClient
    ):
        """A receipt against a loss already incurred, not a change in exposure.

        PRD: "it accumulates into `subrogation_recovered_cents` and lowers
        `total_incurred_cents`, which is `indemnity_paid_cents` plus
        `alae_paid_cents` plus `outstanding_reserve_cents` minus
        `subrogation_recovered_cents`, while leaving `claim_exposure_cents`
        untouched."

        Design: Corner/calculations/subrogation_ceiling_rounds_half_up_at_the_exact_half_cent
        """
        context = _settled_property_claim_with_a_half_cent_ceiling(api)
        settle(api, context["demand"]["id"], settlement_reference="SET-2026-RVN02-0001")
        validate_success(
            api.resolve_subrogation_demand(
                context["recovery"]["id"],
                factories.resolve_subrogation_payload(
                    resolution=SUBROGATION_RESOLUTION_RECOVERED,
                    recovered_amount_cents=RAVENNA_CEILING_CENTS,
                    resolution_note="paving contractor's carrier paid the ceiling",
                ),
                CLAIMS_MANAGER,
            )
        )

        claim = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_ADJUSTER))
        assert_cents(claim["indemnity_paid_cents"], RAVENNA_OFFER_CENTS, "indemnity_paid_cents")
        assert_cents(claim["alae_paid_cents"], RAVENNA_ALAE_CENTS, "alae_paid_cents")
        assert_cents(
            claim["outstanding_reserve_cents"],
            RAVENNA_OUTSTANDING_AFTER_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(
            claim["subrogation_recovered_cents"],
            RAVENNA_CEILING_CENTS,
            "subrogation_recovered_cents",
        )
        assert_cents(
            claim["total_incurred_cents"], RAVENNA_INCURRED_CENTS, "total_incurred_cents"
        )
        assert_cents(
            claim["claim_exposure_cents"], MODERATE_RESERVE_CENTS, "claim_exposure_cents"
        )


SANDUSKY_ANNUAL_MILES = 5.0
SANDUSKY_COMMITTEE_SCORE = 3.00
SANDUSKY_SEVERE_POINTS = 8.0
SANDUSKY_CRASH_RATE = 0.200
SANDUSKY_EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-28T04:00:00Z",
    "window_end_at": "2026-07-28T06:00:00Z",
    "retention_deadline_at": "2026-12-31T00:00:00Z",
}
SANDUSKY_CREW = (
    ("D-4402", "Janek Oyelaran", "OH-CDL-4402"),
    ("D-4403", "Kira Petrauskas", "OH-CDL-4403"),
    ("D-4404", "Luka Ferrante", "OH-CDL-4404"),
    ("D-4405", "Mina Sorensen", "OH-CDL-4405"),
)


def _five_driver_terminal_with_one_suspension_due(api: ApiClient) -> dict:
    """Five drivers, one of whom has just earned an out-of-service period."""
    set_clock(api, CLOCK_EPOCH)
    terminal = build_terminal(
        api,
        name="Sandusky Terminal",
        terminal_code="SAN02",
        region_code="OH",
        annual_miles_millions=SANDUSKY_ANNUAL_MILES,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4401",
        full_name="Ilse Nakagawa",
        cdl_number="OH-CDL-4401",
        hire_date="2011-11-11",
    )
    for employee_code, full_name, cdl_number in SANDUSKY_CREW:
        build_driver(
            api,
            terminal["id"],
            employee_code=employee_code,
            full_name=full_name,
            cdl_number=cdl_number,
            hire_date="2011-11-11",
        )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-28T05:00:00Z",
        notified_at="2026-07-28T05:30:00Z",
        location_text="US-250 at Milan Rd",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    photo = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_SCENE_PHOTO,
        source_device_id="PHONE-4401",
        **SANDUSKY_EVIDENCE_WINDOW,
    )
    preserve_evidence(
        api,
        photo["id"],
        preserved_copy_uri="s3://evidence/2923san/scene-4401.jpg",
        evidence_hash="1a1a2b2b3c3c4d4d5e5e6f6f7a7a8b8b",
    )
    telematics = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-4401",
        **SANDUSKY_EVIDENCE_WINDOW,
    )
    purge_evidence(
        api, telematics["id"], purge_reason="ECM buffer overwritten before the hold letter"
    )
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="I rear-ended the queue at the bridge.",
        conditions_note=None,
    )
    case = build_case_in_deliberation(
        api, crash["id"], committee_name="Sandusky Safety Review Committee"
    )
    cast_quorum(
        api,
        case,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(3),
    )
    decided = decide_case(api, case["id"])
    return {"terminal": terminal, "driver": driver, "crash": crash, "review_case": decided}


class TestTheStaffingRatioIsComparedWithoutRounding:
    """One suspended driver of five, and then of six."""

    def test_one_suspended_of_five_is_exactly_the_strained_boundary(
        self, api: ApiClient
    ):
        """Twenty percent lands on the inclusive lower edge, not on critical.

        PRD: "the ratio is `suspended_driver_count` divided by
        `active_driver_count`, evaluated as an exact rational value and never
        rounded: a ratio of one half or more yields `CRITICAL`, a ratio of at
        least one fifth but below one half yields `STRAINED`, and anything lower
        yields `OK`."

        Design: Corner/calculations/staffing_posture_threshold_at_exactly_one_fifth
        """
        context = _five_driver_terminal_with_one_suspension_due(api)
        assert context["review_case"]["determination"] == DETERMINATION_PREVENTABLE
        assert_score_2dp(
            context["review_case"]["committee_score"],
            SANDUSKY_COMMITTEE_SCORE,
            "committee_score",
        )
        before = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert before["staffing_posture"] == STAFFING_POSTURE_OK

        action = build_discipline(
            api,
            context["driver"]["id"],
            context["crash"]["id"],
            action_type=ACTION_TYPE_SUSPENSION,
            action_note="five-day out-of-service",
            suspension_start_at="2026-08-03T00:00:00Z",
            suspension_end_at="2026-08-08T00:00:00Z",
            retraining_course_code="FOLLOWING-101",
        )
        assert action["override_flag"] is False

        after = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert after["active_driver_count"] == 5
        assert after["suspended_driver_count"] == 1
        assert after["staffing_posture"] == STAFFING_POSTURE_STRAINED
        assert after["staffing_posture"] != STAFFING_POSTURE_CRITICAL

    def test_the_two_terminal_ladders_are_scored_independently(self, api: ApiClient):
        """A strained crew and a standard crash rate coexist on one row.

        PRD: "`crash_rate_per_million_miles` is the counted crash total divided by
        the terminal's `annual_miles_millions`, rounded half up to three decimal
        places. `risk_tier` is `CRITICAL` when that rate is 3.000 or greater,
        `ELEVATED` when it is 1.500 or greater but below 3.000, and `STANDARD`
        otherwise."

        Design: Corner/calculations/staffing_posture_threshold_at_exactly_one_fifth
        """
        context = _five_driver_terminal_with_one_suspension_due(api)
        build_discipline(
            api,
            context["driver"]["id"],
            context["crash"]["id"],
            action_type=ACTION_TYPE_SUSPENSION,
            action_note="five-day out-of-service",
            suspension_start_at="2026-08-03T00:00:00Z",
            suspension_end_at="2026-08-08T00:00:00Z",
            retraining_course_code="FOLLOWING-101",
        )

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["preventable_crash_count"] == 1
        assert_rate(
            terminal["crash_rate_per_million_miles"],
            SANDUSKY_CRASH_RATE,
            "crash_rate_per_million_miles",
        )
        assert terminal["risk_tier"] == RISK_TIER_STANDARD
        assert terminal["staffing_posture"] == STAFFING_POSTURE_STRAINED

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_ADMIN))
        assert_points_1dp(
            driver["preventable_points"], SANDUSKY_SEVERE_POINTS, "preventable_points"
        )
        assert driver["status"] == DRIVER_STATUS_SUSPENDED_PENDING_ACTION

    def test_hiring_a_sixth_driver_flips_the_posture_back_without_touching_the_action(
        self, api: ApiClient
    ):
        """One sixth is below one fifth when the comparison is left unrounded.

        PRD: "one suspended driver out of two non-terminated drivers is exactly
        one half and lands on `CRITICAL` at the boundary; one of five is exactly
        one fifth and is `STRAINED`; one of six falls short of one fifth and is
        `OK`." — "The staffing ratio behind `staffing_posture` is the sole
        exception and is compared as an exact rational value without rounding of
        any kind."

        Design: Corner/calculations/staffing_posture_threshold_at_exactly_one_fifth
        """
        context = _five_driver_terminal_with_one_suspension_due(api)
        action = build_discipline(
            api,
            context["driver"]["id"],
            context["crash"]["id"],
            action_type=ACTION_TYPE_SUSPENSION,
            action_note="five-day out-of-service",
            suspension_start_at="2026-08-03T00:00:00Z",
            suspension_end_at="2026-08-08T00:00:00Z",
            retraining_course_code="FOLLOWING-101",
        )

        build_driver(
            api,
            context["terminal"]["id"],
            employee_code="D-4406",
            full_name="Noor Abdellatif",
            cdl_number="OH-CDL-4406",
            hire_date="2026-07-01",
        )

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["active_driver_count"] == 6
        assert terminal["suspended_driver_count"] == 1
        assert terminal["staffing_posture"] == STAFFING_POSTURE_OK

        actions, meta = validate_paginated(
            api.list_disciplinary_actions(
                SAFETY_MANAGER, {"driver_id": context["driver"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert actions[0]["id"] == action["id"]
        assert actions[0]["status"] == ACTION_STATE_ISSUED


TIFFIN_EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-29T22:00:00Z",
    "window_end_at": "2026-07-30T00:00:00Z",
    "retention_deadline_at": "2026-12-31T00:00:00Z",
}
UNCAPPED_CRASH_FACT_SCORE = 90
RAW_SUM_WITH_REPRESENTED_INJURY = 105
SATURATED_MULTIPLIER = 1.60
TIFFIN_GROSS_CENTS = 135_000_000
TIFFIN_FROZEN_RESERVE_CENTS = 216_000_000


def _worst_case_crash_decided_preventable(api: ApiClient) -> dict:
    """Every risk loading the crash facts can carry, on a green driver.

    A fatality, a hazardous-material release, a spoliated record and a driver
    inside his first year all attach to one catastrophic loss.
    """
    set_clock(api, CLOCK_EPOCH)
    terminal = build_terminal(
        api,
        name="Tiffin North Terminal",
        terminal_code="TIF02",
        region_code="OH",
        annual_miles_millions=3.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4501",
        full_name="Oskar Bittencourt",
        cdl_number="OH-CDL-4501",
        hire_date="2026-05-01",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-29T23:00:00Z",
        notified_at="2026-07-29T23:20:00Z",
        location_text="SR-53 at the river bridge",
        severity=SEVERITY_CATASTROPHIC,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
        fatality_count=1,
        hazmat_release=True,
    )
    photo = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_SCENE_PHOTO,
        source_device_id="PHONE-4501",
        **TIFFIN_EVIDENCE_WINDOW,
    )
    preserve_evidence(
        api,
        photo["id"],
        preserved_copy_uri="s3://evidence/2923tif/scene-4501.jpg",
        evidence_hash="2b2b3c3c4d4d5e5e6f6f7a7a8b8b9c9c",
    )
    telematics = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-4501",
        **TIFFIN_EVIDENCE_WINDOW,
    )
    purge_evidence(
        api, telematics["id"], purge_reason="tractor consumed by fire before download"
    )
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="The load shifted entering the bridge.",
        conditions_note=None,
    )
    case = build_case_in_deliberation(
        api, crash["id"], committee_name="Tiffin Safety Review Committee"
    )
    cast_quorum(
        api,
        case,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(3),
    )
    decided = decide_case(api, case["id"])
    return {"terminal": terminal, "driver": driver, "crash": crash, "review_case": decided}


class TestTheRiskLoadingsAccumulateAndThenSaturate:
    """Five loadings sum to ninety, and a sixth is absorbed by the cap."""

    def test_the_crash_facts_alone_load_the_score_to_ninety(self, api: ApiClient):
        """Determination, spoliation, fatality, hazmat and a green driver.

        PRD: "A further 20 points are added when the crash's `fatality_count` is at
        least one, 10 when the crash involved a hazardous-material release, 5 when
        the driver's `tenure_band` currently reads `UNDER_12_MONTHS`" — "1.60 at 80
        or above"

        Design: Corner/calculations/litigation_risk_aggregate_is_capped_at_one_hundred
        """
        context = _worst_case_crash_decided_preventable(api)
        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_ADMIN))
        assert driver["tenure_band"] == TENURE_UNDER_12_MONTHS
        assert context["review_case"]["determination"] == DETERMINATION_PREVENTABLE
        assert context["review_case"]["decision_basis"] == DECISION_BASIS_WEIGHTED_CRITERIA

        claim = build_claim(api, context["crash"]["id"], claimant_notice_date="2026-07-31")

        assert claim["litigation_risk_score"] == UNCAPPED_CRASH_FACT_SCORE
        assert_multiplier(
            claim["litigation_risk_multiplier"],
            SATURATED_MULTIPLIER,
            "litigation_risk_multiplier",
        )
        assert claim["counsel_required"] is True
        assert_cents(
            claim["provisional_reserve_cents"],
            TIFFIN_FROZEN_RESERVE_CENTS,
            "provisional_reserve_cents",
        )

    def test_the_represented_injury_loading_is_absorbed_by_the_cap(self, api: ApiClient):
        """The raw sum of 105 is reported as 100 and the band is already saturated.

        PRD: "15 when the claim carries at least one `THIRD_PARTY_BODILY_INJURY`
        demand whose claimant is `represented_by_counsel`. The sum is then capped
        at 100."

        Design: Corner/calculations/litigation_risk_aggregate_is_capped_at_one_hundred
        """
        context = _worst_case_crash_decided_preventable(api)
        claim = build_claim(api, context["crash"]["id"], claimant_notice_date="2026-07-31")
        build_demand(
            api,
            claim["id"],
            claimant_name="Estate of P. Kowalczyk",
            claimant_type=CLAIMANT_TYPE_BODILY_INJURY,
            demand_amount_cents=400_000_000,
            represented_by_counsel=True,
            demand_received_at="2026-07-31T15:00:00Z",
        )

        after = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))

        assert after["litigation_risk_score"] == RISK_SCORE_CAP
        assert after["litigation_risk_score"] != RAW_SUM_WITH_REPRESENTED_INJURY
        assert_multiplier(
            after["litigation_risk_multiplier"],
            SATURATED_MULTIPLIER,
            "litigation_risk_multiplier",
        )
        assert after["counsel_required"] is True
        assert_cents(
            after["provisional_reserve_cents"],
            TIFFIN_FROZEN_RESERVE_CENTS,
            "provisional_reserve_cents",
        )
        assert (
            TIFFIN_FROZEN_RESERVE_CENTS
            == int(TIFFIN_GROSS_CENTS * 160 / 100)
        )


MINOR_BASE_CENTS = 500_000
MODERATE_BASE_CENTS = 2_500_000
SEVERE_BASE_CENTS = 12_000_000
CATASTROPHIC_BASE_CENTS = 45_000_000
INJURY_UNIT_CENTS = 3_500_000
URBANA_INJURY_COUNT = 2
URBANA_MODERATE_RESERVE_CENTS = 9_500_000
UNGATED_MULTIPLIER = 1.00
PROVISIONAL_FLOOR_CENTS = 250_000
SUB_FLOOR_DEMAND_CENTS = 100_000

URBANA_CRASHES = (
    ("minor", "2026-07-28T08:00:00Z", "2026-07-28T08:10:00Z", "Yard row A", SEVERITY_MINOR, ROUTE_CLASS_LOCAL, 0),
    (
        "moderate",
        "2026-07-28T12:00:00Z",
        "2026-07-28T12:10:00Z",
        "SR-29 at Kenton Rd",
        SEVERITY_MODERATE,
        ROUTE_CLASS_REGIONAL,
        URBANA_INJURY_COUNT,
    ),
    (
        "severe",
        "2026-07-28T16:00:00Z",
        "2026-07-28T16:10:00Z",
        "US-36 at Mad River",
        SEVERITY_SEVERE,
        ROUTE_CLASS_LINEHAUL,
        0,
    ),
    (
        "catastrophic",
        "2026-07-28T20:00:00Z",
        "2026-07-28T20:10:00Z",
        "US-68 at the overpass",
        SEVERITY_CATASTROPHIC,
        ROUTE_CLASS_LINEHAUL,
        0,
    ),
)


def _one_crash_at_every_severity_with_no_evidence(api: ApiClient) -> dict:
    """Four crashes on one driver, none of them holding any evidence at all.

    With no preserved artifact anywhere the posture of each crash is PARTIAL and
    the preventability is still REPORTED, so every claim opened below scores 10
    and takes the unloaded multiplier — which leaves the reserve tiers on show
    unmultiplied.
    """
    terminal = build_terminal(
        api,
        name="Urbana Terminal",
        terminal_code="URB02",
        region_code="OH",
        annual_miles_millions=8.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4601",
        full_name="Petra Vondracek",
        cdl_number="OH-CDL-4601",
        hire_date="2009-09-09",
    )
    crashes = {}
    for key, occurred_at, notified_at, location, severity, route_class, injuries in URBANA_CRASHES:
        crashes[key] = build_crash(
            api,
            driver["id"],
            terminal["id"],
            occurred_at=occurred_at,
            notified_at=notified_at,
            location_text=location,
            severity=severity,
            route_class=route_class,
            tow_away=False,
            tow_reason=TOW_REASON_NONE,
            injury_transported_count=injuries,
            fatality_count=0,
            hazmat_release=False,
            mechanical_factor=False,
            third_party_at_fault=False,
        )
    return {"terminal": terminal, "driver": driver, "crashes": crashes}


def _open_claim(api: ApiClient, crash_id: str) -> dict:
    return build_claim(api, crash_id, claimant_notice_date="2026-07-30")


class TestTheSeverityTiersAndTheProvisionalFloor:
    """One base per tier, an additive injury unit, and a floor only one path reaches."""

    def test_each_tier_base_is_applied_once_and_the_injury_unit_adds_on_top(
        self, api: ApiClient
    ):
        """Four claims differing only in severity expose the four bases.

        PRD: "the gross exposure is the severity base for the crash's `severity` —
        500,000 cents for `MINOR`, 2,500,000 for `MODERATE`, 12,000,000 for
        `SEVERE` and 45,000,000 for `CATASTROPHIC` — plus 3,500,000 cents for each
        person recorded in `injury_transported_count`, plus 90,000,000 cents for
        each fatality recorded in `fatality_count`."

        Design: Corner/calculations/claim_reserve_severity_tiers_injury_units_and_provisional_floor
        """
        context = _one_crash_at_every_severity_with_no_evidence(api)
        claims = {
            key: _open_claim(api, crash["id"])
            for key, crash in context["crashes"].items()
        }

        for key, claim in claims.items():
            assert claim["litigation_risk_score"] == UNGATED_SCORE, key
            assert_multiplier(
                claim["litigation_risk_multiplier"],
                UNGATED_MULTIPLIER,
                f"{key} litigation_risk_multiplier",
            )
            assert claim["counsel_type"] == COUNSEL_TYPE_NONE, key

        assert_cents(
            claims["minor"]["provisional_reserve_cents"],
            MINOR_BASE_CENTS,
            "minor provisional_reserve_cents",
        )
        assert_cents(
            claims["severe"]["provisional_reserve_cents"],
            SEVERE_BASE_CENTS,
            "severe provisional_reserve_cents",
        )
        assert_cents(
            claims["catastrophic"]["provisional_reserve_cents"],
            CATASTROPHIC_BASE_CENTS,
            "catastrophic provisional_reserve_cents",
        )
        assert_cents(
            claims["moderate"]["provisional_reserve_cents"],
            URBANA_MODERATE_RESERVE_CENTS,
            "moderate provisional_reserve_cents",
        )
        assert (
            URBANA_MODERATE_RESERVE_CENTS
            == MODERATE_BASE_CENTS + URBANA_INJURY_COUNT * INJURY_UNIT_CENTS
        )
        assert claims["moderate"]["provisional_reserve_cents"] != MODERATE_BASE_CENTS
        assert claims["moderate"]["provisional_reserve_cents"] != (
            MINOR_BASE_CENTS + MODERATE_BASE_CENTS + URBANA_INJURY_COUNT * INJURY_UNIT_CENTS
        )

        for key, claim in claims.items():
            assert_cents(
                claim["outstanding_reserve_cents"],
                claim["provisional_reserve_cents"],
                f"{key} outstanding_reserve_cents",
            )
            assert claim["revised_reserve_cents"] is None, key
            assert claim["reserve_status"] == RESERVE_STATUS_PROVISIONAL, key

    def test_a_demand_weighted_revision_without_demands_is_refused_then_binds_the_floor(
        self, api: ApiClient
    ):
        """The variant that can reach the floor first insists on a demand.

        PRD: "a `basis` of `DEMAND_BASED` re-bases the estimate on the written
        demands and requires at least one demand to exist on the claim, failing
        with `ERR_NO_DEMANDS_TO_WEIGHT` when none does." And: "The 250,000-cent
        floor never binds under the provisional variant, since the lowest severity
        base already exceeds it; it becomes reachable only through the
        demand-weighted variant on a claim whose demands total less than that."

        Design: Corner/calculations/claim_reserve_severity_tiers_injury_units_and_provisional_floor
        """
        context = _one_crash_at_every_severity_with_no_evidence(api)
        claim = _open_claim(api, context["crashes"]["minor"]["id"])

        validate_error(
            api.revise_reserve(
                claim["id"],
                factories.reserve_revision_payload(
                    claim["version"],
                    basis=RESERVE_BASIS_DEMAND_BASED,
                    revision_note="no demand yet",
                ),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.NO_DEMANDS_TO_WEIGHT.value,
            422,
        )

        untouched = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        assert untouched["reserve_status"] == RESERVE_STATUS_PROVISIONAL
        assert untouched["revised_reserve_cents"] is None
        assert untouched["version"] == claim["version"]
        assert_cents(
            untouched["provisional_reserve_cents"],
            MINOR_BASE_CENTS,
            "provisional_reserve_cents",
        )

        build_demand(
            api,
            claim["id"],
            claimant_name="Champaign Fence Co",
            claimant_type=CLAIMANT_TYPE_PROPERTY,
            demand_amount_cents=SUB_FLOOR_DEMAND_CENTS,
            represented_by_counsel=False,
            demand_received_at="2026-07-31T11:00:00Z",
        )
        observed = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        assert observed["handling_status"] == CLAIM_HANDLING_NEGOTIATION

        floored = revise_reserve(
            api,
            claim["id"],
            observed["version"],
            basis=RESERVE_BASIS_DEMAND_BASED,
            revision_note="single small property demand",
        )

        assert floored["reserve_status"] == RESERVE_STATUS_REVISED
        assert_cents(
            floored["revised_reserve_cents"],
            PROVISIONAL_FLOOR_CENTS,
            "revised_reserve_cents",
        )
        assert floored["revised_reserve_cents"] != SUB_FLOOR_DEMAND_CENTS
        assert_cents(
            floored["outstanding_reserve_cents"],
            PROVISIONAL_FLOOR_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(
            floored["provisional_reserve_cents"],
            MINOR_BASE_CENTS,
            "provisional_reserve_cents",
        )

    def test_the_basis_selects_the_variant_afresh_on_every_call(self, api: ApiClient):
        """A refresh after a demand-weighted revision returns to the severity proxy.

        PRD: "A `basis` of `PROVISIONAL_REFRESH` re-runs the severity estimate at
        the claim's current multiplier and counsel state". And: "resets
        `outstanding_reserve_cents` to `revised_reserve_cents` less
        `indemnity_paid_cents` less `alae_paid_cents`, floored at zero so it never
        goes negative."

        Design: Corner/calculations/claim_reserve_severity_tiers_injury_units_and_provisional_floor
        """
        context = _one_crash_at_every_severity_with_no_evidence(api)
        claim = _open_claim(api, context["crashes"]["minor"]["id"])
        build_demand(
            api,
            claim["id"],
            claimant_name="Champaign Fence Co",
            claimant_type=CLAIMANT_TYPE_PROPERTY,
            demand_amount_cents=SUB_FLOOR_DEMAND_CENTS,
            represented_by_counsel=False,
            demand_received_at="2026-07-31T11:00:00Z",
        )
        observed = validate_success(api.get_claim(claim["id"], CLAIMS_ADJUSTER))
        floored = revise_reserve(
            api,
            claim["id"],
            observed["version"],
            basis=RESERVE_BASIS_DEMAND_BASED,
            revision_note="single small property demand",
        )

        refreshed = revise_reserve(
            api,
            claim["id"],
            floored["version"],
            basis=RESERVE_BASIS_PROVISIONAL_REFRESH,
            revision_note="back to the severity proxy",
        )

        assert_cents(
            refreshed["revised_reserve_cents"], MINOR_BASE_CENTS, "revised_reserve_cents"
        )
        assert refreshed["revised_reserve_cents"] != PROVISIONAL_FLOOR_CENTS
        assert_cents(
            refreshed["outstanding_reserve_cents"],
            MINOR_BASE_CENTS,
            "outstanding_reserve_cents",
        )
        assert refreshed["reserve_status"] == RESERVE_STATUS_REVISED
        assert_cents(refreshed["indemnity_paid_cents"], 0, "indemnity_paid_cents")
        assert_cents(refreshed["alae_paid_cents"], 0, "alae_paid_cents")


VAN_BUREN_CRASH_AT = "2026-07-30T04:00:00Z"
VAN_BUREN_WINDOW = {
    "window_start_at": "2026-07-30T03:00:00Z",
    "window_end_at": "2026-07-30T05:00:00Z",
    "retention_deadline_at": "2027-12-31T00:00:00Z",
}
VAN_BUREN_PHOTO_URI = "s3://evidence/2923vbu/scene-4701.jpg"
VAN_BUREN_PHOTO_HASH = "3c3c4d4d5e5e6f6f7a7a8b8b9c9c0d0d"
CLOCK_AT_365_DAYS = "2027-07-30T04:00:00Z"
CLOCK_AT_730_DAYS = "2028-07-29T04:00:00Z"
MODERATE_POINT_BASE = 4.0
POINTS_WHEN_FRESH = 4.0
POINTS_AT_365_DAYS = 2.0
POINTS_AT_730_DAYS = 0.0
VAN_BUREN_ANNUAL_MILES = 2.0
VAN_BUREN_RATE_IN_WINDOW = 0.500
VAN_BUREN_RATE_OUT_OF_WINDOW = 0.000
VAN_BUREN_COMMITTEE_SCORE = 3.00


def _moderate_crash_decided_preventable_with_a_retraining(api: ApiClient) -> dict:
    """One preventable MODERATE crash and the retraining issued off the back of it.

    The telematics snapshot is purged before any hold, so the crash's posture is
    COMPROMISED and the committee decides on the weighted-criteria basis.
    """
    terminal = build_terminal(
        api,
        name="Van Buren Terminal",
        terminal_code="VBU02",
        region_code="OH",
        annual_miles_millions=VAN_BUREN_ANNUAL_MILES,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4701",
        full_name="Quirin Baumgartner",
        cdl_number="OH-CDL-4701",
        hire_date="2011-01-03",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at=VAN_BUREN_CRASH_AT,
        notified_at="2026-07-30T04:30:00Z",
        location_text="SR-613 at CR-99",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=0,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=False,
    )
    photo = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_SCENE_PHOTO,
        source_device_id="PHONE-4701",
        **VAN_BUREN_WINDOW,
    )
    preserve_evidence(
        api,
        photo["id"],
        preserved_copy_uri=VAN_BUREN_PHOTO_URI,
        evidence_hash=VAN_BUREN_PHOTO_HASH,
    )
    telematics = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-4701",
        **VAN_BUREN_WINDOW,
    )
    purge_evidence(api, telematics["id"], purge_reason="download window missed")
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="I misjudged the gap at the county road.",
        attested=True,
    )
    case = build_case_in_deliberation(
        api, crash["id"], committee_name="Van Buren Safety Review Committee"
    )
    cast_quorum(
        api,
        case,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(3),
    )
    decided = decide_case(api, case["id"])
    action = build_discipline(
        api,
        driver["id"],
        crash["id"],
        action_type=ACTION_TYPE_RETRAINING,
        action_note="gap judgement refresher",
        retraining_course_code="GAP-110",
    )
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "review_case": decided,
        "action": action,
    }


class TestThePointDecayBandsAreHalfOpenOnTheirUpperEdge:
    """Four points fresh, two the day it turns 365, none the day it turns 730."""

    def test_a_fresh_preventable_moderate_crash_carries_its_whole_base(
        self, api: ApiClient
    ):
        """Two days old is squarely inside the undecayed band.

        PRD: "Each contributing crash yields a base figure from its `severity` — 2
        points for a `MINOR` crash, 4 for a `MODERATE` one, 8 for a `SEVERE` one
        and 12 for a `CATASTROPHIC` one — multiplied by a decay factor selected
        from the crash's age. ... A crash fewer than 365 days old keeps its full
        value at a factor of 1.0."

        Design: Corner/calculations/driver_points_decay_at_the_365_and_730_day_edges
        """
        context = _moderate_crash_decided_preventable_with_a_retraining(api)
        assert context["review_case"]["determination"] == DETERMINATION_PREVENTABLE
        assert context["review_case"]["decision_basis"] == DECISION_BASIS_WEIGHTED_CRITERIA
        assert_score_2dp(
            context["review_case"]["committee_score"],
            VAN_BUREN_COMMITTEE_SCORE,
            "committee_score",
        )

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_COMPROMISED

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_MANAGER))
        assert_points_1dp(
            driver["preventable_points"], POINTS_WHEN_FRESH, "preventable_points"
        )
        assert POINTS_WHEN_FRESH == MODERATE_POINT_BASE * 1.0
        assert driver["required_action_tier"] == ACTION_TIER_RETRAINING
        assert driver["status"] == DRIVER_STATUS_RETRAINING_REQUIRED

    def test_at_exactly_365_days_the_crash_is_halved_but_still_inside_the_window(
        self, api: ApiClient
    ):
        """The two ladders part company on the same instant.

        PRD: "One at least 365 days old but fewer than 730 days old is halved, at
        a factor of 0.5. ... The bands are half-open on their upper edge, so a
        crash exactly 365 days old has already aged into the halved band". And:
        "A crash whose `occurred_at` is exactly 365 days old sits on the inclusive
        lower bound and is therefore inside the window".

        Design: Corner/calculations/driver_points_decay_at_the_365_and_730_day_edges
        """
        context = _moderate_crash_decided_preventable_with_a_retraining(api)
        set_clock(api, CLOCK_AT_365_DAYS)

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_MANAGER))
        assert_points_1dp(
            driver["preventable_points"], POINTS_AT_365_DAYS, "preventable_points"
        )
        assert POINTS_AT_365_DAYS == MODERATE_POINT_BASE * 0.5
        assert driver["required_action_tier"] == ACTION_TIER_COACHING
        assert driver["required_action_tier"] != ACTION_TIER_RETRAINING

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["preventable_crash_count"] == 1
        assert_rate(
            terminal["crash_rate_per_million_miles"],
            VAN_BUREN_RATE_IN_WINDOW,
            "crash_rate_per_million_miles",
        )
        assert terminal["risk_tier"] == RISK_TIER_STANDARD

    def test_at_exactly_730_days_the_points_expire_and_the_window_closes(
        self, api: ApiClient
    ):
        """Both ladders reach zero, and the issued action is unmoved by either.

        PRD: "One 730 days old or older contributes nothing, at a factor of 0.0.
        The bands are half-open on their upper edge, so ... one exactly 730 days
        old has already expired."

        Design: Corner/calculations/driver_points_decay_at_the_365_and_730_day_edges
        """
        context = _moderate_crash_decided_preventable_with_a_retraining(api)
        set_clock(api, CLOCK_AT_365_DAYS)
        set_clock(api, CLOCK_AT_730_DAYS)

        driver = validate_success(api.get_driver(context["driver"]["id"], SAFETY_MANAGER))
        assert_points_1dp(
            driver["preventable_points"], POINTS_AT_730_DAYS, "preventable_points"
        )
        assert driver["required_action_tier"] == ACTION_TIER_NONE
        assert driver["status"] == DRIVER_STATUS_RETRAINING_REQUIRED

        terminal = validate_success(api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN))
        assert terminal["preventable_crash_count"] == 0
        assert_rate(
            terminal["crash_rate_per_million_miles"],
            VAN_BUREN_RATE_OUT_OF_WINDOW,
            "crash_rate_per_million_miles",
        )

        action = validate_success(
            api.get_disciplinary_action(context["action"]["id"], SAFETY_MANAGER)
        )
        assert action["status"] == ACTION_STATE_ISSUED
        assert action["retraining_status"] == RETRAINING_STATUS_PENDING
        assert action["action_type"] == ACTION_TYPE_RETRAINING
        assert action["retraining_course_code"] == "GAP-110"


WOOSTER_SIR_LIMIT_CENTS = 10_000_000
WOOSTER_PRIMARY_ATTACHMENT_CENTS = 10_000_000
WOOSTER_PRIMARY_LIMIT_CENTS = 5_000_000
WOOSTER_EXCESS_ATTACHMENT_CENTS = 15_000_000
WOOSTER_EXCESS_LIMIT_CENTS = 20_000_000
WOOSTER_CORRECT_FOURTH_ATTACHMENT_CENTS = 35_000_000
WOOSTER_WRONG_FOURTH_ATTACHMENT_CENTS = 30_000_000
WOOSTER_PROVISIONAL_RESERVE_CENTS = 15_500_000
WOOSTER_OFFER_CENTS = 12_000_000
WOOSTER_ALAE_CENTS = 1_440_000
WOOSTER_TOTAL_CENTS = 13_440_000
WOOSTER_PRIMARY_TAKE_CENTS = 3_440_000
WOOSTER_OUTSTANDING_AFTER_CENTS = 2_060_000
WOOSTER_SETTLEMENT_REFERENCE = "SET-2026-WOO02-0001"


def _severe_claim_against_a_three_layer_tower(api: ApiClient) -> dict:
    """A 15,500,000 reserve, a well-formed 2026 tower and a 12,000,000 offer on the table."""
    terminal = build_terminal(
        api,
        name="Wooster Terminal",
        terminal_code="WOO02",
        region_code="OH",
        annual_miles_millions=4.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-4801",
        full_name="Rasmus Oyelowo",
        cdl_number="OH-CDL-4801",
        hire_date="2010-06-01",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-29T07:00:00Z",
        notified_at="2026-07-29T07:30:00Z",
        location_text="US-250 at Old Airport Rd",
        severity=SEVERITY_SEVERE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=1,
        fatality_count=0,
        hazmat_release=False,
        mechanical_factor=False,
        third_party_at_fault=False,
    )
    retention = build_policy_layer(
        api,
        program_year=2026,
        layer_index=1,
        layer_type=LAYER_KIND_SIR,
        attachment_point_cents=0,
        limit_cents=WOOSTER_SIR_LIMIT_CENTS,
        insurer_name="Self-insured retention",
    )
    primary = build_policy_layer(
        api,
        program_year=2026,
        layer_index=2,
        layer_type=LAYER_KIND_PRIMARY,
        attachment_point_cents=WOOSTER_PRIMARY_ATTACHMENT_CENTS,
        limit_cents=WOOSTER_PRIMARY_LIMIT_CENTS,
        insurer_name="Cuyahoga Casualty",
    )
    excess = build_policy_layer(
        api,
        program_year=2026,
        layer_index=3,
        layer_type=LAYER_KIND_EXCESS,
        attachment_point_cents=WOOSTER_EXCESS_ATTACHMENT_CENTS,
        limit_cents=WOOSTER_EXCESS_LIMIT_CENTS,
        insurer_name="Lakeshore Excess Re",
    )
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-30")
    demand = build_demand(
        api,
        claim["id"],
        claimant_name="Old Airport Logistics",
        claimant_type=CLAIMANT_TYPE_PROPERTY,
        demand_amount_cents=WOOSTER_OFFER_CENTS,
        represented_by_counsel=False,
        demand_received_at="2026-07-31T08:00:00Z",
    )
    round_row = make_offer(api, demand["id"], WOOSTER_OFFER_CENTS)
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "retention": retention,
        "primary": primary,
        "excess": excess,
        "claim": claim,
        "demand": demand,
        "round": round_row,
    }


class TestTheWaterfallStopsAsSoonAsNothingIsLeftToAllocate:
    """The retention fills to the cent, the primary takes the spill, the excess is spared."""

    def test_the_tower_refuses_a_misattached_layer_and_a_reused_index(
        self, api: ApiClient
    ):
        """Neither malformed request is persisted, so the tower stays three deep.

        PRD: "every layer's `attachment_point_cents` must equal the sum of the
        `limit_cents` of all the layers below it in the same program year. A tower
        that violates any of those is `ERR_POLICY_TOWER_MALFORMED`." And:
        "`layer_index` must be at least 1 and is unique within its program year, so
        redeclaring an index is `ERR_POLICY_LAYER_DUPLICATE`."

        Design: Corner/calculations/settlement_waterfall_fills_sir_before_primary_and_spares_excess
        """
        context = _severe_claim_against_a_three_layer_tower(api)
        assert_cents(
            context["claim"]["outstanding_reserve_cents"],
            WOOSTER_PROVISIONAL_RESERVE_CENTS,
            "outstanding_reserve_cents",
        )
        assert_cents(
            context["claim"]["claim_exposure_cents"],
            WOOSTER_PROVISIONAL_RESERVE_CENTS,
            "claim_exposure_cents",
        )
        assert (
            WOOSTER_CORRECT_FOURTH_ATTACHMENT_CENTS
            == WOOSTER_SIR_LIMIT_CENTS
            + WOOSTER_PRIMARY_LIMIT_CENTS
            + WOOSTER_EXCESS_LIMIT_CENTS
        )

        validate_error(
            api.create_policy_layer(
                factories.policy_layer_payload(
                    program_year=2026,
                    layer_index=4,
                    layer_type=LAYER_KIND_EXCESS,
                    attachment_point_cents=WOOSTER_WRONG_FOURTH_ATTACHMENT_CENTS,
                    limit_cents=10_000_000,
                    insurer_name="Misattached Excess Co",
                ),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.POLICY_TOWER_MALFORMED.value,
            409,
        )
        validate_error(
            api.create_policy_layer(
                factories.policy_layer_payload(
                    program_year=2026,
                    layer_index=2,
                    layer_type=LAYER_KIND_PRIMARY,
                    attachment_point_cents=WOOSTER_PRIMARY_ATTACHMENT_CENTS,
                    limit_cents=WOOSTER_PRIMARY_LIMIT_CENTS,
                    insurer_name="Duplicate Primary Mutual",
                ),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.POLICY_LAYER_DUPLICATE.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_policy_layers(CLAIMS_MANAGER, {"program_year": 2026})
        )
        assert meta["total_count"] == 3
        assert [row["layer_index"] for row in rows] == [1, 2, 3]
        assert [row["insurer_name"] for row in rows] == [
            "Self-insured retention",
            "Cuyahoga Casualty",
            "Lakeshore Excess Re",
        ]

    def test_the_settlement_total_fills_the_retention_then_spills_into_the_primary(
        self, api: ApiClient
    ):
        """Exactly two allocation rows, and the excess layer is never named.

        PRD: "taken in ascending `layer_index` order so the retention is consumed
        before the primary and the primary before each excess layer. ... the take
        is the lesser of the amount still unallocated and that remaining capacity.
        When the take is greater than zero, an allocation entry recording
        `policy_layer_id`, `layer_index`, `layer_type` and `allocated_cents` is
        produced, the unallocated amount falls by the take, and the walk stops as
        soon as nothing is left to allocate."

        Design: Corner/calculations/settlement_waterfall_fills_sir_before_primary_and_spares_excess
        """
        context = _severe_claim_against_a_three_layer_tower(api)

        settled = settle(
            api,
            context["demand"]["id"],
            settlement_reference=WOOSTER_SETTLEMENT_REFERENCE,
        )

        assert settled["status"] == DEMAND_STATE_SETTLED
        assert_cents(
            settled["settled_amount_cents"], WOOSTER_OFFER_CENTS, "settled_amount_cents"
        )
        assert_cents(settled["alae_cents"], WOOSTER_ALAE_CENTS, "alae_cents")
        assert_cents(
            settled["settlement_total_cents"], WOOSTER_TOTAL_CENTS, "settlement_total_cents"
        )
        assert WOOSTER_ALAE_CENTS == int(WOOSTER_OFFER_CENTS * 12 / 100)

        claim = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_MANAGER))
        allocations = claim["layer_allocations"]
        assert len(allocations) == 2
        assert [entry["layer_index"] for entry in allocations] == [1, 2]
        assert allocations[0]["policy_layer_id"] == context["retention"]["id"]
        assert allocations[0]["layer_type"] == LAYER_KIND_SIR
        assert_cents(
            allocations[0]["allocated_cents"],
            WOOSTER_SIR_LIMIT_CENTS,
            "retention allocated_cents",
        )
        assert allocations[1]["policy_layer_id"] == context["primary"]["id"]
        assert allocations[1]["layer_type"] == LAYER_KIND_PRIMARY
        assert_cents(
            allocations[1]["allocated_cents"],
            WOOSTER_PRIMARY_TAKE_CENTS,
            "primary allocated_cents",
        )
        assert all(
            entry["policy_layer_id"] != context["excess"]["id"] for entry in allocations
        )
        assert LAYER_KIND_EXCESS not in [entry["layer_type"] for entry in allocations]
        assert (
            WOOSTER_SIR_LIMIT_CENTS + WOOSTER_PRIMARY_TAKE_CENTS == WOOSTER_TOTAL_CENTS
        )

    def test_the_split_by_layer_type_moves_cents_between_buckets_without_creating_them(
        self, api: ApiClient
    ):
        """Retention erosion and insured payment are separated, exposure is conserved.

        PRD: "increases `sir_eroded_cents` by the allocations to the `SIR` layer
        and `insured_paid_cents` by the allocations to `PRIMARY` and `EXCESS`
        layers"

        Design: Corner/calculations/settlement_waterfall_fills_sir_before_primary_and_spares_excess
        """
        context = _severe_claim_against_a_three_layer_tower(api)
        settle(
            api,
            context["demand"]["id"],
            settlement_reference=WOOSTER_SETTLEMENT_REFERENCE,
        )

        claim = validate_success(api.get_claim(context["claim"]["id"], CLAIMS_MANAGER))
        assert claim["handling_status"] == CLAIM_HANDLING_SETTLEMENT_COMPLETE
        assert_cents(
            claim["sir_eroded_cents"], WOOSTER_SIR_LIMIT_CENTS, "sir_eroded_cents"
        )
        assert_cents(
            claim["insured_paid_cents"], WOOSTER_PRIMARY_TAKE_CENTS, "insured_paid_cents"
        )
        assert_cents(
            claim["indemnity_paid_cents"], WOOSTER_OFFER_CENTS, "indemnity_paid_cents"
        )
        assert_cents(claim["alae_paid_cents"], WOOSTER_ALAE_CENTS, "alae_paid_cents")
        assert_cents(
            claim["outstanding_reserve_cents"],
            WOOSTER_OUTSTANDING_AFTER_CENTS,
            "outstanding_reserve_cents",
        )
        assert (
            WOOSTER_OUTSTANDING_AFTER_CENTS
            == WOOSTER_PROVISIONAL_RESERVE_CENTS - WOOSTER_TOTAL_CENTS
        )
        assert_cents(
            claim["claim_exposure_cents"],
            WOOSTER_PROVISIONAL_RESERVE_CENTS,
            "claim_exposure_cents",
        )
        assert_cents(
            claim["total_incurred_cents"],
            WOOSTER_PROVISIONAL_RESERVE_CENTS,
            "total_incurred_cents",
        )

        rounds, meta = validate_paginated(
            api.list_negotiation_rounds(context["demand"]["id"], CLAIMS_MANAGER)
        )
        assert meta["total_count"] == 1
        assert rounds[0]["id"] == context["round"]["id"]
        assert rounds[0]["outcome"] == ROUND_OUTCOME_ACCEPTED
        assert_cents(
            rounds[0]["carrier_offer_cents"], WOOSTER_OFFER_CENTS, "carrier_offer_cents"
        )
