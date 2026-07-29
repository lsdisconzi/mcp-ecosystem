from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging
from pathlib import Path
import json
import ollama

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/prompt-engineer",
    tags=["Prompt Engineer"]
)

# ===== Pydantic Models =====

class PromptGenerationRequest(BaseModel):
    """Request model for prompt generation"""
    model: str = Field(..., description="Model to use (llama3.1:8b, dolphin-llama3:8b, etc.)")
    user_input: str = Field(..., description="User's description of needs")
    system_prompt: str = Field(..., description="System instructions for prompt engineer")
    vector_context: str = Field("", description="Context from vector store")
    files_context: str = Field("", description="Context from attached files")
    reference_prompts: str = Field("", description="Reference prompts for inspiration")
    quality_metrics: str = Field("", description="Quality metrics preferences")
    temperature: float = Field(0.7, ge=0, le=2)
    max_tokens: int = Field(1000, ge=100, le=4000)
    assistant_id: Optional[str] = Field(None, description="Optional assistant ID to use for context")

class AnalysisRequest(BaseModel):
    """Request model for analyzing user needs"""
    user_input: str = Field(..., description="User's input to analyze")
    model: str = Field(..., description="Model to use for analysis (llama3.1:8b, dolphin-llama3:8b, etc.)")

class VariationRequest(BaseModel):
    """Request model for generating variations"""
    prompt: str = Field(..., description="Original prompt")
    count: int = Field(3, ge=1, le=10, description="Number of variations")
    model: str = Field(..., description="Model to use (llama3.1:8b, dolphin-llama3:8b, etc.)")

class OptimizationRequest(BaseModel):
    """Request model for prompt optimization"""
    prompt: str = Field(..., description="Prompt to optimize")
    metrics: Dict[str, int] = Field(..., description="Quality metrics (clarity, specificity, creativity, conciseness)")
    model: str = Field(..., description="Model to use (llama3.1:8b, dolphin-llama3:8b, etc.)")

class EvaluationRequest(BaseModel):
    """Request model for prompt evaluation"""
    prompt: str = Field(..., description="Prompt to evaluate")
    model: str = Field(..., description="Model to use (llama3.1:8b, dolphin-llama3:8b, etc.)")

class ImprovementRequest(BaseModel):
    """Request model for improvement suggestions"""
    prompt: str = Field(..., description="Prompt to improve")
    metrics: Dict[str, int] = Field(..., description="Quality metrics")
    model: str = Field(..., description="Model to use (hermes3:8b, dolphin-llama3:8b, etc.)")

class PromptGenerationResponse(BaseModel):
    """Response model for prompt generation"""
    prompt: str = Field(..., description="Generated prompt")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Generation metadata")

class EvaluationResponse(BaseModel):
    """Response model for evaluation"""
    scores: Dict[str, int] = Field(..., description="Quality scores")
    feedback: str = Field(..., description="Overall feedback")
    suggestions: List[str] = Field(..., description="Improvement suggestions")

class ImprovementResponse(BaseModel):
    """Response model for improvements"""
    suggestions: List[str] = Field(..., description="Improvement suggestions")
    improved_prompt: str = Field(..., description="Improved version of prompt")

# ===== Helper Functions =====

def call_ollama(model: str, prompt: str, system_prompt: str = "", temperature: float = 0.7, max_tokens: int = 1000) -> str:
    """Call Ollama API directly"""
    try:
        messages = []
        
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        response = ollama.chat(
            model=model,
            messages=messages,
            options={
                "temperature": temperature,
                "num_predict": max_tokens
            }
        )
        
        return response['message']['content']
        
    except Exception as e:
        logger.error(f"Error calling Ollama: {str(e)}")
        raise

def build_engineer_prompt(user_input: str, context: str = "", metrics: str = "") -> str:
    """Build the full prompt for the engineer"""
    engineer_system = """You are an expert prompt engineer specializing in creating high-quality, 
    effective prompts for AI models. Your prompts are:
    - Clear and unambiguous
    - Well-structured with context and examples
    - Optimized for the target use case
    - Following best practices in prompt design
    
    When generating prompts:
    1. Start with a clear role/objective
    2. Provide context and constraints
    3. Include examples if relevant
    4. Define the expected output format
    5. Add any special instructions or rules"""
    
    full_prompt = f"""{engineer_system}

USER REQUEST:
{user_input}
"""
    
    if context:
        full_prompt += f"\nRELEVANT CONTEXT:\n{context}\n"
    
    if metrics:
        full_prompt += f"\nQUALITY TARGETS:\n{metrics}\n"
    
    full_prompt += "\nGENERATE A WELL-CRAFTED PROMPT:"
    
    return full_prompt

def evaluate_prompt_quality(prompt: str) -> Dict[str, Any]:
    """Evaluate various quality aspects of a prompt"""
    # Token count approximation (1 token ≈ 4 characters for English)
    token_count = len(prompt) // 4
    
    # Clarity analysis
    has_clear_goal = any(word in prompt.lower() for word in 
                        ["objective", "goal", "task", "generate", "create", "write", "analyze"])
    
    # Structure analysis
    has_structure = any(marker in prompt for marker in ["1.", "2.", "-", "•", ":", "##", "###"])
    
    # Specificity analysis
    has_examples = any(word in prompt.lower() for word in ["example", "e.g.", "such as", "like"])
    has_constraints = any(word in prompt.lower() for word in ["must", "should", "do not", "avoid", "ensure"])
    
    # Calculate scores (0-10)
    clarity_score = 8 if has_clear_goal else 5
    if "role:" in prompt.lower() or "act as" in prompt.lower():
        clarity_score += 1
    
    specificity_score = 6
    if has_examples:
        specificity_score += 2
    if has_constraints:
        specificity_score += 1
    specificity_score = min(10, specificity_score)
    
    structure_score = 5
    if has_structure:
        structure_score += 3
    if has_clear_goal and has_constraints:
        structure_score += 2
    structure_score = min(10, structure_score)
    
    conciseness_score = 8
    if token_count > 500:
        conciseness_score -= 2
    if token_count > 1000:
        conciseness_score -= 2
    conciseness_score = max(3, conciseness_score)
    
    return {
        "clarity": clarity_score,
        "specificity": specificity_score,
        "structure": structure_score,
        "conciseness": conciseness_score,
        "token_count": token_count,
        "has_clear_goal": has_clear_goal,
        "has_structure": has_structure,
        "has_examples": has_examples,
        "has_constraints": has_constraints
    }

# ===== API Endpoints =====

@router.post("/generate", response_model=PromptGenerationResponse)
async def generate_prompt(request: PromptGenerationRequest):
    """
    Generate a high-quality prompt based on user input and context.
    
    If assistant_id is provided, the assistant's configuration and context will be used.
    """
    try:
        # If assistant_id provided, load assistant context
        if request.assistant_id:
            try:
                assistant_path = Path("data/assistants") / f"{request.assistant_id}.json"
                if assistant_path.exists():
                    with open(assistant_path) as f:
                        assistant_data = json.load(f)
                        # Prepend assistant instructions to system prompt
                        if assistant_data.get("instructions"):
                            request.system_prompt = f"{assistant_data['instructions']}\n\n{request.system_prompt}"
                        # Use assistant's model if not overridden
                        if assistant_data.get("model"):
                            request.model = assistant_data["model"]
            except Exception as e:
                logger.warning(f"Could not load assistant {request.assistant_id}: {e}")
        
        # Build the complete engineer prompt
        engineer_prompt = build_engineer_prompt(
            request.user_input,
            context=request.vector_context + "\n" + request.files_context,
            metrics=request.quality_metrics
        )
        
        # Generate using Ollama
        generated_prompt = call_ollama(
            model=request.model,
            prompt=engineer_prompt,
            system_prompt=request.system_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )
        
        # Evaluate quality
        quality = evaluate_prompt_quality(generated_prompt)
        
        return {
            "prompt": generated_prompt,
            "metadata": {
                "model": request.model,
                "assistant_id": request.assistant_id,
                "quality_scores": {
                    "clarity": quality["clarity"],
                    "specificity": quality["specificity"],
                    "structure": quality["structure"],
                    "conciseness": quality["conciseness"]
                },
                "token_count": quality["token_count"],
                "used_vector_context": bool(request.vector_context),
                "used_files_context": bool(request.files_context),
                "used_reference_prompts": bool(request.reference_prompts),
                "used_assistant": bool(request.assistant_id)
            }
        }
        
    except Exception as e:
        logger.error(f"Error generating prompt: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate prompt: {str(e)}")

@router.post("/analyze")
async def analyze_needs(request: AnalysisRequest):
    """
    Analyze user needs to understand what kind of prompt is needed.
    """
    try:
        analysis_prompt = f"""Analyze the following request and provide a structured breakdown:

REQUEST: {request.user_input}

Provide analysis in this format:
1. PRIMARY OBJECTIVE: [What is the main goal?]
2. TARGET AUDIENCE: [Who will use this prompt?]
3. USE CASE: [What will it be used for?]
4. KEY ELEMENTS: [What should the prompt include?]
5. RECOMMENDED STRUCTURE: [How should it be organized?]
6. POTENTIAL CHALLENGES: [What might be difficult?]
7. ENHANCEMENT SUGGESTIONS: [How to make it better?]

Be specific and actionable in your analysis."""
        
        # Generate using Ollama
        analysis_text = call_ollama(
            model=request.model,
            prompt=analysis_prompt,
            max_tokens=1000
        )
        
        return {
            "status": "success",
            "analysis": analysis_text,
            "parsed": {
                "primary_objective": extract_section(analysis_text, "PRIMARY OBJECTIVE"),
                "target_audience": extract_section(analysis_text, "TARGET AUDIENCE"),
                "use_case": extract_section(analysis_text, "USE CASE"),
                "key_elements": extract_section(analysis_text, "KEY ELEMENTS"),
                "recommended_structure": extract_section(analysis_text, "RECOMMENDED STRUCTURE"),
                "potential_challenges": extract_section(analysis_text, "POTENTIAL CHALLENGES"),
                "enhancement_suggestions": extract_section(analysis_text, "ENHANCEMENT SUGGESTIONS")
            }
        }
        
    except Exception as e:
        logger.error(f"Error analyzing needs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze needs: {str(e)}")

@router.post("/variations")
async def generate_variations(request: VariationRequest):
    """
    Generate multiple variations of a prompt with different styles or approaches.
    """
    try:
        variation_prompt = f"""Generate {request.count} different versions of the following prompt, 
each with a different approach or style:

ORIGINAL PROMPT:
{request.prompt}

Requirements:
1. Each variation should be distinct in approach
2. Maintain the core objective
3. Vary the structure, tone, or methodology
4. Number each variation clearly (1., 2., 3., etc.)
5. Make them all high-quality and usable

Generate the variations now:"""
        
        # Generate using Ollama
        variations_text = call_ollama(
            model=request.model,
            prompt=variation_prompt,
            max_tokens=2000
        )
        
        variations = parse_variations(variations_text, request.count)
        
        return {
            "status": "success",
            "count": len(variations),
            "variations": variations
        }
        
    except Exception as e:
        logger.error(f"Error generating variations: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate variations: {str(e)}")

@router.post("/optimize")
async def optimize_prompt(request: OptimizationRequest):
    """
    Optimize a prompt based on quality metrics.
    """
    try:
        metrics_text = ", ".join([f"{k}: {v}/10" for k, v in request.metrics.items()])
        
        optimize_prompt_text = f"""Optimize the following prompt to better meet these quality targets:

QUALITY TARGETS: {metrics_text}

ORIGINAL PROMPT:
{request.prompt}

Improvements to make:
1. Increase clarity by being more specific
2. Add more concrete examples if needed
3. Improve structure and formatting
4. Enhance specificity of requirements
5. Ensure conciseness without losing information

Provide the optimized prompt below:"""
        
        # Generate using Ollama
        optimized_prompt = call_ollama(
            model=request.model,
            prompt=optimize_prompt_text,
            max_tokens=1500
        )
        
        optimized_prompt = optimized_prompt.strip()
        new_quality = evaluate_prompt_quality(optimized_prompt)
        
        return {
            "status": "success",
            "original_prompt": request.prompt,
            "optimized_prompt": optimized_prompt,
            "original_metrics": request.metrics,
            "new_metrics": {
                "clarity": new_quality["clarity"],
                "specificity": new_quality["specificity"],
                "structure": new_quality["structure"],
                "conciseness": new_quality["conciseness"]
            },
            "improvements_made": generate_improvements_list(request.prompt, optimized_prompt)
        }
        
    except Exception as e:
        logger.error(f"Error optimizing prompt: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to optimize prompt: {str(e)}")

@router.post("/evaluate", response_model=EvaluationResponse)
async def evaluate_prompt(request: EvaluationRequest):
    """
    Evaluate prompt quality across multiple dimensions.
    """
    try:
        eval_prompt = f"""Evaluate this prompt on the following dimensions:

PROMPT TO EVALUATE:
{request.prompt}

Evaluate and provide:
1. CLARITY (0-10): Is the objective clear and unambiguous?
2. SPECIFICITY (0-10): Does it provide specific requirements and constraints?
3. STRUCTURE (0-10): Is it well-organized and easy to follow?
4. CONCISENESS (0-10): Is it efficiently written without unnecessary words?
5. OVERALL FEEDBACK: General assessment of prompt quality
6. IMPROVEMENT SUGGESTIONS: Specific, actionable improvements

Format your response as:
CLARITY: [score]
SPECIFICITY: [score]
STRUCTURE: [score]
CONCISENESS: [score]
OVERALL FEEDBACK: [feedback text]
IMPROVEMENT SUGGESTIONS:
- [suggestion 1]
- [suggestion 2]
- [suggestion 3]"""
        
        # Generate using Ollama
        eval_text = call_ollama(
            model=request.model,
            prompt=eval_prompt,
            max_tokens=1000
        )
        
        return {
            "scores": {
                "clarity": extract_score(eval_text, "CLARITY"),
                "specificity": extract_score(eval_text, "SPECIFICITY"),
                "structure": extract_score(eval_text, "STRUCTURE"),
                "conciseness": extract_score(eval_text, "CONCISENESS")
            },
            "feedback": extract_section(eval_text, "OVERALL FEEDBACK"),
            "suggestions": extract_suggestions(eval_text, "IMPROVEMENT SUGGESTIONS")
        }
        
    except Exception as e:
        logger.error(f"Error evaluating prompt: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to evaluate prompt: {str(e)}")

@router.post("/improve", response_model=ImprovementResponse)
async def suggest_improvements(request: ImprovementRequest):
    """
    Suggest specific improvements to a prompt based on quality metrics.
    """
    try:
        metrics_text = ", ".join([f"{k}: {v}/10" for k, v in request.metrics.items()])
        
        improve_prompt = f"""Analyze this prompt and suggest specific improvements:

TARGET METRICS: {metrics_text}

CURRENT PROMPT:
{request.prompt}

For each area that could be improved, provide:
1. The issue
2. Why it's a problem
3. How to fix it
4. Example of the improvement

Then provide an improved version of the entire prompt.

IMPROVEMENTS:
[Your detailed improvements]

IMPROVED PROMPT:
[Full improved version]"""
        
        # Generate using Ollama
        response_text = call_ollama(
            model=request.model,
            prompt=improve_prompt,
            max_tokens=2000
        )
        
        suggestions = extract_suggestions(response_text, "IMPROVEMENTS")
        improved = extract_section(response_text, "IMPROVED PROMPT")
        
        return {
            "suggestions": suggestions if suggestions else [response_text[:500]],
            "improved_prompt": improved if improved else response_text
        }
        
    except Exception as e:
        logger.error(f"Error suggesting improvements: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to suggest improvements: {str(e)}")

@router.get("/examples")
async def get_prompt_examples(category: str = "general"):
    """
    Get example prompts by category to inspire users.
    """
    examples_db = {
        "general": [
            "Write a comprehensive guide on [topic] for [audience], including key concepts, examples, and actionable tips.",
            "Create a detailed checklist for [process] that covers all important steps and considerations.",
            "Analyze [situation] from multiple perspectives and provide balanced insights."
        ],
        "creative": [
            "Write a short story about [premise] that explores [theme] through compelling characters and vivid descriptions.",
            "Create a poem in [style] that captures the essence of [subject] using figurative language.",
            "Develop a dialogue between [characters] that reveals their personalities and conflicts."
        ],
        "technical": [
            "Explain [technical concept] to a junior developer, breaking it down into understandable parts with code examples.",
            "Write clean, well-documented [language] code that implements [functionality] following best practices.",
            "Debug the following code and explain what's wrong and how to fix it: [code snippet]"
        ],
        "analysis": [
            "Analyze [data/document] and identify key patterns, trends, and anomalies.",
            "Conduct a SWOT analysis for [subject] considering [specific context].",
            "Compare and contrast [items] across [dimensions], highlighting advantages and disadvantages."
        ],
        "coding": [
            "Create a [language] function that [requirement], with proper error handling and documentation.",
            "Refactor this code to be more efficient: [code]. Explain the improvements.",
            "Write unit tests for this function: [code]. Cover edge cases and error conditions."
        ],
        "business": [
            "Develop a business case for [proposal] including ROI analysis, risks, and implementation timeline.",
            "Create a marketing strategy for [product] targeting [audience] across [channels].",
            "Write a professional email to [recipient] about [subject] that is [tone]."
        ]
    }
    
    return {
        "category": category,
        "examples": examples_db.get(category, examples_db["general"]),
        "count": len(examples_db.get(category, examples_db["general"]))
    }

# ===== Text Parsing Helper Functions =====

def extract_section(text: str, section_name: str) -> str:
    """Extract a section from the response text"""
    try:
        import re
        pattern = rf"{section_name}[:\s]+(.*?)(?=\n[A-Z][A-Z\s]+:|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    except:
        pass
    return ""

def extract_score(text: str, metric: str) -> int:
    """Extract a numeric score from text"""
    try:
        import re
        pattern = rf"{metric}[:\s]+(\d+)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    except:
        pass
    return 5  # Default middle score

def extract_suggestions(text: str, section_name: str) -> List[str]:
    """Extract suggestions list from text"""
    try:
        section = extract_section(text, section_name)
        if section:
            import re
            suggestions = re.split(r'\n\s*[-•*]|\n\s*\d+\.', section)
            return [s.strip() for s in suggestions if s.strip() and len(s.strip()) > 5]
    except:
        pass
    return []

def parse_variations(text: str, count: int) -> List[str]:
    """Parse variations from response text"""
    import re
    variations = []
    
    # Try to split by numbered sections
    pattern = r'(?:^|\n)\s*(?:\*\*)?(?:\d+\.|\d+\))\s*\*?\*?([^]*?)(?=\n\s*(?:\d+\.|\d+\))|\Z)'
    matches = re.finditer(pattern, text, re.MULTILINE)
    
    for match in matches:
        var = match.group(1).strip()
        if var and len(var) > 20:
            variations.append(var)
    
    # If we didn't find enough, try splitting by double newlines
    if len(variations) < count:
        parts = text.split('\n\n')
        for part in parts:
            if part.strip() and len(part.strip()) > 50:
                variations.append(part.strip())
    
    return variations[:count] if variations else [text]

def generate_improvements_list(original: str, optimized: str) -> List[str]:
    """Generate a list of improvements between original and optimized prompts"""
    improvements = []
    
    if len(optimized) > len(original):
        improvements.append("Added more specific details and context")
    
    if original.count('\n') < optimized.count('\n'):
        improvements.append("Improved structure and formatting")
    
    if any(word in optimized.lower() for word in ["example", "for instance", "such as"]):
        if not any(word in original.lower() for word in ["example", "for instance", "such as"]):
            improvements.append("Added concrete examples")
    
    if any(word in optimized.lower() for word in ["must", "should", "ensure", "avoid"]):
        if not any(word in original.lower() for word in ["must", "should", "ensure", "avoid"]):
            improvements.append("Added clear constraints and requirements")
    
    if not improvements:
        improvements.append("Enhanced overall clarity and specificity")
    
    return improvements
