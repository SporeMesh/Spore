const source = `
export function classify(row) {
  const calmScore =
    (1.1 - row.sigma_ratio) +
    (0.55 - row.percentile_rank_252) +
    (1.02 - row.ma_ratio_20);
  const transitionScore =
    1.0 -
    Math.abs(row.sigma_ratio - 1.15) -
    Math.abs(row.percentile_rank_252 - 0.52) -
    0.5 * Math.abs(row.ma_ratio_63 - 1.0);
  const stressScore =
    (row.sigma_ratio - 1.05) +
    (row.percentile_rank_252 - 0.45) +
    (row.ma_ratio_20 - 1.0) +
    Math.max(0, row.vol_of_vol);

  const maxScore = Math.max(calmScore, transitionScore, stressScore);
  const scores = {
    calm: Math.exp(calmScore - maxScore),
    transition: Math.exp(transitionScore - maxScore),
    stress: Math.exp(stressScore - maxScore),
  };
  const total = scores.calm + scores.transition + scores.stress;
  return {
    calm: scores.calm / total,
    transition: scores.transition / total,
    stress: scores.stress / total,
  };
}
`.trim();

export default source;
