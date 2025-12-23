"""APEX Protocol SDK - Agent Payments & Exchange.

Three ways to create APEX agents:

1. Load from skill folder:
    agent = apex.load("./my-skill", price=apex.Fixed(5.00))

2. Wrap an API:
    agent = apex.from_api(
        name="Weather",
        endpoint="https://api.weather.com/current",
        body={"city": "{{input.location}}"},
        price=apex.Fixed(1.00),
    )

3. Wrap a curl command:
    agent = apex.from_curl(
        name="Slack",
        curl='curl -X POST https://slack.com/api/... -d "{{input.message}}"',
        price=apex.Fixed(0.50),
    )

All agents support:
    agent.serve(port=8001)          # Start server
    agent.export("./output")        # Export as skill folder
    await agent.register(url)       # Register with registry

Payments:
    from apex.payments import Wallet
    
    wallet = Wallet.from_env("PRIVATE_KEY")
    balance = await wallet.balance()
    result = await wallet.transfer(to="0x...", amount=12.50)
"""

# Pricing models
from .pricing import Fixed, Negotiated, Pricing

# Agent and creation
from .agent import Agent, create_agent

# Loaders - the three creation paths
from .loader import load
from .api import from_api
from .curl import from_curl

# Export
from .export import export_agent, add_apex

# Buyer SDK
from .buyer import Buyer, create_buyer, NegotiationResult

# Low-level client
from .client import Client

# Negotiation internals
from .negotiation import NegotiationEngine, NegotiationState

# Wrapper (legacy, prefer from_api/from_curl)
from .wrapper import wrap_endpoint, wrap_curl, WrappedAgent

__all__ = [
    # Pricing
    "Fixed",
    "Negotiated",
    "Pricing",
    
    # Agent creation
    "Agent",
    "create_agent",
    
    # Three paths
    "load",       # Load skill folder
    "from_api",   # Wrap API endpoint
    "from_curl",  # Wrap curl command
    
    # Export
    "export_agent",
    "add_apex",
    
    # Buyer
    "Buyer",
    "create_buyer",
    "NegotiationResult",
    
    # Client
    "Client",
    
    # Negotiation
    "NegotiationEngine",
    "NegotiationState",
    
    # Legacy wrappers
    "wrap_endpoint",
    "wrap_curl",
    "WrappedAgent",
]

__version__ = "0.3.0"
