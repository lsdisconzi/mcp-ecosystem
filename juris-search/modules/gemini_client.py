import os
import json
import urllib.request
from typing import Optional, List, Dict, Any
from google import genai
from google.genai import types

from modules.config import DEFAULT_COURT

# Use the Google GenAI SDK which replaces vertexai and google-generativeai
# We attempt to initialize it. If the user runs `gcloud auth application-default login`,
# it will automatically pick up the credentials for Vertex AI.
# If they pass GEMINI_API_KEY, it will use that for generic models.

# User's Tuned Model deployed in Vertex AI
TUNED_MODEL_ENDPOINT = "projects/345835065613/locations/us-central1/endpoints/4411443510532636672"
PROJECT_ID = "awareness-498108"
LOCATION = "us-central1"

try:
    # Initialize for Vertex AI usage
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
except Exception as e:
    client = None
    print(f"Warning: Failed to initialize Vertex AI client. {e}")

async def retrieve_rag_context(query_text: str, collection_name: str = "la8159_master_index", limit: int = 5) -> str:
    """
    Queries the Qdrant Master Index (Garage API) for immutable context.
    """
    url = "http://127.0.0.1:8066/v1/qdrant/search"
    payload = {
        "query_text": query_text,
        "collection_name": collection_name,
        "limit": limit
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'},
                                 method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res = json.loads(response.read().decode())
            results = res.get("results", [])
    except Exception as e:
        print(f"Error querying Qdrant: {e}")
        results = []

    if not results:
        return ""
        
    context_parts = ["### CANONICAL CONTEXT (IMMUTABLE FACTS) ###"]
    for idx, r in enumerate(results):
        p = r.get("payload", {})
        doc_id = p.get("doc_id") or p.get("transcript_id") or f"DOC-{idx}"
        
        text = r.get("content") or p.get("text") or p.get("texto", "")
        if not text and "segments" in p:
            text = " ".join([seg.get("text", "") for seg in p["segments"]])
            
        data_type = p.get("data_type", "unknown")
        if "transcript_id" in p:
            data_type = "transcript"
        elif "numero_processo" in p:
            data_type = "law"
        
        context_parts.append(f"\n--- Document [{doc_id}] ({data_type}) ---")
        context_parts.append(str(text).strip())
        
    return "\n".join(context_parts)

async def chat_with_tuned_gemini(
    user_message: str,
    conversation: Optional[List[Dict[str, str]]] = None,
    file_text: Optional[str] = None,
    file_name: Optional[str] = None,
    court: Optional[str] = None,
) -> str:
    """
    Integrates the RAG context and the Fine-Tuned Gemini Model.
    """
    if not client:
        return ("⚠️ Cliente Vertex AI (Gemini) não configurado. "
                "Certifique-se de autenticar usando `gcloud auth application-default login`.")

    # 1. Fetch RAG Context
    context = await retrieve_rag_context(user_message)
    
    # 2. Build Prompt
    system_instruction = "You are a specialized legal AI assistant trained on aviation jurisprudence, regulatory frameworks, and forensic transcripts."
    
    prompt = ""
    if context:
        prompt += f"Review the following canonical context carefully before answering:\n{context}\n\n"
        
    if file_text:
        prompt += f"[Arquivo enviado: {file_name or 'documento'}]\n\nConteúdo extraído:\n{file_text[:6000]}\n\n"
        
    prompt += f"### USER QUERY ###\n{user_message}"

    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    ]
    
    try:
        response = client.models.generate_content(
            model=TUNED_MODEL_ENDPOINT,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                max_output_tokens=2048,
            )
        )
        return response.text
    except Exception as e:
        return f"⚠️ Erro na inferência do modelo Fine-Tuned: {str(e)}"
