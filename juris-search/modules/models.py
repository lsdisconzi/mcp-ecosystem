"""Pydantic models for the juris-search API."""

from typing import Optional, Dict, Any, List

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation: Optional[List[Dict[str, str]]] = None
    file_text: Optional[str] = None
    file_name: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    court: Optional[str] = None


class SearchFields(BaseModel):
    # ── Legacy Brazilian fields ──────────────────────────────────────
    search_text: str = ""
    tipo_processo: Optional[str] = None
    classe_cnj: Optional[str] = None
    assunto_cnj: Optional[str] = None
    comarca_origem: Optional[str] = None
    relator: Optional[str] = None
    orgao_julgador: Optional[str] = None
    tipo_decisao: Optional[str] = None
    tribunal: Optional[str] = None
    court: Optional[str] = None
    courts: Optional[List[str]] = None
    search_index: str = "acordao"
    max_results: int = 20
    # ── Chile-specific fields ────────────────────────────────────────
    categoria: Optional[str] = None
    juez: Optional[str] = None
    materia: Optional[str] = None
    rol: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    tipo_norma: Optional[str] = None
    orden: Optional[str] = None


class DownloadRequest(BaseModel):
    results: Optional[List[Dict[str, Any]]] = None
    url: Optional[str] = None
    numero_processo: Optional[str] = None
    inteiro_url: Optional[str] = None
    folder_name: Optional[str] = None
    tribunal: Optional[str] = None


class BatchDownloadRequest(BaseModel):
    results: List[Dict[str, Any]]
    folder_name: Optional[str] = None
    tribunal: Optional[str] = None
