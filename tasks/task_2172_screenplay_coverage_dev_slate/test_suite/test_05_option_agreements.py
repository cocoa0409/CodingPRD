"""Option agreements: windows, escalation bands, the net purchase price and lapse."""

from test_helpers import (
    BA_APPROVER,
    EXEC_ALPHA,
    ApiErrorId,
    assert_instant_equals,
    assert_option_agreement,
    create_option,
    create_project,
    create_property,
    execute_option,
    fetch_engagement,
    fetch_option,
    fetch_project,
    fetch_property,
    fetch_writer,
    make_clear_property,
    make_partial_property,
    milestones_for_engagement,
    property_version,
    set_clock,
    setup_clear_property_with_active_option,
    setup_development_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# The four-step pricing calculation
# ==========================================================================


def _two_options_with_opposite_credit_variants():
    """Identical money, one applicable to purchase and one not."""
    set_clock("2026-09-01T00:00:00Z")
    money = {
        "option_fee_cents": 5_000_000,
        "purchase_price_cents": 90_000_000,
        "initial_period_months": 18,
        "extension_period_months": 12,
        "extension_fee_cents": 2_500_000,
    }
    prop_a = make_clear_property(genre="THRILLER", title="Salt Flats")
    option_a = create_option(prop_a["id"], applicable_to_purchase=True, **money)
    execute_option(option_a["id"])
    create_project(prop_a["id"], option_a["id"], budget_cents=2_000_000_000)

    prop_b = make_clear_property(genre="THRILLER", title="Salt Flats II")
    option_b = create_option(prop_b["id"], applicable_to_purchase=False, **money)
    execute_option(option_b["id"])
    return {"property_b": prop_b, "option_a": option_a, "option_b": option_b}


def test_applicable_variant_credits_the_option_fee_against_the_price(api):
    """PRD 3.5: "Under the applicable variant — that is, when
    `applicable_to_purchase` is true — `applicable_credit_cents` is the smaller of
    those total fees paid and the escalated price multiplied by the step-three cap in
    basis points divided by ten thousand and floored to whole cents."
    PRD 3.5: "Finally, `net_purchase_due_cents` is `adjusted_purchase_price_cents`
    less `applicable_credit_cents`."

    Design: Difficulty/dual_variant_calc/option_net_purchase_applicable_vs_non_applicable_credit
    """
    ctx = _two_options_with_opposite_credit_variants()
    create_project(
        ctx["property_b"]["id"], ctx["option_b"]["id"], budget_cents=2_000_000_000
    )

    option_a = fetch_option(ctx["option_a"]["id"])
    assert_option_agreement(option_a)
    assert option_a["escalation_bps"] == 1500
    assert option_a["adjusted_purchase_price_cents"] == 103_500_000
    assert option_a["applicable_credit_cents"] == 5_000_000
    assert option_a["net_purchase_due_cents"] == 98_500_000


def test_non_applicable_variant_pays_the_fees_on_top_of_the_price(api):
    """PRD 3.5: "Under the non-applicable variant — when `applicable_to_purchase` is
    false — `applicable_credit_cents` is 0, so the studio pays its fees on top of the
    price rather than against it."
    PRD 3.5: "This calculation is re-run at four moments: when the agreement is
    executed, when it is extended, when it is exercised, and when a development
    project is created against it, because the newly linked `budget_cents` can move
    the escalation band and therefore everything downstream of it."

    Design: Difficulty/dual_variant_calc/option_net_purchase_applicable_vs_non_applicable_credit
    """
    ctx = _two_options_with_opposite_credit_variants()
    create_project(
        ctx["property_b"]["id"], ctx["option_b"]["id"], budget_cents=2_000_000_000
    )

    option_b = fetch_option(ctx["option_b"]["id"])
    assert option_b["escalation_bps"] == 1500
    assert option_b["adjusted_purchase_price_cents"] == 103_500_000
    assert option_b["applicable_credit_cents"] == 0
    assert option_b["net_purchase_due_cents"] == 103_500_000

    option_a = fetch_option(ctx["option_a"]["id"])
    assert (
        option_b["net_purchase_due_cents"] - option_a["net_purchase_due_cents"]
        == 5_000_000
    ), "the only difference between the two agreements is applicable_to_purchase"


def _large_fee_option_without_a_project():
    set_clock("2026-09-01T00:00:00Z")
    prop = create_property(genre="SCIFI", title="Orbital Decay", material_type="BOOK")
    from test_helpers import file_document

    file_document(prop["id"], "CHAIN_OF_TITLE", "2026-03-01", True)
    file_document(prop["id"], "COPYRIGHT_CERT", "2026-03-02", True)
    file_document(prop["id"], "CLEARANCE_OPINION", "2026-03-03", True)
    option = create_option(
        prop["id"],
        option_fee_cents=60_000_000,
        purchase_price_cents=90_000_000,
        initial_period_months=24,
        applicable_to_purchase=True,
    )
    execute_option(option["id"])
    return {"property": prop, "option": option}


def test_credit_cap_tier_is_keyed_on_the_escalated_price(api):
    """PRD 3.5: "Let the escalated price from step two select a cap in basis points:
    below two hundred and fifty thousand dollars — 25,000,000 cents — the cap is 10000
    basis points, meaning the full price may be credited; from two hundred and fifty
    thousand dollars up to but not including one million dollars — 25,000,000 up to
    100,000,000 cents — the cap is 7500 basis points; and at one million dollars or
    above it is 5000 basis points."
    PRD 3.5: "The order matters, because step three keys its tier on the *escalated*
    price produced by step two rather than on the raw `purchase_price_cents`, and
    reading it the other way round gives a different and wrong answer."

    Design: Difficulty/combinatorial_formula/option_credit_cap_tier_keyed_on_escalated_price
    """
    ctx = _large_fee_option_without_a_project()
    create_project(ctx["property"]["id"], ctx["option"]["id"], budget_cents=2_000_000_000)

    option = fetch_option(ctx["option"]["id"])
    assert option["escalation_bps"] == 1500
    assert option["adjusted_purchase_price_cents"] == 103_500_000
    assert option["applicable_credit_cents"] == 51_750_000, (
        "5000 bps of the escalated 103500000 caps the 60000000 of fees paid"
    )
    assert option["net_purchase_due_cents"] == 51_750_000


def test_credit_cap_keyed_on_the_raw_price_would_give_a_different_answer(api):
    """PRD 3.5: "If no development project is linked to this agreement,
    `escalation_bps` is 0."
    PRD 3.5: "`adjusted_purchase_price_cents` is `purchase_price_cents` multiplied by
    ten thousand plus `escalation_bps`, divided by ten thousand, with the result
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/option_credit_cap_tier_keyed_on_escalated_price
    """
    ctx = _large_fee_option_without_a_project()

    before = fetch_option(ctx["option"]["id"])
    assert before["escalation_bps"] == 0, "no project is linked yet"
    assert before["adjusted_purchase_price_cents"] == 90_000_000

    create_project(ctx["property"]["id"], ctx["option"]["id"], budget_cents=2_000_000_000)
    after = fetch_option(ctx["option"]["id"])

    assert after["applicable_credit_cents"] != 60_000_000, (
        "keying the cap on the raw 90000000 would credit the whole fee"
    )
    assert after["net_purchase_due_cents"] != 43_500_000, (
        "keying the cap on the raw price gives the wrong 43500000"
    )
    assert after["net_purchase_due_cents"] == 51_750_000


def test_option_escalation_band_is_inclusive_at_two_billion_cents(api):
    """PRD 3.5: "If no development project is linked to this agreement,
    `escalation_bps` is 0. Otherwise the linked project's `budget_cents` selects a
    band: below twenty million dollars — that is, below 2,000,000,000 cents — the
    escalation is 0 basis points; from twenty million dollars up to but not including
    sixty million dollars — that is, from 2,000,000,000 cents up to 6,000,000,000
    cents — the escalation is 1500 basis points; and at sixty million dollars or above
    it is 2500 basis points."
    PRD 3.6: "The writer budget cap is a fixed 12 percent of the production budget:
    `writer_budget_cap_cents` is `budget_cents` multiplied by 1200 basis points,
    divided by ten thousand, floored to whole cents."

    Design: Corner/calculations/option_escalation_band_inclusive_at_two_billion_budget
    """
    set_clock("2026-09-01T00:00:00Z")
    low = setup_clear_property_with_active_option(
        genre="DRAMA", title="Band Edge Low",
        option_overrides={"applicable_to_purchase": True},
    )
    project_low = create_project(
        low["property"]["id"], low["option"]["id"], budget_cents=1_999_999_999
    )
    high = setup_clear_property_with_active_option(
        genre="DRAMA", title="Band Edge Exact",
        option_overrides={"applicable_to_purchase": True},
    )

    project_high = create_project(
        high["property"]["id"], high["option"]["id"], budget_cents=2_000_000_000
    )

    option_low = fetch_option(low["option"]["id"])
    assert option_low["escalation_bps"] == 0, "one cent under the band floor"
    assert option_low["adjusted_purchase_price_cents"] == 90_000_000
    assert option_low["applicable_credit_cents"] == 5_000_000
    assert option_low["net_purchase_due_cents"] == 85_000_000

    option_high = fetch_option(high["option"]["id"])
    assert option_high["escalation_bps"] == 1500, "the band floor is inclusive"
    assert option_high["adjusted_purchase_price_cents"] == 103_500_000
    assert option_high["net_purchase_due_cents"] == 98_500_000

    assert fetch_project(project_low["id"])["writer_budget_cap_cents"] == 239_999_999
    assert fetch_project(project_high["id"])["writer_budget_cap_cents"] == 240_000_000


def test_option_extend_moves_the_end_instant_and_recomputes_the_net_due(api):
    """PRD 3.5: "On success `extension_exercised` becomes true, `option_end_at`
    advances by `extension_period_months` further calendar months, and
    `net_purchase_due_cents` is recomputed — the extension fee now counts among the
    fees paid, so an applicable-credit agreement's net due typically falls."
    PRD 3.5: "Total option fees paid so far are `option_fee_cents`, plus
    `extension_fee_cents` if and only if `extension_exercised` is true."

    Design: Corner/state_machines/option_extend_moves_end_date_and_recomputes_net_purchase_due
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_clear_property_with_active_option(
        genre="DRAMA",
        title="Extension Granted",
        option_overrides={
            "extension_period_months": 12,
            "extension_fee_cents": 2_500_000,
            "applicable_to_purchase": True,
        },
    )
    before = fetch_option(ctx["option"]["id"])
    assert before["net_purchase_due_cents"] == 85_000_000

    resp = api.extend_option(ctx["option"]["id"], BA_APPROVER)
    data = validate_success(resp, 200)

    assert data["status"] == "EXTENDED"
    assert data["extension_exercised"] is True
    assert_instant_equals(
        data["option_end_at"], "2029-03-01T00:00:00Z", "option_end_at"
    )
    assert data["escalation_bps"] == 0
    assert data["adjusted_purchase_price_cents"] == 90_000_000
    assert data["applicable_credit_cents"] == 7_500_000
    assert data["net_purchase_due_cents"] == 82_500_000
    assert fetch_property(ctx["property"]["id"])["encumbrance_count"] == 1


# ==========================================================================
# The half-open option window
# ==========================================================================


def _property_with_incumbent_option():
    set_clock("2026-09-01T00:00:00Z")
    prop = make_clear_property(genre="HORROR", title="Back To Back")
    incumbent = create_option(
        prop["id"], initial_period_months=18, option_start_at="2026-09-01T00:00:00Z"
    )
    execute_option(incumbent["id"])
    return {"property": prop, "incumbent": incumbent}


def test_back_to_back_option_windows_do_not_collide(api):
    """PRD 3.5: "Back-to-back windows therefore do not collide — a candidate starting
    at precisely the instant an incumbent ends is admissible."
    PRD 3.5: "On success `option_end_at` is set to `option_start_at` advanced by
    `initial_period_months` calendar months under the clamping rule of Section 2.5,
    the four pricing fields are computed, and the property's `encumbrance_count`
    increments by one."

    Design: Difficulty/resource_temporal_overlap/option_window_half_open_adjacency_admitted_but_overlap_rejected
    """
    ctx = _property_with_incumbent_option()
    assert_instant_equals(
        fetch_option(ctx["incumbent"]["id"])["option_end_at"],
        "2028-03-01T00:00:00Z",
        "incumbent option_end_at",
    )

    adjacent = create_option(
        ctx["property"]["id"],
        option_fee_cents=4_000_000,
        purchase_price_cents=80_000_000,
        initial_period_months=12,
        option_start_at="2028-03-01T00:00:00Z",
    )
    data = validate_success(api.execute_option(adjacent["id"], BA_APPROVER), 200)

    assert data["status"] == "ACTIVE"
    assert_instant_equals(
        data["option_end_at"], "2029-03-01T00:00:00Z", "adjacent option_end_at"
    )
    assert fetch_property(ctx["property"]["id"])["encumbrance_count"] == 2


def test_overlapping_option_window_is_refused_on_execution(api):
    """PRD 3.5: "Option windows are half-open, running from `option_start_at`
    inclusive to `option_end_at` exclusive: a candidate conflicts with an incumbent
    when the candidate's `option_start_at` is strictly before the incumbent's
    `option_end_at` and the incumbent's `option_start_at` is strictly before the
    candidate's `option_end_at`."
    PRD 3.5: "Capacity on the property is one: a single conflicting incumbent is
    enough to refuse the execution with `ERR_OPTION_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/option_window_half_open_adjacency_admitted_but_overlap_rejected
    """
    ctx = _property_with_incumbent_option()
    adjacent = create_option(
        ctx["property"]["id"],
        option_fee_cents=4_000_000,
        purchase_price_cents=80_000_000,
        initial_period_months=12,
        option_start_at="2028-03-01T00:00:00Z",
    )
    execute_option(adjacent["id"])

    overlapping = create_option(
        ctx["property"]["id"],
        option_fee_cents=3_000_000,
        purchase_price_cents=70_000_000,
        initial_period_months=6,
        option_start_at="2028-02-01T00:00:00Z",
    )
    resp = api.execute_option(overlapping["id"], BA_APPROVER)
    validate_error(resp, ApiErrorId.ERR_OPTION_PERIOD_OVERLAP, 409)

    assert fetch_option(overlapping["id"])["status"] == "DRAFTED"
    assert fetch_property(ctx["property"]["id"])["encumbrance_count"] == 2


# ==========================================================================
# Execution, exercise and expiry gates
# ==========================================================================


def test_execute_option_on_unclear_chain_returns_rights_chain_incomplete(api):
    """PRD 3.5: "The property's `rights_chain_status` must equal `CLEAR`; anything
    else is `ERR_RIGHTS_CHAIN_INCOMPLETE`."
    PRD 3.5: "The new agreement is created in `DRAFTED` status with
    `extension_exercised` false, `escalation_bps` 0, `applicable_credit_cents` 0, and
    `option_end_at`, `adjusted_purchase_price_cents` and `net_purchase_due_cents` all
    still null."

    Design: Corner/errors/execute_option_on_unclear_chain_returns_rights_chain_incomplete
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = make_partial_property(
        genre="DRAMA", title="Two Of Three", material_type="BOOK"
    )
    option = create_option(prop["id"])

    resp = api.execute_option(option["id"], BA_APPROVER)
    validate_error(resp, ApiErrorId.ERR_RIGHTS_CHAIN_INCOMPLETE, 409)

    stored_property = fetch_property(prop["id"])
    assert stored_property["rights_chain_status"] == "PARTIAL"
    assert stored_property["verified_document_count"] == 2
    assert stored_property["encumbrance_count"] == 0

    stored_option = fetch_option(option["id"])
    assert stored_option["status"] == "DRAFTED"
    assert stored_option["option_end_at"] is None


def test_exercise_option_after_its_end_instant_returns_option_expired(api):
    """PRD 3.5: "The logical clock must be strictly before `option_end_at`, or the
    call is `ERR_OPTION_EXPIRED`."
    PRD 3.5: "On success `exercise_notice_at` is stamped from the logical clock,
    `net_purchase_due_cents` is recomputed, and the linked project's rights axis flips
    `OPTIONED → OWNED`."

    Design: Corner/validations/exercise_option_after_end_returns_option_expired
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_clear_property_with_active_option(
        genre="COMEDY", title="Lapsed Window",
        option_overrides={"initial_period_months": 1},
    )
    project = create_project(
        ctx["property"]["id"], ctx["option"]["id"], budget_cents=2_000_000_000
    )
    set_clock("2026-10-02T00:00:00Z")

    resp = api.exercise_option(ctx["option"]["id"], BA_APPROVER)
    validate_error(resp, ApiErrorId.ERR_OPTION_EXPIRED, 409)

    option = fetch_option(ctx["option"]["id"])
    assert option["status"] == "ACTIVE"
    assert_instant_equals(
        option["option_end_at"], "2026-10-01T00:00:00Z", "option_end_at"
    )
    assert option["exercise_notice_at"] is None
    assert fetch_project(project["id"])["rights_status"] == "OPTIONED"
    assert fetch_property(ctx["property"]["id"])["encumbrance_count"] == 1


def test_project_option_pair_from_different_properties_returns_option_mismatch(api):
    """PRD 3.6: "The agreement must belong to the same property as the one named, or
    the request is refused with `ERR_OPTION_MISMATCH`."

    Design: Corner/errors/project_option_pair_from_different_properties_returns_option_mismatch
    """
    set_clock("2026-09-01T00:00:00Z")
    unoptioned = create_property(genre="DRAMA", title="Property A")
    optioned = setup_clear_property_with_active_option(
        genre="DRAMA", title="Property B"
    )

    resp = api.create_development_project(
        {
            "property_id": unoptioned["id"],
            "option_agreement_id": optioned["option"]["id"],
            "budget_cents": 2_000_000_000,
            "slate_year": 2028,
        },
        EXEC_ALPHA,
    )
    validate_error(resp, ApiErrorId.ERR_OPTION_MISMATCH, 409)

    _, meta = validate_paginated(
        api.list_development_projects(EXEC_ALPHA, {"property_id": unoptioned["id"]})
    )
    assert meta["total_count"] == 0
    assert fetch_option(optioned["option"]["id"])["status"] == "ACTIVE"


# ==========================================================================
# The superseding create and its stale-version guard
# ==========================================================================


def test_stale_property_version_on_option_create_returns_stale_version(api):
    """PRD 2.7: "Each takes a non-optional version field in its request body carrying
    the client's last observed `version` of the parent row. If that value does not
    equal the parent's current `version`, the request is rejected with
    `ERR_STALE_VERSION` and HTTP 412, and nothing is created or superseded."
    PRD 2.7: "`POST /option-agreements` requires `expected_property_version`, matching
    the current `version` of the `LiteraryProperty` named by `property_id`."

    Design: Corner/cross_cutting_layers/occ_stale_property_version_on_option_create_returns_412
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = make_clear_property(genre="DRAMA", title="Stale View")
    observed_version = property_version(prop["id"])
    first = create_option(prop["id"], expected_property_version=observed_version)

    resp = api.create_option_agreement(
        {
            "property_id": prop["id"],
            "expected_property_version": observed_version,
            "option_fee_cents": 4_000_000,
            "purchase_price_cents": 80_000_000,
            "initial_period_months": 12,
            "option_start_at": "2026-09-01T00:00:00Z",
        },
        BA_APPROVER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    stored = fetch_option(first["id"])
    assert stored["status"] == "DRAFTED", "the rejected create supersedes nothing"
    assert stored["termination_reason"] is None
    _, meta = validate_paginated(
        api.list_option_agreements(BA_APPROVER, {"property_id": prop["id"]})
    )
    assert meta["total_count"] == 1


def test_option_create_with_a_fresh_version_supersedes_the_prior_draft(api):
    """PRD 3.5: "Every other agreement on the same property that is still in
    `DRAFTED` status is moved to `TERMINATED` with its `termination_reason` set to
    `SUPERSEDED_BY_NEW_DRAFT`, and the property's `version` increments by one."

    Design: Corner/cross_cutting_layers/option_create_supersedes_prior_draft_on_same_property
    """
    set_clock("2026-09-01T00:00:00Z")
    prop = make_clear_property(genre="DRAMA", title="Superseded Draft")
    first = create_option(prop["id"], expected_property_version=property_version(prop["id"]))

    resp = api.create_option_agreement(
        {
            "property_id": prop["id"],
            "expected_property_version": property_version(prop["id"]),
            "option_fee_cents": 6_000_000,
            "purchase_price_cents": 95_000_000,
            "initial_period_months": 24,
            "option_start_at": "2026-09-01T00:00:00Z",
        },
        BA_APPROVER,
    )
    second = validate_success(resp, 201)

    superseded = fetch_option(first["id"])
    assert superseded["status"] == "TERMINATED"
    assert superseded["termination_reason"] == "SUPERSEDED_BY_NEW_DRAFT"
    assert second["status"] == "DRAFTED"

    _, meta = validate_paginated(
        api.list_option_agreements(BA_APPROVER, {"property_id": prop["id"]})
    )
    assert meta["total_count"] == 2
    assert fetch_property(prop["id"])["encumbrance_count"] == 0


# ==========================================================================
# The five-link lapse cascade
# ==========================================================================


def _matured_option_with_attached_writer():
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(
        genre="SCIFI",
        title="Half-Life Harbor",
        option_overrides={"initial_period_months": 1},
        attach=True,
    )
    set_clock("2026-10-02T00:00:00Z")
    return ctx


def test_option_lapse_kills_the_project_on_both_axes(api):
    """PRD 3.5: "The lapse is admissible only when the logical clock is at or after
    `option_end_at`."
    PRD 3.5: "Link one: the property's `encumbrance_count` decrements by one."
    PRD 3.5: "Link two, caused by that loss of encumbrance: the linked project's
    `rights_status` becomes `LAPSED_RIGHTS`."
    PRD 3.5: "Link three, caused by link two: the project's `development_status`
    becomes `DEAD`, and every engagement on that project in `PROPOSED`, `ATTACHED` or
    `ACTIVE` status becomes `TERMINATED`."

    Design: Difficulty/transitive_cascade/option_lapse_cascades_five_links_to_writer_ledger
    """
    ctx = _matured_option_with_attached_writer()

    resp = api.lapse_option(ctx["option"]["id"], BA_APPROVER)
    data = validate_success(resp, 200)

    assert data["status"] == "LAPSED"
    assert fetch_property(ctx["property"]["id"])["encumbrance_count"] == 0

    project = fetch_project(ctx["project"]["id"])
    assert project["rights_status"] == "LAPSED_RIGHTS"
    assert project["development_status"] == "DEAD"
    assert project["committed_writer_fee_cents"] == 0
    assert fetch_engagement(ctx["engagement"]["id"])["status"] == "TERMINATED"


def test_option_lapse_voids_the_milestones_and_unwinds_the_writer_ledger(api):
    """PRD 3.5: "Link four, caused by link three: every milestone payment on those
    terminated engagements whose status is `SCHEDULED`, `DUE` or `APPROVED` becomes
    `VOIDED`."
    PRD 3.5: "Link five, caused by link four: each affected writer's
    `committed_fee_cents` is reduced by the summed `gross_amount_cents` of their voided
    rows, and their `active_engagement_count` is reduced by the number of their
    engagements that were terminated out of `ATTACHED` or `ACTIVE`."

    Design: Difficulty/transitive_cascade/option_lapse_cascades_five_links_to_writer_ledger
    """
    ctx = _matured_option_with_attached_writer()
    assert fetch_writer(ctx["writer"]["id"])["committed_fee_cents"] == 10_000_003

    validate_success(api.lapse_option(ctx["option"]["id"], BA_APPROVER), 200)

    rows = milestones_for_engagement(ctx["engagement"]["id"])
    assert len(rows) == 3
    assert all(row["status"] == "VOIDED" for row in rows), (
        f"Expected every milestone VOIDED, got {[r['status'] for r in rows]}"
    )
    assert sorted(row["gross_amount_cents"] for row in rows) == [
        3_000_000, 3_000_000, 4_000_003,
    ]

    writer = fetch_writer(ctx["writer"]["id"])
    assert writer["committed_fee_cents"] == 0
    assert writer["paid_fee_cents"] == 0
    assert writer["active_engagement_count"] == 0
