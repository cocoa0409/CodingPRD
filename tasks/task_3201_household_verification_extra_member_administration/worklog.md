# Worklog — task_3201_household_verification_extra_member_administration

## Step 1: Create Task Directory — 2026-09-30T09:53:00.000Z

Verified pre-allocated task directory `./tasks/task_3201_household_verification_extra_member_administration/` with `workspace/` inside exists (per command args; no index computed).

## Step 2: Generate Scaffold — 2026-09-30T10:22:00.000Z

All checks pass. Lint is clean, instance names are unique across both design files (46 total), the stub reference resolves, and all error grounds resolve. I hand-verified every pinned arithmetic literal against the scaffold formulas (799/500/374/574/948/130/270/599 fee-credit values, 0.5/0.25 churn rates, 14d/30d pass ends).

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3201_household_verification_extra_member_administration/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 plus preamble (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`, 9 rules × 2 = **18 instances**
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`, **28 instances** (27 full recipes + 1 `excluded_because` stub) across all 9 claim-extraction-guide sections

**Scaffold counts:** 12 entities, 8 state machines (Account cyclic + parallel `verification_posture` dimension; Household relocation cycle; Device trust cycle; ExtraMemberSlot OFFERED→ACTIVE→REVOKED→OFFERED cycle; VerificationChallenge PENDING→EXPIRED→PENDING reissue cycle; TravelPass; ProfileTransfer; EnforcementPolicy), 6 calculations, 18 ordered validations, 67 endpoints (incl. `/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default and `/_billing/simulate`), 35 error codes, 5 roles, 2 OCC concurrency rules.

**Beyond-expert difficulty mechanisms:**
- Dual-variant calcs on two domains: prospective vs mid-cycle-prorated slot pricing (799 vs 500 literals) and strict-vs-lenient household match confidence (50 vs 60 with pinned cycle-breaking evaluation order)
- Combinatorial modes (a) and (b): 3-input tiered fee (region base × tier multiplier + slot-index surcharge → 374/574) and per-day-round-then-multiply revocation credit (130, vs 133 for the forbidden order)
- Depth-3 cascade (suspend → device untrust → travel-pass revoke → CHURN_SIGNAL metric) and depth-2 transfer cascade (accept → member move → slot revoke with zero credit)
- Priority conflicts on distinct category pairs (state vs fiscal; safety vs referential), boundary checks on two metrics/endpoints (stream cap at ==, download allowance at zero-remaining), two overlap semantics (half-open adjacency on device passes vs closed 300s cooldown buffer on challenge reissue), and compensating invariants on money (billed−credit conserved by purchase + grace-revoke) and usage counters (download create/delete)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (220 calls scanned, 45 non-stub instances). No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-09-30T10:23:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T10:30:00.000Z

Done. Summary:

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3201_household_verification_extra_member_administration/workspace/PRD.md` — 317 lines.

**Section list**:
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 RBAC (all 5 roles with identity translations), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (+ validation-priority preamble), 2.4 Common Resource Properties (incl. the 3 light entities without `updated_at`/`version`), 2.5 Nested Resource Retrieval, 2.6 OCC (both rules with exact error ids/statuses), 2.7 Monetary Precision (round-half-up, pinned per-day rounding order, 4-decimal churn rates), 2.8 Logical Clock (2026-09-01T00:00:00Z default), 2.9 Lazy State Materialization, 2.10 Cascades, 2.11 Policy Regional Exclusivity
- §3 Business Logic (9 subsections): account lifecycle, household relocation, members/devices/confidence (strict vs lenient variants, weights 40/30/30/10/0, cap 50, threshold 70), challenges (900s/1800s expiry, 3/5 attempt caps, 300s cooldown, `000000` reserved), travel passes (14d/30d, half-open overlap, convert bypass), slot pricing (regional bases 799/299/499/349, tier multipliers 1.0/0.75, 200-cent index surcharge, both proration variants, 7-day full-credit window, pinned round-then-multiply), play-time entitlements (stream caps 1/2/4, resolution SD/HD/UHD, downloads 5/25/100), profile transfer (OCC, member move, zero-credit slot cascade), billing simulation/policies/churn metrics (gross vs net formulas)
- §4 Endpoint table: 46 rows, 4 columns
- §5 Error catalogue: 35 errors, 2 columns

**Audit results**:
- Contract 1 (Field-Name Coverage): 97 required identifiers (entity fields, endpoint inputs, OCC fields, computed-read outputs, envelope/pagination fields) — 97 present, 0 missing. All 56 enum values, all 35 error ids, all 5 role names present. PASS
- Contract 2 (Rule Coverage): all 18 validations expressed with priority ordering (validation → auth → existence → OCC → state → business stated in §2.3); both OCC rules name endpoint capability + occ field + error id + 412; all state-machine transitions and side-effect cascades (suspend/reactivate/cancel, relocate/dissolve, trust/untrust/remove, slot purchase/assign/revoke/reoffer/lapse, challenge submit/reissue/lockout, pass revoke/convert, transfer accept/cancel/expire, policy activate/retire) narrated; all 6 calculations expressed in precise prose with constants embedded (no pseudocode, no fuzzy words). PASS
- Contract 3 (§3 Path Purity): 492 backticked tokens scanned in §3, 0 path tokens, 0 bare HTTP-method tokens, 0 method+path combos. PASS

## Step 5: Generate Unit Tests — 2026-09-30T10:48:00.000Z

Generation complete. All artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_3201_household_verification_extra_member_administration/`.

## Stage 1 — `test_helpers/` (9 files)
- `types.py` — 12 entity TypedDicts + all status/role enums; append-only entities (PlaybackSession, Download, EnforcementMetric) omit `updated_at`/`version` per PRD §2.4.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (46 endpoints) under `/hv`.
- `api_errors.py` — full 36-entry `ApiErrorId` enum + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity field assertions + `assert_revenue_invariants` (net = billed − credit).
- `factories.py`, `constants.py` (fee tables, entitlement caps, confidence weights, challenge TTLs/caps), `test_users.py` (opaque-role constants + per-instance builders for the three entity-backed member roles), `fixtures.py` (composite setups: account+household+trusted-device, purchased/assigned slot, challenge issue/lockout/expiry, pending transfer, travel pass; all ownership-gated calls thread real `Member.id`s), `__init__.py` barrel.

## Stage 2 — `test_suite/` (9 test files, 63 tests)
- Queue A (Difficulty): **36 tests, all 18 instances ≥2 tests each** (zero shortfalls).
- Queue B (Corner): **27 tests, all 26 non-stub instances ≥1 test each** (zero shortfalls). The single `excluded_because` stub (`device_confidence_computed_read`) was verified against its difficulty cross-reference and not translated, per spec.

## Instances skipped
None. Every non-stub instance passed the PRD-first two-condition filter (PRD verbatim coverage + unique derivability, including PRD §2.3's explicit validation-ordering sentence which legitimizes the two priority-pair instances).

## Self-audit results
- **Tag audit (C4)**: 63/63 tests carry exactly one `Design:` tag; every tag resolves to a real instance; no unknown tags; no stub translated.
- **PRD citation sweep (C1–C3)**: 63/63 docstrings contain a quoted rule-bearing PRD sentence with an ≥8-word substring surviving a literal grep of `PRD.md`.
- **Hygiene**: no `pytest.mark.skip`/`skipif`/`xfail`; no mentions of "scaffold"/table references in generated code; `pyflakes` clean; `pytest --collect-only` collects 63 tests with zero import errors.

## Step 6: Generate Implementation — 2026-09-30T11:05:00.000Z

All cleaned up. Implementation complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3201_household_verification_extra_member_administration/workspace/implementation/`):
- `start.sh` — foreground launcher with guarded `pip install`, `exec python3 app.py`, executable
- `requirements.txt` — `flask>=2.0,<4.0`
- `app.py` — single-file Flask app (~1100 lines) with in-memory store, logical clock, envelope, auth, RBAC, all state machines, calculations, lazy materialization

**Endpoints implemented**: all 46 from §1.5 (clock set, billing simulate, 7 account ops, 5 household, 4 member, 8 device incl. confidence, 7 extra-member-slot, 5 verification-challenge, 5 travel-pass, 6 profile-transfer, 5 playback-session, 5 download, 5 enforcement-policy, 3 metric/churn).

**Key behaviors verified by smoke test**:
- Account create → OWNER member auto-created, `billing_anchor_day=1` (logical clock at 2026-09-01), envelope shape correct
- Device confidence `strict_pct=100` with full match; trust endpoint transitions UNTRUSTED→TRUSTED
- Slot purchase: STANDARD/NA on day_index=0 → `price_cents_snapshot=799`, full-cycle variant
- Slot assign creates EXTRA member; challenge wrong code → `ERR_CHALLENGE_CODE_MISMATCH` and attempts incremented; correct code → VERIFIED + posture restored
- Profile transfer accept → new account created, member moved with role OWNER, slot auto-REVOKED with `credit_cents=0`
- Billing `FAILED` suspends account with version increment
- Churn summary returns gross/net rates with `active_flag=0` after suspend
- Fresh-boot cleanliness: killed server, restarted, `GET /hv/accounts` returned `total_count: 0` (no carry-over state, no seeding)

## Step 7: Run Tests and Iterate — 2026-09-30T11:17:00.000Z

All 8 rounds pass 62/62 (one test deleted, 63 → 62). Clean sweep.

## Summary

- **Iterations run**: 2 (first sweep: 5 deterministic failures ×8 rounds; second sweep: 8/8 rounds clean, 62/62 each).

- **Tests deleted** (1):
  - `test_device_not_found_beats_suspended_state` (test_04_cascades.py) — mis-applied PRD §2.5 path-identifier ordering to a *body* field (`device_id` in the playback-start payload). PRD §3.7 explicitly names `ERR_DEVICE_NOT_TRUSTED` for a missing device on playback, and §2.3 puts account state gates (`ERR_ACCOUNT_SUSPENDED`) before §3 business rules, so the asserted `ERR_DEVICE_NOT_FOUND` is not uniquely derivable (error-precedence silence / rule mis-citation).

- **Fixes applied to `test_suite/`** (2):
  - `test_extra_member_fee_prospective_vs_prorated_anchor_day` (test_02) — setup violated PRD §3.6's slot cap (`STANDARD` allows 1 slot; test purchased 2). Switched the account to `PREMIUM` and corrected the expected prices per PRD's formula: 599 (`round_half_up(799*0.75)`) on anchor day; second slot full-cycle 799 (599+200 surcharge) prorated to 400 (`round_half_up(799*15/30)`); billed total 999.
  - `test_revoke_credit_per_day_rounding` (test_02) — fixture set the clock to 2026-09-16 *before* account creation, making `billing_anchor_day`=16 so the purchase landed on the anchor day (full price, not prorated). Now creates the account at the default clock (anchor day 1), advances to 2026-09-16 (index 15) for the prorated 400 purchase, and revokes at 2026-09-24 (index 23; 23−15=8 > 7 so the prorated branch applies): credit = `round_half_up(400/30)=13` × 7 days remaining = 91, net revenue 309.
  - `test_challenge_locked_safety_beats_member_referential` (test_05) — the submitter's headers belonged to a different account than the challenge, tripping §2.1 RBAC (`ERR_FORBIDDEN`) before the state gate. Fixed to send account A's owner headers (passing RBAC per §2.3 ordering) while keeping the body `member_id` as account B's owner, so the test exercises the intended `ERR_CHALLENGE_LOCKED` vs `ERR_MEMBER_NOT_IN_ACCOUNT` priority pair.

- **Fixes applied to `implementation/`** (1):
  - `app.py` — `new_common()` and `light_common()` minted ids as `uuid.uuid4().hex` (dash-less); PRD §2.4 requires "a server-minted UUID". Changed to `str(uuid.uuid4())` for all entity ids.

## Step 8: Finalize PRD — 2026-09-30T11:22:00.000Z

PRD_FINALIZED.md is written. Summary of the work:

## Line counts
- PRD.md: 316 lines; PRD_FINALIZED.md: 316 lines (0% line-count delta — three in-place sentence revisions within existing paragraphs; no sections added).

## Changes (one bullet per edit)
- **§2.4 (Common Resource Properties)** — revise — resource `id` pinned to canonical dashed UUID form (`str(uuid.uuid4())`), with an explicit carve-out that non-`id` server-minted fields such as `recommendation_seed` are opaque strings not bound to that format — `implementation/app.py:329` (`new_common`), `app.py:338` (`light_common`), `app.py:802/1038/1347` (`recommendation_seed` uses `uuid.uuid4().hex` and is not a resource id).
- **§3.7 (playback start)** — revise — pinned that `device_id` is a body-supplied identifier, so §2.5's left-to-right path-identifier ordering does not apply; the §3.1 account state gates (via the §2.3 pipeline) fire first (`ERR_ACCOUNT_SUSPENDED`/`ERR_ACCOUNT_CANCELLED`), then a `device_id` matching no device yields `ERR_DEVICE_NOT_FOUND` (404), while an existing device failing the trust/household gate yields `ERR_DEVICE_NOT_TRUSTED` (403) — `implementation/app.py:1800` (`account_gate` before device check), `app.py:1775-1787` (`check_playback_device`: missing → `ERR_DEVICE_NOT_FOUND`, foreign/untrusted → `ERR_DEVICE_NOT_TRUSTED`).
- **§3.7 (downloads)** — revise — mirrored the same body-`device_id` convention sentence for download creation, which shares `check_playback_device` — `implementation/app.py:1895` (calls the same helper after `account_gate` at `app.py:1892`).

## Step 7 items not requiring PRD edits (pure test/fixture bugs)
- `test_extra_member_fee_prospective_vs_prorated_anchor_day` — violated PRD §3.6's already-pinned slot cap (STANDARD=1) and tier multipliers; PRD already determines the behavior.
- `test_revoke_credit_per_day_rounding` — fixture clock-setup bug; PRD §3.6 already pins `purchased_day`, the 7-cycle-day window, and round-per-day-then-multiply.
- `test_challenge_locked_safety_beats_member_referential` — fixture bug (cross-account headers); the PRD's §2.1/§2.3 RBAC-before-state ordering and the impl (`app.py:1476` authorize → `1480` locked → `1490` referential) already agree, so the PRD's ordering was left as-is (widen/soften chosen over pinning a new cross-gate order).

## Per-edit pre-edit search log
1. **Edit §2.4 (id format)** — (a) subject: format of server-minted resource `id`s. (b) enumerated: `app.py:329` `new_common` (all primary resources), `app.py:338` `light_common` (PlaybackSession/Download/EnforcementMetric), `app.py:131` (`req_` id, not a resource), `app.py:802/1038/1347` (`recommendation_seed`, hex form). (c) adjustment: added the parenthetical excluding non-`id` fields so the dashed-form claim doesn't falsify `recommendation_seed`'s hex format.
2. **Edit §3.7 (playback device reference)** — (a) subject: resolution/error for body-supplied `device_id` vs. account gates. (b) enumerated: `app.py:1791-1812` (start_session pipeline), `app.py:1772-1788` (`check_playback_device`), `app.py:1883-1895` (downloads reuse), `app.py:1469-1491` (challenge submit, analogous body-`member_id` → 404 pattern), `app.py:638-644` (`account_gate`). (c) adjustment: worded as "account-level state gates of §3.1" rather than naming only suspension, since `account_gate` covers CANCELLED too; explicitly said §2.5 "does not govern" rather than redefining §2.5 itself (untouched).
3. **Edit §3.7 (downloads convention)** — (a) subject: same device-reference convention at download creation. (b) enumerated: `app.py:1883-1916` (create_download: `req_str` device_id → `account_gate` → `check_playback_device` → allowance check). (c) no wording adjustment needed; "under identical conditions" retained for the trust gate and the 404 case pinned to mirror the playback sentence.

## Step 9: Complete PRD — 2026-09-30T11:37:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_3201_household_verification_extra_member_administration/workspace/PRD_COMPLETED.md`.

**Source:** `PRD_FINALIZED.md` (316 lines / 49,851 chars) → `PRD_COMPLETED.md` (318 lines / 54,901 chars); +2 lines (one new filter-paragraph splits the §4 preamble; the rest are in-paragraph edits), +5,050 chars.

**Counts:** 26 ambiguity-pins (inserts), 0 mismatch-revisions — every PRD claim that was pinned matched the implementation; all edits pinned previously silent behavior. All edits were in-paragraph except the one added filter paragraph in §4 (no new sections added).

**Changes (one per bullet):**

- §2.1 — insert — ambiguity — member role-mismatch between `X-User-Role` and resolved member yields `ERR_UNAUTHENTICATED` (401) — app.py:245-246
- §2.3 — insert — ambiguity — list sort tie-broken by `id` ascending; `has_more = (offset + returned) < total_count` — app.py:148, 211
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — app.py:329
- §2.8 — insert — ambiguity — all resource timestamps are stamped from the logical clock — app.py:333, 690, 1162, etc.
- §2.9 — revise — ambiguity — lazy expiry boundaries are inclusive ("at or after" `expires_at`/`ends_at`) — app.py:567, 573, 584
- §2.10 — insert — ambiguity — household dissolution also ends each removed device's ACTIVE playback sessions — app.py:1006-1009
- §3.1 — insert — ambiguity — suspended gate also covers member removal, travel-pass grant/convert, challenge reissue; plan PATCH on CANCELLED hits ERR_ACCOUNT_CANCELLED before OCC; suspend-from-non-ACTIVE and reactivate-from-non-SUSPENDED yield ERR_INVALID_STATE — app.py:850-853, 865-868, 908-909, 1075, 1518, 1547, 1620
- §3.1 — insert — ambiguity — issuing a challenge while posture is CHALLENGE_PENDING/LOCKED is allowed and leaves posture unchanged — app.py:1439-1441
- §3.1 — insert — ambiguity — net revenue is derived on read as billed minus credit — app.py:353
- §3.1 — insert — ambiguity — plan change allowed on SUSPENDED accounts (no ACTIVE gate) — app.py:908-914
- §3.3 — insert — ambiguity — member `current_streams`/`downloads_used_this_month` are derived on read, not stored — app.py:381-395
- §3.3 — insert — ambiguity — removing owner or non-ACTIVE member → ERR_INVALID_STATE (409) — app.py:1076-1079
- §3.3 — insert — ambiguity — registering a device into a DISSOLVED household → ERR_INVALID_STATE — app.py:1103-1104
- §3.3 — insert — ambiguity — trust gate: device not UNTRUSTED → ERR_INVALID_STATE — app.py:1179-1180
- §3.3 — insert — ambiguity — untrust requires TRUSTED and device removal from other trust statuses → ERR_INVALID_STATE — app.py:1199-1200, 1214-1215
- §3.4 — insert — ambiguity — challenge submit: unknown member_id → ERR_MEMBER_NOT_FOUND; submit against VERIFIED challenge → ERR_INVALID_STATE — app.py:1478-1483
- §3.4 — insert — ambiguity — reissue from non-EXPIRED status → ERR_INVALID_STATE — app.py:1520-1521
- §3.5 — insert — ambiguity — revoke of non-ACTIVE pass → ERR_INVALID_STATE; convert of non-ACTIVE pass → ERR_INVALID_STATE; fingerprint mismatch on convert → ERR_DEVICE_NOT_TRUSTED; convert on already-TRUSTED device leaves count unchanged — app.py:1606-1607, 1622-1630
- §3.6 — insert — ambiguity — purchase: unknown payer_member_id → ERR_MEMBER_NOT_FOUND; non-OWNER payer → ERR_VALIDATION — app.py:1244-1246, 1253-1254
- §3.6 — insert — ambiguity — cycle day index formula pinned: (day-of-month − billing_anchor_day) mod 30 — app.py:647-651
- §3.6 — insert — ambiguity — slot assign from non-OFFERED → ERR_INVALID_STATE — app.py:1334-1335
- §3.6 — insert — ambiguity — slot revoke from non-ACTIVE → ERR_INVALID_STATE — app.py:1364-1365
- §3.6 — insert — ambiguity — slot reoffer from non-REVOKED → ERR_INVALID_STATE — app.py:1394-1395
- §3.7 — insert — ambiguity — session start requires member ACTIVE (else ERR_INVALID_STATE); device gate fails for DISSOLVED/other-account households; session end of non-ACTIVE → ERR_INVALID_STATE — app.py:1801-1802, 1779-1780, 1871-1872
- §3.7 — insert — ambiguity — deleting non-ACTIVE download → ERR_INVALID_STATE — app.py:1974-1975
- §3.8 — insert — ambiguity — transfer initiation: unknown member_id → ERR_MEMBER_NOT_FOUND; member not in source account → ERR_MEMBER_NOT_IN_ACCOUNT — app.py:1648-1652
- §3.8 — insert — ambiguity — cancelling a non-AWAITING_ACCEPTANCE transfer → ERR_INVALID_STATE — app.py:1760-1761
- §3.8 — insert — ambiguity — acceptance points new account's `owner_member_id` at the transferred member and transitions the auto-created owner to REMOVED (retained on the new account) — app.py:1732-1741
- §3.9 — insert — ambiguity — billing simulate SUCCEEDED, or FAILED on non-ACTIVE account, is a no-op returning the account — app.py:765-772
- §3.9 — insert — ambiguity — activating non-DRAFT policy / retiring non-ACTIVE policy → ERR_INVALID_STATE — app.py:2037-2038, 2053-2054
- §3.9 — insert — ambiguity — churn rates report 0.0 when the denominator is zero — app.py:2111-2112
- §4 preamble — insert (one new paragraph) — ambiguity — documented exact-match query filters per list endpoint (region_code/plan_tier/member_role/status/trust_status/member_id/payer_member_id/billing_month/metric_type) — app.py:835-840, 1059-1064, 1135-1137, 1297-1299, 1310-1318, 1462-1464, 1588-1590, 1687-1689, 1702-1707, 1843-1845, 1858-1860, 1937-1942, 1957-1959, 2022-2027, 2095-2097
