[Deutsch](DE-Understanding-Results) | [English](EN-Understanding-Results)

---

# Understanding Results

## pp

`pp` means prompt processing. Example:

```text
pp4096 = processing a prompt of roughly 4096 tokens
```

Higher values mean existing context is processed faster.

## tg

`tg` means text generation. Example:

```text
tg128 = generating 128 tokens
```

## Average and variation

A high average with large variation is less trustworthy than a slightly lower but stable value. Reference runs should use repeated measurements.

## TTFT

Time to First Token:

- P50: typical response latency
- P95: slower but realistic tail latency

## System TPS

Total throughput across all parallel requests. Higher concurrency can increase system TPS while reducing throughput per user and increasing TTFT.

## Status values

- `ok`: successful
- `skipped_capacity`: expected hardware or memory boundary
- `timeout`: configured time limit exceeded
- `failed`: actual test or backend failure

## Efficiency

Tokens/s per watt is useful when power draw was measured reliably.

## Long-context penalty

```text
Penalty = 1 - (tok/s at long context / tok/s at empty context)
```
