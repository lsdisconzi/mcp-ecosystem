"""
Thin per-court wrappers for the e-SAJ scraper.

Each wrapper fixes the court_key parameter so the dispatch system in
modules/courts.py can instantiate with the standard `ScraperClass(headless=True)`
signature used by _get_scraper_class().

These are re-exported here so courts.py can point all e-SAJ courts to
a single module (_shared.esaj_scrapers) with different class names.
"""

from _shared.esaj_scraper import EsajJurisprudenciaScraper as _Base
from _shared.esaj_scraper import SearchCriteria  # noqa: F401 — re-exported for dispatch

# ── São Paulo ───────────────────────────────────────────────────────────────

class TJSPJurisprudenciaScraper(_Base):
    """TJSP — Tribunal de Justiça de São Paulo (reference e-SAJ implementation)."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJSP", headless=headless, wait_time=wait_time)

# ── South ───────────────────────────────────────────────────────────────────

class TJSCJurisprudenciaScraper(_Base):
    """TJSC — Tribunal de Justiça de Santa Catarina."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJSC", headless=headless, wait_time=wait_time)

class TJPRJurisprudenciaScraper(_Base):
    """TJPR — Tribunal de Justiça do Paraná."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJPR", headless=headless, wait_time=wait_time)

# ── Southeast ───────────────────────────────────────────────────────────────

class TJESJurisprudenciaScraper(_Base):
    """TJES — Tribunal de Justiça do Espírito Santo."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJES", headless=headless, wait_time=wait_time)

# ── Northeast ───────────────────────────────────────────────────────────────

class TJBAJurisprudenciaScraper(_Base):
    """TJBA — Tribunal de Justiça da Bahia."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJBA", headless=headless, wait_time=wait_time)

class TJPEJurisprudenciaScraper(_Base):
    """TJPE — Tribunal de Justiça de Pernambuco."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJPE", headless=headless, wait_time=wait_time)

class TJCEJurisprudenciaScraper(_Base):
    """TJCE — Tribunal de Justiça do Ceará."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJCE", headless=headless, wait_time=wait_time)

class TJMAJurisprudenciaScraper(_Base):
    """TJMA — Tribunal de Justiça do Maranhão."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJMA", headless=headless, wait_time=wait_time)

class TJPBJurisprudenciaScraper(_Base):
    """TJPB — Tribunal de Justiça da Paraíba."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJPB", headless=headless, wait_time=wait_time)

class TJRNJurisprudenciaScraper(_Base):
    """TJRN — Tribunal de Justiça do Rio Grande do Norte."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJRN", headless=headless, wait_time=wait_time)

class TJALJurisprudenciaScraper(_Base):
    """TJAL — Tribunal de Justiça de Alagoas."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJAL", headless=headless, wait_time=wait_time)

class TJSEJurisprudenciaScraper(_Base):
    """TJSE — Tribunal de Justiça de Sergipe."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJSE", headless=headless, wait_time=wait_time)

class TJPIJurisprudenciaScraper(_Base):
    """TJPI — Tribunal de Justiça do Piauí."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJPI", headless=headless, wait_time=wait_time)

# ── North ───────────────────────────────────────────────────────────────────

class TJPAJurisprudenciaScraper(_Base):
    """TJPA — Tribunal de Justiça do Pará."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJPA", headless=headless, wait_time=wait_time)

class TJAMJurisprudenciaScraper(_Base):
    """TJAM — Tribunal de Justiça do Amazonas."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJAM", headless=headless, wait_time=wait_time)

class TJROJurisprudenciaScraper(_Base):
    """TJRO — Tribunal de Justiça de Rondônia."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJRO", headless=headless, wait_time=wait_time)

class TJTOJurisprudenciaScraper(_Base):
    """TJTO — Tribunal de Justiça do Tocantins."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJTO", headless=headless, wait_time=wait_time)

class TJACJurisprudenciaScraper(_Base):
    """TJAC — Tribunal de Justiça do Acre."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJAC", headless=headless, wait_time=wait_time)

class TJRRJurisprudenciaScraper(_Base):
    """TJRR — Tribunal de Justiça de Roraima."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJRR", headless=headless, wait_time=wait_time)

class TJAPJurisprudenciaScraper(_Base):
    """TJAP — Tribunal de Justiça do Amapá."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJAP", headless=headless, wait_time=wait_time)

# ── Center-West ─────────────────────────────────────────────────────────────

class TJDFTJurisprudenciaScraper(_Base):
    """TJDFT — Tribunal de Justiça do Distrito Federal e Territórios."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJDFT", headless=headless, wait_time=wait_time)

class TJGOJurisprudenciaScraper(_Base):
    """TJGO — Tribunal de Justiça de Goiás."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJGO", headless=headless, wait_time=wait_time)

class TJMTJurisprudenciaScraper(_Base):
    """TJMT — Tribunal de Justiça do Mato Grosso."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJMT", headless=headless, wait_time=wait_time)

class TJMSJurisprudenciaScraper(_Base):
    """TJMS — Tribunal de Justiça do Mato Grosso do Sul."""
    def __init__(self, headless=True, wait_time=30):
        super().__init__("TJMS", headless=headless, wait_time=wait_time)
