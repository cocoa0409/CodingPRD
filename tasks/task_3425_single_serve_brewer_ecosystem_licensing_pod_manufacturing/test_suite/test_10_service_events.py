"""Service desk: warranty claims, descaling, misuse, and replacement cascades."""
from test_helpers import (
    ApiErrorId,
    create_brand,
    create_brewer_model,
    create_household,
    create_variety,
    get_success_data,
    open_service_event,
    record_brews,
    register_brewer,
    resolve_event,
    set_clock,
    setup_household_with_brewer,
    validate_error,
    validate_success,
)


def test_warranty_claim_on_expired_brewer_rejected(api, support_headers):
    """PRD §3.6: "A `WARRANTY_CLAIM` may only be opened while the brewer is
    `IN_WARRANTY`; against an `EXPIRED` or `VOID` warranty the creation is
    `ERR_WARRANTY_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/validations/warranty_claim_on_expired_brewer_rejected
    """
    _, _, brewer = setup_household_with_brewer(size=2, warranty_months=1)
    set_clock("2026-10-01T00:00:00Z")  # exact anniversary: warranty expires

    claim = api.create_service_event(
        brewer["id"], {"kind": "WARRANTY_CLAIM", "note": "leaking"},
        support_headers)
    validate_error(claim, ApiErrorId.ERR_WARRANTY_NOT_ACTIVE)

    # DESCALING events carry no warranty gate.
    descale = validate_success(api.create_service_event(
        brewer["id"], {"kind": "DESCALING", "note": "routine"},
        support_headers), 201)
    assert descale["status"] == "OPEN"


def test_claim_auto_denied_when_descale_overdue(api, support_headers):
    """PRD §3.6: "a warranty claim opened while the brewer's `descale_overdue`
    is set does not even enter the queue: it is created straight into `DENIED`
    with `resolution` `AUTO_DENIED_DESCALE`, on the policy that a neglected
    machine's failures are not warranty business."

    Design: Corner/validations/claim_auto_denied_when_descale_overdue
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Overdue Brand")
    variety = create_variety(brand["id"], name="Overdue Var")
    _, _, brewer = setup_household_with_brewer(size=2, descale_interval_brews=200)
    record_brews(brewer["id"], 200, variety["id"])  # 200 - 0 >= 200: overdue

    created = validate_success(api.create_service_event(
        brewer["id"], {"kind": "WARRANTY_CLAIM", "note": "pump noise"},
        support_headers), 201)
    assert created["status"] == "DENIED"
    assert created["resolution"] == "AUTO_DENIED_DESCALE"

    # DENIED is terminal: no resolution is possible afterwards.
    resp = api.resolve_service_event(created["id"], {"outcome": "APPROVED"},
                                     support_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_descale_resolution_resets_the_counter(api, support_headers):
    """PRD §3.6: "Approving a `DESCALING` event resets the descale clock by
    setting `last_descaled_brew_count` to the current `brew_count`, which
    clears `descale_overdue`."

    Design: Corner/validations/descale_resolution_resets_the_counter
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Descale Brand")
    variety = create_variety(brand["id"], name="Descale Var")
    _, _, brewer = setup_household_with_brewer(size=2, descale_interval_brews=200)
    record_brews(brewer["id"], 200, variety["id"])

    event = open_service_event(brewer["id"], "DESCALING", note="scale buildup")
    resolve_event(event["id"], "APPROVED")

    brewer_after = get_success_data(api.get_brewer(brewer["id"], support_headers))
    assert brewer_after["last_descaled_brew_count"] == 200
    assert brewer_after["descale_overdue"] is False

    # Descaling restored claim eligibility: a fresh claim opens normally.
    claim = validate_success(api.create_service_event(
        brewer["id"], {"kind": "WARRANTY_CLAIM", "note": "now maintained"},
        support_headers), 201)
    assert claim["status"] == "OPEN"
    assert claim["resolution"] is None


def test_misuse_confirmed_voids_warranty_permanently(api, support_headers):
    """PRD §3.6: "Resolving a `WARRANTY_CLAIM` with `MISUSE_CONFIRMED` voids
    the brewer's warranty outright — `warranty_status` becomes `VOID`."
    PRD §3.6: "`EXPIRED` and `VOID` are both permanent."

    Design: Corner/validations/misuse_confirmed_voids_warranty_permanently
    """
    _, _, brewer = setup_household_with_brewer(size=2, warranty_months=12)

    claim = open_service_event(brewer["id"], "WARRANTY_CLAIM",
                               note="brewer full of glue")
    resolved = resolve_event(claim["id"], "MISUSE_CONFIRMED")
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "MISUSE_CONFIRMED"

    brewer_after = get_success_data(api.get_brewer(brewer["id"], support_headers))
    assert brewer_after["warranty_status"] == "VOID"

    # Eleven warranty months remain on the calendar; VOID still bars claims.
    second = api.create_service_event(
        brewer["id"], {"kind": "WARRANTY_CLAIM", "note": "second try"},
        support_headers)
    validate_error(second, ApiErrorId.ERR_WARRANTY_NOT_ACTIVE)


def test_replacement_resolve_decommissions_and_collapses_household(
        api, admin_headers):
    """PRD §3.6: "Approving a `REPLACEMENT` event decommissions the machine:
    `operational` becomes `DECOMMISSIONED`, then the household's
    `installed_brewers` recomputes, and if that count has reached zero the
    household's `engagement` becomes `CHURNED` and its `expected_monthly_pods`
    collapses to 0.00."

    Design: Difficulty/transitive_cascade/replacement_depth3_cascade
    """
    household, _, brewer = setup_household_with_brewer(size=4)

    healthy = get_success_data(api.get_household(household["id"], admin_headers))
    assert healthy["expected_monthly_pods"] == 120.00

    event = open_service_event(brewer["id"], "REPLACEMENT",
                               note="unit failed; ship replacement")
    resolved = resolve_event(event["id"], "APPROVED")
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "APPROVED"

    brewer_after = get_success_data(api.get_brewer(brewer["id"], admin_headers))
    assert brewer_after["operational"] == "DECOMMISSIONED"

    after = get_success_data(api.get_household(household["id"], admin_headers))
    assert after["installed_brewers"] == 0
    assert after["engagement"] == "CHURNED"
    assert after["expected_monthly_pods"] == 0.00


def test_replacement_with_surviving_brewer_keeps_household_engaged(
        api, admin_headers):
    """PRD §3.6: "if that count has reached zero the household's `engagement`
    becomes `CHURNED` and its `expected_monthly_pods` collapses to 0.00."
    PRD §3.5: "a household is `ENGAGED` when any of its brewers is `ACTIVE`"

    Design: Difficulty/transitive_cascade/replacement_depth3_cascade
    """
    household = create_household(size=4, region="NW")
    model = create_brewer_model(model_code="K-PAIR")
    brewer_a = register_brewer(household["id"], model["id"])
    register_brewer(household["id"], model["id"])

    event = open_service_event(brewer_a["id"], "REPLACEMENT", note="swap out")
    resolve_event(event["id"], "APPROVED")

    brewer_after = get_success_data(api.get_brewer(brewer_a["id"], admin_headers))
    assert brewer_after["operational"] == "DECOMMISSIONED"

    after = get_success_data(api.get_household(household["id"], admin_headers))
    assert after["installed_brewers"] == 1
    assert after["engagement"] == "ENGAGED"
    # 4 * 30 * 1.0 * 1.0 * 1.0 == 120.00 — no collapse while a brewer survives.
    assert after["expected_monthly_pods"] == 120.00
