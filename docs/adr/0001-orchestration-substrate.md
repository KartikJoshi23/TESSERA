# ADR-0001: LangGraph for control flow; our own protocol on top

- **Status:** accepted (3 Nov 2026)
- **Context:** The research claim is about coordination, so the communication and reconciliation
  mechanisms must be explicit, inspectable and switchable for ablation.
- **Decision:**
  - Use LangGraph 1.x only as the control-flow engine: conditional edges and bounded loops.
    Parallel turns are plain `asyncio`, and streaming reads the event log.
  - Do not use its checkpointer. A node's model calls are not safe to repeat, so a run restarts
    any case it did not finish, and replay comes from the event log.
  - Keep LangSmith tracing off in code, so that nothing leaves the machine that way.
  - Keep the typed message protocol, blackboard, conflict detector and decision policy in our
    own code.
  - Use no LangChain model wrappers. Every model call goes through our `LLMClient` and
    `AgentRunner`.
- **Consequences:**
  - Mechanisms are visible in our code and logs.
  - Replacing LangGraph with a hand-written scheduler stays cheap.
  - We pin versions to avoid churn.
- **Rejected:**
  - CrewAI and AutoGen/AG2: they hide the protocol or let the model pick who speaks.
  - Hosted agent platforms: paid, and they store session data off-machine.
