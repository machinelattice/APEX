"""Create agents from API endpoints.

Example:
    import apex
    
    agent = apex.from_api(
        name="Weather API",
        endpoint="https://api.weather.com/v1/current",
        headers={"Authorization": "Bearer {{env.API_KEY}}"},
        body={"location": "{{input.city}}"},
        price=apex.Fixed(1.00),
    )
    agent.serve(port=8001)
"""

import json
import os
import re
from typing import Any

import httpx

from .pricing import Pricing, Fixed


def from_api(
    name: str,
    endpoint: str,
    price: Pricing,
    method: str = "POST",
    headers: dict | None = None,
    body: dict | None = None,
    params: dict | None = None,
    output: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    capabilities: list[str] | None = None,
    wallet: str | None = None,
) -> "Agent":
    """Create an agent that wraps an API endpoint.
    
    Args:
        name: Agent name
        endpoint: API URL to call
        price: Pricing model
        method: HTTP method (GET, POST, etc.)
        headers: Request headers (supports {{env.VAR}} and {{input.field}})
        body: Request body template (supports {{env.VAR}} and {{input.field}})
        params: Query parameters template
        output: JSON path to extract from response (e.g., "data.result")
        description: Agent description
        tags: Searchable tags
        capabilities: Capability IDs
        wallet: Wallet address
    
    Returns:
        Agent instance
    
    Example:
        agent = apex.from_api(
            name="Weather",
            endpoint="https://api.weather.com/current",
            headers={"Authorization": "Bearer {{env.WEATHER_KEY}}"},
            body={"city": "{{input.location}}"},
            output="data.temperature",
            price=apex.Fixed(1.00),
        )
    """
    from .agent import Agent
    
    # Create handler that calls the API
    async def api_handler(input_data: dict) -> dict:
        context = {"input": input_data, "env": dict(os.environ)}
        
        # Substitute templates
        req_headers = _substitute(headers or {}, context)
        req_body = _substitute(body, context) if body else None
        req_params = _substitute(params or {}, context)
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                method=method,
                url=endpoint,
                headers=req_headers,
                json=req_body,
                params=req_params,
            )
            response.raise_for_status()
            response_data = response.json()
        
        # Extract output if path specified
        if output:
            result = _extract_path(response_data, output)
            return {"result": result}
        
        return {"result": response_data}
    
    agent = Agent(
        name=name,
        price=price,
        description=description or f"API wrapper for {endpoint}",
        tags=tags or [],
        capabilities=capabilities or [name.lower().replace(" ", "-")],
        wallet=wallet,
    )
    
    agent._handler = api_handler
    agent._source_type = "api"
    agent._source_config = {
        "endpoint": endpoint,
        "method": method,
        "headers": headers or {},
        "body": body,
        "params": params or {},
        "output": output,
    }
    
    return agent


def _substitute(template: Any, context: dict) -> Any:
    """Substitute {{variable}} placeholders in template."""
    if isinstance(template, str):
        def replace(match):
            path = match.group(1).strip()
            
            # Handle env variables
            if path.startswith("env."):
                env_var = path[4:]
                return os.environ.get(env_var, "")
            
            # Navigate path (e.g., input.query)
            parts = path.split(".")
            value = context
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, "")
                else:
                    value = ""
                    break
            return str(value) if value else ""
        
        return re.sub(r"\{\{(.+?)\}\}", replace, template)
    
    elif isinstance(template, dict):
        return {k: _substitute(v, context) for k, v in template.items()}
    
    elif isinstance(template, list):
        return [_substitute(item, context) for item in template]
    
    return template


def _extract_path(data: dict, path: str) -> Any:
    """Extract value from nested dict using dot notation."""
    parts = path.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            value = value[int(part)]
        else:
            return None
    return value
