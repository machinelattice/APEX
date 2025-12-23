"""APEX Payments Configuration.

Chain and token addresses for supported networks.

Testnet Setup:
    1. Get test ETH: https://www.alchemy.com/faucets/base-sepolia
    2. Get test USDC: https://faucet.circle.com (select Base Sepolia)
    3. Set APEX_NETWORK=base-sepolia in .env
"""

from dataclasses import dataclass
import os


@dataclass
class NetworkConfig:
    """Configuration for a blockchain network."""
    chain_id: int
    name: str
    rpc_url: str
    explorer_url: str
    usdc_address: str
    is_testnet: bool = False


# Supported networks
# Supported networks
NETWORKS = {
    "base": NetworkConfig(
        chain_id=8453,
        name="Base",
        rpc_url="https://mainnet.base.org",
        explorer_url="https://basescan.org",
        usdc_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        is_testnet=False,
    ),
    "base-sepolia": NetworkConfig(
        chain_id=84532,
        name="Base Sepolia (Testnet)",
        rpc_url="https://sepolia.base.org",
        explorer_url="https://sepolia.basescan.org",
        usdc_address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        is_testnet=True,
    ),
    "sepolia": NetworkConfig(
        chain_id=11155111,
        name="Ethereum Sepolia (Testnet)",
        rpc_url="https://eth-sepolia.g.alchemy.com/v2/uqa1KLfFGZBRNF36FydhW",
        explorer_url="https://sepolia.etherscan.io",
        usdc_address="0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238",
        is_testnet=True,
    ),
}

# Default to testnet for safety - override with APEX_NETWORK env var
DEFAULT_NETWORK = os.environ.get("APEX_NETWORK", "base-sepolia")


# Faucet URLs
FAUCETS = {
    "base-sepolia": {
        "eth": "https://www.alchemy.com/faucets/base-sepolia",
        "usdc": "https://faucet.circle.com",
    },
    "sepolia": {
        "eth": "https://faucets.chain.link/sepolia",
        "usdc": "https://faucet.circle.com",
    },
}

# USDC has 6 decimals
USDC_DECIMALS = 6

# ERC20 ABI (minimal - just what we need)
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]


def get_network(network: str = DEFAULT_NETWORK) -> NetworkConfig:
    """Get network configuration."""
    if network not in NETWORKS:
        raise ValueError(f"Unknown network: {network}. Supported: {list(NETWORKS.keys())}")
    return NETWORKS[network]


def get_explorer_url(tx_hash: str, network: str = DEFAULT_NETWORK) -> str:
    """Get block explorer URL for a transaction."""
    config = get_network(network)
    return f"{config.explorer_url}/tx/{tx_hash}"