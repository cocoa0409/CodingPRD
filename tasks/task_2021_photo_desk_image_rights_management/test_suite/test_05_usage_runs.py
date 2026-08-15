"""Usage runs: the compliance gate, embargo/window boundaries, per-line royalty
rounding, and the tier threshold (PRD §3.7, §2.6)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_usage_run,
    create_accepted_assignment,
    create_active_license,
    create_draft_license,
    create_payment_run,
    get_image_fresh,
    ingest_cleared_wire_image,
    ingest_wire_image,
    intake_claim,
    make_rights_manager_headers,
    move_claim_under_review,
    record_usage_run,
    usage_run_payload,
    validate_error,
    validate_success,
)


def test_usage_run_record_immutable_no_version(api, rights_manager_headers):
    """PRD §2.5: "The `UsageRun` resource is the single exception: it is an
    immutable ledger entry carrying `id` and `created_at` only. It has no
    `updated_at` and no `version` field." PRD §3.7: "For wire and stock images,
    whose `photographer_id` is null, no desk royalty is owed and `royalty_cents`
    is zero."

    Design: Corner/entities/usage_run_record_immutable_no_version
    """
    image = ingest_cleared_wire_image()
    lic = create_active_license(image["id"])

    resp = api.create_usage_run(
        image["id"], usage_run_payload(lic["id"]), rights_manager_headers,
    )
    run = validate_success(resp, 201)
    assert_usage_run(run)
    assert run["royalty_cents"] == 0, "a WIRE image owes no desk royalty"


def test_usage_run_at_valid_to_allowed_then_violation(api, rights_manager_headers):
    """PRD §3.7: "`published_at` must fall within the license's window inclusive
    at both ends, so a publication exactly at `valid_to` is allowed
    (`ERR_LICENSE_WINDOW_VIOLATION`)"."

    Design: Corner/validations/usage_run_at_valid_to_allowed_then_violation
    """
    image = ingest_cleared_wire_image()
    lic = create_active_license(
        image["id"], usage_scope="DIGITAL",
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-08-05T00:00:00Z",
    )

    at_boundary = api.create_usage_run(
        image["id"],
        usage_run_payload(lic["id"], story_slug="flood-edge",
                          published_at="2026-08-05T00:00:00Z"),
        rights_manager_headers,
    )
    run = validate_success(at_boundary, 201)
    assert_usage_run(run)

    resp = api.create_usage_run(
        image["id"],
        usage_run_payload(lic["id"], story_slug="flood-late",
                          published_at="2026-08-05T00:00:01Z"),
        rights_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_WINDOW_VIOLATION)


def test_usage_run_scope_mismatch_rejected(api, rights_manager_headers):
    """PRD §3.7: "the run's `channel` must equal the license's `usage_scope`
    (`ERR_SCOPE_NOT_LICENSED`)"."

    Design: Corner/validations/usage_run_scope_mismatch_rejected
    """
    image = ingest_cleared_wire_image()
    lic = create_active_license(image["id"], usage_scope="DIGITAL")
    resp = api.create_usage_run(
        image["id"],
        usage_run_payload(lic["id"], channel="PRINT", story_slug="flood-print"),
        rights_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_LICENSED)


def test_usage_run_license_image_mismatch_rejected(api, rights_manager_headers):
    """PRD §3.7: "the named license must belong to the path's image
    (`ERR_LICENSE_IMAGE_MISMATCH`)"."

    Design: Corner/validations/usage_run_license_image_mismatch_rejected
    """
    image_a = ingest_cleared_wire_image()
    image_b = ingest_cleared_wire_image(caption="Rescue boats on the river")
    lic = create_active_license(image_a["id"], usage_scope="DIGITAL")

    resp = api.create_usage_run(
        image_b["id"],
        usage_run_payload(lic["id"], story_slug="flood-boats"),
        rights_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_IMAGE_MISMATCH)


def test_usage_run_with_draft_license_rejected(api, rights_manager_headers):
    """PRD §3.7: "the license must be `ACTIVE` — `DRAFT`, `EXPIRED`, and `REVOKED`
    licenses cannot authorize publication (`ERR_LICENSE_NOT_ACTIVE`)"."

    Design: Corner/validations/usage_run_with_draft_license_rejected
    """
    image = ingest_cleared_wire_image()
    lic = create_draft_license(image["id"], usage_scope="DIGITAL")
    assert lic["status"] == "DRAFT"

    resp = api.create_usage_run(
        image["id"], usage_run_payload(lic["id"], story_slug="flood-draft"),
        rights_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / embargo_exact_instant_publish_allowed
# ---------------------------------------------------------------------------

def _setup_embargoed_image_with_license():
    image = ingest_cleared_wire_image(
        caption="Embargoed protest scene downtown",
        embargo_until="2026-08-05T00:00:00Z",
    )
    lic = create_active_license(image["id"], usage_scope="DIGITAL")
    return image, lic


def test_publish_one_second_before_embargo_rejected(api, rights_manager_headers):
    """PRD §3.7: "`published_at` must not be strictly before the image's
    `embargo_until`, with publication exactly at the embargo instant allowed
    (`ERR_EMBARGO_ACTIVE`)"."

    Design: Difficulty/boundary_precision_check/embargo_exact_instant_publish_allowed
    """
    image, lic = _setup_embargoed_image_with_license()
    resp = api.create_usage_run(
        image["id"],
        usage_run_payload(lic["id"], story_slug="protest-early",
                          published_at="2026-08-04T23:59:59Z"),
        rights_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_EMBARGO_ACTIVE)


def test_publish_exactly_at_embargo_instant_allowed(api, rights_manager_headers):
    """PRD §3.3: "The `embargo_until` field, when set, bars publication strictly
    before that instant; a publication exactly at the embargo instant is allowed,
    and a null `embargo_until` means no embargo."

    Design: Difficulty/boundary_precision_check/embargo_exact_instant_publish_allowed
    """
    image, lic = _setup_embargoed_image_with_license()
    run = record_usage_run(
        image["id"], lic["id"], story_slug="protest-lifted",
        published_at="2026-08-05T00:00:00Z",
    )
    assert_usage_run(run)

    after = get_image_fresh(image["id"])
    assert after["times_used"] == 1
    assert after["status"] == "PUBLISHED", (
        "the first accepted run moves the image CLEARED -> PUBLISHED"
    )


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / state_error_beats_embargo_temporal
# ---------------------------------------------------------------------------

def test_editorial_gate_surfaces_before_embargo_on_usage_run(api, rights_manager_headers):
    """PRD §2.8: "Within a single endpoint, these priorities resolve ties: for
    example, on license activation the release gate surfaces before the
    exclusivity conflict, which surfaces before the budget check; on a usage-run
    creation, embargo, window, restriction, referential, scope, and license-active
    checks are reported in that relative order after the editorial gate."

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_embargo_temporal
    """
    # W1 violates the editorial gate (INGESTED) AND the embargo at published_at.
    w1 = ingest_wire_image(
        caption="Embargoed protest scene downtown",
        embargo_until="2026-09-01T00:00:00Z",
    )
    # W2 supplies a valid ACTIVE DIGITAL license (its image gate passes).
    w2 = ingest_cleared_wire_image()
    lic = create_active_license(w2["id"], usage_scope="DIGITAL",
                                valid_to="2026-12-31T23:59:59Z")

    resp = api.create_usage_run(
        w1["id"],
        usage_run_payload(lic["id"], story_slug="protest-embargo",
                          published_at="2026-08-20T00:00:00Z"),
        rights_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_IMAGE_NOT_CLEARED)


def test_embargo_fires_when_editorial_gate_passes(api, rights_manager_headers):
    """PRD §3.7: "`published_at` must not be strictly before the image's
    `embargo_until`, with publication exactly at the embargo instant allowed
    (`ERR_EMBARGO_ACTIVE`)"."

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_embargo_temporal
    """
    image, lic = _setup_embargoed_image_with_license()
    # published_at must be strictly before embargo_until (2026-08-05) to trip the
    # embargo gate, while staying inside the license window [2026-08-01, 2026-08-31].
    resp = api.create_usage_run(
        image["id"],
        usage_run_payload(lic["id"], story_slug="protest-early",
                          published_at="2026-08-03T00:00:00Z"),
        rights_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_EMBARGO_ACTIVE)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / usage_run_blocked_by_open_claim
# ---------------------------------------------------------------------------

def _setup_image_with_open_claim():
    image = ingest_cleared_wire_image()
    lic = create_active_license(image["id"], usage_scope="DIGITAL")
    claim = intake_claim(
        image["id"], intaker_id="rm_alice",
        claimant_name="Pix Agency", description="Alleged unlicensed syndication",
        claimed_amount_cents=50000,
    )
    move_claim_under_review(claim["id"], user_id="rm_alice")
    return image, lic, claim


def test_usage_run_rejected_while_claim_open(api, rights_manager_headers):
    """PRD §3.7: "the image must have no open claim against it — its
    `restriction_status` must be `NONE` (`ERR_IMAGE_UNDER_CLAIM`)"."

    Design: Difficulty/cross_entity_state_dependency/usage_run_blocked_by_open_claim
    """
    image, lic, _claim = _setup_image_with_open_claim()
    assert get_image_fresh(image["id"])["restriction_status"] == "RESTRICTED"

    resp = api.create_usage_run(
        image["id"],
        usage_run_payload(lic["id"], story_slug="flood-follow",
                          published_at="2026-08-10T12:00:00Z"),
        rights_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_IMAGE_UNDER_CLAIM)


def test_usage_run_allowed_after_claim_dismissed(api, rights_manager_headers):
    """PRD §3.8: "As compensation, the image's `restriction_status` returns to
    `NONE` — but only when no other open claim (in `INTAKE`, `UNDER_REVIEW`,
    `SETTLEMENT_OFFERED`, `COUNTERED`, or `ESCALATED`) still references the
    image."

    Design: Difficulty/cross_entity_state_dependency/usage_run_blocked_by_open_claim
    """
    image, lic, claim = _setup_image_with_open_claim()
    payload = usage_run_payload(lic["id"], story_slug="flood-follow",
                                published_at="2026-08-10T12:00:00Z")
    validate_error(api.create_usage_run(image["id"], payload, rights_manager_headers),
                   ApiErrorId.ERR_IMAGE_UNDER_CLAIM)

    resolved = api.resolve_claim(
        claim["id"], {"outcome": "DISMISSED"}, make_rights_manager_headers("rm_bob"),
    )
    assert validate_success(resolved, 200)["status"] == "DISMISSED"
    assert get_image_fresh(image["id"])["restriction_status"] == "NONE"

    run = record_usage_run(image["id"], lic["id"], story_slug="flood-follow",
                           published_at="2026-08-10T12:00:00Z")
    assert_usage_run(run)


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / royalty_tier_tenth_use_boundary
# ---------------------------------------------------------------------------

def _setup_freelance_image_with_digital_license():
    """FREELANCE photographer (royalty rate 305) with an accepted assignment image
    and an ACTIVE DIGITAL license."""
    bundle = create_accepted_assignment(
        photographer_overrides={
            "full_name": "Tia Tier", "email": "tia@freelance.io",
            "photographer_type": "FREELANCE", "day_rate_cents": 20000,
            "per_image_fee_cents": 30000,
        },
        shoot_start="2026-08-10T09:00:00Z", shoot_end="2026-08-10T17:00:00Z",
    )
    image_id = bundle["images"][0]["id"]
    lic = create_active_license(
        image_id, usage_scope="DIGITAL",
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-09-30T00:00:00Z",
    )
    return bundle, image_id, lic


def test_uses_one_through_nine_earn_low_tier(api, finance_admin_headers, photo_editor_headers):
    """PRD §3.7: "The line's ordinal is the image's `times_used` before this run
    plus one — runs are counted in `created_at` order, ties broken by ascending
    `created_at`, never by id. The tier multiplier is 1.5 when the ordinal is ten
    or higher, else 1.0."

    Design: Difficulty/boundary_precision_check/royalty_tier_tenth_use_boundary
    """
    bundle, image_id, lic = _setup_freelance_image_with_digital_license()
    for day in range(15, 24):  # nine DIGITAL runs
        record_usage_run(image_id, lic["id"], headers=photo_editor_headers,
                         story_slug="election-night",
                         published_at=f"2026-08-{day:02d}T00:00:00Z")

    run = create_payment_run(bundle["photographer"]["id"])
    # round_half_up(305 x 1.25 x 1.0) = 381 per line; 9 x 381 = 3429.
    assert run["royalty_amount_cents"] == 3429, (
        f"nine low-tier lines must total 3429, got {run['royalty_amount_cents']}"
    )
    assert run["method"] == "ROYALTY"
    assert run["total_cents"] == 3429


def test_tenth_use_crosses_into_high_tier(api, finance_admin_headers, photo_editor_headers):
    """PRD §3.7: "The tier multiplier is 1.5 when the ordinal is ten or higher,
    else 1.0." PRD §3.9: "An overlapping `DRAFT` run is not an error; it is
    auto-voided to `VOIDED` as a supersession."

    Design: Difficulty/boundary_precision_check/royalty_tier_tenth_use_boundary
    """
    bundle, image_id, lic = _setup_freelance_image_with_digital_license()
    for day in range(15, 24):  # nine DIGITAL runs, ordinals 1..9
        record_usage_run(image_id, lic["id"], headers=photo_editor_headers,
                         story_slug="election-night",
                         published_at=f"2026-08-{day:02d}T00:00:00Z")
    run1 = create_payment_run(bundle["photographer"]["id"])
    assert run1["royalty_amount_cents"] == 3429

    tenth = record_usage_run(image_id, lic["id"], headers=photo_editor_headers,
                             story_slug="election-night",
                             published_at="2026-08-24T00:00:00Z")
    # ordinal 10: round_half_up(305 x 1.25 x 1.5) = round_half_up(571.875) = 572.
    assert tenth["royalty_cents"] == 572, (
        f"the tenth use must earn the high tier: expected 572, got {tenth['royalty_cents']}"
    )

    run2 = create_payment_run(bundle["photographer"]["id"])
    assert run2["royalty_amount_cents"] == 4001, (
        f"3429 + 572 = 4001, got {run2['royalty_amount_cents']}"
    )

    run1_after = validate_success(
        api_client.get_payment_run(run1["id"], finance_admin_headers), 200,
    )
    assert run1_after["status"] == "VOIDED", (
        "the superseded overlapping DRAFT run must be auto-voided"
    )


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / royalty_per_line_rounding_then_sum
# ---------------------------------------------------------------------------

def _setup_freelance_image_with_social_license():
    bundle = create_accepted_assignment(
        photographer_overrides={
            "full_name": "Rae Round", "email": "rae@freelance.io",
            "photographer_type": "FREELANCE", "day_rate_cents": 20000,
            "per_image_fee_cents": 30000,
        },
        shoot_start="2026-08-10T09:00:00Z", shoot_end="2026-08-10T17:00:00Z",
    )
    image_id = bundle["images"][0]["id"]
    lic = create_active_license(
        image_id, usage_scope="SOCIAL",
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-09-30T00:00:00Z",
    )
    return bundle, image_id, lic


def test_per_line_royalty_rounded_half_up_at_creation(api, rights_manager_headers):
    """PRD §3.7: "For assignment images, the line is the photographer's
    `royalty_rate_per_use_cents` multiplied by the channel multiplier — 1.0 for
    `PRINT`, 1.25 for `DIGITAL`, 0.5 for `SOCIAL`, 2.0 for `SYNDICATION` —
    multiplied by the tier, rounded half-up to integer cents."

    Design: Difficulty/combinatorial_formula/royalty_per_line_rounding_then_sum
    """
    _bundle, image_id, lic = _setup_freelance_image_with_social_license()
    run = record_usage_run(image_id, lic["id"], channel="SOCIAL", story_slug="county-fair",
                           published_at="2026-08-15T10:00:00Z")
    # round_half_up(305 x 0.5 x 1.0) = round_half_up(152.5) = 153.
    assert run["royalty_cents"] == 153, (
        f"each SOCIAL line must round half-up to 153, got {run['royalty_cents']}"
    )


def test_royalty_total_is_sum_of_rounded_lines(api, finance_admin_headers):
    """PRD §2.6: "Where a per-line royalty is summed into a total, each line is
    rounded half-up to integer cents first and the rounded lines are then summed;
    the system never sums raw values and then rounds."

    Design: Difficulty/combinatorial_formula/royalty_per_line_rounding_then_sum
    """
    bundle, image_id, lic = _setup_freelance_image_with_social_license()
    for day in (15, 16, 17):
        record_usage_run(image_id, lic["id"], channel="SOCIAL", story_slug="county-fair",
                         published_at=f"2026-08-{day}T10:00:00Z")

    run = create_payment_run(bundle["photographer"]["id"])
    # Sum-of-rounded-lines: 153 + 153 + 153 = 459.
    # Sum-then-round would give round_half_up(457.5) = 458.
    assert run["royalty_amount_cents"] == 459, (
        f"total must sum rounded lines (459), not round the raw sum (458); "
        f"got {run['royalty_amount_cents']}"
    )
    assert run["total_cents"] == 459
