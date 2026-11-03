import { resolve } from 'path'
import { loadEnv } from 'vite'
import type { UserConfig, ConfigEnv } from 'vite'
import { createVitePlugins } from './build/vite'
import { include, exclude } from "./build/vite/optimize"
// 当前执行node命令时文件夹的地址(工作目录)
const root = process.cwd()

// 路径查找
function pathResolve(dir: string) {
  return resolve(root, '.', dir)
}

// https://vitejs.dev/config/
export default ({ command, mode }: ConfigEnv): UserConfig => {
  let env = {} as any
  const isBuild = command === 'build'
  if (!isBuild) {
    env = loadEnv((process.argv[3] === '--mode' ? process.argv[4] : process.argv[3]), root)
  } else {
    env = loadEnv(mode, root)
  }
  return {
    base: env.VITE_BASE_PATH,
    root: root,
    // 依赖预构建缓存目录。
    // 说明：在带 FS 代理的 IDE（WorkBuddy / VSCode Remote 等）内，
    // vite 写 node_modules/.vite 缓存会触发代理管道 EPIPE 导致进程崩溃，
    // 因此支持用 VITE_CACHE_DIR 把缓存移到不被代理的目录（如 /tmp）。
    cacheDir: process.env.VITE_CACHE_DIR || 'node_modules/.vite',
    // 服务端渲染
    server: {
      port: env.VITE_PORT, // 端口号
      host: "0.0.0.0",
      open: env.VITE_OPEN === 'true',
      // 本地同源代理：浏览器请求 /admin-api/** 由 vite 转发到本机后端。
      //
      // 为什么需要它：`pnpm dev` 的 mode 是 development，只加载 .env，
      // 不加载 .env.dev，因此 .env 里必须给出 VITE_BASE_URL；我们选择置空，
      // 让前端以相对路径 /admin-api/** 请求，再由此代理转发到后端。
      // 好处：① 不依赖局域网 IP，换网络/IP 变动都不影响本机演示；
      //       ② 同源请求，天然没有跨域问题。
      //
      // 注意：后端接口本身就以 /admin-api 开头（如 /admin-api/system/auth/login），
      // 所以**不能**做 rewrite 去掉该前缀，否则会 404。
      proxy: {
        '/admin-api': {
          target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:48081',
          ws: false,
          changeOrigin: true,
        },
      },
    },
    // 项目使用的vite插件。 单独提取到build/vite/plugin中管理
    plugins: createVitePlugins(),
    css: {
      preprocessorOptions: {
        scss: {
          additionalData: '@import "./src/styles/variables.scss";',
          javascriptEnabled: true
        }
      }
    },
    resolve: {
      extensions: ['.mjs', '.js', '.ts', '.jsx', '.tsx', '.json', '.scss', '.css'],
      alias: [
        {
          find: 'vue-i18n',
          replacement: 'vue-i18n/dist/vue-i18n.cjs.js'
        },
        {
          find: /\@\//,
          replacement: `${pathResolve('src')}/`
        }
      ]
    },
    build: {
      minify: 'terser',
      outDir: env.VITE_OUT_DIR || 'dist',
      sourcemap: env.VITE_SOURCEMAP === 'true' ? 'inline' : false,
      // brotliSize: false,
      terserOptions: {
        compress: {
          drop_debugger: env.VITE_DROP_DEBUGGER === 'true',
          drop_console: env.VITE_DROP_CONSOLE === 'true'
        }
      }
    },
    optimizeDeps: { include, exclude }
  }
}
