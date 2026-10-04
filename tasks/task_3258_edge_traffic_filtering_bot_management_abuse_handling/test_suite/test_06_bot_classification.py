"""Bot classification: heuristic hash, honeypot override, verified crawlers,
fight mode, and score-band actions."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client, TEST_USERS,
    make_account, make_active_zone, zone_headers,
    reset_clock, bot_band,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Corner/entities/bot_classification_computed_fields_from_fingerprint
# ---------------------------------------------------------------------------

def test_bot_classification_computed_fields_from_fingerprint(api):
    """PRD section 3.6: "Otherwise the score is one plus the remainder of
    dividing a hash of the request_fingerprint by 99, where the hash is the sum
    of the ASCII byte values of the fingerprint's characters — deterministic and
    case-sensitive — yielding an integer from 1 to 99 inclusive. A score of
    exactly 30 classifies the request HUMAN; any other heuristic score
    classifies it LIKELY_AUTOMATED."

    Design: Corner/entities/bot_classification_computed_fields_from_fingerprint
    """
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="computed.example.com")
    resp = api.create_bot_classification(
        zone["id"],
        {"request_fingerprint": "fp-m9", "verified_crawler": False,
         "client_ip": "203.0.113.50"},
        zone_headers(acc),
    )
    data = validate_success(resp, expected_status=201)
    # 1 + ((102+112+45+109+57) mod 99) == 1 + (425 mod 99) == 30
    assert data["bot_score"] == 30
    assert data["classification"] == "HUMAN"
    assert data["action_taken"] == "ALLOW", (
        "no bands configured and fight mode off: the request is allowed"
    )


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/honeypot_plan_scoped_classification_variant
# ---------------------------------------------------------------------------

def _zone_with_honeypot_hit(acc, domain):
    zone = make_active_zone(acc, domain=domain)
    headers = zone_headers(acc)
    get_success_data(api_client.add_honeypot(
        zone["id"], {"url_path": "/trap-9"}, headers
    ))
    get_success_data(api_client.record_honeypot_hit(
        zone["id"], {"client_ip": "203.0.113.9", "url_path": "/trap-9"},
        headers,
    ))
    return zone


def test_honeypot_hit_classifies_honeypot_bot_when_feature_on(api):
    """PRD section 3.6: "If the account's plan tier includes the
    bot-classification feature, and the zone's internal honeypot hit log holds a
    hit from the same client_ip whose hit_at falls inside the closed 24-hour
    lookback ending at classified_at ... the request scores bot_score 1 and is
    classified HONEYPOT_BOT."

    Design: Difficulty/dual_variant_calc/honeypot_plan_scoped_classification_variant
    """
    reset_clock()
    acc = make_account(plan_tier="PRO")
    zone = _zone_with_honeypot_hit(acc, "pro.example.com")
    resp = api.create_bot_classification(
        zone["id"],
        {"request_fingerprint": "fp-jz9", "verified_crawler": False,
         "client_ip": "203.0.113.9"},
        zone_headers(acc),
    )
    data = validate_success(resp, expected_status=201)
    assert data["classification"] == "HONEYPOT_BOT"
    assert data["bot_score"] == 1
    assert data["action_taken"] == "BLOCK", (
        "a HONEYPOT_BOT request is always blocked"
    )


def test_honeypot_hit_falls_back_to_heuristic_when_feature_off(api):
    """PRD section 3.6: "Plan context changes outcomes for identical data: when
    the tier lacks bot classification, the honeypot override never applies, and
    a client caught in a honeypot still classifies via the heuristic."

    Design: Difficulty/dual_variant_calc/honeypot_plan_scoped_classification_variant
    """
    reset_clock()
    acc = make_account(plan_tier="FREE")
    zone = _zone_with_honeypot_hit(acc, "free.example.com")
    resp = api.create_bot_classification(
        zone["id"],
        {"request_fingerprint": "fp-jz9", "verified_crawler": False,
         "client_ip": "203.0.113.9"},
        zone_headers(acc),
    )
    data = validate_success(resp, expected_status=201)
    # 1 + ((102+112+45+106+122+57) mod 99) == 1 + (544 mod 99) == 50
    assert data["bot_score"] == 50
    assert data["classification"] == "LIKELY_AUTOMATED"


# ---------------------------------------------------------------------------
# Corner/errors/verified_crawler_always_allowed_even_with_fight_mode
# ---------------------------------------------------------------------------

def test_verified_crawler_always_allowed_even_with_fight_mode(api):
    """PRD section 3.6: "Otherwise, when verified_crawler is true, the request
    scores 99 and is classified VERIFIED_BOT." and "A VERIFIED_BOT request is
    always allowed."

    Design: Corner/errors/verified_crawler_always_allowed_even_with_fight_mode
    """
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="appeal.example.com")
    headers = zone_headers(acc)
    get_success_data(api_client.patch_zone(
        zone["id"], {"bot_fight_mode": True}, headers
    ))
    get_success_data(api_client.patch_zone(
        zone["id"],
        {"bot_action_bands": [bot_band("all", "BLOCK", 1, 99)]},
        headers,
    ))
    resp = api.create_bot_classification(
        zone["id"],
        {"request_fingerprint": "fp-qz", "verified_crawler": True,
         "client_ip": "203.0.113.60"},
        headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["classification"] == "VERIFIED_BOT"
    assert data["bot_score"] == 99
    assert data["action_taken"] == "ALLOW", (
        "verified crawlers bypass the band and fight-mode layers entirely"
    )


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers/fight_mode_challenge_band_respected
# ---------------------------------------------------------------------------

def test_fight_mode_blocks_scores_1_to_29(api):
    """PRD section 3.6: "When no band matches, the bot_fight_mode toggle
    applies: if it is true and the score falls anywhere from 1 to 29 inclusive,
    the action is BLOCK:FIGHT_MODE."

    Design: Corner/cross_cutting_layers/fight_mode_challenge_band_respected
    """
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="fight.example.com")
    headers = zone_headers(acc)
    get_success_data(api_client.patch_zone(
        zone["id"], {"bot_fight_mode": True}, headers
    ))
    resp = api.create_bot_classification(
        zone["id"],
        {"request_fingerprint": "fp-9", "verified_crawler": False,
         "client_ip": "203.0.113.70"},
        headers,
    )
    data = validate_success(resp, expected_status=201)
    # 1 + ((102+112+45+57) mod 99) == 1 + (316 mod 99) == 20
    assert data["bot_score"] == 20
    assert data["action_taken"] == "BLOCK:FIGHT_MODE"


def test_fight_mode_allows_scores_above_29_without_band(api):
    """PRD section 3.6: "When no band matches, the bot_fight_mode toggle
    applies: if it is true and the score falls anywhere from 1 to 29 inclusive,
    the action is BLOCK:FIGHT_MODE. Failing all of that, the request is
    allowed."

    Design: Corner/cross_cutting_layers/fight_mode_challenge_band_respected
    """
    acc = make_account(plan_tier="PRO")
    zone = make_active_zone(acc, domain="fight2.example.com")
    headers = zone_headers(acc)
    get_success_data(api_client.patch_zone(
        zone["id"], {"bot_fight_mode": True}, headers
    ))
    resp = api.create_bot_classification(
        zone["id"],
        {"request_fingerprint": "fp-jz9", "verified_crawler": False,
         "client_ip": "203.0.113.71"},
        headers,
    )
    data = validate_success(resp, expected_status=201)
    # 1 + (544 mod 99) == 50, above the fight-mode range
    assert data["bot_score"] == 50
    assert data["action_taken"] == "ALLOW"
