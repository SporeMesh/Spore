const DEFAULT_BASE_URL = "https://api.sporemesh.com";

export function resolveBaseUrl(baseUrl) {
  return (baseUrl || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

async function request(method, path, { baseUrl, apiKey, json } = {}) {
  const res = await fetch(`${resolveBaseUrl(baseUrl)}${path}`, {
    method,
    headers: {
      ...(json ? { "content-type": "application/json" } : {}),
      ...(apiKey ? { "x-api-key": apiKey } : {}),
    },
    body: json ? JSON.stringify(json) : undefined,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Spore API error ${res.status}${body ? `: ${body}` : ""}`);
  }
  return res.json();
}

export function get(path, options) {
  return request("GET", path, options);
}

export function post(path, options) {
  return request("POST", path, options);
}
