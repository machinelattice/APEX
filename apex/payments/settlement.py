"""APEX Payment Settlement.

Handles the payment flow after negotiation completes:
    1. Negotiation completes → terms agreed
    2. Buyer sends payment
    3. Seller verifies payment
    4. Output released

Example:
    # Buyer side
    payment = Payment(
        job_id="abc123",
        amount=12.50,
        currency="USDC",
        network="base",
        buyer_wallet=buyer_wallet,
        seller_address=seller_address,
    )
    
    result = await payment.execute()
    if result.success:
        # Send proof to seller
        proof = payment.get_proof()
        
    # Seller side
    verified = await Payment.verify(proof)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from decimal import Decimal

from .wallet import Wallet, TransferResult
from .config import get_network, get_explorer_url, USDC_DECIMALS, ERC20_ABI, DEFAULT_NETWORK

from web3 import Web3


@dataclass
class PaymentProof:
    """Proof of payment for seller verification."""
    job_id: str
    tx_hash: str
    network: str
    amount: float
    currency: str
    from_address: str
    to_address: str
    timestamp: str
    
    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "tx_hash": self.tx_hash,
            "network": self.network,
            "amount": self.amount,
            "currency": self.currency,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "PaymentProof":
        return cls(**data)


@dataclass
class PaymentResult:
    """Result of payment execution."""
    success: bool
    proof: Optional[PaymentProof] = None
    tx_hash: Optional[str] = None
    explorer_url: Optional[str] = None
    error: Optional[str] = None
    gas_used: Optional[int] = None


class Payment:
    """Single payment from buyer to seller.
    
    Example:
        payment = Payment(
            job_id="job-123",
            amount=12.50,
            buyer_wallet=wallet,
            seller_address="0x...",
        )
        
        result = await payment.execute()
        if result.success:
            print(f"Paid: {result.explorer_url}")
    """
    
    def __init__(
        self,
        job_id: str,
        amount: float,
        buyer_wallet: Wallet,
        seller_address: str,
        currency: str = "USDC",
        network: str = DEFAULT_NETWORK,
    ):
        self.job_id = job_id
        self.amount = amount
        self.buyer_wallet = buyer_wallet
        self.seller_address = seller_address
        self.currency = currency
        self.network = network
        
        self._result: Optional[PaymentResult] = None
    
    async def execute(self) -> PaymentResult:
        """Execute the payment.
        
        Returns:
            PaymentResult with success status and proof
        """
        if self.currency != "USDC":
            return PaymentResult(
                success=False,
                error=f"Unsupported currency: {self.currency}",
            )
        
        # Check balance first
        balance = await self.buyer_wallet.balance("USDC")
        if balance < self.amount:
            return PaymentResult(
                success=False,
                error=f"Insufficient balance: have ${balance:.2f}, need ${self.amount:.2f}",
            )
        
        # Execute transfer
        transfer_result = await self.buyer_wallet.transfer(
            to=self.seller_address,
            amount=self.amount,
            token="USDC",
        )
        
        if not transfer_result.success:
            return PaymentResult(
                success=False,
                error=transfer_result.error,
            )
        
        # Build proof
        proof = PaymentProof(
            job_id=self.job_id,
            tx_hash=transfer_result.tx_hash,
            network=self.network,
            amount=self.amount,
            currency=self.currency,
            from_address=self.buyer_wallet.address,
            to_address=self.seller_address,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        self._result = PaymentResult(
            success=True,
            proof=proof,
            tx_hash=transfer_result.tx_hash,
            explorer_url=transfer_result.explorer_url,
            gas_used=transfer_result.gas_used,
        )
        
        return self._result
    
    @staticmethod
    async def verify(
        proof: PaymentProof,
        expected_seller: Optional[str] = None,
        tolerance: float = 0.01,
    ) -> bool:
        """Verify a payment proof on-chain.
        
        Args:
            proof: Payment proof from buyer
            expected_seller: Expected recipient address (optional extra check)
            tolerance: Amount tolerance for float comparison
            
        Returns:
            True if payment verified on-chain
        """
        try:
            config = get_network(proof.network)
            w3 = Web3(Web3.HTTPProvider(config.rpc_url))
            
            # Get transaction receipt
            receipt = w3.eth.get_transaction_receipt(proof.tx_hash)
            if receipt is None:
                return False
            
            # Check transaction succeeded
            if receipt["status"] != 1:
                return False
            
            # Get transaction details
            tx = w3.eth.get_transaction(proof.tx_hash)
            
            # Verify it's a USDC transfer
            if tx["to"].lower() != config.usdc_address.lower():
                return False
            
            # Decode transfer data
            usdc = w3.eth.contract(
                address=Web3.to_checksum_address(config.usdc_address),
                abi=ERC20_ABI,
            )
            
            # Parse the transfer call
            try:
                func, params = usdc.decode_function_input(tx["input"])
                if func.fn_name != "transfer":
                    return False
                
                to_address = params["_to"]
                raw_amount = params["_value"]
                amount = raw_amount / (10 ** USDC_DECIMALS)
                
            except Exception:
                return False
            
            # Verify recipient
            if expected_seller and to_address.lower() != expected_seller.lower():
                return False
            
            if to_address.lower() != proof.to_address.lower():
                return False
            
            # Verify amount (with tolerance for float comparison)
            if abs(amount - proof.amount) > tolerance:
                return False
            
            # Verify sender
            if tx["from"].lower() != proof.from_address.lower():
                return False
            
            return True
        
        except Exception as e:
            print(f"Payment verification error: {e}")
            return False


class PaymentManager:
    """Manages payments for an agent.
    
    Tracks payments made/received and provides verification.
    
    Example:
        manager = PaymentManager(wallet)
        
        # As buyer
        result = await manager.pay(
            job_id="job-123",
            amount=12.50,
            seller_address="0x...",
        )
        
        # As seller
        verified = await manager.verify_payment(proof)
    """
    
    def __init__(self, wallet: Wallet):
        self.wallet = wallet
        self._payments_made: dict[str, PaymentResult] = {}
        self._payments_received: dict[str, PaymentProof] = {}
    
    async def pay(
        self,
        job_id: str,
        amount: float,
        seller_address: str,
        currency: str = "USDC",
    ) -> PaymentResult:
        """Make a payment for a job.
        
        Args:
            job_id: Unique job identifier
            amount: Amount to pay
            seller_address: Recipient address
            currency: Currency (default USDC)
            
        Returns:
            PaymentResult
        """
        payment = Payment(
            job_id=job_id,
            amount=amount,
            buyer_wallet=self.wallet,
            seller_address=seller_address,
            currency=currency,
            network=self.wallet.network,
        )
        
        result = await payment.execute()
        
        if result.success:
            self._payments_made[job_id] = result
        
        return result
    
    async def verify_payment(
        self,
        proof: PaymentProof,
    ) -> bool:
        """Verify a payment was received.
        
        Args:
            proof: Payment proof from buyer
            
        Returns:
            True if verified
        """
        verified = await Payment.verify(
            proof=proof,
            expected_seller=self.wallet.address,
        )
        
        if verified:
            self._payments_received[proof.job_id] = proof
        
        return verified
    
    async def balance(self) -> float:
        """Get current USDC balance."""
        return await self.wallet.balance("USDC")
    
    def get_payment_made(self, job_id: str) -> Optional[PaymentResult]:
        """Get a payment made for a job."""
        return self._payments_made.get(job_id)
    
    def get_payment_received(self, job_id: str) -> Optional[PaymentProof]:
        """Get a payment received for a job."""
        return self._payments_received.get(job_id)
    
    @property
    def total_paid(self) -> float:
        """Total amount paid out."""
        return sum(
            p.proof.amount for p in self._payments_made.values()
            if p.success and p.proof
        )
    
    @property
    def total_received(self) -> float:
        """Total amount received."""
        return sum(p.amount for p in self._payments_received.values())
