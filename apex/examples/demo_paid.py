#!/usr/bin/env python3
"""APEX Demo - Real Payments on Base

This demo shows AI agents negotiating and paying each other with real USDC.

Setup:
    1. Create .env file with:
       BUYER_PRIVATE_KEY=0x...     # Buyer wallet (needs USDC + ETH for gas)
       SELLER_PRIVATE_KEY=0x...    # Seller wallet (receives payments)
       OPENAI_API_KEY=sk-...       # For LLM negotiation
    
    2. Fund buyer wallet with:
       - ~$20 USDC on Base
       - ~$1 ETH for gas
    
    3. Run: python demo_paid.py

What happens:
    1. Buyer agent negotiates with Seller agent
    2. They agree on a price
    3. Buyer sends USDC to Seller
    4. Transaction appears on BaseScan
    5. Seller executes the task
"""

import asyncio
import sys
import time
from pathlib import Path

# Add parent to path for local development
sys.path.insert(0, str(Path(__file__).parent.parent))


def type_text(text: str, delay: float = 0.02):
    """Print with typing effect."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()


async def main():
    from apex import create_agent, create_buyer, Negotiated, Fixed
    from apex.payments import Wallet
    
    print()
    print("=" * 65)
    print("  APEX Protocol Demo - Real Payments")
    print("=" * 65)
    print()
    
    # ─── Load Wallets ─────────────────────────────────────────────────
    
    try:
        buyer_wallet = Wallet.from_env("BUYER_PRIVATE_KEY")
        seller_wallet = Wallet.from_env("SELLER_PRIVATE_KEY")
    except ValueError as e:
        print("❌ Wallet setup error:")
        print(f"   {e}")
        print()
        print("   Create a .env file with:")
        print("   BUYER_PRIVATE_KEY=0x...")
        print("   SELLER_PRIVATE_KEY=0x...")
        return
    
    print(f"🔑 Buyer Wallet:  {buyer_wallet.address}")
    print(f"🔑 Seller Wallet: {seller_wallet.address}")
    print()
    
    # ─── Check Balances ───────────────────────────────────────────────
    
    print("💰 Checking balances...")
    
    try:
        buyer_balance = await buyer_wallet.balance("USDC")
        seller_balance = await seller_wallet.balance("USDC")
        buyer_eth = await buyer_wallet.eth_balance()
        
        print(f"   Buyer:  ${buyer_balance:.2f} USDC, {buyer_eth:.4f} ETH")
        print(f"   Seller: ${seller_balance:.2f} USDC")
        print()
        
        if buyer_balance < 5:
            print("❌ Buyer needs at least $5 USDC")
            print("   Send USDC to:", buyer_wallet.address)
            return
        
        if buyer_eth < 0.0001:
            print("❌ Buyer needs ETH for gas")
            print("   Send ETH to:", buyer_wallet.address)
            return
            
    except Exception as e:
        print(f"⚠️  Could not check balances: {e}")
        print("   Continuing anyway...")
        print()
    
    # ─── Create Seller Agent ──────────────────────────────────────────
    
    print("🤖 Starting Seller Agent...")
    
    async def research_handler(input_data: dict) -> dict:
        """Simple handler that returns a mock result."""
        topic = input_data.get("topic", "unknown")
        await asyncio.sleep(1)  # Simulate work
        return {
            "result": f"Research report on '{topic}': AI is transforming industries through automation, enhanced decision-making, and personalized experiences.",
            "status": "completed",
        }
    
    seller_agent = create_agent(
        name="Research Agent",
        price=Negotiated(
            target=15.00,
            minimum=5.00,
            max_rounds=5,
            strategy="llm",
            model="gpt-4o-mini",
            instructions=[
                "Be friendly but professional.",
                "Start firm, become flexible in later rounds.",
                "Your goal is to make a deal.",
            ],
        ),
        description="AI research and analysis",
        wallet=seller_wallet,
        handler=research_handler,
    )
    
    print(f"   Name: {seller_agent.name}")
    print(f"   Price: $5-15 USDC (negotiable)")
    print(f"   Wallet: {seller_agent.wallet_address[:20]}...")
    print()
    
    # ─── Start Server in Background ───────────────────────────────────
    
    import threading
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    
    async def handle_apex(request: Request) -> JSONResponse:
        body = await request.json()
        response = await seller_agent.handle(body)
        return JSONResponse(response)
    
    app = Starlette(routes=[
        Route("/apex", handle_apex, methods=["POST"]),
    ])
    
    server_config = uvicorn.Config(app, host="127.0.0.1", port=8001, log_level="error")
    server = uvicorn.Server(server_config)
    
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    
    await asyncio.sleep(1)  # Wait for server
    print("   Server running on http://127.0.0.1:8001/apex")
    print()
    
    # ─── Create Buyer ─────────────────────────────────────────────────
    
    print("🛒 Creating Buyer Agent...")
    
    buyer = create_buyer(
        budget=12.00,
        strategy="balanced",
        wallet=buyer_wallet,
        auto_pay=True,  # Real payments!
    )
    
    print(f"   Budget: $12.00 USDC")
    print(f"   Wallet: {buyer.address[:20]}...")
    print(f"   Auto-pay: Enabled ✓")
    print()
    
    # ─── Negotiate and Pay ────────────────────────────────────────────
    
    print("─" * 65)
    print("  NEGOTIATION")
    print("─" * 65)
    print()
    
    async with buyer:
        result = await buyer.call(
            url="http://127.0.0.1:8001/apex",
            capability="research",
            input={"topic": "AI trends in 2025"},
            max_rounds=5,
            verbose=True,
        )
    
    print()
    print("─" * 65)
    print("  RESULT")
    print("─" * 65)
    print()
    
    if result.success:
        print(f"✅ Negotiation successful!")
        print(f"   Final price: ${result.final_price:.2f} USDC")
        print(f"   Rounds: {result.rounds}")
        print()
        
        if result.tx_hash:
            print(f"💸 Payment:")
            print(f"   Transaction: {result.tx_hash}")
            print(f"   Explorer: {result.explorer_url}")
            print()
        
        print(f"📄 Output:")
        type_text(f"   {result.output.get('result', result.output)}", delay=0.01)
        
        # Show updated balances
        print()
        print("💰 Updated balances:")
        try:
            new_buyer = await buyer_wallet.balance("USDC")
            new_seller = await seller_wallet.balance("USDC")
            print(f"   Buyer:  ${new_buyer:.2f} USDC (was ${buyer_balance:.2f})")
            print(f"   Seller: ${new_seller:.2f} USDC (was ${seller_balance:.2f})")
        except:
            pass
    else:
        print(f"❌ Negotiation failed: {result.error}")
        print()
        print("   History:")
        for h in result.history:
            print(f"   - {h['party']}: ${h['amount']:.2f} (round {h['round']})")
    
    print()
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
