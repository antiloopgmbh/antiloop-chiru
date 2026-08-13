#!/usr/bin/env node
// Regenerates the vendored files in src/assets/ from the npm packages
// declared in package.json, so the checked-in files always match the
// declared dependency versions. Run `npm run build:assets` after any
// dependency bump (e.g. a Dependabot PR) and commit the resulting diff.
import { build } from "esbuild";
import { copyFile, readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const assetsDir = path.join(root, "src", "assets");
const nodeModules = path.join(root, "node_modules");

async function copyAsset(from, to) {
  await copyFile(path.join(nodeModules, from), path.join(assetsDir, to));
  console.log(`copied ${from} -> src/assets/${to}`);
}

async function bundleHighlightJs() {
  const pkg = JSON.parse(
    await readFile(path.join(nodeModules, "highlight.js", "package.json"), "utf-8"),
  );
  await build({
    // "common.js" ships the core plus ~40 commonly used languages, matching
    // the bundle size historically vendored here. "index.js" (highlight.js's
    // package "main") pulls in all ~190 languages and balloons to ~1MB.
    entryPoints: [path.join(nodeModules, "highlight.js", "lib", "common.js")],
    bundle: true,
    minify: true,
    format: "iife",
    globalName: "hljs",
    platform: "browser",
    outfile: path.join(assetsDir, "highlight.min.js"),
    banner: {
      js: `/*! highlight.js v${pkg.version} | BSD-3-Clause | https://github.com/highlightjs/highlight.js */`,
    },
  });
  console.log(`bundled highlight.js v${pkg.version} -> src/assets/highlight.min.js`);
}

async function bundleGithubMarkdownCss() {
  const pkg = JSON.parse(
    await readFile(path.join(nodeModules, "github-markdown-css", "package.json"), "utf-8"),
  );
  const result = await build({
    entryPoints: [path.join(nodeModules, "github-markdown-css", "github-markdown.css")],
    bundle: true,
    minify: true,
    write: false,
  });
  const banner = `/*! github-markdown-css v${pkg.version} | MIT | https://github.com/sindresorhus/github-markdown-css */\n`;
  await writeFile(path.join(assetsDir, "github-markdown.min.css"), banner + result.outputFiles[0].text);
  console.log(`bundled github-markdown-css v${pkg.version} -> src/assets/github-markdown.min.css`);
}

async function main() {
  await mkdir(assetsDir, { recursive: true });

  // marked, mermaid and dompurify already ship prebuilt, minified UMD bundles.
  await copyAsset(path.join("marked", "marked.min.js"), "marked.min.js");
  await copyAsset(path.join("mermaid", "dist", "mermaid.min.js"), "mermaid.min.js");
  await copyAsset(path.join("dompurify", "dist", "purify.min.js"), "purify.min.js");

  // highlight.js's npm package only ships unbundled CJS/ESM sources for
  // the "core + common languages" entry point, so bundle it ourselves.
  await bundleHighlightJs();

  // highlight.js ships its GitHub theme CSS pre-minified.
  await copyAsset(path.join("highlight.js", "styles", "github.min.css"), "highlight-github.min.css");
  await copyAsset(path.join("highlight.js", "styles", "github-dark.min.css"), "highlight-github-dark.min.css");

  // github-markdown-css ships unminified CSS; minify it with esbuild.
  await bundleGithubMarkdownCss();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
