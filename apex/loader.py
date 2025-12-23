"""Load agents from skill folders.

A skill folder contains:
    SKILL.md      - Agent metadata (name, description in frontmatter)
    handler.py    - Implementation (run function)
    apex.yaml     - APEX pricing config

Example:
    import apex
    
    agent = apex.load("./my-skill", price=apex.Fixed(5.00))
    agent.serve(port=8001)
"""

import asyncio
import importlib.util
import inspect
import re
import yaml
from pathlib import Path
from typing import Callable

from .pricing import Fixed, Negotiated, Pricing


def load(
    path: str,
    price: Pricing | None = None,
    wallet: str | None = None,
) -> "Agent":
    """Load an agent from a skill folder.
    
    Args:
        path: Path to skill folder containing SKILL.md and handler.py
        price: Pricing (overrides apex.yaml if provided)
        wallet: Wallet address (overrides apex.yaml if provided)
    
    Returns:
        Agent instance ready to serve
    
    Example:
        agent = apex.load("./my-skill", price=Fixed(5.00))
        agent.serve(port=8001)
    """
    from .agent import Agent
    
    folder = Path(path)
    
    if not folder.exists():
        raise FileNotFoundError(f"Skill folder not found: {path}")
    
    # Parse SKILL.md for metadata
    skill_md = folder / "SKILL.md"
    if skill_md.exists():
        metadata = _parse_skill_md(skill_md)
    else:
        metadata = {"name": folder.name, "description": None}
    
    # Load apex.yaml for APEX config
    apex_yaml = folder / "apex.yaml"
    apex_config = {}
    if apex_yaml.exists():
        with open(apex_yaml) as f:
            apex_config = yaml.safe_load(f) or {}
    
    # Determine pricing (arg > apex.yaml > default)
    if price is None:
        price = _parse_pricing(apex_config.get("pricing", {}))
    
    # Determine wallet
    if wallet is None:
        wallet = apex_config.get("wallet")
    
    # Load handler
    handler = _load_handler(folder, apex_config.get("handler", {}))
    
    # Extract instructions from SKILL.md body
    instructions = metadata.get("instructions", [])
    if isinstance(instructions, str):
        instructions = [instructions]
    
    agent = Agent(
        name=metadata.get("name", folder.name),
        price=price,
        description=metadata.get("description"),
        instructions=instructions,
        model=metadata.get("model", apex_config.get("model", "gpt-4o")),
        tags=apex_config.get("tags", metadata.get("tags", [])),
        capabilities=apex_config.get("capabilities", metadata.get("capabilities", [])),
        agent_id=apex_config.get("agent_id"),
        wallet=wallet,
    )
    
    if handler:
        agent._handler = handler
    
    # Store source info
    agent._source_type = "skill"
    agent._source_config = {"path": str(folder.absolute())}
    
    return agent


def _parse_skill_md(path: Path) -> dict:
    """Parse SKILL.md frontmatter and body."""
    content = path.read_text()
    
    # Extract YAML frontmatter between --- markers
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', content, re.DOTALL)
    if match:
        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
            body = match.group(2).strip()
            
            # If body exists, use it as instructions
            if body:
                frontmatter["instructions"] = [body]
            
            return frontmatter
        except yaml.YAMLError:
            pass
    
    return {"name": path.stem}


def _parse_pricing(config: dict) -> Pricing:
    """Parse pricing from apex.yaml config."""
    if not config:
        return Fixed(1.00)  # Default
    
    model = config.get("model", "fixed")
    currency = config.get("currency", "USDC")
    
    if model == "fixed":
        return Fixed(
            amount=float(config.get("amount", 1.0)),
            currency=currency,
        )
    
    elif model == "negotiated":
        return Negotiated(
            target=float(config.get("target", config.get("target_amount", 50.0))),
            minimum=float(config.get("minimum", config.get("min_amount", 25.0))),
            max_rounds=int(config.get("max_rounds", 5)),
            currency=currency,
            strategy=config.get("strategy"),
            model=config.get("negotiation_model", config.get("llm_model")),
            instructions=config.get("instructions", []),
        )
    
    return Fixed(1.00)


def _load_handler(folder: Path, handler_config: dict) -> Callable | None:
    """Load handler function from skill folder."""
    
    # Check handler config for file/function names
    handler_file = handler_config.get("file", "handler.py")
    handler_func = handler_config.get("function", "run")
    
    # Alternative file names
    candidates = [handler_file, "handler.py", "main.py", "agent.py"]
    
    for filename in candidates:
        filepath = folder / filename
        if filepath.exists():
            try:
                handler = _import_handler(filepath, handler_func)
                if handler:
                    return handler
            except Exception:
                continue
    
    return None


def _import_handler(filepath: Path, func_name: str) -> Callable | None:
    """Import a function from a Python file."""
    spec = importlib.util.spec_from_file_location("handler_module", filepath)
    if spec is None or spec.loader is None:
        return None
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    # Try specified function name first
    handler = getattr(module, func_name, None)
    if handler and callable(handler):
        return _wrap_handler(handler)
    
    # Try alternative names
    for name in ["run", "handle", "main", "handler"]:
        handler = getattr(module, name, None)
        if handler and callable(handler):
            return _wrap_handler(handler)
    
    return None


def _wrap_handler(handler: Callable) -> Callable:
    """Wrap handler to ensure it's async."""
    if asyncio.iscoroutinefunction(handler):
        return handler
    
    async def async_wrapper(input_data: dict) -> dict:
        result = handler(input_data)
        if asyncio.iscoroutine(result):
            return await result
        return result
    
    return async_wrapper
