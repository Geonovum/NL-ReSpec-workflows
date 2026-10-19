import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

function isChecksIgnoreRule(line) {
  const pattern = line.trim();
  const normalized = pattern.replace(/^!/, "").replace(/^\//, "");
  return normalized === ".checks" || normalized.startsWith(".checks/");
}

export function migrateChecksDirectory(targetRepoDir) {
  const changedPaths = [];
  const gitignorePath = path.join(targetRepoDir, ".gitignore");

  if (existsSync(gitignorePath)) {
    const original = readFileSync(gitignorePath, "utf8");
    const lineEnding = original.includes("\r\n") ? "\r\n" : "\n";
    const hasTrailingNewline = /\r?\n$/.test(original);
    const lines = original.split(/\r?\n/);

    if (hasTrailingNewline) {
      lines.pop();
    }

    const updatedLines = lines.filter((line) => !isChecksIgnoreRule(line));
    const updated = `${updatedLines.join(lineEnding)}${hasTrailingNewline ? lineEnding : ""}`;

    if (updated !== original) {
      writeFileSync(gitignorePath, updated);
      changedPaths.push(".gitignore");
    }
  }

  const checksPath = path.join(targetRepoDir, ".checks");
  if (existsSync(checksPath)) {
    rmSync(checksPath, { recursive: true, force: true });
    changedPaths.push(".checks");
  }

  return changedPaths;
}
