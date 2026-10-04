"""Contributor trust: dual provisional/finalized variants."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    make_contributor,
    make_listing,
    make_map_edit,
    make_region,
    make_rejected_edit,
    open_edit_review_ticket,
    resolve_ticket,
    set_clock,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_trust_variants_diverge_on_young_rejection(api):
    """PRD §2.7: "The `provisional_trust_score` counts every map edit the
    contributor has ever filed, regardless of age, and drives auto-validation
    routing display and public presentation. The `finalized_trust_score` counts
    only edits created at least seven days before the current logical clock
    time — young edits have not yet earned their weight — and it is the
    finalized variant that gates automatic contributor restriction and feeds
    the trust component of edit auto-validation."

    Design: Difficulty/dual_variant_calc/trust_provisional_vs_finalized_diverge_on_young_rejection
    """
    region = make_region(name="R1")
    contributor = make_contributor(region["id"], display_name="C1", email="c1@x.com")
    listing = make_listing(region["id"], name="Cafe One")
    edit = make_rejected_edit(listing, contributor["id"])
    assert edit["status"] == "REJECTED"

    set_clock("2026-09-02T00:00:00Z")
    resp = api.get_contributor(contributor["id"], ADMIN)
    data = validate_success(resp)
    # base 50 - 6 per rejected edit; the rejection is 1 day old.
    assert data["provisional_trust_score"] == 44, (
        f"provisional must count the young rejection (50-6=44), "
        f"got {data['provisional_trust_score']}"
    )
    assert data["finalized_trust_score"] == 50, (
        f"finalized must ignore edits younger than 7 days (stays 50), "
        f"got {data['finalized_trust_score']}"
    )


def test_trust_variants_converge_after_seven_days(api):
    """PRD §2.7: "The `provisional_trust_score` counts every map edit the
    contributor has ever filed, regardless of age, and drives auto-validation
    routing display and public presentation. The `finalized_trust_score` counts
    only edits created at least seven days before the current logical clock
    time — young edits have not yet earned their weight — and it is the
    finalized variant that gates automatic contributor restriction and feeds
    the trust component of edit auto-validation."

    Design: Difficulty/dual_variant_calc/trust_provisional_vs_finalized_diverge_on_young_rejection
    """
    region = make_region(name="R1b")
    contributor = make_contributor(region["id"], display_name="C1b", email="c1b@x.com")
    listing = make_listing(region["id"], name="Cafe One B")
    edit = make_rejected_edit(listing, contributor["id"])
    assert edit["status"] == "REJECTED"

    set_clock("2026-09-09T00:00:00Z")
    resp = api.get_contributor(contributor["id"], ADMIN)
    data = validate_success(resp)
    # Once the rejection is 8 days old both variants count it.
    assert data["provisional_trust_score"] == 44
    assert data["finalized_trust_score"] == 44, (
        f"finalized counts the rejection once it is 7+ days old (50-6=44), "
        f"got {data['finalized_trust_score']}"
    )
