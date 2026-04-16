"""GENERAL_INFO_AGENT — answers company questions from the knowledge base.

Ported from mgr4smb/agents/general_info.py. Contract is identical; the
backing store is a local JSON file instead of MongoDB Atlas, wrapped by
the `knowledge_base` tool.

The system prompt lives in sandbox.prompts.general_info.
"""

from langgraph.prebuilt import create_react_agent

from sandbox.llm import get_llm
from sandbox.prompts.general_info import SYSTEM_PROMPT
from sandbox.tools.knowledge_base import knowledge_base


TOOLS = [knowledge_base]


def build():
    """Return a compiled react agent for GENERAL_INFO_AGENT."""
    return create_react_agent(get_llm(), tools=TOOLS, prompt=SYSTEM_PROMPT)
