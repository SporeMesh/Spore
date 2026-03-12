import { randomUUID } from "node:crypto";
import { hostname } from "node:os";
import { readFile } from "node:fs/promises";
import { Command } from "commander";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { ApiError, request } from "./api.mjs";
import { loadConfig, saveConfig, updateConfig } from "./config.mjs";
import { pickDefaultChallenge } from "./challenge.mjs";
import { detectNodeProfile } from "./detect.mjs";

async function parseJson(text, file) {
  if (text) return JSON.parse(text);
  if (file) return JSON.parse(await readFile(file, "utf8"));
  return null;
}

function print(data) {
  console.log(JSON.stringify(data, null, 2));
}

function defaultNodePublicId() {
  return `${hostname().split(".")[0]}-${randomUUID().replace(/-/g, "").slice(0, 8)}`;
}

async function login(privateKey, baseUrl) {
  if (baseUrl) await updateConfig({ base_url: baseUrl });
  const normalized = privateKey.startsWith("0x") ? privateKey : `0x${privateKey}`;
  const account = privateKeyToAccount(normalized);
  const challenge = await request("POST", "/api/v1/auth/wallet/challenge", {
    json: { wallet_address: account.address },
  });
  const signature = await account.signMessage({ message: challenge.message });
  const verified = await request("POST", "/api/v1/auth/wallet/verify", {
    json: {
      wallet_address: account.address,
      challenge_token: challenge.challenge_token,
      signature,
    },
  });
  const config = await loadConfig();
  await saveConfig({
    ...config,
    base_url: baseUrl || config.base_url,
    api_key: verified.api_key,
    operator_id: verified.operator_id,
    wallet_address: account.address,
    private_key: normalized,
  });
  print({ wallet_address: account.address, ...verified });
}

async function initClient({ privateKey, baseUrl, nodePublicId, label, challengeId, forceNewWallet }) {
  const llmProvider = arguments[0].llmProvider || "groq";
  const llmApiKey =
    arguments[0].llmApiKey ||
    process.env.SPORE_LLM_API_KEY ||
    process.env.GROQ_API_KEY ||
    process.env.ANTHROPIC_API_KEY ||
    process.env.OPENAI_API_KEY ||
    process.env.XAI_API_KEY ||
    "";
  const llmModel = arguments[0].llmModel || "";
  const config = await loadConfig();
  const generated = !privateKey && (forceNewWallet || !config.private_key);
  const resolvedPrivateKey =
    privateKey || (!forceNewWallet ? config.private_key : "") || generatePrivateKey();
  const normalized = resolvedPrivateKey.startsWith("0x")
    ? resolvedPrivateKey
    : `0x${resolvedPrivateKey}`;
  await login(normalized, baseUrl);
  const detected = await detectNodeProfile();
  const payload = {
    node_public_id: nodePublicId || config.default_node_public_id || defaultNodePublicId(),
    label: label || detected.label,
    gpu_model: detected.gpu_model || null,
    cpu_model: detected.cpu_model || null,
    memory_gb: detected.memory_gb || null,
    platform: detected.platform || null,
    software_version: "0.6.2",
    metadata_jsonb: detected.metadata_jsonb,
  };
  const node = await request("POST", "/api/v1/node/register", { auth: true, json: payload });
  const challenges = await request("GET", "/api/v1/challenge");
  const selected = challenges.find((item) => item.id === challengeId) || pickDefaultChallenge(challenges);
  await updateConfig({
    private_key: normalized,
    llm_provider: llmApiKey ? llmProvider : "",
    llm_model: llmModel,
    default_node_id: node.id || "",
    default_node_public_id: payload.node_public_id,
    default_challenge_id: selected?.id || "",
    default_challenge_slug: selected?.slug || "",
  });
  print({
    generated_private_key: generated,
    wallet_address: (await loadConfig()).wallet_address,
    operator_id: (await loadConfig()).operator_id,
    llm_provider: llmApiKey ? llmProvider : "",
    llm_configured: Boolean(llmApiKey),
    node,
    challenge: selected || null,
  });
}

export async function run(argv) {
  const program = new Command();
  program.name("spore").description("Spore CLI for the centralized backend");

  program
    .command("login")
    .requiredOption("--private-key <key>", "Ethereum private key")
    .option("--base-url <url>", "Override backend URL")
    .action(async ({ privateKey, baseUrl }) => login(privateKey, baseUrl));

  program
    .command("init")
    .option("--private-key <key>", "Ethereum private key")
    .option("--base-url <url>", "Override backend URL")
    .option("--node-public-id <id>", "Stable public node ID")
    .option("--label <label>", "Human-readable node label")
    .option("--challenge-id <id>", "Pin a default challenge instead of auto-selecting")
    .option("--force-new-wallet", "Generate and save a fresh local wallet")
    .option("--llm-provider <name>", "LLM provider for local autoresearch", "groq")
    .option("--llm-api-key <key>", "LLM API key for local autoresearch")
    .option("--llm-model <name>", "Optional LLM model override")
    .action(async (options) => initClient(options));

  program.command("logout").action(async () => {
    const config = await loadConfig();
    await saveConfig({ ...config, api_key: "" });
    print({ ok: true });
  });

  const configCmd = program.command("config");
  configCmd.command("show").action(async () => print(await loadConfig()));
  configCmd.command("set-base-url").argument("<url>").action(async (url) => print(await updateConfig({ base_url: url })));

  program.command("whoami").action(async () => print(await request("GET", "/api/v1/operator/me", { auth: true })));

  const challenge = program.command("challenge");
  challenge.command("list").action(async () => print(await request("GET", "/api/v1/challenge")));
  challenge.command("show").argument("[challengeId]").action(async (challengeId) => {
    const config = await loadConfig();
    const resolved = challengeId || config.default_challenge_id;
    if (!resolved) throw new ApiError("missing challenge_id; run `spore init` or pass a challenge id");
    print(await request("GET", `/api/v1/challenge/${resolved}`));
  });
  challenge.command("leaderboard").argument("[challengeId]").action(async (challengeId) => {
    const config = await loadConfig();
    const resolved = challengeId || config.default_challenge_id;
    if (!resolved) throw new ApiError("missing challenge_id; run `spore init` or pass a challenge id");
    print(await request("GET", `/api/v1/challenge/${resolved}/leaderboard`));
  });
  challenge.command("payout-preview").argument("[challengeId]").action(async (challengeId) => {
    const config = await loadConfig();
    const resolved = challengeId || config.default_challenge_id;
    if (!resolved) throw new ApiError("missing challenge_id; run `spore init` or pass a challenge id");
    print(await request("GET", `/api/v1/challenge/${resolved}/payout-preview`, { auth: true }));
  });
  challenge.command("use").argument("<challengeId>").action(async (challengeId) => {
    const challengeData = await request("GET", `/api/v1/challenge/${challengeId}`);
    print(await updateConfig({ default_challenge_id: challengeData.id, default_challenge_slug: challengeData.slug || "" }));
  });

  const node = program.command("node");
  node
    .command("register")
    .option("--node-public-id <id>")
    .option("--label <label>", "")
    .option("--gpu-model <gpu>", "")
    .option("--cpu-model <cpu>", "")
    .option("--memory-gb <n>")
    .option("--platform <platform>", "")
    .option("--software-version <version>", "0.1.0")
    .option("--metadata <json>")
    .option("--metadata-file <path>")
    .action(async (options) => {
      const detected = await detectNodeProfile();
      const payload = {
        node_public_id: options.nodePublicId || defaultNodePublicId(),
        label: options.label || detected.label,
        gpu_model: options.gpuModel || detected.gpu_model || null,
        cpu_model: options.cpuModel || detected.cpu_model || null,
        memory_gb: options.memoryGb ? Number(options.memoryGb) : detected.memory_gb || null,
        platform: options.platform || detected.platform || null,
        software_version: options.softwareVersion || null,
        metadata_jsonb: await parseJson(options.metadata, options.metadataFile) || detected.metadata_jsonb,
      };
      const result = await request("POST", "/api/v1/node/register", { auth: true, json: payload });
      await updateConfig({ default_node_id: result.id || "", default_node_public_id: payload.node_public_id });
      print(result);
    });
  node
    .command("heartbeat")
    .option("--node-public-id <id>")
    .option("--metadata <json>")
    .option("--metadata-file <path>")
    .action(async (options) => {
      const config = await loadConfig();
      print(await request("POST", "/api/v1/node/heartbeat", {
        auth: true,
        json: {
          node_public_id: options.nodePublicId || config.default_node_public_id || defaultNodePublicId(),
          metadata_jsonb: await parseJson(options.metadata, options.metadataFile),
        },
      }));
    });
  node.command("me").action(async () => print(await request("GET", "/api/v1/node/me", { auth: true })));

  const submission = program.command("submission");
  submission
    .command("create")
    .option("--challenge-id <id>")
    .requiredOption("--status <status>")
    .option("--node-id <id>")
    .option("--parent-submission-id <id>")
    .option("--metric-value <value>")
    .option("--title <title>", "")
    .option("--hypothesis <text>", "")
    .option("--description <text>", "")
    .option("--diff-summary <text>", "")
    .option("--runtime-sec <n>")
    .option("--peak-vram-mb <n>")
    .option("--num-steps <n>")
    .option("--num-params <n>")
    .option("--agent-model <text>", "")
    .option("--gpu-model <text>", "")
    .option("--metadata <json>")
    .option("--metadata-file <path>")
    .action(async (options) => {
      const config = await loadConfig();
      const payload = {
        challenge_id: options.challengeId || config.default_challenge_id,
        node_id: options.nodeId || config.default_node_id,
        parent_submission_id: options.parentSubmissionId || null,
        status: options.status || null,
        metric_value: options.metricValue ? Number(options.metricValue) : null,
        title: options.title,
        hypothesis: options.hypothesis,
        description: options.description,
        diff_summary: options.diffSummary,
        runtime_sec: options.runtimeSec ? Number(options.runtimeSec) : null,
        peak_vram_mb: options.peakVramMb ? Number(options.peakVramMb) : null,
        num_steps: options.numSteps ? Number(options.numSteps) : null,
        num_params: options.numParams ? Number(options.numParams) : null,
        agent_model: options.agentModel,
        gpu_model: options.gpuModel,
        metadata_jsonb: await parseJson(options.metadata, options.metadataFile),
      };
      if (!payload.challenge_id) throw new ApiError("missing challenge_id; run `spore init` or pass --challenge-id");
      if (!payload.node_id) throw new ApiError("missing node_id; run `spore node register` first or pass --node-id");
      print(await request("POST", "/api/v1/submission", { auth: true, json: payload }));
    });
  submission.command("list").argument("[challengeId]").action(async (challengeId) => {
    const config = await loadConfig();
    const resolved = challengeId || config.default_challenge_id;
    if (!resolved) throw new ApiError("missing challenge_id; run `spore init` or pass a challenge id");
    print(await request("GET", `/api/v1/challenge/${resolved}/submission`, { auth: true }));
  });
  submission.command("show").argument("<submissionId>").action(async (submissionId) => print(await request("GET", `/api/v1/submission/${submissionId}`, { auth: true })));
  submission.command("lineage").argument("<challengeId>").argument("<submissionId>").action(async (challengeId, submissionId) => print(await request("GET", `/api/v1/challenge/${challengeId}/submission/${submissionId}/lineage`, { auth: true })));

  const artifact = program.command("artifact");
  artifact
    .command("create")
    .requiredOption("--submission-id <id>")
    .requiredOption("--kind <kind>")
    .requiredOption("--filename <name>")
    .option("--content-type <type>")
    .option("--size-bytes <n>")
    .option("--metadata <json>")
    .option("--metadata-file <path>")
    .action(async (options) => {
      print(await request("POST", "/api/v1/artifact", {
        auth: true,
        json: {
          submission_id: options.submissionId,
          kind: options.kind,
          filename: options.filename,
          content_type: options.contentType || null,
          size_bytes: options.sizeBytes ? Number(options.sizeBytes) : null,
          metadata_jsonb: await parseJson(options.metadata, options.metadataFile),
        },
      }));
    });
  artifact.command("list").argument("<submissionId>").action(async (submissionId) => print(await request("GET", `/api/v1/submission/${submissionId}/artifact`, { auth: true })));

  const payout = program.command("payout");
  payout.command("me").action(async () => print(await request("GET", "/api/v1/operator/me/payout", { auth: true })));
  payout.command("challenge").argument("<challengeId>").action(async (challengeId) => print(await request("GET", `/api/v1/challenge/${challengeId}/payout`, { auth: true })));

  await program.parseAsync(argv);
}
