# Token Assumptions

The Fluxora stream contract interacts with exactly one token, fixed at `init` time
and stored in `Config.token`. This document records the assumptions the contract
makes about that token and the consequences of violating them.

---

## Required token properties

| Property | Requirement |
|---|---|
| Interface | SEP-41 / Stellar Asset Contract (SAC) |
| `transfer` failure | Panics (does not silently succeed with a false return) |
| Re-entrancy | Does not call back into the stream contract during `transfer` |
| Balance accounting | `balance(addr)` reflects all prior transfers atomically |

The contract is tested exclusively against the Soroban mock SAC
(`register_stellar_asset_contract_v2`). Deployers using a custom token must
verify these properties independently.

---

## Direct deposits and `sweep_excess`

The contract does **not** implement a `receive` hook. Any tokens sent directly
to the contract address (outside of `create_stream` / `top_up_stream`) are
untracked by the `TotalLiabilities` counter and therefore become sweepable
excess.

```
sweepable = balance(contract_address) - total_liabilities
```

The admin can recover these tokens via `sweep_excess(to)` without affecting
any stream's accounting. See [security.md](security.md) for the full invariant.

---

## Consequences of violating assumptions

| Violation | Impact |
|---|---|
| Token silently fails `transfer` | Recipient/sender does not receive funds; state is already updated (CEI), so the stream appears settled but tokens are lost |
| Token re-enters stream contract | CEI ordering limits damage — state reflects the current operation before re-entry — but full safety is not guaranteed |
| Token balance does not reflect transfers atomically | `sweep_excess` may compute an incorrect `sweepable` amount |

---

## Upgrade considerations

If the token contract is upgraded (e.g. SAC migration), the stream contract
must be re-initialized with the new token address via a contract upgrade, since
`Config.token` is immutable after `init`. Existing streams continue to reference
the old token address.
