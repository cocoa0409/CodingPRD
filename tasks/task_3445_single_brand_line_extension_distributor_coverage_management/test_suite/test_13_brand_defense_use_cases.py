"""Brand defense: posture threshold bands and the consumer use-case pipeline
(submitter identity, launch gating, moderation, genericization risk)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, make_consumer_headers,
    validate_error, validate_success,
)
from test_helpers import fixtures as fx

BM = TEST_USERS["brand_manager_headers"]
CA = TEST_USERS["compliance_auditor_headers"]
MM = TEST_USERS["marketing_manager_headers"]


def test_genericization_risk_gate_at_five_hundred_bps():
    """PRD §3.9: "Across every line of the brand, each `PUBLISHED` submission flagged for generic use contributes 100 basis points and each flagged `VERIFIED` submission contributes 50; the risk is the sum, capped at 10000."
    PRD §3.9: "Publishing moves `VERIFIED` → `PUBLISHED`, but a flagged submission — one whose `generic_use_flag` is true — may publish only while the brand's `genericization_risk_bps` stands below 500; at or above that level the publish is refused with `ERR_GENERICIZATION_RISK` (HTTP 422)."

    Design: Corner/calculations/genericization_risk_gate_at_five_hundred_bps
    """
    sc = fx.setup_launched_line()
    line_id = sc["line"]["id"]
    brand_id = sc["brand"]["id"]

    fx.create_flagged_use_cases(line_id, 5, publish=True)
    at_five = validate_success(api_client.get_brand(brand_id, BM))
    assert at_five["genericization_risk_bps"] == 500, \
        "five flagged publishes contribute 100 each"

    uc6 = fx.create_use_case_record(line_id, "consumer-6")
    validate_success(api_client.review_use_case(uc6["id"], "VERIFY", True, MM))
    blocked = api_client.publish_use_case(uc6["id"], MM)
    validate_error(blocked, ApiErrorId.ERR_GENERICIZATION_RISK)

    uc7 = fx.create_use_case_record(line_id, "consumer-7")
    validate_success(api_client.review_use_case(uc7["id"], "VERIFY", False, MM))
    published = api_client.publish_use_case(uc7["id"], MM)
    assert validate_success(published)["status"] == "PUBLISHED", \
        "the gate blocks only flagged content"

    final = validate_success(api_client.get_brand(brand_id, BM))
    assert final["genericization_risk_bps"] == 550, \
        "5 * 100 published-flagged + 1 * 50 verified-flagged; the unflagged publish contributes 0"


def test_posture_elevated_band_and_relaxation():
    """PRD §3.1: "The posture is `CRITICAL` when at least two such breaches exist, or any single open case has `severity` 5, or the open-case severities sum to at least 10. Failing that, it is `ELEVATED` when exactly one such breach exists or the severity sum reaches at least 6. Otherwise the posture is `NORMAL`."
    PRD §3.1: "The recomputation considers the brand's **open cases** — counterfeit cases in `REPORTED` or `ACTION_TAKEN` — and its **recent breaches** — grants on formulations of the brand's lines whose `revoked_for_cause` flag is true and whose `revoked_at` falls within the trailing 180 days."

    Design: Corner/calculations/posture_elevated_band_and_relaxation
    """
    brand = fx.create_brand()
    market = fx.create_market()

    fx.create_counterfeit_case_record(brand["id"], market["id"], severity=3)
    one = validate_success(api_client.get_brand(brand["id"], CA))
    assert one["protection_posture"] == "NORMAL", "severity sum 3 < 6"

    case2 = fx.create_counterfeit_case_record(brand["id"], market["id"],
                                              severity=3, channel="MASS")
    two = validate_success(api_client.get_brand(brand["id"], CA))
    assert two["protection_posture"] == "ELEVATED", \
        "severity sum 6 >= 6, but no severity-5 case and sum < 10"

    validate_success(api_client.close_counterfeit_case(case2["id"], CA))
    relaxed = validate_success(api_client.get_brand(brand["id"], CA))
    assert relaxed["protection_posture"] == "NORMAL", \
        "closing one case drops the open-case sum back to 3"


def test_use_case_submitter_must_match_caller():
    """PRD §3.9: "A **UseCaseSubmission** is filed under a product line by a `Consumer`, with a `submitter_ref` that must equal the caller's `X-User-ID` (`ERR_SUBMITTER_MISMATCH`, HTTP 403), a short `title`, and a free-text `description`."

    Design: Corner/validations/use_case_submitter_must_match_caller
    """
    sc = fx.setup_launched_line()
    resp = api_client.create_use_case(
        sc["line"]["id"],
        {"submitter_ref": "consumer-bob", "title": " impersonated",
         "description": "Not my use case."},
        make_consumer_headers("consumer-ana"))
    validate_error(resp, ApiErrorId.ERR_SUBMITTER_MISMATCH)


def test_use_case_requires_launched_line():
    """PRD §3.9: "The line must be `LAUNCHED` (`ERR_LINE_NOT_LAUNCHED`, HTTP 409)."

    Design: Corner/errors/use_case_requires_launched_line
    """
    sc = fx.setup_pilot_line()  # PILOT, not LAUNCHED
    resp = api_client.create_use_case(
        sc["line"]["id"],
        {"submitter_ref": "consumer-1", "title": "Early use",
         "description": "Tried it at a trade show."},
        make_consumer_headers("consumer-1"))
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_LAUNCHED)


def test_use_case_reject_and_retract_paths():
    """PRD §3.9: "a `VERIFY` decision moves the submission to `VERIFIED`, records the flag, and recomputes the brand's genericization risk; a `REJECT` decision lands in `REJECTED`."
    PRD §3.9: "`REJECTED` and `RETRACTED` submissions contribute nothing, and the figure is recomputed at every verify-with-flag, publish and retract."
    PRD §3.9: "A published piece can later be retracted to `RETRACTED`."

    Design: Corner/state_machines/use_case_reject_and_retract_paths
    """
    sc = fx.setup_launched_line()
    line_id = sc["line"]["id"]
    brand_id = sc["brand"]["id"]

    uc1 = fx.create_use_case_record(line_id, "consumer-1", title="Weak use")
    rejected = validate_success(
        api_client.review_use_case(uc1["id"], "REJECT", False, MM))
    assert rejected["status"] == "REJECTED"
    assert validate_success(api_client.get_brand(brand_id, BM))[
        "genericization_risk_bps"] == 0, "a REJECTED submission never contributes"

    uc2 = fx.create_use_case_record(line_id, "consumer-2",
                                    title="Generic mention")
    validate_success(api_client.review_use_case(uc2["id"], "VERIFY", True, MM))
    validate_success(api_client.publish_use_case(uc2["id"], MM))
    mid = validate_success(api_client.get_brand(brand_id, BM))
    assert mid["genericization_risk_bps"] == 100, "one flagged PUBLISHED piece"

    retracted = validate_success(api_client.retract_use_case(uc2["id"], MM))
    assert retracted["status"] == "RETRACTED"
    end = validate_success(api_client.get_brand(brand_id, BM))
    assert end["genericization_risk_bps"] == 0, \
        "the retraction returns the contribution to zero"
