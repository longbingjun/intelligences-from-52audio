/**
 * 服务端专用（仅在 .astro frontmatter / getStaticPaths 里用，不要在客户端组件引入）。
 *
 * 52audio 图片 CDN（Aliyun OSS）开启了 Referer 防盗链白名单，浏览器直接热链会被 403，
 * 详情见 scripts/cache-images.mjs 顶部注释。构建时该脚本已把图片下载到 public/images/，
 * 这里只需按同样的规则算出本地文件名，检查文件是否存在，存在则返回本地路径。
 */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { withBase } from "./paths";

function localImageFilename(url: string): string {
  const hash = crypto.createHash("sha1").update(url).digest("hex").slice(0, 16);
  const extMatch = /\.([a-zA-Z0-9]{2,5})(?:\?.*)?$/.exec(url);
  const ext = (extMatch?.[1] || "jpg").toLowerCase();
  return `${hash}.${ext}`;
}

/**
 * 返回本地缓存图片的 site 内路径（已套用 base）；如果构建时未成功缓存该图片，返回 null，
 * 调用处应跳过渲染该图（避免浏览器再去请求会被防盗链拒绝的原始外链，出现裂图图标）。
 */
export function resolveImageSrc(url: string | undefined | null): string | null {
  if (!url) return null;
  const rel = path.posix.join("images", localImageFilename(url));
  const abs = path.join(process.cwd(), "public", rel);
  if (fs.existsSync(abs)) {
    return withBase(`/${rel}`);
  }
  return null;
}
