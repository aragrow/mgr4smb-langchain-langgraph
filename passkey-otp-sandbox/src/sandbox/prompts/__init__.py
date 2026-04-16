"""System prompts for each agent.

Each agent in `sandbox.agents` imports its SYSTEM_PROMPT from the
matching module in this package. Keeping prompts out of the agent
files makes them easy to edit, diff, and share without re-reading
the surrounding Python.
"""
