# cli/web_entry.py
"""ifa-web 命令的入口点。

直接通过 subprocess 调用 streamlit，避免 exe 环境下模块路径问题。
"""

import os
import subprocess
import sys


def main():
    project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    src_dir = os.path.join(project_root, "src")
    app_path = os.path.join(project_root, "web", "app.py")

    env = os.environ.copy()
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "-m", "streamlit", "run", app_path],
        env=env,
        cwd=project_root,
    )
    sys.exit(result.returncode)
