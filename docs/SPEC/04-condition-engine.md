# 04 — Condition Engine (`conditions.py`)

Status: `PLANNED`

> Turns the visual rule rows (Quantman "Entry When / Exit When") into evaluable logic.
> A condition reads precomputed indicator/price arrays at a bar index and returns a boolean.
> Cross detection compares the previous and current closed bars — never the forming bar.

## 1. Operand

An operand is one side of a comparison. It resolves to a single float at bar index `i`.

```python
class Operand:
    kind: str        # "PRICE" | "INDICATOR" | "CONST"
    ref: str = ""    # PRICE: "close"/"open"/"high"/"low"/"hl2"/"hlc3"
                     # INDICATOR: indicator name, or "name.band" (e.g. "bb.upper", "macd.signal")
    const: float = 0 # CONST value
    offset: int = 0  # bars back: 0 = current closed bar, 1 = previous, ...
```

### Resolution
```python
def resolve(op: Operand, candles, indicators, i) -> float | None:
    j = i - op.offset
    if j < 0: return None
    if op.kind == "CONST":     return op.const
    if op.kind == "PRICE":     return field_value(candles, op.ref, j)
    if op.kind == "INDICATOR": return series_value(indicators[op.ref], j)
    return None
# any None / NaN propagates → condition is False (warmup-not-ready)
```

`offset` enables rules like *"close > close 3 bars ago"* (momentum) and *"RSI today >
RSI yesterday"* (slope).

## 2. Operators

| Operator | Semantics (at bar `i`) |
|----------|------------------------|
| `GT` `>` | L > R |
| `LT` `<` | L < R |
| `GTE` `>=` | L ≥ R |
| `LTE` `<=` | L ≤ R |
| `EQ` `==` | abs(L − R) < ε (ε = 1e-9) |
| `CROSS_ABOVE` | L crossed up through R between bar i-1 and i |
| `CROSS_BELOW` | L crossed down through R between bar i-1 and i |

### Cross detection (the part retail tools get wrong)
```
CROSS_ABOVE: prevL <= prevR  AND  curL >  curR
CROSS_BELOW: prevL >= prevR  AND  curL <  curR
```
where `prev*` use bar `i-1`, `cur*` use bar `i`. Requires both bars valid (non-null); at
`i == 0` cross is always False. This is a strict edge transition — a value merely *staying*
above R does not re-fire. That single-fire property prevents the "enters every bar while
above" bug.

## 3. Condition

```python
class Condition:
    lhs: Operand
    op: str          # one of the operators above
    rhs: Operand
```

```python
def eval_condition(c, candles, indicators, i) -> bool:
    if c.op in ("CROSS_ABOVE","CROSS_BELOW"):
        if i == 0: return False
        pL,pR = resolve(c.lhs,..,i-1), resolve(c.rhs,..,i-1)
        cL,cR = resolve(c.lhs,..,i),   resolve(c.rhs,..,i)
        if None in (pL,pR,cL,cR): return False
        return (pL<=pR and cL>cR) if c.op=="CROSS_ABOVE" else (pL>=pR and cL<cR)
    L,R = resolve(c.lhs,..,i), resolve(c.rhs,..,i)
    if L is None or R is None: return False
    return { "GT":L>R, "LT":L<R, "GTE":L>=R, "LTE":L<=R, "EQ":abs(L-R)<1e-9 }[c.op]
```

## 4. Condition Group (tree)

v1 supports a single group joining N conditions with one connective. v2 allows nesting.

```python
class ConditionGroup:
    join: str = "AND"             # "AND" | "OR"
    conditions: list[Condition]
    children: list["ConditionGroup"] = []   # v2 nesting

def eval_group(g, candles, indicators, i) -> bool:
    flags = [eval_condition(c, candles, indicators, i) for c in g.conditions]
    flags += [eval_group(ch, candles, indicators, i) for ch in g.children]
    if not flags: return False    # empty tree never fires
    return all(flags) if g.join == "AND" else any(flags)
```

**Empty entry tree** → no signal entries; the engine falls back to time-based entry only if
explicitly configured, else the day is skipped (`skip_reason="no_entry_tree"`).

## 5. Examples

### EMA crossover entry, opposite-cross exit
```
entry: group(AND, [ Condition(EMA9, CROSS_ABOVE, EMA21) ])
exit:  group(OR,  [ Condition(EMA9, CROSS_BELOW, EMA21) ])
```

### RSI pullback in uptrend
```
entry: group(AND, [
  Condition(close, GT, EMA200),                 # trend filter
  Condition(RSI14, CROSS_ABOVE, const(40)),     # momentum trigger
])
```

### Bollinger mean-reversion
```
entry: group(AND, [ Condition(close, CROSS_BELOW, bb.lower) ])
exit:  group(OR,  [ Condition(close, CROSS_ABOVE, bb.basis) ])
```

### MACD + Supertrend confluence
```
entry: group(AND, [
  Condition(macd.macd, CROSS_ABOVE, macd.signal),
  Condition(st.dir, EQ, const(1)),              # supertrend up
])
```

## 6. Evaluation Timing in the Engine

- Conditions evaluate at **candle close** only. The engine maps each interval bar's close to
  the corresponding 1-minute timestamp and acts there.
- Entry tree is checked while **FLAT**. On first True → open at that bar's close minute.
- Exit tree is checked while **IN POSITION**, alongside risk rules ([07](07-risk-management.md)).
  Risk exits take precedence if both fire on the same bar (capital preservation first).
- After a signal exit, **re-entry** is allowed only if `re_entry_after_exit` is set and the
  entry tree fires again later the same session.

## 7. Determinism & Safety

- Pure function of `(trees, candles, indicators, i)` → no clock, no RNG.
- Null/NaN → False (never an exception, never a fabricated entry).
- Operator set is closed and validated at the API boundary; unknown operator → HTTP 400.
- Indicator references are validated at request time against the declared indicator names;
  a dangling reference (`ema99` not defined) → HTTP 400, not a silent skip.

## 8. Complexity

Per bar: O(conditions). Per day: O(bars × conditions). For 5-min (75 bars) × ~5 conditions
= ~375 evals/day — negligible. Indicator precompute dominates, and that is vectorised once.
