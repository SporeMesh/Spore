import { createArtifact } from "./artifact.mjs";
import { getChallenge } from "./challenge.mjs";
import { createBrowserLLMClient } from "./llm.mjs";
import { heartbeatBrowserNode } from "./node.mjs";
import { createSubmission, normalizeSubmissionPayload } from "./submission.mjs";
import { createMemoryStore } from "./storage.mjs";

function nowIso() {
  return new Date().toISOString();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readState(store) {
  return store.load().run_state || {};
}

function writeState(store, patch) {
  const current = readState(store);
  return store.save({
    run_state: {
      ...current,
      ...patch,
      updated_at: nowIso(),
    },
  }).run_state;
}

function requireConfig(config) {
  if (!config.api_key) {
    throw new Error("missing api key; run init first");
  }
  if (!config.default_node_id) {
    throw new Error("missing node id; run init first");
  }
  if (!config.default_challenge_id) {
    throw new Error("missing challenge id; run init first");
  }
}

function normalizeResult(result, fallbackAgentModel) {
  const status = result?.status;
  if (!["keep", "discard", "crash"].includes(status)) {
    throw new Error("adapter must return status keep, discard, or crash");
  }
  return normalizeSubmissionPayload({
    ...result,
    agent_model: result?.agent_model || fallbackAgentModel || "",
  });
}

async function submitArtifacts(apiKey, submissionId, artifacts, baseUrl) {
  if (!Array.isArray(artifacts)) return [];
  const created = [];
  for (const artifact of artifacts) {
    created.push(
      await createArtifact(
        apiKey,
        {
          submission_id: submissionId,
          kind: artifact.kind || "other",
          storage_path: artifact.storage_path || "",
          content_type: artifact.content_type || "application/octet-stream",
          size_bytes: artifact.size_bytes ?? null,
          metadata_jsonb: artifact.metadata_jsonb || null,
        },
        { baseUrl },
      ),
    );
  }
  return created;
}

export function getBrowserClientStatus(options = {}) {
  const store = options.store || createMemoryStore();
  const config = store.load();
  return {
    config,
    run_state: readState(store),
  };
}

export function pauseBrowserClient(options = {}) {
  const store = options.store || createMemoryStore();
  return writeState(store, {
    paused: true,
    running: false,
  });
}

export async function runBrowserClient(options = {}) {
  const store = options.store || createMemoryStore();
  const config = store.load();
  requireConfig(config);
  if (!options.adapter || typeof options.adapter.runExperiment !== "function") {
    throw new Error("missing adapter.runExperiment");
  }
  const llm = createBrowserLLMClient(config, {
    provider: options.llmProvider,
    apiKey: options.llmApiKey,
    model: options.llmModel,
    baseUrl: options.llmBaseUrl,
  });
  const challenge = await getChallenge(
    options.challengeId || config.default_challenge_id,
    { baseUrl: options.baseUrl || config.base_url },
  );
  let state = writeState(store, {
    running: true,
    paused: false,
    last_error: "",
  });
  let context =
    typeof options.adapter.loadContext === "function"
      ? await options.adapter.loadContext({ challenge, config, llm })
      : undefined;
  const maxIterations = options.maxIterations ?? Number.POSITIVE_INFINITY;
  const intervalMs = options.intervalMs ?? 0;
  while (state.running && !state.paused && state.iteration < maxIterations) {
    if (options.signal?.aborted) {
      state = writeState(store, { running: false, paused: true });
      break;
    }
    const iteration = Number(state.iteration || 0) + 1;
    await heartbeatBrowserNode(config.api_key, {
      baseUrl: options.baseUrl || config.base_url,
      nodePublicId: config.default_node_public_id,
      metadataJsonb: { runtime: "browser", iteration },
    }).catch(() => null);
    try {
      const result = await options.adapter.runExperiment({
        challenge,
        config,
        llm,
        iteration,
        previousSubmissionId: state.last_submission_id || null,
        context,
        signal: options.signal,
      });
      context = result?.context ?? context;
      const payload = normalizeResult(result, llm.config.model);
      payload.challenge_id = challenge.id;
      payload.node_id = config.default_node_id;
      payload.parent_submission_id =
        payload.parent_submission_id || state.last_submission_id || null;
      const submission = await createSubmission(
        config.api_key,
        payload,
        { baseUrl: options.baseUrl || config.base_url },
      );
      await submitArtifacts(
        config.api_key,
        submission.id,
        result?.artifacts,
        options.baseUrl || config.base_url,
      );
      state = writeState(store, {
        running: true,
        paused: false,
        iteration,
        last_submission_id: submission.id || "",
        last_status: submission.status || payload.status,
        last_error: "",
      });
      if (typeof options.onEvent === "function") {
        options.onEvent({ type: "submission", submission, result, state });
      }
    } catch (error) {
      const crashPayload = normalizeSubmissionPayload({
        challenge_id: challenge.id,
        node_id: config.default_node_id,
        parent_submission_id: state.last_submission_id || null,
        status: "crash",
        title: "Browser run crashed",
        description: error?.message || String(error),
        agent_model: llm.config.model,
        metadata_jsonb: {
          runtime: "browser",
          error: error?.message || String(error),
        },
      });
      const submission = await createSubmission(
        config.api_key,
        crashPayload,
        { baseUrl: options.baseUrl || config.base_url },
      );
      state = writeState(store, {
        running: true,
        paused: false,
        iteration,
        last_submission_id: submission.id || "",
        last_status: "crash",
        last_error: error?.message || String(error),
      });
      if (typeof options.onEvent === "function") {
        options.onEvent({ type: "crash", error, submission, state });
      }
    }
    if (intervalMs > 0 && state.running && !state.paused) {
      await sleep(intervalMs);
    }
    state = readState(store);
  }
  if (!state.paused) {
    state = writeState(store, { running: false });
  }
  return getBrowserClientStatus({ store });
}
