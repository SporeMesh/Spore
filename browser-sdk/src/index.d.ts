export type ChallengeStatus = "draft" | "scheduled" | "active" | "closed" | "paid";
export type SubmissionStatus = "keep" | "discard" | "crash";

export interface Challenge {
  id: string;
  slug: string;
  title: string;
  description: string;
  metric: string;
  goal: "minimize" | "maximize";
  status: ChallengeStatus;
  start_at: string;
  end_at: string;
  prize_pool: number;
  rule_jsonb?: Record<string, any> | null;
  evaluator_jsonb?: Record<string, any> | null;
}

export interface BrowserConfig {
  base_url?: string;
  api_key?: string;
  operator_id?: string;
  wallet_address?: string;
  private_key?: string;
  default_node_id?: string;
  default_node_public_id?: string;
  default_challenge_id?: string;
  default_challenge_slug?: string;
  llm_provider?: string;
  llm_api_key?: string;
  llm_model?: string;
  [key: string]: any;
}

export interface BrowserRunState {
  running?: boolean;
  paused?: boolean;
  iteration?: number;
  last_submission_id?: string;
  last_status?: SubmissionStatus;
  last_error?: string;
  updated_at?: string;
  [key: string]: any;
}

export interface BrowserStatus {
  config: BrowserConfig;
  run_state: BrowserRunState;
}

export interface BrowserStore {
  load(): BrowserConfig;
  save(patch: Partial<BrowserConfig> & { run_state?: BrowserRunState }): BrowserConfig;
  clear(): void;
}

export interface BrowserClientInitOptions {
  privateKey?: string;
  challengeId?: string;
  forceNewWallet?: boolean;
  llmProvider?: string;
  llmApiKey?: string;
  llmModel?: string;
  baseUrl?: string;
}

export interface BrowserExperimentResult {
  status: SubmissionStatus;
  title?: string;
  hypothesis?: string;
  description?: string;
  diff_summary?: string;
  metric_value?: number | null;
  parent_submission_id?: string | null;
  runtime_sec?: number | null;
  peak_vram_mb?: number | null;
  num_steps?: number | null;
  num_params?: number | null;
  agent_model?: string;
  gpu_model?: string;
  metadata_jsonb?: Record<string, any> | null;
  artifacts?: Array<Record<string, any>>;
  context?: any;
}

export interface BrowserAdapterContext {
  challenge: Challenge;
  config: BrowserConfig;
  llm: any;
  iteration?: number;
  previousSubmissionId?: string | null;
  context?: any;
  signal?: AbortSignal;
}

export interface BrowserAdapter {
  loadContext?(ctx: BrowserAdapterContext): Promise<any>;
  runExperiment(ctx: BrowserAdapterContext): Promise<BrowserExperimentResult>;
}

export interface BrowserRunOptions {
  intervalMs?: number;
  maxIterations?: number;
  challengeId?: string;
  llmProvider?: string;
  llmApiKey?: string;
  llmModel?: string;
  llmBaseUrl?: string;
  baseUrl?: string;
  signal?: AbortSignal;
  adapter: BrowserAdapter;
  onEvent?(event: any): void;
}

export interface BrowserClient {
  store: BrowserStore;
  init(options?: BrowserClientInitOptions): Promise<any>;
  run(options: BrowserRunOptions): Promise<BrowserStatus>;
  pause(): BrowserRunState;
  status(): BrowserStatus;
  useChallenge(challengeId: string): Promise<any>;
}

export interface LocalStorageStoreOptions {
  key?: string;
}

export interface VixDatasetSummary {
  labels: readonly string[];
  public_train_rows: number;
  public_eval_rows: number;
}

export function createMemoryStore(initial?: BrowserConfig): BrowserStore;
export function createLocalStorageStore(key?: string): BrowserStore;
export function createBrowserWallet(): { privateKey: string; walletAddress: string };
export function importBrowserWallet(privateKey: string): { privateKey: string; walletAddress: string };
export function authenticateBrowserWallet(privateKey: string, options?: { baseUrl?: string }): Promise<any>;
export function createBrowserLLMClient(config?: BrowserConfig, overrides?: Record<string, any>): any;
export function initBrowserClient(options?: BrowserClientInitOptions & { store?: BrowserStore }): Promise<any>;
export function bootstrapBrowserClient(options?: BrowserClientInitOptions & { store?: BrowserStore }): Promise<any>;
export function createBrowserClient(options?: { store?: BrowserStore }): BrowserClient;
export function listChallenges(options?: { baseUrl?: string }): Promise<Challenge[]>;
export function getChallenge(challengeId: string, options?: { baseUrl?: string }): Promise<Challenge>;
export function getChallengeLeaderboard(challengeId: string, options?: { baseUrl?: string }): Promise<any[]>;
export function getChallengePayoutPreview(challengeId: string, apiKey: string, options?: { baseUrl?: string }): Promise<any>;
export function pickDefaultChallenge(challenges: Challenge[]): Challenge | null;
export function challengeRuntime(challenge: Challenge | null | undefined): string;
export function supportsBrowserRuntime(challenge: Challenge | null | undefined): boolean;
export function createSubmission(apiKey: string, payload: Record<string, any>, options?: { baseUrl?: string }): Promise<any>;
export function listSubmissions(challengeId: string, apiKey: string, options?: { baseUrl?: string }): Promise<any[]>;
export function getSubmission(submissionId: string, apiKey: string, options?: { baseUrl?: string }): Promise<any>;
export function getSubmissionLineage(challengeId: string, submissionId: string, apiKey: string, options?: { baseUrl?: string }): Promise<any[]>;
export function createArtifact(apiKey: string, payload: Record<string, any>, options?: { baseUrl?: string }): Promise<any>;
export function listArtifacts(submissionId: string, apiKey: string, options?: { baseUrl?: string }): Promise<any[]>;
export function runBrowserClient(options: BrowserRunOptions & { store?: BrowserStore }): Promise<BrowserStatus>;
export function pauseBrowserClient(options?: { store?: BrowserStore }): BrowserRunState;
export function getBrowserClientStatus(options?: { store?: BrowserStore }): BrowserStatus;
export const baselineClassifierSource: string;
export function createVixRegimeAdapter(options?: { initialSource?: string }): BrowserAdapter;
export function loadClassifier(source: string): Promise<(row: Record<string, any>) => Record<string, number>>;
export function logLoss(dataset: Array<Record<string, any>>, predict: (row: Record<string, any>) => Record<string, number>): number;
export function scoreClassifierSource(source: string, dataset?: Array<Record<string, any>>): Promise<number>;
export function vixDatasetSummary(): VixDatasetSummary;
export const VIX_LABELS: readonly string[];
export const VIX_PUBLIC_EVAL: Array<Record<string, any>>;
export const VIX_PUBLIC_TRAIN: Array<Record<string, any>>;
