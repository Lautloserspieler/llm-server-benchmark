[Deutsch](DE-Benchmark-Methodology) | [English](EN-Benchmark-Methodology)

---

# Benchmark Methodology

## Prompt processing

Measures how quickly existing input tokens are processed. This matters for system prompts, RAG, and long documents.

## Text generation

Measures the speed of newly generated tokens. Typical generation depths include 128, 512, or 1024 tokens.

## Repetitions

A reference value should not come from a single run. llmbench records averages and variation across repeated measurements.

## Long context

Long-context tests populate the context and KV cache before measurement. This shows how performance and memory use change at 8K, 32K, 65K, or larger contexts.

## TTFT

**Time to First Token** measures the delay until the first visible token. P50 and P95 are especially useful.

## Concurrency

Parallel requests reveal:

- total system throughput
- throughput per request
- TTFT
- success rate

## Soak testing

The soak test keeps CPU and GPU paths under load for longer periods to expose thermal instability, errors, and throughput degradation.

## OOM / capacity

`skipped_capacity` represents an expected capacity boundary, not necessarily a benchmark failure.

## Multi-tenant

Multiple servers or models run at the same time to measure resource sharing.

## Comparability

Model, quantization, backend, build, profiles, and relevant configuration should match.
