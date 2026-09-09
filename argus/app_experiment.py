#!/usr/bin/env python3
"""
ARGUS FRAMEWORK BUILDER - Experimental / non-production branch
NOTE: This file is NOT the production entrypoint. Use app.py instead.
It was renamed from app_extra.py during the Phase 2 architectural consolidation.
It uses integrated_legal_framework_parser_v3 and includes attrs-based serialization.
Keep for reference until the v3 parser features are fully merged into the main app.
Port: 8029
"""

import datetime
from attrs import asdict
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from pathlib import Path
from werkzeug.utils import secure_filename
from ingestors.integrated_legal_framework_parser_v3 import IntegratedLegalFrameworkParser
import io, os, json, re, tempfile

app = Flask(__name__)
CORS(app)

# --- Configuration ---
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB limit

@app.route('/')
def index():
    """Main Legal Framework Builder"""
    return render_template('frameworks.html')

@app.route('/view')
def view_template():
    """Generic template viewer - serves frameworks.html"""
    template_path = request.args.get('path')
    if not template_path:
        return "Missing 'path' parameter", 400
    
    # Security: prevent directory traversal
    if ".." in template_path or template_path.startswith("/"):
        return "Invalid path", 400
    
    try:
        return render_template(template_path)
    except Exception as e:
        app.logger.error(f"Template rendering error: {e}")
        return f"Template not found: {template_path}", 404

@app.route('/api/extract_pdf_text', methods=['POST'])
def extract_pdf_text():
    """Extract text content from PDF file"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Only PDF files are supported'}), 400
        
        # Save temporarily
        temp_path = tempfile.mktemp(suffix='.pdf')
        file.save(temp_path)
        
        try:
            # Try pdfminer.six
            from pdfminer import extract_text
            extracted_text = extract_text(temp_path)
        except ImportError:
            # Fallback to PyPDF2
            try:
                import PyPDF2
                text_parts = []
                with open(temp_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        text_parts.append(page.extract_text())
                extracted_text = "\n".join(text_parts)
            except ImportError:
                return jsonify({'error': 'PDF extraction library not available. Install pdfminer.six or PyPDF2'}), 500
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        
        return jsonify({
            'success': True,
            'text': extracted_text,
            'filename': secure_filename(file.filename)
        })
    
    except Exception as e:
        app.logger.error(f"PDF extraction error: {e}", exc_info=True)
        return jsonify({'error': f'Extraction failed: {str(e)}'}), 500

@app.route('/api/generate_config_from_text', methods=['POST'])
def generate_config_from_text():
    """
    AI-powered config generation with streaming reasoning display
    """
    data = request.json
    framework_text = data.get('framework_text')
    
    if not framework_text:
        return jsonify({'error': 'Framework text is required'}), 400
    
    system_prompt = """
You are an expert legal analyst and software configuration specialist. Your task is to read a legal or ethical document and convert its key principles into a structured JSON object for an analysis tool. You must be precise and follow the output format exactly. Your response MUST be ONLY the raw JSON object, with no surrounding text, explanations, or markdown formatting.
"""
    
    user_prompt = f"""
Analyze the following legal/ethical framework text and generate a JSON configuration object based on it.

**Your task is:**
1. Determine the official `framework_name`, `framework_type`, and `responsible_entity` from the text.
2. Identify 8-12 of the most important themes or categories of potential violations within the text. These should be high-level concepts like "Customer Rights," "Data Privacy," "Anti-Corruption," or "Workplace Dignity."
3. For each theme, create a key for the `analysis_focus` object.
4. For each key, create a robust regex pattern that can find the relevant articles or sections in the text. The regex should be a string, with backslashes properly escaped for JSON.
5. Generate a `js_function_name` in CamelCase based on the framework name.

**JSON Output Structure:**
{{
    "framework_name": "Official Name of the Framework",
    "framework_type": "e.g., Corporate Code of Conduct, National Law",
    "responsible_entity": "e.g., LATAM Airlines, Government of Chile",
    "analysis_focus": {{
        "Theme 1 Name": "regex pattern to find theme 1",
        "Theme 2 Name": "regex pattern to find theme 2"
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
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1
    }
    
    endpoint_url = "http://localhost:8019/v1/assistants/deepseek-stream-proxy"
    
    def event_stream():
        try:
            import requests
            response = requests.post(endpoint_url, json=payload, stream=True, timeout=120)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line:
                    yield line.decode('utf-8') + '\n'
        except Exception as e:
            app.logger.error(f"Stream error: {e}")
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"
    
    return Response(stream_with_context(event_stream()), mimetype='text/event-stream')

# In the build_framework_analyzer function (around line 150-250), add:
@app.route('/api/build_framework', methods=['POST'])
def build_framework_analyzer():
    """
    Generate framework analyzer using integrated parser ONLY
    """
    data = request.json
    framework_text = data.get('framework_text')
    config_json_text = data.get('config_json')
    output_filename = data.get('output_filename', 'generatedAnalyzer.js')
    output_language = data.get('output_language', 'en')
    include_canonical = data.get('include_canonical', True)
    
    if not framework_text or not config_json_text:
        return jsonify({'error': 'Framework text and config JSON are required.'}), 400
    
    try:
        # Parse config
        try:
            config = json.loads(config_json_text)
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Invalid JSON configuration: {str(e)}'}), 400
        
        if 'framework_name' not in config:
            return jsonify({'error': 'Configuration missing required key: framework_name'}), 400
        
        # Initialize integrated parser
        app.logger.info(f"Using INTEGRATED framework parser with language: {output_language}")
        legal_parser = IntegratedLegalFrameworkParser()
        
        # Generate framework code BEFORE detection (so detection can override if needed)
        framework_name = config.get('framework_name', 'Legal Framework')
        framework_code = legal_parser._get_framework_code(framework_name)
        config['framework_code'] = framework_code
        
        # Detect framework characteristics
        try:
            detected_info = legal_parser.detect_framework_characteristics(framework_text)
            if detected_info:
                config.update(detected_info)
                # Recalculate framework code based on detected name if available
                if 'detected_name' in detected_info and detected_info['detected_name']:
                    detected_code = legal_parser._get_framework_code(detected_info['detected_name'])
                    config['framework_code'] = detected_code
        except Exception as detect_err:
            app.logger.warning(f"Detection failed: {detect_err}")
        
        # Add language and canonical flag
        config['output_language'] = output_language
        config['include_canonical'] = include_canonical
        
        # UI strings for different languages
        ui_strings = {
            'en': {
                'analyze_button': 'Analyze',
                'reset_button': 'Reset',
                'placeholder': 'Paste your text here...',
                'results_heading': 'Analysis Results',
                'copy_button': 'Copy Results',
                'no_violations': 'No issues found.',
                'violations_found': 'Potential issues found:',
                'see_details': 'See details',
                'violation_text': 'The text may violate',
                'references': 'References',
                'download_report': 'Download Report',
                'canonical_format': 'Canonical Format',
                'violation_id': 'Violation ID',
                'evidence_hash': 'Evidence Hash',
                'generate_canonical': 'Generate Canonical Output',
                'copy_canonical': 'Copy Canonical JSON',
                'view_graph': 'View Graph Structure'
            },
            'es': {
                'analyze_button': 'Analizar',
                'reset_button': 'Restablecer',
                'placeholder': 'Pegue su texto aquí...',
                'results_heading': 'Resultados del Análisis',
                'copy_button': 'Copiar Resultados',
                'no_violations': 'No se encontraron problemas.',
                'violations_found': 'Posibles problemas encontrados:',
                'see_details': 'Ver detalles',
                'violation_text': 'El texto puede violar',
                'references': 'Referencias',
                'download_report': 'Descargar Informe',
                'canonical_format': 'Formato Canónico',
                'violation_id': 'ID de Violación',
                'evidence_hash': 'Hash de Evidencia',
                'generate_canonical': 'Generar Salida Canónica',
                'copy_canonical': 'Copiar JSON Canónico',
                'view_graph': 'Ver Estructura de Gráfico'
            },
            'pt': {
                'analyze_button': 'Analisar',
                'reset_button': 'Redefinir',
                'placeholder': 'Cole seu texto aqui...',
                'results_heading': 'Resultados da Análise',
                'copy_button': 'Copiar Resultados',
                'no_violations': 'Nenhum problema encontrado.',
                'violations_found': 'Possíveis problemas encontrados:',
                'see_details': 'Ver detalhes',
                'violation_text': 'O texto pode violar',
                'references': 'Referências',
                'download_report': 'Baixar Relatório',
                'canonical_format': 'Formato Canônico',
                'violation_id': 'ID de Violação',
                'evidence_hash': 'Hash de Evidência',
                'generate_canonical': 'Gerar Saída Canônica',
                'copy_canonical': 'Copiar JSON Canônico',
                'view_graph': 'Ver Estrutura do Grafo'
            }
        }
        
        if output_language not in ui_strings:
            app.logger.warning(f"Language '{output_language}' not supported, falling back to English")
            output_language = 'en'
        
        config['ui_strings'] = ui_strings[output_language]
        
        # Extract sections/articles
        try:
            extracted_sections = legal_parser.extract_legal_articles_with_context(framework_text)
        except Exception as extraction_error:
            app.logger.error(f"Extraction error: {extraction_error}", exc_info=True)
            extracted_sections = {"Full Document": {"content": framework_text, "metadata": {}}}
        
        # Build enhanced prompt and generate JS
        try:
            full_prompt = legal_parser.build_enhanced_legal_prompt(config, extracted_sections, framework_text)
            
            # Generate canonical schema for JS with correct framework code
            canonical_schema = legal_parser.generate_canonical_schema(config)
            config['canonical_schema'] = canonical_schema
            
            fd, temp_path = tempfile.mkstemp(suffix='.js')
            try:
                os.close(fd)
                legal_parser.generate_integrated_js_analyzer(config, full_prompt, temp_path)
                with open(temp_path, 'r', encoding='utf-8') as f:
                    js_content = f.read()
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        
        except Exception as gen_error:
            app.logger.error(f"JS generation error: {gen_error}", exc_info=True)
            return jsonify({'error': f'Error generating JS: {str(gen_error)}'}), 500
        
        return jsonify({
            'success': True,
            'generated_prompt': full_prompt,
            'generated_js': js_content,
            'filename': secure_filename(output_filename),
            'parser_used': 'integrated',
            'language_used': output_language,
            'framework_code': framework_code,  # Return the generated code
            'canonical_enabled': include_canonical,
            'canonical_schema': canonical_schema if include_canonical else None
        })
    
    except Exception as e:
        app.logger.error(f"Framework build error: {e}", exc_info=True)
        return jsonify({'error': f'An internal error occurred: {str(e)}'}), 500
    


@app.route('/api/extract_canonical', methods=['POST'])
def extract_canonical():
    """
    Extract canonical violations from analysis output directly
    """
    try:
        data = request.json
        analysis_output = data.get('analysis_output')
        framework = data.get('framework', 'Unknown Framework')
        framework_code = data.get('framework_code', 'UNK')
        
        if not analysis_output:
            return jsonify({'error': 'Analysis output is required'}), 400
        
        # Extract canonical JSON block
        canonical_pattern = r'```canonical\s*\n([\s\S]*?)\n```'
        match = re.search(canonical_pattern, analysis_output)
        
        if match:
            try:
                canonical_json = json.loads(match.group(1))
                return jsonify({
                    'success': True,
                    'canonical_violations': canonical_json,
                    'format': 'embedded_json',
                    'count': len(canonical_json) if isinstance(canonical_json, list) else 1
                })
            except json.JSONDecodeError:
                # Try to parse as array of JSON objects
                lines = match.group(1).strip().split('\n')
                violations = []
                for line in lines:
                    line = line.strip()
                    if line.startswith('{') and line.endswith('}'):
                        try:
                            violations.append(json.loads(line))
                        except:
                            continue
                
                if violations:
                    return jsonify({
                        'success': True,
                        'canonical_violations': violations,
                        'format': 'line_delimited',
                        'count': len(violations)
                    })
        
        # If no canonical block found, try to extract from standard analysis format
        violations = []
        
        # Pattern for standard violation format
        violation_pattern = r'([a-z]\))\s+([^\n]+)\s*\n\nTranscript Evidence:\s*(.*?)\n\nLegal Reference:\s*(.*?)\n\nAnalysis:\s*(.*?)(?=\n\n[a-z]\)|\n\n####|\Z)'
        
        for match in re.finditer(violation_pattern, analysis_output, re.DOTALL):
            letter = match.group(1)
            violation_type = match.group(2).strip()
            evidence = match.group(3).strip()
            legal_ref = match.group(4).strip()
            analysis = match.group(5).strip()
            
            # Extract severity from analysis
            severity = "UNKNOWN"
            for sev in ["HIGH", "MEDIUM", "LOW", "CRITICAL", "ALTA", "MODERADA", "BAIXA"]:
                if sev in analysis.upper():
                    severity = sev
                    break
            
            # Generate deterministic IDs
            import hashlib
            from datetime import datetime
            
            case_id = f"CASE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Extract article code from legal reference
            article_match = re.search(r'Article\s*(\d+[a-z]?)|Art\.\s*(\d+[º°]?)', legal_ref, re.IGNORECASE)
            article_code = article_match.group(1) or article_match.group(2) if article_match else "UNK"
            
            # Generate violation ID
            violation_hash = hashlib.sha256(
                f"{case_id}|{framework_code}|{article_code}|{violation_type}".encode()
            ).hexdigest()[:12]
            
            # Generate evidence ID
            evidence_hash = hashlib.sha256(
                f"{case_id}|transcript|{evidence[:50]}".encode()
            ).hexdigest()[:8]
            
            # Generate action ID
            action_hash = hashlib.sha256(
                f"{violation_hash}|{violation_type}".encode()
            ).hexdigest()[:8]
            
            canonical_violation = {
                "violation_id": f"VIOL_{violation_hash}",
                "case_id": case_id,
                "jurisdiction": framework_code[:10].upper(),
                "framework_code": framework_code,
                "violation_type": violation_type,
                "severity": severity.upper() if severity != "UNKNOWN" else "MEDIUM",
                "confidence": 0.85,
                "status": "OPEN",
                "actor_ids": [],  # Fixed actor IDs
                "action_ids": [f"ACTN_{action_hash}"],
                "legal_article_ids": [article_match],  # Use normalized article ID
                "evidence_ids": [f"EVID_{evidence_hash}"],
                "checksum": hashlib.sha256(
                    f"{case_id}{framework_code}{violation_type}".encode()
                ).hexdigest()[:32]
            }
            
            violations.append(canonical_violation)
        
        if violations:
            return jsonify({
                'success': True,
                'canonical_violations': violations,
                'format': 'extracted',
                'count': len(violations)
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No canonical violations found or extractable',
                'suggestion': 'Ensure analysis includes the canonical output format'
            }), 404
            
    except Exception as e:
        app.logger.error(f"Canonical extraction error: {e}", exc_info=True)
        return jsonify({'error': f'Canonical extraction failed: {str(e)}'}), 500
    
    

if __name__ == '__main__':
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() in ("1", "true", "yes")
    print("=" * 60)
    print("🏗️  ARGUS FRAMEWORK BUILDER")
    print("=" * 60)
    print(f"📍 URL: http://localhost:8029")
    print(f"🔧 Framework Builder UI: http://localhost:8029/view?path=frameworks/frameworks.html")
    print(f"📋 Dashboard: http://localhost:8029/")
    print(f"🐛 Debug: {debug_mode}")
    print("=" * 60)
    app.run(debug=debug_mode, port=8029)
