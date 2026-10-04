"""Community fiscal ledger: recognition allocation and conserved quantities.

Covers the dual-variant recognition pair, the compensation pair on travel
funding, and the ledger projection read.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_ledger_identity,
    create_active_agreement_with_record,
    create_complex,
    create_corpus_member,
    create_published_group,
    create_settled_sponsorship,
    get_agreement,
    get_host_community_record,
    get_ledger,
    get_sponsorship,
    register_player,
    set_test_clock,
    validate_error,
    validate_success,
)


def _complex_with_active_agreement(tickets=None, **ag_overrides):
    set_test_clock()
    complex_ = create_complex()
    agreement, record = create_active_agreement_with_record(
        complex_["id"], tickets=tickets, **ag_overrides)
    return complex_, agreement, record


def test_recognize_raises_recognition_allocation_and_void_restores_it():
    """PRD 3.7: "The recognition amount is the sum of two products — the
    sponsorship's `sponsorship_major_league_base_cents` multiplied by the major
    equivalents multiplied by the affected contribution, and the sponsorship's
    `sponsorship_minor_league_base_cents` multiplied by the minor equivalents
    multiplied by the same contribution, floor-divided once by one thousand."
    PRD 2.11: "recognizing a sponsorship and then voiding that settlement must
    leave `ledger_gap_cents` exactly at its pre-settlement value"

    Design: Difficulty/dual_variant_calc/recognition_raise_and_void_are_equal_and_opposite
    """
    complex_, _agreement, record = _complex_with_active_agreement(
        tickets=2, ticket_price_cents=2500)
    create_corpus_member(complex_["id"], roster_bucket="MAJOR")
    sponsorship = create_settled_sponsorship(record["id"], committed_cents=20000)

    before = get_ledger(record["id"])

    validate_success(api_client.recognize_sponsorship(
        sponsorship["id"], TEST_USERS["community_liaison_headers"]))

    after_recognize = get_ledger(record["id"])
    assert after_recognize["recognition_funded_cents"] == 62500, (
        "recognition_funded_cents must be 62500 for the single-major-member corpus"
    )
    assert after_recognize["community_ledger_cents"] == 5000
    assert after_recognize["ledger_gap_cents"] == -57500

    validate_success(api_client.void_settlement(
        sponsorship["id"], TEST_USERS["community_liaison_headers"]))

    after_void = get_ledger(record["id"])
    assert after_void["recognition_funded_cents"] == 0
    assert after_void["ledger_gap_cents"] == before["ledger_gap_cents"]
    assert_ledger_identity(after_void)
    sponsorship_row = get_sponsorship(sponsorship["id"])
    assert sponsorship_row["reconciliation_status"] == "SETTLEMENT_VOIDED"
    assert sponsorship_row["fulfillment_completed"] is False


def test_the_recognition_tier_multiplier_selects_the_raised_allocation():
    """PRD 3.7: "A match-points figure is that weight sum multiplied by a tier
    multiplier expressed in per-mille — 100 for a `LOCAL` sponsor, 130 for
    `REGIONAL` and 165 for `NATIONAL` — and floor-divided by ten. A
    commitment-points figure is the sponsorship's `committed_amount_cents`
    floor-divided by one hundred, capped at two thousand."

    Design: Difficulty/dual_variant_calc/recognition_raise_and_void_are_equal_and_opposite
    """
    complex_, _agreement, record = _complex_with_active_agreement()
    create_corpus_member(complex_["id"], roster_bucket="MAJOR")
    sponsorship = create_settled_sponsorship(
        record["id"], committed_cents=20000, tier="REGIONAL")

    validate_success(api_client.recognize_sponsorship(
        sponsorship["id"], TEST_USERS["community_liaison_headers"]))

    after = get_ledger(record["id"])
    assert after["recognition_funded_cents"] == 66250, (
        "a REGIONAL tier over a single MAJOR member yields 66250 cents"
    )
    assert_ledger_identity(after)


def test_void_settlement_reverses_the_recognition_and_returns_the_gap():
    """PRD 3.7: "Voiding reverses the settlement and everything built on it."
    PRD 3.7: "because the void recomputes the recognition amount from the corpus
    state at void time, a recognise followed by a void leaves
    `recognition_funded_cents` exactly at its pre-recognition value for identical
    corpus inputs."

    Design: Difficulty/compensating_invariant/sponsorship_void_returns_the_recognition_allocation_to_its_pre_recognize_value
    """
    complex_, agreement, record = _complex_with_active_agreement()
    create_corpus_member(complex_["id"], roster_bucket="MAJOR")
    create_corpus_member(complex_["id"], roster_bucket="MINOR")
    sponsorship = create_settled_sponsorship(record["id"], committed_cents=20000)

    pre = get_ledger(record["id"])
    api_client.recognize_sponsorship(sponsorship["id"], TEST_USERS["community_liaison_headers"])
    mid = get_ledger(record["id"])
    assert mid["recognition_funded_cents"] == 164500
    assert mid["ledger_gap_cents"] == -164500

    validate_success(api_client.void_settlement(
        sponsorship["id"], TEST_USERS["community_liaison_headers"]))

    post = get_ledger(record["id"])
    assert post["recognition_funded_cents"] == pre["recognition_funded_cents"]
    assert post["ledger_gap_cents"] == 20000
    # an agreement with nothing on sale slides back to DRAFT on the reversal
    assert get_agreement(agreement["id"])["agreement_status"] == "DRAFT"


def test_the_recognition_void_writes_off_the_full_allocation_and_the_fulfilment():
    """PRD 3.7: "From `SETTLED` and from `RECOGNIZED` alike, the sponsorship
    moves to `SETTLEMENT_VOIDED` and `fulfillment_completed` returns to false."
    PRD 3.7: "From `RECOGNIZED` the same recomputations run, with
    `recognition_funded_cents` recomputed so as to exclude this sponsorship's
    post."

    Design: Difficulty/compensating_invariant/sponsorship_void_returns_the_recognition_allocation_to_its_pre_recognize_value
    """
    complex_, _agreement, record = _complex_with_active_agreement()
    create_corpus_member(complex_["id"], roster_bucket="MAJOR")
    create_corpus_member(complex_["id"], roster_bucket="MINOR")
    sponsorship = create_settled_sponsorship(record["id"], committed_cents=20000)

    pre = get_ledger(record["id"])
    assert pre["recognition_funded_cents"] == 0
    assert pre["ledger_gap_cents"] == 20000

    validate_success(api_client.recognize_sponsorship(
        sponsorship["id"], TEST_USERS["community_liaison_headers"]))
    mid = get_ledger(record["id"])
    assert mid["recognition_funded_cents"] == 164500
    assert mid["ledger_gap_cents"] == -164500

    validate_success(api_client.void_settlement(
        sponsorship["id"], TEST_USERS["community_liaison_headers"]))

    post = get_ledger(record["id"])
    assert post["recognition_funded_cents"] == 0
    assert post["ledger_gap_cents"] == 20000
    assert post["recognized_sponsorship_count"] == 0
    row = get_sponsorship(sponsorship["id"])
    assert row["reconciliation_status"] == "SETTLEMENT_VOIDED"
    assert row["fulfillment_completed"] is False


def test_settled_but_unrecognized_sponsorship_leaves_the_gap_at_its_ledger():
    """PRD 2.11: "The `ledger_gap_cents` is `community_ledger_cents` less
    `recognition_funded_cents`."

    Design: Corner/endpoints/host_community_ledger_projection_matches_the_underlying_rows
    """
    _complex, _agreement, record = _complex_with_active_agreement(
        tickets=25, ticket_price_cents=100)
    create_settled_sponsorship(record["id"], committed_cents=10000)

    ledger = get_ledger(record["id"])
    assert ledger["ticketing_revenue_cents"] == 2500
    assert ledger["sponsorship_revenue_cents"] == 10000
    assert ledger["sponsorship_recorded_cents"] == 10000
    assert ledger["community_ledger_cents"] == 12500
    assert ledger["recognition_funded_cents"] == 0
    assert ledger["ledger_gap_cents"] == 12500
    assert ledger["settled_sponsorship_count"] == 1
    assert ledger["recognized_sponsorship_count"] == 0
    assert_ledger_identity(ledger)


def test_recognition_corpus_excludes_a_player_with_no_group_counts():
    """PRD 3.7: "Entities with both counts at zero, or a negative sum, are
    excluded from the corpus entirely. When the corpus is empty the recognition
    amount is zero and the recognition is still recorded against the
    sponsorship."

    Design: Corner/calculations/recognition_corpus_excludes_entities_with_no_group_counts
    """
    _complex, agreement, record = _complex_with_active_agreement()
    # a player with no group assignments at all, so the corpus stays empty
    register_player(_complex["id"], full_name="Corpus Empty", idp_number="IDP-61401")
    sponsorship = create_settled_sponsorship(record["id"], committed_cents=20000)

    validate_success(api_client.recognize_sponsorship(
        sponsorship["id"], TEST_USERS["community_liaison_headers"]))

    ledger = get_ledger(record["id"])
    assert ledger["recognition_funded_cents"] == 0
    assert ledger["sponsorship_recorded_cents"] == 20000
    # no termination occurred, so the live agreement stays ACTIVE
    assert get_agreement(agreement["id"])["agreement_status"] == "ACTIVE"


def test_voiding_a_settlement_under_a_restricted_posture_is_refused():
    """PRD 2.11: "Fiscal operations are locked whenever the owning complex is
    not in the `NORMAL` posture; voiding a settlement under a restricted or
    closed complex is refused with `ERR_POSTURE_BLOCKS_FISCAL` (HTTP 409)."

    Design: Corner/errors/settlement_void_is_blocked_by_a_non_normal_posture
    """
    set_test_clock()
    complex_ = create_complex(facility_capacity_units=100)
    _agreement, record = create_active_agreement_with_record(complex_["id"], tickets=None)
    sponsorship = create_settled_sponsorship(record["id"], committed_cents=20000)
    # a published group sized to drive the posture to FIELD_RESTRICTED
    create_published_group(complex_["id"], capacity_units=96)

    validate_error(
        api_client.void_settlement(sponsorship["id"], TEST_USERS["community_liaison_headers"]),
        ApiErrorId.ERR_POSTURE_BLOCKS_FISCAL,
    )

    assert get_sponsorship(sponsorship["id"])["reconciliation_status"] == "SETTLED"
    assert get_host_community_record(record["id"])["sponsorship_revenue_cents"] == 20000