# 特色菜订餐微信小程序 · 上线发布方案

| 项 | 值 |
|---|---|
| 版本 | v1.0.0（集团首发） |
| 基座 | `guchengwuyue/yshop-drink`（MIT，gitee.com/guchengwuyue/yshop-drink） |
| 代码路径 | `/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink` |
| 三端 | `yshop-drink-boot3`（Spring Boot 3.2.2，jar ~168MB，端口 48081）/ `yshop-drink-vue3`（Vue3+Vite5.1.4+Element Plus 2.6.1）/ `yshop-drink-uniapp-vue3`（uni-app 2.x + Vue3 + 纯 JS） |
| 中间件 | MySQL 8.4.11、Redis 8.10.3、JDK 21（Temurin）、Maven 3.9.16 |
| 产出角色 | release-manager（上线发布师） |
| 状态 | **待质量门禁放行**（依赖 qa-tester / verify-runner 结论） |

> 平台规则类信息（微信类目、资质、支付、审核周期、ICP 备案等）依据通用工程实践给出，**均需以微信/工信部/云厂商官方最新文档为准**，本方案不替代官方口径。

---

## 0. 上线结论速览与阻塞项

### 0.1 结论

- 架构与构建链路可行，**但当前代码库存在 9 项生产阻断级问题**（含 1 个 P0 功能缺陷、4 项 P0 安全缺陷），全部清零前不安排生产发布。
- 本项目为**首发冷启动**（无存量用户、无历史版本），因此服务端可一次性全量上线；但**微信小程序端仍走灰度**（按比例分阶段发布），且**服务端必须先于小程序发布**且保持对旧版小程序向后兼容 ≥2 个版本。

### 0.2 上线阻塞项（Blocker）清单

| # | 级别 | 问题 | 精确位置 | 处置 |
|---|---|---|---|---|
| B1 | **P0 安全** | 短信验证码在**基础配置**中被固定为 `9999` | `yshop-drink-boot3/yshop-server/src/main/resources/application.yaml` L232-236（`yshop.sms-code.begin-code/end-code: 9999`） | 移出基础 profile，改为按环境注入；生产必须删除这两行 |
| B2 | **P0 安全** | 生产 profile 不存在，且 `local` profile 开启 `mock-enable: true`（可伪造身份免密登录） | `application-local.yaml` L193-194 `yshop.security.mock-enable: true` | 新建 `application-prod.yaml`，`mock-enable: false`、`demo: false` |
| B3 | **P0 安全** | 代码库内**硬编码 13+ 组生产级密钥** | 见 §1.4 泄露清单 | 全量轮换 + 改为 KMS/环境变量注入 + 仓库历史清理 |
| B4 | **P0 安全** | Actuator 全端点暴露 `include: '*'`（含 `env`/`heapdump`/`loggers`/`shutdown`） | `application-local.yaml` L120-123、`application-dev.yaml` L118-121 | 生产收窄为 `health,info,metrics,prometheus` 且绑定内网 |
| B5 | **P1 安全** | Druid 监控台 `/druid/*` **空用户名空密码**、无白名单 | `application-local.yaml` L19-23、`application-dev.yaml` L12-16 | 生产 `enabled: false` 或设口令 + `allow` 白名单 |
| B6 | **P0 功能** | 商品详情接口对不存在的 id 抛 NPE（500） | `yshop-module-mall/yshop-module-product-biz/.../AppStoreProductServiceImpl.java` **L185-187** | 上线前修复：`selectById` 返回 null 时返回 `CommonResult.error(404)` |
| B7 | **P1** | Docker 编排端口/路径错误：`Dockerfile` `EXPOSE 48080` 而 `local` profile 监听 `48081`；`docker-compose.yml` 引用不存在的 `./yshop-ui-admin` 与 `./yshop-server/` 构建上下文；镜像 `mysql:8`/`redis:6-alpine` 与实测版本不符 | `yshop-server/Dockerfile` L20、`script/docker/docker-compose.yml` L32/L61 | 生产编排重写为独立 `deploy/` 目录，版本全部钉死 |
| B8 | **P1** | 生产密钥写死在 yml；`yshop.pay.order-notify-url` 指向 `http://yshop.natapp1.cc`（内网穿透 + 明文 HTTP） | `application-local.yaml` L201-202 | 支付回调改为集团 HTTPS 正式域名，且外网可达 |
| B9 | **P1 合规** | 小程序仍指向上游作者：域名 `apidc.yixiang.co`、appid `wx001e2dc50bf532df`（测试号）、品牌「意象点餐」 | `yshop-drink-uniapp-vue3/config/index.js` L2/L11、`manifest.json` L404、`yshop-drink-vue3/.env` L2 | 全量替换为集团品牌与正式 appid/域名，否则审核必被拒 |

**质量门禁要求**：B1-B9 全部关闭 + qa-tester 出具「P0 bug = 0、核心链路 100%」结论后，方可进入 §5 CI/CD 的生产部署阶段。

---

## 1. 环境规划

### 1.1 四套环境矩阵

| 环境 | 用途 | 后端资源 | 管理后台 | 小程序 | 数据库 | Redis | 配置来源 |
|---|---|---|---|---|---|---|---|
| **dev 开发** | 日常开发、自测 | 1C4G / 2C8G，容器 `yshop-server:dev` | `vite dev` 本地 | HBuilderX 真机预览 | 本地 MySQL 8.4.11 `yixiang-drink-open` | 本地 Redis db=0 | `application-local.yaml`（明文，**仅限本地**） |
| **test 测试** | 集成测试、QA 回归 | 2C4G ×1 | Nginx 静态 `:8080` | 体验版 | 测试库（脱敏生产快照） | db=1 | `application-test.yaml` + 变量注入 |
| **staging 预发** | 提审前验证、与生产同构 | 2C8G ×2（蓝绿） | Nginx `:8080` | 审核版（指向预发 API） | 预发库（生产只读副本 + 独立写库） | db=2 | `application-staging.yaml` + KMS 注入，**拓扑与生产一致** |
| **prod 生产** | 正式对外 | 4C8G ×2（滚动/蓝绿），ECS 或 K8s | Nginx + CDN | 线上版本 | RDS MySQL 8.4 主从 + 只读 | 托管 Redis 8.10（哨兵/集群） | `application-prod.yaml`（**仅占位符**）+ KMS/环境变量注入 |

资源规格基于实测结论：jar 168MB、Spring Boot 3.2.2 + Druid + MyBatis-Plus，4C8G 可支撑集团内部订餐场景（并发按门店数×峰值估算，预估 QPS < 200）。

### 1.2 部署形态选型（三种方案对比）

参考手册给出三方案，对照本项目实际：

| 方案 | 优势 | 劣势 | 适配本项目？ |
|---|---|---|---|
| **云服务器（ECS/CVM）** | 完全可控、成本可预估、Spring Boot 长驻进程天然适配 | 需自运维、扩容要操作 | ✅ **后端主选**。本项目需要 Quartz 定时任务、Druid 长连接、WebSocket（`yshop.websocket.enable: true`）、本地文件上传目录 `yshop.file-path`，Serverless 的冷启动与本地文件系统限制均不友好 |
| **Serverless（函数/云托管）** | 免运维、弹性 | 冷启动（影响点餐首屏）、长任务受限、锁定风险 | ❌ 不选作后端。可作为**兜底**：图片处理、导出 XLSX 等异步任务迁出 |
| **静态托管（OSS+CDN）** | 极廉价、高可用、秒级发布 | 仅前端/静态内容 | ✅ **管理后台主选**。`yshop-drink-vue3` 产物为纯静态（`dist-prod`），配 CDN + 版本目录切换可实现秒级回退 |

**组合基线（与参考手册一致，本项目落地版）**：

```
[微信小程序] ──HTTPS──┐
                      ├──► Nginx(443) ──► 后端 yshop-server ×2（48081）
[管理后台 CDN/OSS] ────┘        │
                               ├──► RDS MySQL 8.4（主 + 只读）
                               ├──► 托管 Redis 8.10
                               └──► OSS（菜品图片，yshop.file-path 改指 OSS）
```

### 1.3 网络与安全域划分（对标等保三级）

按等保三级「通信网络、区域边界、计算环境」三要素划分：

| 安全域 | 网段（示例） | 可访问对象 | 出入口管控 |
|---|---|---|---|
| **DMZ 边界区** | 10.10.0.0/24 | Nginx / LB / CDN 回源 | 只开放 443/80；80 强制 301→443；安全组仅白名单 CDN 回源 IP |
| **应用区（生产）** | 10.20.10.0/24 | yshop-server ×2、Quartz Worker | 只允许 DMZ → 48081；禁止主动出公网（除支付/短信白名单） |
| **数据区** | 10.20.20.0/24 | MySQL 主从、Redis、备份库 | 只允许应用区 3306/6379；**数据库禁止公网访问**；备份库仅备份账号可读写 |
| **运维区（堡垒机）** | 10.20.30.0/24 | 堡垒机、跳板机 | 所有运维操作经堡垒机审计；禁直连生产容器 exec |
| **办公/测试区** | 10.30.0.0/24 | CI Runner、测试环境 | 与生产**物理/逻辑隔离**，不共享数据库账号 |

关键要求：
- 生产数据库**不得**使用 `root`；建立专用账号 `yshop_app`（读写）、`yshop_migrate`（DDL，仅 Flyway 使用）、`yshop_backup`（备份）。
- 安全组最小化：3306/6379 **不对 0.0.0.0/0 开放**。
- 操作审计：堡垒机会话录像 + 数据库审计（云厂商 DB Audit）+ 生产发布操作留痕（发布单）。

### 1.4 配置分离策略（config / secret 分离）

**原则**：`application-*.yaml` 只保留**非敏感**配置与**占位符**；一切密码/密钥走环境变量或 KMS 注入；**生产密码绝不写入 yml、绝不进代码库**。

#### 1.4.1 当前代码库泄露清单（实测扫描结果，上线前必须全量轮换）

| 位置 | 泄露项 | 处置 |
|---|---|---|
| `application.yaml` L79 | `mybatis-plus.encryptor.password: XDV71a+xqStEA3WH` | **立即轮换**。此密钥用于 DB 内配置项加密，泄露后 `infra_config` 表内所有密文可被解密 |
| `application.yaml` L236-237 | `yshop.sms-code.begin-code/end-code: 9999` | 删除（见 B1） |
| `application.yaml` L244-251 | 快递鸟 `api-key: cb022f1e-...`、`business-id: 1809751`；kd100 `key`/`customer` | 轮换 + 注入 |
| `application.yaml` L153-154 | `yshop.web.admin-ui.url: http://dashboard.yshop.yixiang.co`（明文 HTTP） | 改 HTTPS 集团域名 |
| `application-local.yaml` / `application-dev.yaml` | MySQL `root/root`、Redis 无密码、RabbitMQ `rabbit/rabbit`、RocketMQ/Kafka 无认证 | 全部轮换，生产开启密码/ACL |
| `application-local.yaml` L172-185、`application-dev.yaml` L144-159 | 微信公众号 `app-id/secret`、小程序 `appid/secret` | **轮换**（测试号 secret 泄露可被冒用；正式号上线前必须重新生成） |
| `application-local.yaml` L213-221 | 钉钉 `client-secret`、企业微信 `client-secret` | 轮换 |
| `application-local.yaml` L206 | 腾讯地图 `tencent-lbs-key` | 轮换 + 配白名单 |
| `yshop-drink-vue3/.env` L20/L23 | 百度统计 code、百度地图 AK | 轮换或改由集团自有统计 |
| `yshop-drink-uniapp-vue3/config/index.js` L2/L11 | `apidc.yixiang.co`、`wxdbdbc123c8c30b45` | 替换集团域名/appid |
| `manifest.json` L189/L196/L404 | 微信 appid（App/小程序/公众号） | 替换正式 appid |
| `script/docker/docker.env` L3/L9 | `MYSQL_ROOT_PASSWORD=123456` | 删除文件，改为 CI 变量 |

**泄露扫描命令（CI 卡点，每次提交执行）**：

```bash
# Gitleaks（MIT/Apache-2.0，GitHub 官方仓库）
docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest detect \
  --source /repo --redact --report-path gitleaks-report.json --exit-code 1

# 补充：正则兜底扫描（无 gitleaks 时）
grep -rnIE "(password|secret|app-?secret|api-?key|access-?key|private-?key|token)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+_=.-]{12,}" \
  --include='*.yaml' --include='*.yml' --include='*.properties' --include='*.js' --include='*.json' \
  --exclude-dir=node_modules --exclude-dir=uni_modules . || echo "疑似泄露项：$(grep -rlIE ...)"

# 仓库历史清理（泄露密钥进过 git 历史时必须执行，否则只删当前文件无效）
git filter-repo --invert-paths --path config/secrets/ --path '**/application-*.yaml'
git filter-repo --replace-text <(echo 'cb022f1e-48f1-4c4a-a723-9001ac9676b8==>***REMOVED***')
# 清理后必须通知所有协作者重新 clone，并强制轮换全部已泄露凭据
```

#### 1.4.2 生产配置骨架（新增文件，不入库密钥）

`yshop-drink-boot3/yshop-server/src/main/resources/application-prod.yaml`：

```yaml
server:
  port: ${SERVER_PORT:48081}
  shutdown: graceful            # 优雅停机，配合 K8s preStop
  tomcat:
    threads:
      max: 200
      min-spare: 20
    accept-count: 100

spring:
  lifecycle:
    timeout-per-shutdown-phase: 30s
  datasource:
    dynamic:
      primary: master
      datasource:
        master:
          url: ${DB_MASTER_URL}          # jdbc:mysql://...，密文放 KMS
          username: ${DB_MASTER_USER}
          password: ${DB_MASTER_PASSWORD}
        slave:
          lazy: true
          url: ${DB_SLAVE_URL}
          username: ${DB_SLAVE_USER}
          password: ${DB_SLAVE_PASSWORD}
  data:
    redis:
      host: ${REDIS_HOST}
      port: ${REDIS_PORT:6379}
      password: ${REDIS_PASSWORD}
      database: 0
      ssl.enabled: true
  flyway:
    enabled: true
    baseline-on-migrate: true
    baseline-version: 0
    locations: classpath:db/migration
    validate-on-migrate: true
    out-of-order: false
    clean-disabled: true            # 生产禁止 flyway clean
    locations: classpath:db/migration

management:
  endpoints:
    web:
      base-path: /actuator
      exposure:
        include: health,info,metrics,prometheus   # 严禁 '*'
  endpoint:
    health:
      show-details: when-authorized
  server:
    address: 0.0.0.0
  metrics:
    tags:
      application: ${spring.application.name}
      env: prod

yshop:
  info:
    version: 1.0.0
  security:
    mock-enable: false          # 生产必须 false
    permit-all_urls:
      - /admin-api/mp/open/**
  demo: false
  xss:
    enable: true
  access-log:
    enable: true                # 生产开启访问日志
  captcha:
    enable: true
  sms-code:
    expire-times: 10m
    send-frequency: 1m
    send-max-quantity-per-day: 10
    # 注意：此处【不要】再出现 begin-code / end-code
  pay:
    order-notify-url: ${PAY_ORDER_NOTIFY_URL}   # https://api.group.com/app-api/order/notify/order
    refund-notify-url: ${PAY_REFUND_NOTIFY_URL}
  file-path: ${FILE_PATH}       # 指向挂载卷或 OSS 适配目录
  h5: ${H5_BASE_URL}
  tenant:
    enable: false
  trade:
    order:
      app-id: ${TRADE_APP_ID}

wx:
  miniapp:
    appid: ${WX_MINIAPP_APPID}
    secret: ${WX_MINIAPP_SECRET}
    config-storage:
      type: RedisTemplate
      key-prefix: wa
  mp:
    app-id: ${WX_MP_APP_ID}
    secret: ${WX_MP_SECRET}

springdoc:
  api-docs:
    enabled: false              # 生产关闭接口文档
swagger-ui:
  enabled: false
knife4j:
  enable: false

logging:
  file:
    name: /data/logs/${spring.application.name}.log
  level:
    root: INFO
    co.yixiang.yshop: INFO
```

同时在 `application.yaml` 中把 `spring.profiles.active` 由硬编码 `local` 改为：

```yaml
spring:
  profiles:
    active: ${SPRING_PROFILES_ACTIVE:local}   # 容器/环境变量覆盖，禁止本地默认直接上生产
```

#### 1.4.3 密钥注入方式（优先级从高到低）

1. **云厂商 KMS / Secret Manager**：生产首选。CI 从 KMS 拉取 → 以环境变量注入容器 → 容器内不落盘。
2. **CI 受保护变量 + 变量掩码**：非敏感或轮换周期短的密钥。
3. **配置中心（Nacos/Apollo）**：需要运行时热切换的开关（如功能灰度开关）。
4. **禁止**：写入 yml、写入 Dockerfile `ENV`、写入 git、写入构建产物 `application.yml`（构建后用 `sed` 剔除并校验）。

CI 侧的产物校验（构建后执行，防止密钥被打进 jar）：

```bash
unzip -p yshop-server/target/yshop-server.jar BOOT-INF/classes/application-prod.yaml \
  | grep -nE "(password|secret|api-key|access-key):\s*[A-Za-z0-9/+_=.-]{8,}" \
  && { echo "FAIL: 生产配置中检出明文密钥"; exit 1; } || echo "PASS: 无明文密钥"
```

---

## 2. 构建与制品

### 2.1 后端 jar 构建

#### 2.1.1 Java 版本矛盾统一（关键）

**现状矛盾**：顶层 `yshop-drink-boot3/pom.xml` L35-37 声明

```xml
<java.version>17</java.version>
<maven.compiler.source>${java.version}</maven.compiler.source>
<maven.compiler.target>${java.version}</maven.compiler.target>
```

但实测编译期实际生效的是 `release 21`（构建机 JDK 21），而运行镜像 `yshop-server/Dockerfile` L3 为 `eclipse-temurin:21-jre`。三者不一致会让「构建机 JDK 变更 → 产物字节码静默变化」成为隐性风险。

**统一方案（推荐 A，必须二选一，不得并存）**：

- **方案 A（采用）—— 统一到 21**：Spring Boot 3.2.2 最低要求 Java 17，21 属受支持范围；运行镜像已是 `21-jre`，改动最小。

  顶层 `pom.xml` 改为：

  ```xml
  <properties>
      <java.version>21</java.version>
      <!-- 显式使用 release，避免 source/target 与实际 toolchain 脱节 -->
      <maven.compiler.release>${java.version}</maven.compiler.release>
      <maven.compiler.source>${java.version}</maven.compiler.source>
      <maven.compiler.target>${java.version}</maven.compiler.target>
  </properties>
  ```

- **方案 B（备选）—— 统一到 17**：保持 pom 不变，构建机固定 JDK 17，`Dockerfile` 改 `eclipse-temurin:17-jre`。字节码 17 在 JRE 21 上可运行（向下兼容），反之不可。

**硬性规则**：**编译字节码版本 ≤ 运行时 JRE 版本**。无论选 A/B，CI 必须加「字节码版本断言」卡点：

```bash
# 从 fat jar 中取出主类并检查 class 文件 major version
unzip -p yshop-server/target/yshop-server.jar \
  BOOT-INF/classes/co/yixiang/yshop/server/YshopServerApplication.class > /tmp/Main.class
javap -verbose /tmp/Main.class | grep -E '^\s+(major|minor) version'
# 期望：major version: 65（Java 21）/ 61（Java 17）/ 52（Java 8，均非法）
```

#### 2.1.2 构建命令

```bash
export JAVA_HOME=/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/.toolchain/jdk/temurin-21   # CI 用 temurin:21
export PATH="$JAVA_HOME/bin:/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/.toolchain/maven/apache-maven-3.9.16/bin:$PATH"
mvn -v   # 期望 Apache Maven 3.9.16 + JDK 21

cd /Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-boot3

# revision 统一版本号（flatten-maven-plugin 会解析 ${revision}，所有模块版本联动）
mvn -B -T 1C -Drevision=1.0.0 clean package

# 产物
ls -lh yshop-server/target/yshop-server.jar     # 期望 ~168MB 的 Spring Boot fat jar
```

> 说明：项目使用 `flatten-maven-plugin`（`flattenMode=resolveCiFriendliesOnly`）管理 `${revision}`，**不需要**逐个改各子模块 pom 版本。

#### 2.1.3 容器镜像构建（修正版 Dockerfile）

原 `yshop-server/Dockerfile` 的 `EXPOSE 48080` 与实际 `server.port: 48081` 不一致，生产版重写：

```dockerfile
FROM eclipse-temurin:21-jre AS base
LABEL org.opencontainers.image.title="yshop-server" \
      org.opencontainers.image.vendor="group-it" \
      org.opencontainers.image.source="https://gitee.com/guchengwuyue/yshop-drink"

RUN apt-get update && apt-get install -y --no-install-recommends curl tzdata \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY ./target/yshop-server.jar app.jar

ENV TZ=Asia/Shanghai \
    SERVER_PORT=48081 \
    JAVA_OPTS="-XX:MaxRAMPercentage=75.0 -XX:+UseZGC -XX:+ExitOnOutOfMemoryError -Djava.security.egd=file:/dev/./urandom -Dfile.encoding=UTF-8"
EXPOSE 48081
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:48081/actuator/health/readiness || exit 1
ENTRYPOINT ["sh","-c","exec java $JAVA_OPTS -jar app.jar"]
```

- 168MB fat jar 用 `-XX:MaxRAMPercentage` 而非固定 `-Xmx`，适配 4C8G 规格。
- 以非 root（`10001`）运行，满足等保三级最小权限要求。
- 生产编排不复用仓库内 `script/docker/docker-compose.yml`（其构建上下文与 `yshop-ui-admin` 路径均失效），改为新建 `deploy/` 目录（见 §5.3）。

### 2.2 管理后台构建

`yshop-drink-vue3/package.json` 已提供分环境脚本（L12-16）：

```bash
cd /Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-vue3
pnpm install --frozen-lockfile
pnpm lint:eslint            # 卡点：eslint --fix --ext .js,.ts,.vue ./src
pnpm ts:check               # 卡点：vue-tsc --noEmit
pnpm build:prod             # vite build --mode prod，产物在 dist-prod/
```

**必须先修 `.env.prod`**（当前指向 `localhost`，见 B9）：

```ini
# yshop-drink-vue3/.env.prod
NODE_ENV=production
VITE_DEV=false
VITE_BASE_URL='https://api.group.com'              # 生产 API 根域名
VITE_UPLOAD_TYPE=server
VITE_UPLOAD_URL='https://api.group.com/admin-api/infra/file/upload'
VITE_API_URL=/admin-api
VITE_DROP_DEBUGGER=true
VITE_DROP_CONSOLE=true
VITE_SOURCEMAP=false
VITE_BASE_PATH=/
VITE_OUT_DIR=dist-prod
VITE_MALL_H5_DOMAIN='https://h5.group.com'
```

同时 `.env` 中的 `VITE_APP_TITLE=意象点餐管理系统` 必须改为集团名称；`VITE_APP_BAIDU_CODE` / `VITE_BAIDU_MAP_AK` 轮换或移除。

### 2.3 小程序端构建（HBuilderX CLI）

**实测结构结论**：`yshop-drink-uniapp-vue3` 是 **HBuilderX 工程结构**（`manifest.json` / `pages.json` / `main.js` 在仓库根，**无 `src/` 目录、无 `vite.config.js`、`package.json` 内无 `@dcloudio/*` 依赖、无 build 脚本**）。

因此**不能**用 `npm run build:mp-weixin`（uni-app CLI 方式）在 Linux CI runner 上直接构建。两条可行路径：

- **路径 1（采用）**：在装有 HBuilderX 的 macOS 构建机上，用 HBuilderX 自带 CLI 发布到微信小程序：

  ```bash
  # 构建机需预先安装 HBuilderX 并完成项目「发行 → 小程序-微信」首次配置
  HBX=/Applications/HBuilderX.app/Contents/MacOS/cli

  # 1) 打开/注册项目
  $HBX project open --path /Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-uniapp-vue3

  # 2) 发布到微信小程序（输出到 unpackage/dist/build/mp-weixin）
  $HBX publish --platform mp-weixin --project yshop-drink-uniapp-vue3

  # 3) 产物校验
  ls -l unpackage/dist/build/mp-weixin/app.json
  ls -l unpackage/dist/build/mp-weixin/project.config.json
  ```

- **路径 2（工程化改造，可选）**：迁移为 uni-app CLI 工程（新增 `src/` 目录、`vite.config.js`、`@dcloudio/vite-plugin-uni` 等依赖），从而接入标准 CI。**改造会动全部源码目录结构，风险高，不建议在首发窗口做**，可作为首发后的技术债任务。

**上传与提交审核**（微信官方 CI 工具 `miniprogram-ci`，需以官方最新文档为准）：

```bash
npm i -g miniprogram-ci
cat > /tmp/mp-ci.js <<'EOF'
const ci = require('miniprogram-ci')
const project = new ci.Project({
  appid: process.env.WX_MINIAPP_APPID,
  type: 'miniProgram',
  projectPath: 'yshop-drink-uniapp-vue3/unpackage/dist/build/mp-weixin',
  privateKeyPath: process.env.WX_MINIAPP_PRIVATE_KEY_PATH,  // 私钥不入库，CI 变量注入
  ignores: ['node_modules/**', '.git/**']
})
ci.upload({
  project,
  version: process.env.APP_VERSION,          // 1.0.0
  desc: process.env.APP_DESC,                // 集团特色菜订餐 v1.0.0
  robot: 1,                                   // 机器人序号 1~20
  setting: { es6: true, es7: true, minify: true, codeProtect: false }
}).then(() => console.log('upload ok')).catch(e => { console.error(e); process.exit(1) })
EOF
WX_MINIAPP_APPID=wx... node /tmp/mp-ci.js
```

**上传前必须改的两处**（否则审核必被拒）：

```jsonc
// yshop-drink-uniapp-vue3/manifest.json
"mp-weixin": {
    "appid": "<集团正式小程序 appid>",     // 当前为测试号 wx001e2dc50bf532df
    "setting": { "urlCheck": true },        // 当前 false；正式包必须开启域名校验
    "usingComponents": true,
    "permission": { "scope.userLocation": { "desc": "定位最近的门店" } },
    "requiredPrivateInfos": [ "getLocation", "chooseLocation" ]   // 需在隐私保护指引中声明
}
```

> `urlCheck: false` 仅在微信开发者工具中生效，正式版微信会强制开启合法域名校验；**但保留 false 会让「本地无域名也能跑」的假象掩盖白名单漏配**，发布前必须置 `true` 并用真机验证。

```js
// yshop-drink-uniapp-vue3/config/index.js
const DEV_API_URL  = 'https://test-api.group.com/app-api'
const PROD_API_URL = 'https://api.group.com/app-api'    // 原 https://apidc.yixiang.co/app-api
export const APP_ID = '<集团公众号/小程序 appid>'      // 原 wxdbdbc123c8c30b45
```

### 2.4 制品版本号与可追溯性

**版本号规范**：`主.次.修订`（本项目首发 `1.0.0`）。对应关系：

| 制品 | 版本来源 | 落地位置 |
|---|---|---|
| 后端 | `-Drevision=1.0.0` | jar 内 `BOOT-INF/classes/application.yaml` 的 `yshop.info.version`；镜像 tag `yshop-server:1.0.0` |
| 管理后台 | `VITE_APP_VERSION`（写入 `.env`） | `dist-prod/version.json` |
| 小程序 | `manifest.json` 的 `versionName`/`versionCode` | 微信后台版本号 |

**Git Tag 与 commit 绑定**：

```bash
cd /Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink
git tag -a v1.0.0 -m "Release 1.0.0 集团特色菜订餐首发" <commit-sha>
git push origin v1.0.0
```

**Checksum 与清单**（每个制品生成，随发布单归档）：

```bash
# 后端 jar
shasum -a 256 yshop-drink-boot3/yshop-server/target/yshop-server.jar | tee artifacts/yshop-server-1.0.0.jar.sha256

# 管理后台（对打包产物整体计算，确保可复现校验）
find yshop-drink-vue3/dist-prod -type f -exec shasum -a 256 {} \; | sort > artifacts/admin-1.0.0.sha256

# 镜像（digest 是唯一不可变标识，生产部署以 digest 锁定）
docker inspect --format='{{index .RepoDigests 0}}' harbor.group.com/order/yshop-server:1.0.0 | tee artifacts/yshop-server-1.0.0.digest

# 制品清单
cat > artifacts/release-1.0.0.manifest.json <<'EOF'
{
  "version": "1.0.0",
  "git_tag": "v1.0.0",
  "git_commit": "<commit-sha>",
  "build_time": "<ISO8601>",
  "artifacts": {
    "backend_jar":   {"path": "yshop-server-1.0.0.jar",           "sha256": "<...>"},
    "backend_image": {"ref": "harbor.group.com/order/yshop-server@sha256:<digest>"},
    "admin_dist":    {"path": "dist-prod/",                        "sha256_manifest": "admin-1.0.0.sha256"},
    "miniapp":       {"path": "unpackage/dist/build/mp-weixin",    "sha256_manifest": "miniapp-1.0.0.sha256", "appid": "<wx...>"}
  }
}
EOF
```

**制品唯一性纪律**：生产运行的包**必须**来自 CI 产出的同一制品，**禁止本地打包直传生产**；生产部署一律用 **镜像 digest**（非 tag）锁定，保证回滚目标与灰度目标字节级一致。

---

## 3. 数据库变更

### 3.1 现状与基线策略

- 现状：94 张表已由 `yshop-drink-boot3/sql/yixiang-drink-open.sql` 一次性导入，**不在 Flyway 管理下**；种子数据含 530 菜单 / 11 商品 / 7 订单 / 2 门店 / 3 管理账号。
- 集团生产环境若沿用「手工导入 SQL」的方式，将彻底失去变更可追溯性 —— **必须引入 Flyway**。

**引入步骤**：

1. 引入依赖（`yshop-server/pom.xml` 或 `yshop-dependencies/pom.xml`）：

   ```xml
   <dependency>
       <groupId>org.flywaydb</groupId>
       <artifactId>flyway-core</artifactId>
   </dependency>
   <dependency>
       <groupId>org.flywaydb</groupId>
       <artifactId>flyway-mysql</artifactId>   <!-- MySQL 支持，版本随 Spring Boot BOM 管理 -->
   </dependency>
   ```

   > Spring Boot 3.2.2 BOM 管理 `flyway-core` 版本，**不要**手动指定版本号，避免与 BOM 不一致。

2. 配置见 §1.4.2 的 `spring.flyway` 段（`baseline-on-migrate: true` + `baseline-version: 0` + `clean-disabled: true`）。

3. **基线语义**：`baseline-on-migrate=true` 时，Flyway 发现目标 schema 非空且无 `flyway_schema_history` 表，会在版本 `0` 处建立基线，**不校验既有 94 表**，随后执行 `V1` 及以后的迁移。因此第一个迁移脚本必须是**只读校验**，而不是结构修改。

4. 现有 `yshop-module-*/src/test/resources/sql/create_tables.sql` 属测试用，**生产不得执行**（Flyway 接管后它们仅用于单测）。

### 3.2 迁移脚本目录约定

```
yshop-drink-boot3/yshop-server/src/main/resources/db/
├── migration/                                  # Flyway 自动执行（升序）
│   ├── V20260101001__baseline_verify_94_tables.sql
│   ├── V20260101002__add_store_contact_phone.sql
│   └── ...
├── rollback/                                   # 手工回滚脚本（Flyway Community 不支持自动 undo）
│   ├── V20260101002__add_store_contact_phone.down.sql
│   └── ...
└── seed/                                       # 生产种子数据（菜单/角色/门店），幂等 upsert
    └── R20260101001__group_store_seed.sql
```

命名规则：`V{yyyyMMddHHmm}__{snake_case 描述}.sql`，版本号全局单调递增，**已发布脚本严禁修改**（改了就等于改了历史 → `validate-on-migrate` 会失败并阻断启动）。

`V20260101001__baseline_verify_94_tables.sql` 示例（只读校验，不改结构）：

```sql
-- 校验集团生产基线表齐全；缺失则让 Flyway 迁移失败，阻断应用启动
SET @missing := (
  SELECT COUNT(*) FROM (
    SELECT 'system_users' t UNION ALL SELECT 'yshop_store' UNION ALL
    SELECT 'yshop_store_product' UNION ALL SELECT 'yshop_store_order' UNION ALL
    SELECT 'yshop_store_order_coupon' UNION ALL SELECT 'pay_order' UNION ALL
    SELECT 'pay_notify_task' UNION ALL SELECT 'infra_config'
  ) x
  LEFT JOIN information_schema.TABLES t
    ON t.TABLE_SCHEMA = DATABASE() AND t.TABLE_NAME = x.t
  WHERE t.TABLE_NAME IS NULL
);
SET @msg = CONCAT('基线表缺失数=', @missing);
-- MySQL 无法直接 SIGNAL 于脚本中，用触发方式抛错：
DROP PROCEDURE IF EXISTS baseline_assert;
DELIMITER $$
CREATE PROCEDURE baseline_assert()
BEGIN
  IF (SELECT COUNT(*) FROM information_schema.TABLES
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN
      ('system_users','yshop_store','yshop_store_product','yshop_store_order','pay_order','pay_notify_task','infra_config')
  ) < 7 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '基线表缺失，拒绝启动';
  END IF;
END$$
DELIMITER ;
CALL baseline_assert();
DROP PROCEDURE baseline_assert;
```

### 3.3 utf8mb3 → utf8mb4 转换（28/94 表）

#### 3.3.1 前置检查（必须先跑，产出影响评估）

```sql
-- 1) 列出仍为 utf8mb3 的表 + 行数 + 表大小 + 行格式
SELECT t.TABLE_NAME, t.TABLE_ROWS,
       ROUND((t.DATA_LENGTH + t.INDEX_LENGTH)/1024/1024, 2) AS size_mb,
       t.ROW_FORMAT, t.ENGINE, t.TABLE_COLLATION
FROM information_schema.TABLES t
WHERE t.TABLE_SCHEMA = DATABASE()
  AND t.TABLE_COLLATION LIKE 'utf8mb3%'
ORDER BY size_mb DESC;

-- 2) 检查是否存在 FULLTEXT 索引（决定能否用 INPLACE/LOCK=NONE）
SELECT DISTINCT TABLE_NAME, INDEX_NAME, INDEX_TYPE
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND INDEX_TYPE = 'FULLTEXT';

-- 3) 检查索引前缀长度（utf8mb3→utf8mb4 后 3 字节变 4 字节，键长可能超限）
SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME, SUB_PART
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND SUB_PART IS NOT NULL;

-- 4) 检查是否已有 4 字节字符被截断的迹象（utf8mb3 下 emoji 会存成 '?'）
SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND CHARACTER_SET_NAME = 'utf8mb3'
  AND CHARACTER_MAXIMUM_LENGTH > 0;
```

#### 3.3.2 转换脚本（按表逐个执行，禁止一次性全库跑）

```sql
-- 单表转换（InnoDB + DYNAMIC 行格式）
ALTER TABLE `yshop_store_product`
  CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci,
  ALGORITHM=INPLACE, LOCK=NONE;

-- 若报 "ALGORITHM=INPLACE is not supported"（常见于含 FULLTEXT 索引或列类型转换），
-- 退化为 pt-online-schema-change（需在 10.20.10.x 运维区安装 Percona Toolkit）
-- pt-online-schema-change \
#   --alter "CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci" \
#   --host=10.20.20.11 --user=yshop_migrate --ask-pass \
#   D=yixiang-drink_open,t=yshop_store_product \
#   --execute --chunk-size=1000 --max-load Threads_running=50 \
#   --critical-load Threads_running=100 --sleep 0.2 --retry 3 --execute

-- 库与连接默认字符集也要改
ALTER DATABASE `yixiang-drink_open`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```

> 排序规则选择：MySQL 8.4 默认 `utf8mb4_0900_ai_ci`；若集团生产为 MySQL 5.7/8.0，需改用 `utf8mb4_general_ci` 或 `utf8mb4_unicode_ci`。**具体以集团目标 MySQL 版本的官方文档为准**。

#### 3.3.3 锁风险与规避

| 风险 | 表现 | 规避 |
|---|---|---|
| **元数据锁（MDL）** | `ALTER TABLE` 等不到 MDL 时，后续所有对该表的查询排队 → 表面「数据库卡死」 | 执行前 `SET SESSION lock_wait_timeout = 10;`（秒）**快速失败**，不拖垮全库；应用侧连接池设 `max-active: 20` |
| **长事务阻塞 MDL** | 一个未提交的长事务会让 DDL 一直等待 | 上线窗口前执行 `SELECT * FROM information_schema.innodb_trx WHERE trx_started < NOW() - INTERVAL 10 SECOND;` 确认无长事务 |
| **INPLACE 重建耗时** | 大表 copy 期间 IO 打满 | 逐表、低峰期；表 > 1GB 一律走 pt-osc |
| **索引键超限** | 旧行格式（COMPACT/REDUNDANT）下 `VARCHAR(255)` utf8mb4 = 1020 字节 > 767 → `Specified key was too long` | 先 `ALTER TABLE t ROW_FORMAT=DYNAMIC;` 再转换；或缩短索引前缀 |
| **字符集回退不可逆** | 转回 utf8mb3 会丢 4 字节字符 | 转换前完成 §3.4 全量备份；转换后**立即**校验不可逆 |
| **FULLTEXT 索引表** | 无法 INPLACE/LOCK=NONE | pt-osc；或先删 FULLTEXT 索引再转（需评估检索功能） |

执行顺序建议：**先转无索引/小表 → 再转大表 → 最后转含 FULLTEXT 表**；每转完一张立即校验。

```sql
-- 转换后校验
SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_COLLATION LIKE 'utf8mb3%';
-- 期望：0 行

-- 数据抽查（emoji 与生僻字是否正常）
SELECT id, name FROM yshop_store_product WHERE name REGEXP '[^\\x00-\\x7F]' LIMIT 10;
```

### 3.4 大表变更与备份

**上线前强制备份（发布单前置条件）**：

```bash
# 逻辑备份（生产全量 + 校验）
mysqldump --single-transaction --routines --triggers --events \
  --set-gtid-purged=OFF --default-character-set=utf8mb4 \
  -h 10.20.20.11 -P 3306 -u yshop_backup -p \
  yixiang-drink_open | gzip > backup/yixiang-drink_open_$(date +%Y%m%d_%H%M%S).sql.gz

# 校验备份可恢复（不能只看文件大小）
gzip -t backup/yixiang-drink_open_*.sql.gz && echo "压缩包完整"
zcat backup/yixiang-drink_open_*.sql.gz | grep -c 'CREATE TABLE'   # 期望 >= 94
```

同时要求：**开启 binlog 且 `binlog_format=ROW`**（用于 PITR 精确回滚）；生产开启自动备份（保留 ≥7 天）+ 每日全量 + binlog 增量。

---

## 4. 微信小程序发布链路

### 4.1 企业主体注册与认证

| 项 | 要求 | 说明 |
|---|---|---|
| 主体类型 | **企业**（集团主体） | 个人主体无法开通微信支付、无法使用餐饮类目部分能力 |
| 注册 | `mp.weixin.qq.com` → 立即注册 → 小程序 | 需邮箱（未注册过公众平台的）、营业执照、法定代表人身份证、管理员微信 |
| 主体认证 | 微信认证（企业认证） | 需对公账户打款验证或法人人脸核验；**认证费用与年审规则以微信官方最新文档为准** |
| 名称 | 「XX 集团特色菜订餐」 | 名称需与营业执照/商标不冲突；**不得出现「测试」「Demo」「意象」等** |
| 主体信息一致性 | 营业执照、法人、结算账户三者一致 | 不一致是驳回高发项 |
| 开发者绑定 | 绑定开发/体验成员并配权限 | 至少 2 名，避免单点离职失联 |

> 时间预估：企业注册 + 认证 **1~3 个工作日**；名称审核另需 1~2 天。**此项必须最先启动**，是全链路最长前置。

### 4.2 类目选择与资质

餐饮点餐类目需要准备的资质（**具体类目名称与所需材料以微信小程序官方最新类目文档为准**）：

| 资质材料 | 要求 | 备注 |
|---|---|---|
| 《食品经营许可证》 | 企业主体、经营范围与实际供餐业务匹配、有效期覆盖上线后 | 直营门店模式，许可证主体应与小程序主体一致（不一致需出具授权书） |
| 营业执照 | 有效期内 | 经营范围含「餐饮服务/食品销售」 |
| 门店资质 | 各门店的许可证编号 | 若后台支持多门店，建议在管理端维护门店资质字段供核查 |
| 小程序类目 | 「餐饮服务 → 点餐/餐饮服务」相关类目 | **类目选错是首发被拒主因**；另可加「工具/效率」辅助类目 |
| ICP 备案号 | 与主体一致 | 见 §4.3 |

**类目选择建议**：主线只保留**一个**餐饮点餐类目 + 必要的辅助类目。**不要**同时申请电商类目（一旦挂上电商类目，会触发 EDI/平台资质要求与更严的交易保证金规则）。

### 4.3 服务器域名备案与 HTTPS 证书

**域名清单（一次配齐，避免每月限额内反复改）**：

| 用途 | 域名 | 小程序后台配置项 |
|---|---|---|
| API 请求 | `api.group.com` | **request 合法域名** |
| 文件上传 | `api.group.com` | **uploadFile 合法域名** |
| 文件下载 | `cdn.group.com`（或 `api.group.com`） | **downloadFile 合法域名** |
| WebSocket | `wss://api.group.com` | socket 合法域名（若启用） |
| 管理后台 | `admin.group.com` | — |
| H5 | `h5.group.com` | —（web-view 业务域名需单独配） |

**要求与验证**：

```bash
# 1) 备案核验（工信部 ICP）
curl -s "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryByCondition" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'unitName=group.com&serviceType=1' | head -c 500
# 期望：返回备案号，且备案主体 = 集团主体

# 2) HTTPS 证书链完整性（部分安卓机型对缺链证书直接报错）
echo | openssl s_client -connect api.group.com:443 -servername api.group.com -showcerts 2>/dev/null \
  | grep -c 'BEGIN CERTIFICATE'
# 期望 >= 2（叶子 + 中间证书）

# 3) 证书有效期与域名覆盖
echo | openssl s_client -connect api.group.com:443 -servername api.group.com 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName

# 4) TLS 版本与套件（禁用 TLS 1.0/1.1）
openssl s_client -connect api.group.com:443 -tls1_1 </dev/null 2>&1 | grep -i 'alert\|failure'   # 期望：握手失败
```

| 项 | 要求 |
|---|---|
| 备案 | 大陆服务器**必须** ICP 备案完成并生效后才能解析上线；备案期间可用境外/香港服务器临时验证，**正式上线必须备案** |
| 证书类型 | DV/EV 均可；建议 DV + 自动化续期（Let's Encrypt 或云厂商证书服务） |
| 到期监控 | 配置到期前 **30 天 / 7 天**双重告警（对接运维守护师方案） |
| HSTS | 建议 `Strict-Transport-Security: max-age=31536000` |
| 微信白名单生效 | 后台配置后需等待生效，**当天配置次日才可提审**，不要压着截止时间做 |
| 域名修改限额 | 微信后台合法域名每月修改次数有限，**一次配齐** |

### 4.4 微信支付商户号与权限

| 项 | 要求 | 检查点 |
|---|---|---|
| 商户号（mchid） | 申请微信支付商户号，主体与小程序一致或已完成「关联商户号」 | 商户平台 → 产品中心 → AppID 授权 |
| 支付权限 | 餐饮类目下开通「JSAPI 支付」；若开通「服务商模式」需另配 | **具体类目权限以商户平台实际可选为准** |
| APIv3 密钥 | 商户平台设置，32 位 | 存 KMS，不入库 |
| 平台证书 / API 证书 | `apiclient_cert.p12`、`apiclient_key.pem`、平台证书 | 存 KMS；注意 `apiclient_key.pem` **绝不进代码库** |
| 回调地址 | `https://api.group.com/app-api/order/notify/order`（订单）、`.../refund`（退款） | **必须公网可达 + HTTPS + 在商户平台白名单内**；替换掉仓库里的 `http://yshop.natapp1.cc` |
| 回调幂等 | yshop 有 `pay_notify_task` 表；确认重复回调不重复发货/退款 | 上线前做「重复回调」专项用例 |
| 退款 | 需开通退款权限，`yshop.pay.refund-notify-url` 同步替换 | |

**支付沙箱与真钱验证顺序**：先在沙箱/小额真金（0.01 元）走通「下单 → 支付 → 回调 → 订单状态流转 → 退款」，再放量。**支付成功率是本次发布的最高优先级观察指标**。

### 4.5 小程序审核注意事项

| 审核维度 | 风险点 | 应对 |
|---|---|---|
| **类目与资质** | 餐饮类目资质不齐 / 类目选错 | 见 §4.2，**首发被拒主因** |
| **功能完整性** | 空白页、占位功能、「敬请期待」、测试菜单 | 提审前逐页走查；**把未完成的营销/分销/多商家入驻入口从菜单中移除**（yshop 默认带 score/coupon/marketing 模块） |
| **品牌残留** | 页面出现「意象点餐 / yixiang / 奶爸」等上游品牌 | 全量替换品牌文案、Logo、版权信息（`yshop.info`、`.env` 的 `VITE_APP_TITLE`、`pages.json` 标题、隐私政策主体） |
| **隐私合规** | `manifest.json` 声明了 `requiredPrivateInfos: ["getLocation","chooseLocation"]` | 必须在《用户隐私保护指引》中声明「位置信息」及用途；后台「用户隐私保护指引」需填写并生效 |
| **权限最小化** | `app-plus.permissions` 里申请了相机/定位/读写存储/读取手机状态等 | 小程序侧只保留定位；`scope.userLocation.desc` 文案需具体说明用途（当前「定位最近的门店」合格） |
| **登录与演示** | 需要登录才能看到的功能，审核员无法进入 | **在审核备注中提供演示账号 + 密码**（这是提审技巧的核心） |
| **支付合规（虚拟支付）** | 见下方专项 | 集团内部实物点餐**不触发**虚拟支付限制，但须清理虚拟商品入口 |
| **诱导分享/关注** | 分享得优惠、关注才能下单 | 关闭诱导分享文案与强关注门槛 |
| **UGC** | 评价/留言需举报与屏蔽能力 | yshop 有评价模块；上线前需提供举报入口 + 敏感词过滤 + 黑名单 |
| **ICP 备案展示** | 小程序「关于」页需展示备案号 | 集团备案号写入小程序关于页 |
| **客服** | 需提供客服联系方式 | 填写集团客服电话 |

**虚拟支付政策专项说明（重要，需提前告知）**：

- 微信小程序在 **iOS 端不允许虚拟支付**（实物/服务不受限）——这是平台对数字内容购买的限制。
- 本项目售卖的是**实物餐饮菜品**，属实物交易，**正常走微信支付，不触发虚拟支付限制**。集团内部点餐场景（员工用餐报销）亦然。
- **但仍需清理以下虚拟商品入口，否则可能被判定违规甚至下架**：
  1. yshop 的 **score（积分）模块**中的「积分兑换商品 / 积分抵现」；
  2. **member（会员）模块**中的「余额充值 / 储值卡 / 会员储值」；
  3. 任何「充值后余额支付」的入口。
- 处置方式：集团上线版本**关闭积分商城与余额充值入口**（管理端菜单置为不展示），积分仅作为消费累积展示（积分明细/等级），不做可兑换虚拟权益。
- 若后续要卖「会员储值卡」，须单独做政策评估并准备 iOS 侧差异化方案（提审时可能需提供 iOS 端关闭入口的证明）。

### 4.6 灰度发布与回滚（小程序端）

**版本流转**：

```
开发版（开发者工具上传，CI 自动上传）
   → 体验版（设置体验成员，内部 10~20 人全链路试用 ≥1 个工作日）
   → 审核版（提交审核，1~7 天，需预留被拒重提一次的时间）
   → 线上版（审核通过后发布，可按比例分阶段放量）
```

**灰度放量节奏**：

| 阶段 | 放量比例 | 观察时长 | 推进条件 |
|---|---|---|---|
| 阶段 1 | 5% | 2 小时 | 错误率 < 1%、支付成功率 ≥ 99%、无 P0 |
| 阶段 2 | 20% | 4 小时 | 同上 + 下单转化跌幅 < 20% |
| 阶段 3 | 50% | 24 小时 | 同上 + 客诉量无异常 |
| 阶段 4 | 100% | 72 小时观察 | — |

> 微信后台「版本管理」支持按比例发布（分阶段发布）。**首发冷启动无存量用户**，若集团决定直接全量，需说明理由（无存量流量冲击、可快速回退、且前后端已完整冒烟）——**推荐仍走 5%→20%→50%→100%**，因为首发同样要验证真实用户路径（定位、支付、退款）。

**小程序回滚的现实约束**：已发布的小程序版本**无法物理回滚**到旧代码。因此：

1. **服务端必须向后兼容旧版小程序 ≥2 个版本**（参考手册第九章第 4 条），所有新接口以新增为主、**不删除/不改变旧接口语义**；
2. **新功能一律加开关**：用 `infra_config` 表做功能开关，出问题时改配置秒级关闭（无需发版）；
3. 微信后台支持**版本回退**（回退到上一个线上版本），作为最后手段：

   ```sql
   -- 功能开关示例：下单入口开关，出问题立即置 0
   INSERT INTO infra_config (category, name, key, value, visible, remark, creator, create_time, updater, update_time, deleted)
   VALUES ('order','订单入口开关','order.entry.enabled','1',1,'订单入口总开关，出问题置0',1,NOW(),1,NOW(),0)
   ON DUPLICATE KEY UPDATE `value` = '0', update_time = NOW();
   ```

4. 若新版本依赖了旧版没有的接口，回滚服务端**不能**退到旧版代码（会 404）——所以**发布顺序必须是：先发布兼容的新服务端 → 再提审新小程序**，且服务端保留至少 2 个版本。

---

## 5. CI/CD 流水线

### 5.1 阶段定义与卡点

| # | 阶段 | 工具/命令 | 卡点（不通过则阻断下游） |
|---|---|---|---|
| 1 | **Lint / 静态检查** | 后端 `mvn -B checkstyle:check`（可选）；管理端 `pnpm lint:eslint` + `pnpm ts:check` | ESLint 0 error；`vue-tsc` 0 error |
| 2 | **密钥与合规扫描** | `gitleaks detect --exit-code 1`；`trivy fs --severity HIGH,CRITICAL --exit-code 1 .` | 0 个未豁免的高危泄露/CVE |
| 3 | **单元测试** | `mvn -B test`（surefire 3.2.2） | 测试通过率 100%，失败即阻断 |
| 4 | **构建后端制品** | `mvn -B -T 1C -Drevision=$APP_VERSION clean package` + **字节码版本断言** | `major version` 必须 = 65（21）或 61（17），与运行时 JRE 匹配 |
| 5 | **构建镜像** | `docker build -t harbor.group.com/order/yshop-server:$APP_VERSION .` | 构建成功；镜像扫描无 HIGH/CRITICAL |
| 6 | **推送制品仓库** | `docker push` + `docker buildx imagetools inspect` 取 digest | digest 已写入 `release manifest` |
| 7 | **构建管理后台 / 小程序** | `pnpm build:prod`；HBuilderX CLI `publish --platform mp-weixin` | 产物存在且清单校验通过 |
| 8 | **部署开发环境** | 自动 | 自动冒烟通过 |
| 9 | **部署测试环境** | 自动 | **自动化回归全绿**（qa-tester 门禁） |
| 10 | **人工确认 → 部署预发** | 人工 | 预发冒烟 + 支付沙箱走通 |
| 11 | **发布审批** | 人工（发布单 + 清单全绿） | **双人复核**：发布负责人 + QA + 运维各 1 人 |
| 12 | **生产灰度部署** | 蓝绿/滚动 + 5% 流量 | 冒烟 + 监控指标达标 |
| 13 | **小程序提审** | `miniprogram-ci` 上传 + 后台提交审核 | 审核通过 |
| 14 | **全量 + 72h 观察** | 逐步放量 | 见 §9 |

### 5.2 GitLab CI 示例（`.gitlab-ci.yml`）

```yaml
stages: [lint, test, build, scan, deploy-dev, deploy-test, deploy-staging, approve, deploy-prod]

variables:
  APP_VERSION: "1.0.0"
  IMAGE: harbor.group.com/order/yshop-server
  MAVEN_OPTS: "-B -T 1C -Dmaven.repo.local=$CI_PROJECT_DIR/.m2"

.backend-base: &backend-base
  image: maven:3.9-eclipse-temurin-21
  cache:
    key: "$CI_COMMIT_REF_SLUG-maven"
    paths: [.m2/repository]

.lint:
  stage: lint
  image: node:20-alpine
  before_script:
    - corepack enable && corepack prepare pnpm@8 --activate
  script:
    - cd yshop-drink-vue3 && pnpm install --frozen-lockfile && pnpm lint:eslint && pnpm ts:check
  rules: [ { if: '$CI_PIPELINE_SOURCE == "merge_request_event"' } ]

.scan-secrets:
  stage: lint
  image: zricethezav/gitleaks:latest
  script:
    - gitleaks detect --source . --redact --report-path gitleaks.json --exit-code 1
  rules: [ { if: '$CI_PIPELINE_SOURCE == "merge_request_event"' } ]

.test-backend:
  <<: *backend-base
  stage: test
  script:
    - cd yshop-drink-boot3 && mvn $MAVEN_OPTS test
  artifacts:
    when: always
    paths: [yshop-drink-boot3/**/target/surefire-reports/]
  rules: [ { if: '$CI_PIPELINE_SOURCE == "merge_request_event"' } ]

.build-backend:
  <<: *backend-base
  stage: build
  script:
    - cd yshop-drink-boot3
    - mvn $MAVEN_OPTS -Drevision=$APP_VERSION clean package
    # 字节码版本断言（Java 21 = major 65）
    - unzip -p yshop-server/target/yshop-server.jar BOOT-INF/classes/co/yixiang/yshop/server/YshopServerApplication.class > /tmp/Main.class
    - javap -verbose /tmp/Main.class | grep -E 'major version' | grep -q '65' || { echo "FAIL: 字节码版本不是 65(Java21)"; exit 1; }
    # 生产配置无明文密钥
    - unzip -p yshop-server/target/yshop-server.jar BOOT-INF/classes/application-prod.yaml \
      | grep -nE "(password|secret|api-key):\s*[A-Za-z0-9/+_=.-]{8,}" && { echo "FAIL: 明文密钥"; exit 1; } || true
    - shasum -a 256 yshop-server/target/yshop-server.jar > yshop-server-$APP_VERSION.jar.sha256
  artifacts:
    paths: [yshop-drink-boot3/yshop-server/target/yshop-server.jar, yshop-server-$APP_VERSION.jar.sha256]

.scan-image:
  stage: scan
  image: aquasec/trivy:latest
  script:
    - trivy image --severity HIGH,CRITICAL --exit-code 1 $IMAGE:$APP_VERSION

.deploy-prod:
  stage: deploy-prod
  when: manual
  environment:
    name: production
    url: https://api.group.com
  script:
    - echo "$DEPLOY_TOKEN" | docker login harbor.group.com -u $CI_REGISTRY_USER -p --stdin
    - docker pull $IMAGE:$APP_VERSION
    # 生产以 digest 锁定
    - DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' $IMAGE:$APP_VERSION)
    - cd deploy && ./deploy.sh $DIGEST
    - ./smoke.sh https://api.group.com
  rules: [ { if: '$CI_COMMIT_TAG == "v$APP_VERSION"' } ]
```

### 5.3 制品仓库与生产编排

- **制品仓库**：Harbor / Nexus。命名规范 `harbor.group.com/order/<组件>:<版本>`，启用**不可变 tag**（同 tag 禁止覆盖推送）+ 镜像签名（cosign）+ 保留策略（最近 30 个版本，**至少保留上一稳定版本 ≥7 天**）。
- **生产编排目录（新建，不复用仓库里失效的 `script/docker/docker-compose.yml`）**：

  ```
  deploy/
  ├── docker-compose.prod.yml
  ├── .env.example          # 仅变量名，无真实值
  ├── nginx/
  │   ├── nginx.conf
  │   └── admin.conf
  ├── deploy.sh             # 滚动/蓝绿发布脚本
  ├── rollback.sh           # 回滚脚本（见 §6.3）
  └── smoke.sh              # 冒烟脚本
  ```

  `deploy/docker-compose.prod.yml` 关键段（密钥全部走环境变量，`.env` 由 KMS 注入，文件权限 600 且不入库）：

  ```yaml
  services:
    server:
      image: ${SERVER_IMAGE}          # harbor.group.com/order/yshop-server@sha256:<digest>
      restart: always
      ports: ["48081"]
      environment:
        SPRING_PROFILES_ACTIVE: prod
        SERVER_PORT: "48081"
        JAVA_OPTS: "-XX:MaxRAMPercentage=75.0 -XX:+UseZGC -XX:+ExitOnOutOfMemoryError"
        DB_MASTER_URL: ${DB_MASTER_URL}
        DB_MASTER_USER: ${DB_MASTER_USER}
        DB_MASTER_PASSWORD: ${DB_MASTER_PASSWORD}
        DB_SLAVE_URL: ${DB_SLAVE_URL}
        DB_SLAVE_USER: ${DB_SLAVE_USER}
        DB_SLAVE_PASSWORD: ${DB_SLAVE_PASSWORD}
        REDIS_HOST: ${REDIS_HOST}
        REDIS_PORT: "6379"
        REDIS_PASSWORD: ${REDIS_PASSWORD}
        WX_MINIAPP_APPID: ${WX_MINIAPP_APPID}
        WX_MINIAPP_SECRET: ${WX_MINIAPP_SECRET}
        PAY_ORDER_NOTIFY_URL: ${PAY_ORDER_NOTIFY_URL}
        PAY_REFUND_NOTIFY_URL: ${PAY_REFUND_NOTIFY_URL}
      volumes:
        - ys_file:/data/file
        - ys_log:/data/logs
      deploy:
        replicas: 2
        update_config:
          order: start-first          # 滚动：先起新再停旧
          parallelism: 1
          failure_action: rollback
          max_surge: 1
          max_unavailable: 0
      healthcheck:
        test: ["CMD-SHELL","curl -fsS http://127.0.0.1:48081/actuator/health/readiness || exit 1"]
        interval: 15s
        timeout: 5s
        retries: 4
        start_period: 60s
      logging:
        driver: json-file
        options: { max-size: "500m", max-file: "10" }
  ```

- **中间件版本钉死**（对齐实测版本）：`mysql:8.4.11`、`redis:8.10.3-alpine`；生产 MySQL 用云 RDS 或自建 + 主从 + 定时备份；Redis **必须开启 `requirepass`** 且绑定内网 + `rename-command FLUSHALL ""` 等加固。

---

## 6. 发布策略与回滚

### 6.1 三种策略对比与选择

| 策略 | 优点 | 缺点 | 本项目适用性 |
|---|---|---|---|
| **蓝绿（Blue-Green）** | 回滚极快（切 Nginx upstream，<10 秒）；新旧并存便于对比 | 资源双倍成本；需处理会话/DB 状态同步 | ✅ **管理后台静态**采用（版本目录 + 软链切换，秒级回退）；✅ **预发/生产后端**在发布窗口采用（2 组 × 2 副本） |
| **滚动（Rolling）** | 资源占用低、无需双倍 | 回滚较慢；新旧版本共存期需接口兼容；滚动中途失败处理复杂 | ✅ **生产后端**主选（`start-first` 策略，`max_unavailable: 0`，保证 100% 可用容量） |
| **灰度（Canary）** | 风险最低、可按比例/按标签精确控制 | 需分流能力；小流量下指标噪声大 | ✅ **流量层**采用（Nginx `split_clients` 按 userId 哈希分流）；✅ **小程序端**采用（微信后台按比例发布） |

**本项目最终选择**：

- 后端生产：**滚动 + 灰度切流**组合 —— 先用 Nginx `split_clients` 把 5% 流量导向新版本实例（灰度组），观察 2 小时达标后再滚动替换全部实例。
- 管理后台：**蓝绿（版本目录 + 软链）** —— 发布 = 解包新版本目录 → 切 `current` 软链 → `nginx -s reload`；回滚 = 切回旧软链，**3 秒完成**。
- 小程序：**微信后台按比例分阶段发布**。
- 数据库：**expand-contract（先加后删）**，禁止破坏性变更。

Nginx 灰度分流示例：

```nginx
upstream yshop_api {
    server 10.20.10.11:48081 weight=95 max_fails=2 fail_timeout=10s;  # 稳定组
    server 10.20.10.12:48081 weight=5  max_fails=2 fail_timeout=10s;  # 灰度组
    keepalive 64;
}
# 精细灰度（按用户 ID 哈希稳定分桶，避免同一用户来回跳）
split_clients "${http_x_user_id}" $variant {
    5%  "10.20.10.12:48081";
    *   "10.20.10.11:48081";
}
server {
    listen 443 ssl http2;
    server_name api.group.com;
    location / {
        proxy_pass http://$variant;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }
}
```

### 6.2 数据库变更与代码发布的顺序（兼容矩阵）

**总原则**：**先 DB（expand，向后兼容）→ 后代码 → 最后 DB（contract，延后一个版本）**。

| 变更类型 | 顺序 | 说明 | 是否可回滚代码 |
|---|---|---|---|
| 新增表 | **先 DB，后代码** | 代码依赖表存在 | ✅ 可回滚代码，表留着无害 |
| 新增可空列 / 有默认值列 | **先 DB，后代码** | 旧代码 `SELECT *` 不受影响；MyBatis-Plus 实体不全量映射亦安全 | ✅ 可回滚代码 |
| 加索引 | **先 DB，后代码** | 需在线 DDL；注意 MDL 与 IO | ✅ 可回滚代码（索引留着） |
| 新增枚举值 / 字典项 | **先 DB（字典表），后代码** | 代码读字典，不硬编码 | ✅ 可回滚代码 |
| 修改列类型 / 长度 | **分两次发布** | 第一次加新列双写；第二次切读；第三次删旧列 | ⚠️ 需谨慎 |
| **删除/重命名列** | **禁止在首发窗口做** | 必须分三次发布（expand → migrate → contract），contract 延后 1~2 个版本 | ❌ 代码回滚会因列不存在而失败 |
| 修改接口语义/删接口 | **禁止在首发窗口做** | 新旧客户端共存期必炸 | ❌ |

**本次首发（v1.0.0）的 DB 动作仅限**：
1. 建立 Flyway 基线（`baseline-on-migrate`）；
2. utf8mb3 → utf8mb4 转换（**纯字符集扩展，语义不变，代码无需改**）；
3. 生产种子数据（门店、菜单权限、角色）用幂等 upsert 脚本。

> **首发即「首战」**：所有结构性变更（新增列/表）允许「先 DB 后代码」；所有删除性变更一律推迟到 v1.1.0 之后，且必须走 expand-contract 三步法。

### 6.3 回滚触发条件与回滚预案

#### 6.3.1 触发条件（任一命中即触发，无需再讨论）

| 指标 | 阈值 | 观测窗口 |
|---|---|---|
| HTTP 5xx 错误率 | > 1% | 连续 5 分钟 |
| 5xx 错误率 | > 基线 3 倍 | 连续 10 分钟 |
| 核心接口（登录/菜品列表/下单/支付回调）探活 | 连续 3 次失败 | — |
| 支付成功率 | < 95% | 连续 15 分钟 |
| 下单转化率 | 较基线下跌 > 20% | 30 分钟 |
| 出现 P0 缺陷 | 即时 | — |
| 内存持续 > 85% / 频繁 Full GC | 即时 | — |
| 小程序审核被拒 | 不触发线上回滚，改版本重提 | — |

#### 6.3.2 回滚步骤（可执行 · 含预计耗时）

**Step 0 — 决策与通知（0~3 分钟）**

```bash
# 回滚决策人：发布负责人（release-manager）+ 值班运维；5 分钟内必须达成一致
# 同步：团长 / QA / 客服 / 集团 IT
```

**Step 1 — 关闭新功能开关（30 秒，优先于回滚代码）**

```sql
-- 立即关闭新增/变更功能入口，保证回滚期间业务可继续
UPDATE infra_config SET `value`='0', update_time=NOW() WHERE `key` IN
  ('order.entry.enabled','new.coupon.enabled','member.recharge.enabled') AND deleted=0;
```

**Step 2 — 服务端回滚（预计 2~4 分钟）**

```bash
cd /opt/group/deploy

# 2.1 确认当前运行镜像与目标回滚镜像 digest
docker compose -f docker-compose.prod.yml ps
export ROLLBACK_IMAGE="harbor.group.com/order/yshop-server@sha256:<上一稳定版本 digest>"   # 来自 release manifest

# 2.2 灰度组先摘流（Nginx 把 5% 权重切回稳定组）
#     sed 's|server 10.20.10.12:48081 weight=5|# server 10.20.10.12:48081 weight=5|' \
#         nginx/nginx.conf > nginx/nginx.conf.tmp && mv nginx/nginx.conf.tmp nginx/nginx.conf
nginx -t && nginx -s reload

# 2.3 拉取并滚动替换
export SERVER_IMAGE="$ROLLBACK_IMAGE"
docker compose -f docker-compose.prod.yml pull server
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate server

# 2.4 健康检查 + 版本确认
curl -fsS https://api.group.com/actuator/health
curl -fsS https://api.group.com/actuator/info     # 确认 version 回到上一稳定版
```

> 蓝绿模式更快（10 秒级）：把 Nginx upstream 整组切到 blue，`nginx -s reload` 即可，不需重启容器。
> 滚动模式 2~4 分钟；蓝绿模式 10~30 秒。

**Step 3 — 管理后台回滚（预计 3~10 秒）**

```bash
# 目录式发布结构：/data/www/admin/releases/<version>/ + current 软链
ls -l /data/www/admin/current
ln -sfn /data/www/admin/releases/1.0.0 /data/www/admin/current.tmp \
  && mv -Tf /data/www/admin/current.tmp /data/www/admin/current
nginx -t && nginx -s reload
curl -fsS -o /dev/null -w '%{http_code}\n' https://admin.group.com/   # 期望 200
```

**Step 4 — 小程序端（无法物理回滚，用开关 + 版本回退）**

```bash
# 4.1 首选：功能开关（秒级，无需审核）
#     执行 Step 1 的 SQL

# 4.2 若必须回退代码：微信公众平台 → 管理 → 版本管理 → 线上版本 → 回退到上一个版本
#     操作路径：小程序后台「管理」→「版本管理」→ 找到目标旧版本 → 「回退」
#     注意：回退同样需要平台审核/生效时间，**因此不能作为第一手段**
```

**Step 5 — 数据回滚（预计 5~30 分钟，取决于场景）**

```bash
# 场景 A：结构变更（本次首发不应触发，因为只做了 charset 转换）
#   → 手工执行 db/rollback/ 下的 down 脚本
mysql -h 10.20.20.11 -u yshop_migrate -p yixiang-drink_open < db/rollback/V20260101002__xxx.down.sql

# 场景 B：数据被写坏（如 utf8mb4 转换后出现乱码）
#   → 逻辑备份恢复（会丢失备份点之后的业务数据，必须先评估）
gunzip -c backup/yixiang-drink_open_20260101_020000.sql.gz \
  | mysql -h 10.20.20.11 -u yshop_restore -p --default-character-set=utf8mb4 yixiang-drink_open

# 场景 C：精确到误操作时刻 → 用 binlog 做 PITR
#   mysqlbinlog --start-datetime="..." --stop-datetime="..." binlog.000xxx \
#     | mysql -h 10.20.20.11 -u yshop_restore -p
```

**数据兼容性铁律**：
1. 首发所有 DB 变更**只做扩展**（加表、加列、加索引、改字符集）→ **回滚代码时无需回滚数据**；
2. 任何 `DROP COLUMN` / `DROP TABLE` / `NOT NULL` 收紧 / 类型收窄 → **一律推迟到 contract 阶段**；
3. 回滚后必须**保留现场**（日志、binlog position、镜像 digest），供复盘。

**Step 6 — 回滚验证（预计 3 分钟）**

```bash
# 冒烟脚本（deploy/smoke.sh）
curl -fsS https://api.group.com/actuator/health | jq -e '.status=="UP"'
curl -fsS "https://api.group.com/app-api/product/list" | jq -e '.code==0'        # 菜品列表
curl -fsS "https://api.group.com/app-api/store/list"  | jq -e '.code==0'        # 门店列表
# 后台登录 + 商品详情（需带 token，见 smoke.sh 内实现）
# 观测 15 分钟错误率与支付成功率曲线，确认回到基线
```

**Step 7 — 对外沟通**

```
【服务恢复通知模板】
时间：YYYY-MM-DD HH:MM
发生了什么：<一句话描述，如"部分用户下单时出现异常提示">
影响范围：<如"约 X% 的下单请求 / 仅 XX 门店 / 支付未受影响">
当前状态：已恢复，监控指标回到正常水平
补偿方案：<如"受影响且已支付订单由门店人工确认后 24 小时内退款/补发">
后续改进：将在 <日期> 前完成 <措施>，并向各位同步进展
```

客服口径同步在发布前备好（发布单附件）。

### 6.4 灰度放量与观察指标

| 阶段 | 流量 | 时长 | 必看指标 | 决策 |
|---|---|---|---|---|
| G0 内部白名单 | 员工 userId | 30 分钟 | 全链路人工下单 + 支付 | 不通过 → 不继续 |
| G1 | 5% | 2 小时 | 5xx 率、支付成功率、启动耗时、JVM | 达标 → G2 |
| G2 | 20% | 4 小时 | + 下单转化、客诉 | 达标 → G3 |
| G3 | 50% | 24 小时 | + 订单量与基线对比、DB 慢 SQL | 达标 → G4 |
| G4 | 100% | 72 小时 | 全量指标 | 见 §9 |

每阶段记录到发布单《灰度放量记录表》：阶段、时间、放量比例、观察指标实测值、决策人、结论。

---

## 7. 上线检查清单（十项 · 可勾选）

> 执行人逐项打勾并签字；**任一项未通过不得进入生产部署**；如需豁免，须由发布负责人 + 团长书面豁免并写入发布单。

### ① 质量门禁与阻塞项
- [ ] qa-tester 出具「P0 bug = 0、核心链路 100% 通过」的正式结论
- [ ] verify-runner 接口级验证报告通过（登录/菜品/详情/CRUD/订单/统计/导出）
- [ ] §0.2 的 B1–B9 全部关闭并复验
- [ ] `AppStoreProductServiceImpl.getStoreProductById` 的 NPE 已修复并有回归用例
- [ ] CSV 导出接口缺失已确认「不影响首发范围」或已补齐

### ② 配置与密钥（分离 / 无泄露）
- [ ] 已新建 `application-prod.yaml`，其中**不含任何真实密码**，全部为 `${ENV}` 占位符
- [ ] `application.yaml` 中 `yshop.sms-code.begin-code/end-code` **已删除**
- [ ] 生产 profile 下 `yshop.security.mock-enable=false`、`yshop.demo=false`、`yshop.xss.enable=true`、`yshop.access-log.enable=true`
- [ ] `management.endpoints.web.exposure.include` **不等于** `'*'`（应为 `health,info,metrics,prometheus`）
- [ ] Druid 监控台 `stat-view-servlet.enabled=false` 或已设口令 + `allow` 白名单
- [ ] `spring.datasource.druid.wall.config.multi-statement-allow=false`
- [ ] 支付回调 URL 为集团 HTTPS 正式域名（**不含 natapp / http**）
- [ ] `springdoc.api-docs.enabled=false`、`swagger-ui.enabled=false`、`knife4j.enable=false`
- [ ] `yshop.file-path` 指向挂载卷/OSS 适配目录（非 `/Users/...`）
- [ ] **gitleaks 全量扫描 0 未豁免命中**（含 git 历史 `git log -p` 扫描）
- [ ] 全部历史泄露凭据**已轮换**（MyBatis 加密密钥、快递鸟、kd100、微信 appid/secret、justauth secret、腾讯地图 key、百度统计/AK、数据库口令）
- [ ] 仓库 `git filter-repo` 清理完成，协作者已重新 clone
- [ ] 品牌残留已替换（`VITE_APP_TITLE`、`yshop.info`、`pages.json` 标题、隐私政策主体）

### ③ 依赖与中间件
- [ ] 生产 MySQL = **8.4.11**（或集团标准版本），`innodb_file_per_table=ON`，`binlog_format=ROW` 已开启
- [ ] 生产 Redis = **8.10.3**，`requirepass` 已设置，绑定内网，禁公网
- [ ] 生产数据库账号为专用账号（`yshop_app` / `yshop_migrate` / `yshop_backup`），**非 root**
- [ ] 连接池参数与规格匹配（`max-active` ≤ MySQL `max_connections` 预留）
- [ ] Docker 镜像版本钉死（`mysql:8.4.11`、`redis:8.10.3-alpine`、`eclipse-temurin:21-jre`）
- [ ] 后端运行时 JRE 版本 ≥ 编译字节码版本（断言脚本已过）
- [ ] 容器以非 root（uid 10001）运行；`/data/logs`、`/data/file` 卷已挂载且可写

### ④ 证书 / 签名 / 域名白名单
- [ ] 域名 `api.group.com` / `admin.group.com` / `h5.group.com` **ICP 备案已生效**，备案主体 = 集团主体
- [ ] HTTPS 证书在有效期内，**证书链完整**（`openssl s_client` 校验 ≥2 张证书）
- [ ] 证书覆盖所有对外域名（SAN 包含 `*.group.com` 或逐个列出）
- [ ] 证书到期监控已配置（提前 30 天 / 7 天告警）
- [ ] TLS 1.0/1.1 已禁用，HSTS 已配置
- [ ] 小程序后台 **request / uploadFile / downloadFile / socket** 合法域名**一次配齐**且已生效
- [ ] 小程序 `manifest.json` 的 `mp-weixin.appid` = **集团正式 appid**（非测试号 `wx001e2dc50bf532df`）
- [ ] 小程序 `setting.urlCheck = true`
- [ ] `miniprogram-ci` 私钥存 CI 变量 / KMS，**不入代码库**；`project.config.json` 无敏感信息
- [ ] 微信支付 API 证书（`apiclient_cert.p12` / `apiclient_key.pem`）与平台证书已配，存 KMS
- [ ] 支付回调地址已在商户平台配置且**公网可达**（外网实测 curl 通）
- [ ] 微信支付回调**幂等**验证通过（重复回调不重复发货/退款）

### ⑤ 账号与资质
- [ ] 小程序**企业主体**注册完成并通过微信认证
- [ ] 服务类目 = 餐饮点餐相关类目，**类目名称与官方文档核对无误**
- [ ] 《食品经营许可证》有效且主体/范围匹配
- [ ] 门店资质已在管理端维护
- [ ] 微信支付商户号已开通「JSAPI 支付」，AppID 授权完成
- [ ] 管理后台 3 个种子账号（admin / yshop / xixiang001）**密码已重置**为强口令且绑定集团人员
- [ ] 演示账号（供小程序审核员使用）已创建，并写入审核备注
- [ ] 短信/邮件通道（集团通知）已配置并实测发送成功
- [ ] 集团技术管理员微信 = 法定代表人的备份联系人已登记

### ⑥ 数据与数据库
- [ ] 全量逻辑备份已完成并**验证可恢复**（`gzip -t` + 表数量 ≥94）
- [ ] binlog 已开启（`ROW` 格式），备份保留策略 ≥7 天
- [ ] utf8mb3 → utf8mb4 转换**全部完成**，校验查询返回 0 行
- [ ] 转换前后行数一致（抽样比对关键表 `yshop_store_product` / `yshop_store_order`）
- [ ] Flyway 已引入并完成基线（`flyway_schema_history` 有 baseline 记录），`clean-disabled=true`
- [ ] 所有迁移脚本有对应的 `db/rollback/*.down.sql`
- [ ] 本次发布**无任何删除性** DB 变更（`DROP`/`NOT NULL` 收紧/类型收窄）
- [ ] 生产种子数据脚本为幂等 upsert，可重复执行
- [ ] 敏感数据（手机号、地址）已确认存储与展示符合合规要求（展示脱敏）

### ⑦ 制品与可追溯性
- [ ] Git tag `v1.0.0` 已打并推送，tag 指向发布 commit
- [ ] `release-1.0.0.manifest.json` 已生成（版本 / commit / 各制品 sha256 / 镜像 digest）
- [ ] 生产运行的镜像以 **digest** 锁定，与 manifest 完全一致
- [ ] 上一稳定版本制品**仍可拉取**（Harbor 未清理、tag 未被覆盖）
- [ ] 管理后台产物 `dist-prod` 与小程序产物 `unpackage/dist/build/mp-weixin` 校验通过
- [ ] 生产运行的包来自 CI 产出（**无本地手工打包**）
- [ ] 发布材料归档路径已创建（发布单 / 制品记录 / 审核记录 / 配置变更 / 观察报告）

### ⑧ 监控与告警
- [ ] `/actuator/health`、`/actuator/prometheus` 已接入监控，**且不暴露在公网**
- [ ] 告警已接入：错误率（5xx）、响应时间 P99、JVM 内存/GC、线程池、DB 连接池、慢 SQL、Redis 内存
- [ ] 业务告警：下单成功率、支付成功率、订单创建量环比
- [ ] 日志采集已接入（`logging.file.name=/data/logs/yshop-server.log`），容器日志驱动 `json-file` + 轮转
- [ ] 告警静默期已核对（发布窗口不因历史噪声误触发）
- [ ] 证书到期、磁盘水位、备份失败监控已配置
- [ ] 监控与告警责任人已明确并处于待命状态

### ⑨ 回滚方案（可执行 / 已走查）
- [ ] 回滚触发条件已写入发布单，责任人明确（发布负责人 + 值班运维）
- [ ] 回滚脚本 `deploy/rollback.sh` 已通过 shellcheck，并在**预发环境实际演练过**
- [ ] 上一稳定版本镜像 digest / 管理后台版本目录 / 小程序版本号已记录在案
- [ ] 数据回滚路径已确认（down 脚本 / 逻辑备份 / binlog PITR），并演练过恢复
- [ ] 回滚预计耗时已评估（服务端 2~4 分钟 / 后台 10~30 秒 / 数据 5~30 分钟）
- [ ] 功能开关（`infra_config`）回滚路径已验证
- [ ] 用户公告模板、客服口径、事故说明模板已备好
- [ ] 回滚不依赖「本地开发同学的手工操作」（全部脚本化，可由值班运维执行）

### ⑩ 发布窗口 / 灰度 / 应急
- [ ] 发布窗口：**工作日 10:00–11:30**，避开业务高峰（午餐 11:00–13:30 / 晚餐 17:00–19:30 —— **订餐场景高峰必须避开**）
- [ ] 避开节假日与小程序审核积压期
- [ ] 灰度策略已定：5% → 20% → 50% → 100%，每阶段观察时长与推进条件已写入发布单
- [ ] 小程序提审排期已预留「被拒重提一次」的时间（1~7 天 + 1~7 天）
- [ ] 发布单已于**前 1 个工作日**发出并经相关方确认
- [ ] 应急联系人全程待命：发布负责人、QA、运维、客服、后端 DBA、集团 IT
- [ ] 上线后 72 小时观察计划已排班（§9）
- [ ] 未通过项的豁免说明已书面记录（谁豁免、为什么、风险如何兜底）

---

## 8. 风险提示

### 风险 1：代码库历史密钥泄露，生产上线即被打

- **【影响范围】** 全量 —— MySQL/Redis 口令、微信小程序与公众号 secret、微信支付相关凭据、MyBatis 配置加密密钥、快递鸟/kd100 第三方 key、justauth（钉钉/企微）secret、腾讯地图 key、百度统计/AK。
- **【触发条件】** 代码库已推送到任何非受控远端（gitee/GitHub 公开仓库、他人 fork、CI 日志），或集团安全扫描发现历史提交中的明文凭据。
- **【应对措施】** ① 全部凭据**立即轮换**（不是"上线后再换"，因为泄露已发生）；② `git filter-repo` 清理历史 + 通知协作者重新 clone + 强制 `git push --force` 到受控远端；③ 引入 gitleaks 作为 MR 卡点（§5.2）；④ 长期方案：密钥全部走 KMS/环境变量，代码库只保留占位符（§1.4.2）；⑤ 安排一次专项安全评审，核查第三方平台侧是否有异常调用（微信支付 API 调用记录、短信发送量）。

### 风险 2：小程序类目/资质不足被拒，首发延期

- **【影响范围】** 小程序端全量发布（服务端已上线但无客户端入口，等于"无人可用"）。
- **【触发条件】** 类目与实际业务不符；《食品经营许可证》主体与小程序主体不一致或经营范围不含餐饮；材料在审核期被驳回。
- **【应对措施】** ① 提审前用「类目-资质对照表」逐条自检，主体/许可证/门店三处主体名称必须一致；② 提审备注中提供演示账号，让审核员能实际下单；③ 排期预留 **被拒重提一次**的时间（首审 1~7 天 + 重提 1~7 天）；④ 同期推进 H5 版作为兜底入口（`h5.group.com`），小程序被拒时至少保证员工可点餐；⑤ 被拒台账记录版本/原因/处理，同类问题不得二次出现。

### 风险 3：微信支付回调不通或签名校验失败 → 用户能下单但付不了

- **【影响范围】** 全部下单支付链路；转化率直接归零，是本项目最致命的功能性风险。
- **【触发条件】** 回调地址仍指向仓库里的 `http://yshop.natapp1.cc`（内网穿透，会断）；安全组未放行；APIv3 密钥/平台证书过期或配置错；HTTPS 证书链不完整导致微信服务器验签失败；回调未做幂等导致重复发货。
- **【应对措施】** ① 发布前用**外网**实测回调可达（`curl -X POST https://api.group.com/app-api/order/notify/order` 应返回业务错误而非超时/连接拒绝）；② 商户平台回调白名单与代码配置**双向一致**；③ 上线前跑「0.01 元真金」端到端：下单→支付→回调→订单状态→退款；④ 幂等专项用例（重复回调 3 次，订单只发货一次）；⑤ 灰度阶段把「支付成功率」设为**硬门禁**（<95% 立即回滚），因为支付问题无法靠用户重试解决。

### 风险 4：utf8mb3→utf8mb4 转换触发 MDL 锁，生产库「假死」

- **【影响范围】** 被转换表相关的全部读写；MDL 排队会连带阻塞该表的所有查询，表现为「数据库整体卡住」。
- **【触发条件】** 长事务未提交阻塞 DDL；表含 FULLTEXT 索引导致只能 COPY 算法；大表（>1GB）重建耗时超预期；旧行格式下索引键超限报错中断。
- **【应对措施】** ① 执行前跑 §3.3.1 四条检查 SQL，产出影响评估表；② `SET SESSION lock_wait_timeout=10` 快速失败，避免长时间排队拖垮全库；③ 大表一律走 `pt-online-schema-change`（chunk 1000 + 限流）；④ 逐表、低峰期（**避开 11:00–13:30 / 17:00–19:30 订餐高峰**）执行，每张表转换后立即校验行数与抽样数据；⑤ 转换前必须完成可恢复的全量备份并验证。

### 风险 5：NPE 与"不存在的商品 id"缺陷在生产暴露，触发小程序端报错

- **【影响范围】** 商品详情页；小程序端白屏/报错；埋点异常；审核期间被体验版用户遇到。
- **【触发条件】** 用户分享的商品链接指向已下架/已删除商品；数据迁移后出现 id 悬空引用；爬虫批量探测不存在的 id（`/app-api/product/detail?id=999999` → 500）。
- **【应对措施】** ① **上线前修复**（`AppStoreProductServiceImpl` L185-187 增加 null 判断，返回 `CommonResult.error(PRODUCT_NOT_EXISTS)`）——这是 B6，属发布阻塞项；② 小程序端对详情接口失败做友好兜底页，不白屏；③ 灰度阶段监控 404/500 比例；④ 后端对不存在的 id 返回 404 而非 500（500 会被错误率告警放大，掩盖真实问题）。

### 风险 6：上线当天撞上订餐高峰或微信审核积压，双向挤压

- **【影响范围】** 发布窗口延长、客诉上升；小程序侧延期但服务端已变更，导致「客户端旧版 + 服务端新版」的兼容窗口拉长。
- **【触发条件】** 发布窗口与 11:00–13:30 / 17:00–19:30 重叠；提交审核时点处于微信审核积压期；节假日排期未避开。
- **【应对措施】** ① 发布窗口固定为**工作日 10:00–11:30**（订餐场景独有的高峰约束，必须写入发布单）；② 服务端接口保持向后兼容 ≥2 个版本，即使小程序延迟上线也不受影响（§4.6）；③ 小程序提审与后端生产发布**解耦**：后端按自己的窗口发布，小程序审核通过后随时发；④ 灰度阶段遇高峰立即暂停放量（不需回滚，只暂停）；⑤ 版本兼容性用 `infra_config` 开关兜底。

### 风险 7：首版小程序把上游"多商家/虚拟权益"功能暴露，触发违规或审核驳回

- **【影响范围】** 小程序审核结论；严重时小程序被下架，已发版用户无法访问。
- **【触发条件】** yshop 默认带 score（积分兑换）、coupon、marketing（营销）、member（会员等级/储值）、express（快递配送）等模块；若管理端菜单未裁剪，前台可能出现"积分兑换""余额充值""快递配送"入口；多商家入驻/分销入口也易被判"平台类目"而资质不足。
- **【应对措施】** ① 上线版本**裁剪菜单**：关闭积分商城、余额充值、快递配送、多商家入驻、分销/拼团入口；② 积分仅作消费累积展示，不做可兑换虚拟权益（§4.5 虚拟支付专项）；③ 提审前用**体验版真机逐页走查**，确保每个可见页面功能完整、无空白页/占位；④ 管理端 `system_menu` 用 `deleted`/`visible` 控制，避免前台渲染出半成品模块；⑤ 保留「关闭虚拟入口」的 DB 变更脚本，随时可执行。

### 风险 8：生产编排复用仓库失效的 `docker-compose.yml`，上线即起不来

- **【影响范围】** 生产后端与管理后台容器启动失败；发布窗口被拖长。
- **【触发条件】** 直接使用 `script/docker/docker-compose.yml`：其 `build.context: ./yshop-server/` 相对路径指向不存在的目录；`admin` 服务引用不存在的 `./yshop-ui-admin`；`SPRING_PROFILES_ACTIVE: local` 监听 48081 但 `ports` 映射 `48080:48080`；`mysql:8`/`redis:6-alpine` 版本与实测 8.4.11/8.10.3 不符；`.env` 中 root 口令为 `123456`。
- **【应对措施】** ① 新建独立 `deploy/` 目录重写生产编排（§5.3），全部版本钉死、密钥走环境变量；② 统一端口（生产 `SERVER_PORT=48081`，`Dockerfile EXPOSE 48081`，Nginx upstream 对齐）；③ **预发环境用同一套编排文件跑通**，生产只换镜像 digest 与变量；④ 编排文件进版本库，变更走 MR 评审；⑤ 部署脚本幂等且带 `docker compose config` 校验前置。

---

## 9. 上线后 72 小时观察

| 时点 | 检查项 | 责任人 | 阈值 |
|---|---|---|---|
| T+30min | 5xx 错误率、支付成功率、JVM 内存/GC、启动日志异常（OOM/连接池耗尽） | 运维 | 错误率 <1%，支付 ≥99% |
| T+2h | 灰度阶段指标复核；告警静默期核对；小程序/后台无新增异常反馈 | 运维 + QA | 同上 |
| T+6h | 慢 SQL 列表（`performance_schema`）、订单量与基线对比、客诉量 | 后端 + DBA | 无 top10 慢 SQL 恶化 |
| T+24h | 业务指标（订单/注册/活跃/复购）无异常波动；客诉量正常；utf8mb4 抽样数据无乱码 | 产品 + QA | 与基线偏差 <20% |
| T+48h | 证书/域名/配额余量；备份任务成功率；容量水位 | 运维 | 备份成功率 100% |
| T+72h | **发布复盘**：清单执行偏差、告警误报调优、用户反馈 Top3 进需求池、材料归档 | 发布负责人 + 团长 | 材料 24h 内归档，保留 ≥1 年 |

**归档材料清单**（缺一视为发布未完成）：
发布单（含清单执行结果与豁免说明）、制品记录（版本/tag/commit/sha256/digest + 上一稳定版位置）、审核记录（提审时间线 + 被拒台账）、配置变更记录（密钥轮换/白名单/证书）、灰度放量记录表、72 小时观察报告、回滚演练记录。

---

## 10. 交付给下游的接口

- **→ 运维守护师（监控告警与应急衔接）**：
  - 生产部署形态：后端 2 副本 × 4C8G（滚动 + 5% 灰度切流），管理后台 Nginx + CDN 版本目录，小程序走微信后台分阶段发布；MySQL 8.4.11 主从 + 只读、Redis 8.10.3 托管、OSS 存图。
  - 告警需求：5xx 错误率（>1%/5min）、P99 延迟、JVM 内存（>85%）、GC 频率、DB 连接池、慢 SQL、**支付成功率（<95%/15min）**、下单成功率、证书到期（30d/7d）、磁盘水位、备份失败。
  - 回滚预案与发布窗口：见 §6.3；发布窗口工作日 10:00–11:30（避开订餐高峰）；应急联系人与值班表见发布单。
  - 健康检查端点：`/actuator/health/readiness`（内网）、`/actuator/prometheus`（内网）。
- **→ 团长 / 产品**：审核风险已提前告知（§4.1–4.5），排期需包含「企业认证 + 类目审核 + 小程序审核（含被拒重提）」；首发阻塞项 9 项见 §0.2。

---

*本方案基于主控实测结果与仓库真实文件路径编写；平台规则类信息以官方最新文档为准。上线前请核对本方案与实际生产环境（云厂商、地域、域名、集团主体信息）的差异。*

[上线发布方案]
