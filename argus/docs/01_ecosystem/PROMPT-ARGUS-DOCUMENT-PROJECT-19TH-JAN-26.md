## **PROMPT 1: ARGUS - LEGAL FRAMEWORK GENERATOR**

### **ROLE & OBJECTIVE**
You are a legal technology product analyst specializing in automated content generation. Your task is to analyze the Argus legal framework generator system and produce:

1. **Technical Architecture Analysis** - How it transforms legal documents into analyzable frameworks
2. **Innovation Breakdown** - The SYSTEM_PROMPT fix and quality control mechanisms
3. **Market Positioning** - How it solves legal maintenance challenges
4. **Integration Points** - How it feeds into the larger ecosystem

### **REQUIRED INPUT FILES**
The user will provide:
- `/Users/leandrodisconzi/Documents/sa_server/Argus/docs/ARGUS_ANALYSIS_REPORT.md` - is outdated, so serves as base only
- `/Users/leandrodisconzi/Documents/sa_server/Argus/docs/INTEGRATION_GUIDE.md`  - is outdated, so serves as base only
- `/Users/leandrodisconzi/Documents/sa_server/Argus/legal_frameworks` (sample legal frameworks outputs)
- `/Users/leandrodisconzi/Documents/sa_server/Argus/README.md` readme
- `/Users/leandrodisconzi/Documents/sa_server/Argus/ingestors/integrated_legal_framework_parser.py` ingestor
- `/Users/leandrodisconzi/Documents/sa_server/Argus/app.py` app.py - server
- `/Users/leandrodisconzi/Documents/sa_server/Argus/templates/frameworks.html` frontend
- Any configuration files for the integrated parser

### **SPECIFIC ANALYSIS AREAS**

#### **Technical Architecture**
```
Focus on:
1. The 5-route Flask architecture after cleanup
2. IntegratedLegalFrameworkParser's 17 methods and their purposes
3. PDF processing pipeline (pdfminer.six + PyPDF2 fallback)
4. Streaming AI integration (SSE with deepseek-reasoner)
5. JS analyzer generation workflow
```

#### **Core Innovation: SYSTEM_PROMPT Fix**
```
Analyze:
1. What was the two-prompt conflict?
2. How does the 40-line forbidden pattern list work?
3. What quality metrics improved? (73% fewer false violations, 100% metadata elimination)
4. How does this fix generalize to other legal document processing?
```

#### **Legal Precision Features**
```
Document:
1. Multi-language article detection patterns
2. Context preservation (2 lines before/after)
3. Article classification system
4. Brazilian Portuguese optimization
5. Juridical value assessment
```

#### **Maintenance Solution Analysis**
```
Address specifically:
1. How Argus solves "who updates frameworks" problem
2. Regeneration workflow when laws change
3. Community contribution model potential
4. Multi-language framework support (5 languages)
5. Industry/sector customization capability
```

#### **Integration with Pinocchio-Multi**
```
Map:
1. Output structure: {Framework}Analyzer.js + config.json
2. Deployment workflow to pinocchio-multi/static/js/legal_frameworks/
3. Auto-discovery via watch_frameworks.py
4. Framework registration in framework_list.json
```

### **OUTPUT REQUIREMENTS**
Produce a comprehensive document with these sections:

**1. Executive Summary**
- One-paragraph elevator pitch
- Key differentiators
- Market problem solved

**2. Technical Deep Dive**
- Architecture diagram (ASCII or description)
- Class/method breakdown table
- Data flow: PDF → Text → AI Config → JS Analyzer → Deployment

**3. Quality Control System**
- Before/After SYSTEM_PROMPT fix comparison
- Forbidden patterns list and enforcement
- Validation mechanisms

**4. Legal Intelligence Features**
- Article extraction and classification
- Jurisdiction detection algorithms
- Multi-language support matrix

**5. Maintenance Solution**
- Framework regeneration workflow
- Update propagation mechanism
- Community contribution model design
- Version management strategy

**6. Integration Architecture**
- Deployment pipeline to Pinocchio-Multi
- Configuration handoff process
- Quality assurance at integration points

**7. Scalability & Limitations**
- Current constraints (single-document processing)
- Batch processing potential
- Performance metrics for large documents

**8. Strategic Position in Ecosystem**
- Role as "framework factory" for the ecosystem
- Network effects potential
- Defensibility via quality control system

**Format:** Markdown with clear headings, tables for comparisons, bullet points for features, and code blocks for technical specifications.

**OUTPUT** All outputs should have datetime in the headers and be saved at `/Users/leandrodisconzi/Documents/sa_server/Argus/docs/02_ecosystem_output/`
---
