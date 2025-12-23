# Agent Payment EXchange (APEX) Protocol

**Your skills. Your prices. Your income.**

[![Version](https://img.shields.io/badge/version-0.3.0-blue)](https://github.com/apex-protocol/apex-sdk)
[![Python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![Payments](https://img.shields.io/badge/payments-USDC%20on%20Base-purple)](https://base.org)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](./LICENSE)

APEX adds an economic layer to AI agent skills. Your agents can discover each other, negotiate prices, and settle payments—autonomously.

```
pip install apex-protocol
```

---

## Why APEX?

AI agents are getting incredibly capable. But they can't pay each other.

| Today | With APEX |
|-------|-----------|
| Fixed API pricing | Agents negotiate their own deals |
| Manual invoicing | Instant USDC settlement |
| Human approval for every purchase | Autonomous transactions |
| Take-it-or-leave-it pricing | Multi-round bargaining |
| Agents can't refuse bad deals | Agents walk away when price is wrong |

**APEX enables genuine agent autonomy.** When your agent can negotiate and reject unfavorable terms, it's not just executing API calls—it's making economic decisions.

---

## APEX vs x402

[x402](https://x402.org) is a great protocol for pay-per-request APIs. APEX solves a different problem.

| | x402 | APEX |
|---|------|------|
| **Model** | Fixed price, pay-or-don't | Multi-round negotiation |
| **Pricing** | Server sets price, client pays | Agents bargain to agreement |
| **Autonomy** | Client pays the listed price | Agent can reject bad deals |
| **Integration** | HTTP middleware (402 status) | Protocol layer (transport-agnostic) |
| **Focus** | API monetization | Skill monetization |
| **Best for** | Micropayments, simple APIs | Complex services, agent-to-agent commerce |

**Use x402** when you have a simple API and want instant pay-per-request.

**Use APEX** when your agents need to negotiate, compare options, and make economic decisions.

They're complementary: APEX agents could use x402 for commodity resources while negotiating premium services via APEX.

---

## Quick Start

### Your First Paid Agent (60 seconds)

```python
import apex

agent = apex.from_curl(
    name="GPT Assistant",
    curl='''curl -X POST https://api.openai.com/v1/chat/completions \
      -H "Authorization: Bearer $OPENAI_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "{{input.query}}"}]}'
    ''',
    price=apex.Fixed(0.05),  # 5 cents per request
)

agent.serve(port=8001)
```

Your agent is now live at `http://localhost:8001/apex`. Other agents can discover it, negotiate a price, and pay for its services.

---

## Three Paths to Monetization

### 1. Monetize an Existing Skill

Have a skill folder already? Add pricing with one command:

```
my-skill/
├── SKILL.md      # Capability definition
└── handler.py    # Your implementation
```

```python
import apex

apex.add_apex("./my-skill", price=apex.Fixed(5.00))
```

This creates `apex.yaml` with your pricing config. Now serve it:

```python
agent = apex.load("./my-skill")
agent.serve(port=8001)
```

---

### 2. Wrap a REST API

Convert any API into a monetized skill:

```python
import apex

agent = apex.from_api(
    name="Weather Service",
    endpoint="https://api.weatherapi.com/v1/current.json",
    method="GET",
    params={
        "key": "{{env.WEATHER_API_KEY}}",
        "q": "{{input.city}}",
    },
    output="current.temp_f",
    price=apex.Negotiated(
        target=0.50,
        minimum=0.10,
    ),
)

agent.serve(port=8001)
```

---

### 3. Wrap a Curl Command

Have a working curl? That's all you need:

```python
import apex

agent = apex.from_curl(
    name="Slack Notifier",
    curl='''
    curl -X POST https://slack.com/api/chat.postMessage \
      -H "Authorization: Bearer $SLACK_TOKEN" \
      -d '{"channel": "{{input.channel}}", "text": "{{input.message}}"}'
    ''',
    price=apex.Fixed(0.25),
)

agent.serve(port=8001)
```

---

## Pricing Models

### Fixed Pricing

Exact price, no negotiation:

```python
apex.Fixed(5.00)
apex.Fixed(0.10, currency="USDC")
```

### Negotiated Pricing

Let agents bargain:

```python
apex.Negotiated(
    target=50.00,       # Your ideal price
    minimum=20.00,      # Absolute floor
    max_rounds=5,       # Max back-and-forth
    strategy="balanced" # Negotiation style
)
```

**Strategies:**

| Strategy | Behavior | Best For |
|----------|----------|----------|
| `firm` | Holds near target, minimal concessions | Premium services |
| `balanced` | Moderate concessions | General use (default) |
| `flexible` | Faster concessions, closes deals | High volume |
| `llm` | AI controls price and reasoning | Complex negotiations |

**LLM-Powered Negotiation:**

```python
apex.Negotiated(
    target=50.00,
    minimum=20.00,
    strategy="llm",
    model="gpt-4o-mini",
    instructions=[
        "Emphasize quality and thoroughness.",
        "Offer 10% discount for repeat customers.",
        "Never go below $25 in first two rounds.",
    ],
)
```

---

## Buying Services

Create a buyer that auto-negotiates and pays:

```python
from apex import create_buyer
from apex.payments import Wallet

wallet = Wallet.from_env("BUYER_PRIVATE_KEY")

buyer = create_buyer(
    budget=30.00,
    strategy="balanced",
    wallet=wallet,
    auto_pay=True,
)

async with buyer:
    result = await buyer.call(
        url="http://research-agent.com/apex",
        capability="research",
        input={"topic": "quantum computing"},
        verbose=True,
    )
    
    if result.success:
        print(f"Paid: ${result.final_price:.2f}")
        print(f"TX: {result.explorer_url}")
        print(result.output)
```

**Verbose Output:**

```
▸ Round 1/5

🛒 BUYER [offers $18.00]
   "I'd like to use your research services."

🤖 SELLER [$28.00]
   "Quality research takes time. $28 is fair."

▸ Round 2/5

🛒 BUYER [offers $22.00]
   "That's a bit high. How about $22?"

🤖 SELLER [$25.00]
   "I can do $25 for comprehensive research."

▸ Round 3/5

🛒 BUYER [accepts $25.00]
   "Deal!"

✅ Seller accepted $25.00
💸 Payment confirmed: https://basescan.org/tx/0x7a3b...
```

---

## Real Payments

APEX uses USDC on Base for fast, cheap, real payments.

### Wallet Management

```python
from apex.payments import Wallet

# Generate new wallet
wallet = Wallet.generate()
print(f"Address: {wallet.address}")
print(f"Key: {wallet.private_key}")  # Save securely!

# Load from environment
wallet = Wallet.from_env("APEX_PRIVATE_KEY")

# Check balances
usdc = await wallet.balance("USDC")
eth = await wallet.eth_balance()
print(f"${usdc:.2f} USDC, {eth:.4f} ETH")

# Transfer
result = await wallet.transfer(to="0x...", amount=10.00)
print(f"TX: {result.explorer_url}")
```

### Networks

| Network | Chain ID | Purpose |
|---------|----------|---------|
| Base Sepolia | 84532 | Testing (default) |
| Base Mainnet | 8453 | Production |

```bash
APEX_NETWORK=base-sepolia  # Testnet (default)
APEX_NETWORK=base          # Mainnet (real money!)
```

### Get Test Tokens (Free)

1. **Test ETH**: https://www.alchemy.com/faucets/base-sepolia
2. **Test USDC**: https://faucet.circle.com (select Base Sepolia)

---

## Skill Folder Format

APEX extends the [Agent Skills](https://agentskills.io) standard:

```
my-skill/
├── SKILL.md          # Capability description
├── handler.py        # Implementation
├── apex.yaml         # APEX pricing config
└── requirements.txt  # Dependencies
```

### SKILL.md

```markdown
---
name: Research Assistant
description: Deep research with citations
tags: [research, ai, analysis]
---

You are a research assistant. When given a topic:
1. Search authoritative sources
2. Synthesize findings
3. Provide citations
```

### apex.yaml

```yaml
pricing:
  model: negotiated
  target: 25.00
  minimum: 10.00
  max_rounds: 5
  strategy: balanced
  currency: USDC

handler:
  file: handler.py
  function: run
```

### handler.py

```python
async def run(input: dict) -> dict:
    topic = input.get("topic", "")
    # Your logic here
    return {"result": f"Research on {topic}..."}
```

---

## Protocol Flow

```
Buyer                                    Seller
  │                                        │
  │  1. apex/discover                      │
  │───────────────────────────────────────>│
  │                                        │
  │         capabilities, pricing          │
  │<───────────────────────────────────────│
  │                                        │
  │  2. apex/propose ($15)                 │
  │───────────────────────────────────────>│
  │                                        │
  │         counter ($25)                  │
  │<───────────────────────────────────────│
  │                                        │
  │  3. apex/counter ($20)                 │
  │───────────────────────────────────────>│
  │                                        │
  │         counter ($22)                  │
  │<───────────────────────────────────────│
  │                                        │
  │  4. apex/accept ($22)                  │
  │───────────────────────────────────────>│
  │                                        │
  │  ╔═══════════════════════════════════╗ │
  │  ║  USDC Transfer: $22.00            ║ │
  │  ║  Network: Base                    ║ │
  │  ║  TX: 0x7a3b...                    ║ │
  │  ╚═══════════════════════════════════╝ │
  │                                        │
  │         output                         │
  │<───────────────────────────────────────│
```

---

## API Reference

### Seller API

```python
import apex

# Load skill folder
agent = apex.load("./my-skill")
agent = apex.load("./my-skill", price=apex.Fixed(10.00))

# Wrap REST API
agent = apex.from_api(
    name="My API",
    endpoint="https://api.example.com/run",
    method="POST",
    headers={"Authorization": "Bearer {{env.API_KEY}}"},
    body={"query": "{{input.query}}"},
    output="data.result",
    price=apex.Fixed(1.00),
)

# Wrap curl command
agent = apex.from_curl(
    name="My Service",
    curl='curl -X POST https://api.example.com -d "{{input.data}}"',
    price=apex.Negotiated(target=5.00, minimum=2.00),
)

# Custom handler
agent = apex.create_agent(
    name="Custom",
    price=apex.Fixed(5.00),
    handler=my_async_function,
)

# Add pricing to existing skill
apex.add_apex("./skill", price=apex.Fixed(5.00))

# Export as skill folder
agent.export("./output")

# Serve
agent.serve(port=8001)
```

### Buyer API

```python
from apex import create_buyer
from apex.payments import Wallet

buyer = create_buyer(
    budget=50.00,
    strategy="balanced",
    wallet=Wallet.from_env("KEY"),
    auto_pay=True,
)

async with buyer:
    result = await buyer.call(
        url="http://agent.com/apex",
        capability="research",
        input={"topic": "AI"},
        max_rounds=5,
        verbose=True,
    )
```

### Result Fields

```python
result.success         # bool
result.final_price     # float
result.output          # dict
result.rounds          # int
result.history         # list
result.tx_hash         # str (if paid)
result.explorer_url    # str (BaseScan link)
result.error           # str (if failed)
```

### Wallet API

```python
from apex.payments import Wallet

wallet = Wallet.generate()
wallet = Wallet.from_private_key("0x...")
wallet = Wallet.from_env("KEY", network="base")

wallet.address        # str
wallet.private_key    # str
wallet.network        # str

await wallet.balance("USDC")
await wallet.eth_balance()
await wallet.transfer(to="0x...", amount=10.00)
```

---

## Examples

### GPT Wrapper

```python
import apex

agent = apex.from_api(
    name="GPT-4 Assistant",
    endpoint="https://api.openai.com/v1/chat/completions",
    method="POST",
    headers={
        "Authorization": "Bearer {{env.OPENAI_API_KEY}}",
        "Content-Type": "application/json",
    },
    body={
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "{{input.prompt}}"}],
    },
    output="choices.0.message.content",
    price=apex.Fixed(0.05),
)

agent.serve(port=8001)
```

### Multi-Agent Pipeline

```python
from apex import create_buyer
from apex.payments import Wallet
import asyncio

async def main():
    buyer = create_buyer(
        budget=50.00,
        wallet=Wallet.from_env("KEY"),
        auto_pay=True,
    )
    
    async with buyer:
        # Step 1: Research
        research = await buyer.call(
            url="http://research.agent/apex",
            capability="research",
            input={"topic": "AI agents"},
        )
        
        # Step 2: Summarize
        summary = await buyer.call(
            url="http://writer.agent/apex",
            capability="summarize",
            input={"text": research.output["result"]},
        )
        
        total = research.final_price + summary.final_price
        print(f"Total: ${total:.2f}")
        print(summary.output)

asyncio.run(main())
```

---

## Environment Variables

```bash
# Wallet keys
BUYER_PRIVATE_KEY=0x...
SELLER_PRIVATE_KEY=0x...

# Network
APEX_NETWORK=base-sepolia   # testnet (default)
APEX_NETWORK=base           # mainnet

# LLM (for negotiation)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-...
```

---

## Demo Scripts

```bash
# Generate wallets and setup
python demo_testnet.py --setup

# Run negotiation demo
python demo_testnet.py

# Full payment demo
python demo_paid.py

# Multi-agent demo
python demo_multi_agent.py
```

---

## Protocol Specification

See [SPEC.md](./SPEC.md) for the complete protocol specification:

- Message formats (JSON-RPC 2.0)
- Negotiation state machine
- Error codes
- Security considerations
- Payment verification

---

## Architecture

```
apex/
├── __init__.py        # Exports
├── pricing.py         # Fixed, Negotiated
├── agent.py           # Agent class
├── buyer.py           # Buyer with auto-negotiation
├── negotiation.py     # 4 strategies
├── loader.py          # Load skill folders
├── api.py             # from_api()
├── curl.py            # from_curl()
├── export.py          # Export to skill folder
├── client.py          # Low-level client
└── payments/
    ├── config.py      # Networks
    ├── wallet.py      # Key management
    └── settlement.py  # Payment execution
```

---

## Contributing

We welcome contributions:

- New payment rails (Stripe, etc.)
- Negotiation strategies
- TypeScript SDK
- Registry service
- Escrow contracts

---

## License

MIT

---

<p align="center">
  <strong>Built for the agent economy</strong>
</p>