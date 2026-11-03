/**
 * 首页背景图处理：裁除 AI 生成水印 + 语义化命名 + JPEG 压缩
 *
 * 水印定位（原图 1536x1024）：x≈1412..1536, y≈960..1024（右下角水面区域）
 * 裁剪范围取 x=0..1404, y=0..944 —— 完整保留岸桥、集装箱船、天空等主体构图
 *
 * 用法: node bg_crop.js <源png> <输出jpg> [右边界] [下边界]
 */
const fs = require('fs');
const path = require('path');
const { PNG } = require('/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-vue3/node_modules/pngjs');

const SRC = process.argv[2];
const OUT = process.argv[3];
const X1 = parseInt(process.argv[4] || '1404', 10);
const Y1 = parseInt(process.argv[5] || '944', 10);

if (!SRC || !OUT || !fs.existsSync(SRC)) {
  console.error('用法: node bg_crop.js <源png> <输出jpg> [右边界] [下边界]');
  process.exit(1);
}

const img = PNG.sync.read(fs.readFileSync(SRC));
const { width: W, height: H, data } = img;
const cw = Math.min(X1, W);
const ch = Math.min(Y1, H);

const out = new PNG({ width: cw, height: ch });
for (let y = 0; y < ch; y++) {
  for (let x = 0; x < cw; x++) {
    const si = (y * W + x) * 4;
    const di = (y * cw + x) * 4;
    out.data[di] = data[si];
    out.data[di + 1] = data[si + 1];
    out.data[di + 2] = data[si + 2];
    out.data[di + 3] = 255; // 转 JPEG 无需透明，统一不透明
  }
}
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT.replace(/\.jpg$/, '.tmp.png'), PNG.sync.write(out));
console.log(`  裁剪: ${W}x${H} → ${cw}x${ch}（宽高比 ${(cw / ch).toFixed(2)}）`);
