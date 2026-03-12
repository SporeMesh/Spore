const DEFAULT_CONFIG = {
  baseUrl: "https://api.sporemesh.com",
  apiKey: "",
  operatorId: "",
  walletAddress: "",
  privateKey: "",
  nodeId: "",
  nodePublicId: "",
  nodeLabel: "",
  challengeId: "",
  challengeSlug: "",
};

export function createMemoryStore(initial = {}) {
  let state = { ...DEFAULT_CONFIG, ...initial };
  return {
    load() {
      return { ...state };
    },
    save(patch) {
      state = { ...state, ...patch };
      return { ...state };
    },
    clear() {
      state = { ...DEFAULT_CONFIG };
      return { ...state };
    },
  };
}

export function createLocalStorageStore(key = "spore-browser-client") {
  return {
    load() {
      if (typeof window === "undefined") return { ...DEFAULT_CONFIG };
      try {
        const raw = window.localStorage.getItem(key);
        return raw ? { ...DEFAULT_CONFIG, ...JSON.parse(raw) } : { ...DEFAULT_CONFIG };
      } catch {
        return { ...DEFAULT_CONFIG };
      }
    },
    save(patch) {
      const next = { ...this.load(), ...patch };
      if (typeof window !== "undefined") {
        window.localStorage.setItem(key, JSON.stringify(next));
      }
      return next;
    },
    clear() {
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(key);
      }
      return { ...DEFAULT_CONFIG };
    },
  };
}
