#!/usr/bin/env node
// Bundelt de uitkomsten van alle controles uit build.yml tot één rapport in de
// job summary. Faalt pas hier, zodat één run alle bevindingen laat zien.
// Gebruik: node .github/workflows/controlerapport.mjs <map met controle-uitvoer>
// De step-uitkomsten komen binnen via omgevingsvariabelen (zie build.yml).
import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MAX_GROUPS = 25;
const MAX_LOCATIONS = 5;

const ICONS = { ok: "✅", blocking: "❌", notice: "⚠️", failed: "❌", skipped: "⏭️" };

export function stripAnsi(value) {
  return value.replace(/\u001b\[[0-9;]*m/g, "");
}

function readText(file) {
  return existsSync(file) ? readFileSync(file, "utf8") : null;
}

function readJson(file) {
  const text = readText(file);
  if (text === null || text.trim() === "") return null;
  return JSON.parse(text);
}

// Kopje van de sectie waarin een positie van de gegenereerde HTML valt, zodat
// een auteur de plek in de bron terugvindt. ReSpec zet soms meerdere elementen
// op één regel; de kolom geeft dan de doorslag als de tool die meelevert.
export function headingIndex(html) {
  const headings = [];
  const pattern = /<h([1-6])\b[^>]*>([\s\S]*?)<\/h\1>/gi;
  for (const match of html.matchAll(pattern)) {
    const before = html.slice(0, match.index);
    const line = before.split("\n").length;
    const column = match.index - before.lastIndexOf("\n");
    const text = match[2].replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
    if (text) headings.push({ line, column, text });
  }
  return (line, column = Infinity) => headings.findLast(heading =>
    heading.line < line || (heading.line === line && heading.column <= column))?.text ?? null;
}

function locate(headingFor, line, column) {
  if (!line) return null;
  const heading = headingFor?.(line, column);
  return heading ? `sectie "${heading}" (regel ${line} van snapshot.html)` : `regel ${line} van snapshot.html`;
}

export function parseRespec(log) {
  const findings = [];
  let current = null;
  for (const raw of stripAnsi(log).split("\n")) {
    const start = raw.match(/^\[(ERROR|WARNING)\]\s*(.*)$/);
    if (start) {
      current = { severity: start[1] === "ERROR" ? "error" : "warning", message: start[2].trim() };
      findings.push(current);
      continue;
    }
    const detail = raw.match(/^\s+(Hint|Plugin):\s*(.*)$/);
    if (detail && current) {
      if (detail[1] === "Hint") current.hint = detail[2].trim();
      else current.location = `plugin ${detail[2].trim()}`;
    } else if (!raw.startsWith(" ")) {
      current = null;
    }
  }
  return findings;
}

// proof-html: eerst de Nu HTML-validator, daarna html-proofer. Die laatste
// probeert het bij fouten tot drie keer, dus dezelfde melding kan vaker staan.
export function parseProofHtml(log, headingFor) {
  const findings = [];
  const seen = new Set();
  const lines = stripAnsi(log).split("\n");
  for (const line of lines) {
    const match = line.match(/^"file:[^"]*":(\d+)\.(\d+)-\d+\.\d+: (error|warning|info warning): (.*)$/);
    if (match) {
      findings.push({
        severity: "error",
        message: match[4].trim(),
        location: locate(headingFor, Number(match[1]), Number(match[2])),
      });
    }
  }

  let check = null;
  for (let index = 0; index < lines.length; index += 1) {
    const header = lines[index].match(/^For the (.+) check, the following failures were found:/);
    if (header) {
      check = header[1];
      continue;
    }
    const at = lines[index].match(/^\* At [^:]+(?::(\d+))?:\s*$/);
    if (at && check) {
      const message = lines.slice(index + 1).find(next => next.trim() !== "")?.trim();
      const key = `${check}\u0000${message}\u0000${at[1]}`;
      if (message && !seen.has(key)) {
        seen.add(key);
        findings.push({
          severity: "error",
          message: `${check}: ${message}`,
          location: locate(headingFor, at[1] ? Number(at[1]) : null),
        });
      }
    }
  }
  return findings;
}

// Lychee-uitvoer in JSON-formaat; de vorm van status verschilt per versie.
export function parseLychee(report, rootDir, headingFor) {
  const findings = [];
  for (const [file, entries] of Object.entries(report?.error_map ?? {})) {
    for (const entry of entries) {
      const status = typeof entry.status === "string"
        ? entry.status : entry.status?.text ?? JSON.stringify(entry.status);
      let url = entry.url ?? "";
      if (rootDir && url.startsWith("file://")) {
        const target = fileURLToPath(url);
        if (target.startsWith(rootDir)) url = path.relative(rootDir, target);
      }
      findings.push({
        severity: "error",
        message: `${status}: ${url}`,
        location: locate(headingFor, entry.span?.line, entry.span?.column),
      });
    }
  }
  return findings;
}

export function parseWcag(report) {
  if (!Array.isArray(report)) {
    throw new Error(report?.error ?? "Onbekend formaat van het WCAG-rapport.");
  }
  return report.flatMap(violation => (violation.nodes ?? [{}]).map(node => ({
    severity: "warning",
    message: `${violation.impact ?? "onbekend"}: ${violation.description ?? violation.id}`,
    location: Array.isArray(node.target) ? `\`${node.target.join(" ")}\`` : null,
    url: violation.helpUrl,
  })));
}

function check(definition, outcome, collect) {
  const result = { ...definition, findings: [], state: "ok" };
  if (outcome === "skipped" || outcome === "" || outcome === undefined) {
    result.state = "skipped";
    return result;
  }
  try {
    result.findings = collect() ?? [];
  } catch (error) {
    result.state = "failed";
    result.note = `Uitvoer kon niet worden gelezen: ${error.message}`;
    return result;
  }
  const errors = result.findings.filter(finding => finding.severity === "error").length;
  if (outcome === "failure" && result.findings.length === 0) {
    result.state = "failed";
    result.note = "De controle is mislukt zonder bevindingen te melden; zie de log van deze stap.";
  } else if (result.blocking && (errors > 0 || outcome === "failure")) {
    result.state = "blocking";
  } else if (result.findings.length > 0) {
    result.state = "notice";
  }
  return result;
}

export function collectChecks(directory, environment) {
  const outcome = name => environment[`OUTCOME_${name}`];
  const workspace = environment.WORKSPACE ?? process.cwd();
  const isRelease = environment.EVENT_NAME === "release";

  const publicationIndex = path.join(workspace, "publication-validation", "index.html");
  const headingFor = existsSync(publicationIndex)
    ? headingIndex(readFileSync(publicationIndex, "utf8")) : null;

  return [
    check({ title: "Bronbestand (raw.githubusercontent.com)", blocking: isRelease },
      outcome("RAW_LINKS"), () => {
        const matches = readText(path.join(directory, "raw-links.txt")) ?? "";
        return matches.split("\n").filter(Boolean).map(line => {
          const [, number, text] = line.match(/^(\d+):(.*)$/) ?? [null, null, line];
          return {
            severity: isRelease ? "error" : "warning",
            message: "Verwijzing naar raw.githubusercontent.com; gebruik docs.geostandaarden.nl.",
            location: number ? `index.html regel ${number}: ${text.trim().slice(0, 120)}` : text,
          };
        });
      }),
    check({ title: "ReSpec", blocking: false }, outcome("RESPEC"),
      () => parseRespec(readText(path.join(directory, "respec.log")) ?? "")),
    check({ title: "Voorblad (gelokaliseerde links)", blocking: true, optional: true },
      outcome("HEADER_LINKS"),
      () => {
        const log = stripAnsi(readText(path.join(directory, "header-links.log")) ?? "");
        const message = log.match(/^Error: (.*)$/m)?.[1];
        return message ? [{ severity: "error", message }] : [];
      }),
    check({ title: "HTML", blocking: true }, outcome("HTML"),
      () => parseProofHtml(readText(path.join(directory, "html.log")) ?? "", headingFor)),
    check({ title: "WCAG 2.2 (axe)", blocking: false }, outcome("WCAG"),
      () => parseWcag(readJson(path.join(directory, "wcag-report.json")))),
    check({ title: "Links", blocking: true }, outcome("LINKS"),
      () => parseLychee(readJson(path.join(directory, "link-check.json")),
        path.join(workspace, "publication-validation"), headingFor)),
  ];
}

function escapeMarkdown(value) {
  return String(value).replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll("|", "\\|");
}

function groupFindings(findings) {
  const groups = new Map();
  for (const finding of findings) {
    const key = `${finding.severity}\u0000${finding.message}`;
    if (!groups.has(key)) groups.set(key, { ...finding, locations: [] });
    if (finding.location) groups.get(key).locations.push(finding.location);
  }
  // Fouten eerst, daarna de meest voorkomende.
  return [...groups.values()].sort((a, b) =>
    (a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1)
    || b.locations.length - a.locations.length);
}

function countLabel(findings) {
  const errors = findings.filter(finding => finding.severity === "error").length;
  const warnings = findings.length - errors;
  const parts = [];
  if (errors) parts.push(`${errors} ${errors === 1 ? "fout" : "fouten"}`);
  if (warnings) parts.push(`${warnings} ${warnings === 1 ? "waarschuwing" : "waarschuwingen"}`);
  return parts.join(", ");
}

function resultLabel(result) {
  switch (result.state) {
    case "ok": return "geslaagd";
    case "skipped": return "niet uitgevoerd";
    case "failed": return "mislukt";
    default: return countLabel(result.findings) || "afgekeurd";
  }
}

export function renderReport(allChecks, environment) {
  // Optionele controles bestaan niet in elke documentrepo.
  const checks = allChecks.filter(result => !(result.optional && result.state === "skipped"));
  const buildFailed = environment.JOB_STATUS && environment.JOB_STATUS !== "success";
  const blocking = checks.filter(result =>
    result.state === "blocking" || (result.state === "failed" && result.blocking));
  const ready = !buildFailed && blocking.length === 0;

  const lines = ["## Controlerapport", ""];
  lines.push(ready
    ? "✅ **Publicatiegereed: ja**"
    : `❌ **Publicatiegereed: nee**${blocking.length
      ? ` (${blocking.length} blokkerende ${blocking.length === 1 ? "controle" : "controles"})` : ""}`);
  if (buildFailed) {
    lines.push("", "De build is afgebroken vóór alle controles klaar waren; zie de log van de mislukte stap.");
  }
  lines.push("", "| Controle | Resultaat | Blokkeert publicatie |", "| --- | --- | --- |");
  for (const result of checks) {
    lines.push(`| ${result.title} | ${ICONS[result.state]} ${resultLabel(result)} | ${result.blocking ? "ja" : "nee"} |`);
  }

  for (const result of checks) {
    if (result.state === "ok" || result.state === "skipped") continue;
    const open = result.state === "blocking" || (result.state === "failed" && result.blocking);
    lines.push("", `<details${open ? " open" : ""}>`,
      `<summary><strong>${ICONS[result.state]} ${result.title}</strong>: ${resultLabel(result)}</summary>`, "");
    if (result.note) lines.push(result.note, "");

    const groups = groupFindings(result.findings);
    for (const group of groups.slice(0, MAX_GROUPS)) {
      const prefix = group.severity === "error" ? "**Fout**" : "**Waarschuwing**";
      const count = group.locations.length > 1 ? ` (${group.locations.length}×)` : "";
      const link = group.url ? ` ([uitleg](${group.url}))` : "";
      lines.push(`- ${prefix}${count}: ${escapeMarkdown(group.message)}${link}`);
      if (group.hint) lines.push(`  - Tip: ${escapeMarkdown(group.hint)}`);
      for (const location of group.locations.slice(0, MAX_LOCATIONS)) {
        lines.push(`  - ${location.startsWith("`") ? location : escapeMarkdown(location)}`);
      }
      if (group.locations.length > MAX_LOCATIONS) {
        lines.push(`  - … en nog ${group.locations.length - MAX_LOCATIONS}`);
      }
    }
    if (groups.length > MAX_GROUPS) {
      lines.push("", `Nog ${groups.length - MAX_GROUPS} andere meldingen; zie het artifact \`validation-reports\`.`);
    }
    lines.push("", "</details>");
  }
  return { markdown: `${lines.join("\n")}\n`, ready, blocking };
}

function main() {
  const directory = process.argv[2];
  if (!directory) {
    console.error("Gebruik: node controlerapport.mjs <map met controle-uitvoer>");
    process.exit(2);
  }
  const checks = collectChecks(directory, process.env);
  const { markdown, ready, blocking } = renderReport(checks, process.env);

  writeFileSync(path.join(directory, "controlerapport.md"), markdown);
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, markdown);
  console.log(markdown);

  for (const result of blocking) {
    console.log(`::error title=${result.title}::${resultLabel(result)}; zie het controlerapport in de samenvatting van deze run.`);
  }
  if (!ready) process.exit(1);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
