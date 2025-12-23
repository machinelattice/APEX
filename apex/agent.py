"""APEX Agent - Create LLM-powered agents with payment support.

Example:
    from apex import create_agent, Fixed
    from apex.payments import Wallet
    
    agent = create_agent(
        name="Research Bot",
        price=Fixed(5.00),
        description="I research topics",
        instructions=["You are a research assistant."],
        model="gpt-4o",
        wallet=Wallet.from_env("SELLER_KEY"),  # Real wallet
    )
    
    agent.register("https://registry.agenty.ai")
    agent.serve(port=8001)
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union, TYPE_CHECKING

from .pricing import Pricing, Fixed, Negotiated
from .negotiation import NegotiationEngine, NegotiationState
from .export import export_agent

if TYPE_CHECKING:
    from .payments import Wallet


@dataclass
class Agent:
    """APEX Agent instance."""
    
    name: str
    price: Pricing
    description: Optional[str] = None
    instructions: list[str] = field(default_factory=list)
    model: str = "gpt-4o"
    tools: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    agent_id: Optional[str] = None
    wallet: Optional[Union[str, "Wallet"]] = None  # Can be string (mock) or Wallet
    
    # Internal
    _handler: Optional[Callable] = None
    _negotiation_engines: Optional[dict] = None  # job_id -> NegotiationEngine
    _langchain_agent: Any = None
    _langchain_initialized: bool = False
    
    def __post_init__(self):
        # Generate agent_id if not provided
        if self.agent_id is None:
            slug = self.name.lower().replace(" ", "-")
            self.agent_id = f"{slug}-{uuid.uuid4().hex[:8]}"
        
        # Generate mock wallet if not provided
        if self.wallet is None:
            self.wallet = "0x" + uuid.uuid4().hex[:40]
        
        # Generate capabilities if not provided
        if not self.capabilities:
            self.capabilities = [self.name.lower().replace(" ", "-")]
        
        # Initialize negotiation engines dict
        self._negotiation_engines = {}
    
    @property
    def wallet_address(self) -> str:
        """Get wallet address (works for both mock string and real Wallet)."""
        if isinstance(self.wallet, str):
            return self.wallet
        return self.wallet.address
    
    async def balance(self) -> Optional[float]:
        """Get USDC balance (if real wallet)."""
        if not isinstance(self.wallet, str) and hasattr(self.wallet, 'balance'):
            return await self.wallet.balance("USDC")
        return None
    
    def _get_negotiation_engine(self, job_id: str) -> NegotiationEngine:
        """Get or create negotiation engine for a job."""
        if job_id not in self._negotiation_engines:
            self._negotiation_engines[job_id] = NegotiationEngine(self.price)
        return self._negotiation_engines[job_id]
    
    def _init_langchain_agent(self):
        """Initialize LangChain agent (lazy - only when first needed)."""
        if self._langchain_initialized:
            return
        
        self._langchain_initialized = True
        
        if not self.instructions:
            return
        
        try:
            from langchain_openai import ChatOpenAI
            from langchain.agents import AgentExecutor, create_openai_functions_agent
            from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
            
            # Build system prompt from instructions
            system_prompt = "\n".join(self.instructions)
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ])
            
            llm = ChatOpenAI(model=self.model)
            
            if self.tools:
                agent = create_openai_functions_agent(llm, self.tools, prompt)
                self._langchain_agent = AgentExecutor(agent=agent, tools=self.tools)
            else:
                # Simple chain without tools
                self._langchain_agent = prompt | llm
                
        except ImportError:
            print("Warning: langchain not installed. Install with: pip install apex-protocol[llm]")
            self._langchain_agent = None
    
    async def run(self, input: dict) -> dict:
        """Execute the agent with given input."""
        if self._handler:
            return await self._handler(input)
        
        # Lazy initialize LangChain
        if not self._langchain_initialized:
            self._init_langchain_agent()
        
        if self._langchain_agent is None:
            raise RuntimeError("No handler or LangChain agent configured")
        
        # Convert input to string if needed
        if isinstance(input, dict):
            input_str = input.get("query") or input.get("message") or input.get("input") or str(input)
        else:
            input_str = str(input)
        
        # Run LangChain agent
        try:
            if hasattr(self._langchain_agent, "invoke"):
                result = await self._langchain_agent.ainvoke({"input": input_str})
                if isinstance(result, dict):
                    return {"result": result.get("output", result)}
                return {"result": str(result.content if hasattr(result, 'content') else result)}
            else:
                result = await self._langchain_agent.arun(input_str)
                return {"result": result}
        except Exception as e:
            return {"error": str(e)}
    
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
                "currencies": [self.price.currency if hasattr(self.price, 'currency') else "USDC"],
                "address": self.wallet_address,
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
                # Clean up engine
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
        """Handle apex/counter (buyer countering our counter)."""
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
        """Handle apex/accept (buyer accepting our counter)."""
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
        """Create JSON-RPC response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
    
    def _make_error(self, request_id: str, code: int, message: str) -> dict:
        """Create JSON-RPC error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
    
    async def register(self, registry_url: str) -> dict:
        """Register this agent with a registry."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{registry_url}/api/register",
                json={
                    "agent_id": self.agent_id,
                    "name": self.name,
                    "description": self.description,
                    "url": f"http://localhost:8001/apex",  # Will be updated in serve()
                    "capabilities": self.capabilities,
                    "networks": ["base"],
                    "currencies": ["USDC"],
                    "wallet_address": self.wallet_address,
                    "pricing_info": self.price.to_dict(),
                    "tags": self.tags,
                },
                timeout=10.0,
            )
            
            if response.status_code == 200:
                print(f"✅ Registered '{self.name}' with {registry_url}")
                return response.json()
            else:
                raise Exception(f"Registration failed: {response.text}")
    
    def serve(self, host: str = "0.0.0.0", port: int = 8001):
        """Start HTTP server for this agent."""
        import uvicorn
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        
        agent = self  # Capture for closure
        
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
╔═══════════════════════════════════════════════════════════════╗
║  🤖 {self.name:<54} ║
╠═══════════════════════════════════════════════════════════════╣
║  ID:     {self.agent_id:<52} ║
║  URL:    http://{host}:{port}/apex{' ' * (41 - len(str(port)))} ║
║  Wallet: {self.wallet_address[:20]}...{' ' * 30} ║
║  Price:  {self._format_price():<52} ║
╚═══════════════════════════════════════════════════════════════╝
""")
        
        uvicorn.run(app, host=host, port=port)
    
    def export(self, path: str):
        """Export this agent as a skill folder.
        
        Args:
            path: Output directory path
        
        Example:
            agent.export("./my-bot-skill")
        """
        export_agent(self, path)
    
    def _format_price(self) -> str:
        """Format price for display."""
        if isinstance(self.price, Fixed):
            return f"${self.price.amount:.2f} {self.price.currency} (fixed)"
        elif isinstance(self.price, Negotiated):
            strategy = self.price.strategy or "balanced"
            return f"${self.price.minimum:.2f}-${self.price.target:.2f} {self.price.currency} ({strategy})"
        return "Unknown"


def create_agent(
    name: str,
    price: Pricing,
    description: Optional[str] = None,
    instructions: Optional[list[str]] = None,
    model: str = "gpt-4o",
    tools: Optional[list[Any]] = None,
    tags: Optional[list[str]] = None,
    capabilities: Optional[list[str]] = None,
    agent_id: Optional[str] = None,
    wallet: Optional[Union[str, "Wallet"]] = None,
    handler: Optional[Callable] = None,
) -> Agent:
    """Create an APEX agent.
    
    Args:
        name: Agent name
        price: Pricing model (Fixed or Negotiated)
        description: What the agent does
        instructions: System prompt / instructions for LLM
        model: LLM model to use
        tools: LangChain tools the agent can use
        tags: Searchable tags
        capabilities: Capability IDs (auto-generated if not provided)
        agent_id: Unique ID (auto-generated if not provided)
        wallet: Wallet address (string) or Wallet instance (auto-generated if not provided)
        handler: Custom handler function (alternative to LLM)
    
    Returns:
        Agent instance
    
    Example:
        # Basic agent with mock wallet
        agent = create_agent(
            name="Research Bot",
            price=Fixed(5.00),
            instructions=["You are a research assistant."],
            model="gpt-4o",
        )
        
        # Agent with real wallet
        from apex.payments import Wallet
        
        agent = create_agent(
            name="Research Bot",
            price=Fixed(5.00),
            wallet=Wallet.from_env("SELLER_KEY"),
            handler=my_handler,
        )
        agent.serve(port=8001)
    """
    agent = Agent(
        name=name,
        price=price,
        description=description,
        instructions=instructions or [],
        model=model,
        tools=tools or [],
        tags=tags or [],
        capabilities=capabilities or [],
        agent_id=agent_id,
        wallet=wallet,
    )
    
    if handler:
        agent._handler = handler
    
    return agent
