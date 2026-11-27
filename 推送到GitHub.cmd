@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  推送 life-circle-accessibility 到 GitHub
echo  首次运行会弹出浏览器，用 oliveriolikescoding 登录授权一次即可
echo ============================================================
echo.

"C:\Program Files\Git\cmd\git.exe" push -u origin main --force
if errorlevel 1 (
  echo.
  echo [失败] 常见原因：登录弹窗被关掉 / 网络不通。
  echo 重新双击本文件再试一次。
) else (
  echo.
  echo [成功] 前往 https://github.com/oliveriolikescoding/life-circle-accessibility
  echo 刷新页面，图片与 data 就在仓库里了。
)

echo.
pause
