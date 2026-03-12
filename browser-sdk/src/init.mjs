import { listChallenges, pickDefaultChallenge } from "./challenge.mjs";
import { registerBrowserNode } from "./node.mjs";
import {
  authenticateBrowserWallet,
  createBrowserWallet,
  importBrowserWallet,
} from "./wallet.mjs";
import { createMemoryStore } from "./storage.mjs";

export async function initBrowserClient(options = {}) {
  const store = options.store || createMemoryStore();
  const saved = store.load();
  const hasSavedKey = saved.private_key && !options.forceNewWallet;
  const wallet = options.privateKey
    ? importBrowserWallet(options.privateKey)
    : hasSavedKey
      ? importBrowserWallet(saved.private_key)
      : createBrowserWallet();
  const auth = await authenticateBrowserWallet(wallet.privateKey, {
    baseUrl: options.baseUrl || saved.base_url,
  });
  const challenges = await listChallenges({
    baseUrl: options.baseUrl || saved.base_url,
  });
  const selected =
    challenges.find((item) => item.id === options.challengeId) ||
    pickDefaultChallenge(challenges);
  const node = await registerBrowserNode(auth.apiKey, {
    baseUrl: options.baseUrl || saved.base_url,
    nodePublicId:
      options.nodePublicId || saved.default_node_public_id || undefined,
  });
  const config = store.save({
    base_url: options.baseUrl || saved.base_url || "https://api.sporemesh.com",
    api_key: auth.apiKey,
    operator_id: auth.operatorId,
    wallet_address: auth.walletAddress,
    private_key: auth.privateKey,
    llm_provider: options.llmProvider || saved.llm_provider || "groq",
    llm_api_key: options.llmApiKey || saved.llm_api_key || "",
    llm_model: options.llmModel || saved.llm_model || "",
    llm_base_url: options.llmBaseUrl || saved.llm_base_url || "",
    default_node_id: node.id || "",
    default_node_public_id: node.node_public_id || "",
    default_node_label: node.label || "",
    default_challenge_id: selected?.id || "",
    default_challenge_slug: selected?.slug || "",
  });
  return {
    config,
    node,
    challenge: selected || null,
    challenges,
    generatedPrivateKey: !options.privateKey && !hasSavedKey,
  };
}

export const bootstrapBrowserClient = initBrowserClient;
