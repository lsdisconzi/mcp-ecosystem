---
name: LA8159 legal grounding library architecture
description: Reference for the OliviaLegal la8159 agent group — what agents, source files, and mappings exist
type: reference
---

The LA8159 agent group (`agents/agents-groups/la8159/`) is a complete legal grounding library for a specific aviation incident (LA8159 — LATAM/PDI/DGAC, Santiago Airport, 2024-04-04, related GRU incident).

**Agent count (41 total):**
- 2 runtime agents: orchestrator (routes facts/violation IDs) and coordinator (governance, manifest, source sync)
- 16 BR specialists (CDC, CBA, CF88, CP, CC, ANAC R400, Anticorrupcao, Improbidade, LAI, Lei 9784, OAB Disciplina, OAB Comissao Aero, Conflito Interesses, ABEAR Plus, ABRAPAVAA SENTRA, SDC Procon Senacon)
- 7 CL specialists (CACH, Constitution, DGAC L16752, CPCL, LPDC, Contraloria INDH, Transparency L20285)
- 10 INT specialists (MC99, ACHR, Chicago VCLT, ICAO AN17/AN6-AN13/AN9, IATA GC, Softlaw, UNCRC Hague, VCCR)
- 6 meta specialists (Adversarial, Evidence Mapper, Institutional Silence, Personnel Accountability, Prescription Forum, RevolvingDoor)

**Knowledge assets:**
- 59 cached source files: 20 BR statutes, 17 CL statutes, 22 INT instruments — all article-level with ELI IDs, SHA256 hashes, and verification flags
- 71 pre-mapped violation IDs (BR-001 to BR-020, CL-001 to CL-032, INT-001 to INT-019) in `mapping.json` with primary+supporting agent routing
- 7 personnel dossiers with verified roles and OAB inscriptions
- 804-line jurisprudence search guide with targeted queries per article
- Per-agent policies: handoff-routes.json (violation→agent routing) and tool-permissions.by-agent.json (deny-by-default, read-only for all 40 agents)

**Agent schema (9 sections):** Identity, Primary Articles in Scope, Official Sources, Knowledge Boundaries (NEVER-do rules), Capabilities, Cross-References to violations, Adversarial Vulnerabilities, Output Constraints, Provenance

**Verification flags:** verified (full text confirmed), pending (widely cited, not yet confirmed), caveated (verified with scope limits), excluded (fabricated/time-barred — never cite)

**Build system:** `.build-index.py` scaffolder generates all agent files, manifest JSONs, bundles, and policies from canonical source specs in `source/BR/`, `source/CL/`, `source/INT/`, `source/meta/`.

**Location:** `/Users/leandrodisconzi/work/OliviaLegal/agents/agents-groups/la8159/`
