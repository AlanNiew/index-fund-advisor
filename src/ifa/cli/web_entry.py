"""ifa-web 命令的入口点。

直接通过 subprocess 调用 streamlit，避免 exe 环境下模块路径问题。

注意：Web 界面不在 wheel 内（web/app.py 位于仓库根，只有 ifa 包会被打包），所以
全局安装 / wheel 安装后必须给出可操作报错，而不是让 streamlit 报「找不到文件」。
"""

import os
import subprocess
import sys


def main():
    # 本模块位于 src/ifa/cli/，项目根在三层目录之上。
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    src_dir = os.path.join(project_root, "src")
    app_path = os.path.join(project_root, "web", "app.py")

    if not os.path.exists(app_path):
        sys.stderr.write(
            "ifa-web 需要仓库检出：未找到 web/app.py。\n"
            "wheel / 全局安装只包含 ifa 包（CLI 与 MCP）；Web 界面请克隆仓库后运行 ifa-web。\n"
        )
        sys.exit(1)

    env = os.environ.copy()
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "-m", "streamlit", "run", app_path],
        env=env,
        cwd=project_root,
    )
    sys.exit(result.returncode)
