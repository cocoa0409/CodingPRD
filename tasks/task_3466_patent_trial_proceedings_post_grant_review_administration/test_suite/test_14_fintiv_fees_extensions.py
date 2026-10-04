"""Calculation corners: Fintiv variants and input set, per-track merits
thresholds, fee tiers, overage rounding precision, and the extension
deadline pair (PRD §3.3–§3.5, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    PANEL,
    accord,
    add_petitioned_patent,
    api_client,
    assert_petition,
    assert_same_instant,
    create_litigation_matter,
    create_petition_payload,
    decide_institution,
    file_brief,
    file_petition,
    get_petition,
    get_proceeding,
    new_world,
    patch_litigation_matter,
    per_ground_scores,
    request_extension,
    setup_instituted_proceeding,
    validate_error,
    validate_success,
    make_petitioner_headers,
)


def test_fintiv_provisional_score_at_filing_with_null_trial_date():
    """PRD §3.4: "the provisional variant, computed at filing (and refreshed
    on docket updates per §3.2) with each `trial_date` read as-is — a matter
    whose `trial_date` is null contributes no proximity points"."

    Design: Corner/calculations/fintiv_provisional_score_at_filing_with_null_trial_date
    """
    world = new_world(
        total_claims=3, petitioner_name="PN Corp", owner_name="ON Corp",
        matters=[{"complaint_served_date": "2025-12-01T00:00:00Z",
                  "court_name": "D. Del.", "docket_number": "1:25-cv-01200"}],
    )
    petition = file_petition(world["petitioner"]["id"], world["patent"]["id"],
                             challenged_claims=[1])
    # base 20 + proximity 0 (null trial_date) + investment 20 (274 days).
    assert petition["fintiv_score"] == 40


def test_fintiv_input_set_excludes_terminal_litigation_matters():
    """PRD §3.4: "The discretionary screen is the Fintiv score, computed from
    the litigation matters for the same patent that name the petitioner as
    defendant and stand in `ACTIVE` or `STAYED` status — matters that are
    `SETTLED`, `TRIAL_COMPLETED`, or `DISMISSED` are excluded from the input
    set. If no qualifying matter exists, the score is zero."

    Design: Corner/calculations/fintiv_input_set_excludes_terminal_litigation_matters
    """
    world = new_world(total_claims=3, petitioner_name="PO Corp",
                      owner_name="OO Corp")
    matter = create_litigation_matter(
        world["patent"]["id"], world["petitioner"]["id"],
        "2025-12-01T00:00:00Z", trial_date="2027-06-01T00:00:00Z",
        court_name="D. Del.", docket_number="1:25-cv-01201",
    )
    patch_litigation_matter(
        matter["id"],
        {"status": "DISMISSED",
         "expected_litigation_matter_version": matter["version"]},
    )
    # 274 days elapsed: under the time bar even though the dismissed matter
    # still counts for it (PRD §3.3).
    petition = file_petition(world["petitioner"]["id"], world["patent"]["id"],
                             challenged_claims=[1])
    assert petition["status"] == "FILED"
    assert petition["fintiv_score"] == 0


def test_pgr_threshold_51_denies_where_ipr_threshold_40_institutes():
    """PRD §3.4: "the threshold depends on the track: 40 for `IPR`, the
    reasonable-likelihood standard, and 51 for `PGR`, the
    more-likely-than-not standard."

    Design: Corner/calculations/pgr_threshold_51_denies_where_ipr_threshold_40_institutes
    """
    world = new_world(petitioner_name="PP Corp", owner_name="OP Corp")
    ipr = add_petitioned_patent(
        world, patent_number="US10001023A", challenged_claims=(1,),
        do_accord=True,
    )
    pgr = add_petitioned_patent(
        world, patent_number="US10001023B", challenged_claims=(1,),
        review_type="PGR",
        grounds=[{"claim_number": 1, "basis": "OTHER_STATUTORY"}],
        prior_art=[{"reference_type": "TESTIMONY",
                    "citation": "Decl. of J. Smith"}],
        do_accord=True,
    )
    ipr_decision = decide_institution(
        ipr["petition"]["id"], per_ground_scores((1, 45)), "judge-xena"
    )
    assert ipr_decision["outcome"] == "INSTITUTED"
    assert ipr_decision["threshold_used"] == 40
    pgr_decision = decide_institution(
        pgr["petition"]["id"],
        per_ground_scores((1, 45, "OTHER_STATUTORY")),
        "judge-yves",
    )
    assert pgr_decision["outcome"] == "DENIED_MERITS"
    assert pgr_decision["threshold_used"] == 51


def test_brief_overage_fee_round_half_up_precision():
    """PRD §3.5: "the brief's `overage_fee_cents` is that product rounded
    half-up to whole cents" — 5 overage pages cost round-half-up(1581.25) =
    1581 (rounds down), while 2 overage pages cost round-half-up(632.5) =
    633 (rounds up).

    Design: Corner/calculations/brief_overage_fee_round_half_up_precision
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 66}],
        lead_judge="judge-zack",
    )
    po = file_brief(world["proceeding"]["id"], "PO_RESPONSE", 95,
                    world["owner_headers"])
    assert po["overage_fee_cents"] == 1581
    reply = file_brief(world["proceeding"]["id"], "PETITIONER_REPLY", 47,
                       world["petitioner_headers"])
    assert reply["overage_fee_cents"] == 633


def test_petition_required_fee_tiers_at_twenty_claims():
    """PRD §3.3: "a base of 1,900,000 cents covers up to twenty challenged
    claims, and each challenged claim beyond twenty adds 15,000 cents. When
    `fee_paid_cents` falls below the required amount, the filing is rejected
    with `ERR_FEE_INSUFFICIENT` (HTTP 402)."

    Design: Corner/calculations/petition_required_fee_tiers_at_twenty_claims
    """
    world = new_world(petitioner_name="PR Corp", owner_name="OR Corp",
                      total_claims=25, patent_number="US10001025",
                      title="Manifold")
    claims = list(range(1, 22))  # 21 challenged claims
    base_only = create_petition_payload(
        patent_id=world["patent"]["id"],
        petitioner_id=world["petitioner"]["id"],
        challenged_claims=claims,
        fee_paid_cents=1_900_000,
        expected_patent_version=world["patent"]["version"],
    )
    resp = api_client.create_petition(base_only, world["petitioner_headers"])
    validate_error(resp, ApiErrorId.ERR_FEE_INSUFFICIENT, 402)
    # The failed filing does not bump the patent's version.
    assert api_client.get_patent(world["patent"]["id"], PANEL).json()["data"][
        "version"
    ] == world["patent"]["version"]
    exact = create_petition_payload(
        patent_id=world["patent"]["id"],
        petitioner_id=world["petitioner"]["id"],
        challenged_claims=claims,
        fee_paid_cents=1_915_000,  # 1,900,000 + 1 * 15,000
        expected_patent_version=world["patent"]["version"],
    )
    data = validate_success(
        api_client.create_petition(exact, world["petitioner_headers"]), 201
    )
    assert_petition(data)
    assert data["status"] == "FILED"


def test_fintiv_score_reconciles_when_litigation_trial_date_is_set():
    """PRD §3.2: "every one of these docket updates — and both of the
    cascades that can stay a matter — refreshes the provisional
    `fintiv_score` stored on each petition against the same patent that is
    still pending, meaning in `FILED` or `NOTICE_ACCORDED` status."

    Design: Corner/calculations/fintiv_score_reconciles_when_litigation_trial_date_is_set
    """
    world = new_world(
        total_claims=3, petitioner_name="PS Corp", owner_name="OS Corp",
        matters=[{"complaint_served_date": "2025-12-01T00:00:00Z",
                  "court_name": "E.D. Tex.", "docket_number": "2:25-cv-01300"}],
    )
    petition = file_petition(world["petitioner"]["id"], world["patent"]["id"],
                             challenged_claims=[1])
    assert petition["fintiv_score"] == 40  # trial_date null -> proximity 0
    matter = world["matters"][0]
    patch_litigation_matter(
        matter["id"],
        {"trial_date": "2027-06-01T00:00:00Z",
         "expected_litigation_matter_version": matter["version"]},
    )
    # 2027-06-01 is within the base projection (2027-09-01): 20+40+20 = 80.
    assert get_petition(petition["id"])["fintiv_score"] == 80


def test_extension_grant_recomputes_fixed_days_and_anniversary_variants():
    """PRD §3.8: "A granted extension adds 183 days to `fwd_due_date` and 6
    calendar months to `advisory_anniversary_date`, sets `extension_used` to
    true, and increments the proceeding's `version` by one."

    Design: Corner/calculations/extension_grant_recomputes_fixed_days_and_anniversary_variants
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 68}],
        lead_judge="judge-amy",
    )
    before = world["proceeding"]
    # Institution 2026-09-01: identical outside leap spans.
    assert_same_instant(before["fwd_due_date"], "2027-09-01T00:00:00Z",
                        "fwd_due_date")
    assert_same_instant(before["advisory_anniversary_date"],
                        "2027-09-01T00:00:00Z", "advisory_anniversary_date")
    after = request_extension(
        before["id"], world["owner_headers"],
        justification="Parallel claim construction dispute requires extended "
                      "expert engagement.",
    )
    assert_same_instant(after["fwd_due_date"], "2028-03-02T00:00:00Z",
                        "extended fwd_due_date")
    assert_same_instant(after["advisory_anniversary_date"],
                        "2028-03-01T00:00:00Z", "extended anniversary")
    assert after["extension_used"] is True
