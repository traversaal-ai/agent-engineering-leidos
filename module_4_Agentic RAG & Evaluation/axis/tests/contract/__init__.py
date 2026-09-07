"""Conformance tests: one suite run against every implementation of an interface.

"Swappable providers" is only true if the implementations actually behave alike,
so the same tests run against OpenAI, Anthropic, Ollama, and the fake. This directory
also holds the `Retriever` conformance suite, which is where the obligations of a
retriever are actually *defined* rather than described — an empty result is a legitimate
outcome and must not raise, and `is_ready` distinguishes "no index" from "no matches".
"""
