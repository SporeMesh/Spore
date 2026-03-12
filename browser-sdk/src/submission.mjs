import { get, post } from "./api.mjs";

export async function createSubmission(apiKey, payload, options = {}) {
  return post("/api/v1/submission", {
    baseUrl: options.baseUrl,
    apiKey,
    json: payload,
  });
}

export async function listSubmissions(challengeId, apiKey, options = {}) {
  return get(`/api/v1/challenge/${challengeId}/submission`, {
    baseUrl: options.baseUrl,
    apiKey,
  });
}

export async function getSubmission(submissionId, apiKey, options = {}) {
  return get(`/api/v1/submission/${submissionId}`, {
    baseUrl: options.baseUrl,
    apiKey,
  });
}

export async function getSubmissionLineage(
  challengeId,
  submissionId,
  apiKey,
  options = {},
) {
  return get(`/api/v1/challenge/${challengeId}/submission/${submissionId}/lineage`, {
    baseUrl: options.baseUrl,
    apiKey,
  });
}

export function normalizeSubmissionPayload(payload = {}) {
  return {
    challenge_id: payload.challenge_id,
    node_id: payload.node_id,
    parent_submission_id: payload.parent_submission_id || null,
    status: payload.status,
    metric_value: payload.metric_value ?? null,
    title: payload.title || "",
    hypothesis: payload.hypothesis || "",
    description: payload.description || "",
    diff_summary: payload.diff_summary || "",
    runtime_sec: payload.runtime_sec ?? null,
    peak_vram_mb: payload.peak_vram_mb ?? null,
    num_steps: payload.num_steps ?? null,
    num_params: payload.num_params ?? null,
    agent_model: payload.agent_model || "",
    gpu_model: payload.gpu_model || "",
    metadata_jsonb: payload.metadata_jsonb || null,
  };
}
