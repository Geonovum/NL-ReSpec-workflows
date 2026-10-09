#!/usr/bin/env node
// Normaliseer alleen Mermaid-uitvoer, vóór HTML-validatie, PDF en publicatie.
// Installatie: (cd .github/mermaid-svg && npm ci --ignore-scripts)
// Gebruik: node .github/workflows/normalize-mermaid-svg.mjs snapshot.html [...]
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

// Een eigen dependency-directory: verander geen package.json van documentrepos.
const require = createRequire(new URL("../mermaid-svg/package.json", import.meta.url));
const { parse } = await import(require.resolve("parse5"));
const css = require("css-tree");
const SVG = "http://www.w3.org/2000/svg";
const IDREFS = new Set([
  "aria-labelledby", "aria-describedby", "aria-controls", "aria-owns",
  "aria-activedescendant", "aria-details", "aria-errormessage", "aria-flowto",
]);
const URL_ATTRIBUTES = new Set([
  "fill", "stroke", "filter", "clip-path", "mask", "marker", "marker-start",
  "marker-mid", "marker-end", "cursor", "color-profile",
]);

function* elements(node) {
  if (node.tagName) yield node;
  for (const child of node.childNodes ?? []) yield* elements(child);
}

function attr(node, name) {
  return node.attrs?.find(attribute => attribute.name === name)?.value ?? "";
}

function textContent(node) {
  return (node.childNodes ?? []).map(child => child.value ?? textContent(child)).join("");
}

function isMermaid(svg) {
  // Mermaid's eigen container blijft bestaan bij rechtstreeks gebruik.
  for (let node = svg; node; node = node.parentNode) {
    if (attr(node, "class").split(/\s+/).includes("mermaid")) return true;
  }
  // respec-mermaid 1.0.1 verwijdert de .mermaid-container. De gegenereerde
  // diagram-id EN Mermaid-styles herkennen ook flowcharts zonder ARIA/title.
  // 1.3.0 maakt <img src="data:image/svg+xml;base64,...">: die blijven intact.
  return /^diagram-\d+$/.test(attr(svg, "id")) && [...elements(svg)].some(node =>
    node.tagName === "style" && textContent(node).includes("--mermaid-font-family"));
}

function applyEdits(source, edits) {
  for (const { start, end, value } of edits.sort((a, b) => b.start - a.start)) {
    source = source.slice(0, start) + value + source.slice(end);
  }
  return source;
}

function escapeText(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function localFragment(value, renames) {
  return value.startsWith("#") && renames.has(value.slice(1))
    ? `#${renames.get(value.slice(1))}` : value;
}

function rewriteCss(source, context, renames) {
  if (renames.size === 0) return source;
  const edits = [];
  const tree = css.parse(source, { context, positions: true, parseCustomProperty: true });
  css.walk(tree, node => {
    let value;
    if (node.type === "IdSelector") {
      const renamed = renames.get(css.ident.decode(node.name));
      if (renamed) value = `#${css.ident.encode(renamed)}`;
    } else if (node.type === "Url") {
      const renamed = localFragment(node.value, renames);
      if (renamed !== node.value) value = css.generate({ ...node, value: renamed });
    } else if (node.type === "AttributeSelector" && node.value) {
      const name = css.ident.decode(node.name.name);
      const original = node.value.type === "String"
        ? node.value.value : css.ident.decode(node.value.name);
      let renamed = original;
      if (name === "id" && node.matcher === "=") renamed = renames.get(original) ?? original;
      else if (["href", "xlink|href", "*|href"].includes(name) && node.matcher === "=") {
        renamed = localFragment(original, renames);
      } else if (IDREFS.has(name) && ["=", "~="].includes(node.matcher)) {
        renamed = original.replace(/\S+/g, id => renames.get(id) ?? id);
      }
      if (renamed !== original) {
        edits.push({ start: node.value.loc.start.offset, end: node.value.loc.end.offset,
          value: node.value.type === "String" ? css.string.encode(renamed) : css.ident.encode(renamed) });
      }
    }
    // Gewone CSS strings (zoals content), kleuren en externe URLs blijven intact.
    if (value !== undefined) {
      edits.push({ start: node.loc.start.offset, end: node.loc.end.offset, value });
    }
  });
  return applyEdits(source, edits);
}

function normalize(html) {
  const document = parse(html, { sourceCodeLocationInfo: true });
  const nodes = [...elements(document)];
  const counts = new Map();
  for (const node of nodes) {
    const id = attr(node, "id");
    if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  const taken = new Set(counts.keys());
  const edits = [];
  let renamed = 0;
  let stripped = 0;
  const diagrams = nodes.filter(node => {
    if (node.namespaceURI !== SVG || node.tagName !== "svg") return false;
    for (let parent = node.parentNode; parent; parent = parent.parentNode) {
      if (parent.namespaceURI === SVG && parent.tagName === "svg" && isMermaid(parent)) return false;
    }
    return isMermaid(node);
  });

  diagrams.forEach((svg, index) => {
    const descendants = [...elements(svg)];
    const renames = new Map();
    const prefix = attr(svg, "id") || `mermaid-${index + 1}`;
    const localIds = new Set();
    for (const node of descendants) {
      const id = attr(node, "id");
      if (!id) continue;
      // Meerdere definities binnen hetzelfde diagram hebben geen eenduidig
      // doel voor references. Niet stilzwijgend een willekeurig doel kiezen.
      if (localIds.has(id)) throw new Error(`Dubbele id binnen Mermaid-diagram ${prefix}: ${id}`);
      localIds.add(id);
      // Het buitenste SVG is een mogelijk figuuranker; laat dat intact.
      if (node === svg || counts.get(id) < 2) continue;
      let candidate = `${prefix}-${id}`;
      let suffix = 2;
      while (taken.has(candidate)) candidate = `${prefix}-${id}-${suffix++}`;
      taken.add(candidate);
      renames.set(id, candidate);
    }
    renamed += renames.size;

    for (const node of descendants) {
      for (const attribute of node.attrs ?? []) {
        const name = attribute.prefix ? `${attribute.prefix}:${attribute.name}` : attribute.name;
        const location = node.sourceCodeLocation?.attrs?.[name];
        if (!location) continue;
        const original = attribute.value;
        let value = original;
        if (node.namespaceURI === SVG && node.tagName === "g" &&
            ["label-offset-x", "label-offset-y"].includes(name)) {
          edits.push({ start: location.startOffset, end: location.endOffset, value: "" });
          stripped++;
          continue;
        }
        if (name === "id" && node !== svg) value = renames.get(value) ?? value;
        else if (name === "href" || name === "xlink:href") value = localFragment(value, renames);
        else if (IDREFS.has(name)) value = value.replace(/\S+/g, id => renames.get(id) ?? id);
        else if (name === "style") value = rewriteCss(value, "declarationList", renames);
        else if (URL_ATTRIBUTES.has(name)) value = rewriteCss(value, "value", renames);
        if (value !== original) {
          edits.push({ start: location.startOffset, end: location.endOffset,
            value: `${name}="${escapeText(value).replaceAll('"', "&quot;")}"` });
        }
      }
      if (node.namespaceURI === SVG && node.tagName === "style") {
        const original = textContent(node);
        const value = rewriteCss(original, "stylesheet", renames);
        if (value !== original) {
          const location = node.sourceCodeLocation;
          edits.push({ start: location.startTag.endOffset, end: location.endTag.startOffset,
            value: escapeText(value) });
        }
      }
    }
  });
  // Alleen gewijzigde attributen en SVG-styles terugschrijven. De overige HTML,
  // tekst, comments, scripts, afbeeldingen en ReSpec-ankers blijven bytegelijk.
  return { html: applyEdits(html, edits), renamed, stripped, svgCount: diagrams.length };
}

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error("Gebruik: node normalize-mermaid-svg.mjs <bestand.html> [...]");
  process.exit(2);
}
for (const file of files) {
  const original = readFileSync(file, "utf8");
  const { html, renamed, stripped, svgCount } = normalize(original);
  if (html !== original) writeFileSync(file, html);
  console.log(`${file}: ${svgCount} Mermaid SVG('s), ${renamed} dubbele id('s) herschreven, ` +
    `${stripped} ongeldig(e) attribu(u)t(en) verwijderd.`);
}
