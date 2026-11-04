"""Model access: one guarded path for every request, crew and baselines alike.

The layers, from the agent down to the network:

``AgentRunner`` → ``GuardedLLM`` (masking and leak checks) → ``CachingTransport`` (development only)
→ ``ResilientTransport`` (rate limit, retries) → ``HttpChatTransport`` (HTTPS, allowed host only).
"""
