import { listArtifacts } from "./artifact.mjs";
import {
  getChallenge,
  getChallengeLeaderboard,
  getChallengePayoutPreview,
  listChallenges,
} from "./challenge.mjs";
import { initBrowserClient } from "./init.mjs";
import { heartbeatBrowserNode, registerBrowserNode } from "./node.mjs";
import {
  getBrowserClientStatus,
  pauseBrowserClient,
  runBrowserClient,
} from "./run.mjs";
import {
  createSubmission,
  getSubmission,
  getSubmissionLineage,
  listSubmissions,
} from "./submission.mjs";
import { createMemoryStore } from "./storage.mjs";

export function createBrowserClient(options = {}) {
  const store = options.store || createMemoryStore();
  return {
    store,
    config() {
      return store.load();
    },
    status() {
      return getBrowserClientStatus({ store });
    },
    init(initOptions = {}) {
      return initBrowserClient({ store, ...initOptions });
    },
    pause() {
      return pauseBrowserClient({ store });
    },
    run(runOptions = {}) {
      return runBrowserClient({ store, ...runOptions });
    },
    listChallenges(queryOptions = {}) {
      const config = store.load();
      return listChallenges({
        baseUrl: queryOptions.baseUrl || config.base_url,
      });
    },
    getChallenge(challengeId, queryOptions = {}) {
      const config = store.load();
      return getChallenge(
        challengeId || config.default_challenge_id,
        { baseUrl: queryOptions.baseUrl || config.base_url },
      );
    },
    async useChallenge(challengeId, queryOptions = {}) {
      const config = store.load();
      const challenge = await getChallenge(challengeId, {
        baseUrl: queryOptions.baseUrl || config.base_url,
      });
      store.save({
        default_challenge_id: challenge.id || "",
        default_challenge_slug: challenge.slug || "",
      });
      return challenge;
    },
    getLeaderboard(challengeId, queryOptions = {}) {
      const config = store.load();
      return getChallengeLeaderboard(
        challengeId || config.default_challenge_id,
        { baseUrl: queryOptions.baseUrl || config.base_url },
      );
    },
    getPayoutPreview(challengeId, queryOptions = {}) {
      const config = store.load();
      return getChallengePayoutPreview(
        challengeId || config.default_challenge_id,
        queryOptions.apiKey || config.api_key,
        { baseUrl: queryOptions.baseUrl || config.base_url },
      );
    },
    registerNode(nodeOptions = {}) {
      const config = store.load();
      return registerBrowserNode(config.api_key, {
        baseUrl: nodeOptions.baseUrl || config.base_url,
        ...nodeOptions,
      });
    },
    heartbeat(nodeOptions = {}) {
      const config = store.load();
      return heartbeatBrowserNode(config.api_key, {
        baseUrl: nodeOptions.baseUrl || config.base_url,
        nodePublicId: nodeOptions.nodePublicId || config.default_node_public_id,
        metadataJsonb: nodeOptions.metadataJsonb,
      });
    },
    createSubmission(payload, submitOptions = {}) {
      const config = store.load();
      return createSubmission(config.api_key, payload, {
        baseUrl: submitOptions.baseUrl || config.base_url,
      });
    },
    listSubmissions(challengeId, submitOptions = {}) {
      const config = store.load();
      return listSubmissions(
        challengeId || config.default_challenge_id,
        config.api_key,
        { baseUrl: submitOptions.baseUrl || config.base_url },
      );
    },
    getSubmission(submissionId, submitOptions = {}) {
      const config = store.load();
      return getSubmission(submissionId, config.api_key, {
        baseUrl: submitOptions.baseUrl || config.base_url,
      });
    },
    getLineage(challengeId, submissionId, submitOptions = {}) {
      const config = store.load();
      return getSubmissionLineage(
        challengeId || config.default_challenge_id,
        submissionId,
        config.api_key,
        { baseUrl: submitOptions.baseUrl || config.base_url },
      );
    },
    listArtifacts(submissionId, artifactOptions = {}) {
      const config = store.load();
      return listArtifacts(submissionId, config.api_key, {
        baseUrl: artifactOptions.baseUrl || config.base_url,
      });
    },
  };
}
