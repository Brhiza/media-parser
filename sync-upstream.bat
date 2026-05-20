@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ============================================
echo  从上游 ucmao/media-parser 同步最新代码
echo ============================================
echo.

echo [1/4] 检查本地是否有未提交的改动...
git diff --quiet
if errorlevel 1 (
    echo.
    echo [错误] 本地有未提交的改动，请先 git commit 或 git stash 后重试。
    git status -s
    pause
    exit /b 1
)
git diff --cached --quiet
if errorlevel 1 (
    echo.
    echo [错误] 暂存区有未提交的改动，请先 git commit 后重试。
    pause
    exit /b 1
)
echo     工作区干净。

echo.
echo [2/4] 拉取上游最新提交...
git fetch upstream
if errorlevel 1 (
    echo [错误] 拉取失败，请检查网络或 upstream remote 设置。
    pause
    exit /b 1
)

echo.
echo [3/4] 显示上游新增提交：
git log --oneline HEAD..upstream/starter
git log --oneline HEAD..upstream/starter >nul 2>&1
for /f %%i in ('git rev-list --count HEAD..upstream/starter') do set NEW=%%i
if "%NEW%"=="0" (
    echo.
    echo 已是最新，无需更新。
    pause
    exit /b 0
)
echo.
echo     共 %NEW% 个新提交。

echo.
echo [4/4] 合并到当前分支（.gitattributes 已配置：app.py / landing.html 保留本地版本）...
git merge upstream/starter --no-edit
if errorlevel 1 (
    echo.
    echo [警告] 合并出现冲突，请打开 VS Code 或 git status 查看，手动解决后执行：
    echo     git add ^<冲突文件^>
    echo     git commit
    pause
    exit /b 1
)

echo.
echo ============================================
echo  同步完成！记得重新构建容器：
echo      docker-compose up -d --build
echo  并访问 http://localhost:8051 测试一次解析。
echo ============================================
pause
