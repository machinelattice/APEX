"""APEX Buyer - Create buyer agents with auto-negotiation, estimation, and payments.

Example:
    from apex import create_buyer
    from apex.payments import Wallet

    buyer = create_buyer(
        budget=40.00,
        strategy="llm",
        model="gpt-4o-mini",
        wallet=Wallet.from_env("BUYER_KEY"),
        auto_pay=True,
    )
    
    async with buyer:
        result = await buyer.call(
            url="http://localhost:8001/apex",
            capability="research",
            input={"topic": "AI trends"},
        )
        
        if result.success:
            print(f"Paid ${result.final_price} USDC")
            print(f"tx: {result.tx_hash}")
            print(result.output)
"""

import uuid
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Literal, Optional, TYPE_CHECKING
import math

import httpx

from .negotiation import _load_env

if TYPE_CHECKING:
    from .payments import Wallet


# ─── Colors ───────────────────────────────────────────────────────────────────

class _C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    BUYER = "\033[94m"
    SELLER = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"


def _type_text(text: str, delay: float = 0.012):
    """Print text with typing effect."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()


@dataclass
class NegotiationResult:
    """Result of a negotiation and optional payment."""
    success: bool
    final_price: Optional[float] = None
    output: Optional[dict] = None
    rounds: int = 0
    history: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    
    # Estimate fields
    estimate: Optional[dict] = None  # {amount, low, high}
    estimate_id: Optional[str] = None
    
    # Payment fields
    tx_hash: Optional[str] = None
    explorer_url: Optional[str] = None
    payment_verified: bool = False


@dataclass 
class Buyer:
    """APEX Buyer with auto-negotiation, estimation, and payments."""
    
    budget: float
    strategy: Literal["firm", "balanced", "flexible", "llm"] = "balanced"
    model: Optional[str] = None
    instructions: list[str] = field(default_factory=list)
    initial_offer_pct: float = 0.6  # Start at 60% of budget
    wallet: Optional["Wallet"] = None  # Real wallet for payments
    auto_pay: bool = False  # Auto-pay on successful negotiation
    mock_wallet: Optional[str] = None  # Mock wallet address (for testing)
    
    # Internal
    _http: Optional[httpx.AsyncClient] = None
    _llm_client: object = None
    
    def __post_init__(self):
        # Generate mock wallet if no real wallet and no mock specified
        if self.wallet is None and self.mock_wallet is None:
            self.mock_wallet = "0x" + uuid.uuid4().hex[:40]
    
    @property
    def address(self) -> str:
        """Get wallet address (real or mock)."""
        if self.wallet:
            return self.wallet.address
        return self.mock_wallet
    
    async def __aenter__(self):
        self._http = httpx.AsyncClient(timeout=60.0)
        return self
    
    async def __aexit__(self, *args):
        if self._http:
            await self._http.aclose()
    
    async def balance(self) -> Optional[float]:
        """Get USDC balance (if real wallet)."""
        if self.wallet:
            return await self.wallet.balance("USDC")
        return None
    
    async def call(
        self,
        url: str,
        capability: str,
        input: dict,
        max_rounds: int = 5,
        verbose: bool = False,
    ) -> NegotiationResult:
        """Call an agent and auto-negotiate (optionally auto-pay).
        
        Args:
            url: Agent's APEX endpoint URL
            capability: Capability to invoke
            input: Input data for the capability
            max_rounds: Maximum negotiation rounds
            verbose: Print negotiation progress with typing effect
        
        Returns:
            NegotiationResult with success status, output, and payment info
        """
        history = []
        job_id = str(uuid.uuid4())
        self._last_reason = None  # Track buyer's reasoning for display
        
        # Track estimate info
        estimate_info = None
        estimate_id = None
        
        # Get seller info (for payment address and pricing model)
        seller_info = await self._discover(url)
        seller_address = None
        requires_estimation = False
        
        if seller_info:
            seller_address = seller_info.get("payment", {}).get("address")
            # Check if estimation is required
            capabilities = seller_info.get("capabilities", [])
            for cap in capabilities:
                pricing = cap.get("pricing", {})
                if pricing.get("requires_estimation") or pricing.get("base"):
                    requires_estimation = True
                    break
        
        # Step 1: Get estimate if needed
        if requires_estimation:
            estimate_result = await self._estimate(url, capability, input)
            
            if estimate_result and estimate_result.get("status") == "estimated":
                estimate_info = estimate_result.get("estimate", {})
                estimate_id = estimate_result.get("estimate_id")
                negotiation = estimate_result.get("negotiation", {})
                reasoning = estimate_result.get("reasoning", "")
                
                # Add reasoning to estimate_info so it's available in result
                if reasoning:
                    estimate_info["reasoning"] = reasoning
                
                # Check if budget is sufficient
                floor_price = negotiation.get("floor", estimate_info.get("low", 0))
                if floor_price > self.budget:
                    if verbose:
                        print(f"\n{_C.RED}❌ Budget insufficient: need at least ${floor_price:.2f}, have ${self.budget:.2f}{_C.RESET}")
                    return NegotiationResult(
                        success=False,
                        rounds=0,
                        history=[],
                        error=f"Budget insufficient: minimum ${floor_price:.2f}, budget ${self.budget:.2f}",
                        estimate=estimate_info,
                        estimate_id=estimate_id,
                    )
                
                # Calculate initial offer based on estimate
                offer = self._calculate_offer_from_estimate(estimate_info)
            else:
                # Estimation failed, use budget-based offer
                offer = self._calculate_initial_offer()
        else:
            # No estimation needed, use budget-based offer
            offer = self._calculate_initial_offer()
        
        if verbose:
            if requires_estimation:
                print(f"\n{_C.YELLOW}💬 NEGOTIATION{_C.RESET}")
        
        for round_num in range(1, max_rounds + 1):
            if verbose:
                print(f"\n{_C.YELLOW}▸ Round {round_num}/{max_rounds}{_C.RESET}")
            
            # Show buyer's offer
            if verbose:
                print(f"\n{_C.BUYER}🛒 BUYER{_C.RESET} {_C.DIM}[offers ${offer:.2f}]{_C.RESET}")
                if round_num == 1:
                    sys.stdout.write(f"   ")
                    _type_text(f'"I\'d like to use your services. Here\'s my opening offer."')
                elif hasattr(self, '_last_reason') and self._last_reason:
                    sys.stdout.write(f"   ")
                    _type_text(f'"{self._last_reason}"')
            
            # Send offer (include estimate_id if we have one)
            if round_num == 1:
                result = await self._propose(url, capability, input, offer, job_id, estimate_id)
            else:
                result = await self._counter(url, job_id, offer, round_num, input)
            
            history.append({"party": "buyer", "amount": offer, "round": round_num})
            
            if "error" in result:
                if verbose:
                    print(f"{_C.RED}❌ {result['error'].get('message', 'Error')}{_C.RESET}")
                return NegotiationResult(
                    success=False,
                    rounds=round_num,
                    history=history,
                    error=result["error"].get("message", "Unknown error"),
                    estimate=estimate_info,
                    estimate_id=estimate_id,
                )
            
            status = result.get("result", {}).get("status")
            
            # Deal completed
            if status == "completed":
                final = result["result"]
                final_price = final["terms"]["amount"]
                
                if verbose:
                    print(f"\n{_C.GREEN}✅ Seller accepted ${final_price:.2f}{_C.RESET}")
                    
                    # Show estimate comparison if we had one
                    if estimate_info:
                        est_amount = estimate_info.get("amount", 0)
                        if est_amount > 0:
                            pct = (final_price / est_amount) * 100
                            print(f"   {_C.DIM}Settled at {pct:.0f}% of estimate (${est_amount:.2f}){_C.RESET}")
                
                # Handle payment if auto_pay enabled
                tx_hash = None
                explorer_url = None
                payment_verified = False
                
                if self.auto_pay and self.wallet and seller_address:
                    payment_result = await self._make_payment(
                        seller_address=seller_address,
                        amount=final_price,
                        job_id=job_id,
                    )
                    
                    if payment_result.get("success"):
                        tx_hash = payment_result.get("tx_hash")
                        explorer_url = payment_result.get("explorer_url")
                        payment_verified = True
                
                return NegotiationResult(
                    success=True,
                    final_price=final_price,
                    output=final.get("output"),
                    rounds=round_num,
                    history=history,
                    estimate=estimate_info,
                    estimate_id=estimate_id,
                    tx_hash=tx_hash,
                    explorer_url=explorer_url,
                    payment_verified=payment_verified,
                )
            
            # Seller countered
            elif status == "counter":
                seller_offer = result["result"]["offer"]["amount"]
                reason = result["result"].get("reason")
                history.append({"party": "seller", "amount": seller_offer, "round": round_num})
                
                if verbose:
                    print(f"\n{_C.SELLER}🤖 SELLER{_C.RESET} {_C.DIM}[${seller_offer:.2f}]{_C.RESET}")
                    if reason:
                        sys.stdout.write(f"   ")
                        _type_text(f'"{reason}"')
                
                # Decide response
                decision = await self._decide(offer, seller_offer, round_num, max_rounds)
                
                if decision["action"] == "accept":
                    # Accept seller's price
                    if verbose:
                        print(f"\n{_C.BUYER}🛒 BUYER{_C.RESET} {_C.DIM}[accepts ${seller_offer:.2f}]{_C.RESET}")
                        accept_reason = decision.get("reason", "That works for me. Deal!")
                        sys.stdout.write(f"   ")
                        _type_text(f'"{accept_reason}"')
                    
                    result = await self._accept(url, job_id, seller_offer, input)
                    
                    # Handle payment
                    tx_hash = None
                    explorer_url = None
                    payment_verified = False
                    
                    if self.auto_pay and self.wallet and seller_address:
                        payment_result = await self._make_payment(
                            seller_address=seller_address,
                            amount=seller_offer,
                            job_id=job_id,
                        )
                        
                        if payment_result.get("success"):
                            tx_hash = payment_result.get("tx_hash")
                            explorer_url = payment_result.get("explorer_url")
                            payment_verified = True
                    
                    if verbose and estimate_info:
                        est_amount = estimate_info.get("amount", 0)
                        if est_amount > 0:
                            pct = (seller_offer / est_amount) * 100
                            print(f"\n   {_C.DIM}Settled at {pct:.0f}% of estimate (${est_amount:.2f}){_C.RESET}")
                    
                    return NegotiationResult(
                        success=True,
                        final_price=seller_offer,
                        output=result.get("result", {}).get("output"),
                        rounds=round_num,
                        history=history,
                        estimate=estimate_info,
                        estimate_id=estimate_id,
                        tx_hash=tx_hash,
                        explorer_url=explorer_url,
                        payment_verified=payment_verified,
                    )
                
                elif decision["action"] == "counter":
                    offer = decision["price"]
                    self._last_reason = decision.get("reason", "Let me counter with this offer.")
                
                else:  # reject
                    if verbose:
                        reason = decision.get("reason", "Price too high")
                        print(f"\n{_C.BUYER}🛒 BUYER{_C.RESET} {_C.DIM}[walks away]{_C.RESET}")
                        sys.stdout.write(f"   ")
                        _type_text(f'"{reason}"')
                    return NegotiationResult(
                        success=False,
                        rounds=round_num,
                        history=history,
                        error=decision.get("reason", "Buyer rejected - price too high"),
                        estimate=estimate_info,
                        estimate_id=estimate_id,
                    )
        
        return NegotiationResult(
            success=False,
            rounds=max_rounds,
            history=history,
            error="Max rounds exceeded",
            estimate=estimate_info,
            estimate_id=estimate_id,
        )
    
    async def _make_payment(
        self,
        seller_address: str,
        amount: float,
        job_id: str,
    ) -> dict:
        """Make payment via real wallet."""
        try:
            from .payments import Payment
            
            payment = Payment(
                job_id=job_id,
                amount=amount,
                buyer_wallet=self.wallet,
                seller_address=seller_address,
            )
            
            result = await payment.execute()
            
            return {
                "success": result.success,
                "tx_hash": result.tx_hash,
                "explorer_url": result.explorer_url,
                "error": result.error,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    async def _discover(self, url: str) -> Optional[dict]:
        """Discover agent info (for payment address and pricing)."""
        try:
            response = await self._http.post(url, json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "apex/discover",
                "params": {},
            })
            result = response.json()
            return result.get("result")
        except Exception:
            return None
    
    async def _estimate(self, url: str, capability: str, input: dict) -> Optional[dict]:
        """Request estimate from agent."""
        try:
            response = await self._http.post(url, json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "apex/estimate",
                "params": {
                    "capability": capability,
                    "input": input,
                },
            })
            result = response.json()
            return result.get("result")
        except Exception:
            return None
    
    def _calculate_initial_offer(self) -> float:
        """Calculate initial offer based on strategy (budget-based)."""
        if self.strategy == "firm":
            pct = 0.5  # Start low
        elif self.strategy == "flexible":
            pct = 0.75  # Start higher
        else:  # balanced or llm
            pct = 0.6
        
        return round(self.budget * pct, 2)
    
    def _calculate_offer_from_estimate(self, estimate: dict) -> float:
        """Calculate initial offer based on estimate - start LOW to allow negotiation."""
        amount = estimate.get("amount", 0)
        low = estimate.get("minimum", estimate.get("low", amount * 0.8))
        
        # Start at 50-70% of estimate to leave room for negotiation
        if self.strategy == "firm":
            # Start very low - 50% of estimate
            offer = amount * 0.5
        elif self.strategy == "flexible":
            # Start at 70% of estimate  
            offer = amount * 0.7
        else:  # balanced or llm
            # Start at 55-60% of estimate
            offer = amount * 0.55
        
        # Never go below seller's minimum (pointless)
        offer = max(offer, low * 0.9)
        
        # Cap at budget
        if offer > self.budget:
            offer = self.budget * 0.6
        
        return round(min(offer, self.budget), 2)
    
    async def _decide(
        self,
        my_offer: float,
        seller_offer: float,
        round_num: int,
        max_rounds: int,
    ) -> dict:
        """Decide how to respond to seller's counter."""
        
        # For LLM strategy, let the LLM decide (don't auto-accept)
        if self.strategy == "llm" and self.model:
            return await self._llm_decide(my_offer, seller_offer, round_num, max_rounds)
        
        # Accept if within budget (for non-LLM strategies)
        if seller_offer <= self.budget:
            if self.strategy == "flexible":
                return {"action": "accept", "reason": "That works for me. Deal!"}
            elif self.strategy == "firm":
                if seller_offer <= my_offer * 1.1:
                    return {"action": "accept"}
            else:  # balanced
                midpoint = (my_offer + seller_offer) / 2
                if seller_offer <= midpoint * 1.1:
                    return {"action": "accept"}
        
        # Last round and over budget - reject
        if round_num >= max_rounds and seller_offer > self.budget:
            return {"action": "reject", "reason": "Exceeds my budget, can't go higher."}
        
        # Algorithmic fallback
        new_offer = self._curve_counter(my_offer, seller_offer, round_num, max_rounds)
        return {"action": "counter", "price": new_offer}
    
    def _curve_counter(
        self,
        my_offer: float,
        seller_offer: float,
        round_num: int,
        max_rounds: int,
    ) -> float:
        """Calculate counter using exponential concession curve."""
        
        # Risk tolerance based on strategy
        if self.strategy == "firm":
            risk = 0.3
        elif self.strategy == "flexible":
            risk = 0.85
        else:
            risk = 0.6
        
        # How much room we have
        room = min(self.budget, seller_offer) - my_offer
        
        # Exponential concession
        progress = round_num / max_rounds
        concession = room * (1 - math.exp(-risk * progress * 3))
        
        new_offer = my_offer + concession
        return round(min(new_offer, self.budget), 2)
    
    async def _llm_decide(
        self,
        my_offer: float,
        seller_offer: float,
        round_num: int,
        max_rounds: int,
    ) -> dict:
        """Use LLM to decide response with reasoning."""
        _load_env()
        
        # Calculate reasonable next offer - move up gradually
        gap = seller_offer - my_offer
        if round_num <= 2:
            concession = gap * 0.25  # Small steps early
        elif round_num <= 3:
            concession = gap * 0.40
        elif round_num <= 4:
            concession = gap * 0.55
        else:
            concession = gap * 0.75  # Big step to close
        
        suggested_offer = round(min(my_offer + concession, self.budget), 2)
        
        # Track if we're at last offer (for accept logic)
        at_budget = suggested_offer >= self.budget * 0.95
        
        # Format prices
        budget_str = f"${self.budget:.2f}"
        my_offer_str = f"${my_offer:.2f}"
        seller_offer_str = f"${seller_offer:.2f}"
        suggested_str = f"${suggested_offer:.2f}"
        
        # Varied dialogue styles per round
        import random
        
        dialogue_styles = {
            1: [
                f"That's higher than I expected for this scope. Would {suggested_str} work?",
                f"Interesting. I was thinking more like {suggested_str} - can we meet there?",
                f"I see - but {suggested_str} is closer to what I had budgeted. Thoughts?",
            ],
            2: [
                f"I appreciate you explaining. How about {suggested_str}?",
                f"That helps, but I can only go up to {suggested_str} right now.",
                f"Let me come up a bit to {suggested_str}. Can you work with that?",
            ],
            3: [
                f"We're getting closer. I can do {suggested_str} - meet me there?",
                f"I'm trying to make this work. {suggested_str} is my best offer.",
                f"Splitting the difference at {suggested_str}?",
            ],
            4: [
                f"{suggested_str} is really my max. Can we shake on it?",
                f"Final push - {suggested_str}. That's all I've got.",
                f"I want this to work. {suggested_str} - deal?",
            ],
            5: [
                "Alright, you've convinced me. Let's do it.",
                "Deal. I can work with that.",
                "Fine, that's fair. Let's move forward.",
            ],
        }
        
        style_options = dialogue_styles.get(round_num, dialogue_styles[5])
        example_style = random.choice(style_options)
        
        # Round-specific guidance
        if round_num <= 2:
            round_guidance = f"""ROUND {round_num} - PUSH BACK:
- Counter at {suggested_str} (don't accept yet!)
- Question their pricing, ask for justification
- Be friendly but firm"""
        elif round_num <= 4:
            round_guidance = f"""ROUND {round_num} - NEGOTIATE:
- Counter at {suggested_str}
- Show you're serious about making a deal
- Move toward middle ground"""
        else:
            round_guidance = f"""ROUND {round_num} (FINAL):
- Accept if their price is reasonable (within budget)
- Or make final counter at {suggested_str}
- This is your last chance"""

        system = f"""You are buying a service. Negotiate smartly with varied responses.

YOUR POSITION:
- Budget: {budget_str} (max)
- Your last offer: {my_offer_str}  
- Seller asking: {seller_offer_str}

{round_guidance}

{self._format_instructions()}

RULES:
1. Your counter must be {suggested_str} or higher (you're going UP)
2. Vary your dialogue - don't repeat "that's a bit high" every time
3. Be conversational, not robotic

Example for this round: "{example_style}"

Respond with ONLY JSON:
{{"action": "counter", "price": {suggested_offer:.2f}, "reason": "Your unique response"}}
{{"action": "accept", "reason": "Brief acceptance"}}

JSON ONLY:"""

        user = f"Seller wants {seller_offer_str}. Round {round_num}/{max_rounds}."

        try:
            response = self._call_llm(system, user)
            result = self._parse_llm_response(response)
            
            # Ensure price doesn't exceed budget
            if result.get("action") == "counter":
                price = result.get("price", suggested_offer)
                result["price"] = round(min(price, self.budget), 2)
            
            return result
        except Exception:
            return {
                "action": "counter",
                "price": suggested_offer,
                "reason": example_style,
            }
    
    def _format_instructions(self) -> str:
        if not self.instructions:
            return ""
        return "Instructions:\n" + "\n".join(f"- {i}" for i in self.instructions)
    
    def _call_llm(self, system: str, user: str) -> str:
        """Call LLM."""
        if "claude" in self.model.lower():
            return self._call_anthropic(system, user)
        return self._call_openai(system, user)
    
    def _call_openai(self, system: str, user: str) -> str:
        from openai import OpenAI
        if self._llm_client is None:
            self._llm_client = OpenAI()
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
    
    def _parse_llm_response(self, text: str) -> dict:
        import json
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        if "{" in text:
            json_str = text[text.index("{"):text.rindex("}") + 1]
            return json.loads(json_str)
        return {"action": "counter", "price": self.budget * 0.8, "reason": "Let's find middle ground."}
    
    async def _propose(
        self, 
        url: str, 
        capability: str, 
        input: dict, 
        offer: float, 
        job_id: str,
        estimate_id: Optional[str] = None,
    ) -> dict:
        params = {
            "capability": capability,
            "input": input,
            "job_id": job_id,
            "offer": {"amount": offer, "currency": "USDC", "network": "base"},
            "buyer_address": self.address,
        }
        
        # Include estimate_id if we have one
        if estimate_id:
            params["estimate_id"] = estimate_id
        
        response = await self._http.post(url, json={
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "apex/propose",
            "params": params,
        })
        return response.json()
    
    async def _counter(self, url: str, job_id: str, offer: float, round_num: int, input: dict) -> dict:
        response = await self._http.post(url, json={
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "apex/counter",
            "params": {
                "job_id": job_id,
                "offer": {"amount": offer, "currency": "USDC", "network": "base"},
                "round": round_num,
                "input": input,
            },
        })
        return response.json()
    
    async def _accept(self, url: str, job_id: str, amount: float, input: dict) -> dict:
        response = await self._http.post(url, json={
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "apex/accept",
            "params": {
                "job_id": job_id,
                "terms": {"amount": amount, "currency": "USDC"},
                "input": input,
            },
        })
        return response.json()


def create_buyer(
    budget: float,
    strategy: Literal["firm", "balanced", "flexible", "llm"] = "balanced",
    model: Optional[str] = None,
    instructions: Optional[list[str]] = None,
    initial_offer_pct: float = 0.6,
    wallet: Optional["Wallet"] = None,
    auto_pay: bool = False,
) -> Buyer:
    """Create an APEX buyer with auto-negotiation.
    
    Args:
        budget: Maximum amount willing to pay
        strategy: Negotiation strategy (firm/balanced/flexible/llm)
        model: LLM model for llm strategy
        instructions: Custom negotiation instructions for LLM
        initial_offer_pct: Starting offer as % of budget (default 60%)
        wallet: Real Wallet instance for payments
        auto_pay: If True, auto-pay on successful negotiation
    
    Returns:
        Buyer instance
    
    Example:
        # Without payments (mock)
        buyer = create_buyer(budget=40.00, strategy="balanced")
        
        # With real payments
        from apex.payments import Wallet
        
        buyer = create_buyer(
            budget=40.00,
            strategy="llm",
            model="gpt-4o-mini",
            wallet=Wallet.from_env("BUYER_KEY"),
            auto_pay=True,
        )
        
        async with buyer:
            result = await buyer.call(
                url="http://localhost:8001/apex",
                capability="research",
                input={"topic": "AI trends"},
            )
            
            if result.success:
                print(f"Paid: {result.explorer_url}")
                print(result.output)
    """
    return Buyer(
        budget=budget,
        strategy=strategy,
        model=model,
        instructions=instructions or [],
        initial_offer_pct=initial_offer_pct,
        wallet=wallet,
        auto_pay=auto_pay,
    )