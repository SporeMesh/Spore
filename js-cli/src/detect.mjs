import { hostname, machine, platform, totalmem } from "node:os";
import process from "node:process";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

async function run(command, args) {
  try {
    const result = await execFileAsync(command, args, { timeout: 2000 });
    return result.stdout.trim();
  } catch {
    return "";
  }
}

async function detectGpuModel() {
  const nvidia = await run("nvidia-smi", ["--query-gpu=name", "--format=csv,noheader"]);
  if (nvidia) return nvidia.split("\n")[0].trim();
  return "";
}

export async function detectNodeProfile() {
  const host = hostname().split(".")[0];
  return {
    label: host,
    gpu_model: await detectGpuModel(),
    cpu_model: machine(),
    memory_gb: Math.max(1, Math.round(totalmem() / (1024 ** 3))),
    platform: `${platform()}-${process.arch}`,
    metadata_jsonb: {
      hostname: host,
      node_version: process.version,
      platform: process.platform,
      arch: process.arch,
    },
  };
}
