# VIX Regime Classifier Sprint #1

This challenge uses real CBOE VIX daily closes and derived rolling features.

Participants edit a single JavaScript classifier that exports:

```js
export function classify(row) {
  return { calm: 0.2, transition: 0.5, stress: 0.3 };
}
```

The browser and JS runtimes can both work on the same artifact. Public train and
public eval are included in this package. Final leaderboard and payout are meant
to use hidden evaluation data on the backend.
