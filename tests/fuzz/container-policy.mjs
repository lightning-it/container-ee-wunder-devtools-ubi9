const INSTRUCTION_RE = /^\s*([A-Za-z][A-Za-z0-9_-]*)\s+(.*)$/;
const ENV_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const SECRET_NAME_RE = /(token|secret|password|passwd|apikey|api_key|credential|private_key)/i;
const DIGEST_RE = /^sha256:[a-f0-9]{64}$/;

export function stripInlineComment(input) {
  let quoted = false;
  let escaped = false;
  let output = "";

  for (const char of String(input)) {
    if (escaped) {
      output += char;
      escaped = false;
      continue;
    }
    if (char === "\\") {
      output += char;
      escaped = true;
      continue;
    }
    if (char === '"') {
      quoted = !quoted;
      output += char;
      continue;
    }
    if (char === "#" && !quoted) {
      break;
    }
    output += char;
  }

  return output.trim();
}

export function parseContainerInstruction(line) {
  const cleaned = stripInlineComment(line);
  if (!cleaned) {
    return null;
  }
  const match = cleaned.match(INSTRUCTION_RE);
  if (!match) {
    return { instruction: "UNKNOWN", value: cleaned };
  }
  return {
    instruction: match[1].toUpperCase(),
    value: match[2].trim(),
  };
}

export function parseImageReference(value) {
  const ref = String(value).trim();
  if (!ref || /\s/.test(ref)) {
    return { valid: false, reason: "empty-or-whitespace" };
  }
  const [withoutDigest, digest] = ref.split("@", 2);
  const slash = withoutDigest.lastIndexOf("/");
  const colon = withoutDigest.lastIndexOf(":");
  const hasTag = colon > slash;
  const tag = hasTag ? withoutDigest.slice(colon + 1) : "";
  const name = hasTag ? withoutDigest.slice(0, colon) : withoutDigest;
  return {
    valid: Boolean(name) && (!digest || DIGEST_RE.test(digest)) && (!tag || /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$/.test(tag)),
    name,
    tag,
    digest: digest || "",
  };
}

export function parseEnvAssignment(input) {
  const text = String(input).trim();
  const equals = text.indexOf("=");
  if (equals <= 0) {
    return { valid: false, name: "", value: "" };
  }
  const name = text.slice(0, equals).trim();
  const value = text.slice(equals + 1).trim();
  return {
    valid: ENV_NAME_RE.test(name),
    name,
    value,
    secretLike: SECRET_NAME_RE.test(name),
  };
}

export function parseGithubActionRef(input) {
  const value = String(input).trim();
  const at = value.lastIndexOf("@");
  if (at <= 0 || at === value.length - 1) {
    return { valid: false, owner: "", repo: "", ref: "" };
  }
  const path = value.slice(0, at);
  const ref = value.slice(at + 1);
  const parts = path.split("/");
  return {
    valid: parts.length >= 2 && /^[0-9a-f]{40}$/i.test(ref),
    owner: parts[0] || "",
    repo: parts[1] || "",
    ref,
  };
}

export function parseReleaseEvidenceJson(input) {
  try {
    const data = JSON.parse(String(input));
    return {
      valid: data && typeof data === "object" && !Array.isArray(data),
      repository: typeof data.repository === "string" ? data.repository : "",
      tag: typeof data.tag === "string" ? data.tag : "",
      commit_sha: typeof data.commit_sha === "string" ? data.commit_sha : "",
    };
  } catch {
    return { valid: false, repository: "", tag: "", commit_sha: "" };
  }
}

export function validateContainerPolicy(text) {
  const findings = [];
  for (const [index, line] of String(text).split(/\r?\n/).entries()) {
    const parsed = parseContainerInstruction(line);
    if (!parsed) {
      continue;
    }
    if (parsed.instruction === "FROM" && !parseImageReference(parsed.value.split(/\s+AS\s+/i)[0]).valid) {
      findings.push({ line: index + 1, rule: "invalid-from-reference" });
    }
    if (["ARG", "ENV"].includes(parsed.instruction)) {
      for (const item of parsed.value.split(/\s+/)) {
        const assignment = parseEnvAssignment(item);
        if (assignment.valid && assignment.secretLike) {
          findings.push({ line: index + 1, rule: "secret-like-build-variable" });
        }
      }
    }
  }
  return findings;
}
