"""The blackboard: shared, append-only, event-sourced case state.

Every state change is an event, so any case can be replayed exactly as it happened. Everything on
the blackboard is already masked: real restricted values exist only inside local tool calls.
"""
