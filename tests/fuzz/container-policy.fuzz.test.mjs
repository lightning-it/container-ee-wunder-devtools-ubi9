import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import fc from "fast-check";
import {
  parseContainerInstruction,
  parseEnvAssignment,
  parseGithubActionRef,
  parseImageReference,
  parseReleaseEvidenceJson,
  stripInlineComment,
  validateContainerPolicy,
} from "./container-policy.mjs";

const runs = Number.parseInt(process.env.FUZZ_RUNS || "1000", 10);
const root = process.cwd();

function readIfExists(path) {
  return existsSync(path) ? readFileSync(path, "utf8") : "";
}

function workflowFiles() {
  const dir = join(root, ".github", "workflows");
  if (!existsSync(dir)) {
    return [];
  }
  return readdirSync(dir)
    .filter((name) => name.endsWith(".yml") || name.endsWith(".yaml"))
    .map((name) => readIfExists(join(dir, name)));
}

const repoSeeds = [
  readIfExists(join(root, "Dockerfile")),
  readIfExists(join(root, "Containerfile")),
  readIfExists(join(root, ".dockerignore")),
  readIfExists(join(root, "scripts", "generate-release-evidence.py")),
  readIfExists(join(root, "scripts", "generate-release-provenance.py")),
  ...workflowFiles(),
].filter(Boolean);

assert.ok(repoSeeds.length > 0, "fuzz tests need at least one repository-owned seed file");

const imageNamePart = fc
  .tuple(
    fc.constantFrom(..."abcdefghijklmnopqrstuvwxyz0123456789"),
    fc.array(fc.constantFrom(..."abcdefghijklmnopqrstuvwxyz0123456789._-"), { minLength: 0, maxLength: 20 }),
  )
  .map(([first, rest]) => `${first}${rest.join("")}`);
const imageTag = fc
  .tuple(
    fc.constantFrom(..."ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"),
    fc.array(fc.constantFrom(..."ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"), { minLength: 0, maxLength: 30 }),
  )
  .map(([first, rest]) => `${first}${rest.join("")}`);
const envName = fc
  .tuple(
    fc.constantFrom(..."ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_"),
    fc.array(fc.constantFrom(..."ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"), { minLength: 0, maxLength: 40 }),
  )
  .map(([first, rest]) => `${first}${rest.join("")}`);
const githubPathPart = fc
  .array(fc.constantFrom(..."ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"), { minLength: 1, maxLength: 39 })
  .map((chars) => chars.join(""));
const sha40 = fc.array(fc.constantFrom(..."0123456789abcdef"), { minLength: 40, maxLength: 40 }).map((chars) => chars.join(""));

await fc.assert(
  fc.asyncProperty(fc.string(), async (input) => {
    assert.equal(typeof stripInlineComment(input), "string");
    const parsed = parseContainerInstruction(input);
    assert.ok(parsed === null || typeof parsed.instruction === "string");
    assert.ok(Array.isArray(validateContainerPolicy(input)));
  }),
  { numRuns: runs },
);

await fc.assert(
  fc.asyncProperty(
    fc.record({
      registry: fc.option(fc.domain(), { nil: "" }),
      path: fc.array(imageNamePart, { minLength: 1, maxLength: 4 }),
      tag: fc.option(imageTag, { nil: "" }),
    }),
    async ({ registry, path, tag }) => {
      const image = `${registry ? `${registry}/` : ""}${path.join("/")}${tag ? `:${tag}` : ""}`;
      const parsed = parseImageReference(image);
      assert.equal(parsed.valid, true);
      assert.ok(parsed.name.length > 0);
    },
  ),
  { numRuns: runs },
);

await fc.assert(
  fc.asyncProperty(
    fc.record({
      name: envName,
      value: fc.string(),
    }),
    async ({ name, value }) => {
      const parsed = parseEnvAssignment(`${name}=${value}`);
      assert.equal(parsed.valid, true);
      assert.equal(parsed.name, name);
    },
  ),
  { numRuns: runs },
);

await fc.assert(
  fc.asyncProperty(
    fc.record({
      owner: githubPathPart,
      repo: githubPathPart,
      sha: sha40,
    }),
    async ({ owner, repo, sha }) => {
      const parsed = parseGithubActionRef(`${owner}/${repo}@${sha}`);
      assert.equal(parsed.valid, true);
      assert.equal(parsed.ref.length, 40);
    },
  ),
  { numRuns: runs },
);

await fc.assert(
  fc.asyncProperty(fc.dictionary(fc.string(), fc.oneof(fc.string(), fc.integer(), fc.boolean(), fc.constant(null))), async (data) => {
    const parsed = parseReleaseEvidenceJson(JSON.stringify(data));
    assert.equal(parsed.valid, true);
  }),
  { numRuns: runs },
);

for (const seed of repoSeeds) {
  assert.doesNotThrow(() => validateContainerPolicy(seed));
  assert.doesNotThrow(() => parseReleaseEvidenceJson(seed));
}
