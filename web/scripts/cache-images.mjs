#!/usr/bin/env node
/**
 * 构建前置步骤：把产品详情页引用的 52audio OSS 图片下载到本地 public/images/。
 *
 * 根因：图片直接热链 https://52audio-images.oss-cn-shenzhen.aliyuncs.com/...，
 * 该 Aliyun OSS bucket 开启了 Referer 防盗链白名单（仅允许 https://www.52audio.com/），
 * 浏览器从 GitHub Pages 打开站点时请求会被 OSS 返回 403 AccessDenied，导致图片加载不出来。
 *
 * 这里在构建阶段（服务端，可以自定义请求头）带上正确的 Referer 把图片下载到本地，
 * 详情页改为引用本地文件（见 src/lib/images.ts），从根源避开浏览器端热链限制。
 */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const PRODUCTS_DIR = path.join(process.cwd(), "public", "data", "products");
const IMAGES_DIR = path.join(process.cwd(), "public", "images");
const REFERER = "https://www.52audio.com/";
const CONCURRENCY = 6;
const IMAGE_URL_RE = /^https?:\/\/\S+\.(jpe?g|png|webp|gif)(\?\S*)?$/i;

export function localImageFilename(url) {
  const hash = crypto.createHash("sha1").update(url).digest("hex").slice(0, 16);
  const extMatch = /\.([a-zA-Z0-9]{2,5})(?:\?.*)?$/.exec(url);
  const ext = (extMatch?.[1] || "jpg").toLowerCase();
  return `${hash}.${ext}`;
}

function collectImageUrls() {
  const urls = new Set();
  if (!fs.existsSync(PRODUCTS_DIR)) return urls;
  const files = fs.readdirSync(PRODUCTS_DIR).filter((f) => f.endsWith(".json"));

  const walk = (node) => {
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    if (node && typeof node === "object") {
      for (const value of Object.values(node)) {
        if (typeof value === "string" && IMAGE_URL_RE.test(value)) {
          urls.add(value);
        } else {
          walk(value);
        }
      }
    }
  };

  for (const file of files) {
    try {
      const data = JSON.parse(fs.readFileSync(path.join(PRODUCTS_DIR, file), "utf-8"));
      walk(data);
    } catch (err) {
      console.warn(`[cache-images] 跳过无法解析的文件 ${file}: ${err.message}`);
    }
  }
  return urls;
}

async function downloadOne(url) {
  const dest = path.join(IMAGES_DIR, localImageFilename(url));
  if (fs.existsSync(dest) && fs.statSync(dest).size > 0) {
    return { url, status: "cached" };
  }
  try {
    const resp = await fetch(url, {
      headers: {
        Referer: REFERER,
        "User-Agent": "Mozilla/5.0 (compatible; 52audio-intel-bot/1.0)",
      },
    });
    if (!resp.ok) {
      return { url, status: "failed", reason: `HTTP ${resp.status}` };
    }
    const buf = Buffer.from(await resp.arrayBuffer());
    fs.writeFileSync(dest, buf);
    return { url, status: "downloaded" };
  } catch (err) {
    return { url, status: "failed", reason: err.message };
  }
}

async function runPool(items, worker, concurrency) {
  const results = new Array(items.length);
  let idx = 0;
  async function next() {
    while (idx < items.length) {
      const i = idx++;
      results[i] = await worker(items[i]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, next));
  return results;
}

async function main() {
  fs.mkdirSync(IMAGES_DIR, { recursive: true });
  const urls = [...collectImageUrls()];
  console.log(`[cache-images] 发现 ${urls.length} 个图片 URL，开始下载（Referer=${REFERER}）...`);

  if (urls.length === 0) {
    console.log("[cache-images] 无需下载。");
    return;
  }

  const results = await runPool(urls, downloadOne, CONCURRENCY);
  const summary = { downloaded: 0, cached: 0, failed: 0 };
  const failures = [];
  for (const r of results) {
    summary[r.status] = (summary[r.status] || 0) + 1;
    if (r.status === "failed") failures.push(r);
  }
  console.log(
    `[cache-images] 完成：新下载 ${summary.downloaded}，命中本地缓存 ${summary.cached}，失败 ${summary.failed}`
  );
  if (failures.length) {
    console.warn(`[cache-images] 失败示例（最多显示 10 条，构建仍会继续，页面会跳过这些图片）：`);
    for (const f of failures.slice(0, 10)) {
      console.warn(`  - ${f.url} (${f.reason})`);
    }
  }
}

main();
