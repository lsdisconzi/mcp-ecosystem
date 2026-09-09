# ABEAR_Code — ABEAR Instrumentos Normativos Internos

## Metadata

| Field | Value |
|-------|-------|
| **Source** | `missing_law_info/` — two ABEAR instruments |
| **Jurisdiction** | BR |
| **Framework code** | ABEAR_POL |
| **Framework name** | ABEAR – Política de Tratamento de Relatos, Respostas a Incidentes e Medidas Disciplinares (POL/PMD) |
| **Cached provisions** | §1 (Objetivo), §5 (Análise de Não Conformidades), §7 (Medidas Disciplinares) |
| **Norm scope** | contractual (internal policy, not statutory law) |
| **Notes** | See extraction notes below. ABEAR is the Associação Brasileira das Empresas Aéreas (trade association). Its instruments are contractual/organizational, not federal statutory law. They are included as contextual reference only — they do not carry ELI or Planalto citation authority. |

---

## Extraction Notes

#### Instrumento 1 — Estatuto ABEAR (28/junho/2024)

**File:** `ESTATUTO-ABEAR-Associacao-Brasileira-das-Empresas-Aereas-28.junho_.2024-1.pdf`  
**Status:** ⚠️ **Not extractable** — PDF conversion returned empty content. The Estatuto is an association charter (ato constitutivo) defining ABEAR's governance structure, membership, and decision-making bodies. It is cited as factual context only; no articles are cached here.

#### Instrumento 2 — Política de Tratamento de Relatos (nov/2022)

**File:** `Politica-de-Tratamento-de-Relatos-Respostas-a-Incidentes-e-Medidas-Disciplinares-ABEAR.pdf`  
**Code:** POL/PMD-ABEAR | **Approval:** 25/novembro/2022 | **Revision:** 01  
**Status:** ✅ Extracted via PDF-to-markdown conversion.

---

## Provisions — POL/PMD-ABEAR

### Art. §1 — Objetivo

**Theme:** ABEAR Policy
**ELI ID:** `BR.ABEAR_POL.§1 — Objetivo`
**Tags:** norm_type: procedural

**ELI ID:** `BR.ABEAR_POL.S1`  
**Norm type:** procedural | **Direction:** mandatory | **Scope:** contractual

> Esta política estabelece as condições gerais e necessárias para a tomada de decisão que envolvam medidas disciplinares após a devida apuração e conclusão da procedência de fatos que contrariem as diretrizes apresentadas no Código de Conduta e Programa de Compliance ABEAR.

---

### Art. §5 — Análise de Reportes que Representam Não Conformidades

**Theme:** ABEAR Policy
**ELI ID:** `BR.ABEAR_POL.§5 — Análise de Reportes que Representam Não Conformidades`
**Tags:** norm_type: procedural

**ELI ID:** `BR.ABEAR_POL.S5`  
**Norm type:** procedural | **Direction:** mandatory | **Scope:** contractual

> Os reportes que representarem qualquer tipo de violação ao Código de Conduta da ABEAR, ao Programa de Compliance da ABEAR e/ou a Legislação vigente serão:
>
> a) analisados e classificados de acordo com seu teor;  
> b) investigados por equipe específica, coordenada pelo CCO/ABEAR, que manterá os envolvidos em sigilo, denunciante e denunciado, para condução adequada dos trabalhos e, concluído os trabalhos e sendo pertinente, recomendar a aplicação das ações e/ou penalidades previstas no tópico 7 desta política.

**Note:** During investigation, if the reported person obstructs the process, the CCO may adopt provisional administrative measures after consultation with the Compliance Committee.

---

### Art. §7 — Deliberação do Comitê de Compliance e Medidas Disciplinares

**Theme:** ABEAR Policy
**ELI ID:** `BR.ABEAR_POL.§7 — Deliberação do Comitê de Compliance e Medidas Disciplinares`
**Tags:** norm_type: procedural

**ELI ID:** `BR.ABEAR_POL.S7`  
**Norm type:** penalty | **Direction:** mandatory | **Scope:** contractual

> A aplicação das medidas deve ocorrer de acordo com a sua natureza e recomendações advindas do Comitê de Compliance mediante apresentação do resultado dos trabalhos de investigação realizado e a recomendação do Chief Compliance Officer da ABEAR.
>
> As medidas disciplinares poderão ser:
>
> a) **Advertência verbal** — responsabilidade do gestor ao qual o colaborador está subordinado;  
> b) **Advertência escrita** — com registro no prontuário do colaborador;  
> c) **Demissão sem justa causa** — nos casos de quebra de confiança, mesmo sem evidência de falta grave;  
> d) **Demissão por justa causa** — quando houver elementos e evidências suficientes da falta cometida que atendam todos os dispositivos legais previstos na Legislação Trabalhista vigente;  
> e) **Encerramento do Contrato com Terceiros e/ou prestadores de serviços** — nos casos de quebra de confiança; dependendo da gravidade da infração, outras medidas poderão ser avaliadas com a área jurídica.

**Duty bearers:** Comitê de Compliance ABEAR, CCO ABEAR  
**Regulated subject:** disciplinary_measures  
**Sanctions:** advertência_verbal, advertência_escrita, demissão_sem_justa_causa, demissão_por_justa_causa, encerramento_contrato

---

## Related ABEAR instrument caches (per-instrument files)

The following ABEAR instruments are cached as separate per-instrument files under `04-law/BR/`, mirroring this file's "contractual/contextual" convention (added 2026-08-13):

| File | Instrument | Notes |
|---|---|---|
| `ABEAR_CodigoConduta.md` | Código de Conduta ABEAR (POL/COC) | Approved 29/10/2021; **BR-020 anchor** |
| `ABEAR_PoliticaAnticorrupcao.md` | Política Anticorrupção ABEAR (POL/PAC) | Approved 29/10/2021 |
| `ABEAR_PoliticaInteracaoAgentesPublicos.md` | Política de Interações com Agentes Públicos (POL/PIAP) | Approved 28/10/2020; cross-ref `BR_CONFLITO_INTERESSES` |
| `ABEAR_RegimentoComiteCompliance.md` | Regimento Interno do Comitê de Compliance | Defines Coordenador + Secretário Executivo + CCO |

Corporate/institutional compliance caches (LATAM 2024 CoC, Sixth Street CoE) live under `04-law/CORP/`.

---

## Relevance for LA-8159

The ABEAR instruments are **non-statutory contextual reference** for the incident. They are relevant to demonstrate:
1. The industry's own compliance framework obligates member airlines (including TAM/LATAM) to investigate and act on conduct violations.
2. The Política POL/PMD defines a disciplinary escalation ladder from verbal warning to dismissal for just cause.
3. The Estatuto governs how ABEAR member decisions bind member airlines — however, its text is not extractable from the provided PDF.

For statutory legal analysis, cite CC, CDC, CBA, and ANAC/R-400 instruments. ABEAR instruments supplement the factual and industry-standard arguments.
