#!/usr/bin/env node

import { run } from "../src/cli.mjs";

run(process.argv).catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
