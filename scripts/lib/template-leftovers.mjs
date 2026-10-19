import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { runCommand } from "./workflow-utils.mjs";

// Bestanden die met "Use this template" uit NL-ReSpec-template in documentrepos
// terecht zijn gekomen, maar alleen bij de centrale tooling horen. Ze worden
// alleen verwijderd als de inhoud exact gelijk is aan een versie uit de
// geschiedenis van deze repository; aangepaste of eigen bestanden blijven staan.
export const TEMPLATE_LEFTOVER_FILES = [
  ".github/repos.json",
  ".github/workflows/check.yml",
  ".github/workflows/release-tag.yml",
  ".github/workflows/template-regression.yml",
  ".github/workflows/update-workflows.yml",
  ".github/workflows/visual-regression-reusable.yml",
  "publicatie_finder.sh",
  "replace_workflow-local.ps1",
  "replace_workflow-local.sh",
  "replace_workflow.sh",
  "scripts/check-localized-header-links.mjs",
  "scripts/lib/repository-migration.mjs",
  "scripts/lib/workflow-utils.mjs",
  "scripts/sync-repos.mjs",
  "scripts/update-document-repos.mjs",
  "scripts/visual-regression/compare.mjs",
  "tests/fixtures/mermaid/README.md",
  "tests/fixtures/mermaid/data-image.html",
  "tests/fixtures/mermaid/sensordata.html",
  "tests/test_central_workflows.py",
  "tests/test_mermaid_svg_normalization.py",
  "tests/test_publication_preflight.py",
  "tests/test_release_writeback_policy.py",
  "tests/test_repository_migration.py",
  "tests/verify_mermaid_rendering.mjs",
];

const NULL_BLOB = /^0+$/;

// Alle blob-SHA's die de kandidaten ooit hadden in de geschiedenis van historyRepoDir.
export function knownTemplateBlobs(historyRepoDir, files = TEMPLATE_LEFTOVER_FILES) {
  const shallow = runCommand("git", ["rev-parse", "--is-shallow-repository"], {
    cwd: historyRepoDir,
    description: "git rev-parse --is-shallow-repository",
  }).stdout.trim();
  if (shallow === "true") {
    console.log("⚠️  Geschiedenis is shallow; alleen bekende versies worden opgeruimd.");
  }

  const result = runCommand(
    "git",
    ["log", "--all", "--raw", "--no-abbrev", "--no-renames", "--format=", "--", ...files],
    { cwd: historyRepoDir, description: "git log --raw kandidaten" },
  );

  const known = new Map(files.map((file) => [file, new Set()]));
  for (const line of result.stdout.split("\n")) {
    // :100644 100644 <oud> <nieuw> M\t<pad>
    const match = line.match(/^:\d+ \d+ ([0-9a-f]+) ([0-9a-f]+) \w+\t(.+)$/);
    if (!match || !known.has(match[3])) {
      continue;
    }
    for (const blob of [match[1], match[2]]) {
      if (!NULL_BLOB.test(blob)) {
        known.get(match[3]).add(blob);
      }
    }
  }
  return known;
}

// Verwijdert exacte kopieën uit targetRepoDir en geeft de verwijderde paden terug.
export function removeTemplateLeftovers(targetRepoDir, knownBlobs) {
  const removed = [];

  for (const [file, blobs] of knownBlobs) {
    const target = path.join(targetRepoDir, file);
    if (!existsSync(target)) {
      continue;
    }

    const blob = runCommand("git", ["hash-object", "--", file], {
      cwd: targetRepoDir,
      description: `git hash-object ${file}`,
    }).stdout.trim();

    if (blobs.has(blob)) {
      rmSync(target, { force: true });
      removed.push(file);
    } else {
      console.log(`⏩ ${file} overgeslagen: aangepast t.o.v. de template.`);
    }
  }

  return removed;
}
