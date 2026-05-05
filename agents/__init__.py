"""Agent implementations.

Components in this package use Claude reasoning. Per the impact rule, an agent
lives here iff its inputs include unstructured text or judgment-bearing data,
its output requires narrative or contextual reasoning, or misclassification has
high revenue cost.

Pure SQL or deterministic Python belongs in `analytics/` instead.
"""
