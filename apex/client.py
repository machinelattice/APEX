"""APEX Client - For buyers to discover and call agents.

Example:
    from apex import Client
    
    async with Client("https://registry.agenty.ai") as client:
        agents = await client.discover(capability="research")
        result = await client.call(agents[0]["url"], "research", {"topic": "AI"})
"""

import uuid
from dataclasses import dataclass

import httpx


@dataclass
class Client:
    """APEX client for discovering and calling agents."""
    
    registry_url: str
    wallet: str | None = None
    _http: httpx.AsyncClient | None = None
    
    async def __aenter__(self):
        self._http = httpx.AsyncClient(timeout=60.0)
        return self
    
    async def __aexit__(self, *args):
        if self._http:
            await self._http.aclose()
    
    async def discover(
        self,
        capability: str | None = None,
        query: str | None = None,
    ) -> list[dict]:
        """Discover agents from registry.
        
        Args:
            capability: Filter by exact capability ID
            query: Search by text (name, description, tags)
        
        Returns:
            List of agent info dicts
        """
        params = {}
        if capability:
            params["capability"] = capability
        if query:
            params["q"] = query
        
        response = await self._http.get(
            f"{self.registry_url}/api/discover",
            params=params,
        )
        response.raise_for_status()
        return response.json().get("agents", [])
    
    async def call(
        self,
        url: str,
        capability: str,
        input: dict,
        offer: float = 1.0,
        currency: str = "USDC",
    ) -> dict:
        """Call an agent directly.
        
        Args:
            url: Agent's APEX endpoint URL
            capability: Capability to invoke
            input: Input data for the capability
            offer: Amount to offer
            currency: Currency for payment
        
        Returns:
            Agent response
        """
        response = await self._http.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "apex/propose",
                "params": {
                    "capability": capability,
                    "input": input,
                    "job_id": str(uuid.uuid4()),
                    "offer": {
                        "amount": offer,
                        "currency": currency,
                        "network": "base",
                    },
                    "buyer_address": self.wallet or "0xBUYER",
                },
            },
        )
        response.raise_for_status()
        result = response.json()
        
        if "error" in result:
            raise Exception(result["error"].get("message", "Unknown error"))
        
        return result.get("result", {})
    
    async def propose(
        self,
        url: str,
        capability: str,
        input: dict,
        offer: float,
        currency: str = "USDC",
    ) -> dict:
        """Send a proposal to an agent.
        
        Lower-level method that returns the raw response,
        allowing you to handle negotiation.
        """
        job_id = str(uuid.uuid4())
        
        response = await self._http.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "apex/propose",
                "params": {
                    "capability": capability,
                    "input": input,
                    "job_id": job_id,
                    "offer": {
                        "amount": offer,
                        "currency": currency,
                        "network": "base",
                    },
                    "buyer_address": self.wallet or "0xBUYER",
                },
            },
        )
        response.raise_for_status()
        result = response.json()
        
        if "error" in result:
            raise Exception(result["error"].get("message", "Unknown error"))
        
        return {**result.get("result", {}), "job_id": job_id}
    
    async def counter(
        self,
        url: str,
        job_id: str,
        offer: float,
        round: int,
        input: dict | None = None,
        currency: str = "USDC",
    ) -> dict:
        """Counter an agent's offer."""
        response = await self._http.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "apex/counter",
                "params": {
                    "job_id": job_id,
                    "offer": {
                        "amount": offer,
                        "currency": currency,
                        "network": "base",
                    },
                    "round": round,
                    "input": input or {},
                },
            },
        )
        response.raise_for_status()
        result = response.json()
        
        if "error" in result:
            raise Exception(result["error"].get("message", "Unknown error"))
        
        return result.get("result", {})
    
    async def accept(
        self,
        url: str,
        job_id: str,
        terms: dict,
        input: dict | None = None,
    ) -> dict:
        """Accept an agent's counter-offer."""
        response = await self._http.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "apex/accept",
                "params": {
                    "job_id": job_id,
                    "terms": terms,
                    "input": input or {},
                },
            },
        )
        response.raise_for_status()
        result = response.json()
        
        if "error" in result:
            raise Exception(result["error"].get("message", "Unknown error"))
        
        return result.get("result", {})
    
    async def reject(self, url: str, job_id: str, reason: str | None = None) -> dict:
        """Reject/walk away from negotiation."""
        response = await self._http.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "apex/reject",
                "params": {
                    "job_id": job_id,
                    "reason": reason,
                },
            },
        )
        response.raise_for_status()
        return response.json().get("result", {})
