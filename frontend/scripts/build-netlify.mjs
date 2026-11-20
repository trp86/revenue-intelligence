// npm run build:netlify -- https://<name>.up.railway.app   (story #193)
// Builds the app with a relative API address (/api/v1) and writes dist/_redirects, so the
// dist folder can be dragged onto https://app.netlify.com/drop as it is.
import { spawnSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { redirects } from "./netlify.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
let rules;
try {
  rules = redirects(process.argv[2]);
} catch (error) {
  console.error(error.message);
  process.exit(2);
}
const build = spawnSync("npm", ["run", "build"], {
  cwd: root,
  stdio: "inherit",
  shell: true,
  env: { ...process.env, VITE_API_BASE: "/api/v1" },
});
if (build.status !== 0) process.exit(build.status ?? 1);
writeFileSync(join(root, "dist", "_redirects"), rules, "utf-8");
console.log("dist/ is ready: drag it onto https://app.netlify.com/drop");
