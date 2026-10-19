import { readFileSync } from "node:fs";

const snapshotPath = process.argv[2] ?? "snapshot.html";
const html = readFileSync(snapshotPath, "utf8");

const issueLinks = findAnchorTexts(html, /\/issues\/?$/);

if (issueLinks.includes("All issues")) {
  throw new Error("De GitHub-issueslink op het voorblad is nog Engelstalig.");
}

if (!issueLinks.includes("Alle issues")) {
  throw new Error("De GitHub-issueslink op het voorblad mist de tekst 'Alle issues'.");
}

function findAnchorTexts(html, hrefPattern) {
  const texts = [];
  const anchorPattern = /<a\s+[^>]*href=(["'])(.*?)\1[^>]*>([\s\S]*?)<\/a>/gi;
  for (const match of html.matchAll(anchorPattern)) {
    const [, , href, text] = match;
    if (hrefPattern.test(href)) {
      texts.push(stripTags(text).trim().replace(/\s+/g, " "));
    }
  }
  return texts;
}

function stripTags(value) {
  return value.replace(/<[^>]*>/g, "");
}
