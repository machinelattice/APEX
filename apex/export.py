"""Export agents as skill folders.

Creates a portable skill folder:
    my-agent/
    â”œâ”€â”€ SKILL.md        # Metadata
    â”œâ”€â”€ handler.py      # Implementation
    â”œâ”€â”€ apex.yaml       # APEX config
    â””â”€â”€ requirements.txt

Example:
    agent = apex.from_api(...)
    agent.export("./my-agent")
    
    # Or add APEX to existing skill:
    apex.add_apex("./my-skill", apex.Fixed(5.00))
"""

import yaml
from pathlib import Path
from datetime import datetime, timezone

from .pricing import Fixed, Negotiated, Pricing


def add_apex(skill_path: str, price: Pricing, overwrite: bool = False):
    """Add apex.yaml to existing skill folder.
    
    Takes a skill folder with SKILL.md + handler.py and adds
    apex.yaml to make it APEX-compatible.
    
    Args:
        skill_path: Path to skill folder
        price: Pricing model (Fixed or Negotiated)
        overwrite: If True, overwrite existing apex.yaml
    
    Example:
        apex.add_apex("./my-skill", apex.Fixed(5.00))
        apex.add_apex("./my-skill", apex.Fixed(10.00), overwrite=True)
    """
    from .loader import load
    
    folder = Path(skill_path)
    apex_yaml = folder / "apex.yaml"
    existed = apex_yaml.exists()
    
    if existed and not overwrite:
        print(f"âš  {skill_path}/apex.yaml already exists. Use overwrite=True to replace.")
        return
    
    agent = load(skill_path, price=price)
    export_agent(agent, skill_path)
    
    action = "Updated" if existed else "Added"
    print(f"âœ“ {action} APEX in {skill_path}")


def export_agent(agent, path: str):
    """Export an agent as a skill folder.
    
    Args:
        agent: Agent to export
        path: Output directory path
    """
    folder = Path(path)
    folder.mkdir(parents=True, exist_ok=True)
    
    # Generate SKILL.md
    _write_skill_md(agent, folder / "SKILL.md")
    
    # Generate apex.yaml
    _write_apex_yaml(agent, folder / "apex.yaml")
    
    # Generate handler.py based on source type
    _write_handler(agent, folder / "handler.py")
    
    # Generate requirements.txt
    _write_requirements(agent, folder / "requirements.txt")
    
    print(f"âœ“ Exported '{agent.name}' to {folder}")


def _write_skill_md(agent, path: Path):
    """Write SKILL.md with frontmatter."""
    # Build frontmatter
    frontmatter = {
        "name": agent.name,
        "description": agent.description or f"{agent.name} agent",
    }
    
    if agent.model:
        frontmatter["model"] = agent.model
    
    if agent.tags:
        frontmatter["tags"] = agent.tags
    
    if agent.capabilities:
        frontmatter["capabilities"] = agent.capabilities
    
    # Build body
    body_parts = [f"# {agent.name}", ""]
    
    if agent.description:
        body_parts.append(agent.description)
        body_parts.append("")
    
    # Add instructions if present
    if agent.instructions:
        body_parts.append("## Instructions")
        body_parts.append("")
        for instruction in agent.instructions:
            body_parts.append(instruction)
        body_parts.append("")
    
    # Add capabilities section
    if agent.capabilities:
        body_parts.append("## Capabilities")
        body_parts.append("")
        for cap in agent.capabilities:
            body_parts.append(f"- **{cap}**")
        body_parts.append("")
    
    # Combine
    frontmatter_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
    body = "\n".join(body_parts)
    
    content = f"---\n{frontmatter_yaml}---\n\n{body}"
    path.write_text(content)


def _write_apex_yaml(agent, path: Path):
    """Write apex.yaml with APEX-specific config."""
    config = {
        "# APEX Protocol Configuration": None,
        "pricing": _pricing_to_dict(agent.price),
    }
    
    if agent.wallet:
        config["wallet"] = agent.wallet
    
    if agent.agent_id:
        config["agent_id"] = agent.agent_id
    
    if agent.tags:
        config["tags"] = agent.tags
    
    if agent.capabilities:
        config["capabilities"] = agent.capabilities
    
    # Add handler config if from API/curl
    source_type = getattr(agent, "_source_type", None)
    if source_type == "api":
        config["handler"] = {
            "file": "handler.py",
            "function": "run",
        }
    elif source_type == "curl":
        config["handler"] = {
            "file": "handler.py", 
            "function": "run",
        }
    
    # Write YAML (filter out None comment placeholder)
    config = {k: v for k, v in config.items() if v is not None}
    
    yaml_content = "# APEX Protocol Configuration\n"
    yaml_content += yaml.dump(config, default_flow_style=False, sort_keys=False)
    
    path.write_text(yaml_content)


def _pricing_to_dict(price: Pricing) -> dict:
    """Convert Pricing to dict for YAML."""
    if isinstance(price, Fixed):
        return {
            "model": "fixed",
            "amount": price.amount,
            "currency": price.currency,
        }
    
    elif isinstance(price, Negotiated):
        result = {
            "model": "negotiated",
            "target": price.target,
            "minimum": price.minimum,
            "max_rounds": price.max_rounds,
            "currency": price.currency,
        }
        if price.strategy:
            result["strategy"] = price.strategy
        if price.model:
            result["negotiation_model"] = price.model
        if price.instructions:
            result["instructions"] = price.instructions
        return result
    
    return {"model": "fixed", "amount": 1.00}


def _write_handler(agent, path: Path):
    """Generate handler.py based on agent source."""
    source_type = getattr(agent, "_source_type", None)
    source_config = getattr(agent, "_source_config", {})
    
    if source_type == "api":
        content = _generate_api_handler(agent, source_config)
    elif source_type == "curl":
        content = _generate_curl_handler(agent, source_config)
    else:
        content = _generate_default_handler(agent)
    
    path.write_text(content)


def _generate_api_handler(agent, config: dict) -> str:
    """Generate handler for API-based agent."""
    return f'''"""Handler for {agent.name}

Auto-generated from API endpoint.
"""

import os
import re
import httpx


async def run(input: dict) -> dict:
    """Execute the API call."""
    
    # API Configuration
    endpoint = "{config.get('endpoint', '')}"
    method = "{config.get('method', 'POST')}"
    headers = {config.get('headers', {})}
    body_template = {config.get('body')}
    params_template = {config.get('params', {})}
    output_path = {repr(config.get('output'))}
    
    # Substitute templates
    context = {{"input": input, "env": dict(os.environ)}}
    
    def substitute(template):
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
                        return ""
                return str(value) if value else ""
            return re.sub(r"\\{{\\{{(.+?)\\}}\\}}", replace, template)
        elif isinstance(template, dict):
            return {{k: substitute(v) for k, v in template.items()}}
        elif isinstance(template, list):
            return [substitute(item) for item in template]
        return template
    
    req_headers = substitute(headers)
    req_body = substitute(body_template) if body_template else None
    req_params = substitute(params_template)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.request(
            method=method,
            url=endpoint,
            headers=req_headers,
            json=req_body,
            params=req_params,
        )
        response.raise_for_status()
        data = response.json()
    
    # Extract output
    if output_path:
        parts = output_path.split(".")
        result = data
        for part in parts:
            if isinstance(result, dict):
                result = result.get(part)
            elif isinstance(result, list) and part.isdigit():
                result = result[int(part)]
        return {{"result": result}}
    
    return {{"result": data}}
'''


def _generate_curl_handler(agent, config: dict) -> str:
    """Generate handler for curl-based agent."""
    parsed = config.get("parsed", {})
    return f'''"""Handler for {agent.name}

Auto-generated from curl command.
"""

import os
import re
import json
import httpx


async def run(input: dict) -> dict:
    """Execute the curl command."""
    
    # Parsed curl configuration
    endpoint = "{parsed.get('endpoint', '')}"
    method = "{parsed.get('method', 'POST')}"
    headers = {parsed.get('headers', {})}
    body_template = {repr(parsed.get('body'))}
    output_path = {repr(config.get('output'))}
    
    # Substitute templates
    context = {{"input": input, "env": dict(os.environ)}}
    
    def substitute(template):
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
                        return ""
                return str(value) if value else ""
            return re.sub(r"\\{{\\{{(.+?)\\}}\\}}", replace, template)
        elif isinstance(template, dict):
            return {{k: substitute(v) for k, v in template.items()}}
        elif isinstance(template, list):
            return [substitute(item) for item in template]
        return template
    
    req_endpoint = substitute(endpoint)
    req_headers = substitute(headers)
    req_body = substitute(body_template) if body_template else None
    
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
            data = response.json()
        except json.JSONDecodeError:
            data = {{"text": response.text}}
    
    # Extract output
    if output_path:
        parts = output_path.split(".")
        result = data
        for part in parts:
            if isinstance(result, dict):
                result = result.get(part)
            elif isinstance(result, list) and part.isdigit():
                result = result[int(part)]
        return {{"result": result}}
    
    return {{"result": data}}
'''


def _generate_default_handler(agent) -> str:
    """Generate default handler."""
    instructions = agent.instructions or []
    instructions_str = "\\n".join(instructions) if instructions else "Process the input and return a result."
    
    return f'''"""Handler for {agent.name}

Implement your agent logic here.
"""


async def run(input: dict) -> dict:
    """Process input and return result.
    
    Instructions:
    {instructions_str}
    
    Args:
        input: Input data from buyer
        
    Returns:
        Result dictionary
    """
    # TODO: Implement your logic here
    query = input.get("query", input.get("input", str(input)))
    
    return {{
        "result": f"Processed: {{query}}",
        "status": "completed",
    }}
'''


def _write_requirements(agent, path: Path):
    """Generate requirements.txt."""
    requirements = [
        "httpx>=0.24.0",
    ]
    
    # Add based on source type
    source_type = getattr(agent, "_source_type", None)
    if source_type in ("api", "curl"):
        pass  # httpx is enough
    else:
        # LLM-based might need langchain
        requirements.append("# langchain>=0.1.0  # Uncomment if using LLM")
        requirements.append("# openai>=1.0.0      # Uncomment if using OpenAI")
    
    path.write_text("\n".join(requirements) + "\n")