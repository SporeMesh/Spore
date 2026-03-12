const DEFAULT_CONFIG = {
  base_url: "https://api.sporemesh.com",
  api_key: "",
  operator_id: "",
  wallet_address: "",
  private_key: "",
  llm_provider: "",
  llm_api_key: "",
  llm_model: "",
  llm_base_url: "",
  default_node_id: "",
  default_node_public_id: "",
  default_node_label: "",
  default_challenge_id: "",
  default_challenge_slug: "",
  run_state: {
    running: false,
    paused: false,
    iteration: 0,
    last_submission_id: "",
    last_status: "",
    last_error: "",
    updated_at: "",
  },
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
