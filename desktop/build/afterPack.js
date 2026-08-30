// afterPack: 对打包出的 .app 做 ad-hoc 代码签名（无需开发者证书）。
// electron-updater 的 mac 更新（Squirrel.Mac）要求 app 有有效代码签名——
// 未签名会报 "Code signature did not pass validation"。ad-hoc 签名
// （codesign - 本机身份）即可让 Squirrel 校验通过，代价是无法跨机器验证身份
// （仅适用于内测/内部分发；正式上架需真实 Developer ID 签名 + 公证）。
"use strict";

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

exports.default = async function afterPack(context) {
  const { appOutDir, electronPlatformName } = context;
  if (electronPlatformName !== 'darwin') return;

  const appName = context.packager.appInfo.productFilename || 'DeepTutor';
  const appPath = path.join(appOutDir, `${appName}.app`);
  if (!fs.existsSync(appPath)) {
    console.log('[afterPack] app not found, skip ad-hoc sign:', appPath);
    return;
  }

  try {
    console.log('[afterPack] ad-hoc signing:', appPath);
    execSync(`codesign --force --deep --sign - "${appPath}"`, {
      stdio: 'inherit',
    });
    execSync(`codesign --verify --deep --strict "${appPath}"`, {
      stdio: 'inherit',
    });
    console.log('[afterPack] ad-hoc signature verified');
  } catch (err) {
    console.log('[afterPack] ad-hoc signing failed:', err.message);
    throw err;
  }
};
