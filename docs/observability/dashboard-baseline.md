# Prometheus Dashboard Baseline

Suggested baseline panels:

1. Tool call throughput
   - `sum(rate(omniaudit_tool_calls_total[5m])) by (tool)`
2. Tool error rate
   - `sum(rate(omniaudit_tool_calls_total{status="error"}[5m])) by (tool)`
3. Tool latency (p95)
   - `histogram_quantile(0.95, sum(rate(omniaudit_tool_latency_seconds_bucket[5m])) by (le, tool))`
4. Write-gate denials
   - `sum(rate(omniaudit_write_gate_denied_total[5m])) by (tool)`
5. Rate-limit denials
   - `sum(rate(omniaudit_rate_limit_denied_total[5m])) by (bucket)`

Trace correlation conventions:

- Propagate `request_id` as the correlation identifier across logs, traces, and audit records.
- Include tool name and module labels on spans for all MCP tool calls.
- Include receipt identifiers (`receipt_id`) in post-write span events when available.
