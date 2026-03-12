import { VIX_LABELS, VIX_PUBLIC_EVAL, VIX_PUBLIC_TRAIN } from "./vix-regime-data.mjs";

const EXPORT_CLASSIFY_RE = /export\s+function\s+classify\s*\(/;

function normalizeSource(source) {
  const normalized = source.replace(EXPORT_CLASSIFY_RE, "function classify(");
  if (normalized === source) {
    throw new Error("classifier must export classify(row)");
  }
  return normalized;
}

export async function loadClassifier(source) {
  const body = `${normalizeSource(source)}\nreturn classify;`;
  const classify = new Function(body)();
  if (typeof classify !== "function") {
    throw new Error("classifier must export classify(row)");
  }
  return classify;
}

export function logLoss(dataset, predict) {
  let total = 0;
  for (const row of dataset) {
    const probabilities = predict(row);
    const p = Math.max(
      1e-9,
      Number(probabilities?.[row.label] ?? 0),
    );
    total += -Math.log(p);
  }
  return total / dataset.length;
}

export async function scoreClassifierSource(source, dataset = VIX_PUBLIC_EVAL) {
  const predict = await loadClassifier(source);
  return logLoss(dataset, predict);
}

export function datasetSummary() {
  return {
    labels: VIX_LABELS,
    public_train_rows: VIX_PUBLIC_TRAIN.length,
    public_eval_rows: VIX_PUBLIC_EVAL.length,
  };
}
