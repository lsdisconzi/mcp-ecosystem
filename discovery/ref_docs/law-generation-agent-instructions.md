# Agent Instructions — Law File Generation & Correction

**Scope:** You generated these two files and must correct them:
- `data-law/new-generated/abear_code_of_conduct.md`
- `data-law/new-generated/abear_anti_corruption.md`

This document (a) tells you exactly what to fix, (b) defines the **exact expected
outcome** every law file must meet, and (c) gives a **self-check** you must pass
before you mark any file done. Apply these rules to every future law file too.

Read the companion reference first: `ref_docs/law-ingestion-guide.md` — it is the
canonical corpus spec. This file is the enforceable checklist on top of it.

---

## 0. Ground truth about ABEAR (context you must respect)

- ABEAR = Associação Brasileira das Empresas Aéreas (Brazilian airline trade
  association). Its instruments are **contractual/internal corporate policies,
  NOT federal statutory law**.
- Each ABEAR instrument is a **distinct framework code**. Never reuse a code
  across two different instruments.
  - `ABEAR_COC` → Código de Conduta (POL/COC)
  - `ABEAR_PAC` → Política Anticorrupção (POL/PAC)
  - `ABEAR_POL` → **already taken** by a DIFFERENT instrument: the POL/PMD
    "Política de Tratamento de Relatos / Medidas Disciplinares"
    (`data-law/BR/ABEAR_Code.md`). Do NOT use `ABEAR_POL` for the Código de
    Conduta or any other ABEAR instrument.
- These files are destined for **curated ingestion** (article-level, with ELI),
  like `BR/ABEAR_Code.md` which is already in Qdrant. So the `Notes` field must
  NOT say "reference-only / do not ingest" — that is contradictory and wrong.

---

## 1. Correction list — `abear_code_of_conduct.md`

The Código de Conduta is organized by **Sections, not numbered Articles**. Its
true structure (verify against the source) is:

| Real location | Heading in source | Your current (wrong) ELI |
|---|---|---|
| Seção A, item I | `### I. PREÂMBULO` | `BR.ABEAR_POL.SA.I.Art.1` |
| Seção A, item II | `### II. DOS PRINCÍPIOS FUNDAMENTAIS` | `BR.ABEAR_POL.SA.II.Art.1` |
| Seção A, III.1 | `#### III.1 Compromissos Gerais` | `BR.ABEAR_POL.SA.III.1.Art.1` |
| Seção A, III.2 | `#### III.2 Sustentabilidade e Responsabilidade Social` | `BR.ABEAR_POL.SA.III.2.Art.1` |
| Seção A, III.3 | `#### III.3 Declarações … Anticorrupção` | `BR.ABEAR_POL.SA.III.3.Art.1` |
| Seção A, III.4 | `#### III.4 Declarações … Agentes Públicos` | `BR.ABEAR_POL.SA.III.4.Art.1` |
| Seção B, I | `### B I – PRINCÍPIOS GERAIS` | `BR.ABEAR_POL.SB.I.Art.1` |
| … | … (B II … B IX) | `BR.ABEAR_POL.SB.II.Art.1` … `…SB.IX.Art.1` |

### Required corrections

1. **Framework code** must become `ABEAR_COC` everywhere (was `ABEAR_POL`).
2. **Remove the fabricated `.Art.1`.** This document has NO article numbers.
   Do not invent one. The ELI must encode the real location only:
   - `BR.ABEAR_COC.SA.I`   (Seção A, item I)
   - `BR.ABEAR_COC.SA.II`
   - `BR.ABEAR_COC.SA.III.1` … `BR.ABEAR_COC.SA.III.4`
   - `BR.ABEAR_COC.SB.I` … `BR.ABEAR_COC.SB.IX`
3. **Heading** must reflect the real section, not a fake `Art. 1`:
   - `### Seção A, I — Preâmbulo`
   - `### Seção A, II — Dos Princípios Fundamentais`
   - `### Seção A, III.1 — Compromissos Gerais`
   - `### Seção B, IV — Anticorrupção`
   - etc. (heading text may be human-readable; the **ELI is the machine key**).
4. **Metadata `Articles:`** must list exactly the ELI suffix tokens used, and
   must MATCH the ELI IDs in the body. (Currently lists `SA.I.1, SB.IX.1…`
   while bodies say `…SA.I.Art.1` — inconsistent.) Use the corrected forms,
   e.g. `SA.I, SA.II, SA.III.1, SA.III.2, SA.III.3, SA.III.4, SB.I … SB.IX`.
5. **`Sha256`** — provide the SHA-256 of the raw text/PDF you actually
   extracted from. If you cannot compute it, write `(computed on verified source
   — pending)` — never leave the field as just `not provided`.
6. **`Notes`** — remove the "reference-only / do not bulk ingest" wording.
   Replace with: `✅ verified — ABEAR Código de Conduta (POL/COC); corporate
   policy instrument (contractual, not statutory).` Keep `⏳ pending` only if
   you genuinely could not verify against the signed PDF.
7. Do not drop content: every Seção A/B body paragraph must remain under its
   real section.

---

## 2. Correction list — `abear_anti_corruption.md`

This file is **mostly correct** — the Política Anticorrupção really is numbered
`## 1. Objetivo` … `## 10. Anexos`, so `BR.ABEAR_PAC.Art.1` … `.Art.10` with
heading `### Art. N — …` is the right model. Fix only:

1. **`Sha256`** — same rule as above (compute it or mark `(computed on verified
   source — pending)`).
2. **`Notes`** — remove "reference-only / do not bulk ingest"; state
   `✅ verified — ABEAR Política Anticorrupção (POL/PAC); corporate policy
   instrument (contractual, not statutory).`
3. **Art. 7 vs Art. 9 both titled "Disposições Finais"** — verify against the
   source. If the source genuinely repeats the heading, differentiate them so a
   reader isn't confused (e.g. Art. 7 heading stays `Disposições Finais`; Art. 9
   → confirm it isn't a stray duplicate). Do not renumber; only fix the label if
   the source supports it.
4. Optional cleanup: `✓` glyphs and inline `#### 4.1)` sub-numbering are source
   artifacts — keep them only if they are in the source text; otherwise strip.

---

## 3. THE expected outcome — exact spec for EVERY law file

A conformant file MUST satisfy all of the following. Treat this as
non-negotiable.

### 3.1 One file = one instrument, in the right folder

| Jurisdiction | Folder | Language | JUR token |
|---|---|---|---|
| Brazil | `data-law/BR/` | pt | `BR` |
| Chile | `data-law/CL/` | es | `CL` |
| INT original | `data-law/INT/EN/` | en | `INT` |
| INT translation | `data-law/INT/BR/` | pt | `INT` |
| Corporate | `data-law/CORP/` | en | `CORP` |

Filenames: `<CODE>_<SHORTNAME>.md`, uppercase code prefix, e.g.
`R400_ANAC.md`, `L18916_CACH.md`, `ABEAR_CodigoConduta.md`.

### 3.2 ELI ID — derive from REAL structure, never invent

```
<JUR>.<FRAMEWORK>.<hierarchy>Art.<number>
```

- The `.Art.<n>` segment is **only** used when the instrument really numbers
  articles (statutes, ANAC resolutions, MC99, ICAO annexes …).
- Section-organized documents (e.g. codes of conduct) encode their real
  location (`SA.I`, `SB.IV`, `C2.S1`) and must NOT gain a fake `.Art.1`.
- One article = ONE ELI. Never emit two ELI forms for the same block.
- Preserve suffixes verbatim: `Art.133A`, `Art.3.1`, `Art.494 N 16`.

### 3.3 Framework codes are unique per instrument

Before assigning a framework token, check the corpus so you don't collide
(`grep` the existing `data-law/**` ELIs). `ABEAR_POL` is taken; use
`ABEAR_COC` / `ABEAR_PAC` for these instruments.

### 3.4 Required file skeleton (exact)

````markdown
# <Title> — <Human readable name>

## Metadata

- **Source:** <official source / document id>
- **Fetched:** <YYYY-MM-DD>
- **Sha256:** <hex or "(computed on verified source — pending)">
- **Articles:** <token list matching body ELIs>
- **Notes:** <✅ verified | ⏳ pending — one-line description; NO
  "reference-only/do-not-ingest" wording for files destined for ingestion>

---

## Articles

### <Heading matching real location>

**Theme:** <token>
**ELI ID:** `<JUR>.<FRAMEWORK>....>`
**Tags:** norm_type: <type> · scope: <scope> · sanctions: <s1, s2>   <- optional

<verbatim body>

---
````

### 3.5 Metadata ↔ body consistency (critical)

The **`Articles:`** list in Metadata MUST equal the set of ELI **location
tokens** used in the body, in document order. If they disagree, the file is
wrong. Example — code of conduct after fix:

```
- **Articles:** SA.I, SA.II, SA.III.1, SA.III.2, SA.III.3, SA.III.4, SB.I, SB.II, SB.III, SB.IV, SB.V, SB.VI, SB.VII, SB.VIII, SB.IX
```

and each body ELI must be one of those with the `BR.ABEAR_COC.` prefix.

### 3.6 Body text is verbatim

Never paraphrase, summarize, or fabricate. If you lack verified text for a
section, mark `⏳ pending` in Notes — never invent content.

---

## 4. Self-check (run BEFORE finishing any file)

For EACH file you produce or correct, verify:

- [ ] Folder matches jurisdiction; filename matches content.
- [ ] ELI present in every `###` block, exactly one per block, no duplicate forms.
- [ ] ELI derived from REAL structure — no invented `.Art.1` on section docs.
- [ ] Framework token does not collide with another instrument in the corpus.
- [ ] Metadata `Articles:` matches the body ELI location tokens exactly.
- [ ] `Sha256` and `Notes` filled; Notes has no self-contradictory
      "reference-only" wording when the file is article-level/for ingestion.
- [ ] Content is verbatim from the source.
- [ ] After saving, the registry parses it with **zero parse surprises**:
      run
      ```
      node case-server/pipeline/build_law_registry.js
      ```
      then open `data-law/_mapping/LAW_REGISTRY.md` and confirm your file shows
      `Local` = expected article count and no `no ELI headers` note. (Until the
      file is ingested, `In Qdrant = 0` and `Missing = Local` is expected and OK.)

## 5. Order of work

1. Correct `abear_code_of_conduct.md` per §1.
2. Correct `abear_anti_corruption.md` per §2.
3. Re-run the registry self-check (§4).
4. Use the corrected files as the pattern for every future law file.
