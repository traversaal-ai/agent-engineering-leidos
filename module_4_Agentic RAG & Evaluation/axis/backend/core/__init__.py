"""Cross-cutting Backend concerns: auth, caps, error mapping, middleware.

These are the responsibilities System Design Section 6.3 says a dedicated API
gateway would own in a multi-instance deployment. Here the Backend plays that
role directly, in front of the AI Backend — worth teaching as a concept even
though the component is deliberately absent.
"""
