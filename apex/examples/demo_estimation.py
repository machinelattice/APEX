#!/usr/bin/env python3
"""APEX Demo - Estimation + Negotiation

Shows the full flow:
1. AI estimates task complexity and price (seller's target)
2. Buyer has budget BELOW seller's target (creates tension!)
3. Real negotiation: seller starts at target, concedes toward minimum
4. Deal closes somewhere between buyer's budget and seller's minimum

Key insight: Negotiation only makes sense when:
- Buyer budget < Seller target (there's a gap to close)
- Buyer budget >= Seller minimum (deal is possible)
"""

import asyncio
import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from apex import create_agent, create_buyer, Negotiated
from apex.estimation import estimate_task

BASE_RATE = 20.00


def type_text(text: str, delay: float = 0.015):
    """Print with typing effect."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def load_openai_api_key():
    """Load OpenAI API key from environment variable or .env file."""
    # Check if already set
    if os.environ.get("OPENAI_API_KEY"):
        return
    
    # Try to load from .env file
    search_paths = [
        Path.cwd() / ".env",
        Path(__file__).parent.parent.parent / ".env",
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
                        if key == "OPENAI_API_KEY" and key not in os.environ:
                            os.environ[key] = value
                            return


async def run_demo():
    # Load OpenAI API key from environment
    load_openai_api_key()
    
    # Check if API key is set
    if not os.environ.get("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY not found in environment")
        print("   Please set OPENAI_API_KEY environment variable or add it to a .env file")
        return
    print()
    print("=" * 65)
    print("  APEX Protocol - Estimation + Negotiation Demo")
    print("=" * 65)
    print()
    
    # ─── Setup Agent ──────────────────────────────────────────────────
    
    async def research_handler(input_data: dict) -> dict:
        topic = input_data.get("topic", "unknown")
        return {"result": f"Research completed on: {topic[:50]}..."}
    
    agent = create_agent(
        name="Research Agent",
        price=Negotiated(
            base=BASE_RATE,
            model="gpt-5.1",
            instructions=[
                "0.5x: Quick factual lookup",
                "1.0x: Standard research",
                "2.0x: Deep multi-source analysis",
                "3.0x: Cross-domain comprehensive research",
            ],
        ),
        handler=research_handler,
    )
    
    # Start server
    import threading
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    
    async def handle(r: Request) -> JSONResponse:
        return JSONResponse(await agent.handle(await r.json()))
    
    app = Starlette(routes=[Route("/apex", handle, methods=["POST"])])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8001, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    await asyncio.sleep(1)
    
    print("🤖 Research Agent running on http://127.0.0.1:8001/apex")
    print()
    
    # ══════════════════════════════════════════════════════════════════
    # TASK 1: Standard Research
    # ══════════════════════════════════════════════════════════════════
    
    print("─" * 65)
    print("  TASK 1: Standard Research")
    print("─" * 65)
    print()
    
    task1 = "Find the top 5 Python ORMs, compare GitHub stars and use cases."
    print(f'📋 "{task1}"')
    print()
    
    # Step 1: Estimate
    print("💡 ESTIMATION")
    print("─" * 40)
    
    est1 = await estimate_task(
        input={"topic": task1},
        base=BASE_RATE,
        model="gpt-5.1",
        capability="research",
    )
    
    print(f"   AI Analysis: ", end="")
    type_text(est1.reasoning or "Standard research task.", delay=0.012)
    print()
    print(f"   Estimate:  ${est1.estimate.amount:.2f}")
    print(f"   Minimum:   ${est1.estimate.minimum:.2f}")
    print()
    
    # Step 2: Negotiate with tight budget BELOW seller's target
    # This creates real tension - buyer can't afford full price!
    buyer_budget_1 = est1.estimate.amount * 0.92  # 92% of estimate
    
    print("💬 NEGOTIATION")
    print("─" * 40)
    print(f"   Seller target: ${est1.estimate.amount:.2f}")
    print(f"   Buyer budget:  ${buyer_budget_1:.2f} (92% - below target!)")
    print(f"   Seller floor:  ${est1.estimate.minimum:.2f}")
    print()
    
    buyer1 = create_buyer(budget=buyer_budget_1, strategy="llm", model="gpt-5.1")
    async with buyer1:
        r1 = await buyer1.call(
            url="http://127.0.0.1:8001/apex",
            capability="research",
            input={"topic": task1},
            max_rounds=5,
            verbose=True,
        )
    
    print()
    if r1.success:
        print(f"✅ Deal: ${r1.final_price:.2f} (estimate was ${est1.estimate.amount:.2f})")
    else:
        print(f"❌ No deal: {r1.error}")
    
    await asyncio.sleep(2)
    
    # ══════════════════════════════════════════════════════════════════
    # TASK 2: Complex Analysis
    # ══════════════════════════════════════════════════════════════════
    
    print()
    print()
    print("─" * 65)
    print("  TASK 2: Complex Cross-Domain Analysis")
    print("─" * 65)
    print()
    
    task2 = "Compare REST vs GraphQL vs gRPC for fintech: latency, compliance, case studies from Stripe/Square."
    print(f'📋 "{task2}"')
    print()
    
    # Step 1: Estimate
    print("💡 ESTIMATION")
    print("─" * 40)
    
    est2 = await estimate_task(
        input={"topic": task2},
        base=BASE_RATE,
        model="gpt-5.1",
        capability="research",
    )
    
    print(f"   AI Analysis: ", end="")
    type_text(est2.reasoning or "Complex cross-domain analysis.", delay=0.012)
    print()
    print(f"   Estimate:  ${est2.estimate.amount:.2f}")
    print(f"   Minimum:   ${est2.estimate.minimum:.2f}")
    print()
    
    # Step 2: Negotiate with tight budget BELOW seller's target
    buyer_budget_2 = est2.estimate.amount * 0.88  # 88% - tighter than task 1
    
    print("💬 NEGOTIATION")
    print("─" * 40)
    print(f"   Seller target: ${est2.estimate.amount:.2f}")
    print(f"   Buyer budget:  ${buyer_budget_2:.2f} (88% - below target!)")
    print(f"   Seller floor:  ${est2.estimate.minimum:.2f}")
    print()
    
    buyer2 = create_buyer(budget=buyer_budget_2, strategy="llm", model="gpt-5.1")
    async with buyer2:
        r2 = await buyer2.call(
            url="http://127.0.0.1:8001/apex",
            capability="research",
            input={"topic": task2},
            max_rounds=5,
            verbose=True,
        )
    
    print()
    if r2.success:
        print(f"✅ Deal: ${r2.final_price:.2f} (estimate was ${est2.estimate.amount:.2f})")
    else:
        print(f"❌ No deal: {r2.error}")
    
    await asyncio.sleep(2)
    
    # ══════════════════════════════════════════════════════════════════
    # TASK 3: Budget Too Low (Fail Fast)
    # ══════════════════════════════════════════════════════════════════
    
    print()
    print()
    print("─" * 65)
    print("  TASK 3: Same Task, Budget Too Low")
    print("─" * 65)
    print()
    
    print(f'📋 "{task2[:50]}..." (budget: $15)')
    print()
    
    # Step 1: Estimate (reuse est2)
    print("💡 ESTIMATION")
    print("─" * 40)
    print(f"   Estimate:  ${est2.estimate.amount:.2f}")
    print(f"   Minimum:   ${est2.estimate.minimum:.2f}")
    print()
    
    # Check budget before negotiating
    buyer_budget = 15.00
    if buyer_budget < est2.estimate.minimum:
        print("⚠️  BUDGET CHECK")
        print("─" * 40)
        print(f"   Buyer budget:   ${buyer_budget:.2f}")
        print(f"   Seller minimum: ${est2.estimate.minimum:.2f}")
        print()
        print("   ❌ No negotiation - buyer can't afford seller's minimum.")
    else:
        # Would negotiate here
        pass
    
    # ══════════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════════
    
    print()
    print()
    print("=" * 65)
    print("  SUMMARY")
    print("=" * 65)
    print()
    
    if r1.success:
        print(f"  • Task 1: ${est1.estimate.amount:.2f} estimate → ${r1.final_price:.2f} deal")
    if r2.success:
        print(f"  • Task 2: ${est2.estimate.amount:.2f} estimate → ${r2.final_price:.2f} deal")
    print(f"  • Task 3: ${est2.estimate.amount:.2f} estimate → budget too low, no negotiation")
    print()
    print("  Same agent. AI adjusts price based on task complexity.")
    print()
    print("=" * 65)
    print()


if __name__ == "__main__":
    asyncio.run(run_demo())