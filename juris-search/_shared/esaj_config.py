"""
e-SAJ CJSG Court Configuration.

Centralized configuration for all Brazilian Tribunais de Justiça that use the
Softplan e-SAJ CJSG (Consulta de Julgados de Segundo Grau) system.

The e-SAJ system uses a standardized HTML structure across ~22 courts:
  - Search: POST to /cjsg/resultadoCompleta.do
  - Pagination: /cjsg/trocaDePagina.do
  - Download: /cjsg/getArquivo.do?cdAcordao=X&cdForo=0
  - Results: .fundocinza1 CSS blocks
  - Metadata: .ementaClass2 spans

Each court entry specifies the base URL and any court-specific overrides.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List


@dataclass
class EsajCourtConfig:
    """Configuration for a single e-SAJ court."""
    # Court identity
    key: str                              # e.g. "TJSP", "TJSC"
    name: str                             # e.g. "Tribunal de Justiça de São Paulo"
    state: str                            # e.g. "SP", "SC"

    # URLs
    base_url: str                         # e.g. "https://esaj.tjsp.jus.br"
    search_path: str = "/cjsg/resultadoCompleta.do"
    pagination_path: str = "/cjsg/trocaDePagina.do"
    download_path: str = "/cjsg/getArquivo.do"

    @property
    def search_url(self) -> str:
        return f"{self.base_url}{self.search_path}"

    @property
    def pagination_url(self) -> str:
        return f"{self.base_url}{self.pagination_path}"

    @property
    def download_url(self) -> str:
        return f"{self.base_url}{self.download_path}"

    # Captcha
    captcha_type: str = "recaptcha_v3"      # "recaptcha_v3", "image_captcha", "none"

    # Form field overrides (empty = use defaults from EsajScraper)
    form_field_overrides: Dict[str, str] = field(default_factory=dict)

    # CSS selector overrides (empty = use defaults)
    result_block_selector: str = ".fundocinza1"
    download_link_selector: str = ".downloadEmenta"
    metadata_selector: str = ".ementaClass2"
    ementa_selectors: List[str] = field(default_factory=lambda: [
        "textarea",
        ".ementaClass",
    ])
    assunto_classe_selector: str = ".assuntoClasse"

    # Decision type mapping (override if court uses different values)
    tipo_decisao_map: Dict[str, str] = field(default_factory=lambda: {
        "acórdão": "A",
        "acordao": "A",
        "monocrática": "D",
        "monocratica": "D",
        "decisão monocrática": "D",
        "homologação": "H",
        "homologacao": "H",
    })

    # Judge name normalisation (some courts label it differently)
    relator_label_keys: List[str] = field(default_factory=lambda: [
        "relator_a", "relatora", "relator", "relator(a)",
    ])
    orgao_label_keys: List[str] = field(default_factory=lambda: [
        "orgao_julgador", "orgao_judicante", "orgao",
    ])
    comarca_label_keys: List[str] = field(default_factory=lambda: [
        "comarca", "comarca_origem",
    ])
    data_julgamento_keys: List[str] = field(default_factory=lambda: [
        "data_do_julgamento", "data_julgamento", "data_de_julgamento",
    ])
    data_publicacao_keys: List[str] = field(default_factory=lambda: [
        "data_de_publicacao", "data_publicacao",
    ])
    data_registro_keys: List[str] = field(default_factory=lambda: [
        "data_de_registro", "data_registro",
    ])

    # CNJ process number regex (usually same across e-SAJ)
    cnj_process_re: str = r"\b(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\b"

    # Notes for maintainers
    notes: str = ""


# ── Master registry of all e-SAJ courts ──────────────────────────────────────

# ── Tier summary ─────────────────────────────────────────────────────────────
# Tier 1 (VERIFIED — live search returns results): TJMS, TJAC, TJAM, TJCE, TJAL (5)
# Tier 2 (CJSG loads but form has issues): TJRN, TJMA, TJRR (3)
# Tier X (custom portal, NOT e-SAJ): TJSC, TJPR, TJDFT, TJMT, TJBA (5)
# Unreachable (DNS/domain not found): TJES, TJPB, TJSE, TJPA, TJPI, TJRO, TJTO, TJGO, TJAP, TJPE (10)
# Reference: TJSP (dedicated scraper, not using this config)

ESAJ_COURTS: Dict[str, EsajCourtConfig] = {
    # ── São Paulo (reference implementation) ──────────────────────────────
    "TJSP": EsajCourtConfig(
        key="TJSP",
        name="Tribunal de Justiça de São Paulo",
        state="SP",
        base_url="https://esaj.tjsp.jus.br",
        captcha_type="image_captcha",
        notes="Reference implementation. Has both reCAPTCHA v3 and image captcha. Dedicated tjsp_scraper.py.",
    ),

    # ── South Region ──────────────────────────────────────────────────────
    "TJSC": EsajCourtConfig(
        key="TJSC",
        name="Tribunal de Justiça de Santa Catarina",
        state="SC",
        base_url="https://busca.tjsc.jus.br",
        search_path="/jurisprudencia/",
        pagination_path="/jurisprudencia/",
        download_path="/jurisprudencia/",
        captcha_type="none",
        notes="Custom portal (not e-SAJ). Uses busca.tjsc.jus.br/jurisprudencia/.",
    ),
    "TJPR": EsajCourtConfig(
        key="TJPR",
        name="Tribunal de Justiça do Paraná",
        state="PR",
        base_url="https://portal.tjpr.jus.br",
        search_path="/jurisprudencia/",
        pagination_path="/jurisprudencia/",
        download_path="/jurisprudencia/",
        captcha_type="none",
        notes="Custom portal (not e-SAJ). Uses portal.tjpr.jus.br/jurisprudencia/.",
    ),

    # ── Southeast Region ──────────────────────────────────────────────────
    "TJES": EsajCourtConfig(
        key="TJES",
        name="Tribunal de Justiça do Espírito Santo",
        state="ES",
        base_url="https://esaj.tjes.jus.br",
    ),

    # ── Northeast Region ──────────────────────────────────────────────────
    "TJBA": EsajCourtConfig(
        key="TJBA",
        name="Tribunal de Justiça da Bahia",
        state="BA",
        base_url="https://esaj.tjba.jus.br",
    ),
    "TJPE": EsajCourtConfig(
        key="TJPE",
        name="Tribunal de Justiça de Pernambuco",
        state="PE",
        base_url="https://esaj.tjpe.jus.br",
    ),
    "TJCE": EsajCourtConfig(
        key="TJCE",
        name="Tribunal de Justiça do Ceará",
        state="CE",
        base_url="https://esaj.tjce.jus.br",
        notes="TIER 1 VERIFIED. Live search returning results with full metadata.",
    ),
    "TJMA": EsajCourtConfig(
        key="TJMA",
        name="Tribunal de Justiça do Maranhão",
        state="MA",
        base_url="https://www2.tjma.jus.br",
        notes="VERIFIED: www2 subdomain pattern. e-SAJ CJSG confirmed.",
    ),
    "TJPB": EsajCourtConfig(
        key="TJPB",
        name="Tribunal de Justiça da Paraíba",
        state="PB",
        base_url="https://esaj.tjpb.jus.br",
    ),
    "TJRN": EsajCourtConfig(
        key="TJRN",
        name="Tribunal de Justiça do Rio Grande do Norte",
        state="RN",
        base_url="https://www.tjrn.jus.br",
        notes="VERIFIED: www.tjrn.jus.br/cjsg/ (not esaj subdomain). e-SAJ CJSG confirmed.",
    ),
    "TJAL": EsajCourtConfig(
        key="TJAL",
        name="Tribunal de Justiça de Alagoas",
        state="AL",
        base_url="https://www2.tjal.jus.br",
        notes="VERIFIED: www2 subdomain pattern. e-SAJ CJSG confirmed.",
    ),
    "TJSE": EsajCourtConfig(
        key="TJSE",
        name="Tribunal de Justiça de Sergipe",
        state="SE",
        base_url="https://esaj.tjse.jus.br",
    ),
    "TJPI": EsajCourtConfig(
        key="TJPI",
        name="Tribunal de Justiça do Piauí",
        state="PI",
        base_url="https://esaj.tjpi.jus.br",
    ),

    # ── North Region ──────────────────────────────────────────────────────
    "TJPA": EsajCourtConfig(
        key="TJPA",
        name="Tribunal de Justiça do Pará",
        state="PA",
        base_url="https://esaj.tjpa.jus.br",
    ),
    "TJAM": EsajCourtConfig(
        key="TJAM",
        name="Tribunal de Justiça do Amazonas",
        state="AM",
        base_url="https://consultasaj.tjam.jus.br",
        notes="VERIFIED: consultasaj subdomain pattern. e-SAJ CJSG confirmed.",
    ),
    "TJRO": EsajCourtConfig(
        key="TJRO",
        name="Tribunal de Justiça de Rondônia",
        state="RO",
        base_url="https://esaj.tjro.jus.br",
    ),
    "TJTO": EsajCourtConfig(
        key="TJTO",
        name="Tribunal de Justiça do Tocantins",
        state="TO",
        base_url="https://esaj.tjto.jus.br",
    ),
    "TJAC": EsajCourtConfig(
        key="TJAC",
        name="Tribunal de Justiça do Acre",
        state="AC",
        base_url="https://esaj.tjac.jus.br",
        notes="TIER 1 VERIFIED. Live search returning results with full metadata.",
    ),
    "TJRR": EsajCourtConfig(
        key="TJRR",
        name="Tribunal de Justiça de Roraima",
        state="RR",
        base_url="https://www2.tjrr.jus.br",
        notes="VERIFIED: www2 subdomain pattern. e-SAJ CJSG confirmed.",
    ),
    "TJAP": EsajCourtConfig(
        key="TJAP",
        name="Tribunal de Justiça do Amapá",
        state="AP",
        base_url="https://esaj.tjap.jus.br",
    ),

    # ── Center-West Region ────────────────────────────────────────────────
    "TJDFT": EsajCourtConfig(
        key="TJDFT",
        name="Tribunal de Justiça do Distrito Federal e Territórios",
        state="DF",
        base_url="https://pesquisajuris.tjdft.jus.br",
        search_path="/IndexadorAcordaos-web/sistj",
        pagination_path="/IndexadorAcordaos-web/sistj",
        download_path="/IndexadorAcordaos-web/sistj",
        captcha_type="none",
        notes="VERIFIED: Custom SISTJWEB system, NOT e-SAJ. Needs dedicated CSS selectors.",
    ),
    "TJGO": EsajCourtConfig(
        key="TJGO",
        name="Tribunal de Justiça de Goiás",
        state="GO",
        base_url="https://esaj.tjgo.jus.br",
    ),
    "TJMT": EsajCourtConfig(
        key="TJMT",
        name="Tribunal de Justiça do Mato Grosso",
        state="MT",
        base_url="https://esaj.tjmt.jus.br",
    ),
    "TJMS": EsajCourtConfig(
        key="TJMS",
        name="Tribunal de Justiça do Mato Grosso do Sul",
        state="MS",
        base_url="https://esaj.tjms.jus.br",
        notes="TIER 1 VERIFIED. Live search returning results with full metadata. 5/5 test queries pass.",
    ),
}


def get_esaj_config(court_key: str) -> Optional[EsajCourtConfig]:
    """Get e-SAJ configuration for a court key. Returns None if not an e-SAJ court."""
    return ESAJ_COURTS.get(court_key.upper())


def list_esaj_courts() -> List[str]:
    """Return sorted list of all e-SAJ court keys."""
    return sorted(ESAJ_COURTS.keys())


def is_esaj_court(court_key: str) -> bool:
    """Check if a court key is an e-SAJ court."""
    return court_key.upper() in ESAJ_COURTS
