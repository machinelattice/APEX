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

    def __init__(self, pricing: Negotiated, task_context: Optional[dict] = None):
        """Initialize negotiation engine.
        
        Args:
            pricing: Negotiated pricing config with target/minimum
            task_context: Optional dict with task info for LLM justification
                - description: Task description
                - reasoning: Why this price (from estimation)
                - complexity: Complexity level
        """
        # Handle base rate mode vs legacy mode
        if pricing.uses_estimation:
            # This shouldn't happen - engine should be created with dynamic bounds
            raise ValueError(
                "NegotiationEngine requires target/minimum. "
                "For base rate pricing, use Agent._get_or_create_engine() with estimate bounds."
            )
        
        self.target = Decimal(str(pricing.target))
        self.minimum = Decimal(str(pricing.minimum))
        self.max_rounds = pricing.max_rounds
        self.currency = pricing.currency
        self.instructions = pricing.instructions
        self.task_context = task_context or {}
        
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
        
        # Track last counter to enforce monotonic decrease
        self.last_counter: Optional[Decimal] = None
        self.best_buyer_offer: Optional[Decimal] = None

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
        
        # Track best buyer offer (for decision making)
        if self.best_buyer_offer is None or offer_price > self.best_buyer_offer:
            self.best_buyer_offer = offer_price

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

        # CRITICAL: Enforce monotonic decrease - counter can only go DOWN
        counter_price = decision.price.quantize(Decimal("0.01"))
        if self.last_counter is not None and counter_price > self.last_counter:
            # Force price down - at least 2% below last counter
            counter_price = (self.last_counter * Decimal("0.98")).quantize(Decimal("0.01"))
            # But never below minimum
            counter_price = max(counter_price, self.minimum)
        
        # Update last counter
        self.last_counter = counter_price
        
        # Counter
        counter = Offer(
            price=counter_price,
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
        
        # ROUND 1: Always counter at TARGET (don't concede yet!)
        if self.round == 1:
            # Accept if they offer at or above target
            if offer_price >= self.target:
                return Decision(action="accept", reason="Deal!")
            # Otherwise counter at full target price
            suggested = float(self.target)
        else:
            # ROUND 2+: Start conceding from last counter
            current_ceiling = float(self.last_counter) if self.last_counter else float(self.target)
            gap_to_offer = current_ceiling - float(offer_price)
            
            # Concession gets larger each round
            if self.round == 2:
                concession_pct = 0.25  # 25% toward their offer
            elif self.round == 3:
                concession_pct = 0.40  # 40%
            elif self.round == 4:
                concession_pct = 0.55  # 55%
            else:
                concession_pct = 0.75  # 75% - final round, close the deal
            
            suggested = current_ceiling - gap_to_offer * concession_pct
            suggested = max(suggested, float(self.minimum))  # Never below floor
            
            # CRITICAL: Must be below last counter (for round 2+)
            if self.last_counter and suggested >= float(self.last_counter):
                suggested = float(self.last_counter) * 0.97  # Force 3% down
                suggested = max(suggested, float(self.minimum))
        
        # Format prices
        target_str = f"${float(self.target):.2f}"
        floor_str = f"${float(self.minimum):.2f}"
        offer_str = f"${float(offer_price):.2f}"
        suggested_str = f"${suggested:.2f}"
        last_counter_str = f"${float(self.last_counter):.2f}" if self.last_counter else "N/A"
        
        # Build task context section
        task_section = ""
        if self.task_context:
            desc = self.task_context.get("description", "")
            reasoning = self.task_context.get("reasoning", "")
            if desc:
                task_section += f"\nTASK: {desc}\n"
            if reasoning:
                task_section += f"WORK INVOLVED: {reasoning}\n"
        
        # Round-specific dialogue styles
        dialogue_styles = {
            1: [
                f"This requires [specific work], so {suggested_str} would be fair.",
                f"For this scope, I'd need {suggested_str} to do it properly.",
                f"Given what's involved, {suggested_str} is my starting point.",
            ],
            2: [
                f"I hear you. I can come down to {suggested_str} - that's a reasonable middle ground.",
                f"Let me work with you here - {suggested_str} would work for me.",
                f"I appreciate you engaging. How about {suggested_str}?",
            ],
            3: [
                f"We're getting closer. I can do {suggested_str} - that's a fair compromise.",
                f"I want to make this work. {suggested_str} is where I can land.",
                f"Meeting you partway at {suggested_str} - does that work?",
            ],
            4: [
                f"Final offer: {suggested_str}. That's as low as I can reasonably go.",
                f"I'll do {suggested_str} to close this deal. Final price.",
                f"Let's wrap this up at {suggested_str}. Fair?",
            ],
            5: [
                f"Last chance - {suggested_str} or I'll have to pass.",
                f"{suggested_str} is my bottom line. Take it or leave it.",
                f"Deal at {suggested_str}? Otherwise we're too far apart.",
            ],
        }
        
        style_options = dialogue_styles.get(self.round, dialogue_styles[5])
        import random
        example_style = random.choice(style_options)
        
        # Round-specific guidance
        last_counter_note = ""
        if self.last_counter:
            last_counter_note = f"- Your last counter was {last_counter_str} - you MUST go LOWER\n"
        
        if self.round <= 2:
            round_guidance = f"""ROUND {self.round} - ESTABLISH VALUE:
{last_counter_note}- Counter at {suggested_str} or lower
- Explain WHY your work is worth this price
- Reference the specific task requirements"""
        elif self.round <= 4:
            round_guidance = f"""ROUND {self.round} - FIND MIDDLE GROUND:
{last_counter_note}- Move down to {suggested_str}
- Show willingness to compromise
- Keep it collaborative, not combative"""
        else:
            round_guidance = f"""ROUND {self.round} (FINAL) - CLOSE OR WALK:
- Accept if they're at {floor_str} or above
- Or make final offer at/near {floor_str}"""

        system_prompt = f"""You are negotiating to sell a service. Be professional and varied in your responses.

YOUR POSITION:
- Target: {target_str}
- Floor: {floor_str}
- Their offer: {offer_str}
- Last counter: {last_counter_str}
{task_section}
{round_guidance}

{self._format_instructions()}

CRITICAL RULES:
1. Your price MUST be {suggested_str} or LOWER (never higher than last counter!)
2. Vary your dialogue - don't repeat the same phrases
3. Reference the actual work involved

Example response style for this round:
"{example_style}"

Respond with ONLY JSON:
{{"action": "counter", "price": {suggested:.2f}, "reason": "Your unique 1-2 sentence response"}}
{{"action": "accept", "reason": "Brief acceptance"}}

JSON ONLY:"""

        user_prompt = f"Buyer offers {offer_str}. Round {self.round}/{self.max_rounds}."

        try:
            response = self._call_llm(system_prompt, user_prompt)
            decision = self._parse_llm_response(response)
            
            # Double-check: enforce price <= last_counter
            if decision.action == "counter" and self.last_counter:
                if decision.price > self.last_counter:
                    decision.price = Decimal(str(suggested))
            
            return decision
        except Exception:
            return self._curve_decide(offer_price)

        try:
            response = self._call_llm(system_prompt, user_prompt)
            return self._parse_llm_response(response)
        except Exception:
            return self._curve_decide(offer_price)

    def _get_llm_reason(self, offer_price: Decimal, counter_price: Decimal) -> Optional[str]:
        """Get LLM reasoning for curve-decided counter."""
        
        offer_str = f"${float(offer_price):.2f}"
        counter_str = f"${float(counter_price):.2f}"
        
        # Build context from task
        task_info = ""
        if self.task_context:
            desc = self.task_context.get("description", "")
            reasoning = self.task_context.get("reasoning", "")
            if desc:
                task_info += f"Task: {desc}\n"
            if reasoning:
                task_info += f"Why this price: {reasoning}\n"
        
        prompt = f"""Generate a 1-2 sentence negotiation response justifying your price.

You are countering their {offer_str} with {counter_str}.
Round {self.round} of {self.max_rounds}.

{task_info}
{self._format_instructions()}

Justify based on the work involved. Be brief and natural.
Example: "Given [specific work involved], {counter_str} is fair."
"""

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
                price_str = f"${float(entry.price):.2f}"
                lines.append(f"{entry.party}: {entry.action} {price_str}")
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