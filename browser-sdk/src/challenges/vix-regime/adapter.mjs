import baselineSource from "./baseline-source.mjs";
import { VIX_PUBLIC_EVAL, VIX_PUBLIC_TRAIN } from "./vix-regime-data.mjs";
import { scoreClassifierSource } from "./score.mjs";

function stripCodeFences(text) {
  const match = text.match(/```(?:javascript|js|ts|typescript)?\n?([\s\S]*?)```/i);
  return match ? match[1].trim() : text.trim();
}

export function createVixRegimeAdapter(options = {}) {
  return {
    async loadContext() {
      const source = options.initialSource || baselineSource;
      const score = await scoreClassifierSource(source, VIX_PUBLIC_EVAL);
      return {
        source,
        bestSource: source,
        bestScore: score,
      };
    },

    async runExperiment({ llm, iteration, context }) {
      const current = context?.bestSource || baselineSource;
      const prompt = [
        "You are improving a JavaScript volatility regime classifier.",
        "Return only valid JavaScript source that exports classify(row).",
        "Goal: minimize log loss on hidden evaluation data.",
        `Public train rows: ${VIX_PUBLIC_TRAIN.length}. Public eval rows: ${VIX_PUBLIC_EVAL.length}.`,
        "",
        "Current classifier:",
        current,
      ].join("\n");
      const candidateSource = stripCodeFences(
        await llm.chat(
          "Write concise JavaScript. Do not explain. Return code only.",
          prompt,
        ),
      );
      const candidateScore = await scoreClassifierSource(
        candidateSource,
        VIX_PUBLIC_EVAL,
      );
      const bestScore = context?.bestScore ?? Number.POSITIVE_INFINITY;
      const improved = candidateScore + 1e-6 < bestScore;
      return {
        status: improved ? "keep" : "discard",
        title: `VIX regime attempt ${iteration}`,
        description: `Public eval log loss ${candidateScore.toFixed(6)}`,
        diff_summary: improved
          ? `Improved public log loss from ${bestScore.toFixed(6)} to ${candidateScore.toFixed(6)}`
          : `Public log loss ${candidateScore.toFixed(6)} did not beat ${bestScore.toFixed(6)}`,
        metadata_jsonb: {
          challenge: "vix-regime",
          public_log_loss: candidateScore,
          previous_best_log_loss: bestScore,
          source: candidateSource,
        },
        context: improved
          ? {
              source: candidateSource,
              bestSource: candidateSource,
              bestScore: candidateScore,
            }
          : context,
      };
    },
  };
}
