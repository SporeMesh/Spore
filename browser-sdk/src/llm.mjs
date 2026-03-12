const PROVIDERS = {
  anthropic: {
    baseUrl: "https://api.anthropic.com/v1",
    model: "claude-sonnet-4-5-20250929",
  },
  openai: {
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4o",
  },
  groq: {
    baseUrl: "https://api.groq.com/openai/v1",
    model: "moonshotai/kimi-k2-instruct-0905",
  },
  xai: {
    baseUrl: "https://api.x.ai/v1",
    model: "grok-3",
  },
};

export function resolveLLMConfig(config = {}, overrides = {}) {
  const provider = overrides.provider || config.llm_provider || "groq";
  const providerConfig = PROVIDERS[provider] || {};
  return {
    provider,
    apiKey: overrides.apiKey || config.llm_api_key || "",
    model: overrides.model || config.llm_model || providerConfig.model || "",
    baseUrl:
      (overrides.baseUrl || config.llm_base_url || providerConfig.baseUrl || "").replace(
        /\/+$/,
        "",
      ),
  };
}

async function chatOpenAICompatible(config, system, user) {
  const response = await fetch(`${config.baseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${config.apiKey}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: config.model,
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
    }),
  });
  if (!response.ok) {
    throw new Error(`LLM error ${response.status}: ${await response.text()}`);
  }
  const payload = await response.json();
  return payload?.choices?.[0]?.message?.content || "";
}

async function chatAnthropic(config, system, user) {
  const response = await fetch(`${config.baseUrl}/messages`, {
    method: "POST",
    headers: {
      "x-api-key": config.apiKey,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: config.model,
      system,
      messages: [{ role: "user", content: user }],
      max_tokens: 4096,
    }),
  });
  if (!response.ok) {
    throw new Error(`LLM error ${response.status}: ${await response.text()}`);
  }
  const payload = await response.json();
  return (payload?.content || [])
    .filter((block) => block.type === "text")
    .map((block) => block.text)
    .join("");
}

export function createBrowserLLMClient(config = {}, overrides = {}) {
  const resolved = resolveLLMConfig(config, overrides);
  if (!resolved.apiKey) {
    throw new Error("missing llm api key; run init with llm settings first");
  }
  if (!resolved.baseUrl || !resolved.model) {
    throw new Error("incomplete llm configuration");
  }
  return {
    config: resolved,
    async chat(system, user) {
      if (resolved.provider === "anthropic") {
        return chatAnthropic(resolved, system, user);
      }
      return chatOpenAICompatible(resolved, system, user);
    },
  };
}
