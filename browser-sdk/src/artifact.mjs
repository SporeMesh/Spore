import { get, post } from "./api.mjs";

export async function createArtifact(apiKey, payload, options = {}) {
  return post("/api/v1/artifact", {
    baseUrl: options.baseUrl,
    apiKey,
    json: payload,
  });
}

export async function listArtifacts(submissionId, apiKey, options = {}) {
  return get(`/api/v1/submission/${submissionId}/artifact`, {
    baseUrl: options.baseUrl,
    apiKey,
  });
}
