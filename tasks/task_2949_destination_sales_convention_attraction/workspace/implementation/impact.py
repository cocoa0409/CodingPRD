"""Economic impact estimate creation (PRD 3.6).

An estimate is an immutable snapshot: it carries `id`, `created_at` and a
`computed_at` stamped from the logical clock, with no `updated_at` and no
`version`.  Both variants share the same three-component structure and in both
the components are each rounded to two decimals before they are added together.
"""

import calc
from store import db


def create_estimate(opportunity, variant):
    if variant == "PROVISIONAL":
        basis, lodging, delegate, exhibitor = calc.provisional_figures(opportunity)
    else:
        basis, lodging, delegate, exhibitor = calc.final_figures(opportunity)
    direct, total_impact, tax_yield = calc.estimate_tail(lodging, delegate, exhibitor)
    row = db.new_row(versioned=False)
    row.update({
        "opportunity_id": opportunity["id"],
        "variant": variant,
        "room_nights_basis": basis,
        "lodging_spend_amount": lodging,
        "delegate_spend_amount": delegate,
        "exhibitor_spend_amount": exhibitor,
        "direct_spend_amount": direct,
        "total_impact_amount": total_impact,
        "lodging_tax_yield_amount": tax_yield,
        "computed_at": db.clock,
    })
    db.estimates[row["id"]] = row
    return row


def final_variant_available(opportunity_id):
    """A FINAL estimate requires at least one pickup record on a commitment of
    this lead in status COMMITTED or RELEASED."""
    return bool(calc.eligible_pickups(opportunity_id))
