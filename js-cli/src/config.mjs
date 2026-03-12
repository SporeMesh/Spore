import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

const CONFIG_DIR = join(homedir(), ".spore");
const CONFIG_PATH = join(CONFIG_DIR, "client.json");

export function defaultConfig() {
  return {
    base_url: process.env.SPORE_API_URL || "https://api.sporemesh.com",
    api_key: "",
    operator_id: "",
    wallet_address: "",
    private_key: "",
    llm_provider: "",
    llm_model: "",
    default_node_id: "",
    default_node_public_id: "",
    default_challenge_id: "",
    default_challenge_slug: "",
  };
}

export async function loadConfig() {
  try {
    const text = await readFile(CONFIG_PATH, "utf8");
    return { ...defaultConfig(), ...JSON.parse(text) };
  } catch {
    return defaultConfig();
  }
}

export async function saveConfig(config) {
  await mkdir(CONFIG_DIR, { recursive: true });
  await writeFile(CONFIG_PATH, `${JSON.stringify(config, null, 2)}\n`);
  return config;
}

export async function updateConfig(values) {
  const config = await loadConfig();
  return saveConfig({ ...config, ...values });
}
