import { get } from "./api.mjs";

export async function listChallenges(options = {}) {
  return get("/api/v1/challenge", { baseUrl: options.baseUrl });
}

export async function getChallenge(challengeId, options = {}) {
  return get(`/api/v1/challenge/${challengeId}`, { baseUrl: options.baseUrl });
}

export async function getChallengeLeaderboard(challengeId, options = {}) {
  return get(`/api/v1/challenge/${challengeId}/leaderboard`, { baseUrl: options.baseUrl });
}

export async function getChallengePayoutPreview(challengeId, apiKey, options = {}) {
  return get(`/api/v1/challenge/${challengeId}/payout-preview`, {
    baseUrl: options.baseUrl,
    apiKey,
  });
}

export function pickDefaultChallenge(challenges) {
  if (!Array.isArray(challenges) || challenges.length === 0) return null;
  const active = challenges
    .filter((item) => item.status === "active")
    .sort((a, b) => b.prize_pool - a.prize_pool);
  if (active.length > 0) return active[0];
  const scheduled = challenges
    .filter((item) => item.status === "scheduled")
    .sort((a, b) => b.prize_pool - a.prize_pool);
  return scheduled[0] || challenges[0];
}

export function challengeRuntime(challenge) {
  if (!challenge) return "unknown";
  return challenge?.rule_jsonb?.runtime || challenge?.evaluator_jsonb?.runtime || "local";
}

export function supportsBrowserRuntime(challenge) {
  return ["browser", "universal"].includes(challengeRuntime(challenge));
}
