"""APEX Wrappers - Add APEX protocol to existing APIs.

Example:
    from apex import wrap_endpoint, Fixed
    
    agent = wrap_endpoint(
        name="My API",
        price=Fixed(5.00),
        endpoint="https://api.example.com/chat",
        method="POST",
        body={"message": "{{input.query}}"},
        output_mapping={"result": "{{response.answer}}"},
    )
    
    agent.serve(port=8001)
"""

import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from .pricing import Pricing, Fixed, Negotiated
from .negotiation import NegotiationEngine, NegotiationState


def _substitute(template: Any, context: dict) -> Any:
    """Substitute {{variable}} placeholders in template."""
    if isinstance(template, str):
        # Find all {{...}} patterns
        def replace(match):
            path = match.group(1).strip()
            
            # Handle env variables
            if path.startswith("env."):
                env_var = path[4:]
                return os.environ.get(env_var, "")
            
            # Navigate path
            parts = path.split(".")
            value = context
            for part in parts:
                # Handle array index
                if "[" in part:
                    key = part[:part.index("[")]
                    idx = int(part[part.index("[") + 1:part.index("]")])
                    value = value.get(key, [])[idx]
                else:
                    value = value.get(part, "")
            return str(value) if value else ""
        
        return re.sub(r"\{\{(.+?)\}\}", replace, template)
    
    elif isinstance(template, dict):
        return {k: _substitute(v, context) for k, v in template.items()}
    
    elif isinstance(template, list):
        return [_substitute(item, context) for item in template]
    
    return template


@dataclass
class WrappedAgent:
    """Agent that wraps an existing API endpoint."""
    
    name: str
    price: Pricing
    endpoint: str
    method: str = "POST"
    headers: dict = field(default_factory=dict)
    body: dict | None = None
    query_params: dict = field(default_factory=dict)
    output_mapping: dict = field(default_factory=dict)
    output_field: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    agent_id: str | None = None
    wallet: str | None = None
    
    # Internal
    _negotiation_engines: dict = None
    
    def __post_init__(self):
        if self.agent_id is None:
            slug = self.name.lower().replace(" ", "-")
            self.agent_id = f"{slug}-{uuid.uuid4().hex[:8]}"
        
        if self.wallet is None:
            self.wallet = "0x" + uuid.uuid4().hex[:40]
        
        if not self.capabilities:
            self.capabilities = [self.name.lower().replace(" ", "-")]
        
        self._negotiation_engines = {}
    
    def _get_negotiation_engine(self, job_id: str) -> NegotiationEngine:
        """Get or create negotiation engine for a job."""
        if job_id not in self._negotiation_engines:
            self._negotiation_engines[job_id] = NegotiationEngine(self.price)
        return self._negotiation_engines[job_id]
    
    async def run(self, input: dict) -> dict:
        """Execute the wrapped endpoint."""
        context = {"input": input, "env": dict(os.environ)}
        
        # Build request
        url = self.endpoint
        headers = _substitute(self.headers, context)
        body = _substitute(self.body, context) if self.body else None
        params = _substitute(self.query_params, context)
        
        # Make request
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=self.method,
                url=url,
                headers=headers,
                json=body,
                params=params,
                timeout=60.0,
            )
            
            response.raise_for_status()
            response_data = response.json()
        
        # Map output
        context["response"] = response_data
        
        if self.output_field:
            # Simple field extraction
            return {"result": _substitute(f"{{{{{self.output_field}}}}}", context)}
        elif self.output_mapping:
            return _substitute(self.output_mapping, context)
        else:
            return {"result": response_data}
    
    async def handle(self, request: dict) -> dict:
        """Handle an APEX protocol request."""
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id", "1")
        
        try:
            if method == "apex/discover":
                return self._make_response(request_id, self._get_discover_result())
            
            elif method == "apex/propose":
                return await self._handle_propose(request_id, params)
            
            elif method == "apex/counter":
                return await self._handle_counter(request_id, params)
            
            elif method == "apex/accept":
                return await self._handle_accept(request_id, params)
            
            else:
                return self._make_error(request_id, -32601, f"Method not found: {method}")
        
        except Exception as e:
            return self._make_error(request_id, -32603, str(e))
    
    def _get_discover_result(self) -> dict:
        """Build discovery result."""
        return {
            "agent": {
                "id": self.agent_id,
                "name": self.name,
                "description": self.description,
            },
            "capabilities": [
                {"id": cap, "name": cap, "pricing": self.price.to_dict()}
                for cap in self.capabilities
            ],
            "payment": {
                "networks": ["base"],
                "currencies": ["USDC"],
                "address": self.wallet,
            },
        }
    
    async def _handle_propose(self, request_id: str, params: dict) -> dict:
        """Handle apex/propose request."""
        offer_amount = params.get("offer", {}).get("amount", 0)
        input_data = params.get("input", {})
        job_id = params.get("job_id", str(uuid.uuid4()))
        
        # Handle negotiated pricing
        if isinstance(self.price, Negotiated):
            engine = self._get_negotiation_engine(job_id)
            state, counter = engine.receive_offer(offer_amount)
            
            if state == NegotiationState.ACCEPTED:
                output = await self.run(input_data)
                self._negotiation_engines.pop(job_id, None)
                return self._make_response(request_id, {
                    "status": "completed",
                    "job_id": job_id,
                    "terms": {"amount": float(offer_amount), "currency": self.price.currency},
                    "output": output,
                })
            
            elif state == NegotiationState.REJECTED:
                self._negotiation_engines.pop(job_id, None)
                return self._make_error(request_id, -32018, "Offer rejected")
            
            elif state == NegotiationState.EXPIRED:
                self._negotiation_engines.pop(job_id, None)
                return self._make_error(request_id, -32019, "Negotiation expired")
            
            elif counter:  # IN_PROGRESS with counter
                return self._make_response(request_id, {
                    "status": "counter",
                    "job_id": job_id,
                    "offer": {"amount": float(counter.price), "currency": self.price.currency},
                    "round": counter.round,
                    "max_rounds": self.price.max_rounds,
                    "reason": counter.reason,
                })
        
        # Handle fixed pricing
        elif isinstance(self.price, Fixed):
            if offer_amount >= self.price.amount:
                output = await self.run(input_data)
                return self._make_response(request_id, {
                    "status": "completed",
                    "job_id": job_id,
                    "terms": {"amount": self.price.amount, "currency": self.price.currency},
                    "output": output,
                })
            else:
                return self._make_error(
                    request_id, -32017,
                    f"Price is {self.price.amount} {self.price.currency}"
                )
        
    async def _handle_counter(self, request_id: str, params: dict) -> dict:
        """Handle buyer counter-offer."""
        if not isinstance(self.price, Negotiated):
            return self._make_error(request_id, -32007, "Pricing is not negotiable")
        
        offer_amount = params.get("offer", {}).get("amount", 0)
        job_id = params.get("job_id", "")
        input_data = params.get("input", {})
        
        if not job_id or job_id not in self._negotiation_engines:
            return self._make_error(request_id, -32008, "Unknown job_id")
        
        engine = self._negotiation_engines[job_id]
        state, counter = engine.receive_offer(offer_amount)
        
        if state == NegotiationState.ACCEPTED:
            output = await self.run(input_data)
            self._negotiation_engines.pop(job_id, None)
            return self._make_response(request_id, {
                "status": "completed",
                "job_id": job_id,
                "terms": {"amount": float(offer_amount), "currency": self.price.currency},
                "output": output,
            })
        
        elif state == NegotiationState.REJECTED:
            self._negotiation_engines.pop(job_id, None)
            return self._make_error(request_id, -32018, "Negotiation ended - no agreement")
        
        elif state == NegotiationState.EXPIRED:
            self._negotiation_engines.pop(job_id, None)
            return self._make_error(request_id, -32019, "Negotiation expired")
        
        elif counter:
            return self._make_response(request_id, {
                "status": "counter",
                "job_id": job_id,
                "offer": {"amount": float(counter.price), "currency": self.price.currency},
                "round": counter.round,
                "max_rounds": self.price.max_rounds,
                "reason": counter.reason,
            })
    
    async def _handle_accept(self, request_id: str, params: dict) -> dict:
        """Handle buyer accepting our counter."""
        job_id = params.get("job_id", "")
        terms = params.get("terms", {})
        input_data = params.get("input", {})
        
        output = await self.run(input_data)
        
        # Clean up engine
        self._negotiation_engines.pop(job_id, None)
        
        return self._make_response(request_id, {
            "status": "completed",
            "job_id": job_id,
            "terms": terms,
            "output": output,
        })
    
    def _make_response(self, request_id: str, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    
    def _make_error(self, request_id: str, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    
    async def register(self, registry_url: str) -> dict:
        """Register with a registry."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{registry_url}/api/register",
                json={
                    "agent_id": self.agent_id,
                    "name": self.name,
                    "description": self.description,
                    "url": f"http://localhost:8001/apex",
                    "capabilities": self.capabilities,
                    "networks": ["base"],
                    "currencies": ["USDC"],
                    "wallet_address": self.wallet,
                    "pricing_info": self.price.to_dict(),
                    "tags": self.tags,
                },
                timeout=10.0,
            )
            
            if response.status_code == 200:
                print(f"âœ… Registered '{self.name}' with {registry_url}")
                return response.json()
            else:
                raise Exception(f"Registration failed: {response.text}")
    
    def serve(self, host: str = "0.0.0.0", port: int = 8001):
        """Start HTTP server."""
        import uvicorn
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        
        agent = self
        
        async def handle_apex(request: Request) -> JSONResponse:
            body = await request.json()
            response = await agent.handle(body)
            return JSONResponse(response)
        
        async def health(request: Request) -> JSONResponse:
            return JSONResponse({"status": "ok", "agent": agent.name})
        
        app = Starlette(routes=[
            Route("/apex", handle_apex, methods=["POST"]),
            Route("/health", health, methods=["GET"]),
        ])
        
        print(f"""
â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
â•‘  ðŸ“Œ {self.name:<54} â•‘
â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£
â•‘  Wrapping: {self.endpoint[:48]:<48} â•‘
â•‘  URL:      http://{host}:{port}/apex{' ' * (40 - len(str(port)))} â•‘
â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
""")
        
        uvicorn.run(app, host=host, port=port)


def wrap_endpoint(
    name: str,
    price: Pricing,
    endpoint: str,
    method: str = "POST",
    headers: dict | None = None,
    body: dict | None = None,
    query_params: dict | None = None,
    output_mapping: dict | None = None,
    output_field: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    capabilities: list[str] | None = None,
    agent_id: str | None = None,
    wallet: str | None = None,
) -> WrappedAgent:
    """Wrap an existing API endpoint as an APEX agent.
    
    Args:
        name: Agent name
        price: Pricing model
        endpoint: API URL to wrap
        method: HTTP method (GET, POST, etc.)
        headers: Request headers (supports {{env.VAR}} substitution)
        body: Request body template (supports {{input.field}} substitution)
        query_params: URL query parameters
        output_mapping: Map response fields to output
        output_field: Simple path to extract from response
        description: Agent description
        tags: Searchable tags
        capabilities: Capability IDs
        agent_id: Unique ID
        wallet: Wallet address
    
    Example:
        agent = wrap_endpoint(
            name="My API",
            price=Fixed(5.00),
            endpoint="https://api.example.com/chat",
            headers={"Authorization": "Bearer {{env.API_KEY}}"},
            body={"message": "{{input.query}}"},
            output_field="response.answer",
        )
    """
    return WrappedAgent(
        name=name,
        price=price,
        endpoint=endpoint,
        method=method,
        headers=headers or {},
        body=body,
        query_params=query_params or {},
        output_mapping=output_mapping or {},
        output_field=output_field,
        description=description,
        tags=tags or [],
        capabilities=capabilities or [],
        agent_id=agent_id,
        wallet=wallet,
    )


def wrap_curl(
    name: str,
    price: Pricing,
    curl: str,
    output_field: str | None = None,
    output_mapping: dict | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    capabilities: list[str] | None = None,
    agent_id: str | None = None,
    wallet: str | None = None,
) -> WrappedAgent:
    """Wrap a curl command as an APEX agent.
    
    Args:
        name: Agent name
        price: Pricing model
        curl: Curl command (supports {{input.field}} substitution)
        output_field: Path to extract from response
        output_mapping: Map response fields to output
        description: Agent description
        tags: Searchable tags
        capabilities: Capability IDs
        agent_id: Unique ID
        wallet: Wallet address
    
    Example:
        agent = wrap_curl(
            name="My API",
            price=Fixed(5.00),
            curl='''
            curl -X POST https://api.example.com/run \\
              -H "Authorization: Bearer $API_KEY" \\
              -d '{"input": "{{input.text}}"}'
            ''',
            output_field="response.result",
        )
    """
    # Parse curl command
    endpoint, method, headers, body = _parse_curl(curl)
    
    return WrappedAgent(
        name=name,
        price=price,
        endpoint=endpoint,
        method=method,
        headers=headers,
        body=body,
        output_mapping=output_mapping or {},
        output_field=output_field,
        description=description,
        tags=tags or [],
        capabilities=capabilities or [],
        agent_id=agent_id,
        wallet=wallet,
    )


def _parse_curl(curl: str) -> tuple[str, str, dict, dict | None]:
    """Parse a curl command into components."""
    import shlex
    
    # Normalize
    curl = curl.replace("\\\n", " ").strip()
    
    # Tokenize
    tokens = shlex.split(curl)
    
    endpoint = ""
    method = "GET"
    headers = {}
    body = None
    
    i = 0
    while i < len(tokens):
        token = tokens[i]
        
        if token == "curl":
            pass
        elif token in ("-X", "--request"):
            i += 1
            method = tokens[i]
        elif token in ("-H", "--header"):
            i += 1
            header = tokens[i]
            if ":" in header:
                key, value = header.split(":", 1)
                # Convert $VAR to {{env.VAR}}
                value = re.sub(r"\$(\w+)", r"{{env.\1}}", value.strip())
                headers[key.strip()] = value
        elif token in ("-d", "--data", "--data-raw"):
            i += 1
            data = tokens[i]
            # Try to parse as JSON
            try:
                import json
                body = json.loads(data)
            except:
                body = {"data": data}
        elif token.startswith("http"):
            endpoint = token
        elif not token.startswith("-"):
            # Might be the URL
            if "://" in token:
                endpoint = token
        
        i += 1
    
    return endpoint, method, headers, body
