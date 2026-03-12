import { loadConfig } from "./config.mjs";

export class ApiError extends Error {}

export async function request(method, path, { auth = false, json, params, adminKey } = {}) {
  const config = await loadConfig();
  const url = new URL(path, config.base_url.endsWith("/") ? config.base_url : `${config.base_url}/`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  const headers = { accept: "application/json" };
  if (json) headers["content-type"] = "application/json";
  if (auth) {
    if (!config.api_key) throw new ApiError("missing API key; run `spore login --private-key ...`");
    headers["x-api-key"] = config.api_key;
  }
  if (adminKey) headers["x-admin-key"] = adminKey;
  const response = await fetch(url, {
    method,
    headers,
    body: json ? JSON.stringify(json) : undefined,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new ApiError(`${response.status} ${JSON.stringify(payload)}`);
  }
  return payload;
}
