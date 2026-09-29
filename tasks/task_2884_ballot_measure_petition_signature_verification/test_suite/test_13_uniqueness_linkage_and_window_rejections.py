"""Rejection catalogue, part one: uniqueness scopes, batch linkage, sample
membership, temporal windows and the county-distribution aggregate.

Each probe is arranged so that exactly one rule can explain the refusal. A
batch is filed in a county that genuinely exists but is outside the assignment,
so `ERR_COUNTY_NOT_IN_ASSIGNMENT` cannot be confused with a 404; a supplemental
batch is filed while no cure period exists at all, so the coherence rule cannot
be mistaken for a missing-parent error; and the certification refusal is taken
on a petition whose projection, challenge status, referral status and acting
principal all pass, leaving the distribution rule as the only candidate.
"""
from test_helpers import (
    api_client,
    add_signature_payload,
    assert_instants_equal,
    file_batch,
    make_challenger_headers,
    make_county_clerk_headers,
    make_examiner_headers,
    make_proponent_headers,
    make_sos_admin_headers,
    read_batch,
    read_line,
    read_petition,
    setup_circulation_ready,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import (
    add_line,
    close_circulation,
    create_cleared_petition,
    create_assignment,
    create_registered_circulator,
    file_batch_with_lines,
    open_round,
    read_round,
    set_clock,
    tally_round,
    validate_line,
    verify_batch_affidavit,
)

FILING_CLOCK = "2026-08-10T00:00:00Z"
DEADLINE_STAMP = "2027-01-28T00:00:00.000Z"

FOUR_ACTIVE_VOTERS = [
    {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA3", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA4", "registration_status": "ACTIVE"},
]

# signed_on strictly increasing, so the pool order is exactly lines 1..4.
FOUR_LINES = [
    {"claimed_voter_id_number": "VA1", "signed_on": "2026-08-02T00:00:00Z"},
    {"claimed_voter_id_number": "VA2", "signed_on": "2026-08-03T00:00:00Z"},
    {"claimed_voter_id_number": "VA3", "signed_on": "2026-08-04T00:00:00Z"},
    {"claimed_voter_id_number": "VA4", "signed_on": "2026-08-05T00:00:00Z"},
]


def _sample_world():
    """Four accepted lines, a half-percentage draw, and an open round whose
    systematic walk selects lines 1 and 3."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        standard_overrides={
            "jurisdiction_code": "SOS-M",
            "sample_pct_bps": 5000,
            "sufficiency_upper_bps": 10000,
        },
        counties=[("ALPHA", 20)],
        voters=FOUR_ACTIVE_VOTERS,
    )
    set_clock(FILING_CLOCK)
    record = file_batch_with_lines(world, FOUR_LINES)
    close_circulation(world["petition"]["id"])
    world["round"] = open_round(world["petition"]["id"], round_type="RANDOM_SAMPLE")
    assert world["round"]["eligible_pool_size"] == 4
    assert world["round"]["sample_size"] == 2, "max(1, ceil(4 * 5000 / 10000))"
    return world, record


class TestUniquenessConflictsAcrossEveryDeclaredScope:
    """Four uniqueness scopes, four distinct codes — and one scope that is per
    batch rather than global."""

    def test_the_four_declared_scopes_report_four_distinct_conflict_codes(self):
        """A repeated jurisdiction code, county code, voter id number and
        in-batch line number each carry their own 409.

        PRD §2.11: "The signals are `ERR_DUPLICATE_JURISDICTION_CODE`,
        `ERR_DUPLICATE_COUNTY_CODE`, `ERR_DUPLICATE_VOTER_ID_NUMBER` and
        `ERR_DUPLICATE_LINE_NUMBER`, all HTTP 409."

        Design: Corner/validations/uniqueness_conflicts_across_every_declared_scope
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={"jurisdiction_code": "SOS-U"},
            counties=[("ALPHA", 20), ("BRAVO", 40)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
        )
        alpha = world["counties"]["ALPHA"]
        bravo = world["counties"]["BRAVO"]
        set_clock(FILING_CLOCK)
        b1 = file_batch_with_lines(world, ["VA1"], county_code="ALPHA", verify=False)

        validate_error(
            api_client.create_verification_standard(
                {
                    "jurisdiction_code": "SOS-U",
                    "gubernatorial_vote_total": 999,
                    "signature_pct_bps": 100,
                    "sample_pct_bps": 5000,
                    "sample_min_count": 1,
                    "sufficiency_upper_bps": 10000,
                    "sufficiency_lower_bps": 5000,
                    "stratification_mode": "STRATIFIED",
                    "county_distribution_pct_bps": 500,
                    "required_qualifying_counties": 1,
                    "verification_rate_millicents_per_signature": 4750,
                    "county_surcharge_bps": 250,
                },
                make_sos_admin_headers(),
            ),
            "ERR_DUPLICATE_JURISDICTION_CODE",
            409,
        )
        standards, meta = validate_paginated(
            api_client.list_verification_standards(
                make_sos_admin_headers(), params={"jurisdiction_code": "SOS-U"}
            )
        )
        assert meta["total_count"] == 1
        assert standards[0]["stratification_mode"] == "POOLED", (
            "the refused create must not have overwritten the incumbent"
        )

        validate_error(
            api_client.create_county(
                {
                    "county_code": "ALPHA",
                    "name": "Alpha County Duplicate",
                    "registered_voter_count": 99,
                },
                make_sos_admin_headers(),
            ),
            "ERR_DUPLICATE_COUNTY_CODE",
            409,
        )
        assert validate_success(
            api_client.get_county(alpha["id"], make_sos_admin_headers())
        )["registered_voter_count"] == 20

        validate_error(
            api_client.create_voter_record(
                {
                    "county_id": bravo["id"],
                    "voter_id_number": "VA1",
                    "full_name": "Ada Adams Twin",
                    "signature_on_file_hash": "H-TWIN",
                    "registration_date": "2021-01-01T00:00:00Z",
                    "registration_status": "ACTIVE",
                },
                make_sos_admin_headers(),
            ),
            "ERR_DUPLICATE_VOTER_ID_NUMBER",
            409,
        )

        validate_error(
            api_client.add_signature(
                b1["batch"]["id"],
                add_signature_payload(
                    line_number=1,
                    signer_name="Second Ada",
                    claimed_voter_id_number="VA1",
                    signed_on="2026-08-06T00:00:00Z",
                    signature_hash="H-VA1",
                ),
                make_proponent_headers(),
            ),
            "ERR_DUPLICATE_LINE_NUMBER",
            409,
        )
        assert read_batch(b1["batch"]["id"])["raw_count"] == 1

    def test_a_line_number_is_unique_only_inside_its_own_batch(self):
        """Line number 1 is already taken in the first batch and is still
        accepted in a sibling batch of the same petition.

        PRD §3.4: "Each line carries a `line_number` of at least 1 giving its
        position on the sheet, which must be unique within its batch or the
        request is refused with `ERR_DUPLICATE_LINE_NUMBER`."

        Design: Corner/validations/uniqueness_conflicts_across_every_declared_scope
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={"jurisdiction_code": "SOS-U2"},
            counties=[("ALPHA", 20), ("BRAVO", 40)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
        )
        set_clock(FILING_CLOCK)
        first = file_batch_with_lines(world, ["VA1"], county_code="ALPHA", verify=False)
        assert first["lines"][0]["line_number"] == 1

        sibling = file_batch(
            world["petition"]["id"],
            world["circulator"]["id"],
            world["counties"]["BRAVO"]["id"],
        )
        accepted = validate_success(
            api_client.add_signature(
                sibling["id"],
                add_signature_payload(
                    line_number=1,
                    signer_name="Bravo Signer",
                    claimed_voter_id_number="VA1",
                    signed_on="2026-08-06T00:00:00Z",
                    signature_hash="H-VA1",
                ),
                make_proponent_headers(),
            ),
            201,
        )
        assert accepted["line_number"] == 1
        assert accepted["batch_id"] == sibling["id"], (
            "the same number in a sibling batch is a different line"
        )


class TestBatchLinkageAndFilingQuotaRejections:
    """Linkage checks look past existence, and the counting gates fire last."""

    def test_a_real_county_outside_the_assignment_fails_on_linkage_not_existence(self):
        """BRAVO exists but is not in the assignment, and a supplemental batch
        with no cure period is refused on coherence rather than as a 404.

        PRD §2.11: "The batch circulator holds an `ACTIVE` assignment for the
        batch petition; the batch county's code appears in that assignment's
        `assigned_county_codes`; a supplemental batch names an `OPEN` cure period
        of the same petition and a non-supplemental batch names none."

        Design: Corner/validations/batch_linkage_and_filing_quota_rejections
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={"jurisdiction_code": "SOS-B"},
            counties=[("ALPHA", 20), ("BRAVO", 40)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
            assigned_county_codes=["ALPHA"],
        )
        assert world["assignment"]["assigned_county_codes"] == ["ALPHA"]
        set_clock(FILING_CLOCK)

        validate_error(
            api_client.create_signature_batch(
                {
                    "petition_id": world["petition"]["id"],
                    "circulator_id": world["circulator"]["id"],
                    "county_id": world["counties"]["BRAVO"]["id"],
                    "affidavit_signed": True,
                },
                make_proponent_headers(),
            ),
            "ERR_COUNTY_NOT_IN_ASSIGNMENT",
            409,
        )

        validate_error(
            api_client.create_signature_batch(
                {
                    "petition_id": world["petition"]["id"],
                    "circulator_id": world["circulator"]["id"],
                    "county_id": world["counties"]["ALPHA"]["id"],
                    "affidavit_signed": True,
                    "is_supplemental": True,
                },
                make_proponent_headers(),
            ),
            "ERR_SUPPLEMENTAL_WITHOUT_CURE_PERIOD",
            409,
        )

    def test_the_counting_gates_refuse_a_defect_list_an_empty_batch_and_a_bare_filing(self):
        """A defect line number that names nothing, an affidavit on a line-less
        batch and a filing with no verified batch are three distinct 409s, and
        each leaves its target untouched.

        PRD §3.4: "Every entry of `format_defect_line_numbers` must match a
        `line_number` actually present in this batch; an entry that matches none
        is refused with `ERR_LINE_NUMBER_NOT_FOUND`."

        PRD §3.4: "At least one of the petition's batches must have reached
        `AFFIDAVIT_VERIFIED`, else the filing is refused with
        `ERR_NO_VERIFIED_BATCHES`."

        Design: Corner/validations/batch_linkage_and_filing_quota_rejections
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={"jurisdiction_code": "SOS-B2"},
            counties=[("ALPHA", 20)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
        )
        petition_id = world["petition"]["id"]
        county_id = world["counties"]["ALPHA"]["id"]
        set_clock(FILING_CLOCK)

        b1 = file_batch_with_lines(world, ["VA1"], verify=False)
        empty = file_batch(petition_id, world["circulator"]["id"], county_id)

        validate_error(
            api_client.verify_affidavit(
                b1["batch"]["id"],
                {"affidavit_notary_id": "NOT-1", "format_defect_line_numbers": [7]},
                make_county_clerk_headers(county_id),
            ),
            "ERR_LINE_NUMBER_NOT_FOUND",
            409,
        )
        untouched = read_batch(b1["batch"]["id"])
        assert untouched["status"] == "RECEIVED", "the whole affidavit is refused"
        assert untouched["affidavit_notary_id"] is None

        validate_error(
            api_client.verify_affidavit(
                empty["id"],
                {"affidavit_notary_id": "NOT-2"},
                make_county_clerk_headers(county_id),
            ),
            "ERR_BATCH_EMPTY",
            409,
        )
        assert read_batch(empty["id"])["status"] == "RECEIVED"

        validate_error(
            api_client.file_signatures(petition_id, make_proponent_headers()),
            "ERR_NO_VERIFIED_BATCHES",
            409,
        )
        assert read_petition(petition_id)["status"] == "CLEARED"

        verified = verify_batch_affidavit(
            b1["batch"]["id"], county_id, affidavit_notary_id="NOT-3"
        )
        assert verified["status"] == "AFFIDAVIT_VERIFIED"
        assert verified["accepted_raw_count"] == 1

        filed = close_circulation(petition_id)
        assert filed["status"] == "SIGNATURES_FILED"
        assert filed["raw_signature_count"] == 1, "the empty batch is simply ignored"


class TestSampleMembershipAndPendingLineRejections:
    """The draw decides who may be examined, and the tally waits for all of
    them."""

    def test_only_the_drawn_lines_are_validatable_and_never_twice(self):
        """A pool of four sampled at fifty percent yields lines 1 and 3; line 2
        and a replayed line 1 both collapse onto the same 409.

        PRD §3.5: "A line is only validatable while it is genuinely under
        examination: `in_sample` must be `true`, `validated_in_round_id` must
        name a round that is still `OPEN`, and the line's own
        `validation_status` must still be `PENDING`. A line that is not in a
        sample, or whose round has already been closed or voided, or that
        already carries a non-`PENDING` outcome, is refused with
        `ERR_SIGNATURE_NOT_IN_OPEN_ROUND`."

        Design: Corner/validations/sample_membership_and_pending_line_rejections
        """
        world, record = _sample_world()
        alpha_id = world["counties"]["ALPHA"]["id"]
        lines = record["lines"]
        round_id = world["round"]["id"]

        membership = [read_line(line["id"])["in_sample"] for line in lines]
        assert membership == [True, False, True, False], (
            "interval floor(4 / 2) == 2 walked from position zero selects lines 1 and 3"
        )
        assert read_line(lines[0]["id"])["validated_in_round_id"] == round_id
        assert read_line(lines[1]["id"])["validated_in_round_id"] is None

        validate_error(
            api_client.validate_signature_record(
                lines[1]["id"], make_county_clerk_headers(alpha_id)
            ),
            "ERR_SIGNATURE_NOT_IN_OPEN_ROUND",
            409,
        )
        assert read_line(lines[1]["id"])["validation_status"] == "PENDING"

        first = validate_line(lines[0]["id"], alpha_id)
        assert first["validation_status"] == "VALID"

        validate_error(
            api_client.validate_signature_record(
                lines[0]["id"], make_county_clerk_headers(alpha_id)
            ),
            "ERR_SIGNATURE_NOT_IN_OPEN_ROUND",
            409,
        )
        assert read_line(lines[0]["id"])["validation_status"] == "VALID", (
            "a line already adjudicated keeps its outcome"
        )

    def test_a_tally_waits_for_every_selected_line_then_prices_only_those_two(self):
        """With line 3 still pending the tally is refused and the round stays
        open; adjudicating it lets the tally close with two examined lines.

        PRD §3.6: "The round must be `OPEN` — tallying one that is not is
        refused with `ERR_INVALID_ROUND_STATE` — and every line the round
        selected must have moved off `PENDING`, else the tally is refused with
        `ERR_ROUND_HAS_PENDING_SIGNATURES`."

        Design: Corner/validations/sample_membership_and_pending_line_rejections
        """
        world, record = _sample_world()
        alpha_id = world["counties"]["ALPHA"]["id"]
        lines = record["lines"]
        round_id = world["round"]["id"]

        validate_line(lines[0]["id"], alpha_id)

        validate_error(
            api_client.tally_round(round_id, make_examiner_headers()),
            "ERR_ROUND_HAS_PENDING_SIGNATURES",
            409,
        )
        still_open = read_round(round_id)
        assert still_open["status"] == "OPEN"
        assert still_open["determination"] == "PENDING", (
            "PRD §3.6: a round's determination sits at PENDING until it is tallied"
        )
        assert still_open["accrued_cost_cents"] == 0

        validate_line(lines[2]["id"], alpha_id)
        closed = tally_round(round_id)

        assert closed["status"] == "CLOSED"
        assert closed["sampled_valid_count"] == 2
        assert closed["validity_rate_bps"] == 10000
        assert closed["projected_valid_count"] == 4, "floor(4 * 10000 / 10000)"
        assert closed["determination"] == "SUFFICIENT"
        assert closed["accrued_cost_cents"] == 10, (
            "two examined lines: round_half_up(2 * 4750 / 1000)"
        )
        priced = read_batch(record["batch"]["id"])
        assert priced["status"] == "SAMPLED"
        assert priced["checked_signature_count"] == 2, (
            "the two lines left PENDING were never examined and are never billed"
        )
        assert priced["verification_cost_cents"] == 10


class TestCirculationDeadlineBoundaryAndClosedChallengeWindow:
    """The deadline is inclusive on its own instant, and the challenge window
    only opens once a determination is pending."""

    def test_filing_is_accepted_on_the_deadline_and_refused_one_day_later(self):
        """Two petitions cleared together share a deadline of 2027-01-28; the
        first files exactly on it, the second one day past it is refused.

        PRD §3.4: "The logical clock must be at or before
        `circulation_deadline`; a filing attempted when the clock has moved
        strictly past that instant is refused with
        `ERR_CIRCULATION_DEADLINE_PASSED`."

        Design: Corner/validations/circulation_deadline_boundary_and_closed_challenge_window
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={"jurisdiction_code": "SOS-W"},
            counties=[("ALPHA", 20)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
        )
        petition_a = world["petition"]
        assert_instants_equal(petition_a["circulation_deadline"], DEADLINE_STAMP)

        petition_b = create_cleared_petition(world["standard"]["id"])
        assert_instants_equal(petition_b["circulation_deadline"], DEADLINE_STAMP)
        second_circulator = create_registered_circulator(full_name="Dana Doe")
        create_assignment(
            petition_b["id"],
            second_circulator["id"],
            assigned_county_codes=["ALPHA"],
            effective_from=CLOCK_EPOCH,
            effective_to="2026-08-31T00:00:00Z",
        )

        set_clock(FILING_CLOCK)
        file_batch_with_lines(world, ["VA1"])
        batch_b = file_batch(
            petition_b["id"], second_circulator["id"], world["counties"]["ALPHA"]["id"]
        )
        add_line(batch_b["id"], line_number=1, claimed_voter_id_number="VA1")
        verify_batch_affidavit(batch_b["id"], world["counties"]["ALPHA"]["id"])

        set_clock("2027-01-28T00:00:00Z")
        filed = close_circulation(petition_a["id"])
        assert filed["status"] == "SIGNATURES_FILED", (
            "the clock standing exactly on the deadline is still 'at or before' it"
        )
        assert filed["raw_signature_count"] == 1

        set_clock("2027-01-29T00:00:00Z")
        validate_error(
            api_client.file_signatures(petition_b["id"], make_proponent_headers()),
            "ERR_CIRCULATION_DEADLINE_PASSED",
            409,
        )
        assert read_petition(petition_b["id"])["status"] == "CLEARED"
        assert read_petition(petition_b["id"])["raw_signature_count"] == 1, (
            "the one line added before the deadline still counts; the refused "
            "file-signatures call changed nothing"
        )

    def test_a_challenge_is_refused_before_a_determination_is_pending(self):
        """A `CLEARED` petition and a `SIGNATURES_FILED` petition both refuse a
        challenge, and neither records one.

        PRD §3.8: "A challenge is filed by a `Challenger` against a petition
        sitting in `PENDING_CERTIFICATION` or `PENDING_FAILURE`; filing against
        a petition in any other status, including one already `CERTIFIED` or
        `FAILED`, is refused with `ERR_CHALLENGE_WINDOW_CLOSED`."

        Design: Corner/validations/circulation_deadline_boundary_and_closed_challenge_window
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={"jurisdiction_code": "SOS-W2"},
            counties=[("ALPHA", 20)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
        )
        petition_id = world["petition"]["id"]
        set_clock(FILING_CLOCK)
        file_batch_with_lines(world, ["VA1"])

        assert read_petition(petition_id)["status"] == "CLEARED"
        validate_error(
            api_client.create_challenge(
                petition_id,
                {
                    "challenger_name": "Concerned Elector",
                    "grounds": "COUNT_ERROR",
                    "statement": "Filed far too early.",
                },
                make_challenger_headers(),
            ),
            "ERR_CHALLENGE_WINDOW_CLOSED",
            409,
        )

        filed = close_circulation(petition_id)
        assert filed["status"] == "SIGNATURES_FILED"
        validate_error(
            api_client.create_challenge(
                petition_id,
                {
                    "challenger_name": "Concerned Elector",
                    "grounds": "FORMAT_DEFECT",
                    "statement": "Still too early.",
                },
                make_challenger_headers(),
            ),
            "ERR_CHALLENGE_WINDOW_CLOSED",
            409,
        )

        assert read_petition(petition_id)["challenge_status"] == "NONE"
        challenges, meta = validate_paginated(
            api_client.list_challenges(
                make_sos_admin_headers(), params={"petition_id": petition_id}
            )
        )
        assert challenges == []
        assert meta["total_count"] == 0, "a refused filing leaves no challenge behind"


class TestCountyDistributionGateBlocksCertification:
    """Statewide sufficiency is not enough: the geographic quota counts
    qualifying counties, and a county with no surviving batch never
    participates."""

    def test_a_sufficient_petition_with_one_qualifying_county_cannot_certify(self):
        """The standard demands two qualifying counties; only ALPHA holds a
        batch, so the report carries a single participating county and `CERTIFY`
        is refused.

        PRD §3.8: "The third gate is county distribution, and it applies **only**
        to the `CERTIFY` path: the petition's `qualifying_county_count` must be
        at or above the standard's `required_qualifying_counties`, else the
        request is refused with `ERR_COUNTY_DISTRIBUTION_UNMET`."

        PRD §3.6: "Only counties reachable from the petition's non-terminal
        batches participate."

        Design: Corner/validations/county_distribution_gate_blocks_certification
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={
                "jurisdiction_code": "SOS-Q",
                "signature_pct_bps": 100,
                "sufficiency_upper_bps": 10000,
                "required_qualifying_counties": 2,
            },
            counties=[("ALPHA", 20), ("BRAVO", 40)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
        )
        petition_id = world["petition"]["id"]
        assert world["petition"]["required_valid_signatures"] == 1
        alpha_id = world["counties"]["ALPHA"]["id"]

        set_clock(FILING_CLOCK)
        record = file_batch_with_lines(world, ["VA1"], county_code="ALPHA")
        close_circulation(petition_id)
        opened = open_round(petition_id, round_type="RANDOM_SAMPLE")
        validate_line(record["lines"][0]["id"], alpha_id)
        closed = tally_round(opened["id"])

        assert closed["determination"] == "SUFFICIENT"
        assert closed["validity_rate_bps"] == 10000
        pending = read_petition(petition_id)
        assert pending["status"] == "PENDING_CERTIFICATION"
        assert pending["projected_valid_count"] == 1
        assert pending["qualifying_county_count"] == 1

        report = validate_success(
            api_client.get_distribution_report(petition_id, make_examiner_headers())
        )
        assert report["petition_id"] == petition_id
        assert report["required_qualifying_counties"] == 2
        assert report["qualifying_county_count"] == 1
        assert [row["county_code"] for row in report["counties"]] == ["ALPHA"], (
            "BRAVO holds no batch of this petition and is out of the denominator"
        )
        alpha_row = report["counties"][0]
        assert alpha_row["distribution_minimum"] == 1, "ceil(20 * 500 / 10000)"
        assert alpha_row["credited_count"] == 1, "floor(1 * 10000 / 10000)"
        assert alpha_row["qualifies"] is True

        validate_error(
            api_client.issue_determination(
                petition_id, {"determination": "CERTIFY"}, make_examiner_headers("exam-2")
            ),
            "ERR_COUNTY_DISTRIBUTION_UNMET",
            409,
        )
        assert read_petition(petition_id)["status"] == "PENDING_CERTIFICATION", (
            "a petition concentrated in too few counties is stuck, not failed"
        )
