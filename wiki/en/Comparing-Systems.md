[Deutsch](DE-Comparing-Systems) | [English](EN-Comparing-Systems)

---

# Comparing Systems

## Core rule

Only comparable test conditions produce a defensible hardware comparison.

## Strict comparison

```bash
llmbench compare results/server-a results/server-b --strict
```

## Important comparison fields

- exact model file / model hash
- quantization
- backend
- backend build
- benchmark configuration
- profiles
- hardware mode
- context/generation depths
- relevant runtime settings

## GPU vs GPU overload

A normal `gpu` run and a `gpu_overload` run use different methodology and should not be treated as directly equivalent.

## Operating system

Windows and Linux can use different driver, scheduler, memory, and backend paths. The platform difference should remain visible.

## Power limit

```text
RTX 5090 @ 450 W
RTX 5090 @ 600 W
```

These are not the same test conditions.

## Reference-run checklist

1. same Git revision
2. same model suite
3. same quantization
4. same backend/build
5. Long preset
6. system as idle as practical
7. no foreign load
8. archive reports together
