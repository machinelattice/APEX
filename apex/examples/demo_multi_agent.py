#!/usr/bin/env python3
"""APEX Demo - Multi-Agent Coordination

A buyer agent coordinates with multiple seller agents to complete a task.
Each agent negotiates independently and gets paid.

Flow:
1. Buyer needs a research report on AI agents
2. Buyer negotiates with Research Agent (data gathering)
3. Buyer negotiates with Writing Agent (report writing)  
4. Both agents get paid on-chain
"""

import asyncio
import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["APEX_NETWORK"] = "sepolia"

from apex import create_agent, create_buyer, Negotiated
from apex.payments import Wallet, Payment


# ─── Colors ───────────────────────────────────────────────────────────────────

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"


def type_text(text: str, delay: float = 0.008):
    """Print text with typing effect."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def header(text: str):
    print(f"\n{C.CYAN}{'═'*70}{C.RESET}")
    print(f"{C.BOLD}  {text}{C.RESET}")
    print(f"{C.CYAN}{'═'*70}{C.RESET}")


def section(emoji: str, text: str):
    print(f"\n{C.DIM}{'─'*70}{C.RESET}")
    print(f"{C.BOLD}{emoji} {text}{C.RESET}")
    print(f"{C.DIM}{'─'*70}{C.RESET}")


def agent_header(name: str, color: str, price_range: str, buyer_budget: float):
    print(f"\n{color}┌{'─'*50}┐{C.RESET}")
    print(f"{color}│ 🤖 {name:<46} │{C.RESET}")
    print(f"{color}│    {C.DIM}Seller: {price_range:<38}{color} │{C.RESET}")
    print(f"{color}│    {C.BLUE}Buyer budget: ${buyer_budget:.2f}{' '*26}{color} │{C.RESET}")
    print(f"{color}└{'─'*50}┘{C.RESET}")


def deal_box(agent_name: str, price: float, color: str):
    print(f"\n{color}  ✅ Deal with {agent_name}: ${price:.2f} USDC{C.RESET}")


async def run_demo():
    header("🤝 APEX Protocol — Multi-Agent Coordination Demo")
    
    print(f"\n{C.DIM}Network: Ethereum Sepolia (Testnet){C.RESET}")
    
    # ─── Load Wallets ─────────────────────────────────────────────────
    
    try:
        buyer_wallet = Wallet.from_env("BUYER_PRIVATE_KEY", network="sepolia")
        seller1_wallet = Wallet.from_env("SELLER_PRIVATE_KEY", network="sepolia")
        # Use a different address for seller2 (or same for demo)
        seller2_address = "0x" + "2" * 40  # Mock address for demo
    except ValueError as e:
        print(f"\n{C.RED}❌ {e}{C.RESET}")
        return
    
    initial_balance = await buyer_wallet.balance("USDC")
    print(f"{C.DIM}Buyer balance: ${initial_balance:.2f} USDC{C.RESET}")
    
    if initial_balance < 0.30:
        print(f"\n{C.RED}⚠️ Need at least $0.30 USDC for multi-agent demo{C.RESET}")
        print(f"{C.DIM}Get testnet USDC at: https://faucet.circle.com{C.RESET}")
        return
    
    # ─── Task Description ─────────────────────────────────────────────
    
    total_budget = 0.22  # $0.12 + $0.10
    
    section("📋", f"TASK: Create AI Research Report  |  Budget: ${total_budget:.2f}")
    print(f"""
{C.BLUE}Buyer Agent{C.RESET} needs to produce a research report on "AI Agent Communication"

Required services:
  {C.GREEN}1. Research Agent{C.RESET} - Gather data and sources {C.DIM}(budget: $0.12){C.RESET}
  {C.MAGENTA}2. Writing Agent{C.RESET}  - Compile into final report {C.DIM}(budget: $0.10){C.RESET}

The buyer will negotiate with each agent independently.
""")
    
    await asyncio.sleep(1)
    
    # ─── Create Seller Agents ─────────────────────────────────────────
    
    async def research_handler(input_data: dict) -> dict:
        topic = input_data.get("topic", "unknown")
        return {
            "result": f"Research data compiled on: {topic}",
            "sources": ["arxiv.org", "papers.ai", "scholar.google.com"],
            "data_points": 47,
        }
    
    async def writing_handler(input_data: dict) -> dict:
        topic = input_data.get("topic", "unknown")
        return {
            "result": f"Report written: '{topic}' - 2,500 words",
            "sections": ["Introduction", "Methodology", "Findings", "Conclusion"],
            "format": "markdown",
        }
    
    research_agent = create_agent(
        name="Research Agent",
        price=Negotiated(
            target=0.20,
            minimum=0.08,
            max_rounds=5,
            strategy="llm",
            model="gpt-5.1",
            instructions=["You gather research data.", "Keep responses brief."],
        ),
        wallet=seller1_wallet.address,
        handler=research_handler,
    )
    
    writing_agent = create_agent(
        name="Writing Agent", 
        price=Negotiated(
            target=0.15,
            minimum=0.06,
            max_rounds=5,
            strategy="llm",
            model="gpt-5.1",
            instructions=["You write professional reports.", "Keep responses brief."],
        ),
        wallet=seller1_wallet.address,  # Same wallet for demo (would be different in prod)
        handler=writing_handler,
    )
    
    # ─── Start Servers ────────────────────────────────────────────────
    
    import threading
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    
    async def handle_research(request: Request) -> JSONResponse:
        return JSONResponse(await research_agent.handle(await request.json()))
    
    async def handle_writing(request: Request) -> JSONResponse:
        return JSONResponse(await writing_agent.handle(await request.json()))
    
    app = Starlette(routes=[
        Route("/research", handle_research, methods=["POST"]),
        Route("/writing", handle_writing, methods=["POST"]),
    ])
    
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8001, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    await asyncio.sleep(1)
    
    # ─── Negotiation 1: Research Agent ────────────────────────────────
    
    section("💬", "NEGOTIATION 1: Research Agent")
    agent_header("Research Agent", C.GREEN, "$0.08 - $0.20", 0.12)
    
    buyer1 = create_buyer(
        budget=0.12,
        strategy="llm",
        model="gpt-5.1",
        instructions=["Negotiate for research services.", "Be professional."],
        wallet=buyer_wallet,
        auto_pay=False,
    )
    
    async with buyer1:
        result1 = await buyer1.call(
            url="http://127.0.0.1:8001/research",
            capability="research",
            input={"topic": "AI agent communication protocols"},
            max_rounds=5,
            verbose=True,
        )
    
    if not result1.success:
        print(f"{C.RED}❌ Failed to negotiate with Research Agent{C.RESET}")
        return
    
    deal_box("Research Agent", result1.final_price, C.GREEN)
    
    await asyncio.sleep(0.5)
    
    # ─── Negotiation 2: Writing Agent ─────────────────────────────────
    
    section("💬", "NEGOTIATION 2: Writing Agent")
    agent_header("Writing Agent", C.MAGENTA, "$0.06 - $0.15", 0.10)
    
    buyer2 = create_buyer(
        budget=0.10,
        strategy="llm",
        model="gpt-5.1",
        instructions=["Negotiate for writing services.", "Be professional."],
        wallet=buyer_wallet,
        auto_pay=False,
    )
    
    async with buyer2:
        result2 = await buyer2.call(
            url="http://127.0.0.1:8001/writing",
            capability="writing",
            input={"topic": "AI agent communication protocols", "research_data": result1.output},
            max_rounds=5,
            verbose=True,
        )
    
    if not result2.success:
        print(f"{C.RED}❌ Failed to negotiate with Writing Agent{C.RESET}")
        return
    
    deal_box("Writing Agent", result2.final_price, C.MAGENTA)
    
    # ─── Summary ──────────────────────────────────────────────────────
    
    total_cost = result1.final_price + result2.final_price
    
    section("📊", "NEGOTIATION SUMMARY")
    print(f"""
  {C.GREEN}Research Agent:{C.RESET}  ${result1.final_price:.2f} ({result1.rounds} rounds)
  {C.MAGENTA}Writing Agent:{C.RESET}   ${result2.final_price:.2f} ({result2.rounds} rounds)
  {C.DIM}{'─'*30}{C.RESET}
  {C.BOLD}Total Cost:{C.RESET}       ${total_cost:.2f} USDC
""")
    
    # ─── Payments ─────────────────────────────────────────────────────
    
    section("💸", "PROCESSING PAYMENTS")
    
    import concurrent.futures
    
    total_paid = 0.0
    
    def show_spinner(message: str, done_flag: list):
        """Show spinner until done_flag[0] is True."""
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while not done_flag[0]:
            sys.stdout.write(f"\r{C.DIM}  {chars[i % len(chars)]} {message}{C.RESET}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.1)
        sys.stdout.write("\r" + " " * (len(message) + 10) + "\r")
        sys.stdout.flush()
    
    # Payment 1
    done1 = [False]
    spinner_thread1 = threading.Thread(target=show_spinner, args=(f"Paying Research Agent ${result1.final_price:.2f}...", done1))
    spinner_thread1.start()
    
    payment1 = Payment(
        job_id="research-job",
        amount=result1.final_price,
        buyer_wallet=buyer_wallet,
        seller_address=seller1_wallet.address,
    )
    pay1 = await payment1.execute()
    
    done1[0] = True
    spinner_thread1.join()
    
    if pay1.success:
        print(f"{C.GREEN}  ✅ Research Agent: ${result1.final_price:.2f}{C.RESET}")
        print(f"{C.DIM}     {pay1.explorer_url}{C.RESET}")
        total_paid += result1.final_price
    else:
        print(f"{C.RED}  ❌ Research Agent failed: {pay1.error}{C.RESET}")
    
    await asyncio.sleep(2)  # Wait for nonce to update
    
    # Payment 2
    done2 = [False]
    spinner_thread2 = threading.Thread(target=show_spinner, args=(f"Paying Writing Agent ${result2.final_price:.2f}...", done2))
    spinner_thread2.start()
    
    payment2 = Payment(
        job_id="writing-job",
        amount=result2.final_price,
        buyer_wallet=buyer_wallet,
        seller_address=seller1_wallet.address,
    )
    pay2 = await payment2.execute()
    
    done2[0] = True
    spinner_thread2.join()
    
    if pay2.success:
        print(f"{C.MAGENTA}  ✅ Writing Agent: ${result2.final_price:.2f}{C.RESET}")
        print(f"{C.DIM}     {pay2.explorer_url}{C.RESET}")
        total_paid += result2.final_price
    else:
        print(f"{C.RED}  ❌ Writing Agent failed: {pay2.error}{C.RESET}")
    
    # ─── Final Balances ───────────────────────────────────────────────
    
    section("💰", "FINAL BALANCES")
    
    final_balance = await buyer_wallet.balance("USDC")
    seller_balance = await seller1_wallet.balance("USDC")
    
    print(f"""
  {C.BLUE}Buyer:{C.RESET}   ${final_balance:.2f} USDC {C.DIM}(was ${initial_balance:.2f}, spent ${total_paid:.2f}){C.RESET}
  {C.GREEN}Sellers:{C.RESET} ${seller_balance:.2f} USDC
""")
    
    # ─── Task Complete ────────────────────────────────────────────────
    
    print(f"{C.CYAN}{'═'*70}{C.RESET}")
    print(f"{C.BOLD}  🚀 Multi-Agent Task Completed!{C.RESET}")
    print(f"{C.DIM}  • 2 AI agents discovered and negotiated with autonomously{C.RESET}")
    print(f"{C.DIM}  • {result1.rounds + result2.rounds} total negotiation rounds{C.RESET}")
    print(f"{C.DIM}  • ${total_paid:.2f} USDC transferred on-chain{C.RESET}")
    print(f"{C.CYAN}{'═'*70}{C.RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_demo())