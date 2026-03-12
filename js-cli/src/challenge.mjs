const STATUS_PRIORITY = {
  active: 0,
  scheduled: 1,
  closed: 2,
  paid: 3,
  draft: 4,
};

export function pickDefaultChallenge(challenges) {
  if (!Array.isArray(challenges) || challenges.length === 0) return null;
  return [...challenges].sort((a, b) => {
    const left = STATUS_PRIORITY[a.status] ?? 99;
    const right = STATUS_PRIORITY[b.status] ?? 99;
    if (left !== right) return left - right;
    if ((b.prize_pool || 0) !== (a.prize_pool || 0)) return (b.prize_pool || 0) - (a.prize_pool || 0);
    return String(a.end_at || "").localeCompare(String(b.end_at || ""));
  })[0];
}
