"""DeepSeek API client and chat functionality."""

import os
from typing import Optional, List, Dict

from openai import OpenAI

from modules.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEFAULT_COURT,
)
from modules.system_prompt import _build_system_prompt

_DEEPSEEK_MODEL_ALIASES = {
    "deepseek-v4-pro": "deepseek-v4-pro",
    "deepseek-v4-flash": "deepseek-v4-flash",
    "v4-pro": "deepseek-v4-pro",
    "v4-flash": "deepseek-v4-flash",
    "deepseek-chat": "deepseek-v4-pro",
    "deepseek-reasoner": "deepseek-v4-pro",
}


def _resolve_deepseek_model(candidate: Optional[str] = None) -> str:
    raw = str(candidate or DEEPSEEK_MODEL).strip().lower()
    return _DEEPSEEK_MODEL_ALIASES.get(raw, "deepseek-v4-pro")


deepseek_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL
) if DEEPSEEK_API_KEY else None


async def chat_with_deepseek(
    user_message: str,
    conversation: Optional[List[Dict[str, str]]] = None,
    file_text: Optional[str] = None,
    file_name: Optional[str] = None,
    image_b64: Optional[str] = None,
    model: Optional[str] = None,
    court: Optional[str] = None,
) -> str:
    if not deepseek_client:
        return ("⚠️ Chave da API do DeepSeek não configurada. "
                "Defina a variável de ambiente DEEPSEEK_API_KEY.\n\n"
                "Enquanto isso, você pode preencher os campos manualmente e executar a busca.")

    system_prompt = _build_system_prompt(court or DEFAULT_COURT)
    messages = [{"role": "system", "content": system_prompt}]

    if conversation:
        for msg in conversation[-10:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    content_parts = []

    if file_text:
        content_parts.append({
            "type": "text",
            "text": f"[Arquivo enviado: {file_name or 'documento'}]\n\nConteúdo extraído:\n{file_text[:6000]}"
        })

    if image_b64:
        content_parts.append({
            "type": "text",
            "text": f"[Imagem enviada: {file_name or 'imagem'}] — analise o conteúdo da imagem para sugerir campos de busca."
        })
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}", "detail": "auto"}
        })

    content_parts.append({"type": "text", "text": user_message})

    messages.append({"role": "user", "content": content_parts})

    try:
        response = deepseek_client.chat.completions.create(
            model=_resolve_deepseek_model(model),
            messages=messages,
            max_tokens=2000,
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ Erro na API do DeepSeek: {str(e)}"
