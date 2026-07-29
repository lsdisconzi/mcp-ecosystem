# TorchAudio MCP Server

This folder contains a lightweight MCP server that exposes selected TorchAudio
functionalities as tools, with an optional MCPO proxy for HTTP/OpenAPI access.

## What is exposed

- `transcription_healthcheck`: server + dependency versions
- `transcription_audio_info`: inspect basic metadata and waveform stats
- `transcription_resample_audio`: resample and save audio files
- `transcription_extract_features`: compute spectrogram / mel-spectrogram / MFCC stats
- `transcription_list_asr_bundles`: list ASR-capable torchaudio bundles
- `transcription_transcribe_greedy`: ASR transcription with greedy decoding
- `transcription_list_project_paths`: quick project path discovery helper

## Development setup

From the repository root:

```bash
python3 -m venv .venv-mcp
source .venv-mcp/bin/activate
pip install -U pip
uv pip install -r mcp/requirements.txt
```

## Run as MCP (stdio)

```bash
python3 mcp/torchaudio_mcp/server.py
```

This mode is suitable for MCP clients that launch servers over stdio.

## Run as MCP over HTTP transport

```bash
MCP_TRANSPORT=streamable-http MCP_HOST=127.0.0.1 MCP_PORT=8765 \
python3 mcp/torchaudio_mcp/server.py
```

## Expose as MCPO tools (OpenAPI/HTTP proxy)

If you use `mcpo`, install it in the same virtual environment:

```bash
pip install mcpo
mcpo --port 8055 -- python3 mcp/torchaudio_mcp/server.py
```

Then your tools are available through MCPO at `http://127.0.0.1:8055`.

## Notes

- Some tools (like ASR) can download model checkpoints on first run.
- `transcription_transcribe_greedy` supports `cpu` and `cuda` devices.
- Audio read/write behavior depends on the torchaudio backend available in your environment.
