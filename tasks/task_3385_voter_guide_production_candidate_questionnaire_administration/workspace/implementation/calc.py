"""Calculation rules (scaffold 1.3 / PRD 2.9, 3.4-3.6).

All rounding is half-up; grades round once at the very end to 2dp, the
completion index to 1dp, the balance ratio to 4dp. Money-style math uses
Decimal; page/copy numbers are integers with round-up division.
"""
import math
import re
from decimal import Decimal, ROUND_HALF_UP

# Tokens are stripped of leading/trailing punctuation: , . : ; ! ? " '
PUNCT_STRIP = ",.;:!?\"'"

DEFAULT_WORD_LIMIT = 100
ARGUMENT_WORD_LIMIT = 250
GRADE_THRESHOLD = Decimal("8.0")
BALANCE_THRESHOLD = Decimal("0.15")
NEUTRAL_APPROVALS_REQUIRED = 2
FORUM_QUORUM = 2
WORDS_PER_COLUMN = 10
COLUMNS_PER_PAGE = 2
FRONT_MATTER_PAGES = 2

_VOWEL_RUN = re.compile(r"[aeiouy]+")
_SENTENCE_SPLIT = re.compile(r"[.!?]")


def tokens_of(text):
    """Whitespace-split, each token stripped of lead/trail punctuation."""
    return [t.strip(PUNCT_STRIP) for t in text.split()]


def is_url(token):
    return "://" in token or token.startswith("www.")


def word_count(text, policy):
    """STRICT: URL tokens count 0, other tokens count their hyphen-separated
    parts. LENIENT: every token counts exactly 1."""
    toks = tokens_of(text)
    if policy == "LENIENT":
        return len(toks)
    total = 0
    for t in toks:
        if is_url(t):
            continue
        total += len(t.split("-"))
    return total


def _syllables(word):
    return max(1, len(_VOWEL_RUN.findall(word.lower())))


def reading_grades(text):
    """Return (grade_fk, grade_smog), each rounded half-up to 2dp."""
    toks = tokens_of(text)
    words = len(toks)
    sentences = len([s for s in _SENTENCE_SPLIT.split(text) if s.strip()])
    if words == 0 or sentences == 0:
        return 0.0, 0.0
    syllables = sum(_syllables(t) for t in toks)
    polysyllables = sum(1 for t in toks if _syllables(t) >= 3)
    fk = 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59
    smog = 1.043 * math.sqrt(polysyllables * 30 / sentences) + 3.1291
    fk_q = Decimal(repr(fk)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    smog_q = Decimal(repr(smog)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(fk_q), float(smog_q)


def balance(pro_word_total, con_word_total):
    """balance_ratio 4dp half-up; balance_flag strictly above 0.15."""
    divisor = max(pro_word_total, con_word_total, 1)
    ratio = (Decimal(abs(pro_word_total - con_word_total)) / Decimal(divisor))
    ratio = ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(ratio), ratio > BALANCE_THRESHOLD


def completion_index(submitted_count, invited_count):
    if invited_count == 0:
        return 0.0
    value = (Decimal(100 * submitted_count) / Decimal(invited_count))
    value = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(value)


def ceil_div(a, b):
    return -(-a // b)


def guide_page_estimate(contest_word_totals):
    """Per-contest nested rounding, then sum (order is significant, PRD 3.6)."""
    pages_total = FRONT_MATTER_PAGES
    for words in contest_word_totals:
        columns = ceil_div(words, WORDS_PER_COLUMN)
        pages_total += ceil_div(columns, COLUMNS_PER_PAGE)
    return pages_total


def print_copy_allocation(print_run_total, channel_requests):
    """Waterfall: tiers ascending; within a tier requested DESC then
    channel_code ASC; each channel gets min(requested, remaining)."""
    remaining = print_run_total
    allocations = []
    for tier in (1, 2, 3):
        group = [r for r in channel_requests if r["priority_tier"] == tier]
        group.sort(key=lambda r: (-r["requested"], r["channel_code"]))
        for r in group:
            allocated = min(r["requested"], remaining)
            remaining -= allocated
            allocations.append({
                "channel_code": r["channel_code"],
                "requested": r["requested"],
                "priority_tier": r["priority_tier"],
                "allocated": allocated,
            })
    return allocations, remaining
