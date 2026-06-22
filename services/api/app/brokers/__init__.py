"""
Read-only broker portfolio adapters (Phase 14).

This package fetches current positions, cash, and today's performance from Tiger
Brokers and Interactive Brokers and normalises them into a broker-neutral contract.

Strictly read-only: no order, transfer, or other write operations exist here. Each
adapter enforces an in-code allowlist of the exact broker calls it is permitted to make.
No network activity or broker-client construction happens at import time.
"""
