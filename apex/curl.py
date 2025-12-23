"""Create agents from curl commands.

Example:
    import apex
    
    agent = apex.from_curl(
        name="Slack Notifier",
        curl='''
        curl -X POST https://slack.com/api/chat.postMessage \\
          -H "Authorization: Bearer $SLACK_TOKEN" \\
          -d '{"channel": "{{input.channel}}", "text": "{{input.message}}"}'
        ''',
        price=apex.Fixed(0.50),
    )
    agent.serve(port=8001)
"""

import json
import os
import re
import shlex
from typing import Any

import httpx

from .pricing import Pricing


def from_curl(
    name: str,
    curl: str,
    price: Pricing,
    output: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    capabilities: list[str] | None = None,
    wallet: str | None = None,
) -> "Agent":
    """Create an agent from a curl command.
    
    Args:
        name: Agent name
        curl: Curl command string (supports {{input.field}} and $ENV_VAR)
        price: Pricing model
        output: JSON path to extract from response
        description: Agent description
        tags: Searchable tags
        capabilities: Capability IDs
        wallet: Wallet address
    
    Returns:
        Agent instance
    
    Example:
        agent = apex.from_curl(
            name="GitHub API",
            curl='curl -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user',
            price=apex.Fixed(0.10),
        )
    """
    from .agent import Agent
    
    # Parse curl command
    endpoint, method, headers, body = _parse_curl(curl)
    
    # Create handler
    async def curl_handler(input_data: dict) -> dict:
        context = {"input": input_data, "env": dict(os.environ)}
        
        # Substitute templates
        req_endpoint = _substitute(endpoint, context)
        req_headers = _substitute(headers, context)
        req_body = _substitute(body, context) if body else None
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                method=method,
                url=req_endpoint,
                headers=req_headers,
                json=req_body if isinstance(req_body, dict) else None,
                content=req_body if isinstance(req_body, str) else None,
            )
            response.raise_for_status()
            
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                response_data = {"text": response.text}
        
        # Extract output if path specified
        if output:
            result = _extract_path(response_data, output)
            return {"result": result}
        
        return {"result": response_data}
    
    agent = Agent(
        name=name,
        price=price,
        description=description or f"Curl wrapper: {endpoint[:50]}...",
        tags=tags or [],
        capabilities=capabilities or [name.lower().replace(" ", "-")],
        wallet=wallet,
    )
    
    agent._handler = curl_handler
    agent._source_type = "curl"
    agent._source_config = {
        "curl": curl,
        "parsed": {
            "endpoint": endpoint,
            "method": method,
            "headers": headers,
            "body": body,
        },
        "output": output,
    }
    
    return agent


def _parse_curl(curl: str) -> tuple[str, str, dict, Any]:
    """Parse a curl command into components.
    
    Returns:
        (endpoint, method, headers, body)
    """
    # Normalize line continuations
    curl = curl.replace("\\\n", " ").replace("\\\r\n", " ").strip()
    
    # Convert $VAR to {{env.VAR}} for consistency
    curl = re.sub(r"\$(\w+)", r"{{env.\1}}", curl)
    
    try:
        tokens = shlex.split(curl)
    except ValueError:
        # Handle unbalanced quotes
        tokens = curl.split()
    
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
            if i < len(tokens):
                method = tokens[i]
        
        elif token in ("-H", "--header"):
            i += 1
            if i < len(tokens):
                header = tokens[i]
                if ":" in header:
                    key, value = header.split(":", 1)
                    headers[key.strip()] = value.strip()
        
        elif token in ("-d", "--data", "--data-raw", "--data-binary"):
            i += 1
            if i < len(tokens):
                data = tokens[i]
                try:
                    body = json.loads(data)
                except json.JSONDecodeError:
                    body = data
                # Imply POST if not specified
                if method == "GET":
                    method = "POST"
        
        elif token.startswith("http"):
            endpoint = token
        
        elif not token.startswith("-") and "://" in token:
            endpoint = token
        
        i += 1
    
    return endpoint, method, headers, body


def _substitute(template: Any, context: dict) -> Any:
    """Substitute {{variable}} placeholders."""
    if isinstance(template, str):
        def replace(match):
            path = match.group(1).strip()
            
            if path.startswith("env."):
                return os.environ.get(path[4:], "")
            
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
