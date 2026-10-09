import {
  GitHubClient,
  extractRespecBuildUrl,
  extractRespecVersion,
  hasOwn,
  logSection,
  parseArgs,
  readJson,
  requireArg,
  writeJson,
} from "./lib/workflow-utils.mjs";

const ORG_TOKENS = [
  {
    org: "Geonovum",
    token: process.env.GH_TOKEN_GEONOVUM ?? "",
  },
  {
    org: "BROprogramma",
    token: process.env.GH_TOKEN_BROPROGRAMMA ?? "",
  },
];

const args = parseArgs(process.argv.slice(2));
const reposFile = requireArg(args, "repos-file");
const selfOwner = requireArg(args, "self-owner");
const selfRepo = requireArg(args, "self-repo");

const reposJson = await readJson(reposFile);

function ensureOrg(org) {
  if (!reposJson[org]) {
    reposJson[org] = { repos: {} };
  }
  if (!reposJson[org].repos) {
    reposJson[org].repos = {};
  }
  return reposJson[org].repos;
}

function upsertRepoMetadata(repos, repo, defaultUpdateAllow, metadata) {
  const existing = repos[repo] ?? {};
  repos[repo] = {
    ...existing,
    updateAllow: hasOwn(existing, "updateAllow") ? existing.updateAllow : defaultUpdateAllow,
    respecBuildUrl: metadata.respecBuildUrl,
    respecVersion: metadata.respecVersion,
  };
}

async function getRemoteRepoMetadata(client, org, repo) {
  const [indexHtml, snapshotHtml] = await Promise.all([
    client.getRawFile(org, repo, "index.html"),
    client.getRawFile(org, repo, "snapshot.html"),
  ]);

  return {
    respecBuildUrl: extractRespecBuildUrl(indexHtml ?? ""),
    respecVersion: extractRespecVersion(snapshotHtml ?? ""),
  };
}

async function scanOrg(org, token) {
  if (!token) {
    console.log(`⚠️  Geen token voor ${org}, sync overgeslagen.`);
    return;
  }

  logSection(`Sync ${org}`);

  const client = new GitHubClient(token);
  const repos = ensureOrg(org);
  const allRepos = await client.listActiveRepos(org);
  const activeRepos = new Set();

  for (const repo of allRepos) {
    if (!repo || repo === ".github") {
      continue;
    }

    // Deze workflows-repo heeft een voorbeelddocument (js/config.js) voor de
    // regressietests, maar is zelf geen documentrepo.
    if (org === selfOwner && repo === selfRepo) {
      console.log(`⏩ Workflows-repo overgeslagen: ${org}/${repo}`);
      continue;
    }

    const hasJsConfig = await client.fileExists(org, repo, "js/config.js");
    if (!hasJsConfig) {
      continue;
    }

    activeRepos.add(repo);

    if (!hasOwn(repos, repo)) {
      console.log(`➕ Nieuw: ${org}/${repo}`);
    }

    const metadata = await getRemoteRepoMetadata(client, org, repo);
    upsertRepoMetadata(repos, repo, true, metadata);
  }

  for (const repo of Object.keys(repos)) {
    if (!activeRepos.has(repo)) {
      console.log(`🗑️  Verwijderd (niet meer actief): ${org}/${repo}`);
      delete repos[repo];
    }
  }
}

for (const { org, token } of ORG_TOKENS) {
  await scanOrg(org, token);
}

await writeJson(reposFile, reposJson);
