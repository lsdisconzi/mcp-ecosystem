#!/usr/bin/env python3
"""
ARGUS FRAMEWORK BUILDER — Primary Entrypoint
Port: 8029

Routes delegate immediately to application services; no business logic here.
DI wiring lives in infrastructure/di.py.
"""

import os

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename

from application.dto.framework_dtos import BuildRequestDto
from infrastructure.ai.deepseek_proxy_client import DeepseekProxyClient
from infrastructure.di import (
    build_analyzer_pack_builder,
    build_framework_build_service,
    build_law_registry,
    build_pdf_extractor,
)
from infrastructure.pdf.pdf_extractor import PdfExtractor

# ── Application factory ───────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB

# ── Service singletons (constructed once at startup via DI) ───────────────────

_framework_service = build_framework_build_service()
_pdf_extractor = build_pdf_extractor()
_ai_client = DeepseekProxyClient()
_law_registry = build_law_registry()
_pack_builder = build_analyzer_pack_builder()

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("frameworks.html")


@app.route("/view")
def view_template():
    template_path = request.args.get("path")
    if not template_path:
        return "Missing 'path' parameter", 400
    if ".." in template_path or template_path.startswith("/"):
        return "Invalid path", 400
    try:
        return render_template(template_path)
    except Exception as exc:
        app.logger.error(f"Template rendering error: {exc}")
        return f"Template not found: {template_path}", 404


@app.route("/api/extract_pdf_text", methods=["POST"])
def extract_pdf_text():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400
    try:
        extracted_text = _pdf_extractor.extract(file.stream)
        return jsonify({
            "success": True,
            "text": extracted_text,
            "filename": secure_filename(file.filename),
        })
    except ImportError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        app.logger.error(f"PDF extraction error: {exc}", exc_info=True)
        return jsonify({"error": f"Extraction failed: {exc}"}), 500


@app.route("/api/generate_config_from_text", methods=["POST"])
def generate_config_from_text():
    data = request.json or {}
    framework_text = data.get("framework_text")
    if not framework_text:
        return jsonify({"error": "Framework text is required"}), 400

    system_prompt = (
        "You are an expert legal analyst and software configuration specialist. "
        "Your task is to read a legal or ethical document and convert its key principles "
        "into a structured JSON object for an analysis tool. You must be precise and follow "
        "the output format exactly. Your response MUST be ONLY the raw JSON object, with no "
        "surrounding text, explanations, or markdown formatting."
    )
    user_prompt = f"""Analyze the following legal/ethical framework text and generate a JSON configuration object based on it.

**Your task is:**
1. Determine the official `framework_name`, `framework_type`, and `responsible_entity` from the text.
2. Identify 8-12 of the most important themes or categories of potential violations.
3. For each theme, create a key for the `analysis_focus` object.
4. For each key, create a robust regex pattern that can find the relevant articles or sections.
5. Generate a `js_function_name` in CamelCase based on the framework name.

**JSON Output Structure:**
{{
    "framework_name": "Official Name of the Framework",
    "framework_type": "e.g., Corporate Code of Conduct, National Law",
    "responsible_entity": "e.g., LATAM Airlines, Government of Chile",
    "analysis_focus": {{
        "Theme 1 Name": "regex pattern to find theme 1"
    }},
    "js_function_name": "injectFrameworkNamePanel"
}}

**Framework Text to Analyze:**
---
{framework_text[:20000]}
---
"""
    payload = {
        "model": "deepseek-reasoner",
        "stream": True,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }

    def event_stream():
        try:
            yield from _ai_client.stream(payload)
        except Exception as exc:
            app.logger.error(f"Stream error: {exc}")
            yield f'data: {{"error": "{exc}"}}\n\n'

    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")


@app.route("/api/build_framework", methods=["POST"])
def build_framework_analyzer():
    data = request.json or {}
    config_json_text = data.get("config_json")
    if not config_json_text:
        return jsonify({"error": "config_json is required."}), 400

    build_request = BuildRequestDto(
        framework_text=data.get("framework_text", ""),
        config_json_text=config_json_text,
        output_filename=data.get("output_filename", "generatedAnalyzer.js"),
        output_language=data.get("output_language", "en"),
    )

    result = _framework_service.build(build_request)

    if not result.success:
        status = 400 if "required" in (result.error or "") or "Invalid JSON" in (result.error or "") else 500
        return jsonify({"error": result.error}), status

    return jsonify({
        "success": True,
        "generated_prompt": result.generated_prompt,
        "generated_js": result.generated_js,
        "filename": secure_filename(result.filename),
        "parser_used": result.parser_used,
        "language_used": result.language_used,
    })


# ── Law corpus routes ─────────────────────────────────────────────────────────

@app.route("/api/law/frameworks")
def law_frameworks():
    """List all frameworks in the law corpus, optionally filtered by jurisdiction."""
    jurisdiction = request.args.get("jurisdiction")
    if jurisdiction:
        return jsonify(_law_registry.frameworks_for_jurisdiction(jurisdiction))
    return jsonify(_law_registry.list_frameworks())


@app.route("/api/law/frameworks/<code>")
def law_framework_meta(code: str):
    """Return metadata for a single framework."""
    meta = _law_registry.get_framework_meta(code)
    if meta is None:
        return jsonify({"error": f"Framework '{code}' not found"}), 404
    return jsonify(meta)


@app.route("/api/law/frameworks/<code>/articles")
def law_framework_articles(code: str):
    """Return all articles for a framework, optionally filtered by theme."""
    theme = request.args.get("theme")
    if theme:
        articles = _law_registry.articles_by_theme(code, theme)
    else:
        articles = _law_registry.articles_for_framework(code)
    if not articles and _law_registry.get_framework_meta(code) is None:
        return jsonify({"error": f"Framework '{code}' not found"}), 404
    return jsonify(articles)


@app.route("/api/law/frameworks/<code>/themes")
def law_framework_themes(code: str):
    """Return the unique themes for a framework."""
    if _law_registry.get_framework_meta(code) is None:
        return jsonify({"error": f"Framework '{code}' not found"}), 404
    return jsonify(_law_registry.themes_for_framework(code))


@app.route("/api/law/articles/<path:eli_id>")
def law_article(eli_id: str):
    """Return a single article by ELI id, e.g. /api/law/articles/BR.CBA.T3.C1.Art.74"""
    article = _law_registry.get_article(eli_id)
    if article is None:
        return jsonify({"error": f"Article '{eli_id}' not found"}), 404
    return jsonify(article)


# ── Analyzer pack routes ──────────────────────────────────────────────────────

@app.route("/api/pack/build", methods=["POST"])
def build_pack():
    """
    Build a golden v2.4 analyzer pack for a law framework.

    Body (JSON): {"framework_code": "CBA", "save": true}

    Returns the pack contents (js_content, config_json, generated_prompt) and
    optionally writes them to data/analyzers/{code}Analyzer/.
    """
    data = request.get_json(silent=True) or {}
    code = data.get("framework_code") or data.get("code")
    if not code:
        return jsonify({"error": "framework_code is required"}), 400

    result = _pack_builder.build(code)
    if not result.success:
        status = 404 if result.error and "not found" in result.error.lower() else 500
        return jsonify({"error": result.error}), status

    response = {
        "success": True,
        "framework_code": result.framework_code,
        "js_filename": result.js_filename,
        "js_content": result.js_content,
        "config_json": result.config,
        "generated_prompt": result.generated_prompt,
    }

    if data.get("save", False):
        save_result = _save_pack(result)
        response["saved_to"] = save_result

    return jsonify(response)


@app.route("/api/pack/build/<string:code>", methods=["GET"])
def build_pack_get(code: str):
    """Convenience GET endpoint — build and save pack, return paths."""
    result = _pack_builder.build(code)
    if not result.success:
        status = 404 if result.error and "not found" in result.error.lower() else 500
        return jsonify({"error": result.error}), status

    saved = _save_pack(result)
    return jsonify({
        "success": True,
        "framework_code": result.framework_code,
        "js_filename": result.js_filename,
        "saved_to": saved,
    })


def _save_pack(result) -> str:
    """Write pack files to data/analyzers/{code}Analyzer/ and return the directory path."""
    import json
    base = os.path.join(
        os.path.dirname(__file__), "data", "analyzers", result.framework_code + "Analyzer"
    )
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, result.js_filename), "w", encoding="utf-8") as fh:
        fh.write(result.js_content)
    with open(os.path.join(base, "config.json"), "w", encoding="utf-8") as fh:
        json.dump(result.config, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(base, "generated_prompt.txt"), "w", encoding="utf-8") as fh:
        fh.write(result.generated_prompt)
    return base


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() in ("1", "true", "yes")
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8029"))
    print("=" * 60)
    print("ARGUS FRAMEWORK BUILDER")
    print("=" * 60)
    print(f"URL: http://localhost:{port}")
    print(f"Debug: {debug_mode}")
    print("=" * 60)
    app.run(debug=debug_mode, host=host, port=port)

