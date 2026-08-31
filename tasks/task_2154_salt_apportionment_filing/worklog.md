# Worklog — task_2154_salt_apportionment_filing

Scenario: 2154. State & Local Tax Apportionment Filing (multistate SALT team): nexus determination by activity & economic thresholds, apportionment factor computation (sales/property/payroll) & sourcing rules, combined vs separate filing election, state modifications & credits, estimated payment & extension by state, notice/assessment response & appeal, voluntary disclosure agreement for past exposure, filing calendar & registration maintenance

## Step 1: Create task directory — 2026-08-25T12:51:55.929717508Z

Created ./tasks/task_2154_salt_apportionment_filing/workspace (index 2154, next after existing max 2153).

## Step 3: Copy shared files — 2026-08-25T12:51:55.943943969Z

Copied ./INSTRUCTION.md → tasks/task_2154_salt_apportionment_filing/workspace/INSTRUCTION.md (done early; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-25T13:35:12.968733350Z

Done. All three scaffold artifacts are generated and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2154_salt_apportionment_filing/`
- `SCAFFOLD.yaml` (141 KB) — §1.0–§1.7 + preamble; no design keys inside
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (122 KB) — single key `scaffold_difficulty_design`, 20 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` (235 KB) — single key `scaffold_corner_design`, 71 instances (60 with recipes, 11 `excluded_because` stubs)

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2154_salt_apportionment_filing/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2154_salt_apportionment_filing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2154_salt_apportionment_filing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1015

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design shape (expert_plus)

`api_prefix: /salt`, flat topology, parallel state-machine shape, `segregation_of_duties` role model, layers: dual-variant calc / cascading side effects / rate-threshold triggers / OCC.

13 entities · 62 endpoints · 11 calculations · 41 ordered validations · 50 errors · 10 state machines · 2 OCC rules · 4 roles.

**Where the difficulty lives:**
- **Joyce vs Finnigan** apportionment on the same `StateFiling` (0.200000 vs 0.245000) — sourcing cascade with market-based vs cost-of-performance services, throwback/throwout, 8× rent capitalization, zero-denominator factor exclusion with weight renormalization (0.183333).
- **Pinned rounding orders**: per-line modification rounding (676.57, not 676.56); ratio→6dp→weight→sum→6dp; two-step income→tax rounding; notice penalty-cap-then-interest-on-tax+penalty (526.44, not 501.37).
- **Four-link cascades** from two different triggers: compute-factors (apportionment → liability → credit waterfall → balance/payment_status) and evaluate-nexus (nexus → obligation counter → group posture → demotion of APPROVED filings).
- **Parallel axes** on `StateFiling` (preparation × payment) and `StateRegistration` (nexus × registration); cyclic `Notice` (respond ⇄ info-requested) with an appeal fork; cyclic `FilingElection` (revoke ⇄ reinstate).
- **Two interval semantics**: closed integer-year election intervals (adjacency allowed) on `StateRegistration` vs half-open datetime VDA windows with a symmetric 24-month cooling buffer on `LegalEntity`.
- **Three priority-conflict pairs** (state↔fiscal, referential↔temporal, safety↔constraint) and time-window rules driven by a logical clock defaulting to `2026-08-01T00:00:00Z`.

Every formula-derived assert literal was computed with a Decimal/ROUND_HALF_UP script before being written in. All `grounds:` refs resolve, all 91 instance names are unique, stub targets exist, and no forbidden concurrency vocabulary appears. No sibling task directory was read.

## Step 4: Generate PRD — 2026-08-25T13:45:26.744997122Z

PRD generated at `workspace/PRD.md` (476 lines, ~100 KB). Written incrementally in six appends; the file is verified complete end-to-end (§1 → §5, ending on the last error-catalogue row, no truncation, no audit footer).

**Structure** (domain-derived, not copied from the example):
- §1 Introduction — 3 paragraphs + mount note
- §2 — 11 subsections: Practice Roles and Caller Identity / API Response Structure (verbatim) / Pagination / Common Resource Properties / The Logical Compliance Clock / Monetary Precision, Factor Precision and Rounding Order / Path Resolution and Referential Integrity / Optimistic Concurrency on Parent Revisions / The Obligation Counter and Group Compliance Posture / Cascade Discipline / Order of Rejection
- §3 — 9 subsections organized as a compliance-year timeline (footprint → nexus → elections → factors → liability chain → cash & extensions → review/transmission → correspondence → voluntary disclosure)
- §4 — 62 endpoints, 4 columns; §5 — 50 errors, 2 columns

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 143 unique required, 143 present, 0 missing (161 field entries across 13 entities)
- endpoints[].input/request_body: 98 required, 98 present, 0 missing (incl. both occ_field names)
- endpoints[].query_params: 10 required (limit, offset, registration_id, legal_entity_id,
  tax_year, election_id, primary_legal_entity_id, preparation_status, applied_filing_id, status),
  10 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 41 checked, 41 expressed in prose (§2.11 renders the full 41-band
  ladder with error ids; the four documented dual-failure pairings 7>39, 15>29, 23>34, 8>40 are
  called out explicitly), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint framed as capability,
  expected_filing_version / expected_registration_version named non-optional, ERR_STALE_FILING_VERSION
  412 and ERR_STALE_REGISTRATION_VERSION 412 named, plus the "no other endpoint takes a version
  field" closure), 0 missing
- state_machines[].transitions: 57 checked, 57 fully expressed (all 10 machines incl. the two
  StateRegistration axes, both StateFiling axes, the ELECTED→REVOKED→ELECTED cycle, the
  RESPONDED→INFO_REQUESTED→RESPONDED cycle, the APPEAL_FILED fork, and the CreditClaim
  amend-reversal edges), 0 missing
- calculations[]: 11 checked, 11 fully expressed in precise prose — no operator syntax, no fuzzy
  words (grep-verified), all three pinned rounding orders stated (line-then-sum, income-then-rate,
  ratio-then-weight-then-sum), all constants embedded in business context (rent capitalized at
  8x, 90% prepayment, 10% penalty capped at 2,500.00, 6%/365 interest, 90-day appeal window,
  45-day response window, 7-year full exposure, 25% waiver, 24-month cooling/shield,
  April/June/September/December 15th installments), 0 missing
- validations[] conditions: 41 checked, 41 matchable to error_id in §2 or §3 narrative, 0 missing
- endpoints[].side_effects / applies_to: 38 endpoints with side effects checked, 38 expressed
  (incl. the 4-link evaluate-nexus cascade, the 4-link compute-factors cascade, the 3-link
  appeal-decision cascade, the 3-link VDA-execute cascade), 0 missing
- entities[].fields[] structured content: 161 checked, 161 reconstructible from prose (types,
  defaults, initial values, and the ActivityRecord common_fields:false exception stated
  explicitly), 0 missing
- sibling-branch symmetry: 7 groups checked (JOYCE/FINNIGAN, GRANTED/DENIED extension,
  SUSTAINED/DENIED appeal, LOOKBACK_LIMITED/FULL_EXPOSURE, the three safe-harbor bases,
  THROWBACK/THROWOUT/NONE, the three factor_formula weightings), 7 with equal prose density,
  0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 912
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- raw "/salt" occurrences in §3: 0
Status: PASS
```

Also verified: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; all 50 `errors[].id`, all state enum values and all enum-type field values appear verbatim in backticks; no fuzzy/approximating words anywhere in the file.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

Orchestrator verification: 475 lines / 100803 bytes; §1–§5 all present; 62 endpoint rows; 50 error rows; file ends cleanly on last catalogue row.

## Step 6: Generate implementation — 2026-08-25T14:08:54.527770169Z

The implementation is complete and verified.

## What was built

`workspace/implementation/` — Python + Flask, 15 modules, in-memory store only, no seeded data:

- `start.sh` (guarded pip install, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000), `requirements.txt`, `app.py`
- `store.py` (empty-on-boot store + logical clock defaulting to `2026-08-01T00:00:00Z`), `errors.py` (all 50 error IDs → HTTP), `util.py` (Decimal money/6-dp factor helpers, ISO-8601 3-digit formatting, payload validators), `web.py` (envelope, auth/RBAC, pagination, version bumping), `models.py` (field lists + per-entity 404 lookups), `calc.py` (all 11 calculations + cascades)
- `routes_core.py`, `routes_reg.py`, `routes_filing.py`, `routes_money.py`, `routes_notice.py`, `routes_vda.py`

All **62 endpoints** are registered and diff-clean against the PRD §4 table (verified programmatically: 0 missing, 0 extra). 13 entities, 10 state machines, both OCC rules, and the 41-band rejection ladder are implemented in strict priority order.

## Verification

~120 assertions across four end-to-end suites, all passing against a freshly booted server: JOYCE/FINNIGAN doctrine split, pinned rounding orders (ratio→weight→sum; line-then-sum; STI-then-rate), factor exclusion + weight renormalization, throwback/throwout/nowhere-pool, credit waterfall with refundable/carryforward/expiry and amend reversal, safe-harbor variants (100/110/CURRENT_90), notice penalty cap → interest → total, VDA both variants + cooling-window overlap, the nexus→obligation→posture→APPROVED-demotion cascade, DELINQUENT derivation, OCC 412s, SoD 403, and the four dual-failure precedence cases named in PRD §2.11. Fresh boot is <2 s with an empty store.

## Two judgment calls worth flagging

1. **`submit-review` accepts `TaxManager`** in addition to `StateAnalyst`/`Controller`. The PRD §4 table omits TaxManager there (the only endpoint where it does), but §2.1 states the hierarchical override unconditionally: "wherever a `StateAnalyst` or a `Controller` may act, a `TaxManager` may act too." PRD prose won, per the skill's precedence rule.
2. **Two preconditions carry no error ID in the catalogue**, so I mapped both to `ERR_INVALID_FILING_STATE` (409) and placed them *after* every declared band for their endpoint: apply-to-a-`DRAFT`-return (checked after the registration/tax-year mismatch bands, so a mismatch test on a draft return still yields its own code) and appeal-on-a-never-transmitted-return (checked after the appeal-deadline band, matching the order both PRD §3.8 and the scaffold state machine list them in). Withdrawing a registration with in-flight returns uses the same code.

`created_at`/`updated_at` come from wall-clock UTC (3 fractional digits); every spec-named stamp (`registered_on_date`, `filed_on_date`, `executed_on_date`, `requested_on_date`, deadline resets, `shield_expires_at`) reads the logical clock. No file under `test_helpers/` or `test_suite/`, nor either `*_DESIGN.yaml`, was opened.

## Step 5: Generate unit tests — 2026-08-25T14:14:21.249854784Z

Test infrastructure and suite are complete for `task_2154_salt_apportionment_filing`.

## What was generated

**`test_helpers/`** (9 files, ~2,030 lines)
- `types.py` — 12 entity TypedDicts + 20 status enums. `ActivityRecord` correctly omits `updated_at`/`version` (PRD §2.4's single `common_fields: false` entity).
- `api_client.py` — all **62 endpoints**, one method each.
- `api_errors.py` — all **50 error ids** + HTTP status map, registered with the framework.
- `assertions.py` — per-entity assertions, `assert_money`/`assert_ratio` (2dp / 6dp), `assert_credit_pool_conserved`, `assert_obligation_counter_matches`, `assert_balance_due_identity`, `factor_by_type`.
- `factories.py`, `constants.py`, `test_users.py` (all four roles are `identity: opaque`, so shared constants plus per-operator builders for the segregation-of-duties path), `fixtures.py` — a 5-tier composite chain (`setup_state_profile` → `setup_draft_filing` → `setup_computed_filing` → `setup_filing_with_credits` → `setup_locked_filing` → `…in_review` → `…approved` → `…filed` → `…with_notice` / `…notice_under_appeal` / `…with_applied_payment`), which collapses the 25-call "Meridian" preamble that both design indices repeat.

**`test_suite/`** — `conftest.py` + 9 domain-named files, **100 tests**, all collecting cleanly.

## Coverage against the design-index contract

- 20/20 difficulty instances × **2 tests each** = 40 tests.
- 60/60 non-stub corner instances × 1 test = 60 tests.
- All 11 `excluded_because:` stubs verified to resolve to a real difficulty instance; none translated.
- Every docstring ends with exactly one `Design: Difficulty/…` or `Design: Corner/…` line; zero untagged, dual-tagged or unknown tags (verified by script).
- Every PRD citation survives a normalized literal match against `PRD.md` (verified by script); no `skip`/`skipif`/`xfail`; no scaffold references leak into comments or docstrings.

## Notes worth relaying

- **No instances were skipped.** This PRD is unusually complete — §2.11 states the four dual-failure precedences verbatim ("fails at band 7 … not at band 39", etc.), so all three `priority_pair_validation_conflict` instances and the PL 86-272-over-registration-complete corner case passed the two-reader filter without weakening.
- **Two assertions were dropped as PRD-silent**, keeping the instances covered by their remaining assertions: the "API exposes no PUT/PATCH/DELETE route for activity records" claim (PRD declares no such route, so 404-vs-405 is open), and "updated_at advanced on every mutation" in the version-increment test (the logical clock is frozen in that scenario, so `updated_at` cannot legitimately change).
- One design-index bug found and worked around: corner instance `no_activity_records_for_filing_year_returns_error` lives under `section: validations`, not `calculations` — the tag was corrected to match the yaml.
- All pinned arithmetic in the indices was re-derived independently and checks out (JOYCE 0.200000 / FINNIGAN 0.245000, modification_total 676.57, renormalized 0.183333, throwout 0.186856, notice interest 526.44 / 325.89, VDA 90000.00 + 22500.00 waived).

Verification commands used: `pytest --collect-only` (100 collected), `pyflakes` (clean apart from intentional barrel re-exports), plus two purpose-written scripts for the citation pass and the coverage audit.

## Step 7: Test and iterate — 2026-08-25T14:18:30.229767428Z

Clean on the first sweep — no changes were required.

## Summary

**Iterations run: 1** (one full 8-round parallel stability sweep).

**Result: all 8 concurrent rounds passed 100/100.**

| Round | passed/total | failed | errors | skipped | duration |
|---|---|---|---|---|---|
| 1–8 | 100/100 | 0 | 0 | 0 | ~128 s each |

Union of failing tests across all 8 rounds: **empty**. No flakiness surfaced — the 8 rounds ran in lockstep with byte-identical outcomes, so no timing-sensitive bug (concurrency race, fixture ordering, port collision) escaped as a lucky pass.

**Tests deleted:** none. No test entered the diagnostic protocol, so no STEP 1a (PRD-silence) or STEP 1b (unique-derivability collapse) deletion was triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Verification notes

- `skipped: 0` and `errors: 0` in every round — the green result is not a collection failure or a masked skip. Confirmed independently: `grep -rn "skip\|xfail"` over `test_suite/` and `test_helpers/` returns nothing, so no `pytest.mark.skip` / `xfail` is suppressing anything.
- All 100 tests collected and executed under `--isolation per-test-server`, i.e. a fresh `start.sh` boot per test, so no test is passing on state leaked from a prior test.
- Storage is in-memory only (`workspace/implementation/store.py` — empty-on-boot dicts plus a logical clock defaulting to `2026-08-01T00:00:00Z`); no SQLite file, JSON dump, or `/tmp` cache exists in the implementation tree, and nothing is seeded at startup.

### Task state

The pipeline artifacts (`workspace/PRD.md`, `test_suite/` + `test_helpers/`, `workspace/implementation/`) are mutually consistent as generated. Two judgment calls the implementation step recorded in `worklog.md` both survive the sweep and both trace to PRD prose rather than scaffold: `submit-review` accepting `TaxManager` (PRD §2.1's unconditional hierarchical override), and the two catalogue-less preconditions mapped to `ERR_INVALID_FILING_STATE` and ordered *after* every declared band for their endpoint.

Result files are at `workspace/implementation/results.{1..8}.json`.

### Orchestrator independent verification

- Re-read all 8 `results.*.json`: each `passed=100 total=100 failed=0 skipped=0 errors=0`.
- Leak probe over `implementation/*.py` for design-index-only literals (`meridian`, `0.245000`, `0.183333`, `676.57`, `526.44`, `0.186856`): **0 hits** — the green first sweep is not an impl→design-index leak.
- Seeded-data probe (`sqlite`, `json.dump`, `/tmp/`, `seed`): only a `store.py` docstring stating nothing is ever seeded.

## Step 8: Finalize PRD — SKIPPED (2026-08-25T14:18:30.229767428Z)

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-25T14:29:21.733953607Z

`workspace/PRD_COMPLETED.md` is written.

**Counts:** PRD.md 475 lines / 100,803 chars → PRD_COMPLETED.md 475 lines / 107,536 chars (+6,733 chars; no lines added or removed — every change is an in-paragraph insert or revision). 28 changes across 26 lines: **21 ambiguity-pins, 7 mismatch-revisions**. Structure verified: §1–§5 all present, 62 endpoint rows, 50 error rows, clean ending.

**Changes**

- §2.1 — insert — ambiguity — an empty `X-User-ID`/`X-User-Role` is rejected as `ERR_UNAUTHENTICATED`, not only an absent one — `web.py:102`
- §2.4 — revise — **mismatch** — `created_at`/`updated_at` are stamped from the server's real-time UTC clock, not the logical clock — `web.py:30,69,199`, `util.py:49`
- §2.10 — insert — ambiguity — a link that recomputes a resource to values it already held does not re-version it; a resource touched by several links advances `version` by 1 in total — `web.py:72-89`, `calc.py:249-260,430-439`
- §2.11 band 7 — revise — **mismatch** — the target-return status check runs late on four operations (apply after 13/24/25, unapply after 13, appeal after 9/37, withdrawal after 14) — `routes_money.py:112-123,142-149`, `routes_notice.py:116-126`, `routes_reg.py:206-209`
- §2.11 band 14 — revise — **mismatch** — the withdrawn-registration guard fires only on registration-addressed writes — `routes_reg.py:25-29` + call sites
- §3.1 — insert — ambiguity — the four threshold/tax fields may not be negative — `routes_reg.py:46-59`
- §3.1 — insert — ambiguity — a PATCH advances `version` even when it names no recognized field — `routes_reg.py:157-159`
- §3.2 — insert — ambiguity — complete-registration has no source-state precondition; counter/posture move only from `REGISTRATION_REQUIRED` — `routes_reg.py:180-195`
- §3.2 — insert — ambiguity — the in-flight-return refusal on withdrawal carries `ERR_INVALID_FILING_STATE` — `routes_reg.py:206-209`
- §3.3 — revise — **mismatch** — an `EXPIRED` election still occupies its full interval; only `REVOKED` contracts — `routes_reg.py:316-331`
- §3.4 — insert — ambiguity — `federal_taxable_income` may be negative — `routes_filing.py:53`
- §3.4 — insert — ambiguity — factor-row numerator/denominator/throwback/throwout stored at 2 dp while `ratio` divides unrounded values; rows overwritten in place; fixed order SALES/PROPERTY/PAYROLL — `calc.py:397,410-433`
- §3.5 — insert — ambiguity — non-refundable `applied_amount` floored at zero — `calc.py:227-230`
- §3.5 — insert — ambiguity — claim state check follows the concurrency guard; 201 shows post-waterfall status while `version` stays 1 — `routes_filing.py:362-389`
- §3.6 — insert — **mismatch** — the DRAFT refusal on apply is `ERR_INVALID_FILING_STATE`, evaluated last of four checks — `routes_money.py:112-123`
- §3.6 — insert — ambiguity — the detach refusal on `REFUND_CLAIMED` is `ERR_INVALID_FILING_STATE` — `routes_money.py:142-149`
- §3.6 — insert — ambiguity — `state_confirmation` recorded on both GRANTED and DENIED branches — `routes_money.py:221`
- §3.7 — insert — ambiguity — replacement `federal_taxable_income` on amend stored without re-deriving downstream figures — `routes_filing.py:255-262`
- §3.7 — insert — ambiguity — claim-refund leaves `estimated_credits_applied`, `balance_due`, `unapplied_payment_balance` untouched — `routes_filing.py:285-296`
- §3.8 — insert — **mismatch** — notice creation enforces no `preparation_status` precondition; `assessed_tax`/`response_due_days` non-negative — `routes_notice.py:26-56`
- §3.8 — insert — ambiguity — omitted `contested_amount` leaves the prior figure; supplied values rounded to 2 dp — `routes_notice.py:78,88-89`
- §3.8 — insert — **mismatch** — the untransmitted-return refusal on appeal is `ERR_INVALID_FILING_STATE`, after the appeal-window check — `routes_notice.py:116-126`
- §3.8 — revise — ambiguity — DENIED discards a supplied `sustained_amount`; SUSTAINED cap breach is `ERR_INVALID_REQUEST` after the notice source-state check — `routes_notice.py:139-148`
- §3.9 — insert — ambiguity — omitted `negotiated_tax` written into the field; omitted `negotiated_interest` recorded as 0.00; neither may be negative — `routes_vda.py:300-318`
- §3.9 — revise — **mismatch** — `nexus_status` set to `VOLUNTARY` unconditionally — `routes_vda.py:328`
- §3.9 — insert — ambiguity — counter/posture links fire only when the registration axis moved from `REGISTRATION_REQUIRED` — `routes_vda.py:329-333`
- §4 — revise — **mismatch** — `POST /salt/filings/{id}/submit-review` also lists TaxManager — `routes_filing.py:173`

**Not changed** (impl already matches PRD uniquely): all 11 calculation formulas, the nexus four-rung ladder, the posture three-rung ladder and its APPROVED→IN_REVIEW demotion, both OCC guards, all 10 state machines' legal edges, the payment-status ladder, pagination bounds and filters, and the four §2.11 ordering examples.

### Orchestrator independent verification

- `PRD_COMPLETED.md`: 475 lines / 107,536 bytes, §1–§5 present, 62 endpoint rows, 50 error rows, clean ending.
- Withhold-constraint tool_use audit over subagent transcripts (parsing `tool_use` inputs only, per the transcript-audit method): Step 4 PRD-gen 0 hits on `DESIGN`; Step 6 impl-gen 0 hits on `DESIGN`/`test_suite`/`test_helpers`; Step 9 0 hits on `SCAFFOLD`/`worklog`. All withholds held.
- Independent orchestrator re-run of the sweep (2 further concurrent rounds, per-test-server): 100/100 both, 0 failed, 0 skipped. Combined with the zero tool-call hits, the green first sweep is recorded as genuine, not a design-index leak.
