# APEX Protocol SDK v0.3.0

**Agent-to-Agent Commerce Layer with Real Payments**

APEX enables AI agents to discover, negotiate prices, and pay each other with USDC on Base.

## What's New in v0.3.0

✅ **Real Payments** - USDC transfers on Base blockchain  
✅ **Wallet Management** - Generate, load, and manage agent wallets  
✅ **Auto-Pay** - Buyers can auto-pay on successful negotiation  
✅ **Testnet First** - Defaults to Base Sepolia for safe testing  

## Quick Start (Testnet)

### 1. Generate Wallets

```bash
python examples/demo_testnet.py --setup
```

This creates a `.env` file with two fresh wallets.

### 2. Get Test Tokens (Free)

**Test ETH (for gas):**
- Go to https://www.alchemy.com/faucets/base-sepolia
- Paste your **buyer** address
- Get 0.1 ETH

**Test USDC:**
- Go to https://faucet.circle.com
- Select **Base Sepolia**
- Paste your **buyer** address  
- Get 100 USDC

### 3. Run the Demo

```bash
python examples/demo_testnet.py
```

You'll see:
- Real negotiation between agents
- Real USDC transfer (test tokens)
- Real transaction on BaseScan (Sepolia)

## Switch to Mainnet

When ready for real money:

```bash
# In .env
APEX_NETWORK=base
```

Or in code:
```python
wallet = Wallet.from_env("BUYER_KEY", network="base")
```

Fund with real USDC + ETH on Base mainnet, then run `demo_paid.py`.

## Installation

```bash
pip install apex-protocol
```

Or from source:
```bash
pip install -e .
```

## Code Examples

### Wallet Management

```python
from apex.payments import Wallet

# Generate new wallet
wallet = Wallet.generate()
print(f"Address: {wallet.address}")
print(f"Private key: {wallet.private_key}")  # Save this!

# Load from environment variable
wallet = Wallet.from_env("APEX_PRIVATE_KEY")

# Check balance
balance = await wallet.balance("USDC")
print(f"Balance: ${balance:.2f} USDC")

# Transfer
result = await wallet.transfer(to="0x...", amount=12.50)
print(f"TX: {result.explorer_url}")
```

### Seller Agent

```python
from apex import create_agent, Negotiated
from apex.payments import Wallet

seller_wallet = Wallet.from_env("SELLER_KEY")

agent = create_agent(
    name="Research Agent",
    price=Negotiated(
        target=15.00,
        minimum=5.00,
        strategy="balanced",
    ),
    wallet=seller_wallet,
    handler=my_research_function,
)

agent.serve(port=8001)
```

### Buyer with Auto-Pay

```python
from apex import create_buyer
from apex.payments import Wallet

buyer_wallet = Wallet.from_env("BUYER_KEY")

buyer = create_buyer(
    budget=20.00,
    strategy="balanced",
    wallet=buyer_wallet,
    auto_pay=True,
)

async with buyer:
    result = await buyer.call(
        url="http://localhost:8001/apex",
        capability="research",
        input={"topic": "AI trends"},
        verbose=True,
    )
    
    if result.success:
        print(f"Paid ${result.final_price:.2f} USDC")
        print(f"TX: {result.explorer_url}")
        print(result.output)
```

## File Structure

```
apex/
├── __init__.py          # Main exports
├── agent.py             # Agent class (updated with wallet support)
├── buyer.py             # Buyer class (updated with auto_pay)
├── pricing.py           # Fixed, Negotiated pricing
├── negotiation.py       # Negotiation engine
├── payments/
│   ├── __init__.py      # Payment exports
│   ├── config.py        # Network config (Base, USDC addresses)
│   ├── wallet.py        # Wallet class (generate, load, transfer)
│   └── settlement.py    # Payment execution and verification
└── examples/
    └── demo_paid.py     # Full demo with real payments
```

## Payment Flow

```
Buyer                          Seller
  │                              │
  │─── apex/propose ($10) ──────►│
  │                              │
  │◄─── counter ($15) ───────────│
  │                              │
  │─── apex/counter ($12) ──────►│
  │                              │
  │◄─── accept ──────────────────│
  │                              │
  │                              │
  │    ┌─────────────────────┐   │
  │    │   USDC Transfer     │   │
  │    │   $12.00 on Base    │   │
  │    │   tx: 0x7a3b...     │   │
  │    └─────────────────────┘   │
  │                              │
  │◄─── output ──────────────────│
```

## Networks Supported

| Network | Chain ID | Status |
|---------|----------|--------|
| Base Mainnet | 8453 | ✅ Live |
| Base Sepolia | 84532 | ✅ Testnet |

## API Reference

### Wallet

```python
Wallet.generate()                    # New random wallet
Wallet.from_private_key("0x...")     # Load from key
Wallet.from_env("VAR_NAME")          # Load from env

wallet.address                       # Get address
wallet.private_key                   # Get private key (careful!)
await wallet.balance("USDC")         # Get USDC balance
await wallet.eth_balance()           # Get ETH balance
await wallet.transfer(to, amount)    # Send USDC
```

### NegotiationResult (with payments)

```python
result.success          # bool
result.final_price      # float
result.output           # dict
result.rounds           # int
result.tx_hash          # str (if paid)
result.explorer_url     # str (BaseScan link)
result.payment_verified # bool
```

## Security Notes

- Private keys are sensitive - never commit to git
- Use environment variables or secure vaults
- Test on Base Sepolia before mainnet
- Start with small amounts

## License

MIT
