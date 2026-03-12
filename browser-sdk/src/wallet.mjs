import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { post } from "./api.mjs";

export function normalizePrivateKey(value) {
  const trimmed = value.trim();
  return trimmed.startsWith("0x") ? trimmed : `0x${trimmed}`;
}

export function createBrowserWallet() {
  const privateKey = generatePrivateKey();
  const account = privateKeyToAccount(privateKey);
  return { privateKey, walletAddress: account.address };
}

export function importBrowserWallet(privateKey) {
  const normalized = normalizePrivateKey(privateKey);
  const account = privateKeyToAccount(normalized);
  return { privateKey: normalized, walletAddress: account.address };
}

export async function authenticateBrowserWallet(privateKey, options = {}) {
  const wallet = importBrowserWallet(privateKey);
  const challenge = await post("/api/v1/auth/wallet/challenge", {
    baseUrl: options.baseUrl,
    json: { wallet_address: wallet.walletAddress },
  });
  const account = privateKeyToAccount(wallet.privateKey);
  const signature = await account.signMessage({ message: challenge.message });
  const verified = await post("/api/v1/auth/wallet/verify", {
    baseUrl: options.baseUrl,
    json: {
      wallet_address: wallet.walletAddress,
      challenge_token: challenge.challenge_token,
      signature,
    },
  });
  return {
    apiKey: verified.api_key,
    operatorId: verified.operator_id,
    walletAddress: wallet.walletAddress,
    privateKey: wallet.privateKey,
  };
}
