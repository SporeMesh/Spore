import { listChallenges, pickDefaultChallenge } from "./challenge.mjs";
import { registerBrowserNode } from "./node.mjs";
import {
  authenticateBrowserWallet,
  createBrowserWallet,
  importBrowserWallet,
} from "./wallet.mjs";
import { createMemoryStore } from "./storage.mjs";

export async function bootstrapBrowserClient(options = {}) {
  const store = options.store || createMemoryStore();
  const saved = store.load();
  const hasSavedKey = saved.privateKey && !options.forceNewWallet;
  const wallet = options.privateKey
    ? importBrowserWallet(options.privateKey)
    : hasSavedKey
    ? importBrowserWallet(saved.privateKey)
    : createBrowserWallet();
  const auth = await authenticateBrowserWallet(wallet.privateKey, {
    baseUrl: options.baseUrl || saved.baseUrl,
  });
  const challenges = await listChallenges({
    baseUrl: options.baseUrl || saved.baseUrl,
  });
  const selected =
    challenges.find((item) => item.id === options.challengeId) ||
    pickDefaultChallenge(challenges);
  const node = await registerBrowserNode(auth.apiKey, {
    baseUrl: options.baseUrl || saved.baseUrl,
    nodePublicId: options.nodePublicId || saved.nodePublicId || undefined,
  });
  const config = store.save({
    baseUrl: options.baseUrl || saved.baseUrl || "https://api.sporemesh.com",
    apiKey: auth.apiKey,
    operatorId: auth.operatorId,
    walletAddress: auth.walletAddress,
    privateKey: auth.privateKey,
    nodeId: node.id || "",
    nodePublicId: node.node_public_id || "",
    nodeLabel: node.label || "",
    challengeId: selected?.id || "",
    challengeSlug: selected?.slug || "",
  });
  return {
    config,
    node,
    challenge: selected || null,
    challenges,
    generatedPrivateKey: !options.privateKey && !hasSavedKey,
  };
}
