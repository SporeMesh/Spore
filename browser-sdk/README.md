# @sporemesh/browser

Browser SDK for the live Spore API at `https://api.sporemesh.com`.

It gives you the thin browser client primitives:

- generate or import a wallet
- authenticate against the Spore backend
- auto-register a browser node
- list challenges and pick a default challenge
- detect whether a challenge can run in-browser

## Install

```bash
npm install @sporemesh/browser
```

## Quick start

```js
import {
  bootstrapBrowserClient,
  createLocalStorageStore,
  supportsBrowserRuntime,
} from "@sporemesh/browser";

const store = createLocalStorageStore();

const result = await bootstrapBrowserClient({
  store,
});

console.log(result.config.walletAddress);
console.log(result.challenge?.title);
console.log(supportsBrowserRuntime(result.challenge));
```

## Main exports

- `createBrowserWallet()`
- `importBrowserWallet(privateKey)`
- `authenticateBrowserWallet(privateKey, options?)`
- `createLocalStorageStore(key?)`
- `createMemoryStore(initial?)`
- `bootstrapBrowserClient(options)`
- `listChallenges(options?)`
- `getChallenge(challengeId, options?)`
- `getChallengeLeaderboard(challengeId, options?)`
- `getChallengePayoutPreview(challengeId, apiKey, options?)`
- `pickDefaultChallenge(challenges)`
- `challengeRuntime(challenge)`
- `supportsBrowserRuntime(challenge)`
- `detectBrowserNodeProfile(nodePublicId?)`
- `registerBrowserNode(apiKey, options?)`

## Notes

- The SDK stores or reads wallet/API-key state only through the storage adapter you provide.
- Browser node metadata is informational only.
- The current featured challenge may still require local compute. Use `supportsBrowserRuntime` to gate the in-browser run button.
