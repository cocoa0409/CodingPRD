"""User fees, board governance, and the migration-readiness projection.

Every test in this module translates exactly one design instance and carries a
verbatim PRD citation for the rule it pins.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_FEE_PERIOD_INVALID,
    ERR_PAYMENT_EXCEEDS_BALANCE,
    ERR_STALE_VERSION,
)
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_instant_equals,
    assert_nulls,
    assert_one_decimal_place,
    assert_pct,
)
from test_helpers.constants import (
    ACTION_RETIRE,
    AGENCY_TYPE_EMS,
    AGENCY_TYPE_FIRE,
    AGENCY_TYPE_LAW,
    AGENCY_TYPE_PUBLIC_WORKS,
    BASIS_PLANNED,
    BASIS_STRICT,
    BILLING_CURRENT,
    CR_APPROVED,
    FEE_BASIS_PRORATED,
    FEE_BASIS_SNAPSHOT,
    INTEROP_MONITOR,
    KEY_KEYLESS,
    MODEL_MOBILE,
    MODEL_PORTABLE,
    PROVISION_ASSIGNED,
    PROVISION_INVENTORY,
    PROVISION_RETIRED,
    STANDARD_NG_LMR,
    STANDARD_P25_PHASE1,
    TIER_1_RATE_CENTS,
)
from test_helpers.test_users import SYSTEM_ADMIN, make_agency_radio_manager_headers


def _fee_ledger_is_settled(agency, assessed: int, paid: int):
    """The money identity the ledger must satisfy after every fiscal write:
    `fee_balance_cents == lifetime_assessed_cents - lifetime_paid_cents`."""
    assert_cents(agency["lifetime_assessed_cents"], assessed, "lifetime_assessed_cents")
    assert_cents(agency["lifetime_paid_cents"], paid, "lifetime_paid_cents")
    assert_cents(agency["fee_balance_cents"], assessed - paid, "fee_balance_cents")
    assert (
        agency["fee_balance_cents"]
        == agency["lifetime_assessed_cents"] - agency["lifetime_paid_cents"]
    ), "the ledger identity must hold exactly"


def test_fee_assessment_counts_only_assigned_and_suspended_radios(
    api: ApiClient, clock_at_start: str
):
    """Three radios, one billable: the `SNAPSHOT` headcount takes only the
    `ASSIGNED` and `SUSPENDED` rows, so a fleet of one assigned, one still in
    inventory and one retired is billed 4,200 cents rather than 12,600.

    PRD 3.9: "The headcount is the number of that agency's subscriber units whose
    current `provision_status` is `ASSIGNED` or `SUSPENDED`; units in `INVENTORY`
    or `RETIRED` are excluded outright."

    PRD 3.9: "`last_assessed_fee_cents` is set to the total assessed amount;
    `lifetime_assessed_cents` has that amount added to it; `fee_balance_cents` is
    then recomputed as `lifetime_assessed_cents` less `lifetime_paid_cents`;
    `last_assessment_period_start` and `last_assessment_period_end` record the
    period just assessed; and `payment_due_at` is set to `period_end` plus a
    30-day payment grace."

    Design: Corner/calculations/fee_assessment_input_set_excludes_inventory_and_retired_units
    """
    agency = fx.register_agency(
        api,
        name="Filtered Fleet Agency",
        agency_code="FLT01",
        agency_type=AGENCY_TYPE_EMS,
        fee_basis=FEE_BASIS_SNAPSHOT,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="FLT-BASE-1",
        target_standard=STANDARD_P25_PHASE1,
        talkgroup_slot_count=4,
    )
    billable = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="FLT0001",
        radio_id=27001,
        model=MODEL_PORTABLE,
    )
    stock = fx.add_unit(
        api,
        agency["id"],
        serial_number="FLT0002",
        radio_id=27002,
        model=MODEL_PORTABLE,
    )
    retired = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="FLT0003",
        radio_id=27003,
        model=MODEL_MOBILE,
    )
    retired = fx.lifecycle(api, retired["id"], agency["id"], ACTION_RETIRE)

    assert_fields(fx.read_unit(api, billable["id"]), provision_status=PROVISION_ASSIGNED)
    assert_fields(fx.read_unit(api, stock["id"]), provision_status=PROVISION_INVENTORY)
    assert_fields(fx.read_unit(api, retired["id"]), provision_status=PROVISION_RETIRED)

    fx.assess_fees(api, agency["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")

    billed = fx.read_agency(api, agency["id"])
    assert_fields(billed, billable_subscriber_count=1, billing_status=BILLING_CURRENT)
    assert_cents(
        billed["last_assessed_fee_cents"], TIER_1_RATE_CENTS, "last_assessed_fee_cents"
    )
    assert billed["last_assessed_fee_cents"] != 3 * TIER_1_RATE_CENTS, (
        "the inventory and retired radios must not be billed"
    )
    _fee_ledger_is_settled(billed, TIER_1_RATE_CENTS, 0)

    assert_instant_equals(
        billed["last_assessment_period_start"], "2026-07-01T00:00:00Z", "period_start"
    )
    assert_instant_equals(
        billed["last_assessment_period_end"], "2026-08-01T00:00:00Z", "period_end"
    )
    assert_instant_equals(
        billed["payment_due_at"], "2026-08-31T00:00:00Z", "payment_due_at"
    )


def test_governance_standing_reports_board_weight_and_quorum_threshold(
    api: ApiClient, clock_at_start: str
):
    """An empty fleet still carries one vote, so a three-agency register weighs
    three eligible votes and the quorum threshold is three fifths of that rounded
    up — two, not the 1.8 the arithmetic produces.

    PRD 3.9: "Every other agency is `voting_eligible` and its weight is one vote
    plus one additional vote for each complete block of 250 billable subscribers —
    the block count is the billable subscriber count divided by 250 with any
    fraction discarded downward — with the whole figure capped at 5 votes."

    PRD 3.9: "The board-level standing read reports the requested agency's
    `agency_id`, `billing_status`, `billable_subscriber_count`,
    `governance_vote_weight`, and `voting_eligible`, and alongside them two
    aggregates computed across the entire register: `total_eligible_weight`, the
    sum of `governance_vote_weight` over every agency whose `voting_eligible` is
    true (ineligible agencies contribute nothing and are excluded from the sum
    entirely), and `quorum_weight_required`, which is three fifths of
    `total_eligible_weight` rounded **up** to the next whole vote."

    Design: Corner/calculations/governance_standing_read_reports_board_weight_and_quorum
    """
    first = fx.register_agency(
        api,
        name="Quorum Agency One",
        agency_code="QRM01",
        agency_type=AGENCY_TYPE_LAW,
        recorder_retention_days=180,
    )
    fx.register_agency(
        api,
        name="Quorum Agency Two",
        agency_code="QRM02",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    fx.register_agency(
        api,
        name="Quorum Agency Three",
        agency_code="QRM03",
        agency_type=AGENCY_TYPE_PUBLIC_WORKS,
        recorder_retention_days=30,
    )

    standing = validate_success(
        api.get_governance_standing(first["id"], SYSTEM_ADMIN), 200
    )
    assert_fields(
        standing,
        agency_id=first["id"],
        billing_status=BILLING_CURRENT,
        billable_subscriber_count=0,
        governance_vote_weight=1,
        voting_eligible=True,
        total_eligible_weight=3,
        quorum_weight_required=2,
    )


def test_fee_period_longer_than_366_days_rejected(api: ApiClient, clock_at_start: str):
    """A 577-day billing period is refused for length alone — the version pin is
    current and the clock is not the problem — and a 365-day period ending at the
    same instant is accepted, which isolates the refusal to the cap.

    PRD 3.9: "The period itself is validated before anything is computed:
    `period_end` must be strictly after `period_start`, the period may not be
    longer than 366 days, and `period_end` may not lie after the current logical
    clock instant — an authority cannot bill for the future."

    PRD 3.9: "Any of those three failures is rejected with
    `ERR_FEE_PERIOD_INVALID`."

    PRD 3.1: "Its `last_assessment_period_start`, `last_assessment_period_end`,
    and `payment_due_at` are all null until the first assessment is booked."

    Design: Corner/validations/fee_period_longer_than_366_days_rejected
    """
    agency = fx.register_agency(
        api,
        name="Long Period Agency",
        agency_code="LNG01",
        agency_type=AGENCY_TYPE_PUBLIC_WORKS,
        recorder_retention_days=30,
    )
    version_at_registration = agency["version"]

    refused = api.create_fee_assessment(
        agency["id"],
        f.fee_assessment_payload(
            "2025-01-01T00:00:00Z", "2026-08-01T00:00:00Z", version_at_registration
        ),
        SYSTEM_ADMIN,
    )
    validate_error(refused, ERR_FEE_PERIOD_INVALID, 422)

    untouched = fx.read_agency(api, agency["id"])
    assert_cents(untouched["last_assessed_fee_cents"], 0, "last_assessed_fee_cents")
    _fee_ledger_is_settled(untouched, 0, 0)
    assert_nulls(
        untouched,
        "payment_due_at",
        "last_assessment_period_start",
        "last_assessment_period_end",
    )
    assert untouched["version"] == version_at_registration, (
        "a rejected assessment must not bump the agency version"
    )

    # 2025-08-01 to 2026-08-01 is 365 days, one inside the cap.
    fx.assess_fees(api, agency["id"], "2025-08-01T00:00:00Z", "2026-08-01T00:00:00Z")
    booked = fx.read_agency(api, agency["id"])
    assert_instant_equals(
        booked["last_assessment_period_start"], "2025-08-01T00:00:00Z", "period_start"
    )
    assert booked["version"] == version_at_registration + 1, (
        "the accepted assessment must bump the agency version exactly once"
    )


def test_payment_against_a_never_assessed_agency_is_refused(
    api: ApiClient, clock_at_start: str
):
    """Nothing is owed, so nothing may be paid: a 5,000-cent payment against a
    zero balance is refused outright rather than driving the ledger negative.

    PRD 3.9: "A payment names `amount_cents`, which must be at least 1 and must
    not exceed the agency's current `fee_balance_cents`; a payment below one cent
    or larger than the outstanding balance is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."

    PRD 3.1: "Its `billable_subscriber_count`, `last_assessed_fee_cents`,
    `fee_balance_cents`, `lifetime_assessed_cents`, `lifetime_paid_cents`, and
    `active_patch_request_count` all open at 0."

    Design: Corner/errors/error_payment_exceeds_balance_on_unassessed_agency
    """
    agency = fx.register_agency(
        api,
        name="Overpayment Agency",
        agency_code="PAY01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    version_at_registration = agency["version"]
    _fee_ledger_is_settled(agency, 0, 0)

    refused = api.create_payment(
        agency["id"],
        f.payment_payload(5000),
        make_agency_radio_manager_headers(agency["id"]),
    )
    validate_error(refused, ERR_PAYMENT_EXCEEDS_BALANCE, 422)

    unchanged = fx.read_agency(api, agency["id"])
    _fee_ledger_is_settled(unchanged, 0, 0)
    assert_fields(unchanged, billing_status=BILLING_CURRENT)
    assert unchanged["version"] == version_at_registration, (
        "a rejected payment must not bump the agency version"
    )


def test_migration_readiness_reports_zero_for_an_empty_scope(
    api: ApiClient, clock_at_start: str
):
    """A radio still in inventory is outside the projection's scope under both
    bases, so the denominator is zero and the percentage is reported as exactly
    0.0 rather than blowing up or defaulting to a full hundred.

    PRD 3.9: "The evaluation scope is every subscriber unit whose
    `provision_status` is `ASSIGNED` or `SUSPENDED`, optionally narrowed to a
    single agency by an `agency_id` filter; units in `INVENTORY` or `RETIRED` are
    excluded from both the numerator and the denominator."

    PRD 3.9: "The count of ready units is reported as `ready_unit_count`, and
    `readiness_pct` is one hundred multiplied by `ready_unit_count` divided by
    `evaluated_unit_count`, rounded half up to one decimal place — and exactly 0.0
    when the scope is empty."

    PRD 3.9: "A `basis` query parameter selects between two readiness definitions,
    and it defaults to `STRICT` when omitted."

    Design: Corner/endpoints/migration_readiness_computed_read_reports_zero_for_empty_scope
    """
    agency = fx.register_agency(
        api,
        name="Migration Empty Agency",
        agency_code="MIG01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    stock = fx.add_unit(
        api,
        agency["id"],
        serial_number="MIG0001",
        radio_id=35001,
        model=MODEL_PORTABLE,
    )
    assert_fields(stock, provision_status=PROVISION_INVENTORY)

    # No basis parameter at all: the default must be STRICT.
    defaulted = validate_success(
        api.get_migration_readiness(SYSTEM_ADMIN, {"agency_id": agency["id"]}), 200
    )
    assert_fields(
        defaulted,
        basis=BASIS_STRICT,
        agency_id=agency["id"],
        evaluated_unit_count=0,
        ready_unit_count=0,
    )
    assert_pct(defaulted["readiness_pct"], 0.0, "readiness_pct")
    assert_one_decimal_place(defaulted["readiness_pct"], "readiness_pct")

    planned = validate_success(
        api.get_migration_readiness(
            SYSTEM_ADMIN, {"agency_id": agency["id"], "basis": BASIS_PLANNED}
        ),
        200,
    )
    assert_fields(
        planned,
        basis=BASIS_PLANNED,
        agency_id=agency["id"],
        evaluated_unit_count=0,
        ready_unit_count=0,
    )
    assert_pct(planned["readiness_pct"], 0.0, "readiness_pct")

    # A read-only projection: the inventory radio is exactly where it was.
    assert_fields(
        fx.read_unit(api, stock["id"]), provision_status=PROVISION_INVENTORY
    )


def _alpha_and_bravo_identical_fleets(api: ApiClient):
    """Two agencies differing in exactly one input — `fee_basis` — each owning
    three radios assigned on `2026-07-21T00:00:00Z`.

    The fleets are built while the logical clock is parked at
    `2026-07-21T00:00:00Z` so that every `assigned_at` lands on that instant,
    then the clock is advanced to `2026-08-01T00:00:00Z` so the July period may
    legally be billed. Returns ``(agency_a, agency_b, units_a, units_b)``.
    """
    fx.set_clock(api, "2026-07-21T00:00:00Z")
    agency_a = fx.register_agency(
        api,
        name="Alpha County Sheriff",
        agency_code="LAWA1",
        agency_type=AGENCY_TYPE_LAW,
        fee_basis=FEE_BASIS_SNAPSHOT,
        interop_privilege=INTEROP_MONITOR,
        recorder_retention_days=180,
    )
    agency_b = fx.register_agency(
        api,
        name="Bravo County Sheriff",
        agency_code="LAWB1",
        agency_type=AGENCY_TYPE_LAW,
        fee_basis=FEE_BASIS_PRORATED,
        interop_privilege=INTEROP_MONITOR,
        recorder_retention_days=180,
    )
    template = fx.published_template(
        api,
        template_name="REGION-BASE-1",
        target_standard=STANDARD_P25_PHASE1,
        talkgroup_slot_count=8,
        encryption_required=False,
    )

    def _three(agency_id: str, serial_prefix: str, first_radio_id: int):
        rows = []
        for index, model in enumerate((MODEL_PORTABLE, MODEL_PORTABLE, MODEL_MOBILE)):
            rows.append(
                fx.assigned_unit(
                    api,
                    agency_id,
                    template["id"],
                    serial_number=f"{serial_prefix}{index + 1:03d}",
                    radio_id=first_radio_id + index,
                    model=model,
                )
            )
        return rows

    units_a = _three(agency_a["id"], "SNA", 1001)
    units_b = _three(agency_b["id"], "SNB", 2001)
    for row in units_a + units_b:
        assert_fields(row, provision_status=PROVISION_ASSIGNED, key_status=KEY_KEYLESS)
        assert_instant_equals(row["assigned_at"], "2026-07-21T00:00:00Z", "assigned_at")

    fx.set_clock(api, "2026-08-01T00:00:00Z")
    return agency_a, agency_b, units_a, units_b


def test_fee_basis_snapshot_and_prorated_diverge_on_identical_fleets(
    api: ApiClient, clock_at_start: str
):
    """Two byte-identical three-radio fleets, one billing period, two totals: the
    `SNAPSHOT` variant charges a full period per head and books 12,600 cents while
    `PRORATED` weights each head by its eleven days in service and books 4,470 —
    a divergence of 8,130 cents produced by one input field.

    PRD 3.9: "Under both variants the rate schedule is the same three-tier ladder:
    the first 50 billable positions are charged at 4,200 cents each, positions 51
    through 200 at 3,600 cents each, and every position beyond 200 at 3,100 cents
    each."

    PRD 3.9: "Under this variant every billable radio pays for a full period
    regardless of when it entered service, and the rounding happens per tier."

    PRD 3.9: "For the same fleet, this variant yields a strictly smaller — and
    differently rounded — total than `SNAPSHOT` whenever any unit was in service
    for fewer days than the full period."

    Design: Difficulty/dual_variant_calc/fee_basis_snapshot_versus_prorated_diverge_on_identical_fleets
    """
    agency_a, agency_b, _units_a, _units_b = _alpha_and_bravo_identical_fleets(api)
    assert_fields(agency_a, fee_basis=FEE_BASIS_SNAPSHOT)
    assert_fields(agency_b, fee_basis=FEE_BASIS_PRORATED)

    fx.assess_fees(api, agency_a["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    fx.assess_fees(api, agency_b["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")

    snapshot = fx.read_agency(api, agency_a["id"])
    prorated = fx.read_agency(api, agency_b["id"])

    # 3 heads x 4,200 cents, no surcharge at MONITOR and no late fee on a clean
    # ledger.
    assert_cents(
        snapshot["last_assessed_fee_cents"], 12600, "SNAPSHOT last_assessed_fee_cents"
    )
    # 3 x round_half_up(4200 * 11 / 31) == 3 x 1490.
    assert_cents(
        prorated["last_assessed_fee_cents"], 4470, "PRORATED last_assessed_fee_cents"
    )
    assert (
        snapshot["last_assessed_fee_cents"] - prorated["last_assessed_fee_cents"] == 8130
    ), "the two variants must diverge by exactly 8130 cents"
    assert prorated["last_assessed_fee_cents"] < snapshot["last_assessed_fee_cents"], (
        "PRORATED must be strictly smaller for a part-period fleet"
    )
    assert_fields(
        snapshot, billable_subscriber_count=3, interop_privilege=INTEROP_MONITOR
    )
    assert_fields(
        prorated, billable_subscriber_count=3, interop_privilege=INTEROP_MONITOR
    )


def test_fee_basis_divergence_settles_both_ledgers_and_the_day_counts(
    api: ApiClient, clock_at_start: str
):
    """The two divergent totals land in two consistent ledgers, and the prorated
    agency's radios each carry the eleven-day figure the arithmetic used — the day
    count is written back onto the fleet, not just consumed in passing.

    PRD 3.9: "The same day-counting rule is what writes
    `days_in_service_last_period` onto each subscriber unit."

    PRD 3.9: "Each candidate's days in service is the number of whole UTC days
    inside the half-open period for which the radio was billable: a day counts
    when the unit's `assigned_at` is not null, `assigned_at` falls at or before
    midnight UTC beginning that day, and either `retired_at` is null or
    `retired_at` falls strictly after that same midnight."

    PRD 3.9: "In every remaining case — including an outstanding balance with no
    due date yet recorded — the target status is `CURRENT`."

    Design: Difficulty/dual_variant_calc/fee_basis_snapshot_versus_prorated_diverge_on_identical_fleets
    """
    agency_a, agency_b, units_a, units_b = _alpha_and_bravo_identical_fleets(api)

    fx.assess_fees(api, agency_a["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    fx.assess_fees(api, agency_b["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")

    snapshot = fx.read_agency(api, agency_a["id"])
    prorated = fx.read_agency(api, agency_b["id"])
    _fee_ledger_is_settled(snapshot, 12600, 0)
    _fee_ledger_is_settled(prorated, 4470, 0)

    for billed in (snapshot, prorated):
        assert_fields(billed, billing_status=BILLING_CURRENT)
        assert_instant_equals(
            billed["payment_due_at"], "2026-08-31T00:00:00Z", "payment_due_at"
        )

    # July 21 through July 31 inclusive is eleven whole billable days inside the
    # half-open period, and both fleets get the field written back.
    for row in units_a + units_b:
        assert_fields(fx.read_unit(api, row["id"]), days_in_service_last_period=11)


def _charlie_planned_migration_fleet(api: ApiClient):
    """Agency C with two `ASSIGNED`, `KEYLESS` radios still programmed to a
    legacy `P25_PHASE1` template, plus one `APPROVED` change request pinning an
    `NG_LMR` template that has deliberately NOT been deployed.

    Returns ``(agency, legacy_template, nextgen_template, units, change_request)``
    with the logical clock at `2026-08-01T00:00:00Z`.
    """
    agency = fx.register_agency(
        api,
        name="Charlie Fire District",
        agency_code="FIRC1",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    legacy = fx.published_template(
        api,
        template_name="LEGACY-P1",
        target_standard=STANDARD_P25_PHASE1,
        talkgroup_slot_count=8,
    )
    nextgen = fx.published_template(
        api,
        template_name="NEXTGEN-NG1",
        target_standard=STANDARD_NG_LMR,
        talkgroup_slot_count=16,
    )
    units = [
        fx.assigned_unit(
            api,
            agency["id"],
            legacy["id"],
            serial_number="SNC001",
            radio_id=3001,
            model=MODEL_PORTABLE,
        ),
        fx.assigned_unit(
            api,
            agency["id"],
            legacy["id"],
            serial_number="SNC002",
            radio_id=3002,
            model=MODEL_MOBILE,
        ),
    ]
    for row in units:
        assert_fields(
            row,
            provision_status=PROVISION_ASSIGNED,
            key_status=KEY_KEYLESS,
            template_id=legacy["id"],
        )

    change_request = fx.approved_change_request(
        api, nextgen["id"], agency["id"], title="Cut Charlie fleet to NG_LMR"
    )
    assert_fields(change_request, status=CR_APPROVED)
    return agency, legacy, nextgen, units, change_request


def test_migration_readiness_strict_and_planned_diverge_on_one_fleet(
    api: ApiClient, clock_at_start: str
):
    """One unchanged fleet, two readiness definitions, opposite answers: `STRICT`
    sees two keyless radios on a legacy codeplug and reports 0.0 per cent, while
    `PLANNED` credits the approved next-generation change request and reports
    100.0 per cent.

    PRD 3.9: "Under the `STRICT` basis a unit counts as ready only when its own
    `provision_status` is `ASSIGNED`, its `key_status` is `KEYED`, its
    `template_id` is not null, and the programming template it names has a
    `target_standard` of `P25_PHASE2` or `NG_LMR` — that is, the radio already
    carries a live key and a next-generation codeplug."

    PRD 3.9: "Under the `PLANNED` basis a unit counts as ready when it satisfies
    the strict definition, or, additionally, when its `provision_status` is
    `ASSIGNED` and its owning agency has at least one programming change request
    whose `status` is `APPROVED` or `DEPLOYING` and whose template's
    `target_standard` is `P25_PHASE2` or `NG_LMR` — such radios count even though
    they are still programmed to `P25_PHASE1` and may still be `KEYLESS`."

    PRD 3.9: "For the same fleet the `PLANNED` basis therefore yields a strictly
    higher percentage whenever such a change request exists."

    Design: Difficulty/dual_variant_calc/migration_readiness_strict_versus_planned_diverge_on_identical_fleet
    """
    agency, _legacy, _nextgen, _units, _change_request = _charlie_planned_migration_fleet(
        api
    )

    strict = validate_success(
        api.get_migration_readiness(
            SYSTEM_ADMIN, {"agency_id": agency["id"], "basis": BASIS_STRICT}
        ),
        200,
    )
    assert_fields(
        strict, basis=BASIS_STRICT, evaluated_unit_count=2, ready_unit_count=0
    )
    assert_pct(strict["readiness_pct"], 0.0, "STRICT readiness_pct")

    planned = validate_success(
        api.get_migration_readiness(
            SYSTEM_ADMIN, {"agency_id": agency["id"], "basis": BASIS_PLANNED}
        ),
        200,
    )
    assert_fields(
        planned, basis=BASIS_PLANNED, evaluated_unit_count=2, ready_unit_count=2
    )
    assert_pct(planned["readiness_pct"], 100.0, "PLANNED readiness_pct")

    assert planned["readiness_pct"] > strict["readiness_pct"], (
        "PLANNED must be strictly higher while an approved NG change request exists"
    )
    assert planned["evaluated_unit_count"] == strict["evaluated_unit_count"], (
        "the two bases must share one denominator"
    )


def test_migration_readiness_reads_change_nothing_about_the_fleet(
    api: ApiClient, clock_at_start: str
):
    """The projection is a read: after both bases have been queried the radios are
    still on the legacy template, the change request is still merely `APPROVED`,
    and the snapshots frozen at approval are exactly as they were.

    PRD 3.9: "**Migration readiness** is a read-only projection that writes
    nothing, and it answers the authority's planning question: how much of the
    fleet could move to a next-generation air interface today."

    PRD 3.3: "On approval three snapshots are taken and frozen:
    `pinned_template_version` captures the template's lineage number
    `template_version`; `pinned_template_record_version` captures the template
    row's mutation counter `version`; and `target_unit_count` captures the number
    of that target agency's subscriber units whose `provision_status` is
    `ASSIGNED` or `SUSPENDED` at that instant."

    Design: Difficulty/dual_variant_calc/migration_readiness_strict_versus_planned_diverge_on_identical_fleet
    """
    agency, legacy, _nextgen, units, change_request = _charlie_planned_migration_fleet(
        api
    )
    versions_before = {row["id"]: fx.read_unit(api, row["id"])["version"] for row in units}

    for basis in (BASIS_STRICT, BASIS_PLANNED):
        validate_success(
            api.get_migration_readiness(
                SYSTEM_ADMIN, {"agency_id": agency["id"], "basis": basis}
            ),
            200,
        )

    for row in units:
        after = fx.read_unit(api, row["id"])
        assert_fields(after, template_id=legacy["id"], key_status=KEY_KEYLESS)
        assert after["version"] == versions_before[row["id"]], (
            "a read-only projection must not bump a unit's version"
        )

    settled = validate_success(
        api.get_change_request(change_request["id"], SYSTEM_ADMIN), 200
    )
    assert_fields(
        settled,
        status=CR_APPROVED,
        pinned_template_version=1,
        target_unit_count=2,
        deployed_unit_count=0,
    )
    assert_nulls(settled, "deployment_started_at", "deployed_at")


def _delta_prorated_fleet(api: ApiClient):
    """Agency D on the `PRORATED` basis with three radios all assigned on
    `2026-07-21T00:00:00Z`, the clock then advanced to `2026-08-01T00:00:00Z`.

    Returns ``(agency, units)``.
    """
    fx.set_clock(api, "2026-07-21T00:00:00Z")
    agency = fx.register_agency(
        api,
        name="Delta Regional EMS",
        agency_code="EMSD1",
        agency_type=AGENCY_TYPE_EMS,
        fee_basis=FEE_BASIS_PRORATED,
        interop_privilege=INTEROP_MONITOR,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="EMS-BASE-1",
        target_standard=STANDARD_P25_PHASE1,
        talkgroup_slot_count=4,
        encryption_required=False,
    )
    units = []
    for index, model in enumerate((MODEL_PORTABLE, MODEL_PORTABLE, MODEL_MOBILE)):
        row = fx.assigned_unit(
            api,
            agency["id"],
            template["id"],
            serial_number=f"SND{index + 1:03d}",
            radio_id=4001 + index,
            model=model,
        )
        assert_fields(row, provision_status=PROVISION_ASSIGNED, key_status=KEY_KEYLESS)
        assert_instant_equals(row["assigned_at"], "2026-07-21T00:00:00Z", "assigned_at")
        units.append(row)

    fx.set_clock(api, "2026-08-01T00:00:00Z")
    return agency, units


def test_prorated_fee_rounds_each_unit_before_summing(
    api: ApiClient, clock_at_start: str
):
    """Three radios, one rate, eleven days each — and the pinned rounding order is
    the whole difference: rounding per unit and then adding gives 4,470 cents,
    while adding the fractional amounts and rounding once at the end would give
    4,471. Only the first is the contract.

    PRD 3.9: "Each candidate's fee is its rate multiplied by its days in service,
    divided by the period length, **rounded half up to whole cents for that
    unit**, and the tier subtotal is the sum of those per-unit amounts."

    PRD 3.9: "The rounding order is pinned: round per unit first, then add."

    PRD 3.9: "Summing the fractional per-unit amounts and rounding once at the end
    is wrong and produces a different total."

    PRD 3.9: "Those candidates are ordered by ascending `created_at` — never by
    identifier — and that order assigns each one a one-based rank, which in turn
    selects its rate: rank 1 through 50 is charged at 4,200 cents, rank 51 through
    200 at 3,600 cents, and rank 201 onward at 3,100 cents."

    Design: Difficulty/combinatorial_formula/prorated_fee_rounds_per_unit_before_summing_mode_b
    """
    agency, units = _delta_prorated_fleet(api)
    assert_fields(agency, fee_basis=FEE_BASIS_PRORATED)
    assert len(units) == 3, "the fixture must build exactly three candidate radios"

    fx.assess_fees(api, agency["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    billed = fx.read_agency(api, agency["id"])

    # All three radios take rank-1..3 tier-one rates on a 31-day period:
    # round_half_up(4200 * 11 / 31) == round_half_up(1490.32) == 1490 per unit,
    # and 3 * 1490 == 4470.
    assert_cents(billed["last_assessed_fee_cents"], 4470, "last_assessed_fee_cents")
    assert billed["last_assessed_fee_cents"] != 4471, (
        "4471 is the round-once-at-the-end total; the PRD pins round-then-sum"
    )
    assert_fields(
        billed,
        billable_subscriber_count=3,
        interop_privilege=INTEROP_MONITOR,
        billing_status=BILLING_CURRENT,
    )
    assert billed["last_assessed_fee_cents"] < 3 * TIER_1_RATE_CENTS, (
        "a part-period prorated fleet must cost less than three full-period heads"
    )


def test_prorated_rounding_settles_the_ledger_and_the_per_unit_day_counts(
    api: ApiClient, clock_at_start: str
):
    """The per-unit rounding is visible from both ends: the booked ledger carries
    the same 4,470 cents, and each of the three radios carries the eleven-day
    figure the per-unit arithmetic divided by the 31-day period length.

    PRD 3.9: "**Step five** books it. `last_assessed_fee_cents` is set to the total
    assessed amount; `lifetime_assessed_cents` has that amount added to it;
    `fee_balance_cents` is then recomputed as `lifetime_assessed_cents` less
    `lifetime_paid_cents`; `last_assessment_period_start` and
    `last_assessment_period_end` record the period just assessed; and
    `payment_due_at` is set to `period_end` plus a 30-day payment grace."

    PRD 3.9: "The period is half-open, so the length used in the arithmetic below,
    referred to as the **period length**, is the exact count of whole UTC days from
    `period_start` up to but not including `period_end` — never a nominal 30."

    PRD 3.9: "The candidate list is wider here: it is the agency's subscriber units
    whose current `provision_status` is `ASSIGNED`, `SUSPENDED`, or `RETIRED`."

    Design: Difficulty/combinatorial_formula/prorated_fee_rounds_per_unit_before_summing_mode_b
    """
    agency, units = _delta_prorated_fleet(api)

    fx.assess_fees(api, agency["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    billed = fx.read_agency(api, agency["id"])

    _fee_ledger_is_settled(billed, 4470, 0)
    assert_instant_equals(
        billed["last_assessment_period_start"],
        "2026-07-01T00:00:00Z",
        "last_assessment_period_start",
    )
    assert_instant_equals(
        billed["last_assessment_period_end"],
        "2026-08-01T00:00:00Z",
        "last_assessment_period_end",
    )
    assert_instant_equals(
        billed["payment_due_at"], "2026-08-31T00:00:00Z", "payment_due_at"
    )

    for row in units:
        assert_fields(fx.read_unit(api, row["id"]), days_in_service_last_period=11)


def _india_agency_at_version_two(api: ApiClient):
    """Agency I whose `version` has been advanced to 2 by a console-config write,
    so that a pin of 1 is genuinely stale.

    Returns ``(agency_at_version_two, stale_version)``.
    """
    created = fx.register_agency(
        api,
        name="India Water District",
        agency_code="PWKI1",
        agency_type=AGENCY_TYPE_PUBLIC_WORKS,
        fee_basis=FEE_BASIS_SNAPSHOT,
        interop_privilege=INTEROP_MONITOR,
        recorder_retention_days=30,
        console_position_count=2,
    )
    assert_fields(created, version=1, console_position_count=2)
    stale_version = created["version"]

    bumped = fx.set_console_config(api, created["id"], console_position_count=6)
    assert_fields(bumped, version=2, console_position_count=6)
    return bumped, stale_version


def test_fee_assessment_stale_version_outranks_invalid_fee_period(
    api: ApiClient, clock_at_start: str
):
    """One request breaks two rules at once — it pins version 1 against an agency
    now at version 2, and it asks to bill a period ending a month after the logical
    clock. Check 8 outranks group 13, so the answer is `ERR_STALE_VERSION` with
    HTTP 412 and never `ERR_FEE_PERIOD_INVALID`.

    PRD 2.4: "Because many operations are guarded by several rules at once, the
    order in which those rules are evaluated is itself part of the contract."

    PRD 2.4: "8. The optimistic-concurrency field required by the endpoint matches
    the parent's current `version` — otherwise `ERR_STALE_VERSION`."

    PRD 2.4: "13. Remaining domain rules, in the order given by their own sections
    below."

    PRD 2.6: "If that value does not equal the agency's current `version`, the
    assessment is rejected with `ERR_STALE_VERSION` and HTTP 412."

    Design: Difficulty/priority_pair_validation_conflict/fee_assessment_stale_version_outranks_invalid_fee_period
    """
    agency, stale_version = _india_agency_at_version_two(api)

    # period_end lies a month after the logical clock, which is an independent
    # ERR_FEE_PERIOD_INVALID failure inside group 13.
    doubly_invalid = api.create_fee_assessment(
        agency["id"],
        f.fee_assessment_payload(
            "2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z", stale_version
        ),
        SYSTEM_ADMIN,
    )
    body = validate_error(doubly_invalid, ERR_STALE_VERSION, 412)
    assert body["error_id"] != ERR_FEE_PERIOD_INVALID, (
        "the group-13 fiscal rule must not be reported ahead of check 8"
    )

    # Nothing was computed and nothing was booked.
    untouched = fx.read_agency(api, agency["id"])
    assert_fields(
        untouched,
        version=2,
        billing_status=BILLING_CURRENT,
        last_assessed_fee_cents=0,
    )
    _fee_ledger_is_settled(untouched, 0, 0)
    assert_nulls(
        untouched,
        "payment_due_at",
        "last_assessment_period_start",
        "last_assessment_period_end",
    )


def test_fee_period_failure_surfaces_only_once_the_version_pin_is_current(
    api: ApiClient, clock_at_start: str
):
    """The lower-ranked failure is still there: repeat the identical illegal period
    with a current pin and the same request now answers `ERR_FEE_PERIOD_INVALID`
    with HTTP 422 — proving the first response was ordering, not absolution.

    PRD 3.9: "The period itself is validated before anything is computed:
    `period_end` must be strictly after `period_start`, the period may not be
    longer than 366 days, and `period_end` may not lie after the current logical
    clock instant — an authority cannot bill for the future."

    PRD 3.9: "Any of those three failures is rejected with
    `ERR_FEE_PERIOD_INVALID`."

    PRD 3.1: "Its `billable_subscriber_count`, `last_assessed_fee_cents`,
    `fee_balance_cents`, `lifetime_assessed_cents`, `lifetime_paid_cents`, and
    `active_patch_request_count` all open at 0."

    Design: Difficulty/priority_pair_validation_conflict/fee_assessment_stale_version_outranks_invalid_fee_period
    """
    agency, stale_version = _india_agency_at_version_two(api)
    current_version = agency["version"]
    assert current_version != stale_version, "the pin under test must have moved"

    validate_error(
        api.create_fee_assessment(
            agency["id"],
            f.fee_assessment_payload(
                "2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z", stale_version
            ),
            SYSTEM_ADMIN,
        ),
        ERR_STALE_VERSION,
        412,
    )

    # Same illegal period, correct pin: the fiscal rule is now the first failure.
    validate_error(
        api.create_fee_assessment(
            agency["id"],
            f.fee_assessment_payload(
                "2026-07-01T00:00:00Z", "2026-09-01T00:00:00Z", current_version
            ),
            SYSTEM_ADMIN,
        ),
        ERR_FEE_PERIOD_INVALID,
        422,
    )

    still_clean = fx.read_agency(api, agency["id"])
    assert_fields(
        still_clean,
        version=current_version,
        last_assessed_fee_cents=0,
        billable_subscriber_count=0,
        billing_status=BILLING_CURRENT,
    )
    _fee_ledger_is_settled(still_clean, 0, 0)

    # A legal period under the same current pin is accepted, so the agency was
    # never the problem.
    fx.assess_fees(api, agency["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    booked = fx.read_agency(api, agency["id"])
    assert_cents(booked["last_assessed_fee_cents"], 0, "last_assessed_fee_cents")
    assert_instant_equals(
        booked["payment_due_at"], "2026-08-31T00:00:00Z", "payment_due_at"
    )


def _sierra_assessed_ledger(api: ApiClient):
    """Agency S with two billable radios and one booked July assessment of 8,400
    cents outstanding.

    Returns ``(agency_after_assessment, units)`` with the clock at
    `2026-08-01T00:00:00Z`.
    """
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    agency = fx.register_agency(
        api,
        name="Sierra County Sheriff",
        agency_code="LAWS1",
        agency_type=AGENCY_TYPE_LAW,
        fee_basis=FEE_BASIS_SNAPSHOT,
        interop_privilege=INTEROP_MONITOR,
        recorder_retention_days=180,
    )
    template = fx.published_template(
        api,
        template_name="SIERRA-BASE-1",
        target_standard=STANDARD_P25_PHASE1,
        talkgroup_slot_count=6,
        encryption_required=False,
    )
    units = []
    for index, model in enumerate((MODEL_PORTABLE, MODEL_MOBILE)):
        row = fx.assigned_unit(
            api,
            agency["id"],
            template["id"],
            serial_number=f"SNS{index + 1:03d}",
            radio_id=11001 + index,
            model=model,
        )
        assert_fields(row, provision_status=PROVISION_ASSIGNED)
        units.append(row)

    fx.set_clock(api, "2026-08-01T00:00:00Z")
    fx.assess_fees(api, agency["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")

    assessed = fx.read_agency(api, agency["id"])
    # Two heads at the tier-one rate, a full SNAPSHOT period each.
    assert_cents(
        assessed["last_assessed_fee_cents"], 2 * TIER_1_RATE_CENTS, "assessed total"
    )
    assert_cents(assessed["last_assessed_fee_cents"], 8400, "assessed total")
    return assessed, units


def test_fee_assessment_then_full_payment_conserves_the_agency_ledger(
    api: ApiClient, clock_at_start: str
):
    """Money out and money in are two halves of one identity: after an 8,400-cent
    assessment and two payments of 3,400 and 5,000, the balance walks 8,400 to
    5,000 to 0 and `fee_balance_cents` equals `lifetime_assessed_cents` less
    `lifetime_paid_cents` at every single step.

    PRD 3.9: "On success `amount_cents` is added to `lifetime_paid_cents`,
    `fee_balance_cents` is recomputed as `lifetime_assessed_cents` less
    `lifetime_paid_cents`, `billing_status` is re-evaluated, and the agency's
    `version` increments by one."

    PRD 3.9: "A payment that clears the balance entirely returns `billing_status`
    to `CURRENT` and restores the agency's `governance_vote_weight`."

    PRD 3.9: "When `fee_balance_cents` is zero or negative, the target status is
    `CURRENT`."

    Design: Difficulty/compensating_invariant/fee_assessment_then_full_payment_conserves_agency_ledger
    """
    assessed, _units = _sierra_assessed_ledger(api)
    agency_id = assessed["id"]

    _fee_ledger_is_settled(assessed, 8400, 0)
    assert_fields(assessed, billing_status=BILLING_CURRENT, billable_subscriber_count=2)
    assert_instant_equals(
        assessed["payment_due_at"], "2026-08-31T00:00:00Z", "payment_due_at"
    )

    # Partial payment: the identity must survive an intermediate state.
    fx.pay(api, agency_id, 3400)
    part_paid = fx.read_agency(api, agency_id)
    _fee_ledger_is_settled(part_paid, 8400, 3400)
    assert_cents(part_paid["fee_balance_cents"], 5000, "balance after 3400")
    assert_fields(part_paid, billing_status=BILLING_CURRENT)

    # Paying the exact remainder closes the ledger at zero.
    fx.pay(api, agency_id, 5000)
    settled = fx.read_agency(api, agency_id)
    _fee_ledger_is_settled(settled, 8400, 8400)
    assert_cents(settled["fee_balance_cents"], 0, "balance after full payment")
    assert_fields(
        settled,
        billing_status=BILLING_CURRENT,
        governance_vote_weight=1,
        voting_eligible=True,
        billable_subscriber_count=2,
    )
    # The assessment record itself is history and is not rewritten by payments.
    assert_cents(settled["last_assessed_fee_cents"], 8400, "last_assessed_fee_cents")


def test_overpayment_beyond_a_settled_ledger_is_refused_without_drift(
    api: ApiClient, clock_at_start: str
):
    """Once the balance is zero the ledger is closed: a single further cent is
    refused with `ERR_PAYMENT_EXCEEDS_BALANCE` and HTTP 422, and every fiscal and
    governance figure — including the agency's `version` — is exactly where the
    final payment left it.

    PRD 3.9: "A payment names `amount_cents`, which must be at least 1 and must not
    exceed the agency's current `fee_balance_cents`; a payment below one cent or
    larger than the outstanding balance is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."

    PRD 3.9: "Every other agency is `voting_eligible` and its weight is one vote
    plus one additional vote for each complete block of 250 billable subscribers —
    the block count is the billable subscriber count divided by 250 with any
    fraction discarded downward — with the whole figure capped at 5 votes."

    Design: Difficulty/compensating_invariant/fee_assessment_then_full_payment_conserves_agency_ledger
    """
    assessed, _units = _sierra_assessed_ledger(api)
    agency_id = assessed["id"]

    fx.pay(api, agency_id, 3400)
    fx.pay(api, agency_id, 5000)
    settled = fx.read_agency(api, agency_id)
    _fee_ledger_is_settled(settled, 8400, 8400)
    version_before = settled["version"]

    refused = api.create_payment(
        agency_id,
        f.payment_payload(1),
        make_agency_radio_manager_headers(agency_id),
    )
    validate_error(refused, ERR_PAYMENT_EXCEEDS_BALANCE, 422)

    after = fx.read_agency(api, agency_id)
    _fee_ledger_is_settled(after, 8400, 8400)
    assert_fields(
        after,
        version=version_before,
        billing_status=BILLING_CURRENT,
        governance_vote_weight=1,
        voting_eligible=True,
        billable_subscriber_count=2,
    )
    assert_cents(after["last_assessed_fee_cents"], 8400, "last_assessed_fee_cents")

    standing = validate_success(api.get_governance_standing(agency_id, SYSTEM_ADMIN), 200)
    assert_fields(
        standing,
        agency_id=agency_id,
        billing_status=BILLING_CURRENT,
        billable_subscriber_count=2,
        governance_vote_weight=1,
        voting_eligible=True,
    )
