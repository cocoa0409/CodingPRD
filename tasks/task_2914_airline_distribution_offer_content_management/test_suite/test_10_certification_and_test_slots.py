"""Certification: dual readiness variants, the decision gate and the slot rules."""

from test_helpers import (
    ADMIN_HEADERS,
    AGREEMENT_SIGNED,
    AGREEMENT_SUSPENDED,
    CERTIFICATION_CERTIFIED,
    CERTIFICATION_REVOKED,
    CERTIFICATION_TESTING,
    CERT_ENV_A,
    CERT_ENV_B,
    CERT_STATUS_CERTIFIED,
    CERT_STATUS_IN_CERTIFICATION,
    CERT_STATUS_UNCERTIFIED,
    DECISION_CERTIFY,
    DECISION_REVOKE,
    OFFER_CONSTRUCTED,
    OFFER_PUBLISHED,
    OFFER_WITHDRAWN,
    READINESS_PROVISIONAL,
    READINESS_STRICT,
    TEST_CANCELLED,
    TEST_FAILED,
    TEST_PASSED,
    TEST_SCHEDULED,
    ApiErrorId,
    agency_headers,
    assert_instant_equals,
    assert_readiness,
    factories as f,
    fixtures as fx,
    technology_partner_headers,
    validate_error,
)

SLOT_ONE = "2026-08-03T09:00:00.000Z"
SLOT_TWO = "2026-08-03T10:30:00.000Z"
SLOT_THREE = "2026-08-03T12:00:00.000Z"

CODE_AUTH = "AUTH_TOKEN"
CODE_SHOP = "SHOP_SEARCH"
CODE_ORDER = "ORDER_FLOW"


def _certification(api, env_code=CERT_ENV_A):
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = fx.create_alpha_agency(api)
    certification = fx.open_certification(
        api, partner["id"], channel["id"], env_code=env_code
    )
    assert certification["status"] == CERTIFICATION_TESTING
    assert certification["reserved_test_minutes"] == 0
    return channel, partner, certification


def _scored_population(api):
    """One failed mandatory test, one passed mandatory test and one passed option."""
    channel, partner, certification = _certification(api)
    failed = fx.schedule_test(
        api, certification["id"], partner["id"], CODE_AUTH, SLOT_ONE, 60, True
    )
    passed_mandatory = fx.schedule_test(
        api, certification["id"], partner["id"], CODE_SHOP, SLOT_TWO, 60, True
    )
    passed_option = fx.schedule_test(
        api, certification["id"], partner["id"], CODE_ORDER, SLOT_THREE, 60, False
    )
    fx.report_outcome(api, failed["id"], partner["id"], TEST_FAILED, 40)
    fx.report_outcome(api, passed_mandatory["id"], partner["id"], TEST_PASSED, 95)
    fx.report_outcome(api, passed_option["id"], partner["id"], TEST_PASSED, 88)
    return channel, partner, certification


def test_one_failed_mandatory_test_zeroes_strict_but_not_provisional(api):
    """PRD §3.8: "The `STRICT` variant, stored in `readiness_score_strict`, is 0 whenever
    `mandatory_failed_count` is greater than 0, and also 0 when no test has been
    considered at all; otherwise it is the sum over considered tests of that test's
    `score` multiplied by its weight, divided by the sum of those same weights, rounded
    half up to an integer."
    PRD §3.8: "The `PROVISIONAL` variant, stored in `readiness_score_provisional`, first
    drops every considered test that is both mandatory and failed from the population —
    removing it from the numerator **and** from the denominator — and is 0 when the
    remaining population is empty; otherwise it is the same weighted mean over the
    remaining tests, rounded half up."

    Design: Difficulty/dual_variant_calc/certification_readiness_strict_zeroes_while_provisional_clears_minimum
    """
    _channel, _partner, certification = _scored_population(api)

    scored = fx.read_certification(api, certification["id"])
    # PROVISIONAL: (95 * 3 + 88 * 1) / (3 + 1) = 373 / 4 = 93.25 -> 93.
    assert_readiness(
        scored,
        strict=0,
        provisional=93,
        mandatory_failed_count=1,
        reserved_test_minutes=0,
    )
    assert scored["status"] == CERTIFICATION_TESTING
    assert scored["certified_variant"] is None


def test_certify_gate_rejects_strict_and_accepts_provisional(api):
    """PRD §3.8: "A `CERTIFY` decision advances `TESTING → CERTIFIED` and is doubly
    gated: no test of the certification may still be in `SCHEDULED` — an outstanding slot
    makes the decision premature and yields `ERR_INVALID_STATE_TRANSITION` — and the
    readiness score of the variant named by `readiness_variant` must be at or above 80,
    with anything below reported as `ERR_READINESS_BELOW_MINIMUM`."
    PRD §3.8: "On success `certified_variant` records which variant was used, the
    partner's `certification_status` becomes `CERTIFIED` with the `DistributionPartner`'s
    `version` increasing by 1, and every agreement of that partner-and-channel pair
    sitting in `SUSPENDED` returns to `SIGNED`."

    Design: Difficulty/dual_variant_calc/certification_readiness_strict_zeroes_while_provisional_clears_minimum
    """
    _channel, partner, certification = _scored_population(api)

    refused = api.post_certification_decision(
        certification["id"],
        f.decision_payload(DECISION_CERTIFY, READINESS_STRICT),
        headers=ADMIN_HEADERS,
    )
    validate_error(refused, ApiErrorId.READINESS_BELOW_MINIMUM)
    assert fx.read_certification(api, certification["id"])["status"] == CERTIFICATION_TESTING
    assert fx.read_partner(api, partner["id"])["certification_status"] == (
        CERT_STATUS_IN_CERTIFICATION
    )

    certified = fx.record_decision(
        api, certification["id"], DECISION_CERTIFY, READINESS_PROVISIONAL
    )
    assert certified["status"] == CERTIFICATION_CERTIFIED
    assert certified["certified_variant"] == READINESS_PROVISIONAL
    assert certified["readiness_score_strict"] == 0
    assert certified["readiness_score_provisional"] == 93
    assert fx.read_partner(api, partner["id"])["certification_status"] == (
        CERT_STATUS_CERTIFIED
    )


def test_revoking_a_certified_partner_cascades_to_agreements_and_offers(api):
    """PRD §3.8: "Revoking from `CERTIFIED` runs the full four-hop cascade: hop one
    revokes the certification and cancels its scheduled slots; hop two, caused by hop one,
    sets the partner's `certification_status` to `UNCERTIFIED` and bumps the partner's
    `version`; hop three, caused by hop two — an uncertified partner loses content access
    — sets every agreement of that partner-and-channel pair in `SIGNED` to `SUSPENDED`;
    and hop four, caused by hop three, sets every offer of that partner-and-channel pair
    sitting in `CONSTRUCTED` or `PUBLISHED` to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/certification_revoke_cascades_partner_agreement_offer
    """
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = fx.create_alpha_agency(api)
    agreement = fx.create_signed_agreement(
        api, partner["id"], channel["id"], partner["version"]
    )
    certification = fx.certify_partner(api, partner["id"], channel["id"], score=100)
    assert certification["status"] == CERTIFICATION_CERTIFIED
    assert fx.read_partner(api, partner["id"])["certification_status"] == (
        CERT_STATUS_CERTIFIED
    )

    filing = fx.create_ndc_filing(api, fare_basis_code="YCERT01")
    headers = agency_headers(partner["id"])
    published = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    fx.publish_offer(api, published["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    constructed = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    assert constructed["status"] == OFFER_CONSTRUCTED

    before_partner = fx.read_partner(api, partner["id"])
    revoked = fx.record_decision(api, certification["id"], DECISION_REVOKE)
    assert revoked["status"] == CERTIFICATION_REVOKED

    after_partner = fx.read_partner(api, partner["id"])
    assert after_partner["certification_status"] == CERT_STATUS_UNCERTIFIED
    assert after_partner["version"] == before_partner["version"] + 1

    assert fx.read_agreement(api, agreement["id"])["status"] == AGREEMENT_SUSPENDED
    assert fx.read_offer(api, published["id"])["status"] == OFFER_WITHDRAWN
    assert fx.read_offer(api, constructed["id"])["status"] == OFFER_WITHDRAWN


def test_revoking_from_testing_cancels_slots_but_spares_the_commercial_chain(api):
    """PRD §3.8: "All three edges cancel the certification's remaining scheduled tests:
    every test in `SCHEDULED` becomes `CANCELLED` and `reserved_test_minutes` becomes 0."
    PRD §3.8: "Revoking from `TESTING` stops there — the partner was never certified, so
    there is no signed content standing on the certification."

    Design: Difficulty/transitive_cascade/certification_revoke_cascades_partner_agreement_offer
    """
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = fx.create_alpha_agency(api)
    agreement = fx.create_signed_agreement(
        api, partner["id"], channel["id"], partner["version"]
    )
    filing = fx.create_ndc_filing(api, fare_basis_code="YCERT02")
    headers = agency_headers(partner["id"])
    offer = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)

    certification = fx.open_certification(api, partner["id"], channel["id"])
    fx.schedule_test(api, certification["id"], partner["id"], CODE_AUTH, SLOT_ONE, 60, True)
    fx.schedule_test(api, certification["id"], partner["id"], CODE_SHOP, SLOT_TWO, 45, False)
    holding = fx.read_certification(api, certification["id"])
    assert holding["reserved_test_minutes"] == 105

    revoked = fx.record_decision(api, certification["id"], DECISION_REVOKE)
    assert revoked["status"] == CERTIFICATION_REVOKED
    assert revoked["reserved_test_minutes"] == 0

    tests = fx.read_connectivity_tests(api, certification["id"])
    assert len(tests) == 2
    assert {test["status"] for test in tests} == {TEST_CANCELLED}

    assert fx.read_partner(api, partner["id"])["certification_status"] == (
        CERT_STATUS_UNCERTIFIED
    )
    # No content was ever standing on this certification.
    assert fx.read_agreement(api, agreement["id"])["status"] == AGREEMENT_SIGNED
    assert fx.read_offer(api, offer["id"])["status"] == OFFER_PUBLISHED


SLOT_GAP_EXACT = "2026-08-03T10:15:00.000Z"   # 15 minutes after a 09:00 + 60 slot ends
SLOT_GAP_WIDER = "2026-08-03T10:16:00.000Z"   # 16 minutes after it ends


def _three_slots(api):
    """Two AUTH slots a wider-than-buffer gap apart plus one SHOP slot between them."""
    _channel, partner, certification = _certification(api)
    fx.schedule_test(
        api, certification["id"], partner["id"], CODE_AUTH, SLOT_ONE, 60, True
    )
    fx.schedule_test(
        api, certification["id"], partner["id"], CODE_SHOP, SLOT_GAP_EXACT, 30, True
    )
    fx.schedule_test(
        api, certification["id"], partner["id"], CODE_AUTH, SLOT_GAP_WIDER, 30, True
    )
    return partner, certification


def test_a_gap_of_exactly_fifteen_minutes_conflicts_only_for_the_same_test_code(api):
    """PRD §3.8: "**The teardown-buffer rule** is pairwise and narrow: it compares the
    requested slot only against scheduled tests that share both the same `env_code` and the
    same `test_code`, because re-running the same test case needs the harness torn down and
    rebuilt in between."
    PRD §3.8: "Each existing slot is widened by fifteen minutes on **both** sides — its start
    pulled fifteen minutes earlier and its end pushed fifteen minutes later — and a
    conflict exists when the requested closed interval shares at least one instant with any
    widened interval."
    PRD §3.8: "Since both intervals are closed, a gap of exactly fifteen minutes between
    two slots is a conflict, while a gap strictly greater than fifteen minutes is not."

    Design: Difficulty/resource_temporal_overlap/connectivity_test_teardown_buffer_gap_of_exactly_fifteen_conflicts
    """
    _channel, partner, certification = _certification(api)
    headers = technology_partner_headers(partner["id"])

    first = fx.schedule_test(
        api, certification["id"], partner["id"], CODE_AUTH, SLOT_ONE, 60, True
    )
    assert first["status"] == TEST_SCHEDULED
    assert first["score"] is None
    assert_instant_equals(first["scheduled_end"], "2026-08-03T10:00:00.000Z")
    holding = fx.read_certification(api, certification["id"])
    assert holding["reserved_test_minutes"] == 60

    # Widened, the 09:00-10:00 slot runs 08:45-10:15 and so touches a 10:15 start.
    conflict = api.create_connectivity_test(
        certification["id"],
        f.connectivity_test_payload(CODE_AUTH, SLOT_GAP_EXACT, 30, True),
        headers=headers,
    )
    validate_error(conflict, ApiErrorId.TEST_SLOT_CONFLICT)
    unchanged = fx.read_certification(api, certification["id"])
    assert unchanged["reserved_test_minutes"] == 60
    assert unchanged["version"] == holding["version"]

    # The very same instants are free for a different test code.
    other_code = fx.schedule_test(
        api, certification["id"], partner["id"], CODE_SHOP, SLOT_GAP_EXACT, 30, True
    )
    assert_instant_equals(other_code["scheduled_end"], "2026-08-03T10:45:00.000Z")
    assert fx.read_certification(api, certification["id"])["reserved_test_minutes"] == 90

    # One minute later the gap is strictly greater than fifteen, so AUTH fits.
    repeat = fx.schedule_test(
        api, certification["id"], partner["id"], CODE_AUTH, SLOT_GAP_WIDER, 30, True
    )
    assert repeat["status"] == TEST_SCHEDULED
    assert_instant_equals(repeat["scheduled_end"], "2026-08-03T10:46:00.000Z")
    assert fx.read_certification(api, certification["id"])["reserved_test_minutes"] == 120


def test_environment_capacity_counts_across_codes_and_is_scoped_to_one_environment(api):
    """PRD §3.8: "The service counts how many existing scheduled slots on that environment
    share at least one instant with the requested slot; if that count plus the requested
    test itself would exceed two, the request is refused with
    `ERR_TEST_ENV_CAPACITY_EXCEEDED`."
    PRD §3.8: "**The environment capacity rule** is aggregate and wide: it counts every
    scheduled test on the same `env_code` regardless of `test_code`, and applies **no** buffer —
    raw closed intervals only."
    PRD §3.8: "Because the buffer rule is scoped to a code pair while the capacity rule is
    scoped to the whole environment, neither can mask the other and both must be
    evaluated."

    Design: Difficulty/resource_temporal_overlap/connectivity_test_teardown_buffer_gap_of_exactly_fifteen_conflicts
    """
    partner, certification = _three_slots(api)
    headers = technology_partner_headers(partner["id"])

    # 10:30-10:45 raw-overlaps the 10:15 SHOP slot and the 10:16 AUTH slot: 2 + 1 > 2.
    over_capacity = api.create_connectivity_test(
        certification["id"],
        f.connectivity_test_payload(CODE_ORDER, SLOT_TWO, 15, False),
        headers=headers,
    )
    validate_error(over_capacity, ApiErrorId.TEST_ENV_CAPACITY_EXCEEDED)

    busy = fx.read_certification(api, certification["id"])
    assert busy["reserved_test_minutes"] == 120
    scheduled = fx.read_connectivity_tests(api, certification["id"])
    assert len(scheduled) == 3
    assert {test["status"] for test in scheduled} == {TEST_SCHEDULED}

    # The other shared environment is empty, so the same instants are available there.
    channel_id = certification["channel_id"]
    neighbour = fx.create_alpha_agency(
        api, partner_name="Beta Travel AG", iata_code="87654321"
    )
    second = fx.open_certification(
        api, neighbour["id"], channel_id, env_code=CERT_ENV_B
    )
    assert second["env_code"] == CERT_ENV_B
    elsewhere = fx.schedule_test(
        api, second["id"], neighbour["id"], CODE_ORDER, SLOT_TWO, 15, False
    )
    assert elsewhere["status"] == TEST_SCHEDULED
    assert fx.read_certification(api, second["id"])["reserved_test_minutes"] == 15
    # The busy environment's own reservation is untouched by the neighbour.
    assert fx.read_certification(api, certification["id"])["reserved_test_minutes"] == 120


def test_cancelling_a_slot_restores_the_exact_prior_reserved_minutes(api):
    """PRD §3.8: "Scheduling increases the certification's `reserved_test_minutes` by
    `duration_minutes` and increases the certification's `version` by 1; the test's `score`
    starts null and its `status` starts at `SCHEDULED`, with `certification_id` bound to the
    owning certification."
    PRD §3.8: "A cancellation is the deliberate exception: it releases the reserved minutes
    — restoring exactly the value they held before the test was scheduled — leaves `score`
    null, and leaves both readiness figures untouched, so a cancelled slot leaves no trace
    in the score."

    Design: Difficulty/compensating_invariant/schedule_then_cancel_restores_reserved_test_minutes
    """
    _channel, partner, certification = _certification(api)

    kept = fx.schedule_test(
        api, certification["id"], partner["id"], CODE_AUTH, SLOT_ONE, 60, True
    )
    assert kept["certification_id"] == certification["id"]
    before = fx.read_certification(api, certification["id"])
    assert before["reserved_test_minutes"] == 60

    doomed = fx.schedule_test(
        api, certification["id"], partner["id"], CODE_SHOP, SLOT_TWO, 45, True
    )
    assert doomed["status"] == TEST_SCHEDULED
    assert doomed["score"] is None
    reserved = fx.read_certification(api, certification["id"])
    assert reserved["reserved_test_minutes"] == 105
    assert reserved["version"] == before["version"] + 1

    cancelled = fx.report_outcome(api, doomed["id"], partner["id"], TEST_CANCELLED)
    assert cancelled["status"] == TEST_CANCELLED
    assert cancelled["score"] is None

    restored = fx.read_certification(api, certification["id"])
    # Exactly the value the counter held before the cancelled slot was booked.
    assert restored["reserved_test_minutes"] == 60
    assert restored["version"] == reserved["version"] + 1
    assert_readiness(restored, strict=0, provisional=0, mandatory_failed_count=0)

    # The cancelled slot left no trace: the surviving pass alone sets both variants.
    fx.report_outcome(api, kept["id"], partner["id"], TEST_PASSED, 90)
    scored = fx.read_certification(api, certification["id"])
    assert_readiness(
        scored,
        strict=90,
        provisional=90,
        mandatory_failed_count=0,
        reserved_test_minutes=0,
    )


def test_a_failed_outcome_releases_the_same_minutes_but_leaves_a_trace(api):
    """PRD §3.8: "Every outcome decreases the certification's `reserved_test_minutes` by
    that test's `duration_minutes` and increases the certification's `version` by 1."
    PRD §3.8: "A pass and a failure both trigger a recomputation of **both** readiness
    variants; a failure on a test whose `is_mandatory` is true additionally increases
    `mandatory_failed_count` by 1."

    Design: Difficulty/compensating_invariant/schedule_then_cancel_restores_reserved_test_minutes
    """
    _channel, partner, certification = _certification(api)

    failing = fx.schedule_test(
        api, certification["id"], partner["id"], CODE_AUTH, SLOT_ONE, 60, True
    )
    cancelling = fx.schedule_test(
        api, certification["id"], partner["id"], CODE_SHOP, SLOT_TWO, 45, True
    )
    assert fx.read_certification(api, certification["id"])["reserved_test_minutes"] == 105

    fx.report_outcome(api, cancelling["id"], partner["id"], TEST_CANCELLED)
    after_cancel = fx.read_certification(api, certification["id"])
    assert after_cancel["reserved_test_minutes"] == 60
    assert after_cancel["mandatory_failed_count"] == 0

    fx.report_outcome(api, failing["id"], partner["id"], TEST_FAILED, 20)
    after_failure = fx.read_certification(api, certification["id"])
    # The same release of minutes, but this outcome is recorded in the score.
    assert after_failure["reserved_test_minutes"] == 0
    assert after_failure["mandatory_failed_count"] == 1
    # STRICT zeroes on any failed mandatory test; PROVISIONAL drops it and finds nothing.
    assert_readiness(after_failure, strict=0, provisional=0, mandatory_failed_count=1)
    assert after_failure["version"] == after_cancel["version"] + 1
    assert after_failure["status"] == CERTIFICATION_TESTING
