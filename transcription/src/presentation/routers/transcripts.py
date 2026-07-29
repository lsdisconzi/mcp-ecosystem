"""Transcript intelligence router — analyze, search, list, SSE stream, curation, metadata."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import replace as _replace
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.application.dto.schemas import AnalyzeRequest, SearchRequest
from src.config import settings
from src.domain.entities.transcript import Segment, Speaker, Transcript
from src.domain.entities.patch import Patch, PatchOp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/transcripts", tags=["transcripts"])

# Injected by composition root
_analyze_use_case = None
_search_use_case = None
_store = None
_index = None
_auditor = None
_patcher = None
_validate_refine_use_case = None
_asr = None
_audio_files = None
_event_store: list = []


def init_transcript_router(
    analyze_use_case,
    search_use_case,
    store,
    index=None,
    *,
    auditor=None,
    patcher=None,
    validate_refine_use_case=None,
    asr_adapter=None,
    audio_file_adapter=None,
    event_store=None,   # 👈 ADD THIS
):
    global _analyze_use_case, _search_use_case, _store, _index
    global _auditor, _patcher, _validate_refine_use_case, _asr, _audio_files
    global _event_store   # 👈 ADD THIS

    _analyze_use_case = analyze_use_case
    _search_use_case = search_use_case
    _store = store
    _index = index
    _auditor = auditor
    _patcher = patcher
    _validate_refine_use_case = validate_refine_use_case
    _asr = asr_adapter
    _audio_files = audio_file_adapter
    if event_store is not None:
        _event_store = event_store

# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename_stem(name: str) -> str:
    if not name:
        return ""
    base = os.path.basename(str(name)).strip()
    stem, _ext = os.path.splitext(base)
    cleaned = _SAFE_NAME_RE.sub("_", stem).strip("._-")
    return cleaned[:180]


# ------------------------------------------------------------------
# Pydantic models for new metadata and review endpoints
# ------------------------------------------------------------------
class MetadataUpdate(BaseModel):
    """Update transcript metadata (top‑level fields)."""
    title: Optional[str] = None
    subtitle: Optional[str] = None
    recording_datetime: Optional[str] = None
    location: Optional[str] = None
    audio_id: Optional[str] = None
    case_id: Optional[str] = None
    narrative_id: Optional[str] = None
    chronological_order: Optional[int] = None
    prior_stage: Optional[str] = None
    next_stage: Optional[str] = None
    classification: Optional[str] = None
    participants: Optional[List[Dict[str, Any]]] = None
    violations_cited: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    forensic_clusters: Optional[Dict[str, Any]] = None
    key_evidentiary_findings: Optional[List[Dict[str, Any]]] = None
    corrections_applied: Optional[List[Dict[str, Any]]] = None
    # optional: replace entire segment list
    segments: Optional[List[Dict[str, Any]]] = None


class SegmentUpdate(BaseModel):
    """Segment‑level edits (reviewed status, patches, text, speaker, start/end)."""
    reviewed_indices: List[int] = []
    patches: List["PatchPayload"] = Field(default_factory=list)
    edited_texts: Dict[int, str] = {}
    edited_speakers: Dict[int, str] = {}
    edited_starts: Dict[int, float] = {}
    edited_ends: Dict[int, float] = {}
    recording_datetime: Optional[str] = None


class ReviewIndexPayload(BaseModel):
    collection: str = "reviewed_transcripts"
    create_if_missing: bool = True


class ImportSegmentPayload(BaseModel):
    index: int | None = None
    speaker: str | None = None
    start: float | int | None = 0.0
    end: float | int | None = None
    text: str | None = ""
    reviewed: bool | None = False


class ImportRunPayload(BaseModel):
    transcript_id: str | None = None
    source_file: str | None = None
    filename: str | None = None
    language: str | None = None
    timestamp: str | None = None
    provider: str | None = None
    metadata: dict | None = None
    segments: list[ImportSegmentPayload] = Field(default_factory=list)


class ImportTranscriptsPayload(BaseModel):
    runs: list[ImportRunPayload] = Field(default_factory=list)
    overwrite: bool = False
    rename_by_filename: bool = True


class CSVImportPayload(BaseModel):
    filename: str
    overwrite: bool = True


class ReviewSavePayload(BaseModel):
    reviewed_indices: list[int]
    edited_texts: dict[str, str] | None = None
    edited_speakers: dict[str, str] | None = None
    recording_datetime: str | None = None


class RetranscribeSegmentsPayload(BaseModel):
    segment_indices: list[int]
    whisper_model: str = "large-v3"
    language: str = "es"
    beam_size: int = 5
    best_of: int = 5
    whisper_temp: float = 0.0
    condition_on_previous_text: bool = False


class PatchPayload(BaseModel):
    op: str
    segment_indices: list[int] = Field(default_factory=list)
    new_text: str | None = None
    new_speaker: str | None = None
    new_start: float | None = None
    new_end: float | None = None
    insert_after_index: int | None = None
    note: str | None = ""


class PatchSegmentsPayload(BaseModel):
    patches: list[PatchPayload] = Field(default_factory=list)
    save_as_new_id: bool = True


class RefinePayload(BaseModel):
    canonical_name: str | None = None
    use_acoustic_probes: bool = True
    apply_patches: bool = True
    save_as_new_id: bool = True
    max_acoustic_windows: int = 8


# ------------------------------------------------------------------
# Existing endpoints (list, get, import, analyze, search, index, etc.)
# ------------------------------------------------------------------
@router.get("")
async def list_transcripts():
    ids = _store.list_ids()
    return {"transcripts": sorted(ids, reverse=True)}


@router.get("/{transcript_id}")
async def get_transcript(transcript_id: str):
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")
    return {
        "transcript_id": transcript.transcript_id,
        "source_file": transcript.source_file,
        "language": transcript.language,
        "timestamp": transcript.timestamp,
        "provider": transcript.provider,
        "original_transcript_id": transcript.original_transcript_id,
        "metadata": transcript.metadata or {},
        "title": transcript.title or "",
        "subtitle": transcript.subtitle or "",
        "recording_datetime": transcript.recording_datetime or "",
        "location": transcript.location or "",
        "audio_id": transcript.audio_id or "",
        "case_id": transcript.case_id or "",
        "narrative_id": transcript.narrative_id or "",
        "chronological_order": transcript.chronological_order,
        "prior_stage": transcript.prior_stage or "",
        "next_stage": transcript.next_stage or "",
        "classification": transcript.classification or "",
        "participants": transcript.participants or [],
        "violations_cited": transcript.violations_cited or [],
        "tags": transcript.tags or [],
        "forensic_clusters": transcript.forensic_clusters or {},
        "key_evidentiary_findings": transcript.key_evidentiary_findings or [],
        "corrections_applied": transcript.corrections_applied or [],
        "segments": [
            {
                "index": s.index,
                "speaker": s.speaker.label,
                "start": s.start,
                "end": s.end,
                "duration": s.duration,
                "text": s.text,
                "reviewed": getattr(s, "reviewed", False),
            }
            for s in transcript.segments
        ],
    }


@router.post("/import")
async def import_transcripts(payload: ImportTranscriptsPayload):
    if _store is None:
        raise HTTPException(status_code=503, detail="Transcript store not initialized")
    if not payload.runs:
        raise HTTPException(status_code=400, detail="No runs provided for import")

    existing_ids = set(_store.list_ids())
    imported_ids = []
    skipped = []
    errors = []

    for idx, run in enumerate(payload.runs):
        try:
            segments = []
            for seg_idx, seg in enumerate(run.segments):
                start = float(seg.start or 0.0)
                if start < 0:
                    start = 0.0
                end_raw = seg.end if seg.end is not None else start
                end = float(end_raw)
                if end < start:
                    end = start
                speaker_label = (seg.speaker or f"SPEAKER_{seg_idx:02d}").strip() or f"SPEAKER_{seg_idx:02d}"
                segment_index = seg.index if seg.index is not None else seg_idx
                segments.append(
                    Segment(
                        index=int(segment_index),
                        speaker=Speaker(label=speaker_label),
                        start=start,
                        end=end,
                        text=str(seg.text or ""),
                        reviewed=bool(seg.reviewed),
                    )
                )
            if not segments:
                skipped.append({"index": idx, "reason": "empty_segments"})
                continue

            incoming_id = (run.transcript_id or "").strip()
            source_file = (run.source_file or run.filename or "").strip()
            filename_stem = _sanitize_filename_stem(run.filename or run.source_file or "")

            if payload.rename_by_filename and filename_stem:
                desired_id = filename_stem
            elif incoming_id:
                desired_id = incoming_id
            elif filename_stem:
                desired_id = filename_stem
            else:
                desired_id = f"imported_{int(time.time() * 1000)}_{idx + 1}"

            transcript_id = desired_id
            if not payload.overwrite and transcript_id in existing_ids:
                nonce = 1
                while transcript_id in existing_ids:
                    nonce += 1
                    transcript_id = f"{desired_id}_{nonce}"

            transcript = Transcript(
                transcript_id=transcript_id,
                segments=segments,
                source_file=source_file,
                language=(run.language or "es"),
                metadata=(run.metadata or {}),
                timestamp=(run.timestamp or ""),
                provider=(run.provider or ""),
                original_transcript_id=(incoming_id if incoming_id and incoming_id != transcript_id else ""),
            )
            _store.save(transcript)
            existing_ids.add(transcript_id)
            imported_ids.append(transcript_id)
        except Exception as e:
            errors.append({"index": idx, "transcript_id": run.transcript_id, "error": str(e)})

    return {
        "total_runs": len(payload.runs),
        "imported": len(imported_ids),
        "imported_ids": imported_ids,
        "skipped": skipped,
        "errors": errors,
    }


@router.post("/analyze")
async def analyze_transcript(payload: AnalyzeRequest):
    if _analyze_use_case is None:
        raise HTTPException(status_code=503, detail="Transcript analysis not configured")
    try:
        result = await _analyze_use_case.execute(payload.transcript_id, instructions=payload.instructions)
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("[error] analysis failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/search")
async def search_transcripts(payload: SearchRequest):
    if _search_use_case is None:
        raise HTTPException(status_code=503, detail="Transcript search not configured")
    try:
        result = await _search_use_case.execute(payload.query, limit=payload.limit)
        return result.model_dump()
    except Exception as e:
        logger.exception("[error] search failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{transcript_id}/index")
async def index_transcript(transcript_id: str, collection: str | None = Query(default=None)):
    if _index is None:
        raise HTTPException(status_code=503, detail="Vector indexing not configured")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")
    if collection:
        n = await _index.index(transcript, collection_name=collection)
    else:
        n = await _index.index(transcript)
    return {"transcript_id": transcript_id, "segments_indexed": n}


@router.post("/index-all")
async def index_all_transcripts():
    if _index is None:
        raise HTTPException(status_code=503, detail="Vector indexing not configured")
    ids = _store.list_ids()
    total = 0
    errors = []
    for tid in ids:
        transcript = _store.load(tid)
        if transcript is None:
            continue
        try:
            n = await _index.index(transcript)
            total += n
        except Exception as e:
            errors.append({"transcript_id": tid, "error": str(e)})
    return {"transcripts_processed": len(ids), "segments_indexed": total, "errors": errors}


# ------------------------------------------------------------------
# SSE progress (unchanged)
# ------------------------------------------------------------------
_progress: dict[str, list[dict]] = {}
_jobs: dict[str, dict] = {}
_JOB_RETENTION_SEC = 3600


def _now_ts() -> float:
    return time.time()


def _cleanup_jobs() -> None:
    now = _now_ts()
    stale_ids = []
    for job_id, job in _jobs.items():
        updated_at = float(job.get("updated_at", now))
        if now - updated_at > _JOB_RETENTION_SEC:
            stale_ids.append(job_id)
    for job_id in stale_ids:
        _jobs.pop(job_id, None)
        _progress.pop(job_id, None)


def start_progress_job(job_id: str, filename: str | None = None) -> None:
    _cleanup_jobs()
    now = _now_ts()
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "stage": "upload",
        "progress": 0,
        "message": "Job enfileirado",
        "filename": filename,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "ended_at": None,
        "elapsed_s": 0.0,
        "result": None,
        "error": None,
    }
    _progress[job_id] = []
    emit_progress(job_id, "queued", {
        "job_id": job_id,
        "status": "queued",
        "stage": "upload",
        "progress": 0,
        "message": "Job enfileirado",
    })


def update_progress_job(job_id: str, *, stage: str, progress: int, message: str, status: str = "running", extra: dict | None = None) -> None:
    now = _now_ts()
    job = _jobs.get(job_id)
    if job is None:
        start_progress_job(job_id)
        job = _jobs[job_id]
    if job.get("started_at") is None and status == "running":
        job["started_at"] = now
    job.update({
        "status": status,
        "stage": stage,
        "progress": max(0, min(100, int(progress))),
        "message": message,
        "updated_at": now,
    })
    started_at = job.get("started_at") or job.get("created_at") or now
    job["elapsed_s"] = round(max(0.0, now - float(started_at)), 2)
    payload = {
        "job_id": job_id,
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "message": job["message"],
        "elapsed_s": job["elapsed_s"],
    }
    if extra:
        payload.update(extra)
    emit_progress(job_id, "progress", payload)


def complete_progress_job(job_id: str, result: dict) -> None:
    now = _now_ts()
    job = _jobs.get(job_id)
    if job is None:
        start_progress_job(job_id)
        job = _jobs[job_id]
    started_at = job.get("started_at") or job.get("created_at") or now
    elapsed_s = round(max(0.0, now - float(started_at)), 2)
    job.update({
        "status": "done",
        "stage": "transcription",
        "progress": 100,
        "message": "Concluído",
        "result": result,
        "updated_at": now,
        "ended_at": now,
        "elapsed_s": elapsed_s,
        "error": None,
    })
    emit_progress(job_id, "done", {
        "job_id": job_id,
        "status": "done",
        "stage": "transcription",
        "progress": 100,
        "message": "Concluído",
        "elapsed_s": elapsed_s,
    })


def fail_progress_job(job_id: str, error: str) -> None:
    now = _now_ts()
    job = _jobs.get(job_id)
    if job is None:
        start_progress_job(job_id)
        job = _jobs[job_id]
    started_at = job.get("started_at") or job.get("created_at") or now
    elapsed_s = round(max(0.0, now - float(started_at)), 2)
    job.update({
        "status": "error",
        "message": error,
        "updated_at": now,
        "ended_at": now,
        "elapsed_s": elapsed_s,
        "error": error,
    })
    emit_progress(job_id, "error", {
        "job_id": job_id,
        "status": "error",
        "message": error,
        "stage": job.get("stage") or "transcription",
        "progress": int(job.get("progress") or 0),
        "elapsed_s": elapsed_s,
    })


def get_progress_job(job_id: str) -> dict | None:
    _cleanup_jobs()
    job = _jobs.get(job_id)
    return dict(job) if job else None


def emit_progress(job_id: str, event_type: str, data: dict) -> None:
    if job_id not in _progress:
        _progress[job_id] = []
    _progress[job_id].append({"event": event_type, "data": data})


@router.get("/status/{job_id}")
async def get_progress_status(job_id: str):
    job = get_progress_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@router.get("/stream/{job_id}")
async def stream_progress(job_id: str, request: Request):
    async def event_generator():
        cursor = 0
        while True:
            if await request.is_disconnected():
                break
            events = _progress.get(job_id, [])
            while cursor < len(events):
                ev = events[cursor]
                yield {"event": ev["event"], "data": json.dumps(ev["data"])}
                cursor += 1
                if ev["event"] in ("done", "error"):
                    _progress.pop(job_id, None)
                    return
            await asyncio.sleep(0.3)
    return EventSourceResponse(event_generator())


# ------------------------------------------------------------------
# Audit, refine, patch (unchanged)
# ------------------------------------------------------------------
def _audit_to_payload(report) -> dict:
    return {
        "transcript_id": report.transcript_id,
        "counts_by_kind": report.kind_counts(),
        "counts_by_severity": report.severity_counts(),
        "anomalies": [
            {
                "kind": a.kind.value,
                "severity": a.severity.value,
                "segment_indices": list(a.segment_indices),
                "start": a.start,
                "end": a.end,
                "hint": a.hint,
                "detail": a.detail_dict(),
            }
            for a in report.anomalies
        ],
    }


@router.post("/{transcript_id}/audit")
async def audit_transcript_route(transcript_id: str):
    if _auditor is None or _store is None:
        raise HTTPException(status_code=503, detail="Auditor not configured")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")
    return _audit_to_payload(_auditor.audit(transcript))


@router.post("/{transcript_id}/refine")
async def refine_transcript_route(transcript_id: str, payload: RefinePayload | None = None):
    if _validate_refine_use_case is None:
        raise HTTPException(status_code=503, detail="Validate/refine use case not configured")
    body = payload or RefinePayload()
    try:
        result = await _validate_refine_use_case.execute(
            transcript_id,
            canonical_name=body.canonical_name,
            use_acoustic_probes=body.use_acoustic_probes,
            apply_patches=body.apply_patches,
            save_as_new_id=body.save_as_new_id,
            max_acoustic_windows=body.max_acoustic_windows,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("[error] refine failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return result.model_dump()


@router.post("/{transcript_id}/patch")
async def patch_transcript_route(transcript_id: str, payload: PatchSegmentsPayload):
    if _patcher is None or _store is None:
        raise HTTPException(status_code=503, detail="Patcher not configured")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    parsed = []
    for raw in payload.patches:
        try:
            op = PatchOp(raw.op)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"unknown patch op: {raw.op}") from exc
        parsed.append(
            Patch(
                op=op,
                segment_indices=tuple(int(i) for i in raw.segment_indices),
                new_text=raw.new_text,
                new_speaker=raw.new_speaker,
                new_start=raw.new_start,
                new_end=raw.new_end,
                insert_after_index=raw.insert_after_index,
                note=raw.note or "",
            )
        )

    patched, applied = _patcher.apply(transcript, parsed)
    if payload.save_as_new_id:
        new_id = f"{transcript_id}_patched_{int(time.time())}"
        patched = _replace(
            patched,
            transcript_id=new_id,
            original_transcript_id=transcript_id,
        )
    _store.save(patched)

    return {
        "transcript_id_in": transcript_id,
        "transcript_id_out": patched.transcript_id,
        "patches_applied": [
            {
                "op": p.op.value,
                "segment_indices": list(p.segment_indices),
                "new_text": p.new_text,
                "new_speaker": p.new_speaker,
                "new_start": p.new_start,
                "new_end": p.new_end,
                "insert_after_index": p.insert_after_index,
                "note": p.note,
            }
            for p in applied
        ],
    }


# ------------------------------------------------------------------
# CSV import / listing
# ------------------------------------------------------------------
@router.get("/csv/list")
async def list_csvs():
    csv_dir = os.path.join(os.path.dirname(settings.AUDIO_DIR), "csv")
    if not os.path.isdir(csv_dir):
        csv_dir = "/home/leandrodisconzi/transcription/data/csv"
    if not os.path.isdir(csv_dir):
        return {"csvs": []}
    files = [f for f in os.listdir(csv_dir) if f.endswith(".csv")]
    return {"csvs": sorted(files)}


@router.post("/csv/import")
async def import_csv(payload: CSVImportPayload):
    import csv
    csv_dir = os.path.join(os.path.dirname(settings.AUDIO_DIR), "csv")
    if not os.path.isdir(csv_dir):
        csv_dir = "/home/leandrodisconzi/transcription/data/csv"
    csv_path = os.path.join(csv_dir, payload.filename)
    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail=f"CSV file not found: {payload.filename}")

    stem, _ = os.path.splitext(payload.filename)
    transcript_id = _sanitize_filename_stem(payload.filename) or stem

    segments = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                idx = int(row.get("index", len(segments) + 1))
            except (ValueError, TypeError):
                idx = len(segments) + 1
            speaker_label = row.get("speaker", f"SPEAKER_{idx:02d}").strip()
            try:
                start = float(row.get("start", 0.0))
            except (ValueError, TypeError):
                start = 0.0
            try:
                end = float(row.get("end", start))
            except (ValueError, TypeError):
                end = start
            text = row.get("text", "").strip()
            segments.append(
                Segment(
                    index=idx,
                    speaker=Speaker(label=speaker_label),
                    start=start,
                    end=end,
                    text=text,
                    reviewed=False
                )
            )

    if not segments:
        raise HTTPException(status_code=400, detail="CSV file contains no valid segments.")

    audio_file = ""
    for ext in [".m4a", ".mp3", ".wav"]:
        audio_names = [
            stem.replace("segments_", "audio_") + ext,
            stem + ext,
            payload.filename.replace(".csv", ext)
        ]
        for audio_name in audio_names:
            possible_path = os.path.join(settings.AUDIO_DIR, audio_name)
            if os.path.exists(possible_path):
                audio_file = audio_name
                break
            possible_path = os.path.join(settings.ORIGINALS_DIR, audio_name)
            if os.path.exists(possible_path):
                audio_file = audio_name
                break
        if audio_file:
            break

    transcript = Transcript(
        transcript_id=transcript_id,
        segments=segments,
        source_file=audio_file or (stem.replace("segments_", "audio_") + ".m4a"),
        language="es",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(csv_path))),
        provider="csv_import",
    )
    _store.save(transcript)
    return {"status": "imported", "transcript_id": transcript_id, "segments": len(segments), "source_file": transcript.source_file}


# ------------------------------------------------------------------
# Review & curation endpoints (enhanced)
# ------------------------------------------------------------------
@router.get("/review/list")
async def list_transcripts_review(collection: str = Query("reviewed_transcripts")):
    ids = _store.list_ids()
    out = []
    qdrant_client = None
    if _index is not None:
        qdrant_client = _index._client

    qdrant_counts = {}
    if qdrant_client is not None:
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            collections = [c.name for c in qdrant_client.get_collections().collections]
            if collection in collections:
                for tid in ids:
                    res = qdrant_client.count(
                        collection_name=collection,
                        count_filter=Filter(must=[FieldCondition(key="transcript_id", match=MatchValue(value=tid))])
                    )
                    qdrant_counts[tid] = res.count
        except Exception as e:
            logger.warning("[qdrant] failed to query reviewed counts: %s", e)

    for tid in ids:
        t = _store.load(tid)
        if not t:
            continue
        total_segs = len(t.segments)
        reviewed_segs = sum(1 for s in t.segments if getattr(s, "reviewed", False))
        completeness = round(reviewed_segs / total_segs, 4) if total_segs > 0 else 0.0
        out.append({
            "transcript_id": tid,
            "source_file": t.source_file,
            "total_segments": total_segs,
            "reviewed_segments": reviewed_segs,
            "completeness": completeness,
            "qdrant_indexed_segments": qdrant_counts.get(tid, 0),
            "timestamp": t.timestamp,
        })
    out.sort(key=lambda x: (x["completeness"], x["transcript_id"]), reverse=True)
    return {"transcripts": out}


@router.put("/{transcript_id}")
async def update_transcript_metadata(transcript_id: str, update: MetadataUpdate):
    """Update metadata fields of a transcript. Preserves segments unless `segments` is provided."""
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    update_dict = update.model_dump(exclude_unset=True)
    # Update simple fields (top-level)
    for key, value in update_dict.items():
        if key == "segments":
            continue
        if value is not None:
            setattr(transcript, key, value)

    # If full segment list is provided, replace it
    if update.segments is not None:
        new_segments = []
        for seg_dict in update.segments:
            new_segments.append(
                Segment(
                    index=seg_dict.get("index", len(new_segments)),
                    speaker=Speaker(label=seg_dict.get("speaker", "UNKNOWN")),
                    start=float(seg_dict.get("start", 0.0)),
                    end=float(seg_dict.get("end", 0.0)),
                    text=seg_dict.get("text", ""),
                    reviewed=seg_dict.get("reviewed", False),
                )
            )
        transcript.segments = new_segments

    _store.save(transcript)
    return {"status": "ok", "transcript_id": transcript_id, "updated_fields": list(update_dict.keys())}


@router.post("/{transcript_id}/review/save")
async def save_review(transcript_id: str, payload: SegmentUpdate):
    base = _store.load(transcript_id)
    if not base:
        raise HTTPException(status_code=404, detail="Transcript not found")

    now = time.time()

    def emit(seg_idx: int, event_type: str, event_payload: dict):
        _event_store.append({
            "transcript_id": transcript_id,
            "segment_index": seg_idx,
            "type": event_type,
            "payload": event_payload,
            "timestamp": now,
        })

    # Apply patches if patcher is available
    if payload.patches and _patcher is not None:
        parsed = []
        for raw in payload.patches:
            try:
                op = PatchOp(raw.op)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"unknown patch op: {raw.op}") from exc
            parsed.append(
                Patch(
                    op=op,
                    segment_indices=tuple(int(i) for i in raw.segment_indices),
                    new_text=raw.new_text,
                    new_speaker=raw.new_speaker,
                    new_start=raw.new_start,
                    new_end=raw.new_end,
                    insert_after_index=raw.insert_after_index,
                    note=raw.note or "",
                )
            )
        patched, applied = _patcher.apply(base, parsed)
    else:
        patched = base

    # Mark reviewed segments
    for idx in payload.reviewed_indices:
        if 0 <= idx < len(patched.segments):
            patched.segments[idx] = _replace(patched.segments[idx], reviewed=True)
            emit(idx, "segment_reviewed", {})

    for idx, text in payload.edited_texts.items():
        emit(idx, "segment_text_edited", {"text": text})
    for idx, spk in payload.edited_speakers.items():
        emit(idx, "segment_speaker_edited", {"speaker": spk})
    for idx, start in payload.edited_starts.items():
        emit(idx, "segment_time_edited", {"start": start})
    for idx, end in payload.edited_ends.items():
        emit(idx, "segment_time_edited", {"end": end})

    _store.save(patched)

    return {"status": "ok", "events_written": len(payload.reviewed_indices)
            + len(payload.edited_texts)
            + len(payload.edited_speakers)
            + len(payload.edited_starts)
            + len(payload.edited_ends)}
            
@router.post("/{transcript_id}/review/index")
async def index_reviewed_segments(transcript_id: str, payload: ReviewIndexPayload = ReviewIndexPayload()):
    if _index is None:
        raise HTTPException(status_code=503, detail="Vector indexing not configured")
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    reviewed_segments = [s for s in transcript.segments if getattr(s, "reviewed", False)]
    collection_name = (payload.collection or "").strip() or "reviewed_transcripts"

    await _index.delete(transcript_id, collection_name=collection_name)

    if not reviewed_segments:
        return {"transcript_id": transcript_id, "segments_indexed": 0, "message": "No reviewed segments. Existing points cleared."}

    reviewed_transcript = _replace(transcript, segments=reviewed_segments)
    n = await _index.index(reviewed_transcript, collection_name=collection_name)
    return {"transcript_id": transcript_id, "segments_indexed": n, "collection": collection_name}


@router.post("/{transcript_id}/retranscribe_segments")
async def retranscribe_segments(transcript_id: str, payload: RetranscribeSegmentsPayload):
    if _asr is None or _audio_files is None:
        raise HTTPException(status_code=503, detail="ASR or Audio processor not initialized")

    from pydub import AudioSegment
    from src.domain.chilean_spanish import post_process_chilean_spanish
    import tempfile, shutil

    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")

    audio_filename = transcript.source_file
    if not audio_filename:
        audio_filename = f"{transcript_id}.m4a"

    audio_path = None
    search_names = [audio_filename, audio_filename + ".wav", os.path.basename(audio_filename)]
    for folder in [settings.AUDIO_DIR, settings.ORIGINALS_DIR, "/home/leandrodisconzi/transcription/data/audio"]:
        for name in search_names:
            possible_path = os.path.join(folder, name)
            if os.path.exists(possible_path):
                audio_path = possible_path
                break
        if audio_path:
            break

    if not audio_path:
        stems = [transcript_id]
        if transcript.source_file:
            stems.append(transcript.source_file)
            base = os.path.splitext(transcript.source_file)[0]
            if "_" in base:
                parts = base.split("_", 1)
                if parts[0] in ("audio", "segments"):
                    stems.append(parts[1])
        for folder in [settings.AUDIO_DIR, settings.ORIGINALS_DIR]:
            if os.path.isdir(folder):
                for f in sorted(os.listdir(folder)):
                    fl = os.path.splitext(f)[0].lower()
                    for stem in stems:
                        if fl == stem.lower() or fl.startswith(stem.lower().replace(" ", "_")):
                            ext = f.split(".")[-1].lower()
                            if ext in ("wav", "mp3", "m4a", "mp4"):
                                audio_path = os.path.join(folder, f)
                                break
                    if audio_path:
                        break
            if audio_path:
                break

    if not audio_path:
        raise HTTPException(status_code=400, detail=f"Could not locate audio file for '{audio_filename}' or '{transcript_id}'")

    # Prepare WAV source
    temp_wav_source = None
    source_path = audio_path
    if not audio_path.lower().endswith(".wav"):
        # Copy to temp, then convert
        _, ext = os.path.splitext(audio_path)
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
            shutil.copy(audio_path, tf.name)
            temp_copy = tf.name
        temp_wav_source = _audio_files.convert_to_wav(temp_copy)
        source_path = temp_wav_source

    indices_set = set(payload.segment_indices)
    updated_segments = []

    try:
        for s in transcript.segments:
            if s.index in indices_set and not getattr(s, "reviewed", False):
                start_ms = int(s.start * 1000)
                end_ms = int(s.end * 1000)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as turn_file:
                    turn_path = turn_file.name
                try:
                    _audio_files.extract_segment(source_path, start_ms, end_ms, turn_path)
                    asr_result = _asr.transcribe(
                        turn_path,
                        language=payload.language,
                        model_size=payload.whisper_model,
                        temperature=payload.whisper_temp,
                        beam_size=payload.beam_size,
                        best_of=payload.best_of,
                        condition_on_previous_text=payload.condition_on_previous_text,
                    )
                    raw_text = asr_result.get("text", "") if isinstance(asr_result, dict) else asr_result
                    resolved_lang = asr_result.get("language") if isinstance(asr_result, dict) else None
                    is_spanish = resolved_lang in ("es", "es-CL") or (payload.language or "").startswith("es")
                    text = post_process_chilean_spanish(raw_text) if is_spanish else raw_text
                    updated_segments.append(
                        Segment(
                            index=s.index,
                            speaker=s.speaker,
                            start=s.start,
                            end=s.end,
                            text=text,
                            reviewed=False
                        )
                    )
                finally:
                    if os.path.exists(turn_path):
                        os.remove(turn_path)
            else:
                updated_segments.append(s)
    finally:
        if temp_wav_source and os.path.exists(temp_wav_source):
            os.remove(temp_wav_source)

    transcript.segments = updated_segments
    _store.save(transcript)
    return {"status": "updated", "transcript_id": transcript_id, "updated_indices": list(indices_set)}


@router.get("/audio/list")
async def list_audio_files():
    try:
        files = sorted(os.listdir(settings.AUDIO_DIR))
        audio_files = [f for f in files if os.path.isfile(os.path.join(settings.AUDIO_DIR, f))]
        return {"audio_dir": settings.AUDIO_DIR, "files": audio_files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Backward compatibility: the old /pinocchio/review endpoint
# ------------------------------------------------------------------
@router.get("/pinocchio/review/{transcript_id}")
async def get_review_transcript(transcript_id: str):
    transcript = _store.load(transcript_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail=f"Transcript not found: {transcript_id}")
    return {
        "transcript_id": transcript.transcript_id,
        "segments": [
            {
                "index": s.index,
                "speaker": s.speaker.label,
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "reviewed": getattr(s, "reviewed", False),
            }
            for s in transcript.segments
        ],
    }


@router.post("/pinocchio/review/{transcript_id}")
async def save_review_legacy(transcript_id: str, payload: ReviewSavePayload):
    """Legacy endpoint – delegates to the new /review/save implementation."""
    segment_update = SegmentUpdate(
        reviewed_indices=payload.reviewed_indices,
        edited_texts={int(k): v for k, v in (payload.edited_texts or {}).items()},
        edited_speakers={int(k): v for k, v in (payload.edited_speakers or {}).items()},
        recording_datetime=payload.recording_datetime,
    )
    return await save_transcript_review(transcript_id, segment_update)