"""The learning bot's two deterministic tools (docs/LEARNBOT.md): `inventory` (what the desk learned, and the research
it could do next, read-only) and `check-diff` (the guard every learnbot/ pull request must pass).

The bot itself is a scheduled Claude session; these tools are the part that is code. Nothing here writes to the
journal, the configuration, a risk limit or a workflow, and nothing here merges, approves or marks a pull request ready.
"""
