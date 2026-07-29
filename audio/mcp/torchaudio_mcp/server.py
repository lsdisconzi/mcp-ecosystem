#!/usr/bin/env python3
"""MCP server exposing common TorchAudio workflows as tools.

This server is intentionally lightweight and can be launched in stdio mode
(for MCP clients like Claude Desktop) or wrapped by MCPO for OpenAPI/HTTP.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import torch
import torchaudio
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse


mcp = FastMCP("torchaudio-tools")


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for VPS connectivity tests."""
    return JSONResponse({
        "status": "ok",
        "service": "torchaudio-tools",
        "torch": torch.__version__,
        "torchaudio": torchaudio.__version__,
    })


def _as_abs_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _audio_basic_stats(waveform: torch.Tensor, sample_rate: int) -> Dict[str, float]:
    channels, frames = waveform.shape
    duration_sec = float(frames / sample_rate) if sample_rate else 0.0
    return {
        "channels": int(channels),
        "frames": int(frames),
        "sample_rate": int(sample_rate),
        "duration_sec": duration_sec,
        "mean": float(waveform.mean().item()),
        "std": float(waveform.std().item()),
        "min": float(waveform.min().item()),
        "max": float(waveform.max().item()),
    }


def _greedy_decode(emission: torch.Tensor, labels: List[str], blank_id: int = 0) -> str:
    token_ids = torch.argmax(emission, dim=-1)[0]
    transcript_tokens: List[str] = []
    prev = blank_id
    for idx in token_ids.tolist():
        if idx != blank_id and idx != prev:
            transcript_tokens.append(labels[idx])
        prev = idx
    return "".join(transcript_tokens).replace("|", " ").strip()


@mcp.tool()
def transcription_healthcheck() -> Dict[str, str]:
    """Health check for the transcription MCP tools."""
    return {
        "status": "ok",
        "torch": torch.__version__,
        "torchaudio": torchaudio.__version__,
    }


@mcp.tool()
def transcription_audio_info(path: str) -> Dict[str, Any]:
    """Inspect an audio file and return metadata/stats for transcription flows."""
    target = _as_abs_path(path)
    if not target.exists():
        raise FileNotFoundError(f"Audio file not found: {target}")

    waveform, sample_rate = torchaudio.load(str(target))
    out = _audio_basic_stats(waveform, sample_rate)
    out["path"] = str(target)
    return out


@mcp.tool()
def transcription_resample_audio(input_path: str, output_path: str, target_sample_rate: int) -> Dict[str, Any]:
    """Resample an audio file and write the output to a new path."""
    source = _as_abs_path(input_path)
    dest = _as_abs_path(output_path)

    if not source.exists():
        raise FileNotFoundError(f"Input audio file not found: {source}")

    waveform, sample_rate = torchaudio.load(str(source))
    if sample_rate != target_sample_rate:
        waveform = torchaudio.functional.resample(waveform, sample_rate, target_sample_rate)

    dest.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(dest), waveform, target_sample_rate)

    out = _audio_basic_stats(waveform, target_sample_rate)
    out["input_path"] = str(source)
    out["output_path"] = str(dest)
    return out


@mcp.tool()
def transcription_slice_audio(
    input_path: str,
    output_path: str,
    start_sec: float,
    end_sec: float,
) -> Dict[str, Any]:
    """Slice an audio file to [start_sec, end_sec] and write the output to a new path.

    Returns basic stats for the sliced waveform plus input_path/output_path.
    """
    source = _as_abs_path(input_path)
    dest = _as_abs_path(output_path)

    if not source.exists():
        raise FileNotFoundError(f"Input audio file not found: {source}")
    if end_sec <= start_sec:
        raise ValueError(
            f"end_sec ({end_sec}) must be greater than start_sec ({start_sec})"
        )
    if start_sec < 0:
        raise ValueError(f"start_sec must be >= 0 (got {start_sec})")

    waveform, sample_rate = torchaudio.load(str(source))
    total_frames = waveform.shape[1]
    duration_sec = total_frames / sample_rate if sample_rate else 0.0
    if start_sec >= duration_sec:
        raise ValueError(
            f"start_sec ({start_sec}) is past file duration ({duration_sec:.3f}s)"
        )

    end_clamped = min(end_sec, duration_sec)
    start_frame = int(start_sec * sample_rate)
    end_frame = int(end_clamped * sample_rate)
    sliced = waveform[:, start_frame:end_frame]

    dest.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(dest), sliced, sample_rate)

    out = _audio_basic_stats(sliced, sample_rate)
    out["input_path"] = str(source)
    out["output_path"] = str(dest)
    out["start_sec"] = float(start_sec)
    out["end_sec"] = float(end_clamped)
    return out


@mcp.tool()
def transcription_extract_features(
    path: str,
    feature: Literal["spectrogram", "mel_spectrogram", "mfcc"] = "mel_spectrogram",
    n_fft: int = 400,
    hop_length: int = 160,
    n_mels: int = 80,
    n_mfcc: int = 40,
    save_tensor_path: Optional[str] = None,
) -> Dict[str, object]:
    """Compute spectral features and return shape plus summary statistics.

    If save_tensor_path is set, the computed feature tensor is stored with torch.save.
    """
    source = _as_abs_path(path)
    if not source.exists():
        raise FileNotFoundError(f"Input audio file not found: {source}")

    waveform, sample_rate = torchaudio.load(str(source))

    if feature == "spectrogram":
        transform = torchaudio.transforms.Spectrogram(n_fft=n_fft, hop_length=hop_length)
    elif feature == "mel_spectrogram":
        transform = torchaudio.transforms.MelSpectrogram(
            sample_rate=sample_rate,
            n_fft=n_fft,
            hop_length=hop_length,
            n_mels=n_mels,
        )
    else:
        transform = torchaudio.transforms.MFCC(
            sample_rate=sample_rate,
            n_mfcc=n_mfcc,
            melkwargs={"n_fft": n_fft, "hop_length": hop_length, "n_mels": n_mels},
        )

    features = transform(waveform)

    result: Dict[str, object] = {
        "path": str(source),
        "feature": feature,
        "sample_rate": int(sample_rate),
        "shape": list(features.shape),
        "mean": float(features.mean().item()),
        "std": float(features.std().item()),
        "min": float(features.min().item()),
        "max": float(features.max().item()),
    }

    if save_tensor_path:
        save_path = _as_abs_path(save_tensor_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(features, save_path)
        result["saved_tensor_path"] = str(save_path)

    return result


@mcp.tool()
def transcription_list_asr_bundles() -> Dict[str, List[str]]:
    """List available ASR-style pipeline bundles in torchaudio.pipelines."""
    names = []
    for name in dir(torchaudio.pipelines):
        if not name.isupper():
            continue
        item = getattr(torchaudio.pipelines, name)
        if hasattr(item, "get_model") and hasattr(item, "get_labels"):
            names.append(name)
    names.sort()
    return {"bundles": names}


@mcp.tool()
def transcription_transcribe_greedy(
    path: str,
    bundle_name: str = "WAV2VEC2_ASR_BASE_960H",
    device: Literal["cpu", "cuda"] = "cpu",
) -> Dict[str, object]:
    """Run greedy ASR decoding with a torchaudio pipeline bundle.

    This may download model weights on first run.
    """
    source = _as_abs_path(path)
    if not source.exists():
        raise FileNotFoundError(f"Input audio file not found: {source}")

    if not hasattr(torchaudio.pipelines, bundle_name):
        raise ValueError(f"Unknown bundle_name: {bundle_name}")

    bundle = getattr(torchaudio.pipelines, bundle_name)
    if not hasattr(bundle, "get_model"):
        raise ValueError(f"Bundle is not ASR-capable: {bundle_name}")

    model = bundle.get_model().to(device)
    model.eval()

    waveform, sample_rate = torchaudio.load(str(source))
    if hasattr(bundle, "sample_rate") and sample_rate != bundle.sample_rate:
        waveform = torchaudio.functional.resample(waveform, sample_rate, bundle.sample_rate)
        sample_rate = bundle.sample_rate

    with torch.inference_mode():
        emissions, _ = model(waveform.to(device))

    labels = list(bundle.get_labels())
    transcript = _greedy_decode(emissions.cpu(), labels)

    return {
        "path": str(source),
        "bundle_name": bundle_name,
        "sample_rate": int(sample_rate),
        "transcript": transcript,
    }


@mcp.tool()
def transcription_list_project_paths() -> Dict[str, object]:
    """Return key project folders that can be used by automation tools."""
    root = Path(__file__).resolve().parents[2]
    examples = root / "examples"
    docs = root / "docs"
    test = root / "test"

    return {
        "project_root": str(root),
        "paths": {
            "examples": str(examples),
            "docs": str(docs),
            "test": str(test),
        },
    }


def main() -> None:
    """Start the MCP server with configurable transport."""
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8765"))

    if transport == "stdio":
        mcp.run()
        return

    if transport not in {"sse", "streamable-http"}:
        raise ValueError(
            "Unsupported MCP_TRANSPORT. Use one of: stdio, sse, streamable-http"
        )

    # Newer FastMCP versions take host/port from settings, while older ones
    # accept host/port directly in run(). Support both signatures.
    if hasattr(mcp, "settings"):
        if hasattr(mcp.settings, "host"):
            mcp.settings.host = host
        if hasattr(mcp.settings, "port"):
            mcp.settings.port = port

    try:
        mcp.run(transport=transport, host=host, port=port)
    except TypeError as exc:
        message = str(exc)
        if "unexpected keyword argument" in message and (
            "host" in message or "port" in message
        ):
            mcp.run(transport=transport)
            return
        raise


if __name__ == "__main__":
    main()
