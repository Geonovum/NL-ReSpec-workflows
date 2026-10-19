// Uitvoeren vanuit een tijdelijke directory met @playwright/test, pngjs en puppeteer.
// node verify_mermaid_rendering.mjs <repository> <rapportdirectory>
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { copyFile, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "@playwright/test";
import { PNG } from "pngjs";

const require = createRequire(import.meta.url);
const root = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const results = [];

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: "inherit", ...options });
    child.on("error", reject);
    child.on("exit", code => code === 0 ? resolve() : reject(new Error(`${command}: exit ${code}`)));
  });
}

async function comparePng(before, after, label) {
  const a = PNG.sync.read(await readFile(before));
  const b = PNG.sync.read(await readFile(after));
  assert.equal(b.width, a.width, `${label}: breedte`);
  assert.equal(b.height, a.height, `${label}: hoogte`);
  let different = 0;
  for (let i = 0; i < a.data.length; i += 4) {
    if (!a.data.subarray(i, i + 4).equals(b.data.subarray(i, i + 4))) different++;
  }
  results.push({ label, width: a.width, height: a.height, differentPixels: different });
  assert.equal(different, 0, `${label}: gewijzigde pixels`);
}

await mkdir(output, { recursive: true });
const server = createServer(async (request, response) => {
  try {
    const file = path.resolve(output, `.${new URL(request.url, "http://localhost").pathname}`);
    if (!file.startsWith(`${output}${path.sep}`)) throw new Error("outside report");
    response.setHeader("Content-Type", "text/html; charset=utf-8");
    response.end(await readFile(file));
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const url = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
try {
  for (const fixture of ["sensordata", "data-image"]) {
    for (const variant of ["before", "after"]) {
      const dir = path.join(output, fixture, variant);
      await rm(dir, { recursive: true, force: true });
      await mkdir(dir, { recursive: true });
      await copyFile(path.join(root, `tests/fixtures/mermaid/${fixture}.html`), path.join(dir, "snapshot.html"));
    }
    await run(process.execPath, [path.join(root, ".github/workflows/normalize-mermaid-svg.mjs"),
      path.join(output, fixture, "after/snapshot.html")]);

    for (const media of ["screen", "print"]) {
      for (const width of [1440, 1024, 390]) {
        const page = await browser.newPage({ viewport: { width, height: 1000 }, deviceScaleFactor: 1 });
        await page.emulateMedia({ media });
        const filename = `${media}-${width}.png`;
        for (const variant of ["before", "after"]) {
          await page.goto(`${url}/${fixture}/${variant}/snapshot.html`, { waitUntil: "networkidle" });
          await page.evaluate(() => document.fonts.ready);
          if (fixture === "data-image") {
            assert.equal(await page.locator("img").evaluateAll(images =>
              images.length > 0 && images.every(image => image.complete && image.naturalWidth > 0)), true);
          } else {
            assert.equal(await page.locator("svg").count(), 4);
          }
          await page.screenshot({ path: path.join(output, fixture, variant, filename), fullPage: true });
        }
        await page.close();
        await comparePng(path.join(output, fixture, "before", filename),
          path.join(output, fixture, "after", filename), `${fixture}/${media}/${width}`);
      }
    }

    // Roep precies de bestaande PDF-generator aan met zijn normale config- en
    // snapshotcontract. Geen alternatieve testimplementatie van page.pdf().
    for (const variant of ["before", "after"]) {
      const dir = path.join(output, fixture, variant);
      await copyFile(path.join(root, ".github/workflows/pdf.js"), path.join(dir, "pdf.js"));
      await writeFile(path.join(dir, "config.js"),
        'module.exports = {respecConfig:{alternateFormats:[{label:"pdf",uri:"diagram.pdf"}]}};\n');
      await run(process.execPath, ["pdf.js"], { cwd: dir, env: {
        ...process.env,
        NODE_PATH: path.dirname(path.dirname(require.resolve("puppeteer/package.json"))),
        PUPPETEER_EXECUTABLE_PATH: chromium.executablePath(),
        PDF_SNAPSHOT_URL: `${url}/${fixture}/${variant}/snapshot.html`,
      } });
      await run("pdftoppm", ["-r", "96", "-png", path.join(dir, "diagram.pdf"), path.join(dir, "pdf-page")]);
    }
    const pages = (await readdir(path.join(output, fixture, "before"))).filter(file => file.startsWith("pdf-page"));
    const afterPages = (await readdir(path.join(output, fixture, "after"))).filter(file => file.startsWith("pdf-page"));
    assert.ok(pages.length > 0);
    assert.deepEqual(afterPages, pages, `${fixture}: gelijk aantal PDF-pagina's`);
    for (const page of pages) {
      await comparePng(path.join(output, fixture, "before", page),
        path.join(output, fixture, "after", page), `${fixture}/${page}`);
    }
  }
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
  await writeFile(path.join(output, "results.json"), JSON.stringify(results, null, 2));
}
console.log(JSON.stringify(results, null, 2));
