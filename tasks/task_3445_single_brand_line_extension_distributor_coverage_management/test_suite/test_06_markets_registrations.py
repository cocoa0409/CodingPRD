"""Markets and product registrations: uniqueness, market gating, the VOC
regime, one-live-registration, the review loop, and the renewal window."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, validate_error, validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

CM = TEST_USERS["channel_manager_headers"]
RA = TEST_USERS["regulatory_affairs_headers"]


def test_market_country_code_is_unique():
    """PRD §3.4: "A `RegulatoryAffairs` officer creates a **Market** with a `country_code` — unique across all markets, with duplicates rejected by `ERR_MARKET_CODE_EXISTS` (HTTP 409) — a display `name`, a `registration_required` flag, a `voc_regime` of `STANDARD` or `STRICT`, and a non-empty `allowed_channels` array drawn from the four channels."

    Design: Corner/entities/market_country_code_is_unique
    """
    fx.create_market()
    resp = api_client.create_market(
        {"country_code": "US", "name": "United States Duplicate",
         "registration_required": True, "voc_regime": "STRICT",
         "allowed_channels": ["MASS"]}, RA)
    validate_error(resp, ApiErrorId.ERR_MARKET_CODE_EXISTS)


def test_distributor_approval_requires_open_home_market():
    """PRD §3.5: "Approval — `APPLICANT` → `APPROVED` — requires the home market to be `OPEN` (`ERR_MARKET_NOT_OPEN`)."

    Design: Corner/errors/distributor_approval_requires_open_home_market
    """
    market = fx.create_market()
    validate_success(api_client.close_market(market["id"], RA))
    dist = fx.create_distributor_record(market["id"])

    resp = api_client.approve_distributor(dist["id"], CM)
    validate_error(resp, ApiErrorId.ERR_MARKET_NOT_OPEN)
    after = validate_success(api_client.get_distributor(dist["id"], CM))
    assert after["status"] == "APPLICANT"


def test_strict_market_rejects_standard_voc_formulation():
    """PRD §3.4: "a `STRICT`-regime market accepts only a `LOW_VOC` formulation (`ERR_VOC_REGIME_MISMATCH`, HTTP 422)".

    Design: Corner/validations/strict_market_rejects_standard_voc_formulation
    """
    sc = fx.setup_pilot_line()
    market = fx.create_market(country_code="DE", name="Germany",
                            registration_required=True, voc_regime="STRICT",
                            allowed_channels=["HARDWARE"])
    resp = api_client.create_market_registration(
        {"market_id": market["id"], "product_line_id": sc["line"]["id"],
         "formulation_id": sc["formulation"]["id"],
         "expires_on": "2027-01-01T00:00:00Z"}, RA)
    validate_error(resp, ApiErrorId.ERR_VOC_REGIME_MISMATCH)

    rows, meta = validate_paginated(api_client.list_market_registrations(
        RA, params={"market_id": market["id"]}))
    assert rows == [] and meta["total_count"] == 0


def test_registration_formulation_must_belong_to_line():
    """PRD §3.4: "the formulation must actually belong to the named line (`ERR_FORMULATION_LINE_MISMATCH`, HTTP 422) and be `SEALED` or `COMPARTMENTALIZED` (`ERR_FORMULATION_NOT_SEALED`)".

    Design: Corner/errors/registration_formulation_must_belong_to_line
    """
    brand = fx.create_brand()
    line_a = fx.create_product_line(brand["id"], line_code="LA", name="Line A",
                                    is_core=False)
    fx.create_and_seal_formulation(
        line_a["id"], version_label="va", component_codes=["C1", "C2", "C3"])
    line_b = fx.create_product_line(brand["id"], line_code="LB", name="Line B",
                                    is_core=False)
    form_b = fx.create_and_seal_formulation(
        line_b["id"], version_label="vb", component_codes=["D1", "D2", "D3"])
    fx.approve_line_to_pilot(line_a["id"])
    market = fx.create_market(country_code="DE", name="Germany",
                            registration_required=True,
                            allowed_channels=["HARDWARE"])

    resp = api_client.create_market_registration(
        {"market_id": market["id"], "product_line_id": line_a["id"],
         "formulation_id": form_b["id"],
         "expires_on": "2027-01-01T00:00:00Z"}, RA)
    validate_error(resp, ApiErrorId.ERR_FORMULATION_LINE_MISMATCH)


def test_second_non_terminal_registration_rejected_then_allowed_after_revoke():
    """PRD §3.4: "at most one non-terminal registration may exist per market-and-line pair, a second being refused with `ERR_REGISTRATION_EXISTS` (HTTP 409)."
    PRD §3.4: "`EXPIRED` and `REVOKED` are terminal."

    Design: Corner/validations/second_non_terminal_registration_rejected_then_allowed_after_revoke
    """
    sc = fx.setup_pilot_line()
    market = fx.create_market(country_code="DE", name="Germany",
                            registration_required=True,
                            allowed_channels=["HARDWARE"])
    reg1 = fx.create_market_registration_record(
        market["id"], sc["line"]["id"], sc["formulation"]["id"])
    fx_submitted = api_client.submit_market_registration(reg1["id"], RA)
    assert validate_success(fx_submitted)["status"] == "SUBMITTED"

    dup = api_client.create_market_registration(
        {"market_id": market["id"], "product_line_id": sc["line"]["id"],
         "formulation_id": sc["formulation"]["id"],
         "expires_on": "2027-06-01T00:00:00Z"}, RA)
    validate_error(dup, ApiErrorId.ERR_REGISTRATION_EXISTS)

    validate_success(api_client.approve_market_registration(
        reg1["id"], "REG-DE-1001", RA))
    validate_success(api_client.revoke_market_registration(reg1["id"], RA))

    reg2 = api_client.create_market_registration(
        {"market_id": market["id"], "product_line_id": sc["line"]["id"],
         "formulation_id": sc["formulation"]["id"],
         "expires_on": "2027-06-01T00:00:00Z"}, RA)
    assert validate_success(reg2, 201)["status"] == "DRAFT"


def test_registration_reject_revise_resubmit_loop():
    """PRD §3.4: "Rejection moves `SUBMITTED` → `REJECTED` and carries a `reason`. Revision loops `REJECTED` → `DRAFT` and increments `revise_count`, readying the dossier for a fresh submission."
    PRD §3.4: "Approval moves `SUBMITTED` straight to `ACTIVE`: the authority's `registration_number` is supplied with the request and stored, `approved_at` is stamped, and the registration's `expires_on` must still be strictly after the current logical time (`ERR_WINDOW_INVALID`, HTTP 422)."

    Design: Corner/state_machines/registration_reject_revise_resubmit_loop
    """
    sc = fx.setup_pilot_line()
    market = fx.create_market(country_code="DE", name="Germany",
                            registration_required=True,
                            allowed_channels=["HARDWARE"])
    reg = fx.create_market_registration_record(
        market["id"], sc["line"]["id"], sc["formulation"]["id"])
    assert validate_success(
        api_client.submit_market_registration(reg["id"], RA))["status"] == "SUBMITTED"

    rejected = validate_success(
        api_client.reject_market_registration(reg["id"], "dossier incomplete", RA))
    assert rejected["status"] == "REJECTED"

    revised = validate_success(api_client.revise_market_registration(reg["id"], RA))
    assert revised["status"] == "DRAFT"
    assert revised["revise_count"] == 1

    resubmitted = validate_success(
        api_client.submit_market_registration(reg["id"], RA))
    assert resubmitted["status"] == "SUBMITTED"

    approved = validate_success(
        api_client.approve_market_registration(reg["id"], "REG-DE-1001", RA))
    assert approved["status"] == "ACTIVE"
    assert approved["registration_number"] == "REG-DE-1001"
    assert approved["approved_at"] is not None
    assert approved["submitted_at"] is not None


def test_renewal_window_opens_at_exactly_ninety_days():
    """PRD §2.9: "Registration renewal windows open exactly 90 days before expiry, and the boundary instant itself counts: the moment the current time equals `expires_on` minus 90 days, the registration is due for renewal."
    PRD §3.4: "Calling for renewal while the registration is still `ACTIVE` is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 409), because the window has not opened; calling for it once the registration is `EXPIRED` is rejected with `ERR_REGISTRATION_EXPIRED` (HTTP 409)."
    PRD §3.4: "Renewal is admitted only from `RENEWAL_DUE` and requires a `new_expires_on` strictly greater than the current `expires_on` (`ERR_WINDOW_INVALID` otherwise); on success the registration returns to `ACTIVE` with `expires_on` replaced."

    Design: Difficulty/boundary_precision_check/renewal_window_opens_at_exactly_ninety_days
    """
    sc = fx.setup_active_registration()  # expires_on 2027-01-01T00:00:00Z
    reg_id = sc["registration"]["id"]

    fx.advance_clock("2026-10-02T23:59:59Z")  # one second before the window
    early = api_client.renew_market_registration(
        reg_id, "2028-06-30T00:00:00Z", RA)
    validate_error(early, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN)
    still_active = validate_success(api_client.get_market_registration(reg_id, RA))
    assert still_active["status"] == "ACTIVE"

    fx.advance_clock("2026-10-03T00:00:00Z")  # exactly expires_on - 90 days
    renewed = api_client.renew_market_registration(
        reg_id, "2028-06-30T00:00:00Z", RA)
    data = validate_success(renewed)
    assert data["status"] == "ACTIVE"
    assert data["expires_on"].startswith("2028-06-30"), \
        "expires_on was replaced with the new instant"


def test_renew_on_expired_registration_returns_registration_expired():
    """PRD §3.4: "When the current time reaches `expires_on`, a `RENEWAL_DUE` registration becomes `EXPIRED`, and an `ACTIVE` registration whose expiry was jumped past in a single sweep goes straight to `EXPIRED`."
    PRD §3.4: "calling for it once the registration is `EXPIRED` is rejected with `ERR_REGISTRATION_EXPIRED` (HTTP 409)."

    Design: Corner/errors/renew_on_expired_registration_returns_registration_expired
    """
    sc = fx.setup_active_registration()
    reg_id = sc["registration"]["id"]

    fx.advance_clock("2027-01-02T00:00:00Z")
    swept = validate_success(api_client.get_market_registration(reg_id, RA))
    assert swept["status"] == "EXPIRED", "the clock jump swept straight past expiry"

    resp = api_client.renew_market_registration(reg_id, "2028-06-30T00:00:00Z", RA)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_EXPIRED)


def test_renew_requires_strictly_later_expiry():
    """PRD §3.4: "Renewal is admitted only from `RENEWAL_DUE` and requires a `new_expires_on` strictly greater than the current `expires_on` (`ERR_WINDOW_INVALID` otherwise); on success the registration returns to `ACTIVE` with `expires_on` replaced."

    Design: Corner/errors/renew_requires_strictly_later_expiry
    """
    sc = fx.setup_active_registration()
    reg_id = sc["registration"]["id"]
    fx.advance_clock("2026-10-03T00:00:00Z")  # renewal window opens (inclusive)

    resp = api_client.renew_market_registration(reg_id, "2026-12-01T00:00:00Z", RA)
    validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)

    after = validate_success(api_client.get_market_registration(reg_id, RA))
    assert after["status"] == "RENEWAL_DUE"
    assert after["expires_on"].startswith("2027-01-01"), "expires_on unchanged"
