"""Court configuration and resolver for juris-search.

Supports all 27 Brazilian Tribunais de Justiça (TJRS–TJTO), plus STF.
e-SAJ courts (22) use the shared generic scraper in _shared.esaj_scrapers.
Custom-portal courts (TJRS, TJMG, TJRJ) have dedicated scrapers.
"""

import os
from typing import Optional, List

from modules.config import DEFAULT_COURT

SUPPORTED_COURTS = {
    # ── Custom-portal courts (dedicated scrapers) ─────────────────────────
    "TJRS": {
        "name": "TJRS",
        "scraper_module": "tjrs_scraper",
        "scraper_class": "TJRSJurisprudenciaScraper",
    },
    "TJSP": {
        "name": "TJSP",
        "scraper_module": "tjsp_scraper",
        "scraper_class": "TJSPJurisprudenciaScraper",
    },
    "TJMG": {
        "name": "TJMG",
        "scraper_module": "tjmg_scraper",
        "scraper_class": "TJMGJurisprudenciaScraper",
    },
    "TJRJ": {
        "name": "TJRJ",
        "scraper_module": "tjrj_scraper",
        "scraper_class": "TJRJJurisprudenciaScraper",
    },
    "STF": {
        "name": "STF",
        "scraper_module": "stf_scraper",
        "scraper_class": "STFJurisprudenciaScraper",
    },

    # ── Chile ─────────────────────────────────────────────────────────────
    "CL": {
        "name": "CL",
        "scraper_module": "chile_scraper",
        "scraper_class": "ChileJurisprudenciaScraper",
    },

    # ── e-SAJ courts (shared generic scraper via _shared.esaj_scrapers) ───
    # South
    "TJSC": {
        "name": "TJSC",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJSCJurisprudenciaScraper",
    },
    "TJPR": {
        "name": "TJPR",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJPRJurisprudenciaScraper",
    },
    # Southeast
    "TJES": {
        "name": "TJES",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJESJurisprudenciaScraper",
    },
    # Northeast
    "TJBA": {
        "name": "TJBA",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJBAJurisprudenciaScraper",
    },
    "TJPE": {
        "name": "TJPE",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJPEJurisprudenciaScraper",
    },
    "TJCE": {
        "name": "TJCE",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJCEJurisprudenciaScraper",
    },
    "TJMA": {
        "name": "TJMA",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJMAJurisprudenciaScraper",
    },
    "TJPB": {
        "name": "TJPB",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJPBJurisprudenciaScraper",
    },
    "TJRN": {
        "name": "TJRN",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJRNJurisprudenciaScraper",
    },
    "TJAL": {
        "name": "TJAL",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJALJurisprudenciaScraper",
    },
    "TJSE": {
        "name": "TJSE",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJSEJurisprudenciaScraper",
    },
    "TJPI": {
        "name": "TJPI",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJPIJurisprudenciaScraper",
    },
    # North
    "TJPA": {
        "name": "TJPA",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJPAJurisprudenciaScraper",
    },
    "TJAM": {
        "name": "TJAM",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJAMJurisprudenciaScraper",
    },
    "TJRO": {
        "name": "TJRO",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJROJurisprudenciaScraper",
    },
    "TJTO": {
        "name": "TJTO",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJTOJurisprudenciaScraper",
    },
    "TJAC": {
        "name": "TJAC",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJACJurisprudenciaScraper",
    },
    "TJRR": {
        "name": "TJRR",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJRRJurisprudenciaScraper",
    },
    "TJAP": {
        "name": "TJAP",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJAPJurisprudenciaScraper",
    },
    # Center-West
    "TJDFT": {
        "name": "TJDFT",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJDFTJurisprudenciaScraper",
    },
    "TJGO": {
        "name": "TJGO",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJGOJurisprudenciaScraper",
    },
    "TJMT": {
        "name": "TJMT",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJMTJurisprudenciaScraper",
    },
    "TJMS": {
        "name": "TJMS",
        "scraper_module": "_shared.esaj_scrapers",
        "scraper_class": "TJMSJurisprudenciaScraper",
    },
}

COURT_NAMES = {
    "TJRS":  "Tribunal de Justiça do Rio Grande do Sul (TJRS)",
    "TJSP":  "Tribunal de Justiça de São Paulo (TJSP)",
    "TJMG":  "Tribunal de Justiça de Minas Gerais (TJMG)",
    "TJRJ":  "Tribunal de Justiça do Rio de Janeiro (TJRJ)",
    "STF":   "Supremo Tribunal Federal (STF)",
    # Chile
    "CL":    "Poder Judicial de Chile — Buscador Unificado de Fallos",
    # South
    "TJSC":  "Tribunal de Justiça de Santa Catarina (TJSC)",
    "TJPR":  "Tribunal de Justiça do Paraná (TJPR)",
    # Southeast
    "TJES":  "Tribunal de Justiça do Espírito Santo (TJES)",
    # Northeast
    "TJBA":  "Tribunal de Justiça da Bahia (TJBA)",
    "TJPE":  "Tribunal de Justiça de Pernambuco (TJPE)",
    "TJCE":  "Tribunal de Justiça do Ceará (TJCE)",
    "TJMA":  "Tribunal de Justiça do Maranhão (TJMA)",
    "TJPB":  "Tribunal de Justiça da Paraíba (TJPB)",
    "TJRN":  "Tribunal de Justiça do Rio Grande do Norte (TJRN)",
    "TJAL":  "Tribunal de Justiça de Alagoas (TJAL)",
    "TJSE":  "Tribunal de Justiça de Sergipe (TJSE)",
    "TJPI":  "Tribunal de Justiça do Piauí (TJPI)",
    # North
    "TJPA":  "Tribunal de Justiça do Pará (TJPA)",
    "TJAM":  "Tribunal de Justiça do Amazonas (TJAM)",
    "TJRO":  "Tribunal de Justiça de Rondônia (TJRO)",
    "TJTO":  "Tribunal de Justiça do Tocantins (TJTO)",
    "TJAC":  "Tribunal de Justiça do Acre (TJAC)",
    "TJRR":  "Tribunal de Justiça de Roraima (TJRR)",
    "TJAP":  "Tribunal de Justiça do Amapá (TJAP)",
    # Center-West
    "TJDFT": "Tribunal de Justiça do Distrito Federal e Territórios (TJDFT)",
    "TJGO":  "Tribunal de Justiça de Goiás (TJGO)",
    "TJMT":  "Tribunal de Justiça do Mato Grosso (TJMT)",
    "TJMS":  "Tribunal de Justiça do Mato Grosso do Sul (TJMS)",
}


def _resolve_court(court: Optional[str] = None) -> str:
    """Resolve a court identifier to a supported court key."""
    raw = str(court or DEFAULT_COURT).strip().upper()
    if raw in SUPPORTED_COURTS:
        return raw
    for key, info in SUPPORTED_COURTS.items():
        if raw in key or key in raw:
            return key
    return "TJRS"


def _resolve_selected_courts(court: Optional[str] = None, courts: Optional[List[str]] = None) -> List[str]:
    """Resolve a list of requested courts. Supports "ALL" and comma-separated values."""
    requested_tokens: List[str] = []

    if isinstance(courts, list):
        for item in courts:
            if item is None:
                continue
            for token in str(item).split(","):
                normalized = token.strip().upper()
                if normalized:
                    requested_tokens.append(normalized)

    if court:
        for token in str(court).split(","):
            normalized = token.strip().upper()
            if normalized:
                requested_tokens.append(normalized)

    if not requested_tokens:
        return [_resolve_court(DEFAULT_COURT)]

    if any(token in {"ALL", "TODOS", "TODAS", "*"} for token in requested_tokens):
        return list(SUPPORTED_COURTS.keys())

    resolved: List[str] = []
    for token in requested_tokens:
        matched = _resolve_court(token)
        if matched not in resolved:
            resolved.append(matched)

    return resolved or [_resolve_court(court or DEFAULT_COURT)]


def _get_scraper_class(court: str):
    """Return the scraper class and SearchCriteria for the given court."""
    court_key = _resolve_court(court)
    info = SUPPORTED_COURTS[court_key]
    import importlib
    mod = importlib.import_module(info["scraper_module"])
    scraper_cls = getattr(mod, info["scraper_class"])
    search_criteria_cls = getattr(mod, "SearchCriteria")
    return scraper_cls, search_criteria_cls
