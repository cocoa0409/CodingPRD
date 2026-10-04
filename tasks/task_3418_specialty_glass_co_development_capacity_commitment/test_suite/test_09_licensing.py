"""Brand licensing: activation precondition stack, term intervals, secondary
applications, the two independent state dimensions, and checkpoint expiry.

All rules cited from PRD sections 3.1, 3.7, and 3.9.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    activate_license,
    begin_qualification,
    create_license,
    create_program_with_nda,
    create_qualified_composition,
    freeze_design,
    ip_review,
    lock_composition,
    review_marketing,
    run_checkpoint,
    set_clock,
    setup_active_license,
    setup_licensing_chain,
    submit_marketing,
    validate_error,
    validate_success,
    get_success_data,
)

LEGAL = TEST_USERS["legal_counsel_headers"]

LICENSE_EFFECTIVE = "2027-01-01T00:00:00Z"


def test_license_activate_requires_program_design_frozen():
    """PRD section 3.7: "The referenced program must be `DESIGN_FROZEN`,
    failing otherwise with `ERR_PROGRAM_NOT_FROZEN`." The identical activate
    call fails while the program sits in QUALIFICATION and succeeds after the
    design freeze with no change to the license itself.

    Design: Difficulty/cross_entity_state_dependency/license_activate_requires_program_design_frozen
    """
    chain = create_program_with_nda(maker_name="Beta Devices", maker_region="EU")
    create_qualified_composition(chain.program, chain.maker, composition_code="GX-200")
    program = begin_qualification(chain.program)
    license_ = create_license(chain.maker, chain.program)
    set_clock(LICENSE_EFFECTIVE)

    resp = api_client.activate_license(license_["id"], headers=LEGAL)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FROZEN)

    freeze_design(program)
    activated = validate_success(api_client.activate_license(license_["id"], headers=LEGAL))
    assert activated["license_status"] == "ACTIVE"


def test_license_closed_interval_inclusive_end_conflicts():
    """PRD section 3.7: "And no other license of the same `device_maker_id`
    and `market` may be `ACTIVE` with a closed term interval intersecting this
    one — because both intervals are closed, terms that merely touch at an
    expiry date count as overlapping — failing otherwise with
    `ERR_LICENSE_TERM_OVERLAP`." A successor whose effective date equals the
    incumbent's expiry date conflicts; one starting the next day activates.

    Design: Difficulty/resource_temporal_overlap/license_closed_interval_inclusive_end_conflicts
    """
    chain = setup_licensing_chain(market="AUTOMOTIVE", lock_composition=True)
    activate_license(chain.license)  # [2027-01-01, 2028-12-31] ACTIVE

    touching = create_license(
        chain.maker,
        chain.program,
        market="AUTOMOTIVE",
        effective_date="2028-12-31T00:00:00Z",
        expiry_date="2030-12-30T00:00:00Z",
    )
    set_clock("2028-12-31T00:00:00Z")
    resp = api_client.activate_license(touching["id"], headers=LEGAL)
    validate_error(resp, ApiErrorId.ERR_LICENSE_TERM_OVERLAP)

    past_end = create_license(
        chain.maker,
        chain.program,
        market="AUTOMOTIVE",
        effective_date="2029-01-01T00:00:00Z",
        expiry_date="2030-12-31T00:00:00Z",
    )
    set_clock("2029-01-01T00:00:00Z")
    activated = validate_success(api_client.activate_license(past_end["id"], headers=LEGAL))
    assert activated["license_status"] == "ACTIVE"


def test_license_expires_at_checkpoint():
    """PRD section 3.7: "the operations checkpoint moves an `ACTIVE` license
    to `EXPIRED`, also terminal, once the logical clock has passed its
    `expiry_date`." PRD section 2.4: "Time-driven state changes do not fire
    spontaneously when the clock moves: they are applied only when an
    authorized operator runs the operations checkpoint sweep". PRD section 3.9:
    "The response reports the sweep's work as counts: `campaigns_completed`,
    `campaigns_cancelled`, `licenses_expired`, `commitments_exhausted`, and
    `commitments_breached`."

    Design: Corner/state_machines/license_expires_at_checkpoint
    """
    chain = setup_active_license()  # term [2027-01-01, 2028-12-31]
    set_clock("2029-01-01T00:00:00Z")
    result = run_checkpoint()
    assert result["licenses_expired"] == 1
    license_ = get_success_data(api_client.get_license(chain.license["id"], LEGAL))
    assert license_["license_status"] == "EXPIRED"


def test_activate_before_effective_date_returns_license_term_invalid():
    """PRD section 3.7: "The logical clock must read at or after
    `effective_date` and at or before `expiry_date`, failing otherwise with
    `ERR_LICENSE_TERM_INVALID`." The clock still reads the default
    2026-09-01T00:00:00Z, before the term opens at 2027-01-01.

    Design: Corner/errors/activate_before_effective_date_returns_license_term_invalid
    """
    chain = setup_licensing_chain(move_clock_to_term=False)
    resp = api_client.activate_license(chain.license["id"], headers=LEGAL)
    validate_error(resp, ApiErrorId.ERR_LICENSE_TERM_INVALID)
    license_ = get_success_data(api_client.get_license(chain.license["id"], LEGAL))
    assert license_["license_status"] == "NEGOTIATION"


def test_activate_with_confirmed_infringement_returns_ip_hold():
    """PRD section 3.1: "While a maker sits in `CONFIRMED_INFRINGEMENT`, four
    operations are blocked with `ERR_IP_LITIGATION_HOLD`: activating a license
    for that maker, reinstating one, creating an allocation whose commitment
    belongs to that maker, and submitting a usage report against that maker's
    license."

    Design: Corner/errors/activate_with_confirmed_infringement_returns_ip_hold
    """
    chain = setup_licensing_chain(move_clock_to_term=False)
    ip_review(chain.maker, "UNDER_REVIEW")
    ip_review(chain.maker, "CONFIRMED_INFRINGEMENT")
    set_clock(LICENSE_EFFECTIVE)
    resp = api_client.activate_license(chain.license["id"], headers=LEGAL)
    validate_error(resp, ApiErrorId.ERR_IP_LITIGATION_HOLD)
    license_ = get_success_data(api_client.get_license(chain.license["id"], LEGAL))
    assert license_["license_status"] == "NEGOTIATION"


def test_secondary_market_without_locked_base_returns_base_platform_not_qualified():
    """PRD section 3.7: "For a secondary application, at least one composition
    of the program must be `LOCKED` — `QUALIFIED` is insufficient for
    adjacent-market certification — failing otherwise with
    `ERR_BASE_PLATFORM_NOT_QUALIFIED`." Locking the composition then lets the
    identical activate succeed.

    Design: Corner/validations/secondary_market_without_locked_base_returns_base_platform_not_qualified
    """
    chain = setup_licensing_chain(market="ARCHITECTURAL")  # clock in term
    resp = api_client.activate_license(chain.license["id"], headers=LEGAL)
    validate_error(resp, ApiErrorId.ERR_BASE_PLATFORM_NOT_QUALIFIED)

    lock_composition(chain.composition)
    activated = validate_success(
        api_client.activate_license(chain.license["id"], headers=LEGAL)
    )
    assert activated["license_status"] == "ACTIVE"


def test_license_parallel_status_dimensions():
    """PRD section 3.7: "Every License carries two parallel and independent
    state dimensions." PRD section 3.7: "Counsel may suspend an `ACTIVE`
    license, moving it to `SUSPENDED` with `suspension_reason` set to
    `MANUAL`" and "Reinstating a `SUSPENDED` license returns it to `ACTIVE`
    and clears `suspension_reason` to `NONE`". The marketing track cycles
    DRAFT -> IN_REVIEW -> CHANGES_REQUIRED -> IN_REVIEW -> APPROVED while the
    legal state sits in NEGOTIATION, and a later suspend/reinstate pair never
    touches marketing.

    Design: Difficulty/non_linear_state_machine/license_parallel_status_dimensions
    """
    chain = setup_licensing_chain()  # NEGOTIATION / DRAFT, clock in term
    license_ = submit_marketing(chain.license, chain.maker)
    assert license_["marketing_status"] == "IN_REVIEW"
    assert license_["license_status"] == "NEGOTIATION"
    license_ = review_marketing(license_, "CHANGES_REQUIRED")
    assert license_["marketing_status"] == "CHANGES_REQUIRED"
    license_ = submit_marketing(license_, chain.maker, materials_ref="MKT-2")
    license_ = review_marketing(license_, "APPROVED")
    assert license_["marketing_status"] == "APPROVED"
    assert license_["license_status"] == "NEGOTIATION"

    license_ = activate_license(license_)
    license_ = validate_success(api_client.suspend_license(license_["id"], headers=LEGAL))
    assert license_["license_status"] == "SUSPENDED"
    assert license_["suspension_reason"] == "MANUAL"
    assert license_["marketing_status"] == "APPROVED"

    license_ = validate_success(api_client.reinstate_license(license_["id"], headers=LEGAL))
    assert license_["license_status"] == "ACTIVE"
    assert license_["suspension_reason"] == "NONE"
    assert license_["marketing_status"] == "APPROVED"
