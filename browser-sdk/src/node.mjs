import { post } from "./api.mjs";

export function createNodePublicId(prefix = "browser") {
  return `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
}

export function detectBrowserNodeProfile(nodePublicId = createNodePublicId()) {
  const navigatorInfo = typeof navigator === "undefined" ? null : navigator;
  const deviceMemory = Number(navigatorInfo?.deviceMemory || 0);
  const hardwareConcurrency = navigatorInfo?.hardwareConcurrency || 0;
  return {
    node_public_id: nodePublicId,
    label: "Browser node",
    gpu_model: "Browser/WebGPU",
    cpu_model: navigatorInfo?.userAgent || "browser",
    memory_gb: deviceMemory || null,
    platform: navigatorInfo
      ? [navigatorInfo.platform, navigatorInfo.userAgent].filter(Boolean).join(" / ")
      : "browser",
    software_version: "browser-beta",
    metadata_jsonb: {
      runtime: "browser",
      hardware_concurrency: hardwareConcurrency || null,
      user_agent: navigatorInfo?.userAgent || "",
      language: navigatorInfo?.language || "",
    },
  };
}

export async function registerBrowserNode(apiKey, options = {}) {
  const payload =
    options.payload || detectBrowserNodeProfile(options.nodePublicId || undefined);
  return post("/api/v1/node/register", {
    baseUrl: options.baseUrl,
    apiKey,
    json: payload,
  });
}
