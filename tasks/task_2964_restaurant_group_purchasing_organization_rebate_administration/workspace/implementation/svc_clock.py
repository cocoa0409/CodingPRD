"""The logical clock and the expiries advancing it causes (PRD §2.11)."""

from store import date_of_instant, db, iso_instant, parse_instant, touch


def set_clock(current_utc_text):
    """Move the logical clock and age out letters and rate cards.

    Moving the clock backwards is permitted and reverses nothing already expired.
    """
    instant = parse_instant(current_utc_text)
    db.clock = instant
    now_iso = iso_instant(instant)
    today = date_of_instant(now_iso)

    letters_expired = 0
    for letter in db.letters.values():
        if letter["status"] != "ACTIVE":
            continue
        # Half-open window: an effective_to at or before the new instant is over.
        if parse_instant(letter["effective_to"]) > instant:
            continue
        letter["status"] = "EXPIRED"
        touch(letter)
        letters_expired += 1
        member = db.members.get(letter["member_id"])
        if member is not None:
            member["active_letter_count"] -= 1
            touch(member)
        distributor = db.distributors.get(letter["distributor_id"])
        if distributor is not None:
            distributor["active_letter_count"] -= 1
            touch(distributor)

    cards_expired = 0
    for card in db.rate_cards.values():
        if card["status"] not in ("PROPOSED", "APPROVED"):
            continue
        # Closed range: a card only ages out once the date is strictly past.
        if not (card["effective_to"] < today):
            continue
        was_approved = card["status"] == "APPROVED"
        card["status"] = "EXPIRED"
        touch(card)
        cards_expired += 1
        if was_approved:
            item = db.items.get(card["contracted_item_id"])
            if item is not None:
                item["approved_rate_card_count"] -= 1
                touch(item)

    return {
        "current_utc": now_iso,
        "letters_expired": letters_expired,
        "rate_cards_expired": cards_expired,
    }
