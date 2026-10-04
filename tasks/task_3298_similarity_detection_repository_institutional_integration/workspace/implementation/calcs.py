"""Calculation rules: similarity_score, match_weighting, ai_confidence_score."""
from decimal import Decimal, ROUND_HALF_UP

from services import CATEGORY_MULT, BAND_MARGIN


def round_half_up_int(x):
    """x may be Decimal or numeric; return int rounded half-up."""
    d = x if isinstance(x, Decimal) else Decimal(str(x))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_weighted_words(matched_word_count, category):
    mult = CATEGORY_MULT[category]
    return round_half_up_int(Decimal(matched_word_count) * mult)


def _cluster_dedup(fragments):
    """Cluster fragments by transitive overlap of [offset_start, offset_start+matched_word_count);
    keep the max weighted_words per cluster (tie: earliest created_at)."""
    # Build clusters via union-find over pairwise overlaps.
    n = len(fragments)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    intervals = [
        (f["offset_start"], f["offset_start"] + f["matched_word_count"]) for f in fragments
    ]
    for i in range(n):
        for j in range(i + 1, n):
            a0, a1 = intervals[i]
            b0, b1 = intervals[j]
            if a0 < b1 and b0 < a1:  # overlap
                union(i, j)

    clusters = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(fragments[i])

    survivors = []
    for members in clusters.values():
        # max weighted_words; tie-break earliest created_at
        best = max(members, key=lambda f: f["weighted_words"])
        best = min(
            (m for m in members if m["weighted_words"] == best["weighted_words"]),
            key=lambda f: f["created_at"],
        )
        survivors.append(best)
    return survivors


def similarity_score_bps(fragments, word_count):
    """fragments: pre-filtered, non-excluded. Returns integer bps."""
    if word_count <= 0:
        return 0
    survivors = _cluster_dedup(fragments)
    matched = sum(f["weighted_words"] for f in survivors)
    ratio = Decimal(matched) / Decimal(word_count)
    if ratio > 1:
        ratio = Decimal(1)
    return round_half_up_int(Decimal(10000) * ratio)


def filtered_fragment_set(fragments, snapshot):
    out = []
    for f in fragments:
        if f["excluded"]:
            continue
        if snapshot.get("exclude_quotes") and f["match_category"] == "DIRECT_QUOTE":
            continue
        if snapshot.get("exclude_bibliography") and f["match_category"] == "BIBLIOGRAPHY_ENTRY":
            continue
        if snapshot.get("exclude_small_matches") and f["matched_word_count"] < snapshot.get(
            "small_match_threshold_words", 8
        ):
            continue
        out.append(f)
    return out


def ai_confidence(burstiness, perplexity, stylometry):
    b = Decimal(str(burstiness))
    p = Decimal(str(perplexity))
    s = Decimal(str(stylometry))
    base = b * Decimal("0.5") + p * Decimal("0.3") + s * Decimal("0.2")
    ai_score_bps = round_half_up_int(Decimal(10000) * base)
    spread = max(b, p, s) - min(b, p, s)
    if spread <= Decimal("0.15"):
        band = "HIGH"
    elif spread <= Decimal("0.30"):
        band = "MEDIUM"
    else:
        band = "LOW"
    conservative = max(0, ai_score_bps - BAND_MARGIN[band])
    return ai_score_bps, band, conservative
