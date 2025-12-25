"""APEX Estimation Engine.

LLM-based task complexity estimation for dynamic pricing.

Human provides base rate. Agent applies multiplier based on task analysis.

Example:
    from apex.estimation import estimate_task, TaskEstimate
    
    estimate = await estimate_task(
        base=20.00,
        input={"topic": "AI agent protocols", "depth": "comprehensive"},
        model="gpt-4o-mini",
        instructions=["Legal topics: 2x", "Multi-language: +50%"],
    )
    
    print(f"Estimate: ${estimate.amount:.2f}")
    print(f"Range: ${estimate.low:.2f} - ${estimate.high:.2f}")
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional, Literal


# ─── Constants ────────────────────────────────────────────────────────────────

ESTIMATE_EXPIRY_SECONDS = 300  # 5 minutes

# Minimum is 80% of estimate (seller's floor for negotiation)
MINIMUM_FLOOR_PCT = 0.80

MULTIPLIER_GUIDE = """
Multiplier guide:
- 0.25x: Trivial (simple lookup, basic question)
- 0.5x: Simple (straightforward task, clear scope)
- 1.0x: Standard (typical task for this capability)
- 1.5x: Moderate (multiple sources, some synthesis)
- 2.0x: Complex (cross-domain, significant analysis)
- 3.0x: Hard (deep research, many dimensions)
- 4.0x: Very hard (novel territory, extensive work)
"""


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class TaskEstimate:
    """Result of task complexity estimation."""
    amount: float           # AI's fair value estimate
    minimum: float          # Seller's floor (80% of amount)
    currency: str = "USDC"
    
    # Internals
    multiplier: float = 1.0
    reasoning: Optional[str] = None
    
    # Keep 'low' as alias for minimum (backwards compat)
    @property
    def low(self) -> float:
        return self.minimum
    
    def to_dict(self) -> dict:
        return {
            "amount": round(self.amount, 2),
            "minimum": round(self.minimum, 2),
            "low": round(self.minimum, 2),  # backwards compat
            "currency": self.currency,
        }


@dataclass
class EstimateResult:
    """Full estimate response for protocol."""
    estimate_id: str
    estimate: TaskEstimate
    expires_at: datetime
    
    # Negotiation bounds derived from estimate
    target: float           # ≈ amount
    floor: float            # ≈ low
    
    # Analysis details
    factors: list[dict] = field(default_factory=list)
    reasoning: Optional[str] = None
    
    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at
    
    def to_dict(self) -> dict:
        return {
            "status": "estimated",
            "estimate_id": self.estimate_id,
            "expires_at": self.expires_at.isoformat(),
            "estimate": self.estimate.to_dict(),
            "negotiation": {
                "target": round(self.target, 2),
                "floor": round(self.floor, 2),
            },
            "factors": self.factors,
            "reasoning": self.reasoning,
        }


# ─── Estimation Logic ─────────────────────────────────────────────────────────

def _load_env():
    """Load API keys from .env file if not already set."""
    if os.environ.get("_APEX_ENV_LOADED"):
        return
    
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.home() / ".env",
    ]
    
    for env_path in search_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key not in os.environ:
                            os.environ[key] = value
            break
    
    os.environ["_APEX_ENV_LOADED"] = "1"


async def estimate_task(
    base: float,
    input: dict,
    model: str = "gpt-4o-mini",
    instructions: Optional[list[str]] = None,
    capability: Optional[str] = None,
) -> EstimateResult:
    """Estimate task complexity and generate pricing.
    
    Args:
        base: Base rate (human-provided anchor)
        input: Task input data
        model: LLM model for estimation
        instructions: Custom estimation hints
        capability: Capability name for context
    
    Returns:
        EstimateResult with pricing estimate and bounds
    """
    _load_env()
    
    # Build estimation prompt
    system_prompt = _build_estimation_prompt(base, instructions, capability)
    
    # Extract task description
    task = input.get("topic", input.get("query", input.get("task", str(input))))
    user_prompt = f"Task: {task}"
    
    # Call LLM
    try:
        response = _call_llm(model, system_prompt, user_prompt)
        multiplier, reasoning = _parse_estimation_response(response)
    except Exception:
        # LLM didn't return valid JSON, use standard estimate
        multiplier = 1.0
        reasoning = "Standard complexity estimate."
    
    # Calculate estimate
    estimate = _calculate_estimate(base, multiplier)
    estimate.reasoning = reasoning
    
    # Build result
    estimate_id = f"est-{uuid.uuid4().hex[:12]}"
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ESTIMATE_EXPIRY_SECONDS)
    
    # Derive negotiation bounds
    target = estimate.amount   # Seller's target price
    floor = estimate.minimum   # Seller's floor (80% of estimate)
    
    factors = [
        {"name": "base_rate", "value": f"${base:.2f}"},
        {"name": "multiplier", "value": f"{multiplier:.2f}x"},
    ]
    
    return EstimateResult(
        estimate_id=estimate_id,
        estimate=estimate,
        expires_at=expires_at,
        target=target,
        floor=floor,
        factors=factors,
        reasoning=reasoning,
    )


def _build_estimation_prompt(
    base: float,
    instructions: Optional[list[str]],
    capability: Optional[str],
) -> str:
    """Build the estimation system prompt."""
    
    cap_context = f"Capability: {capability}\n" if capability else ""
    
    inst_text = ""
    if instructions:
        inst_text = "Complexity guidelines:\n" + "\n".join(f"- {i}" for i in instructions) + "\n\n"
    
    base_str = f"${base:.2f}"
    
    return f"""You are a PRICING ESTIMATOR. Your ONLY job is to analyze task complexity and output a JSON object.

DO NOT negotiate. DO NOT write conversational text. ONLY output JSON.

Base rate: {base_str}
{cap_context}
{inst_text}{MULTIPLIER_GUIDE}

Analyze the task complexity and respond with ONLY this JSON format:
{{"multiplier": 1.0, "reasoning": "Brief explanation of complexity"}}

Rules:
- multiplier: 0.25 (trivial) to 4.0 (very complex)
- reasoning: 1 sentence explaining why this multiplier

RESPOND WITH JSON ONLY. NO OTHER TEXT."""


def _calculate_estimate(
    base: float,
    multiplier: float,
) -> TaskEstimate:
    """Calculate estimate from base and multiplier."""
    
    # Clamp multiplier to reasonable bounds
    multiplier = max(0.25, min(4.0, multiplier))
    
    # Calculate
    amount = base * multiplier
    minimum = amount * MINIMUM_FLOOR_PCT  # 80% floor
    
    return TaskEstimate(
        amount=round(amount, 2),
        minimum=round(minimum, 2),
        multiplier=multiplier,
    )


def _call_llm(model: str, system: str, user: str) -> str:
    """Call LLM (OpenAI or Anthropic)."""
    if "claude" in model.lower():
        return _call_anthropic(model, system, user)
    return _call_openai(model, system, user)


def _call_openai(model: str, system: str, user: str) -> str:
    """Call OpenAI."""
    from openai import OpenAI
    
    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=100,
        temperature=0.1,  # Very low temp for deterministic JSON
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content


def _call_anthropic(model: str, system: str, user: str) -> str:
    """Call Anthropic."""
    import anthropic
    
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=100,
        temperature=0.1,  # Very low temp for deterministic JSON
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def _parse_estimation_response(text: str) -> tuple[float, str]:
    """Parse LLM estimation response.
    
    Returns:
        (multiplier, reasoning)
    """
    # Strip markdown if present
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    
    # Extract JSON
    if "{" in text:
        json_str = text[text.index("{"):text.rindex("}") + 1]
        data = json.loads(json_str)
    else:
        raise ValueError(f"No JSON in response: {text}")
    
    multiplier = float(data.get("multiplier", 1.0))
    reasoning = data.get("reasoning", "")
    
    # Smart default reasoning if LLM didn't provide one
    if not reasoning:
        if multiplier < 0.5:
            reasoning = "Quick factual lookup - minimal research required."
        elif multiplier < 1.0:
            reasoning = "Straightforward task with limited scope."
        elif multiplier < 1.5:
            reasoning = "Standard research task requiring synthesis."
        elif multiplier < 2.5:
            reasoning = "Complex analysis requiring multiple sources and deep synthesis."
        else:
            reasoning = "Comprehensive cross-domain research with high complexity."
    
    return multiplier, reasoning


# ─── Estimate Cache ───────────────────────────────────────────────────────────

class EstimateCache:
    """In-memory cache for estimates with expiry."""
    
    def __init__(self):
        self._cache: dict[str, EstimateResult] = {}
    
    def store(self, result: EstimateResult) -> None:
        """Store an estimate."""
        self._cache[result.estimate_id] = result
        self._cleanup()
    
    def get(self, estimate_id: str) -> Optional[EstimateResult]:
        """Get an estimate if valid."""
        result = self._cache.get(estimate_id)
        if result and not result.expired:
            return result
        # Remove if expired
        self._cache.pop(estimate_id, None)
        return None
    
    def remove(self, estimate_id: str) -> None:
        """Remove an estimate."""
        self._cache.pop(estimate_id, None)
    
    def _cleanup(self) -> None:
        """Remove expired estimates."""
        now = datetime.now(timezone.utc)
        expired = [k for k, v in self._cache.items() if v.expires_at < now]
        for k in expired:
            del self._cache[k]