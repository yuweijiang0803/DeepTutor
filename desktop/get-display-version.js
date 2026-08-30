// 桌面端"显示版本"：把 semver 更新版本（1.6.100、1.6.101…）映射成
// 基于上游的自定义格式（1.6.0.1、1.6.0.2…），供 NEXT_PUBLIC_APP_VERSION 注入。
//
// 规则：MAJOR.MINOR.PATCH → MAJOR.MINOR.0.(PATCH - 99)
//   1.6.100 → 1.6.0.1
//   1.6.101 → 1.6.0.2
// 这样更新判断用严格 semver（自动更新正常），左下角显示用户想要的格式，
// 且不会和上游小 patch 版本（1.6.1、1.6.2…）混淆。
const raw = process.env.npm_package_version || process.env.npm_config_package_version || '';
const parts = raw.split('.').map((p) => parseInt(p, 10));
if (parts.length >= 3 && !Number.isNaN(parts[0]) && !Number.isNaN(parts[1]) && !Number.isNaN(parts[2])) {
  process.stdout.write(`${parts[0]}.${parts[1]}.0.${parts[2] - 99}`);
} else {
  process.stdout.write(raw || '1.6.0.1');
}
