"""APEX Payments - USDC on Base.

Handles payment settlement for APEX protocol transactions.

Example:
    from apex.payments import Wallet, Payment
    
    # Create/load wallet
    wallet = Wallet.generate()
    wallet = Wallet.from_private_key("0x...")
    wallet = Wallet.from_env("AGENT_PRIVATE_KEY")
    
    # Check balance
    balance = await wallet.balance()
    print(f"${balance:.2f} USDC")
    
    # Make a payment
    result = await wallet.transfer(to="0x...", amount=12.50)
    print(f"tx: {result.explorer_url}")
    
    # Or use Payment for full flow
    payment = Payment(
        job_id="job-123",
        amount=12.50,
        buyer_wallet=wallet,
        seller_address="0x...",
    )
    result = await payment.execute()
    
    # Seller verifies
    verified = await Payment.verify(result.proof)
"""

from .wallet import Wallet, TransferResult
from .settlement import Payment, PaymentProof, PaymentResult, PaymentManager
from .config import (
    get_network,
    get_explorer_url,
    NetworkConfig,
    NETWORKS,
    DEFAULT_NETWORK,
    USDC_DECIMALS,
    FAUCETS,
)

__all__ = [
    # Core
    "Wallet",
    "Payment",
    "PaymentManager",
    
    # Results
    "TransferResult",
    "PaymentResult", 
    "PaymentProof",
    
    # Config
    "get_network",
    "get_explorer_url",
    "NetworkConfig",
    "NETWORKS",
    "DEFAULT_NETWORK",
    "USDC_DECIMALS",
    "FAUCETS",
]
