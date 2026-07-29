# Court Document Extraction Schemas

Based on analysis of 4 sample documents (TJSP, TJMS, TJCE, TJRS) + CAPTCHA-blocked courts (TJAC, TJAL, TJAM).

Generated: 2026-05-27

---

## Common Fields (all courts)

These fields should be extracted from every court document:

| Field | Description | Priority |
|---|---|---|
| `tribunal` | Court abbreviation (TJSP, TJMS, etc.) | CRITICAL |
| `numero_processo` | Case number (CNJ format or local) | CRITICAL |
| `classe` | Case type (Apelação Criminal, Habeas Corpus, etc.) | CRITICAL |
| `relator` | Reporting judge name | CRITICAL |
| `orgao_julgador` | Judging body (Câmara, Turma, etc.) | HIGH |
| `comarca` | Judicial district of origin | HIGH |
| `data_julgamento` | Judgment date | HIGH |
| `data_publicacao` | Publication date | MEDIUM |
| `ementa` | Case summary / syllabus | CRITICAL |
| `partes` | List of parties (appellants, appellees) | HIGH |
| `advogados` | Lawyers with OAB numbers | MEDIUM |
| `decisao` | Decision text (provimento, improvimento, etc.) | CRITICAL |
| `outcome` | Normalized outcome enum | CRITICAL |
| `votacao` | Voting breakdown (unanimous, majority, etc.) | MEDIUM |
| `legislacao_citada` | Cited legislation references | MEDIUM |
| `jurisprudencia_citada` | Cited precedents/case law | MEDIUM |
| `assuntos` | Subject matter / legal topics | HIGH |
| `texto_inteiro` | Full text of the decision | CRITICAL |

---

## TJSP — Tribunal de Justiça de São Paulo

**Sample**: 1000137-61.2021.8.26.0411 (348,871 chars)

### Document Structure
```
TRIBUNAL DE JUSTIÇA / PODER JUDICIÁRIO / São Paulo
Registro: 2026.XXXXXXXXX
ACÓRDÃO
[decision summary paragraph with parties]
ACORDAM, em [Câmara] (...) "Deram provimento/negaram..."
O julgamento teve a participação dos Exmos. [judges]
São Paulo, [date]
[RELATOR]
---
[repeated header block]
Voto nº XXXXX
[Câmara]
[case number + parties + comarca]
[EMENTA - in all caps block]
I. CASO EM EXAME
  1.1. [detailed case description]
II. QUESTÃO EM DISCUSSÃO
  (i) [legal question 1]
  (ii) [legal question 2]
III. RAZÕES DE DECIDIR
  [numbered paragraphs]
[DISPOSITIVO - final ruling with numbered items]
[RELATOR signature]
```

### Key Extraction Patterns
- **Processo**: Line with `Apelação Criminal nº XXXX` or similar
- **Registro**: `Registro: (\d{4}\.\d+)` 
- **Ementa**: All-caps text block between header and `I. CASO EM EXAME`
- **Classe**: `Apelação Criminal`, `Habeas Corpus`, `Agravo`, etc.
- **Outcome markers**: `deram provimento`, `negaram provimento`, `provimento parcial`
- **Voto nº**: `Voto nº (\d+)`
- **Partes**: `Apelante(s):`, `Apelado(s):` lines after case number
- **Relator**: Last line before signature, or in ACÓRDÃO section

### TJSP-Specific Fields
| Field | Pattern |
|---|---|
| `registro` | `Registro: (\d{4}\.\d+)` |
| `voto_numero` | `Voto nº (\d+)` |
| `camara` | `(\d+ª Câmara de Direito \w+)` |

---

## TJMS — Tribunal de Justiça de Mato Grosso do Sul

**Sample**: 2000778-96.2018.8.12.0000 (313,797 chars)

### Document Structure
```
Tribunal de Justiça do Estado de Mato Grosso do Sul
[date]
[Câmara Criminal]
Apelação Criminal - Nº XXXX - [Comarca]
Relator (Designado) – Exº. Sr. Des. [name]
Apelante: [name].
Advogado: [name] (OAB: XXXX/MS).
[repeat for all parties]
Apelado: [party]
Prom. Justiça: [name]
[EMENTA - all caps, very long]
I. Caso em Exame
  [narrative]
II. Questão em Discussão
  (i) [question]
  (ii) [question]
III. Razões de Decidir
  (i) [reasoning per party]
  (ii) [reasoning]
---
D E C I S Ã O
Como consta na ata, a decisão foi a seguinte:
POR MAIORIA/POR UNANIMIDADE, DERAM/NEGARAM PROVIMENTO...
[NOS TERMOS DO VOTO DO Xº VOGAL...]
[VENCIDO O RELATOR - if applicable]
Presidência do Exº. Sr. Des. [name]
Relator, o Exº. Sr. Des. [name]
Tomaram parte no julgamento os Exºs. Srs. [judges]
Campo Grande, [date].
```

### Key Extraction Patterns
- **Date at top**: First 3 lines — `Tribunal...\n[date]\n[Câmara]`
- **OAB numbers**: `OAB: (\d+)/(\w+)` — extract for each lawyer
- **Promotor**: `Prom. Justiça:` line
- **Interessado**: `Interessado:` / `Proc. Município:` lines
- **Decision**: `POR (MAIORIA|UNANIMIDADE), (DERAM|NEGARAM) PROVIMENTO`
- **Voting breakdown**: `VENCIDO O RELATOR` / `VOGAL` mentions
- **Judges panel**: `Tomaram parte no julgamento` section

### TJMS-Specific Fields
| Field | Pattern |
|---|---|
| `camara` | `(\d+ª Câmara \w+)` at line 3 |
| `data_sessao` | Date line between header and câmara |
| `oab_advogados` | List of `(name, OAB_number, state)` tuples |
| `promotor` | `Prom. Justiça: (.+)` |
| `interessados` | `Interessado: (.+)` lines |
| `votacao_detalhe` | Who was vencido/vogal, vote direction |

---

## TJCE — Tribunal de Justiça do Ceará

**Sample**: 0012094-32.2023.8.06.0001 (396,178 chars)

### Document Structure
```
ESTADO DO CEARÁ / PODER JUDICIÁRIO / TRIBUNAL DE JUSTIÇA
GABINETE DESEMBARGADOR [NAME]
Processo: XXXX - Apelação Criminal
Apelantes: [list]
Apelados: [list]
Corréu: [if applicable]
EMENTA
[all-caps detailed syllabus, may span many lines]
I. CASO EM EXAME
  1. [narrative]
II. QUESTÃO EM DISCUSSÃO
  2. [numbered questions]
III. RAZÕES DE DECIDIR (or just inline reasoning)
[numbered paragraphs]
---
[final disposition/vote]
[DESEMBARGADOR NAME]
Relator
```

### Key Extraction Patterns
- **Gabinete**: `GABINETE DESEMBARGADOR (.+)` — desk/office of judge
- **Corréu**: `Corréu: (.+)` — co-defendant
- **EMENTA**: Between `EMENTA\n` marker and `I. CASO EM EXAME`
- **Structure**: Same Roman numeral pattern as TJSP

### TJCE-Specific Fields
| Field | Pattern |
|---|---|
| `gabinete` | `GABINETE DESEMBARGADOR (.+)` |
| `correu` | `Corréu: (.+)` |
| `estado` | Always "CEARÁ" |
| `ementa_start` | `^EMENTA\n` |
| `ementa_end` | `^I\. CASO EM EXAME` or `^\d+\. ` after ementa |

---

## TJRS — Tribunal de Justiça do Rio Grande do Sul

**Sample**: 70078303831 (682,670 chars after .doc conversion, multi-fact case)

### Document Structure (very different from others!)
```
apelaçÕES crime. [crime list - FATOS 1-24].
ABSOLVIÇÃO DOS RÉUS NOS [fatos].
PRELIMINARES.
  [each preliminary argument → rejection]
MÉRITO.
  [N]º FATO. [CRIME TYPE]. [resolution].
    [detailed reasoning per fato]
    [party identification per fato]
    [evidence discussion per fato]
1º FATO. ASSOCIAÇÃO CRIMINOSA. [reasoning]
DOSIMETRIA DAS PENAS.
  [DEFENDANT NAME]. [sentence adjustment]
  [repeat per defendant]
```

### Key Extraction Patterns (WARNING: Legacy .doc format!)
- **Multi-fato**: One document covers 24 separate criminal facts
- **Fato IDs**: `(\d+)º FATO\.` — numbered facts
- **Crime per fato**: Text after fato number: `(\d+)º FATO\. (.+?)\.`
- **Defendants per fato**: Named inline in reasoning
- **Preliminares**: `PRELIMINARES\.` section with sub-items
- **Sentences**: `DOSIMETRIA DAS PENAS\.` section — one per defendant
- **Regime**: `regime inicial (fechado|semiaberto|aberto)`
- **Pena**: `(\d+) anos, (\d+) meses e (\d+) dias de reclusão`

### TJRS-Specific Fields
| Field | Pattern |
|---|---|
| `fatos` | Array of `{numero, crime, reus, decisao}` per fact |
| `preliminares` | Array of preliminary arguments and rulings |
| `dosimetria` | Array of `{reu, pena_final, regime}` per defendant |
| `armas_apreendidas` | Weapons seized during operation |
| `quantidade_reus` | Total number of defendants |

### RISK: TJRS uses .doc (binary MS Word)
- 245 docs need LibreOffice conversion before text extraction
- Slow (~10-30s per doc with LibreOffice --headless)
- Missing structured fields — the "text_chars" and "json_path" are null for ALL 245 docs
- The converter (convert_docs.py) exists at docx_jurisprudence/ but hasn't been run

---

## TJAC, TJAL, TJAM — CAPTCHA-Blocked Courts

### Status: NO REAL CONTENT
All downloaded files are reCAPTCHA blocker pages, not actual decisions.

**Evidence:**
- All text_chars = 222 (exact same size for CAPTCHA page)
- Content: `Consulta de Jurisprudência do Segundo Grau` + Google reCAPTCHA
- TJAC: 33/42 CAPTCHA, 9 no-text
- TJAL: 38/39 CAPTCHA, 1 no-text  
- TJAM: 47/47 CAPTCHA

### Required Fix
The scraper needs CAPTCHA-solving capability (2captcha API, Playwright stealth, or session cookie injection) to bypass these courts' anti-bot protection.

### Expected Formats (unknown until real content is obtained)
These courts use the SAJ/PJe system and likely follow formats similar to TJSP or TJMS.

---

## Extraction Pipeline Architecture

```
DOCX/PDF/DOC/HTML
    ↓
[Format-specific parser per court]
    ↓
Raw text + metadata
    ↓
[LLM or regex extraction per court schema]
    ↓
Structured JSON with common fields + court-specific fields
    ↓
[Qdrant vector embedding]
    ↓
law_br collection
```

### Recommended Approach
1. **Phase 1**: Mechanical regex extraction for high-confidence fields (processo, relator, data, partes, decisao)
2. **Phase 2**: LLM-assisted extraction for ementa, assuntos, and complex fields
3. **Phase 3**: Cross-validation between regex and LLM results

### Court Format Coverage

| Court | Docs | Format | Extraction Ready? |
|---|---|---|---|
| TJSP | 468 (294 real) | PDF text | YES |
| TJMS | 161 (128 real) | PDF text | YES |
| TJCE | 47 (23 real) | PDF text | YES |
| TJRS | 245 (0 real) | .doc binary | Needs conversion |
| TJAC | 42 (0 real) | CAPTCHA | Needs scraper fix |
| TJAL | 39 (0 real) | CAPTCHA | Needs scraper fix |
| TJAM | 47 (0 real) | CAPTCHA | Needs scraper fix |
