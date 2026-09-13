#!/usr/bin/env python3
"""
Mechanical Jurisprudence Document Extractor.

Extracts structured fields from Brazilian court documents (TJSP, TJMS, TJCE, TJRS)
using regex patterns, producing structured JSON ready for Qdrant ingestion.

Usage:
    cd /root/juris-search && source .venv/bin/activate
    python court_extractor.py --courts TJSP TJMS TJCE TJRS --max-per-court 5
    python court_extractor.py --courts TJSP --max-per-court 1  # single test
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re

logger = logging.getLogger("juris-search.court_extractor")
import sys
import textwrap
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# ── Add .venv site-packages for PyPDF2 and python-docx ──────────────────────
_VENV_SP = "/home/disconzi1986_gmail_com/juris-search-VPS/.venv/lib/python3.12/site-packages"
if _VENV_SP not in sys.path:
    sys.path.insert(0, _VENV_SP)

from PyPDF2 import PdfReader
from docx import Document as DocxDocument
from bs4 import BeautifulSoup
try:
    import pdfplumber
except ImportError:
    pdfplumber = None
try:
    from odf.opendocument import load as load_odt
    from odf.text import P
    HAS_ODF = True
except ImportError:
    HAS_ODF = False

# ── Reusable patterns from juris_indexer.py ──────────────────────────────────
CNJ_PROC_RE = re.compile(r"\b(\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4})\b")
MONEY_RE = re.compile(r"R\$\s*[\d\.\,]+", re.IGNORECASE)
OUTCOME_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("negado_provimento",     re.compile(r"\bnegar(?:am)?\s+provimento\b", re.IGNORECASE)),
    ("dado_provimento",       re.compile(r"\bd(?:ar(?:am)?|eram)\s+provimento\b", re.IGNORECASE)),
    ("provimento_parcial",    re.compile(r"\bparcial(?:mente)?\s+provimento\b|\bprovimento\s+parcial\b", re.IGNORECASE)),
    ("reformada",             re.compile(r"\bsenten[cç]a\s+reformada\b", re.IGNORECASE)),
    ("mantida",               re.compile(r"\bmantida\s+a\s+senten[cç]a\b|\bmantenho\s+por\s+seus\s+pr[oó]prios\s+fundamentos\b", re.IGNORECASE)),
    ("procedente",            re.compile(r"\bjulgo\s+procedente\b|\bprocedente\s+o\s+pedido\b", re.IGNORECASE)),
    ("improcedente",          re.compile(r"\bjulgo\s+improcedente\b|\bimprocedente\s+o\s+pedido\b", re.IGNORECASE)),
    ("unanime",               re.compile(r"\bun[aâ]nime\b", re.IGNORECASE)),
]
EMENTA_END_RE = re.compile(r"\b(AC[ÓO]RD[ÃA]O|RELAT[ÓO]RIO|VOTOS?)\b")
TJRS_FNAME_RE = re.compile(
    r"inteiro_teor_(?P<numero>\d+)_(?P<ano>\d{4})_(?P<codigo>\d+)", re.IGNORECASE)
ESAJ_FNAME_RE = re.compile(
    r"(?:inteiro_teor|acordao|cdacordao)[_\-]?(?P<cdacordao>\d{6,})", re.IGNORECASE)

# ── TC Chile (Tribunal Constitucional de Chile) patterns ────────────────────
# Local download names are ``CLTC_[YYYY-MM-DD_]folio.pdf`` — see tc_chile_scraper.py.
CLTC_FNAME_RE = re.compile(
    r"CLTC[_-](?:(?P<fecha>\d{4}-\d{2}-\d{2})[_-])?(?P<folio>\d+)", re.IGNORECASE)
# "Rol 16.622-2025 INA" / "Rol N° 16.622-25-INA"
CLTC_ROL_RE = re.compile(
    r"\bRol\s*(?:N[°º]?\.?)?\s*(?P<numero>\d[\d\.]*)\s*[-–]\s*(?P<ano>\d{2,4})"
    r"(?:[\s\-–]+(?P<sigla>[A-Z]{2,4})(?![A-Z]))?",
    re.IGNORECASE)
# TC sentences are structured VISTOS / CONSIDERANDO / SE RESUELVE (not EMENTA/ACÓRDÃO).
CLTC_VISTOS_RE = re.compile(r"\bVISTOS\b\s*:?", re.IGNORECASE)
# The operative part always carries a colon ("SE RESUELVE:", "RESUELVO:").
# Requiring it avoids matching body prose such as "sí ha resuelto reiteradamente".
CLTC_RESUELVE_RE = re.compile(
    r"\b(?:SE\s+RESUELVE|RESUELVO|HA\s+RESUELTO)\s*:", re.IGNORECASE)
CLTC_CONSIDERANDO_RE = re.compile(
    r"\b(?:CONSIDERANDO|TENIENDO\s+PRESENTE|PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|"
    r"S[ÉE]PTIMO|OCTAVO|NOVENO|D[ÉE]CIMO)\b\s*:?",
    re.IGNORECASE)
CLTC_DISIDENCIA_RE = re.compile(
    r"\b(?:DISIDENCIA|VOTO\s+DE\s+MINOR[ÍI]A|PREVENCI[ÓO]N|ESTUVIERON\s+POR)\b",
    re.IGNORECASE)
CLTC_REDACTOR_RE = re.compile(
    r"Redact[óo]\s+la\s+sentencia\s+(?:el|la)\s+Ministr[oa]\s+(?:se[ñn]or(?:a)?\s+)?"
    r"(?P<nombre>[^.,]{5,90}?)\s*[.,]",
    re.IGNORECASE)
CLTC_INTEGRACION_RE = re.compile(
    r"(?:integrada|compuesta|constituida)\s+por\s+(?P<body>.{20,1500}?)\.\s",
    re.IGNORECASE | re.DOTALL)
CLTC_SIDECAR_RE = re.compile(r"^CLTC_", re.IGNORECASE)
# "I. QUE SE RECHAZA EL REQUERIMIENTO ..." holdings under SE RESUELVE:
CLTC_HOLDING_RE = re.compile(
    r"^\s*(?P<num>[IVXLC]{1,6})\s*[.\-–]\s*(?:QUE\s+)?(?P<texto>.+?)"
    r"(?=^\s*[IVXLC]{1,6}\s*[.\-–]\s|\Z)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE)
CLTC_LEGISLACAO_RE = re.compile(
    r"(?:art[íi]culos?\s*[\d\.\-]+\s*(?:incisos?\s+\w+\s*)?(?:,?\s*N[°º]\s*\d+\s*)?"
    r"(?:de\s+la\s+|del\s+|de\s+)?)?"
    r"(Constituci[óo]n\s+Pol[íi]tica(?:\s+de\s+la\s+Rep[úu]blica)?|"
    r"C[óo]digo\s+(?:de\s+Procedimiento\s+)?(?:Civil|Penal|Procesal\s+Penal|Tributario|"
    r"del\s+Trabajo|Org[áa]nico\s+de\s+Tribunales)|"
    r"Ley\s+(?:N[°º]\s*)?[\d\.]+\s*(?:Org[áa]nica\s+Constitucional)?)",
    re.IGNORECASE)
CLTC_OUTCOME_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("acoge",           re.compile(r"\bQUE\s+SE\s+ACOGE\b|\bse\s+acoge\s+el\s+requerimiento\b"
                                   r"|\bacoger\s+el\s+libelo\b", re.IGNORECASE)),
    ("rechaza",         re.compile(r"\bQUE\s+SE\s+RECHAZA\b|\bse\s+rechaza\s+el\s+requerimiento\b"
                                   r"|\brechazar\s+el\s+libelo\b", re.IGNORECASE)),
    ("acoge_parcial",   re.compile(r"\bacoge\s+parcial|\bparcialmente\s+acoge", re.IGNORECASE)),
    ("rechaza_parcial", re.compile(r"\brechaza\s+parcial|\bparcialmente\s+rechaza", re.IGNORECASE)),
    ("empate_votos",    re.compile(r"\bempate\s+de\s+votos?\b", re.IGNORECASE)),
    ("inadmisible",     re.compile(r"\bdeclara\s+inadmisible\b|\binadmisible\s+el\s+requerimiento\b",
                                   re.IGNORECASE)),
    ("no_conoce",       re.compile(r"\bse\s+abstiene\s+de\s+conocer\b", re.IGNORECASE)),
]
# Spanish-Chilean constitutional subject keywords (the inherited list is
# Brazilian Portuguese and would always return nothing for TC Chile).
CLTC_ASSUNTOS: List[str] = [
    "DERECHO A LA VIDA", "IGUALDAD ANTE LA LEY", "DEBIDO PROCESO",
    "LIBERTAD PERSONAL", "DERECHO DE PROPIEDAD", "MEDIO AMBIENTE",
    "DERECHO A LA SALUD", "DERECHO A LA EDUCACIÓN", "LIBERTAD DE CONCIENCIA",
    "LIBERTAD DE EXPRESIÓN", "PROTECCIÓN DE LA VIDA PRIVADA",
    "INVIOLABILIDAD DEL HOGAR", "PROTECCIÓN DE DATOS PERSONALES",
    "TUTELA JUDICIAL EFECTIVA", "DERECHO AL RECURSO", "LIBERTAD ECONÓMICA",
    "DERECHO A LA INTIMIDAD", "PROTECCIÓN DE LA FAMILIA", "SEGURIDAD SOCIAL",
    "LIBERTAD DE TRABAJO", "NO DISCRIMINACIÓN", "DERECHO A LA HONRA",
    "INAPLICABILIDAD POR INCONSTITUCIONALIDAD", "CONTROL DE CONSTITUCIONALIDAD",
]

# ── Spanish month names (TC Chile dates: "19 de marzo de 2026") ─────────────
_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
DATE_LONG_ES_RE = re.compile(
    r"(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})",
    re.IGNORECASE)

# ── Month name → number for Brazilian Portuguese ─────────────────────────────
_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}

# ── Legislation citation patterns ────────────────────────────────────────────
LEGISLACAO_RE = re.compile(
    r"(?:art(?:igo)?s?\s*[\d\.\-]+\s*(?:[e,]\s*[\d\.\-]+)*\s*(?:do|da|,)?\s*)?"
    r"(Lei\s+(?:[nN][º°]\.?\s*)?\d[\d\.]*/\d{4}|"
    r"Decreto[- ]Lei\s+(?:[nN][º°]\.?\s*)?\d[\d\.]*/\d{4}|"
    r"C[oó]digo\s+(?:de\s+)?(?:Processo\s+)?(?:Civil|Penal|Tribut[aá]rio|"
    r"de\s+Defesa\s+do\s+Consumidor|Eleitoral|Comercial|de\s+Tr[aâ]nsito\s+Brasileiro)|"
    r"Constitui[cç][aã]o\s+Federal)",
    re.IGNORECASE,
)

# ── Date patterns ────────────────────────────────────────────────────────────
DATE_LONG_RE = re.compile(
    r"(\d{1,2})\s+de\s+(janeiro|fevereiro|março|marco|abril|maio|junho|julho|"
    r"agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})",
    re.IGNORECASE,
)
DATE_DDMMYYYY_RE = re.compile(r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b")


# ═══════════════════════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════════════════════

def _norm(text: str) -> str:
    """Normalize whitespace: collapse multiple spaces/newlines into single space."""
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(text: str) -> Optional[str]:
    """Try multiple date formats, return ISO YYYY-MM-DD or None."""
    text = text.strip()
    # dd/mm/yyyy or dd-mm-yyyy
    m = DATE_DDMMYYYY_RE.search(text)
    if m:
        try:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        except ValueError:
            pass
    # "19 de maio de 2026"
    m = DATE_LONG_RE.search(text)
    if m:
        try:
            mon = _MONTHS.get(m.group(2).lower(), 0)
            if mon:
                return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
        except ValueError:
            pass
    return None


def _parse_date_es(text: str) -> Optional[str]:
    """Parse a Spanish/ISO date, returning ISO ``YYYY-MM-DD`` or None.

    Handles ``19 de marzo de 2026``, ``2026-03-19`` and
    ``2026-03-19 03:00:00`` (the shape stored in the TC Chile sidecar).
    """
    if not text:
        return None
    text = str(text).strip()
    # ISO / sidecar timestamp
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # "19 de marzo de 2026"
    m = DATE_LONG_ES_RE.search(text)
    if m:
        mon = _MONTHS_ES.get(m.group(2).lower(), 0)
        if mon:
            return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
    # dd/mm/yyyy
    m = DATE_DDMMYYYY_RE.search(text)
    if m:
        try:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        except ValueError:
            pass
    return None


def _titlecase_name(name: str) -> str:
    """Title-case an ALL-CAPS personal name ("HÉCTOR MERY ROMERO" → "Héctor Mery Romero").

    Names that already contain lowercase letters are returned unchanged.
    """
    name = _norm(name)
    if not name:
        return name
    letters = [c for c in name if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters):
        return name
    small = {"de", "del", "la", "las", "los", "y", "e", "van", "von", "da", "do"}
    out = []
    for i, word in enumerate(name.split()):
        low = word.lower()
        if i > 0 and low in small:
            out.append(low)
        else:
            out.append(low[:1].upper() + low[1:])
    return " ".join(out)


def _extract_outcomes(text: str) -> List[str]:
    seen = set()
    results = []
    for label, pat in OUTCOME_PATTERNS:
        if pat.search(text) and label not in seen:
            results.append(label)
            seen.add(label)
    return results


def _extract_cnj(text: str) -> Optional[str]:
    """Find first CNJ-format process number in text."""
    m = CNJ_PROC_RE.search(text)
    return m.group(1) if m else None


def _extract_money(text: str) -> List[str]:
    return MONEY_RE.findall(text)[:8]


def _extract_legislacao(text: str) -> List[str]:
    seen = set()
    result = []
    for m in LEGISLACAO_RE.finditer(text):
        item = _norm(m.group(0))
        if item.lower() not in seen:
            result.append(item)
            seen.add(item.lower())
    return result[:20]


def _classify(text: str, keywords: List[str]) -> List[str]:
    """Classify text into categories based on keyword presence."""
    found = []
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE):
            found.append(kw)
    return found


def _load_master_index(path: str = "/home/disconzi1986_gmail_com/juris-search-VPS/master_index/master_index.json") -> dict:
    with open(path) as f:
        return json.load(f)


def _build_master_lookup(master: dict) -> Dict[str, dict]:
    """Build lookup by cdacordao and by raw_source_path basename."""
    by_cdacordao = {}
    by_rsp = {}
    for doc in master.get("documents", []):
        cd = doc.get("cdacordao")
        if cd:
            by_cdacordao[str(cd)] = doc
        rsp = doc.get("raw_source_path", "")
        if rsp:
            by_rsp[os.path.basename(rsp)] = doc
    return by_cdacordao, by_rsp


def _load_sidecar(filepath: str) -> Dict[str, Any]:
    """Read the ``<file>.metadata.json`` sidecar written by the scrapers.

    Returns an empty dict when the sidecar is missing or unreadable. The
    scraper-produced sidecar is the most reliable source of structured
    metadata (especially for TC Chile, whose PDFs are Spanish free text).
    """
    path = Path(f"{filepath}.metadata.json")
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("sidecar unreadable for %s: %s", filepath, exc)
        return {}
    return data if isinstance(data, dict) else {}


# ═══════════════════════════════════════════════════════════════════════════════
# Text Extraction
# ═══════════════════════════════════════════════════════════════════════════════

def extract_pdf_text(pdf_path: str) -> str:
    """Extract full text from PDF using PyPDF2, with pdfplumber fallback.

    The fallback kicks in for PDFs PyPDF2 struggles with (e.g. unsupported
    CMaps such as Big5 fonts, which emit empty text and a PdfReadWarning).
    """
    reader = PdfReader(pdf_path)
    parts = []
    for page in reader.pages:
        txt = page.extract_text()
        if txt:
            parts.append(txt)
    text = "\n\n".join(parts)

    if pdfplumber and len(text.strip()) < 200:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                plumber_parts = []
                for page in pdf.pages:
                    txt = page.extract_text() or ""
                    if txt:
                        plumber_parts.append(txt)
                if plumber_parts:
                    text = "\n\n".join(plumber_parts)
        except Exception as exc:
            logger.debug("pdfplumber fallback failed for %s: %s", pdf_path, exc)

    return text


def extract_docx_text(docx_path: str) -> str:
    """Extract full text from DOCX using python-docx."""
    doc = DocxDocument(docx_path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_doc_text(doc_path: str) -> str:
    """Extract full text from .doc file.
    
    First attempts to use LibreOffice to convert .doc to .docx,
    then extracts text from the resulting .docx.
    Falls back to basic text extraction if conversion fails.
    """
    try:
        # Try to use LibreOffice to convert .doc to .docx
        import subprocess
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "converted.docx")
            try:
                subprocess.run(
                    ["libreoffice", "--headless", "--convert-to", "docx", 
                     "--outdir", tmpdir, doc_path],
                    timeout=30,
                    capture_output=True
                )
                if os.path.exists(output_path):
                    return extract_docx_text(output_path)
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                pass  # Fall through to other methods
    except Exception:
        pass
    
    # Fallback: Try to extract using python-docx directly (works for some .doc files)
    try:
        doc = DocxDocument(doc_path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        # If all else fails, return empty string
        return ""


def extract_html_text(html_path: str) -> str:
    """Extract readable text from HTML file using BeautifulSoup."""
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
    except UnicodeDecodeError:
        # Try with latin-1 if utf-8 fails
        with open(html_path, "r", encoding="latin-1") as f:
            html = f.read()
    
    soup = BeautifulSoup(html, "html.parser")
    
    # Remove script and style elements
    for tag in soup(["script", "style", "meta", "link"]):
        tag.decompose()
    
    # Get text and clean it up
    text = soup.get_text(separator="\n", strip=True)
    
    # Remove excessive whitespace
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Base Extractor
# ═══════════════════════════════════════════════════════════════════════════════

class BaseExtractor:
    tribunal: str = ""
    section_marker = re.compile(
        r"(I+\.?)\s*(?:-|–)?\s*(?:CASO\s+EM\s+EXAME|RELAT[ÓO]RIO)",
        re.IGNORECASE,
    )

    def __init__(self, text: str, filename: str, master_lookup: dict = None,
                 sidecar: dict = None):
        self.raw_text = text
        self.text = _norm(text)
        self.filename = filename
        self.master = master_lookup or {}
        # Scraper-written ``<file>.metadata.json`` payload (may be empty).
        # Preferred over PDF free text when a field is available there.
        self.sidecar: Dict[str, Any] = sidecar or {}
        self.result: Dict[str, Any] = {
            "schema_version": 1,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "source_file": filename,
            "tribunal": self.tribunal,
        }
        self.confidence: Dict[str, str] = {}

    def _set(self, key: str, value: Any, confidence: str = "high"):
        if value is not None and value != [] and value != "":
            self.result[key] = value
            self.confidence[key] = confidence

    def extract_all(self) -> dict:
        self._extract_common()
        self._extract_ementa()
        self._extract_outcomes()
        self._extract_legislacao()
        self._extract_assuntos()
        self._extract_court_specific()
        self.result["texto_inteiro"] = self.raw_text
        self.result["texto_length"] = len(self.raw_text)
        self.result["extraction_confidence"] = self.confidence
        return self.result

    def _extract_common(self):
        """Override in subclasses."""
        pass

    def _extract_ementa(self):
        """Extract ementa between EMENTA marker and next section (ACÓRDÃO/RELATÓRIO/VOTO)."""
        raw = self.raw_text
        # Find EMENTA start
        m_start = re.search(r"\bEMENTA\b", raw, re.IGNORECASE)
        if not m_start:
            m_start = re.search(r"\bE\s+M\s+E\s+N\s+T\s+A\b", raw, re.IGNORECASE)
        if m_start:
            rest = raw[m_start.end():]
            # Stop at next major section
            m_end = re.search(
                r"\b(?:A\s+C\s+[ÓO]\s+R\s+D\s+[ÃA]\s+O|AC[ÓO]RD[ÃA]O|RELAT[ÓO]RIO|VOTO\b|"
                r"I+\.?\s*(?:-|–)?\s*(?:CASO\s+EM\s+EXAME|RELAT[ÓO]RIO))",
                rest, re.IGNORECASE,
            )
            end_pos = m_end.start() if m_end else min(3000, len(rest))
            ementa = _norm(rest[:end_pos]).lstrip("-–: \t")
            if len(ementa) > 80:
                self._set("ementa", ementa, "high")
                return
        # Fallback to section-marker approach
        m = self.section_marker.search(self.text)
        if m:
            prefix = self.text[:m.start()]
            ementa_start = 0
            for marker in ["EMENTA", "E M E N T A", "Ementa"]:
                idx = prefix.rfind(marker)
                if idx > ementa_start:
                    ementa_start = idx + len(marker)
            if ementa_start > 0:
                ementa = _norm(prefix[ementa_start:]).lstrip("-–: \t")
                em_end = EMENTA_END_RE.search(ementa)
                if em_end:
                    ementa = ementa[:em_end.start()]
                if len(ementa) > 50:
                    self._set("ementa", ementa, "medium")
                    return
        # Last resort
        self._set("ementa", self.text[:2000], "low")

    def _extract_outcomes(self):
        outcomes = _extract_outcomes(self.text)
        self._set("outcome", outcomes, "high" if outcomes else "low")

    def _extract_legislacao(self):
        leg = _extract_legislacao(self.text)
        self._set("legislacao_citada", leg, "medium" if leg else "low")

    def _extract_assuntos(self):
        keywords = [
            "DIREITO PENAL", "DIREITO CIVIL", "DIREITO DO CONSUMIDOR",
            "DIREITO ADMINISTRATIVO", "DIREITO TRIBUTÁRIO", "DIREITO PROCESSUAL CIVIL",
            "DIREITO PROCESSUAL PENAL", "TRÁFICO DE DROGAS", "ASSOCIAÇÃO PARA O TRÁFICO",
            "ORGANIZAÇÃO CRIMINOSA", "HOMICÍDIO", "ROUBO", "FURTO", "ESTELIONATO",
            "LICITAÇÃO", "IMPROBIDADE ADMINISTRATIVA", "RESPONSABILIDADE CIVIL",
            "DANO MORAL", "ALIMENTOS", "FAMÍLIA", "EXECUÇÃO FISCAL",
            "CRIMES DE RESPONSABILIDADE", "CONTRAVENÇÃO PENAL", "VIOLÊNCIA DOMÉSTICA",
            "POSSE DE ARMA", "RECEPTAÇÃO", "LAVAGEM DE DINHEIRO",
        ]
        found = _classify(self.text, keywords)
        self._set("assuntos", found, "high" if found else "low")

    def _extract_court_specific(self):
        """Override in subclasses."""
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# TJSP Extractor
# ═══════════════════════════════════════════════════════════════════════════════

class TJSPExtractor(BaseExtractor):
    tribunal = "TJSP"

    def _extract_common(self):
        text = self.text

        # Registro
        m = re.search(r"Registro:\s*(\d{4}\.\d+)", text)
        if m:
            self.result.setdefault("court_specific", {})["registro"] = m.group(1)

        # Numero processo
        m = re.search(
            r"(?:Apelação|Agravo|Habeas\s+Corpus)\s+\w+\s+(?:[nN][º°]\.?\s*)?(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})",
            text,
        )
        if m:
            self._set("numero_processo", m.group(1))
        else:
            cnj = _extract_cnj(text)
            if cnj:
                self._set("numero_processo", cnj, "medium")

        # Classe
        m = re.search(r"(Apelação\s+Criminal|Apelação\s+C[íi]vel|Habeas\s+Corpus|Agravo\s+de\s+Instrumento|Agravo\s+em\s+Execu[cç][aã]o)", text, re.IGNORECASE)
        if m:
            self._set("classe", m.group(1))

        # Órgão julgador
        m = re.search(r"(\d+ª\s+C[aâ]mara\s+de\s+Direito\s+\w+)", text)
        if m:
            self._set("orgao_julgador", m.group(1))
            self.result.setdefault("court_specific", {})["camara"] = m.group(1)

        # Comarca
        m = re.search(r"Comarca\s+de\s+(.+?)(?:,|\.|\n|\s+em\s+que)", text)
        if m:
            self._set("comarca", _norm(m.group(1)))

        # Relator — after ACÓRDÃO block, name before "Relator"
        m = re.search(r"([A-ZÀ-Ú][A-ZÀ-Ú\s]{3,40})\s*\n\s*Relator", self.raw_text)
        if m:
            self._set("relator", _norm(m.group(1)))

        # Data julgamento
        m = re.search(r"São Paulo,\s*(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})", text)
        if m:
            dt = _parse_date(m.group(1))
            self._set("data_julgamento", dt)

        # Partes
        partes = {}
        for role, label in [("apelantes", "Apelante"), ("apelados", "Apelad[ao]")]:
            pat = re.compile(rf"{label}s?:?\s*(.+?)(?=\n\n|\n(?:Apelad|Ju[ií]zo|Advogad|EMENTA|DIREITO))", re.IGNORECASE | re.DOTALL)
            m = pat.search(self.raw_text)
            if m:
                names = re.split(r"\s*[,;]\s*|\s+e\s+", _norm(m.group(1)))
                names = [n for n in names if len(n) > 3]
                if names:
                    partes[role] = names
        if partes:
            self._set("partes", partes)

        # Decisão
        m = re.search(r'"[^"]*((?:deram|negaram|proveram|acolheram|rejeitaram)[^"]*)"', text, re.IGNORECASE)
        if m:
            self._set("decisao", _norm(m.group(0).strip('"')))
        else:
            m = re.search(r"(Deram\s+provimento(?:\s+parcial)?.*?V\.\s*U\.)", text, re.IGNORECASE)
            if m:
                self._set("decisao", _norm(m.group(1)), "medium")

        # Voto número
        m = re.search(r"Voto\s+(?:[nN][º°]\.?\s*)?(\d+(?:\.\d+)?)", text)
        if m:
            self.result.setdefault("court_specific", {})["voto_numero"] = m.group(1)

        # Votação
        m = re.search(r"\b(V\.\s*U\.|POR\s+MAIORIA|POR\s+UNANIMIDADE)\b", text, re.IGNORECASE)
        if m:
            self._set("votacao", _norm(m.group(1)))

    def _extract_ementa(self):
        """TJSP ementa is between second header block (APTE/APDO) and 'Trata-se de'."""
        raw = self.raw_text
        # Find second "PODER JUDICIÁRIO" after "Assinatura Eletrônica"
        ass_idx = raw.find("Assinatura")
        if ass_idx > 0:
            rest = raw[ass_idx:]
            # Skip past APTE/APDO block, find ementa start
            m_apte = re.search(r"APTE\.\s*:", rest)
            m_apdo = re.search(r"APDO\.\s*:", rest)
            if m_apte or m_apdo:
                # Start after APDO block (the later of the two)
                ementa_start = max(m_apte.end() if m_apte else 0, m_apdo.end() if m_apdo else 0)
                ementa_text = rest[ementa_start:]
                # Find end at "Trata-se de" or "Vistos" or "I." section
                m_end = re.search(r"\b(Trata-se\s+de|Vistos\s*[,;]|I+\.?\s*(?:-|–)?\s*(?:CASO|RELAT))", ementa_text, re.IGNORECASE)
                end_pos = m_end.start() if m_end else min(3000, len(ementa_text))
                ementa = _norm(ementa_text[:end_pos]).lstrip("*–: \t")
                if len(ementa) > 80:
                    self._set("ementa", ementa, "high")
                    return
        # Fallback to base class
        super()._extract_ementa()

    def _extract_court_specific(self):
        pass  # Done inside _extract_common


# ═══════════════════════════════════════════════════════════════════════════════
# TJMS Extractor
# ═══════════════════════════════════════════════════════════════════════════════

class TJMSExtractor(BaseExtractor):
    tribunal = "TJMS"

    def _extract_common(self):
        text = self.text
        raw = self.raw_text

        # Número processo
        m = re.search(
            r"(?:Apelação|Agravo)\s+(?:C[íi]vel|Criminal)\s+-\s+(?:[nN][º°]\.?\s*)?(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})",
            text,
        )
        if m:
            self._set("numero_processo", m.group(1))
        else:
            cnj = _extract_cnj(text)
            if cnj:
                self._set("numero_processo", cnj, "medium")

        # Comarca — use raw_text to stop at newline
        m = re.search(
            r"(?:[nN][º°]\.?\s*)?\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\s*-\s*(.+?)(?:\n|$)",
            raw[:2000],
        )
        if m:
            self._set("comarca", _norm(m.group(1)))

        # Câmara — first few lines
        m = re.search(r"(\d+ª\s+C[aâ]mara\s+\w+)", raw[:500])
        if m:
            self._set("orgao_julgador", m.group(1))
            self.result.setdefault("court_specific", {})["camara"] = m.group(1)

        # Relator — use raw_text to stop at newline
        m = re.search(
            r"^Relator\s+(?:Designad[oa]\s*)?(?:–|-)?\s*(?:Ex[º°]\.?\s*Sr\.?\s*Des\.?\s*)?(.+?)$",
            raw[:2000],
            re.IGNORECASE | re.MULTILINE,
        )
        if m:
            self._set("relator", _norm(m.group(1)))

        # Data sessão
        m = re.search(
            r"Tribunal\s+de\s+Justi[cç]a\s+do\s+Estado\s+de\s+Mato\s+Grosso\s+do\s+Sul\s*\n\s*(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})",
            self.raw_text,
        )
        if m:
            dt = _parse_date(m.group(1))
            self._set("data_sessao", dt)

        # Partes
        partes = {}
        for role, label in [("apelantes", "Apelante"), ("apelados", "Apelad[oa]")]:
            pat = re.compile(
                rf"^{label}\s*:\s*(.+?)$",
                re.IGNORECASE | re.MULTILINE,
            )
            names = []
            for m in pat.finditer(self.raw_text):
                name = _norm(m.group(1))
                if name and len(name) > 3:
                    names.append(re.sub(r"\s*\(OAB:.*$", "", name))
            if names:
                partes[role] = names
        if partes:
            self._set("partes", partes)

        # Advogados + OAB
        advs = []
        for m in re.finditer(
            r"Advogad[oa]\s*:\s*(.+?)\s*\(OAB:\s*(\d+/\w+)\)",
            self.raw_text,
        ):
            advs.append({"nome": _norm(m.group(1)), "oab": m.group(2)})
        if advs:
            self._set("advogados", advs)
            self.result.setdefault("court_specific", {})["oab_advogados"] = [
                f"{a['nome']} (OAB: {a['oab']})" for a in advs
            ]

        # Promotor
        m = re.search(r"Prom\.\s*Justi[cç]a\s*:\s*(.+?)(?:\n|$)", self.raw_text, re.IGNORECASE)
        if m:
            self.result.setdefault("court_specific", {})["promotor"] = _norm(m.group(1))

        # Interessado
        interessados = []
        for m in re.finditer(r"Interessad[oa]\s*:\s*(.+?)(?:\n|$)", self.raw_text, re.IGNORECASE):
            interessados.append(_norm(m.group(1)))
        if interessados:
            self.result.setdefault("court_specific", {})["interessados"] = interessados

        # Decisão from D E C I S Ã O section
        dec_text = ""
        idx = text.find("D E C I S Ã O")
        if idx < 0:
            idx = text.find("DECISÃO")
        if idx >= 0:
            dec_text = text[idx:idx + 1500]
        else:
            dec_text = text[-2000:]
        m = re.search(
            r"(?:POR\s+(MAIORIA|UNANIMIDADE),\s*)?(DERAM|NEGARAM)\s+PROVIMENTO(?:\s+PARCIAL)?",
            dec_text,
            re.IGNORECASE,
        )
        if m:
            self._set("decisao", _norm(m.group(0)))

        # Votação detalhe
        vot_detail = []
        if re.search(r"VENCIDO\s+O\s+RELATOR", dec_text, re.IGNORECASE):
            vot_detail.append("vencido_relator")
        m = re.search(r"NOS\s+TERMOS\s+DO\s+VOTO\s+DO\s+(\d+[º°]\s+VOGA?L)", dec_text, re.IGNORECASE)
        if m:
            vot_detail.append(m.group(1))
        m = re.search(r"\b(POR\s+MAIORIA|POR\s+UNANIMIDADE)\b", dec_text, re.IGNORECASE)
        if m:
            self._set("votacao", _norm(m.group(1)))
            vot_detail.append(_norm(m.group(1)))
        if vot_detail:
            self.result.setdefault("court_specific", {})["votacao_detalhe"] = vot_detail

        # Data julgamento — from footer
        m = re.search(r"(?:Campo\s+Grande|Data)[,\s]*(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})", text[-2000:])
        if m:
            dt = _parse_date(m.group(1))
            self._set("data_julgamento", dt)

    def _extract_ementa(self):
        """TJMS ementa is between EMENTA marker and ACÓRDÃO marker."""
        raw = self.raw_text
        m_start = re.search(r"\bEMENTA\b", raw, re.IGNORECASE)
        if m_start:
            rest = raw[m_start.end():]
            m_end = re.search(r"\bA\s+C\s+[ÓO]\s+R\s+D\s+[ÃA]\s+O\b|AC[ÓO]RD[ÃA]O", rest, re.IGNORECASE)
            end_pos = m_end.start() if m_end else min(3000, len(rest))
            ementa = _norm(rest[:end_pos]).lstrip("-– \t")
            if len(ementa) > 80:
                self._set("ementa", ementa, "high")
                return
        # Fallback
        self._set("ementa", self.text[:2000], "low")

    def _extract_court_specific(self):
        pass  # Done inside _extract_common


# ═══════════════════════════════════════════════════════════════════════════════
# TJCE Extractor
# ═══════════════════════════════════════════════════════════════════════════════

class TJCEExtractor(BaseExtractor):
    tribunal = "TJCE"

    def _extract_common(self):
        text = self.text

        # Gabinete
        m = re.search(r"GABINETE\s+DESEMBARGADOR\s+(.+)", text[:500])
        if m:
            self.result.setdefault("court_specific", {})["gabinete"] = _norm(m.group(1))

        # Número processo
        m = re.search(r"Processo:\s*(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})", text[:1000])
        if m:
            self._set("numero_processo", m.group(1))
        else:
            cnj = _extract_cnj(text)
            if cnj:
                self._set("numero_processo", cnj, "medium")

        # Classe
        m = re.search(r"Processo:\s*\d+-\d+\s*-\s*(.+?)(?:\n|$)", text[:1000])
        if m:
            self._set("classe", _norm(m.group(1)))

        # Partes
        partes = {}
        for role, label in [("apelantes", "Apelantes?"), ("apelados", "Apelados?")]:
            pat = re.compile(
                rf"{label}\s*:\s*(.+?)(?:\.\s*(?:Apelad|Corr[eé]u|\.\s*$)|$)",
                re.IGNORECASE | re.DOTALL,
            )
            m = pat.search(self.raw_text[:3000])
            if m:
                names = re.split(r"\s*[,;]\s*|\s+e\s+", _norm(m.group(1)))
                names = [n for n in names if len(n) > 3]
                if names:
                    partes[role] = names
        if partes:
            self._set("partes", partes)

        # Corréu
        m = re.search(r"Corr[eé]u\s*:\s*(.+?)(?:\n|$)", self.raw_text[:3000], re.IGNORECASE)
        if m:
            self.result.setdefault("court_specific", {})["correu"] = _norm(m.group(1))

        # Relator — at the end of the document
        m = re.search(r"([A-ZÀ-Ú][A-ZÀ-Ú\s]{3,40})\s*\n\s*(?:Desembargador|Relator)", self.raw_text[-2000:])
        if m:
            self._set("relator", _norm(m.group(1)))
        if not self.result.get("relator"):
            m = re.search(r"(?:DESEMBARGADOR|Desembargador)\s+(.+)", text[-3000:])
            if m:
                self._set("relator", _norm(m.group(1)), "medium")

        # Decisão — near end
        dec_text = text[-5000:]
        m = re.search(
            r"(?:DERAM|NEGARAM|DERAM\s+PARCIAL\s+PROVIMENTO|NEGARAM\s+PROVIMENTO).*?(?:\.|\n)",
            dec_text,
            re.IGNORECASE,
        )
        if m:
            self._set("decisao", _norm(m.group(0)))

        # Votação
        m = re.search(r"\b(POR\s+MAIORIA|POR\s+UNANIMIDADE|V\.\s*U\.)\b", dec_text, re.IGNORECASE)
        if m:
            self._set("votacao", _norm(m.group(1)))

        # Data julgamento
        m = re.search(r"Fortaleza,\s*(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})", text[-3000:])
        if m:
            dt = _parse_date(m.group(1))
            self._set("data_julgamento", dt)

    def _extract_court_specific(self):
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# TJRS Extractor
# ═══════════════════════════════════════════════════════════════════════════════

class TJRSExtractor(BaseExtractor):
    tribunal = "TJRS"

    def _extract_common(self):
        text = self.text
        raw = self.raw_text

        # Número processo from filename
        m = TJRS_FNAME_RE.search(self.filename)
        if m:
            self._set("numero_processo", m.group("numero"))
            self._set("ano", m.group("ano"))
            self._set("codigo", m.group("codigo"))

        # Classe from first line
        m = re.search(r"^(?:APELA[ÇC][ÃA]O|APELAÇÕES)\s+(\w+)", text, re.IGNORECASE)
        if m:
            self._set("classe", f"Apelação {m.group(1).capitalize()}")

        # Cross-reference with master index for metadata not in body
        if self.master:
            self._cross_reference_master()

        # Preliminares section
        p_start = raw.upper().find("PRELIMINARES")
        if p_start >= 0:
            p_text = raw[p_start:]
            m_end = p_text.upper().find("MÉRITO")
            if m_end > 200:
                p_text = p_text[:m_end]
            preliminares = [s.strip() for s in re.split(r"\n\s*\n", p_text) if len(s.strip()) > 50]
            self.result.setdefault("court_specific", {})["preliminares"] = preliminares[:30]

        # Fatos
        fatos = []
        for m in re.finditer(r"(\d+)[º°]\s+FATO\.\s*([^\.]+)\.?\s*", raw, re.IGNORECASE):
            fato_num = int(m.group(1))
            crime = _norm(m.group(2))
            # Get more context after the match
            ctx_start = m.end()
            next_fato = re.search(r"\d+[º°]\s+FATO\.", raw[ctx_start:ctx_start + 5000], re.IGNORECASE)
            ctx_end = ctx_start + next_fato.start() if next_fato else ctx_start + 2000
            contexto = _norm(raw[ctx_start:ctx_end])[:500]
            fatos.append({"numero": fato_num, "crime": crime, "contexto": contexto})
        if fatos:
            self.result.setdefault("court_specific", {})["fatos"] = fatos
            self.result.setdefault("court_specific", {})["quantidade_fatos"] = len(fatos)

        # Dosimetria
        dos_text = ""
        d_start = raw.upper().find("DOSIMETRIA")
        if d_start >= 0:
            dos_text = raw[d_start:]
        if dos_text:
            reus = []
            for m in re.finditer(
                r"([A-ZÀ-Ú][A-ZÀ-Ú\s]{5,40}(?:DOS\s+SANTOS|DE\s+\w+|DA\s+\w+|J[UÚ]NIOR)?)\."
                r"(.*?)"
                r"(?:(?:fixo|estabele[cç]o|reduz[oi]\s*(?:a|para))\s*(?:a\s*)?(?:pena|san[cç][aã]o)\s*(?:em|para|definitiva)?\s*"
                r"(\d+)\s*(?:a\s*)?(?:ano|ANOS?)(?:[^.]*?(?:(\d+)\s*(?:m[êe]s|MESES?))?[^.]*?(?:(\d+)\s*(?:dia|DIAS?))?)?"
                r"[^.]*?regime\s+inicial\s+(fechado|semiaberto|aberto))",
                dos_text,
                re.IGNORECASE | re.DOTALL,
            ):
                nome = _norm(m.group(1))
                pena_anos = int(m.group(3)) if m.group(3) else 0
                pena_meses = int(m.group(4)) if m.group(4) else 0
                pena_dias = int(m.group(5)) if m.group(5) else 0
                regime = m.group(6).lower() if m.group(6) else ""
                reus.append({
                    "nome": nome,
                    "pena_anos": pena_anos,
                    "pena_meses": pena_meses,
                    "pena_dias": pena_dias,
                    "regime": regime,
                })
            if reus:
                self.result.setdefault("court_specific", {})["dosimetria"] = reus
                self.result.setdefault("court_specific", {})["quantidade_reus"] = len(reus)

        # Decisão — from final paragraph
        m = re.search(
            r"(?:DERAM|NEGARAM|DERAM\s+PARCIAL)\s+PROVIMENTO.*?UN[AÂ]NIME",
            text[-5000:],
            re.IGNORECASE,
        )
        if m:
            self._set("decisao", _norm(m.group(0)), "medium")

        # Votação
        m = re.search(r"\bUN[AÂ]NIME\b", text[-2000:], re.IGNORECASE)
        if m:
            self._set("votacao", "UNANIME")

    def _cross_reference_master(self):
        """Fill missing metadata from master index."""
        if not self.master:
            return
        # Find this document in master lookup by cdacordao or filename
        master_doc = None
        for key in self.master:
            doc = self.master[key]
            rsp = doc.get("raw_source_path", "")
            if self.filename in rsp or os.path.basename(rsp) in self.filename:
                master_doc = doc
                break
        if not master_doc:
            return
        for field in ["relator", "comarca", "data_julgamento", "data_publicacao",
                       "orgao_julgador", "assunto", "classe"]:
            val = master_doc.get(field)
            if val and not self.result.get(field):
                self._set(field, val, "cross_reference")

    def _extract_court_specific(self):
        pass  # Done inside _extract_common

# =============================================================================
# TJPR Extractor
# =============================================================================

class TJPRExtractor(BaseExtractor):
    tribunal = "TJPR"

    def _extract_common(self):
        text = self.text
        raw = self.raw_text

        # 1. Split into cases using "Processo:" as delimiter
        # We'll keep the first part (maybe preamble) but we'll parse each block
        # Since this method is called per file (which contains multiple cases),
        # we'll extract metadata only from the first case, but we could also
        # produce a list of cases. For simplicity, we'll focus on the first case.
        # A more robust approach would be to split and process all, but the
        # current BaseExtractor expects a single document. We'll extract the
        # first occurrence.

        # Find first "Processo:" line and capture the number
        m = re.search(r"Processo:\s*(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})", text)
        if m:
            self._set("numero_processo", m.group(1))
        else:
            cnj = _extract_cnj(text)
            if cnj:
                self._set("numero_processo", cnj, "medium")

        # Relator
        m = re.search(r"Relator:\s*([^\n]+?)(?:\n|$)", text, re.IGNORECASE)
        if m:
            self._set("relator", _norm(m.group(1)))
        else:
            # sometimes "Relator(a):"
            m = re.search(r"Relator\(a\):\s*([^\n]+?)(?:\n|$)", text, re.IGNORECASE)
            if m:
                self._set("relator", _norm(m.group(1)))

        # Órgão Julgador
        m = re.search(r"Orgão\s+Julgador:\s*([^\n]+?)(?:\n|$)", text, re.IGNORECASE)
        if m:
            self._set("orgao_julgador", _norm(m.group(1)))

        # Data de Publicação
        m = re.search(r"Data de Publicação:\s*([\d/]+(?:\s+\d{2}:\d{2}:\d{2})?)", text, re.IGNORECASE)
        if m:
            dt = _parse_date(m.group(1))
            if dt:
                self._set("data_publicacao", dt)
            else:
                # fallback: keep raw
                self._set("data_publicacao", m.group(1).strip(), "medium")

        # Comarca - sometimes appears near the process number
        m = re.search(r"Processo:.*?-\s*([A-Za-zÀ-ÖØ-öø-ÿ\s]+?)(?:\n|$)", text)
        if m:
            comarca = _norm(m.group(1))
            if comarca and not comarca.startswith("Relator"):
                self._set("comarca", comarca)

        # Classe - infer from document context
        m = re.search(r"APELAÇÃO\s+CÍVEL", text, re.IGNORECASE)
        if m:
            self._set("classe", "Apelação Cível")
        else:
            m = re.search(r"APELAÇÃO\s+CRIMINAL", text, re.IGNORECASE)
            if m:
                self._set("classe", "Apelação Criminal")
            else:
                m = re.search(r"AGRAVO\s+DE\s+INSTRUMENTO", text, re.IGNORECASE)
                if m:
                    self._set("classe", "Agravo de Instrumento")

        # Partes - usually appear after "Partes:" or in the header
        partes = {}
        for role, label in [("apelantes", "Apelante"), ("apelados", "Apelado")]:
            pat = re.compile(
                rf"{label}s?:?\s*(.+?)(?:\n\s*(?:Relator|Orgão|Data|Apelad|Ementa|VOTO|DISPOSITIVO))",
                re.IGNORECASE | re.DOTALL,
            )
            m = pat.search(raw[:3000])
            if m:
                names = re.split(r"\s*[,;]\s*|\s+e\s+", _norm(m.group(1)))
                names = [n for n in names if len(n) > 3 and not n.startswith("(")]
                if names:
                    partes[role] = names
        if partes:
            self._set("partes", partes)

        # Decisão / Outcome - look for "Voto" or "Dispositivo"
        # Often the outcome is in the ementa or at the end.
        # We'll rely on the base class outcome extraction.
        pass

    def _extract_ementa(self):
        """Extract ementa from the TJPR document."""
        raw = self.raw_text
        # Look for "Ementa:" or "EMENTA:" marker
        m_start = re.search(r"\bEMENTA\s*:", raw, re.IGNORECASE)
        if not m_start:
            m_start = re.search(r"\bE\s+M\s+E\s+N\s+T\s+A\s*:", raw, re.IGNORECASE)
        if m_start:
            rest = raw[m_start.end():]
            # Stop at next section (VOTO, RELATÓRIO, DISPOSITIVO, etc.)
            m_end = re.search(
                r"\b(VOTO|RELAT[ÓO]RIO|DISPOSITIVO|AC[ÓO]RD[ÃA]O|I+\.?\s*[-–]\s*RELAT)",
                rest,
                re.IGNORECASE,
            )
            end_pos = m_end.start() if m_end else min(4000, len(rest))
            ementa = _norm(rest[:end_pos]).lstrip(":- \t")
            if len(ementa) > 80:
                self._set("ementa", ementa, "high")
                return
        # Fallback: look for a paragraph after "Ementa" (without colon)
        m_start = re.search(r"\bEMENTA\b", raw, re.IGNORECASE)
        if m_start:
            rest = raw[m_start.end():]
            m_end = re.search(r"\b(VOTO|RELAT[ÓO]RIO|DISPOSITIVO|AC[ÓO]RD[ÃA]O)\b", rest, re.IGNORECASE)
            end_pos = m_end.start() if m_end else min(4000, len(rest))
            ementa = _norm(rest[:end_pos]).lstrip(":- \t")
            if len(ementa) > 80:
                self._set("ementa", ementa, "high")
                return
        # Last resort: use base class (first 2000 chars)
        self._set("ementa", self.text[:2000], "low")

    def _extract_court_specific(self):
        # We can extract the votação from the final lines
        m = re.search(r"\b(V\.\s*U\.|UN[ÂA]NIME)\b", self.text[-2000:], re.IGNORECASE)
        if m:
            self._set("votacao", _norm(m.group(1)), "medium")
        # Maybe extract the "Dispositivo" section
        m = re.search(
            r"DISPOSITIVO.*?([\"“][^\"“]*?[A-Z]{2,}[^\"“]*?[\"“])",
            self.text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            self._set("decisao", _norm(m.group(1)), "medium")
        else:
            # fallback: look for the last paragraph with "provimento"
            m = re.search(
                r"(NEGAR\s+PROVIMENTO|DAR\s+PROVIMENTO|PARCIAL\s+PROVIMENTO).*?(?:\n\n|$)",
                self.text[-3000:],
                re.IGNORECASE,
            )
            if m:
                self._set("decisao", _norm(m.group(0)), "medium")


# ═══════════════════════════════════════════════════════════════════════════════
# CLTC Extractor — Tribunal Constitucional de Chile
# ═══════════════════════════════════════════════════════════════════════════════

class CLTCExtractor(BaseExtractor):
    """Spanish-Chilean extractor for TC Chile (*Tribunal Constitucional*) rulings.

    TC sentences follow ``VISTOS`` / considerandos / ``SE RESUELVE`` and use
    Chilean legal vocabulary, so none of the Brazilian Portuguese machinery in
    :class:`BaseExtractor` applies (no ``EMENTA``, no ``ACÓRDÃO``, no CNJ number).

    The scraper already writes a rich ``<file>.metadata.json`` sidecar carrying
    the official ficha fields (competencia, resultado, ministros, doctrina,
    palabras clave, precepto impugnado). That sidecar is authoritative and is
    preferred; the PDF text is used for the full body, the header block and any
    field the sidecar does not provide.
    """

    tribunal = "CLTC"
    tribunal_nombre = "Tribunal Constitucional de Chile"

    # TC preambles open with one of these subject headings.
    MATERIA_KEYWORDS = (
        "REQUERIMIENTO DE INAPLICABILIDAD",
        "INAPLICABILIDAD POR INCONSTITUCIONALIDAD",
        "INAPLICABILIDAD DE PRECEPTO LEGAL",
        "REQUERIMIENTO DE INCONSTITUCIONALIDAD",
        "CUESTIÓN DE INCONSTITUCIONALIDAD",
        "CONTROL PREVENTIVO DE CONSTITUCIONALIDAD",
        "CONTROL DE CONSTITUCIONALIDAD",
        "PROYECTO DE LEY",
        "TRATADO INTERNACIONAL",
        "LEY ORGÁNICA CONSTITUCIONAL",
        "DECRETO CON FUERZA DE LEY",
        "AUTO ACORDADO",
        "RECURSO DE PROTECCIÓN",
        "AMPARO",
    )
    # Marker separating the subject heading from the parties block.
    PARTIES_MARKER_RE = re.compile(
        r"\b(Y\s+OTROS?|Y\s+OTRAS?|EN\s+EL\s+PROCESO|EN\s+LOS\s+AUTOS|"
        r"CONTRA|SOBRE)\b",
        re.IGNORECASE)
    # Legal instruments that terminate a TC Chile subject heading.
    MATERIA_TAIL_RE = re.compile(
        r"\b(?:C[ÓO]DIGO(?:\s+DE\s+[A-ZÁÉÍÓÚÑ]+)?|LEY(?:\s+N[°º]\s*[\d\.]+)?|"
        r"CONSTITUCI[ÓO]N(?:\s+POL[ÍI]TICA)?|DECRETO(?:\s+(?:LEY|CON\s+FUERZA\s+DE\s+LEY))?|"
        r"TRATADO(?:\s+INTERNACIONAL)?|AUTO\s+ACORDADO|REGLAMENTO|ESTATUTO|"
        r"ORDENANZA|CONVENIO|CIVIL|PENAL)\b",
        re.IGNORECASE)

    # ── sidecar accessors ───────────────────────────────────────────────────

    @property
    def _ficha(self) -> Dict[str, Any]:
        """The nested ``metadata`` object (official ficha fields)."""
        inner = self.sidecar.get("metadata")
        return inner if isinstance(inner, dict) else {}

    def _sc(self, *keys: str) -> Any:
        """First non-empty value among *keys* across sidecar and nested ficha."""
        for key in keys:
            for src in (self.sidecar, self._ficha):
                val = src.get(key)
                if val not in (None, "", [], {}):
                    return val
        return None

    @staticmethod
    def _split_pipe(value: Any) -> List[str]:
        """Split a sidecar multi-value field (``"A | B | C"``) into a list."""
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if str(v).strip()]
        return [part.strip() for part in str(value).split("|") if part.strip()]

    # ── header helpers ──────────────────────────────────────────────────────

    def _cltc_header(self) -> str:
        """Return the normalized front matter between the date banner and ``VISTOS``."""
        m = CLTC_VISTOS_RE.search(self.raw_text)
        if not m:
            return ""
        head = self.raw_text[:m.start()]
        m_date = re.search(r"\[[^\]]*\d{4}[^\]]*\]", head)
        if m_date:
            head = head[m_date.end():]
        head = _norm(head.replace("_", " "))
        return head[:1500]

    def _cltc_rol(self) -> Optional[re.Match]:
        return CLTC_ROL_RE.search(self.text)

    def _operative_text(self) -> str:
        """Return only the operative part (``SE RESUELVE`` → dissent/signatures).

        Scoping to this slice prevents body prose and, crucially, a dissenting
        vote ("estuvieron por acoger el libelo") from being read as the holding.
        """
        m = CLTC_RESUELVE_RE.search(self.raw_text)
        if not m:
            return ""
        tail = self.raw_text[m.end():]
        m_stop = CLTC_DISIDENCIA_RE.search(tail)
        if m_stop and m_stop.start() > 20:
            tail = tail[:m_stop.start()]
        return tail

    def _cltc_holdings(self) -> List[str]:
        """Roman-numbered holdings listed under ``SE RESUELVE``."""
        tail = self._operative_text()
        if not tail:
            return []
        holdings = []
        for m_h in CLTC_HOLDING_RE.finditer(tail):
            texto = _norm(m_h.group("texto"))
            if len(texto) >= 12:
                holdings.append(f"{_norm(m_h.group('num')).upper()}. {texto}")
        return holdings[:10]

    def _cltc_se_resuelve_text(self) -> Optional[str]:
        texto = _norm(self._operative_text())
        return texto[:4000] if len(texto) > 40 else None

    # Role scaffolding that prefixes each name in the closing "integrada por"
    # sentence ("su Presidenta, Ministra señora X, y por sus Ministros señor Y").
    ROLE_PREFIX_RE = re.compile(
        r"^(?:y|e|por|sus|su|el|la|los|las|Excmo|Ministr[oa]s?|President[ae]|"
        r"se[ñn]or(?:a|es)?)\b[\s,]*",
        re.IGNORECASE)

    def _cltc_ministerios(self) -> Tuple[List[str], List[str]]:
        """Return ``(ministros, ministros_disidencia)`` from the closing block."""
        m = CLTC_INTEGRACION_RE.search(self.raw_text)
        if not m:
            return [], []
        body = _norm(m.group("body"))
        ministros: List[str] = []
        seen = set()
        for part in re.split(r"[,;]|\by\b", body):
            name = part.strip()
            prev = None
            while prev != name:  # strip stacked role words
                prev = name
                name = self.ROLE_PREFIX_RE.sub("", name).strip(" ,.-")
            if len(name) < 8 or len(name.split()) < 2:
                continue
            if not re.match(r"^[A-ZÁÉÍÓÚÑÜ]", name):
                continue
            name = _titlecase_name(name)
            key = name.lower()
            if key not in seen:
                seen.add(key)
                ministros.append(name)
        disidencia = self._split_pipe(self._sc("tc_Voto disidencia", "Voto disidencia"))
        return ministros[:12], disidencia

    # ── BaseExtractor overrides ─────────────────────────────────────────────

    def _extract_common(self):
        m_fname = CLTC_FNAME_RE.search(self.filename)
        folio = self._sc("folio", "numero_processo") or (
            m_fname.group("folio") if m_fname else None)
        if folio:
            self._set("numero_processo", str(folio))
            self._set("pdf_folio", str(folio))

        # Date — sidecar first (exact), PDF banner as fallback.
        fecha = _parse_date_es(
            self._sc("fecha", "data_julgamento", "fecha_sentencia", "tc_fecha_sentencia")
        )
        if not fecha:
            m_date = re.search(r"\[([^\]]*\d{4}[^\]]*)\]", self.raw_text)
            if m_date:
                fecha = _parse_date_es(m_date.group(1))
        if not fecha and m_fname and m_fname.group("fecha"):
            fecha = m_fname.group("fecha")
        if fecha:
            self._set("data_julgamento", fecha, "high")

        # ROL (case number + year + competence sigla), e.g. "16.622-2025 INA"
        rol_match = self._cltc_rol()
        if rol_match:
            self._set("rol", _norm(rol_match.group(0)))
            numero = rol_match.group("numero").replace(".", "")
            ano = rol_match.group("ano")
            if ano and len(ano) == 2:
                ano = f"20{ano}"
            if ano:
                self._set("ano", ano)
            if rol_match.group("sigla"):
                self._set("codigo", rol_match.group("sigla").upper())
            # Last-resort folio: the download key (folio) equals the ROL number
            # with separators removed. This matters when neither the sidecar nor
            # the CLTC_<fecha>_<folio>.pdf filename is available — e.g. a PDF
            # uploaded through the API, which is stored under a UUID filename.
            if numero and not folio:
                self._set("numero_processo", numero)
                self._set("pdf_folio", numero)
        # The official ficha ships the canonical competence code (e.g. "06a-INA").
        codigo = self._sc("codigo", "template_codigo", "nombre")
        if codigo:
            self._set("codigo", str(codigo), "high")

        # Competence / case class — the official ficha template is authoritative.
        competencia = self._sc("template", "classe_assunto", "classe", "tipo_processo")
        if not competencia:
            head_up = self._cltc_header().upper()
            for kw in self.MATERIA_KEYWORDS:
                if kw in head_up:
                    competencia = kw.title()
                    break
        if competencia:
            self._set("classe", str(competencia), "high" if self._ficha.get("template") else "medium")
            self._set("competencia", str(competencia), "high" if self._ficha.get("template") else "medium")

        # Rapporteur ("relator") — redactor of the majority opinion.
        relator = self._sc("tc_Redactor voto mayoría", "relator", "redactor")
        if not relator:
            m_red = CLTC_REDACTOR_RE.search(self.raw_text)
            if m_red:
                relator = _norm(m_red.group("nombre"))
        if relator:
            self._set("relator", _titlecase_name(str(relator)), "high")

        # Court / chamber
        orgao = self._sc("tribunal", "orgao_julgador") or self.tribunal_nombre
        sala = self._sc("sala")
        if sala:
            orgao = f"{orgao} - {sala}"
        self._set("orgao_julgador", str(orgao))

        # Outcome (raw Spanish + normalized label)
        resultado = self._sc("tc_Resultado", "resultado")
        if resultado:
            self._set("decisao", _norm(str(resultado)), "high")

        # Parties from the preamble (best effort; PyPDF2 flattens the block).
        header = self._cltc_header()
        if header:
            self._set("encabezado", header, "medium")
            upper = header.upper()
            start = -1
            for kw in self.MATERIA_KEYWORDS:
                idx = upper.find(kw)
                if idx >= 0 and (start < 0 or idx < start):
                    start = idx
            region = header[start:] if start >= 0 else header
            # Scope the search for the closing legal instrument to the part
            # before the parties block, so a parenthetical such as
            # "ROL N° 9947-2025 (CIVIL)" cannot be mistaken for it.
            m_marker = self.PARTIES_MARKER_RE.search(region)
            limit = m_marker.start() if m_marker else len(region)
            cut = None
            for m_tail in self.MATERIA_TAIL_RE.finditer(region[:limit]):
                cut = m_tail.end()
            if cut is None and m_marker:
                cut = m_marker.start()
            if cut is not None and cut >= 15:
                materia = _norm(region[:cut]).strip(" ,.-")
                partes = _norm(region[cut:]).strip(" ,.-")
                partes = re.sub(r"^(?:Y|E)\s+", "", partes).strip(" ,.-")
                if len(materia) >= 15:
                    self._set("materia", materia, "medium")
                if len(partes) >= 10:
                    self._set("partes", [partes], "medium")
            elif len(region) >= 15:
                self._set("materia", _norm(region), "low")

        # Voting alignment
        voto_mayoria = self._split_pipe(self._sc("tc_Voto mayoría"))
        voto_disidencia = self._split_pipe(self._sc("tc_Voto disidencia"))
        if voto_disidencia:
            self._set("votacao", "MAYORÍA / CON DISIDENCIA", "high")
        elif voto_mayoria or "UNÁNIME" in self.text.upper():
            self._set("votacao", "UNÁNIME", "medium")
        # Free-text fallback when the sidecar is missing
        if not voto_disidencia and CLTC_DISIDENCIA_RE.search(self.raw_text):
            self._set("votacao", "MAYORÍA / CON DISIDENCIA", "low")

    def _extract_ementa(self):
        """TC Chile 'doctrina': sidecar ``tc_Doctrina``, else the VISTOS preamble."""
        doctrina = self._sc("tc_Doctrina", "ementa_trecho", "ementa")
        if doctrina and len(str(doctrina)) > 60:
            self._set("ementa", _norm(str(doctrina)), "high")
            return
        m_start = CLTC_VISTOS_RE.search(self.raw_text)
        if m_start:
            rest = self.raw_text[m_start.end():]
            m_end = CLTC_RESUELVE_RE.search(rest) or CLTC_CONSIDERANDO_RE.search(rest)
            end = m_end.start() if m_end else min(3000, len(rest))
            ementa = _norm(rest[:end])
            if len(ementa) > 120:
                self._set("ementa", ementa[:6000], "medium")
                return
        self._set("ementa", _norm(self.raw_text)[:2000], "low")

    def _extract_outcomes(self):
        """Normalized outcome labels.

        The official ficha ``Resultado`` field is authoritative and is used on
        its own when present; only in its absence do we scan the operative part
        (never the body, so a dissent is not mistaken for the holding).
        """
        canonical = {
            "acoge": "acoge",
            "acoge parcial": "acoge_parcial",
            "acoge parcialmente": "acoge_parcial",
            "rechaza": "rechaza",
            "rechaza parcial": "rechaza_parcial",
            "rechaza parcialmente": "rechaza_parcial",
            "empate de votos": "empate_votos",
            "empate": "empate_votos",
            "inadmisible": "inadmisible",
            "declara inadmisible": "inadmisible",
            "no se pronuncia": "no_conoce",
        }
        raw = _norm(str(self._sc("tc_Resultado", "resultado") or "")).lower()
        outcomes: List[str] = []
        if raw in canonical:
            outcomes.append(canonical[raw])
        else:
            operative = self._operative_text()
            if operative:
                for label, pat in CLTC_OUTCOME_PATTERNS:
                    if label not in outcomes and pat.search(operative):
                        outcomes.append(label)
            # De-duplicate the generic form when a "_parcial" variant matched.
            if "acoge_parcial" in outcomes and "acoge" in outcomes:
                outcomes.remove("acoge")
            if "rechaza_parcial" in outcomes and "rechaza" in outcomes:
                outcomes.remove("rechaza")
        self._set("outcome", outcomes, "high" if outcomes else "low")

    def _extract_legislacao(self):
        found: List[str] = []
        seen = set()

        def _add(item: str) -> None:
            item = _norm(str(item)).strip(" ,.;:-")
            # Drop vestigial fragments ("ley .", "326", "segundo").
            if len(item) < 6 or not re.search(r"[A-Za-zÁÉÍÓÚÑ]{3}", item):
                return
            key = item.lower()
            if key not in seen:
                found.append(item)
                seen.add(key)

        # Sidecar: impugned provision, rendered as one readable citation.
        impugnado = self._split_pipe(
            self._sc("tc_Precepto legal impugnado", "Precepto legal impugnado"))
        if impugnado:
            cuerpo = impugnado[0]
            numeros = [p for p in impugnado[1:] if re.fullmatch(r"\d+", p)]
            incisos = [p for p in impugnado[1:] if not re.fullmatch(r"\d+", p)]
            cita = f"{cuerpo}, artículo {', '.join(numeros)}" if numeros else cuerpo
            if incisos:
                cita += f", inciso {', '.join(incisos)}"
            _add(cita)
        # Sidecar: constitutional articles invoked.
        for raw in (self._sc("tc_Artículo de la Constitución"),
                    self._sc("Artículo de la Constitución")):
            for item in self._split_pipe(raw):
                _add(item)
        # Free-text citations from the PDF body.
        for m in CLTC_LEGISLACAO_RE.finditer(self.text):
            _add(m.group(0))
            if len(found) >= 25:
                break
        self._set("legislacao_citada", found[:25], "high" if found else "low")

    def _extract_assuntos(self):
        found: List[str] = []
        seen = set()
        # Official ficha keywords first — authoritative.
        for raw in (self._sc("tc_Palabras clave"), self._sc("Palabras clave")):
            for item in self._split_pipe(raw):
                if item.lower() not in seen:
                    found.append(item)
                    seen.add(item.lower())
        # Constitutional-right keywords detected in the body.
        for kw in _classify(self.text, CLTC_ASSUNTOS):
            if kw.lower() not in seen:
                found.append(kw)
                seen.add(kw.lower())
        self._set("assuntos", found[:20], "high" if found else "low")

    def _extract_court_specific(self):
        specific: Dict[str, Any] = {}

        folio = self._sc("folio", "numero_processo")
        if folio:
            specific["folio"] = str(folio)
        for key, out in (
            ("ficha_id", "ficha_id"), ("template", "template"),
            ("template_codigo", "template_codigo"), ("estado", "estado"),
            ("fecha_sentencia", "fecha_sentencia"),
            ("tc_Resultado", "resultado"), ("resultado", "resultado"),
            ("tc_Redactor voto mayoría", "redactor_mayoria"),
            ("tc_Redactor disidencia", "redactor_disidencia"),
            ("tc_Tipo de resolución", "tipo_resolucion"),
            ("sala", "sala"), ("search_terms", "search_terms"),
            ("url_detalle", "url_detalle"), ("inteiro_url", "inteiro_url"),
            ("es_reservada", "es_reservada"),
        ):
            val = self._sc(key)
            if val not in (None, "", [], {}):
                specific.setdefault(out, val)

        for key, out in (
            ("tc_Voto mayoría", "ministros_mayoria"),
            ("tc_Voto disidencia", "ministros_disidencia"),
            ("tc_Artículo de la Constitución", "articulos_constitucion"),
            ("tc_Palabras clave", "palabras_clave"),
            ("tc_Precepto legal impugnado", "preceptos_impugnados"),
            ("tc_Sentencias relacionadas", "sentencias_relacionadas"),
            ("tc_Gestión pendiente", "gestion_pendiente"),
            ("tc_Doctrina", "doctrina"),
        ):
            items = self._split_pipe(self._sc(key))
            if items:
                specific.setdefault(out, items)

        # Derived from the PDF body
        ministros, disidencia = self._cltc_ministerios()
        if ministros and "ministros" not in specific:
            specific["ministros"] = ministros
        if disidencia and "ministros_disidencia" not in specific:
            specific["ministros_disidencia"] = disidencia

        holdings = self._cltc_holdings()
        if holdings:
            specific["resuelvo"] = holdings
        se_resuelve = self._cltc_se_resuelve_text()
        if se_resuelve:
            specific["se_resuelve_texto"] = se_resuelve

        m_verif = re.search(r"\b([0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})\b",
                            self.raw_text)
        if m_verif:
            specific["codigo_verificacion"] = m_verif.group(1)

        specific["pais"] = "Chile"
        if specific:
            self.result.setdefault("court_specific", {}).update(specific)

    # ── convenience ─────────────────────────────────────────────────────────

    def extract_all(self) -> dict:
        result = super().extract_all()
        result["tribunal_pais"] = "Chile"
        result["tribunal_nombre"] = self.tribunal_nombre
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Extractor registry
# ═══════════════════════════════════════════════════════════════════════════════

EXTRACTORS: Dict[str, type] = {
    "TJSP": TJSPExtractor,
    "TJMS": TJMSExtractor,
    "TJCE": TJCEExtractor,
    "TJRS": TJRSExtractor,
    "TJPR": TJPRExtractor,
    "CLTC": CLTCExtractor,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def _find_files_for_courts(
    base_dir: str,
    courts: List[str],
    master_lookup_cd: dict,
    master_lookup_rsp: dict,
) -> Dict[str, List[str]]:
    """Find files in base_dir/PDF and base_dir/docx, mapping to courts."""
    base = Path(base_dir)
    pdf_dir = base / "PDF"
    docx_dir = base / "docx"

    court_files: Dict[str, List[str]] = {c: [] for c in courts}

    # Scan PDFs
    if pdf_dir.exists() and any(c in courts for c in ["TJSP", "TJMS", "TJCE"]):
        for f in sorted(pdf_dir.glob("*.pdf")):
            cd_match = ESAJ_FNAME_RE.search(f.name)
            if cd_match:
                cdacordao = cd_match.group("cdacordao")
                master_doc = master_lookup_cd.get(cdacordao)
                if master_doc:
                    trib = master_doc.get("tribunal", "")
                    if trib in courts:
                        court_files[trib].append(str(f))
                        continue
            # Fallback: try raw_source_path lookup
            master_doc = master_lookup_rsp.get(f.name)
            if master_doc:
                trib = master_doc.get("tribunal", "")
                if trib in courts:
                    court_files[trib].append(str(f))

    # Scan DOCX (always TJRS)
    if docx_dir.exists() and "TJRS" in courts:
        for f in sorted(docx_dir.glob("*.docx")):
            court_files["TJRS"].append(str(f))

    # Scan CLTC downloads — TC Chile files are named CLTC_[YYYY-MM-DD_]folio.pdf
    # and live under jurisprudence_downloads/<agent>/<folder>/<timestamp>/.
    if "CLTC" in courts:
        seen: set = set()
        for pattern in ("CLTC_*.pdf", "**/CLTC_*.pdf", "*.pdf", "**/*.pdf"):
            for f in sorted(base.glob(pattern)):
                if CLTC_SIDECAR_RE.match(f.name) or CLTC_FNAME_RE.match(f.name):
                    if str(f) not in seen:
                        seen.add(str(f))
                        court_files["CLTC"].append(str(f))

    return court_files
    # ═══════════════════════════════════════════════════════════════════════════════
# TJPR Multi‑Case Logic (new)
# ═══════════════════════════════════════════════════════════════════════════════

def _process_tjpr_multiple(text: str, filename: str, master_lookup_rsp: dict) -> List[dict]:
    """
    Split a TJPR PDF into individual cases by "Processo:" and extract each.

    The split is anchored on the CNJ process-number format, which is the most
    reliable marker of a new judgment. We allow minor cosmetic variations
    (extra spaces, optional dash/underscore, case-insensitive label) so that
    multi-case PDFs are not merged into a single block.
    """
    # Anchor on the canonical CNJ number. Allow optional spaces inside the
    # number and tolerate "Processo" / "PROCESSO" / "Processo nº".
    cnj = r"\d{7}\s*[-_ ]?\s*\d{2}\s*[-_ ]?\s*\.\s*\d{4}\s*[-_ ]?\s*\.\s*\d\s*[-_ ]?\s*\.\s*\d{2}\s*[-_ ]?\s*\.\s*\d{4}"
    pattern = rf"(?i)(?=Processo\s*:?\s*(?:n[º°o]\.?\s*)?{cnj})"
    case_blocks = re.split(pattern, text)
    results = []
    for block in case_blocks:
        block = block.strip()
        if not block or len(block) < 50:
            continue
        extractor = TJPRExtractor(block, filename, master_lookup_rsp)
        result = extractor.extract_all()
        if result:
            results.append(result)
    return results


def process_file(filepath: str, tribunal: str, master_lookup_rsp: dict) -> List[dict]:
    """Process a single file: extract text, run court extractor, return list of results."""
    ext = os.path.splitext(filepath)[1].lower()
    fname = os.path.basename(filepath)

    # Extract text
    if ext == ".pdf":
        text = extract_pdf_text(filepath)
    elif ext == ".docx":
        text = extract_docx_text(filepath)
    elif ext == ".doc":
        text = extract_doc_text(filepath)
    elif ext == ".html" or ext == ".htm":
        text = extract_html_text(filepath)
    else:
        print(f"  SKIP {fname}: unsupported format {ext}")
        return []

    if not text or len(text) < 100:
        print(f"  SKIP {fname}: text too short ({len(text)} chars)")
        return []

    # Run extractor
    extractor_cls = EXTRACTORS.get(tribunal)
    if not extractor_cls:
        print(f"  SKIP {fname}: no extractor for {tribunal}")
        return []

    # ---- TJPR multi‑case handling ----
    if tribunal == "TJPR":
        return _process_tjpr_multiple(text, fname, master_lookup_rsp)
    # ---- Normal single‑case ----
    # Scrapers write a ``<file>.metadata.json`` sidecar with authoritative
    # structured metadata; pass it through so extractors can prefer it over
    # parsing free text (essential for TC Chile / CLTC).
    sidecar = _load_sidecar(filepath)
    extractor = extractor_cls(text, fname, master_lookup_rsp, sidecar=sidecar)
    result = extractor.extract_all()
    return [result] if result else []


def main():
    parser = argparse.ArgumentParser(description="Mechanical Jurisprudence Document Extractor")
    parser.add_argument("--courts", nargs="+", default=["TJSP", "TJMS", "TJCE", "TJRS"],
                        choices=["TJSP", "TJMS", "TJCE", "TJRS", "TJPR", "CLTC"],
                        help="Courts to process")
    parser.add_argument("--max-per-court", type=int, default=None,
                        help="Max documents per court (for testing)")
    parser.add_argument("--input-dir", default="/home/disconzi1986_gmail_com/juris-search-VPS/court_samples/jurisprudence-documents",
                        help="Directory with PDF/ and docx/ subdirectories")
    parser.add_argument("--output-dir", 
                        default=os.environ.get(
                            "JURIS_SEARCH_EXTRACTIONS_DIR",
                            os.path.join(os.path.dirname(os.path.abspath(__file__)), "extracted_documents")
                        ),
                        help="Output directory for extracted JSONs")
    parser.add_argument("--master-index", default="/home/disconzi1986_gmail_com/juris-search-VPS/master_index/master_index.json",
                        help="Path to master_index.json for cross-referencing")
    args = parser.parse_args()

    # Load master index
    master = _load_master_index(args.master_index)
    cd_lookup, rsp_lookup = _build_master_lookup(master)

    # Find files
    print(f"Scanning {args.input_dir} ...")
    court_files = _find_files_for_courts(args.input_dir, args.courts, cd_lookup, rsp_lookup)
    for trib, files in court_files.items():
        print(f"  {trib}: {len(files)} candidates")

    # Limit per court
    if args.max_per_court:
        for trib in court_files:
            court_files[trib] = court_files[trib][:args.max_per_court]

    # Process
    os.makedirs(args.output_dir, exist_ok=True)
    total = 0
    field_counts = Counter()

    for tribunal in args.courts:
        files = court_files.get(tribunal, [])
        if not files:
            print(f"\n{tribunal}: no files found")
            continue
        print(f"\n{'='*60}")
        print(f"{tribunal}: processing {len(files)} files")
        print(f"{'='*60}")

        for i, filepath in enumerate(files, 1):
            fname = os.path.basename(filepath)
            print(f"  [{i}/{len(files)}] {fname} ...", end=" ", flush=True)

            # process_file now returns a LIST of results
            results = process_file(filepath, tribunal, rsp_lookup)
            if not results:
                print("FAILED")
                continue

            # Write one JSON per case extracted
            for idx, result in enumerate(results):
                # Build a unique doc_id from the process number or fallback
                proc = result.get("numero_processo") or result.get("cnj_numero") or f"{fname}_case{idx+1}"
                safe_id = re.sub(r"[^\w\-\.]", "_", proc)[:120]
                out_path = os.path.join(args.output_dir, f"{tribunal}_{safe_id}.json")
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)

                # Count extracted fields for summary
                extracted = [k for k, v in result.items()
                             if k not in ("schema_version", "extracted_at", "source_file",
                                          "tribunal", "texto_inteiro", "texto_length",
                                          "extraction_confidence", "court_specific")
                             and v is not None and v != [] and v != ""]
                for f in extracted:
                    field_counts[f] += 1

                # Print status per case
                conf_items = [f"{k}={v}" for k, v in result.get("extraction_confidence", {}).items()
                              if v == "low"]
                conf_str = f"  LOW_CONF: {', '.join(conf_items[:5])}" if conf_items else ""
                case_label = f"case {idx+1}" if len(results) > 1 else ""
                print(f"  {case_label} OK ({len(extracted)} fields){conf_str}")

                total += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY: {total} documents processed")
    print(f"Output: {args.output_dir}")
    print(f"\nField extraction rates:")
    for field, count in field_counts.most_common():
        pct = count / max(total, 1) * 100
        print(f"  {field}: {count}/{total} ({pct:.0f}%)")
# ═══════════════════════════════════════════════════════════════════════════════
# Automation API — callable from post-download chain
# ═══════════════════════════════════════════════════════════════════════════════

import uuid as _uuid
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

_QDRANT_API_BASE = os.environ.get("JURIS_SEARCH_QDRANT_API", "http://localhost:8066")
_QDRANT_COLLECTION = os.environ.get("JURIS_SEARCH_QDRANT_COLLECTION", "juris_br_v1")
_EXTRACTIONS_DIR = os.environ.get(
    "JURIS_SEARCH_EXTRACTIONS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "extracted_documents"),
)


def _doc_uuid(doc_id: str) -> str:
    return str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"juris-search:{doc_id}"))


def _http_post_json(url: str, payload: dict, timeout: int = 120) -> Tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        try:
            return e.code, json.loads(body) if body else {"detail": str(e)}
        except json.JSONDecodeError:
            return e.code, {"detail": body[:500]}


def _build_embedding_text(doc: dict) -> str:
    """Compose text blob for semantic embedding."""
    parts = [f"Tribunal: {doc.get('tribunal') or 'N/D'}"]
    proc = doc.get("numero_processo") or doc.get("cnj_numero") or "N/D"
    parts.append(f"Processo: {proc}")
    if doc.get("classe"):
        parts.append(f"Classe: {doc['classe']}")
    if doc.get("relator"):
        parts.append(f"Relator: {doc['relator']}")
    if doc.get("orgao_julgador"):
        parts.append(f"Orgao julgador: {doc['orgao_julgador']}")
    if doc.get("comarca"):
        parts.append(f"Comarca: {doc['comarca']}")
    if doc.get("data_julgamento"):
        parts.append(f"Julgado em: {doc['data_julgamento']}")
    outcome = doc.get("outcome")
    if outcome:
        parts.append(f"Resultado: {', '.join(outcome) if isinstance(outcome, list) else outcome}")
    assuntos = doc.get("assuntos")
    if assuntos:
        parts.append(f"Assuntos: {', '.join(assuntos) if isinstance(assuntos, list) else assuntos}")
    header = " | ".join(parts)
    body_parts = []
    if doc.get("ementa"):
        body_parts.append(doc["ementa"])
    if doc.get("decisao"):
        body_parts.append(doc["decisao"])
    legislacao = doc.get("legislacao_citada")
    if legislacao:
        body_parts.append("Legislacao: " + (", ".join(legislacao) if isinstance(legislacao, list) else legislacao))
    body = "\n\n".join(body_parts) if body_parts else ""
    return f"{header}\n\n{body}" if body else header


def _load_master_lookup() -> dict:
    """Load master_index.json and build rsp_lookup for extractor context."""
    master_path = Path(
        os.environ.get(
            "JURIS_SEARCH_MASTER_INDEX",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "master_index", "master_index.json")
        )
    )
    if not master_path.is_file():
        return {}
    try:
        master = json.loads(master_path.read_text(encoding="utf-8"))
        _, rsp = _build_master_lookup(master)
        return rsp
    except Exception:
        return {}


def extract_file(file_path: str, tribunal: str) -> Optional[dict]:
    """
    Extract structured fields from a single downloaded document.

    For TJPR files that may contain multiple cases, this will write one JSON
    file per case and return the first extracted document.

    Args:
        file_path: Path to the .pdf or .docx file.
        tribunal: One of TJSP, TJMS, TJCE, TJRS, TJPR.

    Returns:
        Extracted document dict (first one), or None on failure.
    """
    master_lookup = _load_master_lookup()
    results = process_file(file_path, tribunal, master_lookup)   # process_file returns List[dict]
    if not results:
        return None

    # Write each result to a separate JSON file
    EXTRACTIONS_DIR = Path(_EXTRACTIONS_DIR)
    EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    fname = os.path.basename(file_path)
    for idx, result in enumerate(results):
        proc = result.get("numero_processo") or result.get("cnj_numero") or f"{fname}_case{idx+1}"
        safe_id = re.sub(r"[^\w\-\.]", "_", proc)[:120]
        out_path = EXTRACTIONS_DIR / f"{tribunal}_{safe_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[extract] OK {fname} case {idx+1} → {out_path.name}")

    return results[0]


def ingest_extracted_to_qdrant(
    doc: dict,
    qdrant_api: str = _QDRANT_API_BASE,
    collection: str = _QDRANT_COLLECTION,
) -> Dict[str, Any]:
    """Ingest a single extracted document into Qdrant."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import ingest_to_qdrant as _ingest
        return _ingest.ingest_single(doc, collection=collection, api_base=qdrant_api)
    except Exception as exc:
        return {"ok": False, "error": f"import failed: {exc}"}


# ═══════════════════════════════════════════════════════════════════════════════
# Programmatic API — importable from other modules
# ═══════════════════════════════════════════════════════════════════════════════

EXTRACTIONS_DIR = Path(_EXTRACTIONS_DIR)
MASTER_INDEX_PATH = Path(
    os.environ.get(
        "JURIS_SEARCH_MASTER_INDEX",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "master_index", "master_index.json")
    )
)
QDRANT_API_DEFAULT = "http://localhost:8114"
QDRANT_COLLECTION = "juris_br_v1"


def extract_and_ingest(filepath: str, tribunal: str) -> Dict[str, Any]:
    """
    Combined: extract structured fields + ingest to Qdrant.
    Called by routes_download._auto_extract_and_ingest().

    process_file() always returns a list of case dicts (one entry per judgment,
    even for single-case documents). We ingest each case individually, deriving
    the process number from each dict so multi-case PDFs land as distinct points.
    Returns {"ok": bool, "proc": str, "error": str}.
    """
    extracted = extract_file(filepath, tribunal)
    if extracted is None:
        return {"ok": False, "proc": os.path.basename(filepath), "error": "extraction failed"}

    cases = extracted if isinstance(extracted, list) else [extracted]
    if not cases:
        return {"ok": False, "proc": os.path.basename(filepath), "error": "no cases extracted"}

    ingested = 0
    first_proc = None
    last_error = None
    for case in cases:
        if not isinstance(case, dict):
            continue
        proc = case.get("numero_processo") or os.path.basename(filepath)
        if first_proc is None:
            first_proc = proc
        result = ingest_extracted_to_qdrant(case)
        if result.get("ok"):
            ingested += 1
        else:
            last_error = result.get("error", "unknown")

    if ingested:
        return {"ok": True, "proc": first_proc or os.path.basename(filepath), "ingested": ingested}
    return {
        "ok": False,
        "proc": first_proc or os.path.basename(filepath),
        "error": last_error or "ingestion failed",
    }


def _load_master_lookup() -> dict:
    """Load master_index.json and build rsp_lookup for extractor context."""
    if not MASTER_INDEX_PATH.is_file():
        return {}
    try:
        master = json.loads(MASTER_INDEX_PATH.read_text(encoding="utf-8"))
        _, rsp = _build_master_lookup(master)
        return rsp
    except Exception:
        return {}


def extract_file(filepath: str, tribunal: str) -> Optional[Union[dict, list]]:
    """
    Extract structured fields from a single downloaded document.
    Writes each case to extracted_documents/ and returns the list of result dicts
    (process_file() always returns a list — one entry per judgment).
    Returns None on failure.
    """
    master_lookup = _load_master_lookup()
    result = process_file(filepath, tribunal, master_lookup)
    if result is None:
        return None

    # Write output: one JSON per case so multi-case PDFs don't collide in a single
    # list file and the master indexer can enumerate each judgment individually.
    EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    fname = os.path.basename(filepath)
    doc_id = os.path.splitext(fname)[0]
    cases = result if isinstance(result, list) else [result]
    written = []
    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        proc = case.get("numero_processo") or case.get("cnj_numero") or f"{doc_id}_{idx}"
        safe_proc = re.sub(r"[^0-9A-Za-z._-]", "_", str(proc))
        out_path = EXTRACTIONS_DIR / f"{tribunal}_{safe_proc}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(case, f, ensure_ascii=False, indent=2)
        written.append(case)

    return written if written else (result if isinstance(result, list) else [result])


if __name__ == "__main__":
    main()
