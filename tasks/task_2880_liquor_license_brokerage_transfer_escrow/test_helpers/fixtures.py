"""Composite setup helpers.

Each test starts against an empty database, so every helper below builds its
preconditions from scratch using only the endpoints the PRD declares.

Ownership-gated calls always use the per-instance header builders with the real
entity id: a ``Broker`` acts as its ``Brokerage``, a ``Buyer`` as its
``BuyerProfile`` and a ``Seller`` as its ``SellerProfile``.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLASS_FEE_CENTS,
    EXPEDITE_TIER_0_BPS,
    EXPEDITE_TIER_1_BPS,
    EXPEDITE_TIER_1_MIN_SUBTOTAL_CENTS,
    EXPEDITE_TIER_2_BPS,
    EXPEDITE_TIER_2_MIN_SUBTOTAL_CENTS,
    DEFICIENCY_ROUND_FEE_CENTS,
    FILING_BASE_CENTS,
    POSTING_FEE_CENTS,
)
from . import factories as f
from .test_users import (
    ANALYST_ONE,
    ANALYST_TWO,
    TEST_USERS,
    make_broker_headers,
    make_buyer_headers,
    make_regulator_analyst_headers,
    make_seller_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["regulator_analyst_headers"]
ANALYST_2 = TEST_USERS["regulator_analyst_two_headers"]
ESCROW = TEST_USERS["escrow_officer_headers"]


# ─── Fee arithmetic used to tender exact amounts during setup ─────────────────

def compute_filing_fee(license_class: str, deficiency_round_count: int = 0) -> int:
    """The filing fee in its three pinned steps: an exact integer subtotal, an
    expedite rate selected from that subtotal, then the surcharge added on."""
    subtotal = (
        FILING_BASE_CENTS
        + CLASS_FEE_CENTS[license_class]
        + POSTING_FEE_CENTS
        + DEFICIENCY_ROUND_FEE_CENTS * deficiency_round_count
    )
    if subtotal >= EXPEDITE_TIER_2_MIN_SUBTOTAL_CENTS:
        rate = EXPEDITE_TIER_2_BPS
    elif subtotal >= EXPEDITE_TIER_1_MIN_SUBTOTAL_CENTS:
        rate = EXPEDITE_TIER_1_BPS
    else:
        rate = EXPEDITE_TIER_0_BPS
    surcharge = (subtotal * rate + 5000) // 10000
    return subtotal + surcharge


# ─── Single-step helpers ──────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock. Answers with the resulting current_utc."""
    return get_success_data(
        api_client.set_clock(f.set_clock_payload(to_iso8601), ADMIN)
    )


def create_county(**overrides) -> dict:
    return get_success_data(
        api_client.create_county(f.create_county_payload(**overrides), ADMIN)
    )


def create_seller(**overrides) -> dict:
    return get_success_data(
        api_client.create_seller_profile(
            f.create_seller_profile_payload(**overrides), ADMIN
        )
    )


def create_buyer(**overrides) -> dict:
    return get_success_data(
        api_client.create_buyer_profile(
            f.create_buyer_profile_payload(**overrides), ADMIN
        )
    )


def create_brokerage(**overrides) -> dict:
    return get_success_data(
        api_client.create_brokerage(f.create_brokerage_payload(**overrides), ADMIN)
    )


def create_license(county_id: str, owner_seller_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_license(
            f.create_license_payload(county_id, owner_seller_id, **overrides), ADMIN
        )
    )


def register_premises(buyer_id: str, county_id: str, brokerage_id: str = None,
                      **overrides) -> dict:
    """A candidate premises is registered by either a Broker or the Buyer itself."""
    headers = (make_broker_headers(brokerage_id) if brokerage_id
               else make_buyer_headers(buyer_id))
    return get_success_data(
        api_client.create_premises(
            f.create_premises_payload(buyer_id, county_id, **overrides), headers
        )
    )


def verify_zoning(premises_id: str, conditional_use_permit_status: str = "GRANTED",
                  analyst_id: str = ANALYST_ONE, **overrides) -> dict:
    return get_success_data(
        api_client.zoning_verification(
            premises_id,
            f.zoning_verification_payload(conditional_use_permit_status, **overrides),
            make_regulator_analyst_headers(analyst_id),
        )
    )


def record_landlord_consent(premises_id: str, landlord_consent_status: str = "GRANTED",
                            brokerage_id: str = None, buyer_id: str = None,
                            **overrides) -> dict:
    headers = (make_broker_headers(brokerage_id) if brokerage_id
               else make_buyer_headers(buyer_id))
    return get_success_data(
        api_client.landlord_consent(
            premises_id,
            f.landlord_consent_payload(landlord_consent_status, **overrides),
            headers,
        )
    )


def review_buyer(buyer_id: str, premises_id: str, review_mode: str = "FINAL_REVIEW",
                 analyst_id: str = ANALYST_ONE) -> dict:
    return get_success_data(
        api_client.qualification_review(
            buyer_id,
            f.qualification_review_payload(premises_id, review_mode),
            make_regulator_analyst_headers(analyst_id),
        )
    )


def create_listing(license_id: str, brokerage_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_listing(
            f.create_listing_payload(license_id, brokerage_id, **overrides),
            make_broker_headers(brokerage_id),
        )
    )


def activate_listing(listing_id: str, brokerage_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.activate_listing(
            listing_id, make_broker_headers(brokerage_id),
            f.activate_listing_payload(**overrides),
        )
    )


def draft_agreement(listing_id: str, buyer_id: str, premises_id: str,
                    expected_listing_version: int, brokerage_id: str,
                    **overrides) -> dict:
    return get_success_data(
        api_client.create_purchase_agreement(
            f.create_purchase_agreement_payload(
                listing_id, buyer_id, premises_id, expected_listing_version,
                **overrides
            ),
            make_broker_headers(brokerage_id),
        )
    )


def file_disclosure(agreement_id: str, brokerage_id: str, represents_seller=True,
                    represents_buyer=False, **overrides) -> dict:
    return get_success_data(
        api_client.create_disclosure(
            f.create_disclosure_payload(
                agreement_id, represents_seller, represents_buyer, **overrides
            ),
            make_broker_headers(brokerage_id),
        )
    )


def acknowledge_as_seller(disclosure_id: str, seller_id: str) -> dict:
    return get_success_data(
        api_client.acknowledge_disclosure(
            disclosure_id, f.acknowledge_disclosure_payload("SELLER"),
            make_seller_headers(seller_id),
        )
    )


def acknowledge_as_buyer(disclosure_id: str, buyer_id: str) -> dict:
    return get_success_data(
        api_client.acknowledge_disclosure(
            disclosure_id, f.acknowledge_disclosure_payload("BUYER"),
            make_buyer_headers(buyer_id),
        )
    )


def fund_escrow(agreement_id: str, amount_cents: int, buyer_id: str = None,
                **overrides) -> dict:
    """Funding is performed by the Buyer or by the EscrowOfficer."""
    headers = make_buyer_headers(buyer_id) if buyer_id else ESCROW
    return get_success_data(
        api_client.escrow_deposit(
            agreement_id, f.escrow_deposit_payload(amount_cents, **overrides), headers
        )
    )


def execute_agreement(agreement_id: str, brokerage_id: str) -> dict:
    return get_success_data(
        api_client.execute_agreement(agreement_id, make_broker_headers(brokerage_id))
    )


def file_application(agreement_id: str, fee_paid_cents: int, brokerage_id: str,
                     **overrides) -> dict:
    return get_success_data(
        api_client.create_transfer_application(
            f.create_transfer_application_payload(
                agreement_id, fee_paid_cents, **overrides
            ),
            make_broker_headers(brokerage_id),
        )
    )


def accept_review(application_id: str, analyst_id: str = ANALYST_ONE) -> dict:
    return get_success_data(
        api_client.accept_review(
            application_id, make_regulator_analyst_headers(analyst_id)
        )
    )


def issue_deficiency(application_id: str, deficiency_codes=None,
                     analyst_id: str = ANALYST_ONE) -> dict:
    return get_success_data(
        api_client.issue_deficiency(
            application_id, f.deficiency_payload(deficiency_codes),
            make_regulator_analyst_headers(analyst_id),
        )
    )


def resubmit_application(application_id: str, fee_paid_cents: int,
                         brokerage_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.resubmit_application(
            application_id,
            f.resubmit_application_payload(fee_paid_cents, **overrides),
            make_broker_headers(brokerage_id),
        )
    )


def post_notice(application_id: str, analyst_id: str = ANALYST_ONE) -> dict:
    return get_success_data(
        api_client.post_notice(
            application_id, make_regulator_analyst_headers(analyst_id)
        )
    )


def file_protest(application_id: str, analyst_id: str = ANALYST_ONE,
                 **overrides) -> dict:
    return get_success_data(
        api_client.create_protest(
            f.create_protest_payload(application_id, **overrides),
            make_regulator_analyst_headers(analyst_id),
        )
    )


def answer_protest(protest_id: str, brokerage_id: str,
                   response_text_ref: str = "resp-1") -> dict:
    return get_success_data(
        api_client.respond_to_protest(
            protest_id, f.protest_response_payload(response_text_ref),
            make_broker_headers(brokerage_id),
        )
    )


def decide_application(application_id: str, decision: str,
                       analyst_id: str = ANALYST_TWO, **overrides) -> dict:
    return get_success_data(
        api_client.decide_application(
            application_id, f.decision_payload(decision, **overrides),
            make_regulator_analyst_headers(analyst_id),
        )
    )


def settle_escrow(agreement_id: str, disposition: str, **overrides) -> dict:
    """Settlement is the sole preserve of the EscrowOfficer."""
    return get_success_data(
        api_client.escrow_settlement(
            agreement_id, f.escrow_settlement_payload(disposition, **overrides), ESCROW
        )
    )


def file_safekeeping(license_id: str, expected_license_version: int,
                     filing_type: str = "INITIAL", requested_months: int = None,
                     brokerage_id: str = None, seller_id: str = None,
                     **overrides) -> dict:
    """A Broker or the owning Seller files a safekeeping petition."""
    headers = (make_broker_headers(brokerage_id) if brokerage_id
               else make_seller_headers(seller_id))
    return get_success_data(
        api_client.create_safekeeping_filing(
            f.create_safekeeping_filing_payload(
                license_id, expected_license_version, filing_type,
                requested_months, **overrides
            ),
            headers,
        )
    )


def decide_safekeeping(filing_id: str, decision: str,
                       analyst_id: str = ANALYST_ONE) -> dict:
    return get_success_data(
        api_client.decide_safekeeping_filing(
            filing_id, f.safekeeping_decision_payload(decision),
            make_regulator_analyst_headers(analyst_id),
        )
    )


# ─── Read-back helpers ────────────────────────────────────────────────────────

def read_county(county_id: str) -> dict:
    return get_success_data(api_client.get_county(county_id, ADMIN))


def read_license(license_id: str) -> dict:
    return get_success_data(api_client.get_license(license_id, ADMIN))


def read_premises(premises_id: str) -> dict:
    return get_success_data(api_client.get_premises(premises_id, ADMIN))


def read_buyer(buyer_id: str) -> dict:
    return get_success_data(api_client.get_buyer_profile(buyer_id, ADMIN))


def read_listing(listing_id: str) -> dict:
    return get_success_data(api_client.get_listing(listing_id, ADMIN))


def preview_valuation(listing_id: str, headers=None) -> dict:
    """The read-only both-variants valuation preview for one listing."""
    return get_success_data(
        api_client.get_valuation_preview(listing_id, headers or ADMIN)
    )


def read_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_purchase_agreement(agreement_id, ADMIN))


def read_disclosure(disclosure_id: str) -> dict:
    return get_success_data(api_client.get_disclosure(disclosure_id, ADMIN))


def read_application(application_id: str) -> dict:
    return get_success_data(api_client.get_transfer_application(application_id, ADMIN))


def read_protest(protest_id: str) -> dict:
    return get_success_data(api_client.get_protest(protest_id, ADMIN))


def read_filing(filing_id: str) -> dict:
    return get_success_data(api_client.get_safekeeping_filing(filing_id, ADMIN))


def ledger_rows(agreement_id: str) -> list:
    """The immutable escrow ledger for one agreement in append order."""
    body = api_client.get_agreement_escrow_ledger(agreement_id, ADMIN)
    return body.json()["data"]


# ─── The transfer proceeding, staged ──────────────────────────────────────────

SCENARIO_STAGES = (
    "reference",
    "premises",
    "qualified",
    "listing_draft",
    "listing_active",
    "agreement_draft",
    "disclosure_filed",
    "disclosure_acked",
    "escrow_held",
    "executed",
    "application_filed",
    "application_under_review",
    "application_posted",
)


def _stage_at_least(stage: str, target: str) -> bool:
    return SCENARIO_STAGES.index(stage) >= SCENARIO_STAGES.index(target)


def setup_scenario(
    stage="application_posted",
    county_overrides=None,
    seller_overrides=None,
    buyer_overrides=None,
    brokerage_overrides=None,
    license_overrides=None,
    premises_overrides=None,
    listing_overrides=None,
    activate_overrides=None,
    agreement_overrides=None,
    premises_by_buyer=False,
    verify_zoning_step=True,
    cup_status="GRANTED",
    landlord_step=True,
    landlord_status="GRANTED",
    review_step=True,
    review_mode="FINAL_REVIEW",
    represents_seller=True,
    represents_buyer=False,
    acknowledge=True,
    deposit_by_buyer=False,
    deposit_amount=None,
    application_fee=None,
    post_notice_at=None,
    analyst_id=ANALYST_ONE,
):
    """Walk the transfer proceeding from an empty database up to ``stage``.

    Returns a dict carrying every record created plus ready-made headers for the
    acting parties. Stages, in order: reference, premises, qualified,
    listing_draft, listing_active, agreement_draft, disclosure_filed,
    disclosure_acked, escrow_held, executed, application_filed,
    application_under_review, application_posted.
    """
    assert stage in SCENARIO_STAGES, f"Unknown stage {stage!r}"
    s = {}

    county = create_county(**(county_overrides or {}))
    seller = create_seller(**(seller_overrides or {}))
    buyer = create_buyer(**(buyer_overrides or {}))
    brokerage = create_brokerage(**(brokerage_overrides or {}))
    license_row = create_license(county["id"], seller["id"], **(license_overrides or {}))
    s.update({
        "county": county, "seller": seller, "buyer": buyer,
        "brokerage": brokerage, "license": license_row,
        "county_id": county["id"], "seller_id": seller["id"],
        "buyer_id": buyer["id"], "brokerage_id": brokerage["id"],
        "license_id": license_row["id"],
        "admin_headers": ADMIN,
        "analyst_headers": make_regulator_analyst_headers(analyst_id),
        "analyst_two_headers": ANALYST_2,
        "escrow_headers": ESCROW,
        "broker_headers": make_broker_headers(brokerage["id"]),
        "buyer_headers": make_buyer_headers(buyer["id"]),
        "seller_headers": make_seller_headers(seller["id"]),
    })
    if not _stage_at_least(stage, "premises"):
        return s

    premises = register_premises(
        buyer["id"], county["id"],
        brokerage_id=None if premises_by_buyer else brokerage["id"],
        **(premises_overrides or {}),
    )
    if verify_zoning_step:
        premises = verify_zoning(premises["id"], cup_status, analyst_id)
    if landlord_step:
        premises = record_landlord_consent(
            premises["id"], landlord_status, brokerage_id=brokerage["id"]
        )
    s["premises"] = premises
    s["premises_id"] = premises["id"]
    if not _stage_at_least(stage, "qualified"):
        return s

    if review_step:
        s["buyer"] = review_buyer(buyer["id"], premises["id"], review_mode, analyst_id)
    if not _stage_at_least(stage, "listing_draft"):
        return s

    listing = create_listing(
        license_row["id"], brokerage["id"], **(listing_overrides or {})
    )
    s["listing"] = listing
    s["listing_id"] = listing["id"]
    if not _stage_at_least(stage, "listing_active"):
        return s

    listing = activate_listing(
        listing["id"], brokerage["id"], **(activate_overrides or {})
    )
    s["listing"] = listing
    if not _stage_at_least(stage, "agreement_draft"):
        return s

    agreement_kwargs = dict(agreement_overrides or {})
    expected_version = agreement_kwargs.pop(
        "expected_listing_version", listing["version"]
    )
    agreement = draft_agreement(
        listing["id"], buyer["id"], premises["id"], expected_version,
        brokerage["id"], **agreement_kwargs,
    )
    s["agreement"] = agreement
    s["agreement_id"] = agreement["id"]
    if not _stage_at_least(stage, "disclosure_filed"):
        return s

    disclosure = file_disclosure(
        agreement["id"], brokerage["id"], represents_seller, represents_buyer
    )
    s["disclosure"] = disclosure
    s["disclosure_id"] = disclosure["id"]
    if not _stage_at_least(stage, "disclosure_acked"):
        return s

    if acknowledge:
        if represents_seller:
            disclosure = acknowledge_as_seller(disclosure["id"], seller["id"])
        if represents_buyer:
            disclosure = acknowledge_as_buyer(disclosure["id"], buyer["id"])
        s["disclosure"] = disclosure
    if not _stage_at_least(stage, "escrow_held"):
        return s

    amount = (agreement["required_deposit_cents"] if deposit_amount is None
              else deposit_amount)
    s["agreement"] = fund_escrow(
        agreement["id"], amount,
        buyer_id=buyer["id"] if deposit_by_buyer else None,
    )
    if not _stage_at_least(stage, "executed"):
        return s

    s["agreement"] = execute_agreement(agreement["id"], brokerage["id"])
    if not _stage_at_least(stage, "application_filed"):
        return s

    fee = (compute_filing_fee(license_row["license_class"])
           if application_fee is None else application_fee)
    application = file_application(agreement["id"], fee, brokerage["id"])
    s["application"] = application
    s["application_id"] = application["id"]
    s["filing_fee_cents"] = fee
    if not _stage_at_least(stage, "application_under_review"):
        return s

    s["application"] = accept_review(application["id"], analyst_id)
    if not _stage_at_least(stage, "application_posted"):
        return s

    if post_notice_at:
        set_clock(post_notice_at)
    s["application"] = post_notice(application["id"], analyst_id)
    return s


# ─── Valuation and quota benches ──────────────────────────────────────────────

def setup_comparable_bench(comp_prices=(), license_class="CLASS_47_ONSALE_GENERAL",
                           subject_receipts_cents=120000000,
                           ask_price_cents=18500000,
                           county_overrides=None, seller_overrides=None,
                           brokerage_overrides=None, subject_overrides=None,
                           comp_overrides=None, activate=False,
                           activate_overrides=None):
    """A county stocked with priced peer licenses plus one unpriced subject
    license carried to a DRAFT (or ACTIVE) listing.

    Every peer contributes its ``last_transfer_price_cents`` to the comparable
    set for a subject of the same county and class; the subject itself is always
    excluded.
    """
    county = create_county(**(county_overrides or {}))
    seller = create_seller(**(seller_overrides or {}))
    brokerage = create_brokerage(**(brokerage_overrides or {}))

    comps = []
    for index, price in enumerate(comp_prices, start=1):
        overrides = {
            "license_number": f"COMP-{index}",
            "license_class": license_class,
            "annual_gross_receipts_cents": 0,
            "last_transfer_price_cents": price,
        }
        overrides.update(comp_overrides or {})
        comps.append(create_license(county["id"], seller["id"], **overrides))

    subject_kwargs = {
        "license_number": "SUBJ-1",
        "license_class": license_class,
        "annual_gross_receipts_cents": subject_receipts_cents,
    }
    subject_kwargs.update(subject_overrides or {})
    subject = create_license(county["id"], seller["id"], **subject_kwargs)

    listing = create_listing(
        subject["id"], brokerage["id"], ask_price_cents=ask_price_cents
    )
    if activate:
        listing = activate_listing(
            listing["id"], brokerage["id"], **(activate_overrides or {})
        )

    return {
        "county": county, "county_id": county["id"],
        "seller": seller, "seller_id": seller["id"],
        "brokerage": brokerage, "brokerage_id": brokerage["id"],
        "comps": comps,
        "license": subject, "license_id": subject["id"],
        "listing": listing, "listing_id": listing["id"],
        "broker_headers": make_broker_headers(brokerage["id"]),
        "admin_headers": ADMIN,
        "analyst_headers": ANALYST,
    }


# ─── Safekeeping bench ────────────────────────────────────────────────────────

def setup_safekeeping_bench(last_active_date="2026-02-02",
                            license_class="CLASS_41_ONSALE_BEER_WINE",
                            annual_gross_receipts_cents=20000000,
                            license_number="SON-41-1",
                            county_overrides=None, seller_overrides=None,
                            brokerage_overrides=None, license_overrides=None):
    """A county, a cleared selling licensee, a brokerage and one idle license
    whose nonuse clock started on ``last_active_date``."""
    county = create_county(**(county_overrides or {}))
    seller = create_seller(**(seller_overrides or {}))
    brokerage = create_brokerage(**(brokerage_overrides or {}))
    overrides = {
        "license_number": license_number,
        "license_class": license_class,
        "annual_gross_receipts_cents": annual_gross_receipts_cents,
        "last_active_date": last_active_date,
    }
    overrides.update(license_overrides or {})
    license_row = create_license(county["id"], seller["id"], **overrides)
    return {
        "county": county, "county_id": county["id"],
        "seller": seller, "seller_id": seller["id"],
        "brokerage": brokerage, "brokerage_id": brokerage["id"],
        "license": license_row, "license_id": license_row["id"],
        "admin_headers": ADMIN,
        "analyst_headers": ANALYST,
        "broker_headers": make_broker_headers(brokerage["id"]),
        "seller_headers": make_seller_headers(seller["id"]),
    }


# ─── Late-lifecycle shortcuts ─────────────────────────────────────────────────

def advance_to_decision(scenario: dict, decision="APPROVED", decision_clock=None,
                        analyst_id=ANALYST_TWO):
    """Move the logical clock strictly past the posting end, then issue the
    decision under a different analyst identifier than the accepting one."""
    if decision_clock:
        set_clock(decision_clock)
    scenario["application"] = decide_application(
        scenario["application_id"], decision, analyst_id
    )
    return scenario["application"]


def setup_closed_agreement(post_notice_at="2026-08-10T00:00:00Z",
                           decision_clock="2026-09-10T00:00:00Z",
                           **scenario_kwargs):
    """The full happy path through an APPROVED transfer decision: the agreement's
    contract dimension is CLOSED while its money dimension is still HELD."""
    scenario = setup_scenario(
        stage="application_posted", post_notice_at=post_notice_at, **scenario_kwargs
    )
    advance_to_decision(scenario, "APPROVED", decision_clock)
    scenario["agreement"] = read_agreement(scenario["agreement_id"])
    return scenario


def setup_denied_agreement(post_notice_at="2026-08-10T00:00:00Z",
                           decision_clock="2026-09-10T00:00:00Z",
                           **scenario_kwargs):
    """The full path through a DENIED transfer decision, which moves no license,
    listing or agreement field and leaves the escrow HELD."""
    scenario = setup_scenario(
        stage="application_posted", post_notice_at=post_notice_at, **scenario_kwargs
    )
    advance_to_decision(scenario, "DENIED", decision_clock)
    scenario["agreement"] = read_agreement(scenario["agreement_id"])
    return scenario


def add_parallel_transfer(scenario: dict, license_number="SON-47-2",
                          ask_price_cents=18500000,
                          closing_window_start="2026-09-01T00:00:00Z",
                          license_overrides=None, agreement_overrides=None,
                          take_into_review=True):
    """Add a second license, listing, executed agreement and transfer application
    that share the first scenario's premises, buyer and brokerage."""
    overrides = {"license_number": license_number}
    overrides.update(license_overrides or {})
    license_row = create_license(
        scenario["county_id"], scenario["seller_id"], **overrides
    )
    listing = create_listing(
        license_row["id"], scenario["brokerage_id"], ask_price_cents=ask_price_cents
    )
    listing = activate_listing(listing["id"], scenario["brokerage_id"])
    agreement_kwargs = {"closing_window_start": closing_window_start}
    agreement_kwargs.update(agreement_overrides or {})
    agreement = draft_agreement(
        listing["id"], scenario["buyer_id"], scenario["premises_id"],
        listing["version"], scenario["brokerage_id"], **agreement_kwargs,
    )
    disclosure = file_disclosure(agreement["id"], scenario["brokerage_id"])
    acknowledge_as_seller(disclosure["id"], scenario["seller_id"])
    fund_escrow(agreement["id"], agreement["required_deposit_cents"])
    execute_agreement(agreement["id"], scenario["brokerage_id"])
    application = file_application(
        agreement["id"],
        compute_filing_fee(license_row["license_class"]),
        scenario["brokerage_id"],
    )
    if take_into_review:
        application = accept_review(application["id"])
    return {
        "license": license_row, "license_id": license_row["id"],
        "listing": listing, "listing_id": listing["id"],
        "agreement": agreement, "agreement_id": agreement["id"],
        "disclosure": disclosure, "disclosure_id": disclosure["id"],
        "application": application, "application_id": application["id"],
    }


def create_second_brokerage(firm_name="Gulf Brokers",
                            state_broker_license_no="BRK-0002",
                            commission_rate_bps=600, **overrides):
    """A second, unrelated firm — used to prove ownership is compared against the
    brokerage_id of the resource being acted on."""
    return create_brokerage(
        firm_name=firm_name,
        state_broker_license_no=state_broker_license_no,
        commission_rate_bps=commission_rate_bps,
        **overrides,
    )
