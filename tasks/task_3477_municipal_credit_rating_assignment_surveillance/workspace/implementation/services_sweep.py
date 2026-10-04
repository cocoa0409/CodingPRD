"""The time-driven non-disclosure sweep (PRD §3.5, scaffold
nondisclosure_sweep) plus review-item escalation (PRD §3.6). Runs on every
POST /_clock/set_current_utc. Evaluation order is pinned:

  (1) obligations of PUBLISHED ratings flip PENDING -> OVERDUE ->
      DELINQUENT -> DEFAULTED (a single jump walks every threshold, in
      created_at ASC order; delinquency logs OBLIGATION_DELINQUENT; default
      sets the issuer's delinquent_flag);
  (2) each obligation that hit DEFAULTED withdraws its rating for
      NON_DISCLOSURE (no version increment) and logs RATING_WITHDRAWN;
  (3) PENDING review items whose due_at is behind the clock ESCALATE
      (IN_REVIEW items are exempt);
  (4) surveillance postures recompute for ratings still PUBLISHED; ratings
      withdrawn in the same sweep keep their frozen DELINQUENT posture.

All comparisons are strictly greater-than: clock == due_at changes nothing.
"""
import timeutil
from constants import (
    DELINQUENCY_GRACE_DAYS,
    EVENT_OBLIGATION_DELINQUENT,
    EVENT_RATING_WITHDRAWN,
    NONDISCLOSURE_WITHDRAW_DAYS,
)
from services_disclosure import recompute_posture
from store import db, notify, touch, touch_no_version


def _open_obligations_of_published():
    items = []
    for o in db.obligations.values():
        if o["status"] not in ("PENDING", "OVERDUE", "DELINQUENT"):
            continue
        rating = db.ratings.get(o["rating_id"])
        if rating is not None and rating["status"] == "PUBLISHED":
            items.append(o)
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    return items


def run_sweep():
    clock = db.now()

    # ---- step (1): obligation state flips, thresholds in sequence ---------
    defaulted = []
    for obligation in _open_obligations_of_published():
        rating = db.ratings[obligation["rating_id"]]
        issuer = db.issuers.get(rating["issuer_id"])
        due_at = obligation["due_at"]
        # A single clock jump may walk an obligation through several flips.
        if obligation["status"] == "PENDING" and clock > due_at:
            obligation["status"] = "OVERDUE"
            touch(obligation)
            rating["surveillance_posture"] = "GRACE"
        if obligation["status"] == "OVERDUE" and clock > timeutil.add_days(
            due_at, DELINQUENCY_GRACE_DAYS
        ):
            obligation["status"] = "DELINQUENT"
            touch(obligation)
            rating["surveillance_posture"] = "DELINQUENT"
            notify(
                rating["issuer_id"],
                EVENT_OBLIGATION_DELINQUENT,
                obligation["id"],
                "Disclosure obligation %s for rating %s is delinquent (period %s)."
                % (obligation["id"], rating["id"], obligation["period_index"]),
            )
        if obligation["status"] == "DELINQUENT" and clock > timeutil.add_days(
            due_at, NONDISCLOSURE_WITHDRAW_DAYS
        ):
            obligation["status"] = "DEFAULTED"
            touch(obligation)
            if issuer is not None and not issuer["delinquent_flag"]:
                issuer["delinquent_flag"] = True
                touch(issuer)
            defaulted.append(obligation)

    # ---- step (2): non-disclosure withdrawals ------------------------------
    for obligation in defaulted:
        rating = db.ratings[obligation["rating_id"]]
        if rating["status"] != "PUBLISHED":
            continue  # already withdrawn by an earlier default in this sweep
        rating["status"] = "WITHDRAWN"
        rating["withdraw_reason"] = "NON_DISCLOSURE"
        rating["withdrawn_at"] = clock
        rating["notch_at_withdrawal"] = rating["notch"]
        # PRD §3.5: the sweep-driven withdrawal carries no version increment;
        # posture stays frozen (DELINQUENT).
        touch_no_version(rating)
        notify(
            rating["issuer_id"],
            EVENT_RATING_WITHDRAWN,
            rating["id"],
            "Rating %s withdrawn for non-disclosure." % rating["id"],
        )

    # ---- step (3): review-item escalations ---------------------------------
    for item in sorted(db.review_items.values(), key=lambda i: (i["created_at"], i["_seq"])):
        if item["status"] == "PENDING" and clock > item["due_at"]:
            item["status"] = "ESCALATED"
            touch(item)

    # ---- step (4): posture recomputation for ratings still PUBLISHED -------
    for rating in db.ratings.values():
        recompute_posture(rating)
