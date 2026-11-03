#!/bin/bash
# ==============================================================================
#  特色菜订餐小程序 · 演示环境一键部署脚本
#
#  用法（务必在 macOS 自带的「终端」App 里运行，不要在 IDE 内置终端运行）：
#     cd /Users/tristan/Documents/tencent/Workbuddy/MiniProgram
#     bash setup_demo.sh
#
#  为什么必须在普通终端跑？
#     IDE 内置终端的文件代理会拒绝 rename 操作（报错
#     ERR_PNPM_CODEBUDDY_BROKER_DENY: Brokered rename refused by resolved path policy），
#     而 pnpm/npm 安装重度依赖 rename，会产出「目录在但文件缺」的损坏依赖树。
#     普通终端没有这层代理，一次安装即可成功。
# ==============================================================================

set -o pipefail

WS="/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
TC="$WS/.toolchain"
VUE="$WS/yshop-drink/yshop-drink-vue3"
BACK="$WS/yshop-drink/yshop-drink-boot3"

BOLD=$'\033[1m'; GRN=$'\033[32m'; RED=$'\033[31m'; YLW=$'\033[33m'; CYN=$'\033[36m'; RST=$'\033[0m'
ok()   { echo "${GRN}✅ $1${RST}"; }
bad()  { echo "${RED}❌ $1${RST}"; }
warn() { echo "${YLW}⚠️  $1${RST}"; }
info() { echo "${CYN}ℹ️  $1${RST}"; }
hr()   { echo "──────────────────────────────────────────────────────────"; }

echo ""
echo "${BOLD}══════════════════════════════════════════════════════════════${RST}"
echo "${BOLD}  特色菜订餐小程序 · 演示环境部署${RST}"
echo "${BOLD}══════════════════════════════════════════════════════════════${RST}"
echo ""

# ----------------------------------------------------------------------------
# 0. 环境准备
# ----------------------------------------------------------------------------
hr; echo "${BOLD}[0/6] 环境准备${RST}"; hr

export JAVA_HOME="$TC/jdk21/jdk-21.0.13+9/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"

if [ ! -d "$JAVA_HOME" ]; then
  bad "JDK 21 未找到：$JAVA_HOME"
  exit 1
fi
ok "JDK 21：$(java -version 2>&1 | head -1)"

# 管理端依赖（唯一需要网络、且必须在普通终端完成的一步）
if [ ! -d "$VUE/node_modules/vite" ]; then
  info "首次运行：安装管理端依赖（pnpm，1143 个包，约 3~8 分钟）…"
  cd "$VUE" || exit 1
  if command -v pnpm >/dev/null 2>&1; then
    pnpm install --frozen-lockfile && ok "pnpm install 完成"
  else
    npx --yes pnpm@9 install --frozen-lockfile && ok "pnpm(npx) install 完成"
  fi
  cd "$WS" || exit 1
else
  ok "管理端依赖已存在，跳过安装"
fi

# postcss 版本守卫：8.5.x 与 postcss-scss@4.0.9 不兼容（会导致 scss 解析报错）
PCSS_VER=$(node -e "try{console.log(require('$VUE/node_modules/postcss/package.json').version)}catch(e){console.log('none')}" 2>/dev/null)
if [ "$PCSS_VER" != "8.4.38" ] && [ "$PCSS_VER" != "none" ]; then
  warn "postcss = $PCSS_VER（应为 8.4.38），自动修复…"
  printf 'node_modules/postcss\tpostcss\t8.4.38\n' | python3 "$TC/full_restore.py" >/dev/null 2>&1
  NEW_VER=$(node -e "try{console.log(require('$VUE/node_modules/postcss/package.json').version)}catch(e){console.log('fail')}" 2>/dev/null)
  [ "$NEW_VER" = "8.4.38" ] && ok "postcss 已修复为 8.4.38" || bad "postcss 修复失败（当前 $NEW_VER）"
elif [ "$PCSS_VER" = "8.4.38" ]; then
  ok "postcss = 8.4.38（与 lockfile 一致）"
fi

# ----------------------------------------------------------------------------
# 1. MySQL
# ----------------------------------------------------------------------------
hr; echo "${BOLD}[1/6] 启动 MySQL 8.4${RST}"; hr
if "$TC/mysql/mysql-8.4.11-macos15-x86_64/bin/mysqladmin" --socket=/tmp/mysql-deli.sock -u root -proot status >/dev/null 2>&1; then
  ok "MySQL 已在运行"
else
  mkdir -p "$TC/mysqldata"
  nohup "$TC/mysql/mysql-8.4.11-macos15-x86_64/bin/mysqld" \
    --socket=/tmp/mysql-deli.sock --datadir="$TC/mysqldata" --port=3306 \
    --basedir="$TC/mysql/mysql-8.4.11-macos15-x86_64" \
    --pid-file=/tmp/mysql-deli.pid --log-error="$TC/mysqldata/error.log" \
    --bind-address=0.0.0.0 >/dev/null 2>&1 &
  for i in $(seq 1 40); do
    sleep 1.5
    "$TC/mysql/mysql-8.4.11-macos15-x86_64/bin/mysqladmin" --socket=/tmp/mysql-deli.sock -u root -proot status >/dev/null 2>&1 && break
  done
  "$TC/mysql/mysql-8.4.11-macos15-x86_64/bin/mysqladmin" --socket=/tmp/mysql-deli.sock -u root -proot status >/dev/null 2>&1 \
    && ok "MySQL 已启动" || { bad "MySQL 启动失败，见 $TC/mysqldata/error.log"; exit 1; }
fi
TBL=$("$TC/mysql/mysql-8.4.11-macos15-x86_64/bin/mysql" --socket=/tmp/mysql-deli.sock -u root -proot \
  -D 'yixiang-drink-open' -N -e \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='yixiang-drink-open';" 2>/dev/null)
[ "$TBL" = "94" ] && ok "数据库表数 94（数据完整）" || warn "表数 = $TBL（期望 94，请检查导入）"

# ----------------------------------------------------------------------------
# 2. Redis
# ----------------------------------------------------------------------------
hr; echo "${BOLD}[2/6] 启动 Redis 8.10${RST}"; hr
if "$TC/redis/redis-redis-1a2574c/src/redis-cli" -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG; then
  ok "Redis 已在运行"
else
  mkdir -p "$TC/redisdata"
  nohup "$TC/redis/redis-redis-1a2574c/src/redis-server" --port 6379 --daemonize no \
    --dir "$TC/redisdata" --appendonly yes >/dev/null 2>&1 &
  for i in $(seq 1 20); do
    sleep 1
    "$TC/redis/redis-redis-1a2574c/src/redis-cli" -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG && break
  done
  "$TC/redis/redis-redis-1a2574c/src/redis-cli" -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG \
    && ok "Redis 已启动" || { bad "Redis 启动失败"; exit 1; }
fi

# ----------------------------------------------------------------------------
# 3. 后端
# ----------------------------------------------------------------------------
hr; echo "${BOLD}[3/6] 启动后端 Spring Boot 48081${RST}"; hr
if curl -s --noproxy '*' -m 5 http://127.0.0.1:48081/actuator/health 2>/dev/null | grep -q UP; then
  ok "后端已在运行"
else
  if [ ! -f "$BACK/yshop-server/target/yshop-server.jar" ]; then
    info "jar 不存在，先构建（约 4 分钟）…"
    cd "$BACK" || exit 1
    mvn -B clean install package -Dmaven.test.skip=true
    cd "$WS" || exit 1
  fi
  info "启动后端（首次约 70 秒）…"
  nohup "$JAVA_HOME/bin/java" -Xms512m -Xmx2g \
    -jar "$BACK/yshop-server/target/yshop-server.jar" \
    --spring.profiles.active=local --server.port=48081 \
    > "$TC/backend_run.log" 2>&1 &
  for i in $(seq 1 60); do
    sleep 2
    curl -s --noproxy '*' -m 5 http://127.0.0.1:48081/actuator/health 2>/dev/null | grep -q UP && break
  done
  curl -s --noproxy '*' -m 5 http://127.0.0.1:48081/actuator/health 2>/dev/null | grep -q UP \
    && ok "后端已启动" || { bad "后端启动失败，见 $TC/backend_run.log"; exit 1; }
fi

# ----------------------------------------------------------------------------
# 4. 管理端
# ----------------------------------------------------------------------------
hr; echo "${BOLD}[4/6] 启动管理端 Vite 3000${RST}"; hr
if curl -s --noproxy '*' -m 5 http://127.0.0.1:3000/ >/dev/null 2>&1; then
  ok "管理端已在运行"
else
  lsof -nP -iTCP:3000 -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $2}' | xargs -r kill -9 2>/dev/null
  info "启动管理端（加载 14 个 vite 插件，约 2~4 分钟）…"
  # 用专用启动器：os.setsid 让 vite 脱离当前会话 + stdout/stderr 直连文件 fd，
  # 规避 WorkBuddy broker 的 write EPIPE；并自动注入当前有效的 broker.sock 路径
  # （IDE 重启后旧 socket 会变僵尸，导致 ECONNREFUSED 崩溃）。
  python3 "$WS/scripts/start_vite.py"
  if curl -s --noproxy '*' -m 10 http://127.0.0.1:3000/ >/dev/null 2>&1; then
    ok "管理端已启动"
  else
    bad "管理端启动失败，见 /tmp/vite_run.log"
    tail -20 /tmp/vite_run.log 2>/dev/null
    exit 1
  fi
fi

# 开启守护：检测到 3000 掉线自动重拉（IDE 重启导致 broker 失效时会自愈）
if [ "${VITE_WATCHDOG:-1}" = "1" ]; then
  python3 "$WS/scripts/start_vite.py" --daemon >/dev/null 2>&1
  ok "管理端守护已开启（掉线自动重拉，日志 /tmp/vite_daemon.log）"
fi

# ---- 登录链路校验：确认 /admin-api 代理转发正常（防「登录 404」）----
LOGIN_CODE=$(curl -s --noproxy '*' -m 20 -X POST http://127.0.0.1:3000/admin-api/system/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' 2>/dev/null \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('code'))" 2>/dev/null)
if [ "$LOGIN_CODE" = "0" ]; then
  ok "登录链路正常（/admin-api 代理转发 → code=0）"
else
  bad "登录链路异常（code=$LOGIN_CODE）——大概率是 VITE_BASE_URL 未配置或 proxy 未生效"
  echo ""
  echo "  ${YLW}排查：${RST}"
  echo "   1) 确认 $VUE/.env 里有： VITE_BASE_URL= （空值） 和 VITE_API_URL=/admin-api"
  echo "   2) 确认 vite.config.ts 的 server.proxy 已启用 '/admin-api' → http://127.0.0.1:48081"
  echo "   3) 直接测代理： curl -X POST http://127.0.0.1:3000/admin-api/system/auth/login \\"
  echo "        -H 'Content-Type: application/json' -d '{\"username\":\"admin\",\"password\":\"admin123\"}'"
  echo "   4) 若前端请求里出现 undefined/admin-api，说明 .env 缺 VITE_BASE_URL 且用了 pnpm dev（不读 .env.dev）"
  exit 1
fi

# ----------------------------------------------------------------------------
# 5. IP 同步
# ----------------------------------------------------------------------------
hr; echo "${BOLD}[5/6] 同步演示地址（mDNS 主机名，IP 无关）${RST}"; hr
HOST=$(hostname 2>/dev/null)
case "$HOST" in
  *.local) : ;;
  "") HOST=$(ipconfig getifaddr en0 2>/dev/null) ;;
  *) HOST="$HOST.local" ;;
esac
if [ -z "$HOST" ]; then
  warn "取不到本机主机名 / 局域网 IP，请检查网络连接"
else
  ok "本机演示地址（.local，IP 无关）：$HOST"
  python3 "$TC/sync_ip.py" 2>/dev/null | grep -E "✅|LAN_API_URL|VITE_BASE_URL" || warn "地址同步脚本执行异常，请手工检查"
  echo ""
  warn "小程序端需重新编译（HBuilderX 重新运行到微信开发者工具 / 真机预览）才生效"
fi

# ----------------------------------------------------------------------------
# 6. 自检
# ----------------------------------------------------------------------------
hr; echo "${BOLD}[6/6] 演示前自检${RST}"; hr
python3 "$TC/demo_check.py"

echo ""
echo "${BOLD}══════════════════════════════════════════════════════════════${RST}"
echo "${BOLD}  部署完成 · 访问地址${RST}"
echo "${BOLD}══════════════════════════════════════════════════════════════${RST}"
echo ""
echo "  ${BOLD}管理端（本机）${RST}   http://127.0.0.1:3000"
echo "  ${BOLD}管理端（局域网）${RST} http://$HOST:3000"
echo "  ${BOLD}后端 API${RST}        http://$HOST:48081"
echo "  ${BOLD}后端文档${RST}        http://127.0.0.1:48081/doc.html"
echo "  ${BOLD}小程序端 API${RST}    http://$HOST:48081/app-api  （已写入 config/index.js，IP 无关）"
echo ""
echo "  ${BOLD}管理端账号${RST}      admin / admin123"
echo "  ${BOLD}小程序端账号${RST}    15136175246 / Test@123456"
echo ""
echo "  ${YLW}若管理端配置改过 IP，需重启 vite：${RST}"
echo "  ${YLW}  lsof -nP -iTCP:3000 -sTCP:LISTEN | awk 'NR>1{print \$2}' | xargs -r kill -9${RST}"
echo "  ${YLW}  cd $VUE && nohup node node_modules/vite/bin/vite.js --host 0.0.0.0 --port 3000 > $TC/vite_run.log 2>&1 < /dev/null &${RST}"
echo ""
