"""APEX Wallet - Key management for agent payments.

Example:
    # Generate new wallet
    wallet = Wallet.generate()
    print(wallet.address)
    
    # Load from private key
    wallet = Wallet.from_private_key("0x...")
    
    # Load from environment
    wallet = Wallet.from_env("AGENT_PRIVATE_KEY")
    
    # Check balance
    balance = await wallet.balance()
    print(f"${balance} USDC")
    
    # Transfer
    tx_hash = await wallet.transfer(to="0x...", amount=12.50)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from .config import (
    get_network,
    get_explorer_url,
    DEFAULT_NETWORK,
    USDC_DECIMALS,
    ERC20_ABI,
)


@dataclass
class TransferResult:
    """Result of a transfer operation."""
    success: bool
    tx_hash: Optional[str] = None
    explorer_url: Optional[str] = None
    error: Optional[str] = None
    gas_used: Optional[int] = None


class Wallet:
    """Agent wallet for signing transactions and managing funds."""
    
    def __init__(self, account: LocalAccount, network: str = DEFAULT_NETWORK):
        """Initialize wallet with an eth-account LocalAccount.
        
        Use class methods to create:
            Wallet.generate()
            Wallet.from_private_key(key)
            Wallet.from_env(var_name)
        """
        self._account = account
        self._network = network
        self._web3: Optional[Web3] = None
        self._last_nonce: Optional[int] = None  # Track nonce locally
    
    @classmethod
    def generate(cls, network: str = DEFAULT_NETWORK) -> "Wallet":
        """Generate a new random wallet.
        
        Returns:
            New Wallet instance
            
        Example:
            wallet = Wallet.generate()
            print(f"Address: {wallet.address}")
            print(f"Private key: {wallet.private_key}")  # Save this!
        """
        account = Account.create()
        return cls(account, network)
    
    @classmethod
    def from_private_key(cls, private_key: str, network: str = DEFAULT_NETWORK) -> "Wallet":
        """Load wallet from a private key.
        
        Args:
            private_key: Hex-encoded private key (with or without 0x prefix)
            network: Network to use (default: base)
            
        Returns:
            Wallet instance
            
        Example:
            wallet = Wallet.from_private_key("0x...")
        """
        # Normalize key format
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        
        account = Account.from_key(private_key)
        return cls(account, network)
    
    @classmethod
    def from_env(cls, var_name: str = "APEX_PRIVATE_KEY", network: str = DEFAULT_NETWORK) -> "Wallet":
        """Load wallet from an environment variable.
        
        Args:
            var_name: Environment variable name containing private key
            network: Network to use (default: base)
            
        Returns:
            Wallet instance
            
        Raises:
            ValueError: If environment variable not set
            
        Example:
            # In .env: APEX_PRIVATE_KEY=0x...
            wallet = Wallet.from_env("APEX_PRIVATE_KEY")
        """
        # Try to load from .env file first
        _load_env()
        
        private_key = os.environ.get(var_name)
        if not private_key:
            raise ValueError(f"Environment variable {var_name} not set")
        
        return cls.from_private_key(private_key, network)
    
    @property
    def address(self) -> str:
        """Get wallet address (checksummed)."""
        return self._account.address
    
    @property
    def private_key(self) -> str:
        """Get private key (hex-encoded with 0x prefix).
        
        WARNING: Handle with care! Never log or expose.
        """
        return self._account.key.hex()
    
    @property
    def network(self) -> str:
        """Get current network."""
        return self._network
    
    def _get_web3(self) -> Web3:
        """Get or create Web3 instance."""
        if self._web3 is None:
            config = get_network(self._network)
            self._web3 = Web3(Web3.HTTPProvider(config.rpc_url))
            # Add POA middleware for Base
            self._web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return self._web3
    
    async def balance(self, token: str = "USDC") -> float:
        """Get token balance.
        
        Args:
            token: Token symbol (currently only USDC supported)
            
        Returns:
            Balance as float (human-readable, e.g., 12.50)
        """
        if token != "USDC":
            raise ValueError(f"Unsupported token: {token}. Only USDC supported.")
        
        w3 = self._get_web3()
        config = get_network(self._network)
        
        # Get USDC contract
        usdc = w3.eth.contract(
            address=Web3.to_checksum_address(config.usdc_address),
            abi=ERC20_ABI,
        )
        
        # Get balance (returns integer with 6 decimals)
        raw_balance = usdc.functions.balanceOf(self.address).call()
        
        # Convert to human-readable
        return raw_balance / (10 ** USDC_DECIMALS)
    
    async def eth_balance(self) -> float:
        """Get ETH balance (for gas)."""
        w3 = self._get_web3()
        raw_balance = w3.eth.get_balance(self.address)
        return w3.from_wei(raw_balance, "ether")
    
    async def transfer(
        self,
        to: str,
        amount: float,
        token: str = "USDC",
        gas_limit: Optional[int] = None,
    ) -> TransferResult:
        """Transfer tokens to another address.
        
        Args:
            to: Recipient address
            amount: Amount to send (human-readable, e.g., 12.50)
            token: Token symbol (currently only USDC)
            gas_limit: Optional gas limit override
            
        Returns:
            TransferResult with tx_hash and explorer URL
            
        Example:
            result = await wallet.transfer(to="0x...", amount=12.50)
            if result.success:
                print(f"Sent! {result.explorer_url}")
        """
        if token != "USDC":
            raise ValueError(f"Unsupported token: {token}. Only USDC supported.")
        
        try:
            # Force fresh Web3 connection to avoid stale nonce
            self._web3 = None
            w3 = self._get_web3()
            config = get_network(self._network)
            
            # Get USDC contract
            usdc = w3.eth.contract(
                address=Web3.to_checksum_address(config.usdc_address),
                abi=ERC20_ABI,
            )
            
            # Convert amount to raw (6 decimals)
            raw_amount = int(amount * (10 ** USDC_DECIMALS))
            
            # Check balance
            current_balance = usdc.functions.balanceOf(self.address).call()
            if current_balance < raw_amount:
                return TransferResult(
                    success=False,
                    error=f"Insufficient balance: have {current_balance / 10**USDC_DECIMALS:.2f}, need {amount:.2f}",
                )
            
            # Build transaction
            to_address = Web3.to_checksum_address(to)
            
            # Get nonce - use local tracking to avoid collisions
            chain_nonce = w3.eth.get_transaction_count(self.address, "pending")
            if self._last_nonce is not None and self._last_nonce >= chain_nonce:
                nonce = self._last_nonce + 1
            else:
                nonce = chain_nonce
            
            # Get gas price and bump by 20% to avoid replacement issues
            gas_price = int(w3.eth.gas_price * 1.2)
            
            # Build transfer call
            tx = usdc.functions.transfer(to_address, raw_amount).build_transaction({
                "chainId": config.chain_id,
                "from": self.address,
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": gas_limit or 100000,  # USDC transfers typically use ~50k
            })
            
            # Sign transaction
            signed_tx = w3.eth.account.sign_transaction(tx, self._account.key)
            
            # Send transaction
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = "0x" + tx_hash.hex()
            
            # Update local nonce tracking
            self._last_nonce = nonce
            
            # Transaction sent - return immediately with pending status
            # Don't wait for confirmation to avoid hanging
            explorer_url = get_explorer_url(tx_hash_hex, self._network)
            
            try:
                # Quick wait - 30 seconds max
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
                
                if receipt["status"] == 1:
                    return TransferResult(
                        success=True,
                        tx_hash=tx_hash_hex,
                        explorer_url=explorer_url,
                        gas_used=receipt["gasUsed"],
                    )
                else:
                    return TransferResult(
                        success=False,
                        tx_hash=tx_hash_hex,
                        explorer_url=explorer_url,
                        error="Transaction reverted",
                    )
            except Exception:
                # Timeout waiting - tx is pending, return success anyway
                return TransferResult(
                    success=True,
                    tx_hash=tx_hash_hex,
                    explorer_url=explorer_url,
                    error="Pending confirmation",
                )
        
        except Exception as e:
            return TransferResult(
                success=False,
                error=str(e),
            )
    
    def __repr__(self) -> str:
        return f"Wallet({self.address[:10]}...{self.address[-6:]}, network={self._network})"


def _load_env():
    """Load .env file if present."""
    from pathlib import Path
    
    # Already loaded?
    if os.environ.get("_APEX_PAYMENTS_ENV_LOADED"):
        return
    
    # Search paths
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
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
                        if key not in os.environ:
                            os.environ[key] = value
            break
    
    os.environ["_APEX_PAYMENTS_ENV_LOADED"] = "1"