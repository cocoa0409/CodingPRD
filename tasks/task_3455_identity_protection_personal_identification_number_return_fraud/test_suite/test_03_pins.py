"""IP PIN program tests: OCC-guarded manual reissue conserving the
single-ACTIVE-pin invariant, opt-out revocation, and the idempotent annual
regeneration batch.

PRD section 3.2.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_protection_pin,
    assert_single_active_pin,
    create_enrolled_taxpayer,
    list_pins,
    make_taxpayer_headers,
    reissue_protection_pin_payload,
    run_pin_regeneration,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]


# ─── Manual reissue: conserved single-ACTIVE invariant ──

def test_pin_reissue_mints_fresh_active_pin_value(api):
    """PRD section 3.2: "Reissue requires the taxpayer to be `ENROLLED` (else
    `ERR_NOT_ENROLLED`), creates the new pin in `ACTIVE`, supersedes the prior
    `ACTIVE` pin of the same taxpayer and tax year, and increments the
    taxpayer's `version` by 1."
    PRD section 3.2: "the pin carries a server-generated 6-digit `pin_value`
    unique per taxpayer and tax year".

    Design: Difficulty/compensating_invariant/pin_reissue_conserves_single_active
    """
    set_clock("2027-01-25T00:00:00Z")
    taxpayer, pin1 = create_enrolled_taxpayer()

    resp = api.reissue_protection_pin(
        reissue_protection_pin_payload(taxpayer["id"], taxpayer["version"]),
        ADMIN,
    )
    pin2 = validate_success(resp, 201)
    assert_protection_pin(pin2)
    assert pin2["status"] == "ACTIVE"
    assert pin2["tax_year"] == 2026
    assert pin2["pin_value"] != pin1["pin_value"]


def test_pin_reissue_supersedes_prior_and_conserves_single_active(api):
    """PRD section 3.2: "At most one pin may be `ACTIVE` for a given taxpayer
    and tax year, so minting the new pin flips any previously `ACTIVE` pin
    for that same pair to `SUPERSEDED`."

    Design: Difficulty/compensating_invariant/pin_reissue_conserves_single_active
    """
    set_clock("2027-01-25T00:00:00Z")
    taxpayer, pin1 = create_enrolled_taxpayer()
    pin2 = validate_success(
        api.reissue_protection_pin(
            reissue_protection_pin_payload(taxpayer["id"], taxpayer["version"]),
            ADMIN,
        ),
        201,
    )

    pins = list_pins(taxpayer["id"])
    by_id = {p["id"]: p for p in pins}
    assert by_id[pin1["id"]]["status"] == "SUPERSEDED"
    assert by_id[pin2["id"]]["status"] == "ACTIVE"
    # The conserved quantity: exactly one ACTIVE pin for (taxpayer, 2026)
    # before and after the reissue.
    assert_single_active_pin(pins, 2026)


# ─── Opt-out ─────────────────────────────────────────

def test_opt_out_revokes_active_pins_and_rejects_repeat(api):
    """PRD section 3.2: "Leaving the program revokes everything: opting out
    requires the taxpayer to be `ENROLLED` (otherwise the request is rejected
    with `ERR_NOT_ENROLLED`, HTTP 422), moves `ip_pin_enrollment` to
    `OPTED_OUT`, transitions every `ACTIVE` pin of that taxpayer to
    `REVOKED`, and increments the taxpayer's `version` by 1."

    Design: Corner/state_machines/opt_out_revokes_active_pins
    """
    set_clock("2027-01-25T00:00:00Z")
    taxpayer, _pin = create_enrolled_taxpayer()

    resp = api.opt_out_ip_pin(
        taxpayer["id"], make_taxpayer_headers(taxpayer["id"])
    )
    data = validate_success(resp, 200)
    assert data["ip_pin_enrollment"] == "OPTED_OUT"

    pins = list_pins(taxpayer["id"])
    assert len(pins) == 1
    assert pins[0]["status"] == "REVOKED"

    repeat = api.opt_out_ip_pin(
        taxpayer["id"], make_taxpayer_headers(taxpayer["id"])
    )
    validate_error(repeat, ApiErrorId.ERR_NOT_ENROLLED)


# ─── Annual regeneration batch ───────────────────────

def test_annual_regeneration_idempotent_rerun(api):
    """PRD section 3.2: "The run reports `created_count`, `superseded_count`
    (the number of prior-year pins the run superseded), and `skipped_count`,
    and is idempotent per tax year: re-running it with the same `tax_year`
    creates nothing, so `created_count` comes back 0 and every previously
    created pin is counted as skipped."

    Design: Corner/calculations/annual_regeneration_idempotent_rerun
    """
    set_clock("2026-12-15T00:00:00Z")
    taxpayer_a, _pin_a = create_enrolled_taxpayer()
    taxpayer_b, _pin_b = create_enrolled_taxpayer()

    first = run_pin_regeneration(2027)
    assert first["created_count"] == 2
    assert first["superseded_count"] == 2
    assert first["skipped_count"] == 0

    second = run_pin_regeneration(2027)
    assert second["created_count"] == 0
    assert second["superseded_count"] == 0
    assert second["skipped_count"] == 2

    for taxpayer in (taxpayer_a, taxpayer_b):
        pins = list_pins(taxpayer["id"])
        assert_single_active_pin(pins, 2027)
        prior_year = [p for p in pins if p["tax_year"] == 2026]
        assert len(prior_year) == 1
        assert prior_year[0]["status"] == "SUPERSEDED"
