// 本地演示配置（2026-11-03 改造：IP 无关化）
// 说明：
//  1) 笔记本演示模式下本机局域网 IP 每天都可能变化，写死 IP 会让小程序端次日失效。
//     改用 macOS 的 Bonjour/mDNS 主机名（*.local），它永远指向本机「当前」IP，
//     一次配置、长期有效，换 Wi-Fi / 重新拨号都不用再改。
//  2) 真机预览 / 微信开发者工具只要与本机在同一网络即可经 mDNS 解析到本机，
//     后端已监听 0.0.0.0，故 http://<主机名>.local:48081 始终可达。
//  3) 工具内「不校验合法域名」开启后，可直接用 http + 主机名，无需配置 request 合法域名。
//  注意：下面主机名由 sync_ip.py 按本机 `hostname` 自动注入，请勿手填 IP。
const LAN_API_URL = 'http://TristandeMacBook-Pro.local:48081/app-api'

const DEV_API_URL = LAN_API_URL
const PROD_API_URL = 'https://apidc.yixiang.co/app-api'

// #ifdef APP-PLUS || H5 || MP-WEIXIN
// 本地演示固定走局域网地址：微信开发者工具编译时 NODE_ENV 通常为 production，
// 若按原三元判断会误连线上 https://apidc.yixiang.co，故演示期统一使用 LAN_API_URL。
// 恢复线上环境时把下面这行改回：
//   process.env.NODE_ENV === 'development' ? DEV_API_URL : PROD_API_URL
export const VUE_APP_API_URL = LAN_API_URL
// #endif

export const VUE_APP_RESOURCES_URL = 'https://h5.yixiang.co/static'
export const VUE_APP_UPLOAD_URL = VUE_APP_API_URL + '/infra/file/upload'
export const APP_ID = 'wxdbdbc123c8c30b45'

const orderListStatus = {}

// -1:申请退款
// -2:退货成功
// 0:待发货；
// 1:待收货；
// 2:已收货；
// 3:待评价；
// -1:已退款

export const orderStatus = {
  0: '未支付',
  1: '待发货',
  2: '待收货',
  3: '待评价',
  4: '已完成',
  5: '退款中',
  6: '已退款',
  7: '退款',
}

export const orderReStatus = {
  0: '等待买家付款',
  // 1: '等待卖家发货',
  1: '卖家已发货',
  2: '等待买家待评价',
  3: '订单已完成',
  4: '订单退款中',
  5: '订单已退款',
  6: '退款已完成',
}

// export const orderReStatus = {
//   0: '等待买家付款',
//   1: '等待卖家发货',
//   2: '卖家已发货',
//   3: '等待买家待评价',
//   4: '订单已完成',
//   5: '订单退款中',
//   6: '订单已退款',
//   7: '退款已完成',
// }
