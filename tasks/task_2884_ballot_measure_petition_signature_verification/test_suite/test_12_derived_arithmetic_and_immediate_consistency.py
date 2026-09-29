"""Derived arithmetic: frozen snapshots, keeper ranking, the two aggregation
legs, and the immediacy of every recomputation.

Each rounding direction in this file is chosen so that the wrong direction
produces a different integer: 12345 votes at 375 basis points lands on
462.9375, a validity rate of one valid line out of two lands on exactly 5000
after truncation, and a surcharge of 0.125 cents rounds up to 1. The
consistency claim is asserted on the *causing* response first and only then on
a follow-up read, because an implementation that recomputes lazily on the next
GET would satisfy a suite that always reads back.
"""
from test_helpers import (
    api_client,
    add_signature_payload,
    assert_instants_equal,
    file_batch,
    file_petition,
    make_examiner_headers,
    make_county_clerk_headers,
    make_proponent_headers,
    make_sos_admin_headers,
    read_batch,
    read_line,
    read_petition,
    register_standard,
    setup_circulation_ready,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import (
    close_circulation,
    decide_format,
    file_batch_with_lines,
    open_round,
    prepare_title_summary,
    set_clock,
    submit_petition,
    tally_round,
    validate_line,
)

FILING_CLOCK = "2026-08-10T00:00:00Z"
EPOCH_STAMP = "2026-08-01T00:00:00.000Z"
DEADLINE_STAMP = "2027-01-28T00:00:00.000Z"

# Line 1 was signed later than line 2 on purpose, so "first validated wins",
# "lowest line_number wins" and "earliest signed_on wins" disagree.
LATE_THEN_EARLY = [
    {
        "line_number": 1,
        "claimed_voter_id_number": "VA1",
        "signed_on": "2026-08-05T00:00:00Z",
        "signature_hash": "H-VA1",
        "signer_name": "Ada Adams",
    },
    {
        "line_number": 2,
        "claimed_voter_id_number": "VA1",
        "signed_on": "2026-08-03T00:00:00Z",
        "signature_hash": "H-VA1",
        "signer_name": "Ada Adams",
    },
]


def _duplicate_world():
    """One census round over two lines that claim the same ACTIVE voter."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        standard_overrides={
            "jurisdiction_code": "SOS-D",
            "sufficiency_upper_bps": 10000,
            "cure_eligibility_floor_bps": 8000,
        },
        counties=[("ALPHA", 20)],
        voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
    )
    set_clock(FILING_CLOCK)
    record = file_batch_with_lines(world, LATE_THEN_EARLY)
    assert record["batch"]["accepted_raw_count"] == 2
    close_circulation(world["petition"]["id"])
    world["round"] = open_round(world["petition"]["id"], round_type="RANDOM_SAMPLE")
    assert world["round"]["sample_size"] == 2, "sample_pct_bps 10000 draws a census"
    return world, record


def _single_line_world(jurisdiction_code):
    """The minimal ledger: one required signature, one county, one ACTIVE voter."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        standard_overrides={
            "jurisdiction_code": jurisdiction_code,
            "signature_pct_bps": 100,
            "sufficiency_upper_bps": 10000,
        },
        counties=[("ALPHA", 20)],
        voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
    )
    assert world["petition"]["required_valid_signatures"] == 1
    set_clock(FILING_CLOCK)
    return world


class TestRequiredThresholdAndDeadlineFrozenAtClearance:
    """Clearance computes the threshold with a ceiling and the deadline by whole
    days, then freezes both on the petition."""

    def test_a_non_round_formula_rounds_up_and_the_deadline_crosses_the_year(self):
        """12345 votes at 375 basis points is 462.9375, so the threshold is 463,
        and 180 whole days from 2026-08-01 is 2027-01-28.

        PRD §3.2: "It sets `circulation_deadline` to `cleared_at` advanced by the
        standard's `circulation_window_days` whole days — one hundred and eighty
        days of street circulation by default. And it freezes the signature
        threshold: `required_valid_signatures` is set to the standard's
        `gubernatorial_vote_total` multiplied by its `signature_pct_bps`,
        divided by 10000, with any fractional remainder rounded **up** to the
        next whole signature."

        Design: Corner/calculations/required_threshold_and_deadline_frozen_at_clearance
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(
            jurisdiction_code="SOS-N",
            gubernatorial_vote_total=12345,
            signature_pct_bps=375,
            sample_pct_bps=5000,
            sample_min_count=2,
            sufficiency_upper_bps=12000,
            sufficiency_lower_bps=6000,
            circulation_window_days=180,
        )

        petition = file_petition(standard["id"], submitted_title="Threshold Measure")
        assert petition["required_valid_signatures"] == 0, (
            "the threshold is not computed at create time"
        )
        assert petition["circulation_deadline"] is None

        submit_petition(petition["id"])
        decide_format(petition["id"], "APPROVE")
        prepare_title_summary(petition["id"], official_title="The Threshold Act")

        cleared = validate_success(
            api_client.clear_for_circulation(petition["id"], make_sos_admin_headers())
        )

        assert cleared["status"] == "CLEARED"
        assert cleared["required_valid_signatures"] == 463, (
            "ceil(12345 * 375 / 10000) == ceil(462.9375) == 463; 462 is floor"
        )
        assert_instants_equal(cleared["cleared_at"], EPOCH_STAMP)
        assert_instants_equal(cleared["circulation_deadline"], DEADLINE_STAMP)

    def test_both_snapshots_survive_a_later_read_by_the_committee(self):
        """The frozen threshold and deadline come back unchanged from a plain
        read, so neither is recomputed from the standard on demand.

        PRD §3.2: "Exactly one standard participates, resolved through the
        petition's `standard_id` at clearance time, and the value is frozen:
        editing the standard afterwards never moves an already-cleared
        petition's threshold."

        Design: Corner/calculations/required_threshold_and_deadline_frozen_at_clearance
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(
            jurisdiction_code="SOS-N2",
            gubernatorial_vote_total=12345,
            signature_pct_bps=375,
            circulation_window_days=180,
        )
        petition = file_petition(standard["id"], submitted_title="Threshold Measure")
        submit_petition(petition["id"])
        decide_format(petition["id"], "APPROVE")
        prepare_title_summary(petition["id"])
        cleared = validate_success(
            api_client.clear_for_circulation(petition["id"], make_sos_admin_headers())
        )

        reread = read_petition(petition["id"], make_proponent_headers())
        assert reread["required_valid_signatures"] == 463
        assert_instants_equal(reread["circulation_deadline"], DEADLINE_STAMP)
        assert reread == cleared, "a read must not mutate the frozen snapshot"


class TestDuplicateKeeperSelectionIsOrderIndependent:
    """The keeper is the earliest `signed_on`, whatever order the clerk works
    in and whatever the line numbers say."""

    def test_the_later_signature_loses_even_though_it_is_validated_first(self):
        """Line 1 is adjudicated first and still becomes `INVALID_DUPLICATE`,
        pointing at line 2, which stays `VALID` when adjudicated second.

        PRD §3.5: "The candidates are ranked by `signed_on` ascending, then by
        their batch's `filed_at` ascending, then by `line_number` ascending, and
        the first-ranked candidate is the **keeper**. If the line being
        validated is the keeper, it becomes `VALID` and
        `matched_voter_record_id` is set. If it is not, it becomes
        `INVALID_DUPLICATE`, `matched_voter_record_id` is set, and
        `duplicate_of_signature_id` is set to the keeper's identifier."

        Design: Corner/calculations/duplicate_keeper_selection_is_order_independent
        """
        world, record = _duplicate_world()
        county_id = record["county"]["id"]
        late, early = record["lines"][0], record["lines"][1]
        voter_id = world["voters"]["VA1"]["id"]

        late_result = validate_line(late["id"], county_id)
        assert late_result["validation_status"] == "INVALID_DUPLICATE", (
            "validated first, yet the loser, because its signed_on is later"
        )
        assert late_result["duplicate_of_signature_id"] == early["id"]
        assert late_result["matched_voter_record_id"] == voter_id

        early_result = validate_line(early["id"], county_id)
        assert early_result["validation_status"] == "VALID"
        assert early_result["duplicate_of_signature_id"] is None
        assert early_result["matched_voter_record_id"] == voter_id

        assert read_line(late["id"])["validation_status"] == "INVALID_DUPLICATE", (
            "adjudicating the keeper afterwards must not flip the loser back"
        )

    def test_the_duplicate_shrinks_the_valid_numerator_and_nothing_else(self):
        """The tally sees one valid line in two, so the rate is 5000 and the
        projection 1 — while `accepted_raw_total` stays at 2.

        PRD §3.6: "`projected_valid_count` is where the two documented variants
        of the standard diverge... For a `RANDOM_SAMPLE` round under a `POOLED`
        standard, the projection is the petition's `accepted_raw_total`
        multiplied by the round's `validity_rate_bps`, divided by 10000, with
        the remainder discarded."

        Design: Corner/calculations/duplicate_keeper_selection_is_order_independent
        """
        world, record = _duplicate_world()
        county_id = record["county"]["id"]
        validate_line(record["lines"][0]["id"], county_id)
        validate_line(record["lines"][1]["id"], county_id)

        tallied = tally_round(world["round"]["id"])
        assert tallied["sampled_valid_count"] == 1
        assert tallied["validity_rate_bps"] == 5000, "floor(1 * 10000 / 2)"
        assert tallied["projected_valid_count"] == 1, "floor(2 * 5000 / 10000)"
        assert tallied["determination"] == "INSUFFICIENT", (
            "projected 1 sits exactly on the lower gate floor(2 * 5000 / 10000)"
        )

        petition = read_petition(world["petition"]["id"])
        assert petition["accepted_raw_total"] == 2, (
            "a duplicate is an accepted sheet; only the valid numerator drops"
        )
        assert petition["projected_valid_count"] == 1
        assert petition["status"] == "PENDING_FAILURE", (
            "1 * 10000 is below 2 * 8000, so the petition is not cure-eligible"
        )


class TestAcceptedTotalsFilterOutFormatRejectedBatches:
    """`raw_signature_count` and `accepted_raw_total` are driven apart by one
    clerk decision, because they filter on different batch statuses."""

    def test_striking_some_lines_verifies_while_striking_all_of_them_rejects(self):
        """b1 keeps one of two lines and lands in `AFFIDAVIT_VERIFIED`; b2 loses
        its only line and lands in the terminal `REJECTED_FORMAT`.

        PRD §3.4: "If at least one line survives, the batch moves from
        `RECEIVED` to `AFFIDAVIT_VERIFIED` and its accepted lines join the
        petition's countable pool. If `format_defect_line_numbers` covers every
        line in the batch — that is, the number of entries equals the batch's
        `raw_count` — the batch moves from `RECEIVED` to `REJECTED_FORMAT`,
        which is terminal, and `accepted_raw_count` is set to 0."

        Design: Corner/calculations/accepted_totals_filter_out_format_rejected_batches
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={"jurisdiction_code": "SOS-F"},
            counties=[("ALPHA", 20)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
        )
        set_clock(FILING_CLOCK)

        b1 = file_batch_with_lines(
            world,
            [
                {"claimed_voter_id_number": "VA1", "signer_name": "Ada Adams"},
                {"claimed_voter_id_number": "VA1", "signer_name": "Blank Line"},
            ],
            format_defect_line_numbers=[2],
        )
        assert b1["batch"]["status"] == "AFFIDAVIT_VERIFIED"
        assert b1["batch"]["raw_count"] == 2
        assert b1["batch"]["accepted_raw_count"] == 1, "raw_count less format_defect_count"
        assert b1["batch"]["format_defect_count"] == 1

        b2 = file_batch_with_lines(
            world,
            [
                {
                    "claimed_voter_id_number": "VA1",
                    "signed_on": "2026-08-06T00:00:00Z",
                    "signer_name": "Torn Sheet",
                }
            ],
            format_defect_line_numbers=[1],
        )
        assert b2["batch"]["status"] == "REJECTED_FORMAT", (
            "striking every line rejects the whole batch"
        )
        assert b2["batch"]["raw_count"] == 1
        assert b2["batch"]["accepted_raw_count"] == 0
        assert b2["batch"]["format_defect_count"] == 1

        assert read_line(b1["lines"][1]["id"])["validation_status"] == (
            "INVALID_FORMAT_DEFECT"
        ), "struck lines are marked, not deleted"
        assert read_line(b2["lines"][0]["id"])["validation_status"] == (
            "INVALID_FORMAT_DEFECT"
        )

    def test_the_petition_counts_rejected_sheets_as_raw_but_never_as_accepted(self):
        """Three sheets were physically filed and one survives review, so the
        petition reports 3 and 1 at the same time.

        PRD §3.4: "`raw_signature_count` is the sum of `raw_count` across all of
        the petition's batches whose `status` is anything other than
        `INVALIDATED`. `accepted_raw_total` is the sum of `accepted_raw_count`
        across only those batches whose `status` is `AFFIDAVIT_VERIFIED`,
        `SAMPLED` or `FULLY_CHECKED`."

        Design: Corner/calculations/accepted_totals_filter_out_format_rejected_batches
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={"jurisdiction_code": "SOS-F2"},
            counties=[("ALPHA", 20)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
        )
        set_clock(FILING_CLOCK)
        b1 = file_batch_with_lines(
            world,
            [
                {"claimed_voter_id_number": "VA1", "signer_name": "Ada Adams"},
                {"claimed_voter_id_number": "VA1", "signer_name": "Blank Line"},
            ],
            format_defect_line_numbers=[2],
        )
        file_batch_with_lines(
            world,
            [{"claimed_voter_id_number": "VA1", "signer_name": "Torn Sheet"}],
            format_defect_line_numbers=[1],
        )

        petition = read_petition(world["petition"]["id"])
        assert petition["raw_signature_count"] == 3, (
            "raw counts every non-INVALIDATED batch, REJECTED_FORMAT included"
        )
        assert petition["accepted_raw_total"] == 1, (
            "only the AFFIDAVIT_VERIFIED batch contributes on the accepted side"
        )
        assert petition["status"] == "CLEARED", (
            "verifying affidavits does not by itself advance the petition"
        )
        assert read_batch(b1["batch"]["id"])["checked_signature_count"] == 0, (
            "no round has examined anything yet, so nothing is priced"
        )
        assert read_batch(b1["batch"]["id"])["verification_cost_cents"] == 0


class TestDerivedLedgerFieldsVisibleInTheCausingResponse:
    """Every recomputation is part of the request that caused it, so the
    mutation's own body already carries the new numbers."""

    def test_each_mutation_body_already_carries_the_counters_it_moved(self):
        """A line's own create response shows it unexamined, the affidavit
        response shows the accepted total, and the petition's roll-up happened
        during the affidavit request rather than on the next read.

        PRD §2.10: "Whenever an operation anywhere below the petition changes a
        batch status, a line's validation outcome, or a stored batch cost, the
        affected counters are recomputed in full from the surviving data."

        Design: Corner/consistency_model/derived_ledger_fields_visible_in_the_causing_response
        """
        world = _single_line_world("SOS-I")
        petition_id = world["petition"]["id"]
        county_id = world["counties"]["ALPHA"]["id"]

        batch = file_batch(petition_id, world["circulator"]["id"], county_id)
        assert batch["raw_count"] == 0
        assert batch["accepted_raw_count"] == 0
        assert batch["verification_cost_cents"] == 0

        line = validate_success(
            api_client.add_signature(
                batch["id"],
                add_signature_payload(
                    line_number=1,
                    signer_name="Ada Adams",
                    claimed_voter_id_number="VA1",
                    signed_on="2026-08-05T00:00:00Z",
                    signature_hash="H-VA1",
                ),
                make_proponent_headers(),
            ),
            201,
        )
        assert line["validation_status"] == "PENDING"
        assert line["in_sample"] is False

        assert read_batch(batch["id"])["raw_count"] == 1, (
            "the parent's raw_count already reflects the child created one call ago"
        )

        verified = validate_success(
            api_client.verify_affidavit(
                batch["id"],
                {"affidavit_notary_id": "NOT-1"},
                make_county_clerk_headers(county_id),
            )
        )
        assert verified["status"] == "AFFIDAVIT_VERIFIED"
        assert verified["accepted_raw_count"] == 1, (
            "the accepted total is in the affidavit response itself"
        )

        after_affidavit = read_petition(petition_id)
        assert after_affidavit["raw_signature_count"] == 1
        assert after_affidavit["accepted_raw_total"] == 1, (
            "the cross-entity roll-up happened during the affidavit request"
        )

        filed = validate_success(
            api_client.file_signatures(petition_id, make_proponent_headers())
        )
        assert filed["status"] == "SIGNATURES_FILED"
        assert filed["raw_signature_count"] == 1, "filing does not recount"
        assert filed["accepted_raw_total"] == 1

    def test_the_tally_prices_the_batch_and_the_invoice_follows_immediately(self):
        """The tally response carries all five derived round fields, the batch is
        advanced and priced by that same request, and the invoice read
        summarises the ledger with no intervening write.

        PRD §3.6: "County reimbursement accrues at exactly those moments, once
        per batch the round touched."

        PRD §3.8: "Its `gross_cents` is the sum of `verification_cost_cents`
        across only those batches of the petition whose `status` is `SAMPLED` or
        `FULLY_CHECKED`... `surcharge_cents` is `subtotal_cents` multiplied by
        the standard's `county_surcharge_bps` divided by 10000 with any
        remainder rounded **up**."

        Design: Corner/consistency_model/derived_ledger_fields_visible_in_the_causing_response
        """
        world = _single_line_world("SOS-I2")
        petition_id = world["petition"]["id"]
        county_id = world["counties"]["ALPHA"]["id"]
        record = file_batch_with_lines(world, ["VA1"])
        close_circulation(petition_id)

        opened = validate_success(
            api_client.create_verification_round(
                petition_id, {"round_type": "RANDOM_SAMPLE"}, make_examiner_headers()
            ),
            201,
        )
        assert opened["sample_size"] == 1
        assert opened["status"] == "OPEN"
        assert read_line(record["lines"][0]["id"])["in_sample"] is True, (
            "selection is written to the child rows synchronously"
        )

        adjudicated = validate_success(
            api_client.validate_signature_record(
                record["lines"][0]["id"], make_county_clerk_headers(county_id), {}
            )
        )
        assert adjudicated["validation_status"] == "VALID"
        assert adjudicated["matched_voter_record_id"] == world["voters"]["VA1"]["id"]
        assert adjudicated["validated_in_round_id"] == opened["id"]

        tallied = validate_success(
            api_client.tally_round(opened["id"], make_examiner_headers())
        )
        assert tallied["sampled_valid_count"] == 1
        assert tallied["validity_rate_bps"] == 10000
        assert tallied["projected_valid_count"] == 1
        assert tallied["determination"] == "SUFFICIENT"
        assert tallied["accrued_cost_cents"] == 5, "round_half_up(1 * 4750 / 1000)"

        batch = read_batch(record["batch"]["id"])
        assert batch["status"] == "SAMPLED"
        assert batch["checked_signature_count"] == 1
        assert batch["verification_cost_cents"] == 5, (
            "the batch was advanced and priced by the tally request"
        )

        petition = read_petition(petition_id)
        assert petition["status"] == "PENDING_CERTIFICATION"
        assert petition["projected_valid_count"] == 1
        assert petition["verification_cost_accrued_cents"] == 5
        assert petition["qualifying_county_count"] == 1

        invoice = validate_success(
            api_client.get_verification_invoice(petition_id, make_examiner_headers())
        )
        assert invoice["petition_id"] == petition_id
        assert invoice["gross_cents"] == 5
        assert invoice["tier"] == "TIER_NONE", "5 cents is below the tier-A floor of 20"
        assert invoice["discount_bps"] == 0
        assert invoice["discount_cents"] == 0
        assert invoice["subtotal_cents"] == 5
        assert invoice["surcharge_cents"] == 1, "ceil(5 * 250 / 10000) == ceil(0.125)"
        assert invoice["total_cents"] == 6
