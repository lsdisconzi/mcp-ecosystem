"""
TorchAudio Web Application - FastAPI Backend
Provides REST API endpoints for all torchaudio audio processing capabilities.
"""

import io
import tempfile
import os
from pathlib import Path
from typing import Optional

import torch
import torchaudio
from fastapi import FastAPI, File, UploadFile, Form, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

app = FastAPI(title="TorchAudio Processing Suite", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session storage for processed audio
sessions: dict[str, dict] = {}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _tensor_to_wav_bytes(waveform: torch.Tensor, sample_rate: int) -> bytes:
    """Convert a waveform tensor to WAV bytes."""
    waveform = waveform.cpu().detach()
    # Ensure correct shape [channels, time]
    if waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)

    # TorchCodec-backed save can reject BytesIO destinations. Try in-memory first,
    # then fallback to a temporary .wav path so the muxer can infer a valid format.
    buf = io.BytesIO()
    try:
        torchaudio.save(buf, waveform, sample_rate, format="wav", channels_first=True)
        buf.seek(0)
        return buf.read()
    except Exception:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            torchaudio.save(tmp_path, waveform, sample_rate, format="wav", channels_first=True)
            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _load_upload(upload: UploadFile) -> tuple[torch.Tensor, int]:
    """Load an uploaded file into a waveform tensor."""
    contents = upload.file.read()
    buf = io.BytesIO(contents)
    buf.seek(0)
    waveform, sample_rate = torchaudio.load(buf)
    return waveform, sample_rate


def _get_session(session_id: str) -> dict:
    if session_id not in sessions:
        sessions[session_id] = {}
    return sessions[session_id]


# ──────────────────────────────────────────────
# 1. AUDIO I/O
# ──────────────────────────────────────────────

@app.post("/api/upload")
async def upload_audio(file: UploadFile = File(...)):
    """Upload an audio file and return its info."""
    try:
        waveform, sample_rate = _load_upload(file)
        duration = waveform.shape[-1] / sample_rate
        return JSONResponse({
            "filename": file.filename,
            "sample_rate": sample_rate,
            "channels": waveform.shape[0] if waveform.dim() > 1 else 1,
            "num_frames": waveform.shape[-1],
            "duration": round(duration, 3),
            "dtype": str(waveform.dtype),
            "max_amplitude": round(waveform.abs().max().item(), 4),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/upload-session")
async def upload_to_session(file: UploadFile = File(...), session_id: str = Form("default")):
    """Upload audio and store in session for subsequent processing."""
    try:
        waveform, sample_rate = _load_upload(file)
        session = _get_session(session_id)
        session["waveform"] = waveform
        session["sample_rate"] = sample_rate
        return JSONResponse({
            "status": "ok",
            "sample_rate": sample_rate,
            "channels": waveform.shape[0] if waveform.dim() > 1 else 1,
            "num_frames": waveform.shape[-1],
            "duration": round(waveform.shape[-1] / sample_rate, 3),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/audio/{session_id}")
async def get_audio(session_id: str):
    """Download the processed audio from a session."""
    session = _get_session(session_id)
    if "waveform" not in session:
        return JSONResponse({"error": "No audio in session"}, status_code=404)
    wav_bytes = _tensor_to_wav_bytes(session["waveform"], session["sample_rate"])
    return JSONResponse({
        "audio_base64": _array_to_b64(session["waveform"], session["sample_rate"]),
        "sample_rate": session["sample_rate"],
    })


# ──────────────────────────────────────────────
# 2. FILTERS & EQUALIZATION
# ──────────────────────────────────────────────

FILTER_TYPES = {
    "lowpass": torchaudio.functional.lowpass_biquad,
    "highpass": torchaudio.functional.highpass_biquad,
    "bandpass": torchaudio.functional.bandpass_biquad,
    "bandreject": torchaudio.functional.bandreject_biquad,
    "allpass": torchaudio.functional.allpass_biquad,
    "bass": torchaudio.functional.bass_biquad,
    "treble": torchaudio.functional.treble_biquad,
    "equalizer": torchaudio.functional.equalizer_biquad,
}

# Maps filter type -> parameter names (beyond waveform, sample_rate)
FILTER_PARAMS = {
    "lowpass": ("cutoff_freq", "Q"),
    "highpass": ("cutoff_freq", "Q"),
    "bandpass": ("central_freq", "Q"),
    "bandreject": ("central_freq", "Q"),
    "allpass": ("central_freq", "Q"),
    "bass": ("gain", "central_freq", "Q"),
    "treble": ("gain", "central_freq", "Q"),
    "equalizer": ("central_freq", "gain", "Q"),
}

@app.post("/api/filter")
async def apply_filter(
    file: UploadFile = File(...),
    filter_type: str = Form(...),
    cutoff_freq: float = Form(1000.0),
    Q: float = Form(0.707),
    gain_db: float = Form(0.0),
    central_freq: float = Form(1000.0),
):
    """Apply a biquad filter to the audio."""
    try:
        waveform, sample_rate = _load_upload(file)
        if filter_type not in FILTER_TYPES:
            return JSONResponse({"error": f"Unknown filter: {filter_type}. Choose from {list(FILTER_TYPES.keys())}"}, status_code=400)

        func = FILTER_TYPES[filter_type]
        params = {
            "cutoff_freq": cutoff_freq,
            "Q": Q,
            "gain": gain_db,
            "central_freq": central_freq,
        }

        # Build kwargs using only the params this filter expects
        kwargs = {"waveform": waveform, "sample_rate": sample_rate}
        for pname in FILTER_PARAMS.get(filter_type, ()):
            kwargs[pname] = params.get(pname, 0.0)

        filtered = func(**kwargs)

        return JSONResponse({
            "audio_base64": _tensor_to_b64(filtered, sample_rate),
            "sample_rate": sample_rate,
            "applied": filter_type,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# Full parametric chain
@app.post("/api/filter-chain")
async def apply_filter_chain(
    file: UploadFile = File(...),
    filters: str = Form(...),  # JSON array of filter specs
):
    """Apply a chain of filters."""
    try:
        waveform, sample_rate = _load_upload(file)
        import json
        filter_list = json.loads(filters)
        result = waveform
        for spec in filter_list:
            ftype = spec["type"]
            if ftype not in FILTER_TYPES:
                continue
            func = FILTER_TYPES[ftype]
            args = {"waveform": result, "sample_rate": sample_rate}
            args.update({k: v for k, v in spec.items() if k not in ("type",)})
            result = func(**{k: v for k, v in args.items()})
        wav_bytes = _tensor_to_wav_bytes(result, sample_rate)
        return JSONResponse({
            "audio_base64": _tensor_to_b64(result, sample_rate),
            "sample_rate": sample_rate,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ──────────────────────────────────────────────
# 3. AUDIO EFFECTS
# ──────────────────────────────────────────────

@app.post("/api/effects/gain")
async def apply_gain(file: UploadFile = File(...), gain_db: float = Form(0.0)):
    """Apply gain in dB to audio."""
    waveform, sample_rate = _load_upload(file)
    result = torchaudio.functional.gain(waveform, gain_db)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/effects/dither")
async def apply_dither(
    file: UploadFile = File(...),
    density_function: str = Form("TPDF"),
    noise_shaping: bool = Form(False),
):
    """Apply dithering to audio."""
    waveform, sample_rate = _load_upload(file)
    result = torchaudio.functional.dither(waveform, density_function=density_function, noise_shaping=noise_shaping)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/effects/dcshift")
async def apply_dcshift(file: UploadFile = File(...), shift: float = Form(0.0), limiter_gain: float = Form(0.0)):
    """Apply DC shift to audio."""
    waveform, sample_rate = _load_upload(file)
    result = torchaudio.functional.dcshift(waveform, shift, limiter_gain)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/effects/overdrive")
async def apply_overdrive(file: UploadFile = File(...), gain: float = Form(20.0), colour: float = Form(20.0)):
    """Apply overdrive distortion."""
    waveform, sample_rate = _load_upload(file)
    result = torchaudio.functional.overdrive(waveform, gain, colour)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/effects/contrast")
async def apply_contrast(file: UploadFile = File(...), enhancement_amount: float = Form(75.0)):
    """Apply contrast enhancement."""
    waveform, sample_rate = _load_upload(file)
    result = torchaudio.functional.contrast(waveform, enhancement_amount)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/effects/flanger")
async def apply_flanger(
    file: UploadFile = File(...),
    delay: float = Form(0.0),
    depth: float = Form(2.0),
    regen: float = Form(0.0),
    width: float = Form(71.0),
    speed: float = Form(0.5),
    phase: float = Form(25.0),
    modulation: str = Form("sinusoidal"),
    interpolation: str = Form("linear"),
):
    """Apply flanger effect."""
    waveform, sample_rate = _load_upload(file)
    result = torchaudio.functional.flanger(
        waveform, sample_rate,
        delay=delay, depth=depth, regen=regen,
        width=width, speed=speed, phase=phase,
        modulation=modulation, interpolation=interpolation,
    )
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/effects/phaser")
async def apply_phaser(
    file: UploadFile = File(...),
    gain_in: float = Form(0.4),
    gain_out: float = Form(0.74),
    delay_ms: float = Form(3.0),
    decay: float = Form(0.4),
    mod_speed: float = Form(0.5),
    sinusoidal: bool = Form(True),
):
    """Apply phaser effect."""
    waveform, sample_rate = _load_upload(file)
    result = torchaudio.functional.phaser(
        waveform, sample_rate,
        gain_in=gain_in, gain_out=gain_out,
        delay_ms=delay_ms, decay=decay,
        mod_speed=mod_speed, sinusoidal=sinusoidal,
    )
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


# ──────────────────────────────────────────────
# 4. VOICE ENHANCEMENT
# ──────────────────────────────────────────────

@app.post("/api/enhance/pitch-shift")
async def pitch_shift(file: UploadFile = File(...), n_steps: float = Form(0.0)):
    """Shift the pitch of the audio by n_steps semitones."""
    waveform, sample_rate = _load_upload(file)
    result = torchaudio.functional.pitch_shift(waveform, sample_rate, n_steps)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/enhance/speed")
async def change_speed(file: UploadFile = File(...), factor: float = Form(1.0)):
    """Change the speed of audio (also affects pitch)."""
    waveform, sample_rate = _load_upload(file)
    result, _ = torchaudio.functional.speed(waveform, sample_rate, factor)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/enhance/preemphasis")
async def preemphasis(file: UploadFile = File(...), coeff: float = Form(0.97)):
    """Apply pre-emphasis filter to boost high frequencies (enhance clarity)."""
    waveform, sample_rate = _load_upload(file)
    result = torchaudio.functional.preemphasis(waveform, coeff)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/enhance/deemphasis")
async def deemphasis(file: UploadFile = File(...), coeff: float = Form(0.97)):
    """Apply de-emphasis filter."""
    waveform, sample_rate = _load_upload(file)
    result = torchaudio.functional.deemphasis(waveform, coeff)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/enhance/volume")
async def change_volume(file: UploadFile = File(...), gain_type: str = Form("amplitude"), gain_value: float = Form(1.0)):
    """Change volume - amplitude multiplier or dB."""
    waveform, sample_rate = _load_upload(file)
    if gain_type == "amplitude":
        result = waveform * gain_value
    else:
        result = torchaudio.functional.gain(waveform, gain_value)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/enhance/fade")
async def apply_fade(
    file: UploadFile = File(...),
    fade_in: float = Form(0.0),
    fade_out: float = Form(0.0),
    fade_shape: str = Form("linear"),
):
    """Apply fade in/out to audio (duration in seconds)."""
    waveform, sample_rate = _load_upload(file)
    transform = torchaudio.transforms.Fade(
        fade_in_len=int(fade_in * sample_rate),
        fade_out_len=int(fade_out * sample_rate),
        fade_shape=fade_shape,
    )
    result = transform(waveform)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/enhance/add-noise")
async def add_noise(
    file: UploadFile = File(...),
    snr_db: float = Form(20.0),
    noise_type: str = Form("gaussian"),
):
    """Add noise to audio at given SNR."""
    waveform, sample_rate = _load_upload(file)
    if noise_type == "gaussian":
        noise = torch.randn_like(waveform)
    elif noise_type == "uniform":
        noise = (torch.rand_like(waveform) * 2) - 1
    else:
        noise = torch.randn_like(waveform)
    result = torchaudio.functional.add_noise(waveform, noise, snr=torch.tensor([snr_db]))
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


# ──────────────────────────────────────────────
# 5. SPECTRAL ANALYSIS
# ──────────────────────────────────────────────

@app.post("/api/analysis/spectrogram")
async def compute_spectrogram(
    file: UploadFile = File(...),
    n_fft: int = Form(400),
    hop_length: int = Form(160),
    power: float = Form(2.0),
    to_db: bool = Form(True),
):
    """Compute spectrogram data for visualization."""
    waveform, sample_rate = _load_upload(file)
    # Use only first channel for visualization
    mono = waveform.mean(dim=0, keepdim=True) if waveform.shape[0] > 1 else waveform
    transform = torchaudio.transforms.Spectrogram(
        n_fft=n_fft,
        hop_length=hop_length,
        power=power,
    )
    spec = transform(mono)
    if to_db:
        spec = torchaudio.transforms.AmplitudeToDB()(spec)
    spec_data = spec[0].cpu().detach().numpy().tolist()
    return JSONResponse({
        "spectrogram": spec_data,
        "freq_bins": spec.shape[1],
        "time_frames": spec.shape[2],
        "sample_rate": sample_rate,
    })


@app.post("/api/analysis/mel-spectrogram")
async def compute_mel_spectrogram(
    file: UploadFile = File(...),
    n_fft: int = Form(400),
    hop_length: int = Form(160),
    n_mels: int = Form(128),
    to_db: bool = Form(True),
):
    """Compute mel spectrogram."""
    waveform, sample_rate = _load_upload(file)
    mono = waveform.mean(dim=0, keepdim=True) if waveform.shape[0] > 1 else waveform
    transform = torchaudio.transforms.MelSpectrogram(
        sample_rate=sample_rate,
        n_fft=n_fft,
        hop_length=hop_length,
        n_mels=n_mels,
    )
    mel_spec = transform(mono)
    if to_db:
        mel_spec = torchaudio.transforms.AmplitudeToDB()(mel_spec)
    mel_data = mel_spec[0].cpu().detach().numpy().tolist()
    return JSONResponse({
        "mel_spectrogram": mel_data,
        "n_mels": n_mels,
        "time_frames": mel_spec.shape[2],
        "sample_rate": sample_rate,
    })


@app.post("/api/analysis/mfcc")
async def compute_mfcc(
    file: UploadFile = File(...),
    n_mfcc: int = Form(13),
    n_mels: int = Form(40),
    to_db: bool = Form(True),
):
    """Compute MFCC coefficients."""
    waveform, sample_rate = _load_upload(file)
    mono = waveform.mean(dim=0, keepdim=True) if waveform.shape[0] > 1 else waveform
    transform = torchaudio.transforms.MFCC(
        sample_rate=sample_rate,
        n_mfcc=n_mfcc,
        melkwargs={"n_mels": n_mels},
    )
    mfcc = transform(mono)
    mfcc_data = mfcc[0].cpu().detach().numpy().tolist()
    return JSONResponse({
        "mfcc": mfcc_data,
        "n_mfcc": n_mfcc,
        "time_frames": mfcc.shape[2],
        "sample_rate": sample_rate,
    })


@app.post("/api/analysis/loudness")
async def compute_loudness(file: UploadFile = File(...)):
    """Compute loudness (ITU-R BS.1770-4 recommendation)."""
    waveform, sample_rate = _load_upload(file)
    loudness_val = torchaudio.functional.loudness(waveform, sample_rate)
    return JSONResponse({
        "loudness": round(loudness_val.item(), 3),
    })


@app.post("/api/analysis/spectral-centroid")
async def compute_spectral_centroid(file: UploadFile = File(...)):
    """Compute spectral centroid."""
    waveform, sample_rate = _load_upload(file)
    centroid = torchaudio.functional.spectral_centroid(waveform, sample_rate)
    centroid_data = centroid[0].cpu().detach().numpy().tolist()
    return JSONResponse({
        "spectral_centroid": centroid_data,
        "sample_rate": sample_rate,
    })


@app.post("/api/analysis/pitch")
async def detect_pitch(file: UploadFile = File(...), freq_low: int = Form(85), freq_high: int = Form(3400)):
    """Detect fundamental frequency (pitch) of audio."""
    waveform, sample_rate = _load_upload(file)
    pitch = torchaudio.functional.detect_pitch_frequency(waveform, sample_rate, freq_low=freq_low, freq_high=freq_high)
    pitch_data = pitch.cpu().detach().numpy().tolist()
    return JSONResponse({
        "pitch": pitch_data,
        "sample_rate": sample_rate,
    })


# ──────────────────────────────────────────────
# 6. SOURCE SEPARATION (HDemucs)
# ──────────────────────────────────────────────

@app.post("/api/separate")
async def separate_sources(
    file: UploadFile = File(...),
    model_size: str = Form("low"),  # low, medium, high
):
    """
    Separate audio into sources using HDemucs.
    For music: drums, bass, other, vocals
    Model sizes: low (fast), medium (balanced), high (best quality).
    """
    # Note: This requires downloading the model on first use.
    try:
        waveform, sample_rate = _load_upload(file)

        # Load the appropriate model
        if model_size == "high":
            bundle = torchaudio.pipelines.HDEMUCS_HIGH_MUSDB_PLUS
        elif model_size == "medium":
            bundle = torchaudio.pipelines.HDEMUCS_HIGH_MUSDB
        else:
            # Use low by default (faster, less memory)
            from torchaudio.models import hdemucs_low
            model = hdemucs_low()
            # Try HDEMUCS_HIGH_MUSDB for medium; fall back to what's available
            bundle = None

        if bundle is not None:
            model = bundle.get_model()

        model.eval()

        # Ensure correct shape: [1, channels, time]
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)
        if waveform.dim() == 2:
            waveform = waveform.unsqueeze(0)

        # HDemucs requires the channel count to match its `audio_channels`
        # (default 2 / stereo). Convert mono → stereo by duplicating; downmix
        # >2 channels to stereo by averaging extra channels into L/R.
        expected_channels = int(getattr(model, "audio_channels", 2))
        cur_channels = waveform.shape[1]
        if cur_channels != expected_channels:
            if cur_channels == 1 and expected_channels == 2:
                waveform = waveform.repeat(1, 2, 1)
            elif cur_channels > expected_channels:
                # Downmix: average all channels, then expand to expected count
                mono = waveform.mean(dim=1, keepdim=True)
                waveform = mono.repeat(1, expected_channels, 1)
            else:
                # Generic upmix by repeating the first channel
                first = waveform[:, :1, :]
                waveform = first.repeat(1, expected_channels, 1)

        # Resample to 44100 if needed (HDemucs expects 44100)
        expected_sr = getattr(bundle, 'sample_rate', 44100) if bundle else 44100
        if sample_rate != expected_sr:
            waveform = torchaudio.functional.resample(waveform, sample_rate, expected_sr)
            sample_rate = expected_sr

        with torch.no_grad():
            sources = model(waveform)  # [1, num_sources, channels, time]

        sources = sources[0]  # remove batch dim
        source_names = ["drums", "bass", "other", "vocals"]

        result = {}
        for i, name in enumerate(source_names):
            if i < sources.shape[0]:
                src_waveform = sources[i]  # [channels, time]
                result[name] = _tensor_to_b64(src_waveform, sample_rate)

        result["sample_rate"] = sample_rate
        result["source_names"] = source_names[:sources.shape[0]]
        return JSONResponse(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": f"Source separation failed: {str(e)}"}, status_code=500)


# ──────────────────────────────────────────────
# 7. VOICE ACTIVITY DETECTION
# ──────────────────────────────────────────────

@app.post("/api/vad")
async def voice_activity_detection(
    file: UploadFile = File(...),
    trigger_level: float = Form(7.0),
):
    """Detect voice activity regions in audio."""
    waveform, sample_rate = _load_upload(file)
    vad_result = torchaudio.functional.vad(waveform, sample_rate, trigger_level=trigger_level)
    vad_data = vad_result.cpu().detach().numpy().tolist()
    return JSONResponse({
        "vad": vad_data,
        "sample_rate": sample_rate,
    })


# ──────────────────────────────────────────────
# 8. RESAMPLE
# ──────────────────────────────────────────────

@app.post("/api/resample")
async def resample_audio(
    file: UploadFile = File(...),
    target_sr: int = Form(16000),
):
    """Resample audio to target sample rate."""
    waveform, sample_rate = _load_upload(file)
    if sample_rate == target_sr:
        result = waveform
    else:
        result = torchaudio.functional.resample(waveform, sample_rate, target_sr)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, target_sr),
        "sample_rate": target_sr,
    })


# ──────────────────────────────────────────────
# 9. CONVOLVE / REVERB SIMULATION
# ──────────────────────────────────────────────

@app.post("/api/effects/convolve")
async def apply_convolve(file: UploadFile = File(...), mode: str = Form("full")):
    """Apply convolution (useful for reverb simulation)."""
    waveform, sample_rate = _load_upload(file)
    # Use a simple reverb-like impulse response
    ir_len = int(sample_rate * 0.3)  # 300ms reverb
    ir = torch.exp(-torch.linspace(0, 5, ir_len)) * torch.cos(torch.linspace(0, 20 * 3.14159, ir_len))
    ir = ir.unsqueeze(0)  # [1, time]
    result = torchaudio.functional.fftconvolve(waveform, ir, mode=mode)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


@app.post("/api/effects/ir-convolve")
async def apply_ir_convolve(file: UploadFile = File(...), ir_file: UploadFile = File(...), mode: str = Form("full")):
    """Convolve audio with a custom impulse response file."""
    waveform, sample_rate = _load_upload(file)
    ir_waveform, ir_sr = _load_upload(ir_file)
    if ir_sr != sample_rate:
        ir_waveform = torchaudio.functional.resample(ir_waveform, ir_sr, sample_rate)
    result = torchaudio.functional.fftconvolve(waveform, ir_waveform, mode=mode)
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


# ──────────────────────────────────────────────
# 10. TIME STRETCH
# ──────────────────────────────────────────────

@app.post("/api/enhance/time-stretch")
async def time_stretch(file: UploadFile = File(...), rate: float = Form(1.0)):
    """Time-stretch audio without changing pitch."""
    waveform, sample_rate = _load_upload(file)
    transform = torchaudio.transforms.TimeStretch(rate=rate)
    # TimeStretch works on complex spectrograms
    spec = torch.stft(
        waveform,
        n_fft=512,
        hop_length=128,
        return_complex=True,
    )
    stretched = transform(spec)
    result = torch.istft(stretched, n_fft=512, hop_length=128, return_complex=False, length=waveform.shape[-1])
    return JSONResponse({
        "audio_base64": _tensor_to_b64(result, sample_rate),
        "sample_rate": sample_rate,
    })


# ──────────────────────────────────────────────
# 11. INFO
# ──────────────────────────────────────────────

@app.get("/api/info")
async def get_info():
    """Get information about available functionality."""
    return JSONResponse({
        "version": torchaudio.__version__ if hasattr(torchaudio, '__version__') else "unknown",
        "torch_version": torch.__version__,
        "available_transforms": [
            {"name": "Spectrogram", "category": "spectral", "desc": "Compute the spectrogram of audio"},
            {"name": "MelSpectrogram", "category": "spectral", "desc": "Compute mel-frequency spectrogram"},
            {"name": "MFCC", "category": "spectral", "desc": "Mel-frequency cepstral coefficients"},
            {"name": "LFCC", "category": "spectral", "desc": "Linear-frequency cepstral coefficients"},
            {"name": "AmplitudeToDB", "category": "spectral", "desc": "Convert amplitude/power to dB scale"},
            {"name": "GriffinLim", "category": "spectral", "desc": "Phase reconstruction from spectrogram"},
            {"name": "ComputeDeltas", "category": "spectral", "desc": "Compute delta coefficients (first/second order derivatives)"},
            {"name": "SpectralCentroid", "category": "analysis", "desc": "Spectral centroid (brightness)"},
            {"name": "Loudness", "category": "analysis", "desc": "ITU-R BS.1770-4 loudness measurement"},
            {"name": "PitchShift", "category": "voice", "desc": "Shift pitch without changing speed"},
            {"name": "TimeStretch", "category": "voice", "desc": "Change speed without changing pitch (phase vocoder)"},
            {"name": "Speed", "category": "voice", "desc": "Change speed (with pitch change)"},
            {"name": "Preemphasis", "category": "voice", "desc": "Boost high frequencies for voice clarity"},
            {"name": "Deemphasis", "category": "voice", "desc": "Attenuate high frequencies"},
            {"name": "Resample", "category": "io", "desc": "Change sample rate"},
            {"name": "Fade", "category": "editing", "desc": "Fade in/out"},
            {"name": "Vol", "category": "editing", "desc": "Adjust volume"},
            {"name": "AddNoise", "category": "editing", "desc": "Mix noise at specified SNR"},
            {"name": "VAD", "category": "analysis", "desc": "Voice Activity Detection"},
        ],
        "available_filters": [
            {"name": "Lowpass Biquad", "param": "cutoff_freq, Q"},
            {"name": "Highpass Biquad", "param": "cutoff_freq, Q"},
            {"name": "Bandpass Biquad", "param": "central_freq, Q"},
            {"name": "Bandreject Biquad", "param": "central_freq, Q"},
            {"name": "Allpass Biquad", "param": "central_freq, Q"},
            {"name": "Bass Biquad", "param": "central_freq, gain, Q"},
            {"name": "Treble Biquad", "param": "central_freq, gain, Q"},
            {"name": "Equalizer Biquad", "param": "central_freq, gain, Q"},
        ],
        "available_effects": [
            {"name": "Flanger"},
            {"name": "Phaser"},
            {"name": "Overdrive (distortion)"},
            {"name": "Contrast enhancement"},
            {"name": "DC Shift"},
            {"name": "Dither"},
            {"name": "Gain"},
            {"name": "Convolution (reverb)"},
        ],
        "available_models": [
            {"name": "HDemucs", "desc": "Music source separation (drums, bass, other, vocals)"},
            {"name": "ConvTasNet", "desc": "Speech source separation"},
            {"name": "Wav2Vec2", "desc": "Speech recognition / feature extraction"},
            {"name": "HuBERT", "desc": "Self-supervised speech model"},
            {"name": "WavLM", "desc": "Large-scale speech model"},
            {"name": "SquimObjective", "desc": "Speech quality assessment (PESQ, STOI)"},
            {"name": "SquimSubjective", "desc": "Speech subjective quality (MOS)"},
        ],
    })


# ──────────────────────────────────────────────
# Helper: Convert waveform to base64
# ──────────────────────────────────────────────

def _tensor_to_b64(tensor: torch.Tensor, sample_rate: int) -> str:
    """Convert a waveform tensor to a base64-encoded WAV string."""
    import base64
    wav_bytes = _tensor_to_wav_bytes(tensor, sample_rate)
    return base64.b64encode(wav_bytes).decode("utf-8")


def _array_to_b64(tensor: torch.Tensor, sample_rate: int) -> str:
    return _tensor_to_b64(tensor, sample_rate)


# ──────────────────────────────────────────────
# Serve static files and frontend
# ──────────────────────────────────────────────

# Mount static directory for JS modules if needed
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)


@app.get("/")
async def serve_frontend():
    """Serve the main HTML application."""
    html_path = Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return JSONResponse({"error": "index.html not found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8777)
