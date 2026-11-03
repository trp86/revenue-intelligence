import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // only the API client may call the network (spec 07 section 11)
      "no-restricted-globals": ["error", { name: "fetch", message: "Use src/api/client.ts" }],
      "no-restricted-imports": ["error", { patterns: ["duckdb*", "@google/*", "*genai*"] }],
    },
  },
  {
    files: ["src/api/client.ts", "src/**/*.test.{ts,tsx}", "src/test/**"],
    rules: { "no-restricted-globals": "off" },
  },
);
