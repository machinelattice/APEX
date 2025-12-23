"""APEX Negotiation Engine.

Four strategies:
- FIRM: Holds near target, minimal concessions (risk=0.3)
- BALANCED: Moderate concessions (risk=0.6, default)
- FLEXIBLE: Faster concessions, prioritizes deals (risk=0.85)
- LLM: Full AI control over price and reasoning

Features:
- Exponential concession curve for algorithmic strategies
- Pure LLM freedom for llm strategy (prompt-guided only)
- Hash-chained transcript for dispute resolution
- Deadline expiration handling
- Auto-loads API keys from .env files
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional, Literal
import hashlib
import json
import math
import os

from .pricing import Negotiated


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


class NegotiationState(Enum):
    """Current state of negotiation."""
    IN_PROGRESS = "in_progress"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Strategy(Enum):
    """Negotiation strategy."""
    FIRM = "firm"
    BALANCED = "balanced"
    FLEXIBLE = "flexible"
    LLM = "llm"


# Risk tolerance for each algorithmic strategy
_STRATEGY_RISK = {
    Strategy.FIRM: 0.3,
    Strategy.BALANCED: 0.6,
    Strategy.FLEXIBLE: 0.85,
}


@dataclass
class Decision:
    """Result of a negotiation decision."""
    action: Literal["accept", "counter", "reject"]
    price: Optional[Decimal] = None
    reason: Optional[str] = None


@dataclass
class Offer:
    """Counter offer from seller."""
    price: Decimal
    round: int
    reason: Optional[str] = None


@dataclass
class TranscriptEntry:
    """Immutable record of negotiation event."""
    party: str
    action: str
    price: Optional[Decimal]
    timestamp: datetime
    hash: str


def _exp_concession(
    target: Decimal,
    minimum: Decimal,
    round: int,
    max_rounds: int,
    risk: float,
) -> Decimal:
    """Exponential concession curve for algorithmic strategies."""
    t = round / max_rounds
    base = 0.65 * risk
    factor = Decimal(str(1 - math.exp(-base * t)))
    return target - (target - minimum) * factor


class NegotiationEngine:
    """Seller-side negotiation engine."""

    def __init__(self, pricing: Negotiated):
        """Initialize negotiation engine."""
        self.target = Decimal(str(pricing.target))
        self.minimum = Decimal(str(pricing.minimum))
        self.max_rounds = pricing.max_rounds
        self.currency = pricing.currency
        self.instructions = pricing.instructions
        
        # Determine strategy
        if pricing.strategy:
            self.strategy = Strategy(pricing.strategy)
        elif pricing.model:
            self.strategy = Strategy.LLM
        else:
            self.strategy = Strategy.BALANCED
        
        # LLM setup
        self.model = pricing.model
        self.base_url = pricing.base_url
        self._llm_client = None

        # State
        self.state = NegotiationState.IN_PROGRESS
        self.round = 0
        self.deadline = datetime.now(timezone.utc) + timedelta(seconds=300)
        self.transcript: list[TranscriptEntry] = []

    def receive_offer(self, price: float) -> tuple[NegotiationState, Optional[Offer]]:
        """Process buyer offer."""
        offer_price = Decimal(str(price))
        
        # Check deadline
        if datetime.now(timezone.utc) > self.deadline:
            self._log("system", "expired", None)
            self.state = NegotiationState.EXPIRED
            return self.state, None

        self.round += 1
        self._log("buyer", "offer", offer_price)

        # Too many rounds
        if self.round > self.max_rounds:
            self._log("system", "reject", None)
            self.state = NegotiationState.REJECTED
            return self.state, None

        # Get decision based on strategy
        if self.strategy == Strategy.LLM and self.model:
            decision = self._llm_decide(offer_price)
        else:
            decision = self._curve_decide(offer_price)

        # Protocol enforcement: can't reject offers >= minimum within rounds
        if decision.action == "reject" and offer_price >= self.minimum:
            decision = Decision(
                action="counter",
                price=self.minimum,
                reason="Let's find a middle ground.",
            )

        # Process decision
        if decision.action == "accept":
            self._log("seller", "accept", offer_price)
            self.state = NegotiationState.ACCEPTED
            return self.state, None

        if decision.action == "reject":
            self._log("seller", "reject", None)
            self.state = NegotiationState.REJECTED
            return self.state, None

        # Counter
        counter = Offer(
            price=decision.price.quantize(Decimal("0.01")),
            round=self.round,
            reason=decision.reason,
        )
        self._log("seller", "counter", counter.price)
        return self.state, counter

    def _curve_decide(self, offer_price: Decimal) -> Decision:
        """Algorithmic decision using exponential curve."""
        
        # Accept if meets target
        if offer_price >= self.target:
            return Decision(action="accept")

        # Calculate counter
        risk = _STRATEGY_RISK.get(self.strategy, 0.6)
        counter_price = _exp_concession(
            self.target,
            self.minimum,
            self.round,
            self.max_rounds,
            risk,
        )

        # Accept if their offer beats our counter
        if offer_price >= counter_price:
            return Decision(action="accept")

        # Generate reason if LLM available (but price from curve)
        reason = self._get_llm_reason(offer_price, counter_price) if self.model else None

        return Decision(action="counter", price=counter_price, reason=reason)

    def _llm_decide(self, offer_price: Decimal) -> Decision:
        """Pure LLM decision - full control over price and reasoning."""
        
        system_prompt = f"""You are negotiating price for an AI agent service.

Target: ${self.target:.2f} (your ideal price)
Minimum: ${self.minimum:.2f} (absolute floor - only go this low in final rounds!)
Round: {self.round} of {self.max_rounds}

{self._format_instructions()}

NEGOTIATION STRATEGY:
- Round 1-2: Stay firm, counter near your target. Don't concede much yet.
- Round 3-4: Start meeting halfway. Show willingness to deal.
- Round 5: Final round - be flexible, close the deal if reasonable.

DON'T jump to minimum immediately! Real negotiators concede gradually.

History:
{self._format_history()}

Respond with JSON only (no markdown):
{{"action": "accept"}}
{{"action": "counter", "price": 0.20, "reason": "1-2 sentences max"}}"""

        user_prompt = f"Buyer offers ${offer_price:.2f}. What's your counter?"

        try:
            response = self._call_llm(system_prompt, user_prompt)
            return self._parse_llm_response(response)
        except Exception as e:
            print(f"LLM error: {e}, falling back to curve")
            return self._curve_decide(offer_price)

    def _get_llm_reason(self, offer_price: Decimal, counter_price: Decimal) -> Optional[str]:
        """Get LLM reasoning for curve-decided counter."""
        
        prompt = f"""Generate a 1-2 sentence negotiation response.
You are countering ${offer_price:.2f} with ${counter_price:.2f}.
Round {self.round} of {self.max_rounds}.
{self._format_instructions()}
Be brief and natural."""

        try:
            return self._call_llm(prompt, "Your response:")
        except:
            return None

    def _call_llm(self, system: str, user: str) -> str:
        """Call LLM (OpenAI or Anthropic)."""
        if "claude" in self.model.lower():
            return self._call_anthropic(system, user)
        else:
            return self._call_openai(system, user)

    def _call_openai(self, system: str, user: str) -> str:
        """Call OpenAI."""
        _load_env()
        from openai import OpenAI
        
        if self._llm_client is None:
            kwargs = {}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._llm_client = OpenAI(**kwargs)
        
        response = self._llm_client.chat.completions.create(
            model=self.model,
            max_completion_tokens=100,
            temperature=0.9,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content

    def _call_anthropic(self, system: str, user: str) -> str:
        """Call Anthropic."""
        _load_env()
        import anthropic
        
        if self._llm_client is None:
            self._llm_client = anthropic.Anthropic()
        
        response = self._llm_client.messages.create(
            model=self.model,
            max_tokens=100,
            temperature=0.9,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    def _parse_llm_response(self, text: str) -> Decision:
        """Parse LLM JSON response. Only enforce min/max bounds."""
        
        # Strip markdown
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

        action = data["action"]
        
        # Only enforce absolute bounds (min/max), no algorithmic floor
        if action == "counter":
            price = Decimal(str(data["price"]))
            if price < self.minimum:
                price = self.minimum
            if price > self.target:
                price = self.target
            return Decision(
                action="counter",
                price=price,
                reason=data.get("reason"),
            )

        return Decision(action=action, reason=data.get("reason"))

    def _format_instructions(self) -> str:
        """Format custom instructions for LLM."""
        if not self.instructions:
            return ""
        lines = "\n".join(f"- {i}" for i in self.instructions)
        return f"Instructions:\n{lines}"

    def _format_history(self) -> str:
        """Format negotiation history for LLM."""
        if not self.transcript:
            return "No prior exchanges."
        lines = []
        for entry in self.transcript[-6:]:
            if entry.price:
                lines.append(f"{entry.party}: {entry.action} ${entry.price:.2f}")
            else:
                lines.append(f"{entry.party}: {entry.action}")
        return "\n".join(lines)

    def _log(self, party: str, action: str, price: Optional[Decimal]):
        """Log negotiation event with hash chain."""
        prev_hash = self.transcript[-1].hash if self.transcript else "0"
        ts = datetime.now(timezone.utc)
        payload = f"{prev_hash}:{party}:{action}:{price}:{ts.isoformat()}"
        
        self.transcript.append(TranscriptEntry(
            party=party,
            action=action,
            price=price,
            timestamp=ts,
            hash=hashlib.sha256(payload.encode()).hexdigest()[:16],
        ))


# Backwards compatibility aliases
Action = type("Action", (), {
    "ACCEPT": "accept",
    "COUNTER": "counter",
    "REJECT": "reject",
})