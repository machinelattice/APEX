"""APEX Pricing Models.

Two pricing models for APEX agents:
- Fixed: Exact price, no negotiation
- Negotiated: Dynamic price negotiation with 4 strategies

"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Fixed:
    """Fixed price - exact amount, no negotiation.
    
    Example:
        Fixed(5.00)
        Fixed(5.00, currency="USDC")
    """
    amount: float
    currency: str = "USDC"
    
    def to_dict(self) -> dict:
        return {
            "model": "fixed",
            "amount": self.amount,
            "currency": self.currency,
        }


@dataclass
class Negotiated:
    """Negotiated pricing - 4 strategies available.
    
    Strategies:
        - "firm": Holds near target, minimal concessions
        - "balanced": Moderate concessions (default)
        - "flexible": Faster concessions, prioritizes deals
        - "llm": Full AI control over price and reasoning
    
    Example:
        # Algorithmic (fast, predictable)
        Negotiated(target=25.00, minimum=15.00)
        Negotiated(target=25.00, minimum=15.00, strategy="firm")
        
        # Algorithmic price + LLM reasons
        Negotiated(target=25.00, minimum=15.00, strategy="firm", model="gpt-4o-mini")
        
        # Pure LLM control
        Negotiated(
            target=25.00,
            minimum=15.00,
            strategy="llm",
            model="gpt-4o",
            instructions=["Be firm but fair.", "Offer bulk discounts."],
        )
    """
    target: float
    minimum: float
    max_rounds: int = 5
    currency: str = "USDC"
    strategy: Literal["firm", "balanced", "flexible", "llm"] | None = None
    model: str | None = None
    base_url: str | None = None
    instructions: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "model": "negotiated",
            "target_amount": self.target,
            "min_amount": self.minimum,
            "max_rounds": self.max_rounds,
            "currency": self.currency,
            "strategy": self.strategy,
        }


# Type alias
Pricing = Fixed | Negotiated