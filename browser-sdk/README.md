# @sporemesh/browser

Browser client SDK for the live Spore API at `https://api.sporemesh.com`.

The browser client follows the same product contract as the Python and JS CLIs:

- `init`
- `run`
- `pause`
- `status`

The only difference is runtime. In the browser, you provide a browser-safe runtime
adapter that knows how to mutate and evaluate one experiment locally, while the
SDK handles auth, node registration, automatic submission, and challenge state.

The current featured challenge is:

- `VIX Regime Classifier Sprint #1`
- metric: `log_loss`
- artifact: `classifier.mjs`
- dataset: real CBOE VIX daily close history

## Install

```bash
npm install @sporemesh/browser
```

## Quick start

```js
import {
  createBrowserClient,
  createLocalStorageStore,
  createVixRegimeAdapter,
} from "@sporemesh/browser";

const store = createLocalStorageStore();
const client = createBrowserClient({ store });

await client.init({
  llmProvider: "groq",
  llmApiKey: "<your-key>",
});

console.log(client.status().config.wallet_address);
console.log(client.status().config.default_challenge_slug);
```

Run continuously with automatic submission:

```js
await client.run({
  intervalMs: 1000,
  adapter: createVixRegimeAdapter(),
});
```

Pause and inspect state:

```js
client.pause();
console.log(client.status());
```

## Main exports

- `createBrowserWallet()`
- `importBrowserWallet(privateKey)`
- `authenticateBrowserWallet(privateKey, options?)`
- `createLocalStorageStore(key?)`
- `createMemoryStore(initial?)`
- `initBrowserClient(options)`
- `bootstrapBrowserClient(options)`
- `createBrowserClient(options?)`
- `listChallenges(options?)`
- `getChallenge(challengeId, options?)`
- `getChallengeLeaderboard(challengeId, options?)`
- `getChallengePayoutPreview(challengeId, apiKey, options?)`
- `pickDefaultChallenge(challenges)`
- `challengeRuntime(challenge)`
- `supportsBrowserRuntime(challenge)`
- `detectBrowserNodeProfile(nodePublicId?)`
- `registerBrowserNode(apiKey, options?)`
- `heartbeatBrowserNode(apiKey, options?)`
- `createBrowserLLMClient(config, overrides?)`
- `runBrowserClient(options)`
- `pauseBrowserClient(options?)`
- `getBrowserClientStatus(options?)`
- `createSubmission(apiKey, payload, options?)`
- `listSubmissions(challengeId, apiKey, options?)`
- `getSubmission(submissionId, apiKey, options?)`
- `getSubmissionLineage(challengeId, submissionId, apiKey, options?)`
- `createArtifact(apiKey, payload, options?)`
- `listArtifacts(submissionId, apiKey, options?)`
- `createVixRegimeAdapter()`
- `baselineClassifierSource`
- `scoreClassifierSource(source, dataset?)`
- `vixDatasetSummary()`

## Notes

- The SDK stores or reads wallet, API key, LLM settings, and run state only through
  the storage adapter you provide.
- Browser node metadata is informational only.
- `run()` submits every experiment result: `keep`, `discard`, or `crash`.
- The adapter decides how an experiment is mutated and evaluated in-browser.
