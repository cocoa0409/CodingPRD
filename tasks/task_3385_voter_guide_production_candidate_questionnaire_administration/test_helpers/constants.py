"""Domain thresholds and shared literals from the PRD.

Numeric constants come from the calculation and workflow rules in PRD
§2.4, §2.9, §3.4-§3.7; timestamp literals are the shared logical-clock
schedule used by the fixtures (filing deadline, questionnaire window).
"""

# ── Logical clock (PRD §2.4) ────────────────────────────────────────────
CLOCK_START = "2026-09-01T00:00:00Z"

# Shared schedule used across fixtures: filings close 2026-09-15T17:00:00Z,
# the questionnaire window closes 2026-10-01T17:00:00Z.
FILING_DEADLINE = "2026-09-15T17:00:00Z"
PAST_FILING_DEADLINE = "2026-09-16T00:00:00Z"
QUESTIONNAIRE_DUE_AT = "2026-10-01T17:00:00Z"
PAST_DUE_AT = "2026-10-02T00:00:00Z"

# ── Word counting (PRD §2.9, §3.4, §3.5) ────────────────────────────────
DEFAULT_WORD_LIMIT = 100          # contest questionnaire_word_limit default
ARGUMENT_WORD_LIMIT = 250         # measure-argument auto-verdict threshold

# ── Readability gate (PRD §3.5, §3.6) ───────────────────────────────────
GRADE_THRESHOLD = 8.0             # accessibility gate; exactly 8.0 passes

# ── Neutrality review (PRD §3.5) ────────────────────────────────────────
NEUTRAL_APPROVALS_REQUIRED = 2    # distinct NEUTRAL reviewers per round
BALANCE_THRESHOLD = 0.15          # balance_ratio strictly greater flags

# ── Forums (PRD §3.7) ───────────────────────────────────────────────────
FORUM_QUORUM = 2                  # eligible candidates needed to confirm
QUESTION_CAP = 5                  # max SELECTED questions per forum
MODERATOR_BUFFER_HOURS = 24       # min gap between one moderator's forums

# ── Volunteers (PRD §3.1) ───────────────────────────────────────────────
ATTESTATION_PERIOD_DAYS = 90      # attestation_expires_at = created + 90d

# ── Page estimate (PRD §3.6) ────────────────────────────────────────────
WORDS_PER_COLUMN = 10
COLUMNS_PER_PAGE = 2
FRONT_MATTER_PAGES = 2

# ── Shared texts whose word/grade arithmetic is pinned by the PRD ───────
# 11 words, 13 syllables, 1 polysyllable ("banana"), 1 sentence:
# FK = 0.39*11 + 11.8*(13/11) - 15.59 = 2.65; SMOG = 1.043*sqrt(30) + 3.1291
# = 8.84 (PRD §3.5 formulas, rounded half-up to 2dp).
EXPLANATION_TEXT = "Cats run fast with dogs on soft brown mats near banana."
EXPLANATION_GRADE_FK = 2.65
EXPLANATION_GRADE_SMOG = 8.84

TEN_WORDS = "one two three four five six seven eight nine ten"
ELEVEN_WORDS = TEN_WORDS + " eleven"
TWENTY_ONE_WORDS = (
    "one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone"
)
THIRTY_WORDS = (
    TWENTY_ONE_WORDS
    + " twentytwo twentythree twentyfour twentyfive twentysix twentyseven "
    "twentyeight twentynine thirty"
)
FIVE_WORDS = "one two three four five"

# 7 tokens that count 8 under STRICT (two hyphenated compounds split, the
# URL counts 0) and 7 under LENIENT (PRD §2.9) — with a 7-word limit the
# same text is over under STRICT and within under LENIENT.
POLICY_SPLIT_TEXT = "My pro-tenant, anti-sprawl record: https://x.org/123 proves it."

DEFAULT_QUESTION = {"position_index": 1, "prompt_text": "Why are you running?"}
