/**
 * 江苏省港口集团 logo 拆分与适配工具
 *
 * 背景：官网下载的 logoboxshadow.png 是「JSPG 图形标志 + 中文全称 + 英文全称」的
 *      横向组合图（3875x2091，约 1.85:1）。而管理端 Logo.vue 的容器是固定的正方形
 *      （w-[calc(var(--logo-height)-10px)] h-[...]），直接把横向图塞进去会拉伸变形。
 *
 * 本脚本按 alpha 通道逐行分析非透明像素的行区间，用「空白间隙」把图切成
 *      ① 图形标志段（JSPG）  ② 文字段（中文+英文）
 *      然后输出：
 *      - logo-mark.png   图形标志，裁成居中正方形（适配正方形容器，不变形）
 *      - logo-full.png   完整组合图（含文字），用于登录页/欢迎页等横向位置
 *
 * 依赖：pngjs（管理端 node_modules 已带）
 */
const fs = require('fs');
const path = require('path');
const { PNG } = require('/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-vue3/node_modules/pngjs');

const SRC = process.argv[2];
const OUT_DIR = process.argv[3] || '/tmp/jsg-logo/out';
const ALPHA_MIN = 12; // 视为「有内容」的 alpha 阈值

if (!SRC || !fs.existsSync(SRC)) {
  console.error('用法: node logo_split.js <源png> [输出目录]');
  process.exit(1);
}
fs.mkdirSync(OUT_DIR, { recursive: true });

const src = PNG.sync.read(fs.readFileSync(SRC));
const { width: W, height: H, data } = src;
console.log(`源图: ${W}x${H}`);

// ---- 1. 逐行统计非透明像素 ----
const rowContent = new Array(H).fill(0);
for (let y = 0; y < H; y++) {
  let c = 0;
  for (let x = 0; x < W; x++) {
    if (data[(y * W + x) * 4 + 3] > ALPHA_MIN) c++;
  }
  rowContent[y] = c;
}

// ---- 2. 找空白间隙（连续多行几乎无内容）----
const gaps = [];
let gapStart = -1;
for (let y = 0; y < H; y++) {
  const empty = rowContent[y] <= 2;
  if (empty && gapStart < 0) gapStart = y;
  if (!empty && gapStart >= 0) {
    if (y - gapStart >= H * 0.012) gaps.push([gapStart, y - 1]);
    gapStart = -1;
  }
}
if (gapStart >= 0 && H - gapStart >= H * 0.012) gaps.push([gapStart, H - 1]);

console.log('检测到空白间隙:');
for (const [a, b] of gaps) console.log(`  y=${a}..${b}  (高 ${b - a + 1})`);

// ---- 3. 分段 ----
const bounds = [];
let segStart = 0;
for (const [a, b] of gaps) {
  if (a - segStart > H * 0.02) {
    bounds.push([segStart, a - 1]);
    segStart = b + 1;
  }
}
if (H - segStart > H * 0.02) bounds.push([segStart, H - 1]);

console.log('内容分段:');
for (const [a, b] of bounds) console.log(`  y=${a}..${b}  高 ${b - a + 1}`);

// ---- 4. 每段的横向内容边界 ----
function hRange(y0, y1) {
  let x0 = W, x1 = -1;
  for (let y = y0; y <= y1; y++) {
    for (let x = 0; x < W; x++) {
      if (data[(y * W + x) * 4 + 3] > ALPHA_MIN) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        break;
      }
    }
    for (let x = W - 1; x >= 0; x--) {
      if (data[(y * W + x) * 4 + 3] > ALPHA_MIN) {
        if (x > x1) x1 = x;
        if (x < x0) x0 = x;
        break;
      }
    }
  }
  return [x0, x1];
}

const segs = bounds.map(([a, b]) => {
  const [x0, x1] = hRange(a, b);
  return { y0: a, y1: b, x0, x1, w: x1 - x0 + 1, h: b - a + 1 };
});
for (const s of segs) {
  console.log(`  段 y=${s.y0}..${s.y1} x=${s.x0}..${s.x1}  尺寸 ${s.w}x${s.h}  宽高比 ${(s.w / s.h).toFixed(2)}`);
}

// ---- 5. 输出 ----
function crop(s, outPath, square) {
  const cw = s.x1 - s.x0 + 1;
  const ch = s.y1 - s.y0 + 1;

  let outW = cw, outH = ch;
  // 正方形化时的留白：内容在画布中居中
  let padTop = 0, padLeft = 0;
  if (square) {
    const side = Math.max(cw, ch);
    outW = side; outH = side;
    padTop = Math.floor((side - ch) / 2);
    padLeft = Math.floor((side - cw) / 2);
  }

  const out = new PNG({ width: outW, height: outH });
  for (let y = 0; y < outH; y++) {
    for (let x = 0; x < outW; x++) {
      // 画布坐标 → 源图坐标（正方形模式下内容居中）
      const sx = s.x0 + (x - padLeft);
      const sy = s.y0 + (y - padTop);
      // 关键：越出【本段】行范围就留透明，避免混入相邻段（如下方中文）
      if (sy < s.y0 || sy > s.y1) continue;
      if (sx < 0 || sx >= W || sy < 0 || sy >= H) continue;
      const si = (sy * W + sx) * 4;
      const di = (y * outW + x) * 4;
      out.data[di] = data[si];
      out.data[di + 1] = data[si + 1];
      out.data[di + 2] = data[si + 2];
      out.data[di + 3] = data[si + 3];
    }
  }
  fs.writeFileSync(outPath, PNG.sync.write(out));
  console.log(`  ✅ ${path.basename(outPath)}  ${outW}x${outH}  ${fs.statSync(outPath).size} bytes`);
}

console.log('\n输出:');
if (segs.length >= 1) {
  // 第一段 = 图形标志（正方形）
  crop(segs[0], path.join(OUT_DIR, 'logo-mark.png'), true);
  console.log('     → 图形标志（正方形，适配管理端正方形容器）');
}
if (segs.length >= 2) {
  // 全部段合并 = 完整组合图
  const all = {
    y0: Math.min(...segs.map((s) => s.y0)),
    y1: Math.max(...segs.map((s) => s.y1)),
    x0: Math.min(...segs.map((s) => s.x0)),
    x1: Math.max(...segs.map((s) => s.x1)),
  };
  crop(all, path.join(OUT_DIR, 'logo-full.png'), false);
  console.log('     → 完整组合图（含中英文，横向）');

  // 纯中文段（若存在）
  if (segs.length >= 3) {
    crop(segs[1], path.join(OUT_DIR, 'logo-cn.png'), false);
    console.log('     → 中文文字段');
  }
}
