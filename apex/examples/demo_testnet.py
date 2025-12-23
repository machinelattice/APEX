#!/usr/bin/env python3
"""APEX Demo - Real AI Negotiation with Payments

Uses the apex SDK properly - no custom negotiation code.
"""

import asyncio
import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["APEX_NETWORK"] = "sepolia"

from apex import create_agent, create_buyer, Negotiated
from apex.payments import Wallet


# ─── Colors ───────────────────────────────────────────────────────────────────

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    BUYER = "\033[94m"
    SELLER = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"


def header(text: str):
    print(f"\n{C.CYAN}{'─'*60}{C.RESET}")
    print(f"{C.BOLD}🤝 {text}{C.RESET}")
    print(f"{C.CYAN}{'─'*60}{C.RESET}")


def section(emoji: str, text: str):
    print(f"\n{C.DIM}{'─'*60}{C.RESET}")
    print(f"{C.BOLD}{emoji} {text}{C.RESET}")
    print(f"{C.DIM}{'─'*60}{C.RESET}")


async def run_demo():
    header("APEX Protocol — AI Agent Negotiation Demo")
    
    # ─── Load Wallets ─────────────────────────────────────────────────
    
    try:
        buyer_wallet = Wallet.from_env("BUYER_PRIVATE_KEY", network="sepolia")
        seller_wallet = Wallet.from_env("SELLER_PRIVATE_KEY", network="sepolia")
    except ValueError as e:
        print(f"\n{C.RED}❌ {e}{C.RESET}")
        return
    
    buyer_usdc = await buyer_wallet.balance("USDC")
    if buyer_usdc < 0.10:
        print(f"\n{C.RED}⚠️ Need at least $0.10 USDC. Get more at https://faucet.circle.com{C.RESET}")
        return
    
    # ─── Task ─────────────────────────────────────────────────────────
    
    section("📋", "TASK")
    print(f"{C.BUYER}Buyer{C.RESET} wants: Research on 'AI agent communication'")
    print(f"{C.BUYER}Budget:{C.RESET} $0.15 max")
    print(f"{C.SELLER}Seller{C.RESET} wants: $0.25 (will go as low as $0.12)")
    
    # ─── Create Seller Agent ──────────────────────────────────────────
    
    async def research_handler(input_data: dict) -> dict:
        return {"result": f"Research completed on: {input_data.get('topic', '?')}"}
    
    seller_agent = create_agent(
        name="Research Agent",
        price=Negotiated(
            target=0.25,
            minimum=0.12,
            max_rounds=5,
            strategy="llm",
            model="gpt-4o-mini",
            instructions=[
                "Start near your target price and concede slowly.",
                "Keep responses to 1-2 sentences.",
            ],
        ),
        wallet=seller_wallet.address,
        handler=research_handler,
    )
    
    # ─── Start Server ─────────────────────────────────────────────────
    
    import threading
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    
    async def handle_apex(request: Request) -> JSONResponse:
        return JSONResponse(await seller_agent.handle(await request.json()))
    
    app = Starlette(routes=[Route("/apex", handle_apex, methods=["POST"])])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8001, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    await asyncio.sleep(1)
    
    # ─── Create Buyer (using SDK!) ────────────────────────────────────
    
    buyer = create_buyer(
        budget=0.15,
        strategy="llm",
        model="gpt-4o-mini",
        instructions=[
            "You need quality research but have a tight budget.",
            "Be professional and negotiate firmly.",
            "Keep responses to 1-2 sentences.",
        ],
        wallet=buyer_wallet,
        auto_pay=False,  # Handle payment manually after showing deal
    )
    
    # ─── Negotiate (using SDK!) ───────────────────────────────────────
    
    section("💬", "NEGOTIATION")
    
    async with buyer:
        result = await buyer.call(
            url="http://127.0.0.1:8001/apex",
            capability="research",
            input={"topic": "AI agent communication"},
            max_rounds=5,
            verbose=True,  # SDK prints the conversation
        )
    
    # ─── Result ───────────────────────────────────────────────────────
    
    if result.success:
        print(f"\n{C.SELLER}╔{'═'*44}╗")
        print(f"║  ✅ DEAL REACHED — ${result.final_price:.2f} USDC{' '*17}║")
        print(f"╚{'═'*44}╝{C.RESET}")
        
        # Now process payment with spinner
        section("💸", "PAYMENT")
        
        import threading
        
        def show_spinner(message: str, done_flag: list):
            chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            i = 0
            while not done_flag[0]:
                sys.stdout.write(f"\r{C.DIM}  {chars[i % len(chars)]} {message}{C.RESET}")
                sys.stdout.flush()
                i += 1
                time.sleep(0.1)
            sys.stdout.write("\r" + " " * (len(message) + 10) + "\r")
            sys.stdout.flush()
        
        done = [False]
        spinner_thread = threading.Thread(target=show_spinner, args=(f"Sending ${result.final_price:.2f} USDC...", done))
        spinner_thread.start()
        
        from apex.payments import Payment
        payment = Payment(
            job_id="demo",
            amount=result.final_price,
            buyer_wallet=buyer_wallet,
            seller_address=seller_wallet.address,
        )
        pay_result = await payment.execute()
        
        done[0] = True
        spinner_thread.join()
        
        if pay_result.success:
            print(f"{C.SELLER}✅ Confirmed!{C.RESET} {C.DIM}{pay_result.explorer_url}{C.RESET}")
            
            new_buyer = await buyer_wallet.balance("USDC")
            new_seller = await seller_wallet.balance("USDC")
            print(f"\n{C.BOLD}💰 Balances:{C.RESET}")
            print(f"   {C.BUYER}Buyer:{C.RESET}  ${new_buyer:.2f} {C.DIM}(was ${buyer_usdc:.2f}){C.RESET}")
            print(f"   {C.SELLER}Seller:{C.RESET} ${new_seller:.2f}")
        else:
            print(f"{C.RED}⚠️ Payment failed: {pay_result.error}{C.RESET}")
    else:
        print(f"\n{C.RED}╔{'═'*44}╗")
        print(f"║  ❌ NO DEAL — {result.error[:28]:<28}║")
        print(f"╚{'═'*44}╝{C.RESET}")
    
    print(f"\n{C.CYAN}{'─'*60}{C.RESET}")
    print(f"{C.BOLD}🚀 Two AI agents negotiated and transacted autonomously!{C.RESET}")
    print(f"{C.CYAN}{'─'*60}{C.RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_demo())