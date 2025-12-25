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
    """Negotiated pricing with LLM-based estimation.
    
    Two modes:
    
    1. Base rate mode (recommended):
       Human provides base rate, agent estimates multiplier per-task.
       
       Negotiated(base=20.00)
       
    2. Legacy mode (backward compatible):
       Fixed target/minimum, no estimation.
       
       Negotiated(target=25.00, minimum=15.00)
    
    Strategies (for negotiation, not estimation):
        - "firm": Holds near target, minimal concessions
        - "balanced": Moderate concessions (default)
        - "flexible": Faster concessions, prioritizes deals
        - "llm": Full AI control over price and reasoning
    
    Example:
        # Base rate mode - agent estimates per task
        Negotiated(base=20.00)
        Negotiated(base=20.00, model="gpt-4o-mini")
        Negotiated(
            base=20.00,
            instructions=["Legal topics: 2x", "Urgent: 1.5x"],
        )
        
        # Legacy mode - fixed bounds
        Negotiated(target=25.00, minimum=15.00)
    """
    # Base rate mode (new)
    base: float | None = None
    
    # Legacy mode (backward compatible)
    target: float | None = None
    minimum: float | None = None
    
    # Common settings
    max_rounds: int = 5
    currency: str = "USDC"
    strategy: Literal["firm", "balanced", "flexible", "llm"] | None = None
    model: str | None = None
    base_url: str | None = None
    instructions: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        # Validate: must have either base OR target+minimum
        if self.base is None and (self.target is None or self.minimum is None):
            raise ValueError("Negotiated requires either 'base' or both 'target' and 'minimum'")
        
        # Default model for base mode
        if self.base is not None and self.model is None:
            self.model = "gpt-4o-mini"
    
    @property
    def uses_estimation(self) -> bool:
        """True if using base rate mode (requires estimation)."""
        return self.base is not None
    
    def to_dict(self) -> dict:
        if self.uses_estimation:
            return {
                "model": "negotiated",
                "base": self.base,
                "max_rounds": self.max_rounds,
                "currency": self.currency,
                "strategy": self.strategy,
                "requires_estimation": True,
            }
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